from typing import Dict, Any, List, Optional
import numpy as np
from fastapi import HTTPException

from app.schemas import (
    DamageCurvePoint,
    DamageConfigResponse,
    DamageScenarioRequest,
    DamageScenarioResponse,
    TotalEstimates,
    AssetCountSummary,
    CategoryDamageResult,
)
from app.vector_service import get_exposure_assets

DEFAULT_ASSUMED_DEPTH_UNIT = "assumed meters (unverified)"
DEFAULT_CURRENCY_LABEL = "INR (₹)"
DEFAULT_SENSITIVITY_PERCENTAGE = 20.0

DEFAULT_REPLACEMENT_VALUES: Dict[str, float] = {
    "building": 2500000.0,      # ₹25 Lakhs
    "healthcare": 15000000.0,   # ₹1.5 Crores
    "education": 8000000.0,     # ₹80 Lakhs
    "emergency": 10000000.0,    # ₹1.0 Crore
    "settlement": 5000000.0,    # ₹50 Lakhs
    "transport": 3000000.0,     # ₹30 Lakhs
    "other": 1000000.0,         # ₹10 Lakhs
}

DEFAULT_DEPTH_DAMAGE_CURVE: List[DamageCurvePoint] = [
    DamageCurvePoint(depth=0.0, damage_ratio=0.0),
    DamageCurvePoint(depth=0.5, damage_ratio=0.15),
    DamageCurvePoint(depth=1.5, damage_ratio=0.40),
    DamageCurvePoint(depth=3.0, damage_ratio=0.70),
    DamageCurvePoint(depth=6.0, damage_ratio=1.00),
]

DISCLAIMER_TEXT = (
    "Illustrative scenario only — not an official loss estimate, validated risk assessment, or emergency decision."
)
METHODOLOGY_TEXT = (
    "Piecewise linear depth–damage interpolation applied to preliminary representative point screening depths. "
    "Road networks and population/casualties are intentionally excluded."
)


def get_default_damage_config() -> DamageConfigResponse:
    """Return default editable illustrative damage scenario configuration."""
    return DamageConfigResponse(
        assumed_depth_unit=DEFAULT_ASSUMED_DEPTH_UNIT,
        currency_label=DEFAULT_CURRENCY_LABEL,
        replacement_values=dict(DEFAULT_REPLACEMENT_VALUES),
        depth_damage_curve=list(DEFAULT_DEPTH_DAMAGE_CURVE),
        sensitivity_percentage=DEFAULT_SENSITIVITY_PERCENTAGE,
        disclaimer=DISCLAIMER_TEXT,
        methodology=METHODOLOGY_TEXT,
    )


def validate_damage_request(request: DamageScenarioRequest) -> None:
    """
    Validate input parameters according to requirements:
    1. Acknowledgment boolean must be True
    2. Replacement values must be non-negative
    3. Sensitivity percentage between 0 and 100
    4. Curve points must have >= 2 items, strictly ascending depth, monotonic damage ratios in [0, 1]
    5. Size limits to avoid memory/DOS issues
    """
    if not request.acknowledge_unverified_inputs:
        raise HTTPException(
            status_code=422,
            detail=(
                "Estimation rejected: requires explicit user acknowledgement of illustrative assumptions "
                "and unverified sample inputs."
            ),
        )

    # Validate replacement values
    if not request.replacement_values or len(request.replacement_values) > 50:
        raise HTTPException(status_code=422, detail="Replacement values mapping must have between 1 and 50 categories.")

    for cat, val in request.replacement_values.items():
        if val is None or val < 0.0 or np.isnan(val) or np.isinf(val):
            raise HTTPException(
                status_code=422,
                detail=f"Replacement value for category '{cat}' must be a finite non-negative number.",
            )

    # Validate sensitivity percentage
    if request.sensitivity_percentage < 0.0 or request.sensitivity_percentage > 100.0:
        raise HTTPException(
            status_code=422,
            detail="Sensitivity percentage must be between 0.0% and 100.0%.",
        )

    # Validate depth-damage curve
    curve = request.depth_damage_curve
    if not curve or len(curve) < 2 or len(curve) > 100:
        raise HTTPException(
            status_code=422,
            detail="Depth-damage curve must contain between 2 and 100 control points.",
        )

    prev_depth = -1.0
    prev_ratio = -1.0
    for idx, pt in enumerate(curve):
        if pt.depth < 0.0:
            raise HTTPException(
                status_code=422,
                detail=f"Curve point {idx}: depth must be non-negative (got {pt.depth}).",
            )
        if pt.depth <= prev_depth:
            raise HTTPException(
                status_code=422,
                detail=f"Curve points must have strictly ascending depths. Point {idx} (depth={pt.depth}) <= previous (depth={prev_depth}).",
            )
        if pt.damage_ratio < 0.0 or pt.damage_ratio > 1.0:
            raise HTTPException(
                status_code=422,
                detail=f"Curve point {idx}: damage_ratio must be in [0.0, 1.0] (got {pt.damage_ratio}).",
            )
        if pt.damage_ratio < prev_ratio:
            raise HTTPException(
                status_code=422,
                detail=f"Curve points must be monotonic non-decreasing in damage_ratio. Point {idx} (ratio={pt.damage_ratio}) < previous (ratio={prev_ratio}).",
            )
        prev_depth = pt.depth
        prev_ratio = pt.damage_ratio


def interpolate_damage_ratio(depth: float, curve: List[DamageCurvePoint]) -> float:
    """Interpolate damage ratio from piecewise linear depth-damage curve."""
    if depth <= 0.0:
        return 0.0

    curve_depths = [pt.depth for pt in curve]
    curve_ratios = [pt.damage_ratio for pt in curve]

    ratio = float(np.interp(depth, curve_depths, curve_ratios))
    return max(0.0, min(1.0, ratio))


def compute_damage_scenario(request: DamageScenarioRequest) -> DamageScenarioResponse:
    """
    Calculate illustrative damage scenario estimates from Phase 6 screened assets:
    - Interpolates damage ratio from asset depth
    - Computes category and total illustrative base loss
    - Applies sensitivity bounds (low/high)
    - Returns comprehensive breakdown, counts, methodology, and warnings
    """
    validate_damage_request(request)

    assets_geojson = get_exposure_assets()
    features = assets_geojson.get("features", [])

    total_assets = len(features)
    assessed_assets = 0
    screening_positive_assets = 0
    not_exposed_assets = 0
    not_assessed_assets = 0

    # Ensure all standard categories exist in results
    standard_categories = [
        "building",
        "healthcare",
        "education",
        "emergency",
        "settlement",
        "transport",
        "other",
    ]
    # Add any extra categories present in user replacement_values
    all_categories = list(dict.fromkeys(standard_categories + list(request.replacement_values.keys())))

    category_stats = {
        cat: {
            "total_count": 0,
            "screening_positive_count": 0,
            "not_exposed_count": 0,
            "not_assessed_count": 0,
            "unit_replacement_value": request.replacement_values.get(cat, request.replacement_values.get("other", 1000000.0)),
            "base_loss": 0.0,
        }
        for cat in all_categories
    }

    grand_base_loss = 0.0

    for feat in features:
        props = feat.get("properties") or {}
        cat = props.get("category", "other")
        if cat not in category_stats:
            cat = "other"

        category_stats[cat]["total_count"] += 1

        assessed = bool(props.get("assessed", False))
        exposed = bool(props.get("exposed", False))
        depth = props.get("depth_value")

        if assessed:
            assessed_assets += 1
            if exposed and depth is not None and depth > 0.0:
                screening_positive_assets += 1
                category_stats[cat]["screening_positive_count"] += 1

                damage_ratio = interpolate_damage_ratio(depth, request.depth_damage_curve)
                unit_val = category_stats[cat]["unit_replacement_value"]
                asset_loss = damage_ratio * unit_val

                category_stats[cat]["base_loss"] += asset_loss
                grand_base_loss += asset_loss
            else:
                not_exposed_assets += 1
                category_stats[cat]["not_exposed_count"] += 1
        else:
            not_assessed_assets += 1
            category_stats[cat]["not_assessed_count"] += 1

    # Sensitivity calculation
    sens_factor = request.sensitivity_percentage / 100.0
    low_grand_loss = max(0.0, grand_base_loss * (1.0 - sens_factor))
    high_grand_loss = grand_base_loss * (1.0 + sens_factor)

    by_category_response: Dict[str, CategoryDamageResult] = {}
    for cat, data in category_stats.items():
        base_cat_loss = round(data["base_loss"], 2)
        low_cat_loss = round(max(0.0, base_cat_loss * (1.0 - sens_factor)), 2)
        high_cat_loss = round(base_cat_loss * (1.0 + sens_factor), 2)

        by_category_response[cat] = CategoryDamageResult(
            total_count=data["total_count"],
            screening_positive_count=data["screening_positive_count"],
            not_exposed_count=data["not_exposed_count"],
            not_assessed_count=data["not_assessed_count"],
            unit_replacement_value=round(data["unit_replacement_value"], 2),
            base_loss=base_cat_loss,
            low_loss=low_cat_loss,
            high_loss=high_cat_loss,
        )

    warnings = [
        "Illustrative estimation based on unverified sample raster depths and user-configured unit values.",
        "Not an engineering-grade or actuarial damage analysis.",
        "Road infrastructure network and human population/casualties are strictly excluded from monetary estimation.",
    ]

    return DamageScenarioResponse(
        disclaimer=DISCLAIMER_TEXT,
        methodology=METHODOLOGY_TEXT,
        currency_label=request.currency_label or DEFAULT_CURRENCY_LABEL,
        assumed_depth_unit=request.assumed_depth_unit or DEFAULT_ASSUMED_DEPTH_UNIT,
        sensitivity_percentage=request.sensitivity_percentage,
        total_estimates=TotalEstimates(
            base_loss=round(grand_base_loss, 2),
            low_loss=round(low_grand_loss, 2),
            high_loss=round(high_grand_loss, 2),
        ),
        asset_counts=AssetCountSummary(
            total_assets=total_assets,
            assessed_assets=assessed_assets,
            screening_positive_assets=screening_positive_assets,
            not_exposed_assets=not_exposed_assets,
            not_assessed_assets=not_assessed_assets,
        ),
        by_category=by_category_response,
        warnings=warnings,
    )

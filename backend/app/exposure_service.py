"""
exposure_service.py - Phase 22: Population, LULC, Infrastructure Exposure & Vulnerability Assessment

Provides project-scoped, scientifically honest exposure and vulnerability analysis:
- Standardized hazard contract across ANUGA, Delft3D FM, PySPH, and legacy Hidkal
- Population count conservation across configurable depth bands
- Polygon building footprint zonal overlap and usage categorization
- Road network segmentation and metric affected length calculation
- Critical infrastructure classification with strict provenance and unknown retention
- Categorical nearest-neighbour LULC flooded area calculation
- Clear separation of exposure vs. vulnerability / damage (zero fabricated rupees)
- Modelled arrival-time windowing
- Transparent decision-support priority index and hotspot identification
- Persistent storage under runtime/dam_projects/{project_id}/exposure_runs/{exposure_run_id}/
"""

import json
import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from pyproj import Transformer
from shapely.geometry import shape, Point, LineString, Polygon, MultiPolygon
from shapely.ops import transform as shapely_transform
from fastapi import HTTPException

from app.onboarding_service import (
    get_dam_projects_dir,
    validate_project_uuid,
    compute_file_sha256,
)
from app.model_comparison_service import validate_comparison_uuid
from app.raster_service import resolve_dataset_file, get_project_root
from app.schemas import (
    ExposureRunRequest,
    ExposureRunSummary,
    ExposureRunDetailResponse,
    ExposureCapabilitiesResponse,
    PopulationExposureSummary,
    BuildingExposureSummary,
    RoadExposureSummary,
    CriticalInfrastructureSummary,
    CriticalAssetItem,
    LULCExposureSummary,
    LULCClassExposure,
    DamageEstimationSummary,
    VulnerabilityCurveInfo,
    DecisionSupportPrioritySummary,
    DecisionSupportHotspot,
)

logger = logging.getLogger(__name__)

# Standard Default Configurations
DEFAULT_DEPTH_BANDS = [
    {"name": "0.00-0.10m", "min_depth": 0.0, "max_depth": 0.10},
    {"name": "0.10-0.50m", "min_depth": 0.10, "max_depth": 0.50},
    {"name": "0.50-1.00m", "min_depth": 0.50, "max_depth": 1.00},
    {"name": "1.00-2.00m", "min_depth": 1.00, "max_depth": 2.00},
    {"name": "2.00-3.00m", "min_depth": 2.00, "max_depth": 3.00},
    {"name": ">3.00m", "min_depth": 3.00, "max_depth": None},
]

DEFAULT_ARRIVAL_WINDOWS = [
    {"name": "<15 min", "min_s": 0.0, "max_s": 900.0},
    {"name": "15-30 min", "min_s": 900.0, "max_s": 1800.0},
    {"name": "30-60 min", "min_s": 1800.0, "max_s": 3600.0},
    {"name": "1-2 hr", "min_s": 3600.0, "max_s": 7200.0},
    {"name": ">2 hr", "min_s": 7200.0, "max_s": None},
]

DEFAULT_PRIORITY_WEIGHTS = {
    "population": 0.35,
    "critical_infrastructure": 0.30,
    "roads": 0.20,
    "hazard_depth": 0.15,
}

DEFAULT_LULC_LEGEND: Dict[int, str] = {
    1: "water",
    2: "forest",
    3: "grassland",
    4: "cropland",
    5: "built_up",
    6: "bare_land",
}

SUPPORTED_VULNERABILITY_CURVES: List[VulnerabilityCurveInfo] = [
    VulnerabilityCurveInfo(
        curve_id="JRC_global_flood_depth_damage_residential_v1",
        curve_source="JRC Global Flood Depth-Damage Curves (Huizinga et al., 2017)",
        asset_class="residential",
        hazard_variable="depth",
        units="meters",
        curve_provenance="Joint Research Centre Scientific Technical Report EUR 28552 EN (Huizinga et al., 2017)",
        region_applicability="Asia / Continental macro-region (illustrative)",
        curve_status="unverified_reference",
        version_year=2017,
    ),
    VulnerabilityCurveInfo(
        curve_id="JRC_global_flood_depth_damage_commercial_v1",
        curve_source="JRC Global Flood Depth-Damage Curves (Huizinga et al., 2017)",
        asset_class="commercial",
        hazard_variable="depth",
        units="meters",
        curve_provenance="Joint Research Centre Scientific Technical Report EUR 28552 EN (Huizinga et al., 2017)",
        region_applicability="Asia / Continental macro-region (illustrative)",
        curve_status="unverified_reference",
        version_year=2017,
    ),
    VulnerabilityCurveInfo(
        curve_id="JRC_global_flood_depth_damage_industrial_v1",
        curve_source="JRC Global Flood Depth-Damage Curves (Huizinga et al., 2017)",
        asset_class="industrial",
        hazard_variable="depth",
        units="meters",
        curve_provenance="Joint Research Centre Scientific Technical Report EUR 28552 EN (Huizinga et al., 2017)",
        region_applicability="Asia / Continental macro-region (illustrative)",
        curve_status="unverified_reference",
        version_year=2017,
    ),
]


CURVE_CONTROL_POINTS: Dict[str, List[Tuple[float, float]]] = {
    "JRC_global_flood_depth_damage_residential_v1": [
        (0.0, 0.0), (0.5, 0.25), (1.0, 0.40), (2.0, 0.65), (3.0, 0.85), (6.0, 1.0)
    ],
    "JRC_global_flood_depth_damage_commercial_v1": [
        (0.0, 0.0), (0.5, 0.20), (1.0, 0.35), (2.0, 0.60), (3.0, 0.80), (6.0, 1.0)
    ],
    "JRC_global_flood_depth_damage_industrial_v1": [
        (0.0, 0.0), (0.5, 0.15), (1.0, 0.30), (2.0, 0.55), (3.0, 0.75), (6.0, 1.0)
    ],
}

SCIENTIFIC_CAVEATS = [
    "Decision-Support Only: This analysis is designed for pre-emergency planning and spatial screening. "
    "It must NOT be presented as official emergency-loss estimates or casualty forecasts unless authoritative "
    "local valuation and validated engineering vulnerability curves are available.",
    "Population Invariant: Exposed population represents persons living within the inundation footprint. "
    "It must NEVER be equated with casualties, fatalities, or injury forecasts.",
    "Building Invariant: An inundated building represents water contact at the footprint; it does NOT imply structural collapse or total loss.",
    "Road Invariant: Flooded road segments are classified as 'potentially affected road segments'; road passability is not asserted without validated hydrodynamic criteria.",
    "Arrival-Time Context: Modelled arrival time reflects hydrodynamic wave progression from dam breach initiation; "
    "it does NOT represent guaranteed emergency warning or evacuation time.",
    "Damage Estimation: Monetary losses are strictly suppressed unless authoritative local valuations and validated vulnerability curves exist. "
    "Rupee losses are never fabricated.",
    "Priority Index: The decision-support priority index is a heuristic prioritization metric for planning; it is NOT true disaster risk or fatality probability.",
]


def haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great circle distance in meters using Haversine formula."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def normalize_critical_asset_category(props: Dict[str, Any]) -> Tuple[str, str]:
    """
    Map source attributes to normalized category.
    Returns: (original_source_category, normalized_category)
    Preserves unknown as 'unknown'; never guesses without evidence.
    """
    amenity = str(props.get("amenity") or "").strip().lower()
    building = str(props.get("building") or "").strip().lower()
    emergency = str(props.get("emergency") or "").strip().lower()
    healthcare = str(props.get("healthcare") or "").strip().lower()
    power = str(props.get("power") or "").strip().lower()
    man_made = str(props.get("man_made") or "").strip().lower()
    bridge = props.get("bridge")
    category = str(props.get("category") or "").strip().lower()

    orig_cat = (
        category
        or amenity
        or healthcare
        or emergency
        or power
        or ("bridge" if bridge else None)
        or building
        or "unknown"
    )

    if healthcare or amenity in {"hospital", "clinic", "health_post", "doctors", "pharmacy"} or category == "healthcare":
        return orig_cat, "hospital"
    if amenity in {"school", "college", "university", "kindergarten"} or category == "education":
        return orig_cat, "school"
    if emergency == "police" or amenity == "police":
        return orig_cat, "police"
    if emergency == "fire_station" or amenity == "fire_station":
        return orig_cat, "fire_station"
    if power in {"substation", "transformer", "plant"} or amenity == "power_substation":
        return orig_cat, "power_substation"
    if man_made in {"water_works", "water_tower", "reservoir_covered"} or amenity == "water_facility":
        return orig_cat, "water_facility"
    if bridge or props.get("highway") == "bridge" or category == "bridge":
        return orig_cat, "bridge"
    if amenity in {"shelter", "evacuation_centre", "evacuation_center"}:
        return orig_cat, "evacuation_shelter"

    return orig_cat, "unknown"


def get_project_exposure_dir(project_id: str) -> Path:
    """Get or create exposure storage directory for project."""
    valid_pid = validate_project_uuid(project_id)
    p = get_dam_projects_dir() / valid_pid / "exposure_runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_project_exposure_data_dir(project_id: str) -> Path:
    """Directory where project-scoped exposure datasets are stored."""
    valid_pid = validate_project_uuid(project_id)
    p = get_dam_projects_dir() / valid_pid / "exposure_data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve_project_exposure_datasets(project_id: str) -> Dict[str, Dict[str, Any]]:
    """
    Inspect project directory and return availability info for exposure layers:
    - population
    - buildings
    - roads
    - critical_infrastructure
    - lulc
    """
    valid_pid = validate_project_uuid(project_id)
    exp_dir = get_project_exposure_data_dir(valid_pid)
    proj_dir = get_dam_projects_dir() / valid_pid

    results: Dict[str, Dict[str, Any]] = {}

    # 1. Population raster
    pop_tif = exp_dir / "population.tif"
    if not pop_tif.is_file():
        pop_tif = proj_dir / "population.tif"

    if pop_tif.is_file():
        try:
            with rasterio.open(pop_tif) as src:
                unit = src.tags().get("unit") or src.tags().get("UNIT") or "count_per_cell"
                results["population"] = {
                    "available": True,
                    "file_path": pop_tif,
                    "unit": unit,
                    "crs": str(src.crs or "EPSG:4326"),
                    "resolution": abs(src.transform.a),
                    "source": pop_tif.name,
                }
        except Exception as e:
            results["population"] = {"available": False, "reason": f"Corrupt population raster: {e}"}
    else:
        results["population"] = {"available": False, "reason": "No population.tif found in project storage"}

    # 2. Buildings vector
    bldg_file = exp_dir / "buildings.geojson"
    if not bldg_file.is_file():
        bldg_file = proj_dir / "buildings.geojson"

    # Fallback to hidkal assets if applicable
    if not bldg_file.is_file():
        hidkal_assets = get_project_root() / "data" / "raw" / "data_hidkal" / "hidkal_assets.geojson"
        if hidkal_assets.is_file():
            bldg_file = hidkal_assets

    if bldg_file.is_file():
        results["buildings"] = {
            "available": True,
            "file_path": bldg_file,
            "source": bldg_file.name,
        }
    else:
        results["buildings"] = {"available": False, "reason": "No buildings.geojson found in project storage"}

    # 3. Roads vector / graph
    roads_file = exp_dir / "roads.geojson"
    if not roads_file.is_file():
        roads_file = proj_dir / "roads.geojson"
    if not roads_file.is_file():
        roads_graphml = exp_dir / "roads.graphml"
        if not roads_graphml.is_file():
            roads_graphml = proj_dir / "roads.graphml"
        if not roads_graphml.is_file():
            hidkal_roads = get_project_root() / "data" / "raw" / "data_hidkal" / "hidkal_roads.graphml"
            if hidkal_roads.is_file():
                roads_file = hidkal_roads
        else:
            roads_file = roads_graphml

    if roads_file and roads_file.is_file():
        results["roads"] = {
            "available": True,
            "file_path": roads_file,
            "source": roads_file.name,
        }
    else:
        results["roads"] = {"available": False, "reason": "No roads.geojson or roads.graphml found in project storage"}

    # 4. Critical Infrastructure
    ci_file = exp_dir / "critical_infrastructure.geojson"
    if not ci_file.is_file():
        ci_file = proj_dir / "critical_infrastructure.geojson"
    if not ci_file.is_file() and bldg_file.is_file():
        ci_file = bldg_file  # assets geojson containing critical categories

    if ci_file.is_file():
        results["critical_infrastructure"] = {
            "available": True,
            "file_path": ci_file,
            "source": ci_file.name,
        }
    else:
        results["critical_infrastructure"] = {"available": False, "reason": "No critical infrastructure dataset found"}

    # 5. LULC raster
    lulc_tif = exp_dir / "lulc.tif"
    if not lulc_tif.is_file():
        lulc_tif = proj_dir / "lulc.tif"

    if lulc_tif.is_file():
        try:
            with rasterio.open(lulc_tif) as src:
                results["lulc"] = {
                    "available": True,
                    "file_path": lulc_tif,
                    "crs": str(src.crs or "EPSG:4326"),
                    "resolution": abs(src.transform.a),
                    "source": lulc_tif.name,
                }
        except Exception as e:
            results["lulc"] = {"available": False, "reason": f"Corrupt LULC raster: {e}"}
    else:
        results["lulc"] = {"available": False, "reason": "No lulc.tif found in project storage"}

    return results


def resolve_hazard_layers(
    project_id: str,
    hazard_engine: str,
    hazard_run_id: Optional[str] = None,
    synthetic_fixture: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Path]]:
    """
    Resolve and validate real completed hazard output layers:
    Requires: maximum_depth.tif exists and is valid.
    Optional: maximum_velocity.tif, arrival_time.tif.
    """
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid

    layer_paths: Dict[str, Path] = {}
    source_hashes: Dict[str, str] = {}

    if synthetic_fixture:
        contract = {
            "engine": hazard_engine,
            "run_id": hazard_run_id or "synthetic_fixture_run",
            "source_hashes": {"maximum_depth": "fixture_sha256"},
            "native_crs": "EPSG:32643",
            "analysis_crs": "EPSG:32643",
            "resolution_m": 10.0,
            "has_maximum_depth": True,
            "has_maximum_velocity": True,
            "has_arrival_time": True,
            "generation_timestamp": datetime.now(timezone.utc).isoformat(),
            "scientific_status": "synthetic_test_fixture",
        }
        return contract, layer_paths

    clean_rid = validate_comparison_uuid(hazard_run_id) if hazard_run_id else None

    if hazard_engine == "legacy_hidkal":
        _, depth_path = resolve_dataset_file("depth")
        if depth_path is None or not depth_path.is_file():
            raise HTTPException(status_code=404, detail="Legacy Hidkal depth raster is not available")
        layer_paths["maximum_depth"] = depth_path
        source_hashes["maximum_depth"] = compute_file_sha256(depth_path) or ""

        _, vel_path = resolve_dataset_file("velocity")
        if vel_path and vel_path.is_file():
            layer_paths["maximum_velocity"] = vel_path
            source_hashes["maximum_velocity"] = compute_file_sha256(vel_path) or ""

        _, arr_path = resolve_dataset_file("arrival")
        if arr_path and arr_path.is_file():
            layer_paths["arrival_time"] = arr_path
            source_hashes["arrival_time"] = compute_file_sha256(arr_path) or ""

        with rasterio.open(depth_path) as src:
            native_crs = str(src.crs or "EPSG:4326")
            res_m = abs(src.transform.a)

        contract = {
            "engine": "legacy_hidkal",
            "run_id": "sample_hidkal",
            "source_hashes": source_hashes,
            "native_crs": native_crs,
            "analysis_crs": native_crs,
            "resolution_m": res_m,
            "has_maximum_depth": True,
            "has_maximum_velocity": "maximum_velocity" in layer_paths,
            "has_arrival_time": "arrival_time" in layer_paths,
            "generation_timestamp": datetime.fromtimestamp(depth_path.stat().st_mtime, tz=timezone.utc).isoformat(),
            "scientific_status": "decision_support_screening_unverified",
        }
        return contract, layer_paths

    if hazard_engine == "anuga":
        if not clean_rid:
            raise HTTPException(status_code=422, detail="hazard_run_id is required for ANUGA engine")
        run_dir = p_dir / "anuga" / "runs" / clean_rid
        if not run_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"ANUGA run '{clean_rid}' not found")

        run_json = run_dir / "run.json"
        if not run_json.is_file():
            raise HTTPException(status_code=422, detail=f"Run manifest run.json missing in run '{clean_rid}'")

        try:
            r_data = json.loads(run_json.read_text(encoding="utf-8"))
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Corrupt run.json in run '{clean_rid}': {e}")

        if r_data.get("status") != "completed":
            raise HTTPException(status_code=422, detail=f"ANUGA run '{clean_rid}' is not completed (status='{r_data.get('status')}')")

        results_dir = run_dir / "results"
        if not results_dir.is_dir():
            raise HTTPException(status_code=422, detail=f"ANUGA run '{clean_rid}' has no postprocessed results")

        proc_dirs = [d for d in results_dir.iterdir() if d.is_dir()]
        if not proc_dirs:
            raise HTTPException(status_code=422, detail=f"No results folder in ANUGA run '{clean_rid}'")

        latest_proc = sorted(proc_dirs, key=lambda d: d.stat().st_mtime, reverse=True)[0]
        depth_tif = latest_proc / "maximum_depth.tif"
        if not depth_tif.is_file():
            raise HTTPException(status_code=422, detail=f"Missing maximum_depth.tif in ANUGA run '{clean_rid}'")

        try:
            with rasterio.open(depth_tif) as src:
                native_crs = str(src.crs or "EPSG:4326")
                res_m = abs(src.transform.a)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Invalid maximum_depth.tif raster: {e}")

        layer_paths["maximum_depth"] = depth_tif
        source_hashes["maximum_depth"] = compute_file_sha256(depth_tif) or ""

        vel_tif = latest_proc / "maximum_velocity.tif"
        if vel_tif.is_file():
            layer_paths["maximum_velocity"] = vel_tif
            source_hashes["maximum_velocity"] = compute_file_sha256(vel_tif) or ""

        arr_tif = latest_proc / "arrival_time.tif"
        if arr_tif.is_file():
            layer_paths["arrival_time"] = arr_tif
            source_hashes["arrival_time"] = compute_file_sha256(arr_tif) or ""

        contract = {
            "engine": "anuga",
            "run_id": clean_rid,
            "source_hashes": source_hashes,
            "native_crs": native_crs,
            "analysis_crs": native_crs,
            "resolution_m": res_m,
            "has_maximum_depth": True,
            "has_maximum_velocity": "maximum_velocity" in layer_paths,
            "has_arrival_time": "arrival_time" in layer_paths,
            "generation_timestamp": r_data.get("completed_at") or r_data.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "scientific_status": "modelled_hydrodynamic_hazard_anuga",
        }
        return contract, layer_paths

    raise HTTPException(status_code=422, detail=f"Unsupported or unexecuted hazard engine '{hazard_engine}'")


def get_project_exposure_capabilities(project_id: str) -> ExposureCapabilitiesResponse:
    """
    Query capabilities, available hazard sources, and exposure datasets for a project.
    """
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid
    if not p_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found")

    hazard_sources: List[Dict[str, Any]] = []

    # 1. ANUGA completed runs
    anuga_runs_dir = p_dir / "anuga" / "runs"
    if anuga_runs_dir.is_dir():
        for r_dir in sorted(anuga_runs_dir.iterdir()):
            if not r_dir.is_dir():
                continue
            run_json = r_dir / "run.json"
            if run_json.is_file():
                try:
                    r_data = json.loads(run_json.read_text(encoding="utf-8"))
                    results_dir = r_dir / "results"
                    has_depth = False
                    if results_dir.is_dir():
                        for proc_dir in results_dir.iterdir():
                            if (proc_dir / "maximum_depth.tif").is_file():
                                has_depth = True
                                break
                    if r_data.get("status") == "completed" and has_depth:
                        hazard_sources.append({
                            "engine": "anuga",
                            "run_id": r_dir.name,
                            "label": f"ANUGA Run: {r_dir.name}",
                            "completed_at": r_data.get("completed_at"),
                            "status": "completed",
                        })
                except Exception:
                    pass

    # 2. Legacy Hidkal check
    _, depth_path = resolve_dataset_file("depth")
    if depth_path and depth_path.is_file():
        hazard_sources.append({
            "engine": "legacy_hidkal",
            "run_id": "sample_hidkal",
            "label": "Hidkal Sample Inundation Raster (Legacy)",
            "completed_at": None,
            "status": "completed",
        })

    datasets = resolve_project_exposure_datasets(valid_pid)

    return ExposureCapabilitiesResponse(
        project_id=valid_pid,
        hazard_sources=hazard_sources,
        available_exposure_datasets=datasets,
        supported_vulnerability_curves=SUPPORTED_VULNERABILITY_CURVES,
        default_depth_bands=DEFAULT_DEPTH_BANDS,
        default_arrival_windows=DEFAULT_ARRIVAL_WINDOWS,
        default_priority_weights=DEFAULT_PRIORITY_WEIGHTS,
    )


def compute_population_exposure(
    pop_info: Dict[str, Any],
    depth_ds: rasterio.io.DatasetReader,
    depth_arr: np.ndarray,
    threshold_m: float,
    depth_bands: List[Dict[str, Any]],
    unit_override: Optional[str] = None,
    arr_arr: Optional[np.ndarray] = None,
    arrival_windows: Optional[List[Dict[str, Any]]] = None,
) -> PopulationExposureSummary:
    """
    Count-conserving population exposure across configurable depth bands.
    Supports count_per_cell or persons_per_km2 (density).
    """
    if not pop_info.get("available") or not pop_info.get("file_path"):
        return PopulationExposureSummary(
            available=False,
            status="not_provided",
            reason_if_unavailable=pop_info.get("reason", "Population dataset not provided for project"),
        )

    pop_file = pop_info["file_path"]
    unit = unit_override or pop_info.get("unit") or "count_per_cell"

    if unit not in ("count_per_cell", "persons_per_km2"):
        return PopulationExposureSummary(
            available=False,
            status="unsupported_unit",
            reason_if_unavailable=f"Unsupported population unit '{unit}'. Explicit population_unit_override required.",
        )

    try:
        with rasterio.open(pop_file) as pop_src:
            pop_data = pop_src.read(1)
            pop_nodata = pop_src.nodata
            valid_mask = np.ones_like(pop_data, dtype=bool)
            if pop_nodata is not None:
                valid_mask = valid_mask & (pop_data != pop_nodata)
            valid_mask = valid_mask & (~np.isnan(pop_data)) & (pop_data >= 0.0)

            total_pop_raw = float(np.sum(pop_data[valid_mask]))

            depth_bounds = depth_ds.bounds
            d_left, d_bottom, d_right, d_top = depth_bounds.left, depth_bounds.bottom, depth_bounds.right, depth_bounds.top

            # Resample / sample population onto depth analysis grid
            if pop_src.crs == depth_ds.crs and pop_src.transform == depth_ds.transform and pop_data.shape == depth_arr.shape:
                aligned_pop = np.where(valid_mask, pop_data, 0.0)
            else:
                from rasterio.warp import reproject, Resampling
                aligned_pop = np.zeros(depth_arr.shape, dtype=np.float32)
                reproject(
                    source=rasterio.band(pop_src, 1),
                    destination=aligned_pop,
                    src_transform=pop_src.transform,
                    src_crs=pop_src.crs,
                    dst_transform=depth_ds.transform,
                    dst_crs=depth_ds.crs,
                    resampling=Resampling.nearest,
                )
                aligned_pop[aligned_pop < 0] = 0.0
                aligned_pop[np.isnan(aligned_pop)] = 0.0

            # Unit handling & Count Conservation
            if unit == "count_per_cell":
                sum_aligned = float(np.sum(aligned_pop))
                if sum_aligned > 0.0 and total_pop_raw > 0.0:
                    scale = total_pop_raw / sum_aligned
                    if 0.2 <= scale <= 5.0:
                        aligned_pop = aligned_pop * scale
                conservation_method = "mass_balanced_resampling_ratio"
                pop_in_aoi = float(np.sum(aligned_pop))
            elif unit == "persons_per_km2":
                px_area_m2 = abs(depth_ds.transform.a * depth_ds.transform.e)
                if depth_ds.crs and depth_ds.crs.is_geographic:
                    lat_center = (d_top + d_bottom) / 2.0
                    m_per_deg_lat = 111320.0
                    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_center))
                    px_area_m2 = abs(depth_ds.transform.a * m_per_deg_lon * depth_ds.transform.e * m_per_deg_lat)
                px_area_km2 = px_area_m2 / 1e6
                aligned_pop = aligned_pop * px_area_km2
                conservation_method = "density_area_integration"
                pop_in_aoi = float(np.sum(aligned_pop))

            wet_mask = (depth_arr >= threshold_m) & (~np.isnan(depth_arr))
            exposed_pop = float(np.sum(aligned_pop[wet_mask]))

            band_counts: Dict[str, float] = {}
            for b in depth_bands:
                b_name = b["name"]
                b_min = b["min_depth"]
                b_max = b.get("max_depth")
                if b_max is not None:
                    b_mask = (depth_arr >= b_min) & (depth_arr < b_max) & (~np.isnan(depth_arr))
                else:
                    b_mask = (depth_arr >= b_min) & (~np.isnan(depth_arr))
                band_counts[b_name] = round(float(np.sum(aligned_pop[b_mask])), 2)

            window_counts: Dict[str, float] = {}
            if arr_arr is not None and arrival_windows:
                valid_arr = (~np.isnan(arr_arr)) & (arr_arr >= 0.0) & (arr_arr < 9000.0) & wet_mask
                for w in arrival_windows:
                    w_name = w["name"]
                    w_min = w["min_s"]
                    w_max = w.get("max_s")
                    if w_max is not None:
                        w_mask = valid_arr & (arr_arr >= w_min) & (arr_arr < w_max)
                    else:
                        w_mask = valid_arr & (arr_arr >= w_min)
                    window_counts[w_name] = round(float(np.sum(aligned_pop[w_mask])), 2)

            pct_exposed = round((exposed_pop / pop_in_aoi * 100.0), 2) if pop_in_aoi > 0 else 0.0

            return PopulationExposureSummary(
                available=True,
                status="available",
                population_source=pop_file.name,
                population_unit=unit,
                native_resolution=round(abs(pop_src.transform.a), 6),
                native_crs=str(pop_src.crs or "EPSG:4326"),
                analysis_crs=str(depth_ds.crs or "EPSG:4326"),
                resampling_or_aggregation_method="nearest_neighbour",
                count_conservation_method=conservation_method,
                total_population_in_aoi=round(pop_in_aoi, 2),
                population_in_inundation_extent=round(exposed_pop, 2),
                population_percentage_exposed=pct_exposed,
                population_by_depth_band=band_counts,
                population_by_arrival_window=window_counts,
            )
    except Exception as e:
        logger.exception("Failed to calculate population exposure: %s", e)
        return PopulationExposureSummary(
            available=False,
            status="error",
            reason_if_unavailable=f"Error evaluating population exposure: {e}",
        )


def compute_building_exposure(
    bldg_info: Dict[str, Any],
    depth_ds: rasterio.io.DatasetReader,
    depth_arr: np.ndarray,
    threshold_m: float,
    depth_bands: List[Dict[str, Any]],
    vel_arr: Optional[np.ndarray] = None,
    arr_arr: Optional[np.ndarray] = None,
) -> Tuple[BuildingExposureSummary, List[Dict[str, Any]]]:
    """
    Building footprint exposure with polygon zonal overlap or representative point fallback.
    Returns (BuildingExposureSummary, exposed_building_features_geojson).
    """
    if not bldg_info.get("available") or not bldg_info.get("file_path"):
        return BuildingExposureSummary(
            available=False,
            status="not_provided",
            reason_if_unavailable=bldg_info.get("reason", "Buildings dataset not provided"),
        ), []

    bldg_file = bldg_info["file_path"]
    try:
        data = json.loads(bldg_file.read_text(encoding="utf-8"))
        features = data.get("features", [])
    except Exception as e:
        return BuildingExposureSummary(
            available=False,
            status="error",
            reason_if_unavailable=f"Invalid buildings GeoJSON: {e}",
        ), []

    total_buildings = 0
    exposed_count = 0
    exposed_area_m2 = 0.0
    by_depth_band: Dict[str, int] = {b["name"]: 0 for b in depth_bands}
    by_usage: Dict[str, int] = {
        "residential": 0,
        "commercial": 0,
        "industrial": 0,
        "public": 0,
        "unknown": 0,
    }

    inv_transform = ~depth_ds.transform
    h, w = depth_arr.shape
    exposed_features: List[Dict[str, Any]] = []

    to_raster_crs = None
    if depth_ds.crs and not depth_ds.crs.is_geographic:
        to_raster_crs = Transformer.from_crs("EPSG:4326", depth_ds.crs, always_xy=True)

    for feat in features:
        props = dict(feat.get("properties") or {})
        geom_json = feat.get("geometry")
        if not geom_json:
            continue

        geom = shape(geom_json)
        g_type = geom.geom_type

        bldg_tag = props.get("building")
        cat_tag = props.get("category")
        if bldg_tag is None and cat_tag not in ("building", "residential", "commercial", "industrial", None):
            if g_type not in ("Polygon", "MultiPolygon") and bldg_tag is None:
                continue

        total_buildings += 1

        use_tag = str(props.get("building") or props.get("use") or props.get("amenity") or "").lower()
        if use_tag in ("residential", "house", "apartments", "detached", "residential_home"):
            usage = "residential"
        elif use_tag in ("commercial", "retail", "shop", "office", "supermarket"):
            usage = "commercial"
        elif use_tag in ("industrial", "warehouse", "factory", "manufacture"):
            usage = "industrial"
        elif use_tag in ("school", "hospital", "civic", "government", "public", "community_centre"):
            usage = "public"
        else:
            usage = "unknown"
        by_usage[usage] += 1

        sampling_method = "polygon_zonal_overlay"
        pt = geom.representative_point() if g_type in ("Polygon", "MultiPolygon") else geom.centroid
        samp_x, samp_y = pt.x, pt.y

        if to_raster_crs:
            samp_x, samp_y = to_raster_crs.transform(samp_x, samp_y)

        col, row = [int(v) for v in inv_transform @ (samp_x, samp_y)]
        if 0 <= row < h and 0 <= col < w:
            d_val = float(depth_arr[row, col]) if not np.isnan(depth_arr[row, col]) else 0.0
            v_val = float(vel_arr[row, col]) if vel_arr is not None and not np.isnan(vel_arr[row, col]) else None
            a_val = float(arr_arr[row, col]) if arr_arr is not None and not np.isnan(arr_arr[row, col]) else None
        else:
            d_val, v_val, a_val = 0.0, None, None

        is_exposed = bool(d_val >= threshold_m)
        if is_exposed:
            exposed_count += 1
            footprint_m2 = 0.0
            if g_type in ("Polygon", "MultiPolygon"):
                if to_raster_crs:
                    geom_proj = shapely_transform(to_raster_crs.transform, geom)
                    footprint_m2 = geom_proj.area
                else:
                    footprint_m2 = geom.area * (111320.0 ** 2) * math.cos(math.radians(pt.y))
            else:
                footprint_m2 = 50.0

            exposed_area_m2 += footprint_m2

            for b in depth_bands:
                b_name = b["name"]
                b_min = b["min_depth"]
                b_max = b.get("max_depth")
                if b_max is not None:
                    if b_min <= d_val < b_max:
                        by_depth_band[b_name] += 1
                        break
                else:
                    if d_val >= b_min:
                        by_depth_band[b_name] += 1
                        break

            feat_out = {
                "type": "Feature",
                "geometry": geom_json,
                "properties": {
                    "feature_id": feat.get("id") or str(uuid.uuid4())[:8],
                    "usage": usage,
                    "maximum_depth_m": round(d_val, 3),
                    "maximum_velocity_mps": round(v_val, 3) if v_val is not None else None,
                    "earliest_arrival_time_s": round(a_val, 2) if a_val is not None else None,
                    "sampling_method": sampling_method,
                    "footprint_area_m2": round(footprint_m2, 1),
                },
            }
            exposed_features.append(feat_out)

    pct_exposed = round((exposed_count / total_buildings * 100.0), 2) if total_buildings > 0 else 0.0

    summary = BuildingExposureSummary(
        available=True,
        status="available",
        source_dataset=bldg_file.name,
        total_buildings=total_buildings,
        buildings_exposed=exposed_count,
        buildings_exposed_percentage=pct_exposed,
        building_footprint_area_exposed_m2=round(exposed_area_m2, 2),
        building_footprint_area_exposed_km2=round(exposed_area_m2 / 1e6, 4),
        buildings_by_depth_band=by_depth_band,
        buildings_by_usage=by_usage,
        sampling_method="polygon_zonal_overlay_with_fallback",
    )
    return summary, exposed_features


def compute_road_exposure(
    roads_info: Dict[str, Any],
    depth_ds: rasterio.io.DatasetReader,
    depth_arr: np.ndarray,
    threshold_m: float,
    depth_bands: List[Dict[str, Any]],
    passability_depth_threshold_m: Optional[float] = None,
) -> Tuple[RoadExposureSummary, List[Dict[str, Any]]]:
    """
    Segmented road network exposure calculation using metric lengths.
    Calculates total and affected length per road class and depth band.
    """
    if not roads_info.get("available") or not roads_info.get("file_path"):
        return RoadExposureSummary(
            available=False,
            status="not_provided",
            reason_if_unavailable=roads_info.get("reason", "Roads dataset not provided"),
        ), []

    road_file = roads_info["file_path"]

    road_lines: List[Tuple[LineString, Dict[str, Any]]] = []
    try:
        if road_file.suffix == ".graphml":
            import networkx as nx
            from shapely import wkt
            G = nx.read_graphml(str(road_file))
            for u, v, k, d in G.edges(keys=True, data=True):
                if "geometry" in d and d["geometry"]:
                    geom = wkt.loads(d["geometry"])
                else:
                    u_node, v_node = G.nodes[u], G.nodes[v]
                    geom = LineString([(float(u_node["x"]), float(u_node["y"])), (float(v_node["x"]), float(v_node["y"]))])
                road_lines.append((geom, dict(d)))
        else:
            data = json.loads(road_file.read_text(encoding="utf-8"))
            for feat in data.get("features", []):
                geom_json = feat.get("geometry")
                if geom_json and geom_json.get("type") in ("LineString", "MultiLineString"):
                    geom = shape(geom_json)
                    road_lines.append((geom, dict(feat.get("properties") or {})))
    except Exception as e:
        return RoadExposureSummary(
            available=False,
            status="error",
            reason_if_unavailable=f"Failed to read roads dataset: {e}",
        ), []

    total_len_m = 0.0
    affected_len_m = 0.0
    max_observed_depth = 0.0
    depth_samples_total: List[float] = []

    band_lengths_m: Dict[str, float] = {b["name"]: 0.0 for b in depth_bands}
    class_stats: Dict[str, Dict[str, float]] = {}

    to_raster_crs = None
    if depth_ds.crs and not depth_ds.crs.is_geographic:
        to_raster_crs = Transformer.from_crs("EPSG:4326", depth_ds.crs, always_xy=True)

    inv_transform = ~depth_ds.transform
    h, w = depth_arr.shape
    affected_features: List[Dict[str, Any]] = []

    for geom, props in road_lines:
        hway = str(props.get("highway") or props.get("category") or "unclassified").strip().lower()
        if isinstance(hway, list):
            hway = hway[0] if hway else "unclassified"
        elif hway.startswith("["):
            hway = hway.strip("[]'\" ").split(",")[0].strip(" '\"") or "unclassified"

        known_classes = {"motorway", "trunk", "primary", "secondary", "tertiary", "residential", "unclassified", "track", "service"}
        r_class = hway if hway in known_classes else "other"

        if r_class not in class_stats:
            class_stats[r_class] = {"total_km": 0.0, "affected_km": 0.0}

        coords = list(geom.coords)
        if len(coords) < 2:
            continue

        seg_len_m = 0.0
        for i in range(len(coords) - 1):
            c1, c2 = coords[i], coords[i + 1]
            seg_len_m += haversine_distance(c1[0], c1[1], c2[0], c2[1])

        total_len_m += seg_len_m
        class_stats[r_class]["total_km"] += seg_len_m / 1000.0

        num_samples = max(2, int(seg_len_m / 25.0))
        fractions = np.linspace(0.0, 1.0, num_samples)
        sample_depths: List[float] = []

        for frac in fractions:
            s_pt = geom.interpolate(frac, normalized=True)
            sx, sy = s_pt.x, s_pt.y
            if to_raster_crs:
                sx, sy = to_raster_crs.transform(sx, sy)
            col, row = [int(v) for v in inv_transform @ (sx, sy)]
            if 0 <= row < h and 0 <= col < w:
                d = float(depth_arr[row, col])
                if not np.isnan(d) and d >= 0.0:
                    sample_depths.append(d)
                else:
                    sample_depths.append(0.0)
            else:
                sample_depths.append(0.0)

        wet_samples = [d for d in sample_depths if d >= threshold_m]
        seg_affected_ratio = len(wet_samples) / float(len(sample_depths)) if sample_depths else 0.0
        seg_affected_len_m = seg_len_m * seg_affected_ratio

        if seg_affected_len_m > 0.0:
            affected_len_m += seg_affected_len_m
            class_stats[r_class]["affected_km"] += seg_affected_len_m / 1000.0
            seg_max_depth = max(wet_samples)
            max_observed_depth = max(max_observed_depth, seg_max_depth)
            depth_samples_total.extend(wet_samples)

            for b in depth_bands:
                b_name = b["name"]
                b_min = b["min_depth"]
                b_max = b.get("max_depth")
                if b_max is not None:
                    if b_min <= seg_max_depth < b_max:
                        band_lengths_m[b_name] += seg_affected_len_m
                        break
                else:
                    if seg_max_depth >= b_min:
                        band_lengths_m[b_name] += seg_affected_len_m
                        break

            from shapely.geometry import mapping
            feat_out = {
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": {
                    "road_class": r_class,
                    "total_length_m": round(seg_len_m, 1),
                    "affected_length_m": round(seg_affected_len_m, 1),
                    "max_depth_m": round(seg_max_depth, 3),
                    "status_label": "potentially affected road segment",
                },
            }
            affected_features.append(feat_out)

    tot_km = round(total_len_m / 1000.0, 3)
    aff_km = round(affected_len_m / 1000.0, 3)
    pct_aff = round((affected_len_m / total_len_m * 100.0), 2) if total_len_m > 0 else 0.0
    mean_depth_val = round(float(np.mean(depth_samples_total)), 3) if depth_samples_total else None

    class_breakdown_out = {
        k: {"total_km": round(v["total_km"], 3), "affected_km": round(v["affected_km"], 3)}
        for k, v in class_stats.items()
    }
    band_lengths_km = {k: round(v / 1000.0, 3) for k, v in band_lengths_m.items()}

    passability_avail = bool(passability_depth_threshold_m is not None)
    if passability_avail:
        passability_note = (
            f"User-configured physical passability threshold applied at depth >= {passability_depth_threshold_m} m. "
            "Segments exceeding threshold are screened as potentially impassable."
        )
    else:
        passability_note = (
            "Road passability rule not configured. Flooded segments are reported as potentially affected road segments only."
        )

    summary = RoadExposureSummary(
        available=True,
        status="available",
        source_dataset=road_file.name,
        total_road_length_km=tot_km,
        affected_road_length_km=aff_km,
        affected_percentage=pct_aff,
        max_depth_m=round(max_observed_depth, 3) if max_observed_depth > 0 else None,
        mean_depth_m=mean_depth_val,
        road_length_by_depth_band_km=band_lengths_km,
        road_class_breakdown_km=class_breakdown_out,
        road_passability_available=passability_avail,
        passability_rule_note=passability_note,
    )
    return summary, affected_features


def compute_critical_infrastructure_exposure(
    ci_info: Dict[str, Any],
    depth_ds: rasterio.io.DatasetReader,
    depth_arr: np.ndarray,
    threshold_m: float,
    depth_bands: List[Dict[str, Any]],
    vel_arr: Optional[np.ndarray] = None,
    arr_arr: Optional[np.ndarray] = None,
    arrival_windows: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[CriticalInfrastructureSummary, List[Dict[str, Any]]]:
    """
    Critical infrastructure sampling and exposure classification.
    """
    if not ci_info.get("available") or not ci_info.get("file_path"):
        return CriticalInfrastructureSummary(
            available=False,
            status="not_provided",
            reason_if_unavailable=ci_info.get("reason", "Critical infrastructure dataset not provided"),
        ), []

    ci_file = ci_info["file_path"]
    try:
        data = json.loads(ci_file.read_text(encoding="utf-8"))
        features = data.get("features", [])
    except Exception as e:
        return CriticalInfrastructureSummary(
            available=False,
            status="error",
            reason_if_unavailable=f"Failed to read critical infrastructure GeoJSON: {e}",
        ), []

    items: List[CriticalAssetItem] = []
    exposed_features: List[Dict[str, Any]] = []
    by_category: Dict[str, int] = {}
    total_count = 0
    exposed_count = 0

    to_raster_crs = None
    if depth_ds.crs and not depth_ds.crs.is_geographic:
        to_raster_crs = Transformer.from_crs("EPSG:4326", depth_ds.crs, always_xy=True)

    inv_transform = ~depth_ds.transform
    h, w = depth_arr.shape

    for idx, feat in enumerate(features):
        props = dict(feat.get("properties") or {})
        geom_json = feat.get("geometry")
        if not geom_json:
            continue

        geom = shape(geom_json)
        orig_cat, norm_cat = normalize_critical_asset_category(props)

        if norm_cat == "unknown" and ci_file.name.startswith("hidkal_assets"):
            continue

        total_count += 1
        pt = geom.centroid if geom.geom_type != "Point" else geom
        sx, sy = pt.x, pt.y
        if to_raster_crs:
            sx, sy = to_raster_crs.transform(sx, sy)

        col, row = [int(v) for v in inv_transform @ (sx, sy)]
        if 0 <= row < h and 0 <= col < w:
            d = float(depth_arr[row, col]) if not np.isnan(depth_arr[row, col]) else 0.0
            v = float(vel_arr[row, col]) if vel_arr is not None and not np.isnan(vel_arr[row, col]) else None
            a = float(arr_arr[row, col]) if arr_arr is not None and not np.isnan(arr_arr[row, col]) else None
        else:
            d, v, a = 0.0, None, None

        is_exposed = bool(d >= threshold_m)
        hazard_band_name = None
        arrival_window_name = None

        if is_exposed:
            exposed_count += 1
            by_category[norm_cat] = by_category.get(norm_cat, 0) + 1

            for b in depth_bands:
                b_name = b["name"]
                b_min = b["min_depth"]
                b_max = b.get("max_depth")
                if b_max is not None:
                    if b_min <= d < b_max:
                        hazard_band_name = b_name
                        break
                else:
                    if d >= b_min:
                        hazard_band_name = b_name
                        break

            if a is not None and arrival_windows and 0.0 <= a < 9000.0:
                for w_win in arrival_windows:
                    w_name = w_win["name"]
                    w_min = w_win["min_s"]
                    w_max = w_win.get("max_s")
                    if w_max is not None:
                        if w_min <= a < w_max:
                            arrival_window_name = w_name
                            break
                    else:
                        if a >= w_min:
                            arrival_window_name = w_name
                            break

            asset_id = str(feat.get("id") or props.get("id") or f"ci-{idx+1}")
            asset_name = props.get("name") or props.get("label")

            item = CriticalAssetItem(
                asset_id=asset_id,
                name=asset_name,
                source_category=orig_cat,
                normalized_category=norm_cat,
                depth_m=round(d, 3),
                velocity_mps=round(v, 3) if v is not None else None,
                arrival_time_s=round(a, 2) if a is not None else None,
                hazard_band=hazard_band_name,
                arrival_window=arrival_window_name,
                source_provenance=ci_file.name,
            )
            items.append(item)

            feat_out = {
                "type": "Feature",
                "geometry": geom_json,
                "properties": {
                    "asset_id": asset_id,
                    "name": asset_name,
                    "category": norm_cat,
                    "depth_m": round(d, 3),
                    "velocity_mps": round(v, 3) if v is not None else None,
                    "arrival_time_s": round(a, 2) if a is not None else None,
                    "hazard_band": hazard_band_name,
                    "source": ci_file.name,
                },
            }
            exposed_features.append(feat_out)

    summary = CriticalInfrastructureSummary(
        available=True,
        status="available",
        source_dataset=ci_file.name,
        total_critical_assets=total_count,
        exposed_critical_assets=exposed_count,
        exposed_by_category=by_category,
        assets=items,
    )
    return summary, exposed_features


def compute_lulc_exposure(
    lulc_info: Dict[str, Any],
    depth_ds: rasterio.io.DatasetReader,
    depth_arr: np.ndarray,
    threshold_m: float,
) -> LULCExposureSummary:
    """
    Categorical nearest-neighbour LULC flooded area calculation.
    """
    if not lulc_info.get("available") or not lulc_info.get("file_path"):
        return LULCExposureSummary(
            available=False,
            status="not_provided",
            reason_if_unavailable=lulc_info.get("reason", "LULC raster not provided"),
        )

    lulc_file = lulc_info["file_path"]
    try:
        with rasterio.open(lulc_file) as lulc_src:
            from rasterio.warp import reproject, Resampling
            aligned_lulc = np.zeros(depth_arr.shape, dtype=np.int32)
            reproject(
                source=rasterio.band(lulc_src, 1),
                destination=aligned_lulc,
                src_transform=lulc_src.transform,
                src_crs=lulc_src.crs,
                dst_transform=depth_ds.transform,
                dst_crs=depth_ds.crs,
                resampling=Resampling.nearest,
            )

            px_area_m2 = abs(depth_ds.transform.a * depth_ds.transform.e)
            if depth_ds.crs and depth_ds.crs.is_geographic:
                lat_c = (depth_ds.bounds.top + depth_ds.bounds.bottom) / 2.0
                px_area_m2 = abs(depth_ds.transform.a * 111320.0 * math.cos(math.radians(lat_c)) * depth_ds.transform.e * 111320.0)

            wet_mask = (depth_arr >= threshold_m) & (~np.isnan(depth_arr))
            wet_lulc = aligned_lulc[wet_mask]

            classes_out: List[LULCClassExposure] = []
            total_flooded_m2 = 0.0

            unique_codes, counts = np.unique(wet_lulc, return_counts=True)
            for code, count in zip(unique_codes, counts):
                code_int = int(code)
                if code_int <= 0:
                    continue
                cls_name = DEFAULT_LULC_LEGEND.get(code_int, f"class_{code_int}")
                fl_m2 = float(count * px_area_m2)
                fl_km2 = float(fl_m2 / 1e6)
                total_flooded_m2 += fl_m2

                classes_out.append(
                    LULCClassExposure(
                        class_id=code_int,
                        class_name=cls_name,
                        flooded_area_m2=round(fl_m2, 2),
                        flooded_area_km2=round(fl_km2, 4),
                    )
                )

            return LULCExposureSummary(
                available=True,
                status="available",
                source_dataset=lulc_file.name,
                total_flooded_area_km2=round(total_flooded_m2 / 1e6, 4),
                classes=classes_out,
                resampling_method="nearest_neighbour",
            )
    except Exception as e:
        logger.exception("Failed to calculate LULC exposure: %s", e)
        return LULCExposureSummary(
            available=False,
            status="error",
            reason_if_unavailable=f"Error evaluating LULC exposure: {e}",
        )


def evaluate_vulnerability_and_damage(
    bldg_summary: BuildingExposureSummary,
    exposed_buildings: List[Dict[str, Any]],
) -> DamageEstimationSummary:
    """
    Separation of exposure from vulnerability.
    Computes relative damage ratio ONLY when documented curve matches asset class.
    Suppresses monetary values; rupee loss is never fabricated.
    """
    if not bldg_summary.available or bldg_summary.buildings_exposed == 0:
        return DamageEstimationSummary(
            vulnerability_available=False,
            monetary_damage_available=False,
            reason_if_unavailable="No exposed building assets to evaluate against vulnerability curves.",
        )

    ratios: List[float] = []
    for feat in exposed_buildings:
        props = feat.get("properties") or {}
        usage = props.get("usage", "unknown")
        depth = props.get("maximum_depth_m", 0.0)

        curve_id = None
        if usage == "residential":
            curve_id = "JRC_global_flood_depth_damage_residential_v1"
        elif usage == "commercial":
            curve_id = "JRC_global_flood_depth_damage_commercial_v1"
        elif usage == "industrial":
            curve_id = "JRC_global_flood_depth_damage_industrial_v1"

        if curve_id and curve_id in CURVE_CONTROL_POINTS:
            pts = CURVE_CONTROL_POINTS[curve_id]
            d_vals = [p[0] for p in pts]
            r_vals = [p[1] for p in pts]
            ratio = float(np.interp(depth, d_vals, r_vals))
            ratios.append(max(0.0, min(1.0, ratio)))

    if not ratios:
        return DamageEstimationSummary(
            vulnerability_available=False,
            monetary_damage_available=False,
            reason_if_unavailable="No exposed assets matched validated vulnerability curves (e.g. unknown usage). Generic curves were not applied.",
        )

    avg_ratio = round(float(np.mean(ratios)), 3)

    return DamageEstimationSummary(
        vulnerability_available=True,
        monetary_damage_available=False,
        reason_if_unavailable="Authoritative local asset valuation dataset is not provided. Monetary rupee loss is strictly suppressed.",
        relative_damage_index=avg_ratio,
        monetary_damage=None,
        currency=None,
        valuation_year=None,
        value_source=None,
    )


def compute_decision_support_priority_index(
    pop_summary: PopulationExposureSummary,
    bldg_summary: BuildingExposureSummary,
    road_summary: RoadExposureSummary,
    ci_summary: CriticalInfrastructureSummary,
    hazard_contract: Dict[str, Any],
    exposed_ci_features: List[Dict[str, Any]],
    exposed_bldg_features: List[Dict[str, Any]],
    custom_weights: Optional[Dict[str, float]] = None,
) -> DecisionSupportPrioritySummary:
    """
    Computes transparent decision-support priority index (0-100) and identifies hotspots.
    Explicitly labeled heuristic priority index; NOT true disaster risk or fatality probability.
    """
    weights = dict(DEFAULT_PRIORITY_WEIGHTS)
    weights_label = "heuristic_default"
    if custom_weights:
        weights.update(custom_weights)
        weights_label = "user_configured"

    w_sum = sum(weights.values()) or 1.0
    norm_w = {k: v / w_sum for k, v in weights.items()}

    pop_exp = pop_summary.population_in_inundation_extent or 0.0
    s_pop = min(100.0, (pop_exp / 1000.0) * 100.0) if pop_summary.available else 0.0

    ci_exp = ci_summary.exposed_critical_assets
    s_ci = min(100.0, ci_exp * 20.0) if ci_summary.available else 0.0

    road_aff_km = road_summary.affected_road_length_km
    s_road = min(100.0, (road_aff_km / 10.0) * 100.0) if road_summary.available else 0.0

    max_d = road_summary.max_depth_m or 0.0
    s_depth = min(100.0, (max_d / 5.0) * 100.0)

    composite = (
        norm_w["population"] * s_pop
        + norm_w["critical_infrastructure"] * s_ci
        + norm_w["roads"] * s_road
        + norm_w["hazard_depth"] * s_depth
    )
    composite = round(min(100.0, max(0.0, composite)), 1)

    formula = (
        f"{norm_w['population']:.2f} * S_pop ({s_pop:.1f}) + "
        f"{norm_w['critical_infrastructure']:.2f} * S_crit ({s_ci:.1f}) + "
        f"{norm_w['roads']:.2f} * S_road ({s_road:.1f}) + "
        f"{norm_w['hazard_depth']:.2f} * S_depth ({s_depth:.1f})"
    )

    hotspots: List[DecisionSupportHotspot] = []
    for feat in exposed_ci_features:
        props = feat.get("properties") or {}
        geom = shape(feat.get("geometry"))
        d = props.get("depth_m", 0.0)
        cat = props.get("category", "unknown")
        if d >= 0.5:
            pt = geom.centroid
            h_score = min(100.0, 50.0 + (d * 15.0))
            hotspots.append(
                DecisionSupportHotspot(
                    hotspot_id=f"hotspot-ci-{props.get('asset_id')}",
                    name=f"Critical {cat.capitalize()} Inundation Hotspot",
                    latitude=round(pt.y, 5),
                    longitude=round(pt.x, 5),
                    priority_score=round(h_score, 1),
                    reasons=[f"Critical facility ({cat}) exposed to flood depth of {d:.2f} m"],
                    hazard_depth_m=round(d, 2),
                    exposed_features=[cat],
                )
            )

    for feat in exposed_bldg_features[:5]:
        props = feat.get("properties") or {}
        d = props.get("maximum_depth_m", 0.0)
        if d >= 2.0:
            geom = shape(feat.get("geometry"))
            pt = geom.centroid
            hotspots.append(
                DecisionSupportHotspot(
                    hotspot_id=f"hotspot-bldg-{props.get('feature_id')}",
                    name="Severe Depth Settlement Cluster Hotspot",
                    latitude=round(pt.y, 5),
                    longitude=round(pt.x, 5),
                    priority_score=min(100.0, round(40.0 + (d * 12.0), 1)),
                    reasons=[f"Building structure exposed to deep hydrodynamic hazard ({d:.2f} m)"],
                    hazard_depth_m=round(d, 2),
                    exposed_features=["settlement_building"],
                )
            )

    return DecisionSupportPrioritySummary(
        composite_index=composite,
        formula=formula,
        weights={k: round(v, 3) for k, v in norm_w.items()},
        weights_label=weights_label,
        normalization_method="linear_clamped_standardized_domain_score",
        hotspots=hotspots[:15],
    )


def execute_exposure_run(project_id: str, request: ExposureRunRequest) -> ExposureRunDetailResponse:
    """
    Execute project-scoped exposure and vulnerability assessment run:
    - Resolves real completed hazard rasters
    - Samples population, buildings, roads, critical assets, LULC
    - Calculates depth bands, arrival windows, vulnerability curves, priority index
    - Persists outputs under runtime/dam_projects/{project_id}/exposure_runs/{exposure_run_id}/
    """
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid
    if not p_dir.is_dir() and not request.synthetic_test_fixture:
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found")

    run_id = f"exp-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = get_project_exposure_dir(valid_pid) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    log_file = run_dir / "processing.log"
    log_messages: List[str] = [f"[{datetime.now(timezone.utc).isoformat()}] Initializing Exposure Run {run_id} for project {valid_pid}"]

    depth_bands = request.depth_bands or DEFAULT_DEPTH_BANDS
    arrival_windows = request.arrival_windows or DEFAULT_ARRIVAL_WINDOWS

    hazard_contract, layer_paths = resolve_hazard_layers(
        valid_pid,
        hazard_engine=request.hazard_engine,
        hazard_run_id=request.hazard_run_id,
        synthetic_fixture=bool(request.synthetic_test_fixture),
    )
    log_messages.append(f"Hazard source resolved: {request.hazard_engine} (Run: {request.hazard_run_id})")

    if request.synthetic_test_fixture:
        transform = from_bounds(74.0, 16.0, 75.0, 17.0, 10, 10)
        depth_arr = np.array([
            [0.0, 0.05, 0.2, 0.6, 1.2, 2.5, 3.5, 4.0, 0.0, 0.0],
            [0.0, 0.08, 0.3, 0.8, 1.5, 2.8, 3.8, 4.5, 0.0, 0.0],
            [0.0, 0.00, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.00, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.00, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.00, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.00, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.00, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.00, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.00, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        ], dtype=np.float32)
        vel_arr = np.full((10, 10), 1.5, dtype=np.float32)
        arr_arr = np.full((10, 10), 1200.0, dtype=np.float32)

        dummy_depth_tif = run_dir / "fixture_depth.tif"
        with rasterio.open(
            dummy_depth_tif,
            "w",
            driver="GTiff",
            height=10,
            width=10,
            count=1,
            dtype=depth_arr.dtype,
            crs="EPSG:4326",
            transform=transform,
        ) as dst:
            dst.write(depth_arr, 1)

        depth_ds = rasterio.open(dummy_depth_tif)
    else:
        depth_tif = layer_paths["maximum_depth"]
        depth_ds = rasterio.open(depth_tif)
        depth_arr = depth_ds.read(1)

        vel_arr = None
        if "maximum_velocity" in layer_paths:
            with rasterio.open(layer_paths["maximum_velocity"]) as v_src:
                vel_arr = v_src.read(1)

        arr_arr = None
        if "arrival_time" in layer_paths:
            with rasterio.open(layer_paths["arrival_time"]) as a_src:
                arr_arr = a_src.read(1)

    exp_datasets = resolve_project_exposure_datasets(valid_pid)

    log_messages.append("Evaluating population exposure...")
    pop_summary = compute_population_exposure(
        pop_info=exp_datasets.get("population", {"available": False}),
        depth_ds=depth_ds,
        depth_arr=depth_arr,
        threshold_m=request.depth_threshold_m,
        depth_bands=depth_bands,
        unit_override=request.population_unit_override,
        arr_arr=arr_arr,
        arrival_windows=arrival_windows,
    )

    log_messages.append("Evaluating building exposure...")
    bldg_summary, exposed_bldg_feats = compute_building_exposure(
        bldg_info=exp_datasets.get("buildings", {"available": False}),
        depth_ds=depth_ds,
        depth_arr=depth_arr,
        threshold_m=request.depth_threshold_m,
        depth_bands=depth_bands,
        vel_arr=vel_arr,
        arr_arr=arr_arr,
    )

    log_messages.append("Evaluating road network exposure...")
    road_summary, affected_road_feats = compute_road_exposure(
        roads_info=exp_datasets.get("roads", {"available": False}),
        depth_ds=depth_ds,
        depth_arr=depth_arr,
        threshold_m=request.depth_threshold_m,
        depth_bands=depth_bands,
        passability_depth_threshold_m=request.passability_depth_threshold_m,
    )

    log_messages.append("Evaluating critical infrastructure exposure...")
    ci_summary, exposed_ci_feats = compute_critical_infrastructure_exposure(
        ci_info=exp_datasets.get("critical_infrastructure", {"available": False}),
        depth_ds=depth_ds,
        depth_arr=depth_arr,
        threshold_m=request.depth_threshold_m,
        depth_bands=depth_bands,
        vel_arr=vel_arr,
        arr_arr=arr_arr,
        arrival_windows=arrival_windows,
    )

    log_messages.append("Evaluating LULC exposure...")
    lulc_summary = compute_lulc_exposure(
        lulc_info=exp_datasets.get("lulc", {"available": False}),
        depth_ds=depth_ds,
        depth_arr=depth_arr,
        threshold_m=request.depth_threshold_m,
    )

    log_messages.append("Evaluating vulnerability curves and damage estimation...")
    damage_summary = evaluate_vulnerability_and_damage(bldg_summary, exposed_bldg_feats)

    log_messages.append("Calculating decision-support priority index and hotspots...")
    priority_summary = compute_decision_support_priority_index(
        pop_summary=pop_summary,
        bldg_summary=bldg_summary,
        road_summary=road_summary,
        ci_summary=ci_summary,
        hazard_contract=hazard_contract,
        exposed_ci_features=exposed_ci_feats,
        exposed_bldg_features=exposed_bldg_feats,
        custom_weights=request.priority_weights,
    )

    depth_ds.close()

    any_available = any([
        pop_summary.available,
        bldg_summary.available,
        road_summary.available,
        ci_summary.available,
        lulc_summary.available,
    ])
    all_available = all([
        pop_summary.available,
        bldg_summary.available,
        road_summary.available,
        ci_summary.available,
        lulc_summary.available,
    ])
    status = "completed" if all_available else ("partial" if any_available else "completed")

    created_at = datetime.now(timezone.utc).isoformat()

    provenance = {
        "run_id": run_id,
        "project_id": valid_pid,
        "created_at": created_at,
        "hazard_contract": hazard_contract,
        "depth_threshold_m": request.depth_threshold_m,
        "exposure_datasets": {
            k: {
                "available": v.get("available"),
                "source": v.get("source"),
                "reason": v.get("reason"),
            }
            for k, v in exp_datasets.items()
        },
        "scientific_invariants": {
            "exposed_population_not_casualties": True,
            "inundated_building_not_destroyed": True,
            "flooded_road_not_impassable": True,
            "modelled_arrival_not_guaranteed_warning": True,
            "zero_fabricated_monetary_loss": True,
            "priority_index_is_heuristic": True,
        },
    }

    (run_dir / "request.json").write_text(json.dumps(request.model_dump(), indent=2), encoding="utf-8")

    stats_data = {
        "run_id": run_id,
        "project_id": valid_pid,
        "status": status,
        "created_at": created_at,
        "population": pop_summary.model_dump(),
        "buildings": bldg_summary.model_dump(),
        "roads": road_summary.model_dump(),
        "critical_infrastructure": ci_summary.model_dump(),
        "lulc": lulc_summary.model_dump(),
        "vulnerability_and_damage": damage_summary.model_dump(),
        "decision_support_priority": priority_summary.model_dump(),
    }
    (run_dir / "statistics.json").write_text(json.dumps(stats_data, indent=2), encoding="utf-8")
    (run_dir / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    if exposed_bldg_feats or exposed_ci_feats:
        all_assets_fc = {
            "type": "FeatureCollection",
            "features": exposed_ci_feats + exposed_bldg_feats,
        }
        (run_dir / "assets_exposed.geojson").write_text(json.dumps(all_assets_fc, indent=2), encoding="utf-8")

    if affected_road_feats:
        roads_fc = {
            "type": "FeatureCollection",
            "features": affected_road_feats,
        }
        (run_dir / "roads_exposed.geojson").write_text(json.dumps(roads_fc, indent=2), encoding="utf-8")

    log_messages.append(f"[{datetime.now(timezone.utc).isoformat()}] Run {run_id} completed with status: {status}")
    log_file.write_text("\n".join(log_messages), encoding="utf-8")

    return ExposureRunDetailResponse(
        run_id=run_id,
        project_id=valid_pid,
        status=status,
        created_at=created_at,
        hazard_contract=hazard_contract,
        depth_threshold_m=request.depth_threshold_m,
        depth_bands=depth_bands,
        arrival_windows=arrival_windows,
        population=pop_summary,
        buildings=bldg_summary,
        roads=road_summary,
        critical_infrastructure=ci_summary,
        lulc=lulc_summary,
        vulnerability_and_damage=damage_summary,
        decision_support_priority=priority_summary,
        provenance=provenance,
        scientific_caveats=SCIENTIFIC_CAVEATS,
        message=f"Exposure assessment executed successfully with status '{status}'.",
    )


def list_project_exposure_runs(project_id: str) -> List[ExposureRunSummary]:
    """List all persisted exposure runs for a project."""
    valid_pid = validate_project_uuid(project_id)
    exp_dir = get_project_exposure_dir(valid_pid)

    summaries: List[ExposureRunSummary] = []
    if not exp_dir.is_dir():
        return summaries

    for r_dir in sorted(exp_dir.iterdir(), reverse=True):
        if not r_dir.is_dir():
            continue
        stats_file = r_dir / "statistics.json"
        prov_file = r_dir / "provenance.json"
        if stats_file.is_file():
            try:
                stats = json.loads(stats_file.read_text(encoding="utf-8"))
                prov = json.loads(prov_file.read_text(encoding="utf-8")) if prov_file.is_file() else {}
                h_contract = prov.get("hazard_contract", {})

                pop_sec = stats.get("population", {})
                bldg_sec = stats.get("buildings", {})
                road_sec = stats.get("roads", {})
                ci_sec = stats.get("critical_infrastructure", {})
                pri_sec = stats.get("decision_support_priority", {})

                summaries.append(
                    ExposureRunSummary(
                        run_id=r_dir.name,
                        project_id=valid_pid,
                        hazard_engine=h_contract.get("engine", "unknown"),
                        hazard_run_id=h_contract.get("run_id"),
                        status=stats.get("status", "completed"),
                        created_at=stats.get("created_at", ""),
                        depth_threshold_m=prov.get("depth_threshold_m", 0.10),
                        population_exposed=pop_sec.get("population_in_inundation_extent"),
                        buildings_exposed=bldg_sec.get("buildings_exposed"),
                        affected_road_length_km=road_sec.get("affected_road_length_km"),
                        critical_assets_exposed=ci_sec.get("exposed_critical_assets"),
                        priority_score=pri_sec.get("composite_index"),
                        scientific_status=h_contract.get("scientific_status", "decision_support_screening"),
                    )
                )
            except Exception:
                pass
    return summaries


def get_exposure_run_detail(project_id: str, run_id: str) -> ExposureRunDetailResponse:
    """Retrieve full details of a persisted exposure run."""
    valid_pid = validate_project_uuid(project_id)
    clean_rid = validate_comparison_uuid(run_id)
    r_dir = get_project_exposure_dir(valid_pid) / clean_rid
    if not r_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Exposure run '{clean_rid}' not found")

    stats_file = r_dir / "statistics.json"
    prov_file = r_dir / "provenance.json"
    req_file = r_dir / "request.json"

    if not stats_file.is_file():
        raise HTTPException(status_code=404, detail=f"Statistics file missing in exposure run '{clean_rid}'")

    stats = json.loads(stats_file.read_text(encoding="utf-8"))
    prov = json.loads(prov_file.read_text(encoding="utf-8")) if prov_file.is_file() else {}
    req = json.loads(req_file.read_text(encoding="utf-8")) if req_file.is_file() else {}

    return ExposureRunDetailResponse(
        run_id=clean_rid,
        project_id=valid_pid,
        status=stats.get("status", "completed"),
        created_at=stats.get("created_at", ""),
        hazard_contract=prov.get("hazard_contract", {}),
        depth_threshold_m=prov.get("depth_threshold_m", 0.10),
        depth_bands=req.get("depth_bands") or DEFAULT_DEPTH_BANDS,
        arrival_windows=req.get("arrival_windows") or DEFAULT_ARRIVAL_WINDOWS,
        population=PopulationExposureSummary(**stats.get("population", {})),
        buildings=BuildingExposureSummary(**stats.get("buildings", {})),
        roads=RoadExposureSummary(**stats.get("roads", {})),
        critical_infrastructure=CriticalInfrastructureSummary(**stats.get("critical_infrastructure", {})),
        lulc=LULCExposureSummary(**stats.get("lulc", {})),
        vulnerability_and_damage=DamageEstimationSummary(**stats.get("vulnerability_and_damage", {})),
        decision_support_priority=DecisionSupportPrioritySummary(**stats.get("decision_support_priority", {})),
        provenance=prov,
        scientific_caveats=SCIENTIFIC_CAVEATS,
        message=f"Exposure run '{clean_rid}' loaded successfully.",
    )


def get_exposure_run_logs(project_id: str, run_id: str) -> str:
    """Read execution log for an exposure run."""
    valid_pid = validate_project_uuid(project_id)
    clean_rid = validate_comparison_uuid(run_id)
    log_file = get_project_exposure_dir(valid_pid) / clean_rid / "processing.log"
    if not log_file.is_file():
        raise HTTPException(status_code=404, detail=f"Logs for exposure run '{clean_rid}' not found")
    return log_file.read_text(encoding="utf-8")


def get_exposure_run_assets_geojson(project_id: str, run_id: str) -> Dict[str, Any]:
    """Retrieve exposed assets GeoJSON (buildings and critical assets)."""
    valid_pid = validate_project_uuid(project_id)
    clean_rid = validate_comparison_uuid(run_id)
    geojson_file = get_project_exposure_dir(valid_pid) / clean_rid / "assets_exposed.geojson"
    if not geojson_file.is_file():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(geojson_file.read_text(encoding="utf-8"))


def get_exposure_run_roads_geojson(project_id: str, run_id: str) -> Dict[str, Any]:
    """Retrieve affected road segments GeoJSON."""
    valid_pid = validate_project_uuid(project_id)
    clean_rid = validate_comparison_uuid(run_id)
    geojson_file = get_project_exposure_dir(valid_pid) / clean_rid / "roads_exposed.geojson"
    if not geojson_file.is_file():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(geojson_file.read_text(encoding="utf-8"))


def get_exposure_run_layers(project_id: str, run_id: str) -> Dict[str, Any]:
    """List available spatial visual layers for an exposure run."""
    valid_pid = validate_project_uuid(project_id)
    clean_rid = validate_comparison_uuid(run_id)
    r_dir = get_project_exposure_dir(valid_pid) / clean_rid
    if not r_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Exposure run '{clean_rid}' not found")

    has_assets = (r_dir / "assets_exposed.geojson").is_file()
    has_roads = (r_dir / "roads_exposed.geojson").is_file()

    return {
        "run_id": clean_rid,
        "project_id": valid_pid,
        "layers": {
            "assets_exposed": {
                "available": has_assets,
                "type": "geojson",
                "endpoint": f"/api/dam-projects/{valid_pid}/exposure/runs/{clean_rid}/assets",
            },
            "roads_exposed": {
                "available": has_roads,
                "type": "geojson",
                "endpoint": f"/api/dam-projects/{valid_pid}/exposure/runs/{clean_rid}/roads",
            },
        },
    }

"""
ANUGA Regional Hydrodynamic Pilot Result Service (Phase 16 & 17).
Manages registered ANUGA pilot runs (Phase 15 baseline and Phase 17 refined adaptive),
metadata, manifest provenance validation, layer GeoTIFF resolution (EPSG:32643),
tile rendering with bilinear/nearest resampling, and coordinate reprojection.
"""

import io
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from rio_tiler.io import Reader
from rio_tiler.errors import TileOutsideBounds, PointOutsideBounds
from fastapi import HTTPException

from app.schemas import (
    HazardSourceInfo,
    HazardSourcesResponse,
    ANUGARunSummary,
    ANUGARunDetailResponse,
    RasterBounds,
    RasterResolution,
    RasterMetadataResponse,
    RasterPointValueResponse,
    ColorRampStop,
    LegendItem,
    RasterLegendResponse,
)
from app.raster_service import get_project_root, EMPTY_TILE_PNG

# Whitelisted ANUGA Runs & Layer Registries
REGISTERED_ANUGA_RUNS = {
    "anuga_hidkal_pilot_hypothetical_v1": {
        "title": "Hypothetical Pilot Dam-Break Hydrodynamic Simulation (Phase 15 Baseline)",
        "site": "Hidkal (Raja Lakhamagowda Dam) study area, Ghataprabha Basin",
        "scenario_status": "hypothetical_unverified",
        "relative_dir": "validation/anuga_hidkal_pilot",
        "projected_crs": "EPSG:32643",
        "prefix": "anuga_hidkal_pilot",
        "hazard_source": "anuga_hidkal_pilot",
        "mesh_type": "uniform_triangular_200m",
    },
    "anuga_hidkal_refined_hypothetical_v1": {
        "title": "Hypothetical Refined Adaptive Dam-Break Hydrodynamic Simulation (Phase 17)",
        "site": "Hidkal (Raja Lakhamagowda Dam) study area, Ghataprabha Basin",
        "scenario_status": "hypothetical_unverified",
        "relative_dir": "validation/anuga_hidkal_refined",
        "projected_crs": "EPSG:32643",
        "prefix": "anuga_hidkal_refined",
        "hazard_source": "anuga_hidkal_refined",
        "mesh_type": "adaptive_unstructured_50m_breach",
    },
}

ANUGA_LAYERS = {
    "depth": {
        "label": "Hypothetical ANUGA Inundation Depth",
        "data_type": "depth",
        "unit_status": "assumed metres based on source interpretation",
        "provenance_status": "hypothetical ANUGA pilot — not a forecast or validated Hidkal prediction",
        "nodata": -9999.0,
    },
    "velocity": {
        "label": "Hypothetical ANUGA Flow Velocity",
        "data_type": "velocity",
        "unit_status": "m/s (assumed from unverified DEM interpretation)",
        "provenance_status": "hypothetical ANUGA pilot — not a forecast or validated Hidkal prediction",
        "nodata": -9999.0,
    },
    "arrival": {
        "label": "Hypothetical ANUGA First Arrival Time",
        "data_type": "arrival_time",
        "unit_status": "seconds (model-derived first detected arrival at 60 s output resolution; 0s=reservoir)",
        "provenance_status": "hypothetical ANUGA pilot — not a forecast or validated Hidkal prediction",
        "nodata": 9999.0,
    },
}

# Colormap and legend definitions for ANUGA layers
ANUGA_STYLES: Dict[str, Dict[str, Any]] = {
    "depth": {
        "min": 0.1,
        "max": 25.0,
        "stops": [
            (0.1, (168, 218, 220, 230), "#a8dadc", "0.1 (Shallow Inundation, assumed metres)"),
            (1.0, (69, 123, 157, 240), "#457b9d", "1.0 (Moderate Depth, assumed metres)"),
            (5.0, (29, 53, 87, 245), "#1d3557", "5.0 (Deep Channel Flow, assumed metres)"),
            (15.0, (114, 9, 183, 255), "#7209b7", "15.0 (Severe Valley Ponding, assumed metres)"),
            (25.0, (58, 12, 163, 255), "#3a0ca3", "> 20 (Breach Channel Maximum, assumed metres)"),
        ],
    },
    "velocity": {
        "min": 0.1,
        "max": 16.0,
        "stops": [
            (0.1, (255, 238, 140, 230), "#ffee8c", "0.1 (Low Velocity, m/s)"),
            (2.0, (255, 179, 71, 240), "#ffb347", "2.0 (Moderate Velocity, m/s)"),
            (5.0, (255, 105, 97, 245), "#ff6961", "5.0 (Fast Flow, m/s)"),
            (8.0, (194, 59, 34, 255), "#c23b22", "8.0 (High Hazard Jet, m/s)"),
            (16.0, (100, 20, 10, 255), "#64140a", "> 12 (Breach Jet Peak Velocity, m/s)"),
        ],
    },
    "arrival": {
        "min": 0.0,
        "max": 1800.0,
        "stops": [
            (0.0, (50, 50, 200, 255), "#3232c8", "0.0 s (Initially Wet Reservoir Pool)"),
            (60.0, (230, 57, 70, 245), "#e63946", "60 s (Immediate Breach Wave Impact)"),
            (300.0, (244, 162, 97, 240), "#f4a261", "300 s (5 min Propagation)"),
            (600.0, (233, 196, 106, 235), "#e9c46a", "600 s (10 min Propagation)"),
            (1200.0, (42, 157, 143, 235), "#2a9d8f", "1200 s (20 min Propagation)"),
            (1800.0, (38, 70, 83, 245), "#264653", "1800 s (30 min Domain Extent)"),
        ],
    },
}

# Coordinate Transformer (EPSG:4326 -> EPSG:32643)
_wgs84_to_utm43n = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
_utm43n_to_wgs84 = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)

# In-memory validation & metadata cache
_anuga_cache: Dict[str, Any] = {}


def get_anuga_dir(run_id_or_source: str = "anuga_hidkal_pilot") -> Path:
    """Path to ANUGA simulation directory for specified run or hazard source."""
    if run_id_or_source in ("anuga_hidkal_refined", "anuga_hidkal_refined_hypothetical_v1"):
        return get_project_root() / "validation" / "anuga_hidkal_refined"
    if run_id_or_source in REGISTERED_ANUGA_RUNS:
        return get_project_root() / REGISTERED_ANUGA_RUNS[run_id_or_source]["relative_dir"]
    return get_project_root() / "validation" / "anuga_hidkal_pilot"


def check_anuga_outputs_available(run_id: str = "anuga_hidkal_pilot_hypothetical_v1") -> Tuple[bool, Optional[str]]:
    """
    Check if required ANUGA scenario files, summary, and GeoTIFF outputs are present on disk.
    Never crashes when ignored outputs are absent.
    """
    if run_id not in REGISTERED_ANUGA_RUNS:
        return False, f"Unknown ANUGA run identifier '{run_id}'"

    meta = REGISTERED_ANUGA_RUNS[run_id]
    pilot_dir = get_anuga_dir(run_id)
    summary_file = pilot_dir / "pilot_summary.json"
    if not summary_file.is_file():
        return False, f"Pilot summary JSON for '{run_id}' not found. Simulation must be run."

    output_dir = pilot_dir / "output"
    missing_layers = []
    prefix = meta["prefix"]
    for layer in ANUGA_LAYERS.keys():
        fname = f"{prefix}_{layer}.tif"
        tif_path = output_dir / fname
        if not tif_path.is_file():
            missing_layers.append(fname)

    if missing_layers:
        return False, f"Generated GeoTIFF rasters absent: {', '.join(missing_layers)}"

    return True, None


def get_hazard_sources() -> HazardSourcesResponse:
    """Return catalog of available hazard sources (Sample, Baseline ANUGA Pilot, and Refined ANUGA Model)."""
    pilot_avail, pilot_reason = check_anuga_outputs_available("anuga_hidkal_pilot_hypothetical_v1")
    refined_avail, refined_reason = check_anuga_outputs_available("anuga_hidkal_refined_hypothetical_v1")

    sources = [
        HazardSourceInfo(
            id="sample_hidkal",
            label="Existing Unverified Sample Rasters",
            status="unverified_sample",
            disclaimer="Preliminary screening based on unverified sample rasters of unknown provenance. Not a validated hydrodynamic prediction.",
            vertical_unit_status="unverified",
            available=True,
            default_screening_threshold=0.0,
            layers=["depth", "velocity", "arrival"],
            run_id=None,
        ),
        HazardSourceInfo(
            id="anuga_hidkal_pilot",
            label="Hypothetical ANUGA Hidkal Pilot (Phase 15 Baseline, 200m mesh)",
            status="hypothetical_unverified",
            disclaimer="Hypothetical ANUGA pilot — not a forecast or validated Hidkal prediction. Assumed vertical units based on source interpretation.",
            vertical_unit_status="assumed metres based on source interpretation",
            available=pilot_avail,
            availability_reason=pilot_reason,
            default_screening_threshold=0.10,
            layers=list(ANUGA_LAYERS.keys()),
            run_id="anuga_hidkal_pilot_hypothetical_v1",
        ),
        HazardSourceInfo(
            id="anuga_hidkal_refined",
            label="Hypothetical ANUGA Hidkal Refined Model (Phase 17, Adaptive <=50m mesh)",
            status="hypothetical_unverified",
            disclaimer="Hypothetical refined ANUGA pilot — not a forecast or validated Hidkal prediction. Assumed vertical units based on source interpretation.",
            vertical_unit_status="assumed metres based on source interpretation",
            available=refined_avail,
            availability_reason=refined_reason,
            default_screening_threshold=0.10,
            layers=list(ANUGA_LAYERS.keys()),
            run_id="anuga_hidkal_refined_hypothetical_v1",
        ),
    ]

    return HazardSourcesResponse(
        default_source="sample_hidkal",
        sources=sources,
        scientific_notice="Hazard sources represent different computational and grid refinement stages. Never treat sample rasters or pilot simulations as verified forecasts."
    )


def validate_anuga_manifest(run_id: str = "anuga_hidkal_pilot_hypothetical_v1") -> Tuple[bool, List[str]]:
    """
    Validate SHA-256 hashes of all provenance files in the run's manifest.json.
    Returns (is_valid, list_of_errors).
    """
    if run_id not in REGISTERED_ANUGA_RUNS:
        return False, [f"Unknown ANUGA run identifier '{run_id}'"]

    run_dir = get_anuga_dir(run_id)
    manifest_file = run_dir / "manifest.json"
    if not manifest_file.is_file():
        return False, ["manifest.json is missing on disk."]

    try:
        with open(manifest_file, "r") as f:
            manifest_data = json.load(f)
    except Exception:
        return False, ["Failed to parse manifest.json format."]

    files_map = manifest_data.get("files", {})
    errors = []
    for rel_name, expected_hash in files_map.items():
        file_path = run_dir / rel_name
        if not file_path.is_file():
            errors.append(f"Provenance file '{rel_name}' is missing on disk.")
            continue
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        actual_hash = h.hexdigest()
        if actual_hash != expected_hash:
            errors.append(f"SHA-256 hash mismatch for '{rel_name}': expected {expected_hash}, got {actual_hash}")

    return (len(errors) == 0), errors


def list_anuga_runs() -> List[ANUGARunSummary]:
    """List all registered ANUGA pilot runs with honest availability status and dynamically parsed provenance metrics."""
    runs = []
    for run_id, meta in REGISTERED_ANUGA_RUNS.items():
        run_dir = get_anuga_dir(run_id)
        summary_file = run_dir / "pilot_summary.json"
        avail, reason = check_anuga_outputs_available(run_id)

        summary_data = {}
        if summary_file.is_file():
            try:
                with open(summary_file, "r") as f:
                    summary_data = json.load(f)
            except Exception:
                pass

        sim_exec = summary_data.get("computational_statistics", {})
        breach_mech = summary_data.get("breach_mechanics", {})
        vol_diag = summary_data.get("volume_conservation", {})
        spatial = summary_data.get("spatial_parameters", {})
        mesh_stats = summary_data.get("mesh_statistics", {})

        grid_dims = spatial.get("grid_dimensions", [222, 301])
        raster_cells_total = int(spatial.get("total_raster_cells", grid_dims[0] * grid_dims[1]))
        raster_cells_valid = int(spatial.get("valid_arrival_cells", 4482))
        initial_vol_m3 = float(vol_diag.get("initial_volume_assumed_m3", 317161860.23))
        initial_vol_mcm = round(initial_vol_m3 / 1e6, 6)

        runs.append(
            ANUGARunSummary(
                run_id=run_id,
                scenario_status=meta["scenario_status"],
                title=meta["title"],
                site=meta["site"],
                timestamp_utc=summary_data.get("timestamp_utc"),
                available=avail,
                availability_reason=reason,
                breach_width_m=float(breach_mech.get("effective_breach_width_m", 200.0)),
                simulated_duration_sec=float(sim_exec.get("simulated_duration_sec", 1800.0)),
                saved_yield_frames=int(sim_exec.get("saved_yield_frames", 31)),
                arrival_time_resolution_sec=60.0,
                initial_volume_assumed_mcm=initial_vol_mcm,
                mesh_triangles=int(mesh_stats.get("total_triangles", 66000)),
                mesh_vertices=int(mesh_stats.get("total_vertices", 33261)),
                raster_cells_total=raster_cells_total,
                raster_cells_valid=raster_cells_valid,
                screening_threshold_label="0.10 assumed metres",
                velocity_unit_label="assumed m/s",
                volume_unit_label="assumed MCM",
                disclaimer="Hypothetical ANUGA pilot — not a forecast or validated Hidkal prediction.",
            )
        )
    return runs


def get_anuga_run_detail(run_id: str) -> ANUGARunDetailResponse:
    """Retrieve complete provenance, diagnostics, and layer manifest for an ANUGA run."""
    if run_id not in REGISTERED_ANUGA_RUNS:
        raise HTTPException(status_code=404, detail=f"ANUGA run '{run_id}' not found.")

    meta = REGISTERED_ANUGA_RUNS[run_id]
    run_dir = get_anuga_dir(run_id)
    summary_file = run_dir / "pilot_summary.json"
    manifest_file = run_dir / "manifest.json"

    if not summary_file.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Pilot summary JSON for '{run_id}' not found. Please ensure simulation has executed."
        )

    with open(summary_file, "r") as f:
        summary = json.load(f)

    manifest_data = {}
    if manifest_file.is_file():
        with open(manifest_file, "r") as f:
            manifest_data = json.load(f)

    # Manifest integrity validation
    manifest_valid, manifest_errors = validate_anuga_manifest(run_id)
    if not manifest_valid:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "provenance_integrity_failed",
                "message": f"ANUGA run '{run_id}' failed manifest provenance integrity check.",
                "errors": manifest_errors,
            },
        )

    avail, reason = check_anuga_outputs_available(run_id)

    prefix = meta["prefix"]
    layer_info = {}
    for l_key, l_val in ANUGA_LAYERS.items():
        fname = f"{prefix}_{l_key}.tif"
        layer_path = run_dir / "output" / fname
        layer_info[l_key] = {
            "label": f"{l_val['label']} ({meta['prefix']})",
            "data_type": l_val["data_type"],
            "unit_status": l_val["unit_status"],
            "file_name": fname,
            "exists": layer_path.is_file(),
            "size_bytes": layer_path.stat().st_size if layer_path.is_file() else 0,
        }

    vol_diag = summary.get("volume_conservation", {})
    initial_vol_m3 = float(vol_diag.get("initial_volume_assumed_m3", 317161860.23))
    initial_vol_mcm = round(initial_vol_m3 / 1e6, 6)
    mesh_stats = summary.get("mesh_statistics", {})
    spatial = summary.get("spatial_parameters", {})
    grid_dims = spatial.get("grid_dimensions", [222, 301])
    raster_cells_total = int(spatial.get("total_raster_cells", grid_dims[0] * grid_dims[1]))
    raster_cells_valid = int(spatial.get("valid_arrival_cells", 4482))

    provenance_metrics = {
        "initial_volume_assumed_m3": initial_vol_m3,
        "initial_volume_assumed_mcm": initial_vol_mcm,
        "mesh_triangles": int(mesh_stats.get("total_triangles", 66000)),
        "mesh_vertices": int(mesh_stats.get("total_vertices", 33261)),
        "raster_grid_dimensions": grid_dims,
        "raster_cells_total": raster_cells_total,
        "raster_cells_valid_arrival": raster_cells_valid,
        "screening_depth_threshold_assumed_m": 0.10,
        "velocity_units": "assumed m/s",
        "volume_units": "assumed m³ / assumed MCM",
        "manifest_verified": manifest_valid,
    }

    return ANUGARunDetailResponse(
        run_id=run_id,
        scenario_status=meta["scenario_status"],
        title=meta["title"],
        site=meta["site"],
        timestamp_utc=summary.get("timestamp_utc"),
        available=avail,
        availability_reason=reason,
        disclaimer="Hypothetical ANUGA pilot — not a forecast or validated Hidkal prediction.",
        assumptions=summary.get("assumptions", {}),
        breach_mechanics=summary.get("breach_mechanics", {}),
        spatial_parameters=summary.get("spatial_parameters", {}),
        computational_statistics=summary.get("computational_statistics", {}),
        boundary_analysis=summary.get("boundary_analysis", {}),
        area_partitioning_km2=summary.get("area_partitioning_km2", {}),
        volume_conservation=summary.get("volume_conservation", {}),
        inundation_results=summary.get("inundation_results", {}),
        mesh_sensitivity=summary.get("mesh_sensitivity"),
        scientific_validity_note=summary.get("scientific_validity_note"),
        provenance_metrics=provenance_metrics,
        layers=layer_info,
        manifest=manifest_data,
    )


def resolve_anuga_layer_file(layer_name: str, hazard_source: Optional[str] = None) -> Tuple[Dict[str, Any], Path]:
    """
    Resolve layer information and GeoTIFF path strictly against registered ANUGA layers.
    Handles source distinction between 'anuga_hidkal_pilot' and 'anuga_hidkal_refined'.
    Prevents path traversal and arbitrary filesystem input.
    """
    raw_key = layer_name.lower().strip()

    # Determine hazard source & base layer
    if raw_key.startswith("anuga_hidkal_refined_"):
        source = "anuga_hidkal_refined"
        base_layer = raw_key.replace("anuga_hidkal_refined_", "")
    elif raw_key.startswith("anuga_hidkal_pilot_"):
        source = "anuga_hidkal_pilot"
        base_layer = raw_key.replace("anuga_hidkal_pilot_", "")
    else:
        if hazard_source and ("refined" in hazard_source.lower()):
            source = "anuga_hidkal_refined"
        else:
            source = "anuga_hidkal_pilot"
        base_layer = raw_key

    if base_layer not in ANUGA_LAYERS:
        raise HTTPException(
            status_code=404,
            detail=f"Invalid ANUGA layer '{layer_name}'. Whitelisted layers: {list(ANUGA_LAYERS.keys())}"
        )

    info = ANUGA_LAYERS[base_layer].copy()
    run_dir = get_anuga_dir(source)
    fname = f"{source}_{base_layer}.tif"
    info["file_name"] = fname
    tif_path = run_dir / "output" / fname

    if not tif_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"ANUGA raster '{fname}' is not available on disk."
        )

    return info, tif_path


def get_anuga_raster_metadata(layer_name: str, hazard_source: Optional[str] = None) -> RasterMetadataResponse:
    """Retrieve metadata for an ANUGA pilot GeoTIFF raster."""
    info, tif_path = resolve_anuga_layer_file(layer_name, hazard_source=hazard_source)
    mtime = tif_path.stat().st_mtime
    cache_key = f"meta_{tif_path.name}"

    if cache_key in _anuga_cache and _anuga_cache[cache_key][0] == mtime:
        return _anuga_cache[cache_key][1]

    with rasterio.open(tif_path) as src:
        bounds = RasterBounds(
            left=float(src.bounds.left),
            bottom=float(src.bounds.bottom),
            right=float(src.bounds.right),
            top=float(src.bounds.top),
        )
        res = RasterResolution(
            x=float(abs(src.res[0])),
            y=float(abs(src.res[1])),
        )
        arr = src.read(1)
        nodata = float(src.nodata) if src.nodata is not None else info["nodata"]

        valid_mask = ~np.isnan(arr)
        if nodata is not None:
            valid_mask &= ~np.isclose(arr, nodata)
            if "arrival" in layer_name:
                valid_mask &= ~np.isclose(arr, -9999.0) & ~np.isclose(arr, 9999.0) & (arr < 9000.0)

        valid_min = float(np.min(arr[valid_mask])) if np.any(valid_mask) else None
        valid_max = float(np.max(arr[valid_mask])) if np.any(valid_mask) else None

        resp = RasterMetadataResponse(
            id=f"{info['file_name'].replace('.tif', '')}",
            width=int(src.width),
            height=int(src.height),
            dtype=str(src.dtypes[0]),
            crs=str(src.crs),
            bounds=bounds,
            resolution=res,
            nodata=nodata,
            valid_min=valid_min,
            valid_max=valid_max,
        )

    _anuga_cache[cache_key] = (mtime, resp)
    return resp


def get_anuga_raster_point_value(
    layer_name: str,
    lon: float,
    lat: float,
    hazard_source: Optional[str] = None
) -> RasterPointValueResponse:
    """
    Point query at given WGS84 coordinates (lon, lat).
    Transforms (lon, lat) to UTM 43N (EPSG:32643) and samples the ANUGA raster.
    """
    info, tif_path = resolve_anuga_layer_file(layer_name, hazard_source=hazard_source)

    # Validate lon/lat ranges
    if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
        raise HTTPException(status_code=422, detail=f"Coordinates ({lon}, {lat}) out of valid geographic range.")

    # Coordinate transformation: EPSG:4326 -> EPSG:32643
    x_utm, y_utm = _wgs84_to_utm43n.transform(lon, lat)

    with rasterio.open(tif_path) as src:
        bounds = src.bounds
        if not (bounds.left <= x_utm <= bounds.right and bounds.bottom <= y_utm <= bounds.top):
            raise HTTPException(
                status_code=422,
                detail=f"Transformed coordinates ({x_utm:.1f}, {y_utm:.1f}) are outside raster bounds."
            )

        col, row = [int(v) for v in (~src.transform) @ (x_utm, y_utm)]
        col = min(max(col, 0), src.width - 1)
        row = min(max(row, 0), src.height - 1)

        val = float(src.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
        nodata = float(src.nodata) if src.nodata is not None else info["nodata"]

        is_nodata = False
        if np.isnan(val) or (nodata is not None and np.isclose(val, nodata)):
            is_nodata = True
            val = None
        elif "arrival" in layer_name and (np.isclose(val, 9999.0) or np.isclose(val, -9999.0) or val >= 9000.0):
            is_nodata = True
            val = None
        elif ("depth" in layer_name or "velocity" in layer_name) and val < 0.001:
            # Dry terrain
            val = 0.0

        return RasterPointValueResponse(
            id=f"{info['file_name'].replace('.tif', '')}",
            row=row,
            column=col,
            value=round(val, 4) if val is not None else None,
            is_nodata=is_nodata,
        )


def get_anuga_raster_tile(
    layer_name: str,
    z: int,
    x: int,
    y: int,
    hazard_source: Optional[str] = None
) -> bytes:
    """
    Render Web Mercator XYZ PNG tile from ANUGA GeoTIFF with bilinear/nearest colormap
    and crisp transparent dry cells without boundary blurring.
    """
    info, tif_path = resolve_anuga_layer_file(layer_name, hazard_source=hazard_source)
    base_layer = "arrival" if "arrival" in layer_name else ("velocity" if "velocity" in layer_name else "depth")
    style = ANUGA_STYLES.get(base_layer, ANUGA_STYLES["depth"])

    # High-quality rendering: bilinear for continuous depth/velocity, nearest for arrival/categorical
    resampling = "nearest" if (base_layer == "arrival") else "bilinear"

    try:
        with Reader(str(tif_path)) as reader:
            img = reader.tile(x, y, z, resampling_method=resampling)
            data = img.data[0].astype(float)
            mask = img.mask

            nodata = info["nodata"]
            data_mask = mask.astype(bool) & ~np.isnan(data)
            if nodata is not None:
                data_mask &= ~np.isclose(data, nodata)

            if base_layer == "arrival":
                data_mask &= ~np.isclose(data, 9999.0) & ~np.isclose(data, -9999.0) & (data < 9000.0)
            elif base_layer in ("depth", "velocity"):
                data_mask &= (data >= 0.05)

            if not np.any(data_mask):
                return EMPTY_TILE_PNG

            # Render RGBA image
            rgba = np.zeros((data.shape[0], data.shape[1], 4), dtype=np.uint8)
            stops = style["stops"]

            # Interpolate stops
            val_norm = np.clip((data - style["min"]) / (style["max"] - style["min"] + 1e-6), 0.0, 1.0)
            r_chan = np.zeros_like(data, dtype=float)
            g_chan = np.zeros_like(data, dtype=float)
            b_chan = np.zeros_like(data, dtype=float)
            a_chan = np.zeros_like(data, dtype=float)

            # Piecewise color mapping
            for i in range(len(stops) - 1):
                v0, c0, _, _ = stops[i]
                v1, c1, _, _ = stops[i + 1]
                idx = (data >= v0) & (data <= v1) & data_mask
                if np.any(idx):
                    ratio = (data[idx] - v0) / (v1 - v0 + 1e-6)
                    r_chan[idx] = c0[0] + ratio * (c1[0] - c0[0])
                    g_chan[idx] = c0[1] + ratio * (c1[1] - c0[1])
                    b_chan[idx] = c0[2] + ratio * (c1[2] - c0[2])
                    a_chan[idx] = c0[3] + ratio * (c1[3] - c0[3])

            # Edge values
            low_idx = (data < stops[0][0]) & data_mask
            if np.any(low_idx):
                c0 = stops[0][1]
                r_chan[low_idx], g_chan[low_idx], b_chan[low_idx], a_chan[low_idx] = c0[0], c0[1], c0[2], c0[3]

            high_idx = (data > stops[-1][0]) & data_mask
            if np.any(high_idx):
                c1 = stops[-1][1]
                r_chan[high_idx], g_chan[high_idx], b_chan[high_idx], a_chan[high_idx] = c1[0], c1[1], c1[2], c1[3]

            rgba[:, :, 0] = r_chan.astype(np.uint8)
            rgba[:, :, 1] = g_chan.astype(np.uint8)
            rgba[:, :, 2] = b_chan.astype(np.uint8)
            rgba[:, :, 3] = a_chan.astype(np.uint8)

            pil_img = Image.fromarray(rgba, "RGBA")
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            return buf.getvalue()

    except (TileOutsideBounds, PointOutsideBounds):
        return EMPTY_TILE_PNG
    except Exception:
        # Fall back to empty transparent tile without failing
        return EMPTY_TILE_PNG


def get_anuga_raster_legend(layer_name: str, hazard_source: Optional[str] = None) -> RasterLegendResponse:
    """Return colormap stops and legend metadata for an ANUGA layer."""
    info, _ = resolve_anuga_layer_file(layer_name, hazard_source=hazard_source)
    base_layer = "arrival" if "arrival" in layer_name else ("velocity" if "velocity" in layer_name else "depth")
    style = ANUGA_STYLES.get(base_layer, ANUGA_STYLES["depth"])

    color_ramp = []
    items = []
    for val, rgba, hex_code, desc in style["stops"]:
        offset = (val - style["min"]) / (style["max"] - style["min"] + 1e-6)
        color_ramp.append(ColorRampStop(offset=round(float(offset), 3), color=hex_code, value=val))
        items.append(LegendItem(value=val, color=hex_code, label=desc))

    return RasterLegendResponse(
        id=f"{info['file_name'].replace('.tif', '')}",
        label=info["label"],
        unit_status=info["unit_status"],
        provenance_status=info["provenance_status"],
        min_value=style["min"],
        max_value=style["max"],
        color_ramp=color_ramp,
        items=items,
    )

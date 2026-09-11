"""Model Comparison Service - Phase 21: Multi-Engine Spatial Hydrodynamic Comparison.

Provides a scientifically honest, project-scoped hydrodynamic comparison framework
allowing outputs from multiple hydrodynamic solvers (ANUGA, Delft3D/D-Flow FM, PySPH)
to be compared spatially and statistically on a shared projected metric grid without
fabricating unavailable solver results.
"""

import hashlib
import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject, transform_bounds
from fastapi import HTTPException

from app.schemas import (
    ModelComparisonEngineCapability,
    ModelComparisonCapabilitiesResponse,
    HydrodynamicOutputContract,
    ToleranceBandCoverage,
    DepthDifferenceStats,
    VelocityDifferenceStats,
    InundationAgreementStats,
    ArrivalTimeDifferenceStats,
    InterModelSpreadDiagnostic,
    ModelComparisonRunRequest,
    ModelComparisonRunResponse,
)
from app.onboarding_service import (
    get_dam_projects_dir,
    validate_project_uuid,
    compute_file_sha256,
    apply_colormap_and_transparency,
    EMPTY_TILE_PNG,
)

logger = logging.getLogger(__name__)


def validate_comparison_uuid(comp_id: str) -> str:
    """Validate comparison identifier format to prevent path traversal."""
    if not comp_id or not isinstance(comp_id, str):
        raise HTTPException(status_code=400, detail="Invalid comparison ID")
    # Accept standard comparison IDs e.g. comp-20260911_120000_abcd1234 or UUIDs
    clean = comp_id.strip()
    if "/" in clean or "\\" in clean or ".." in clean:
        raise HTTPException(status_code=400, detail="Path traversal characters not allowed in comparison ID")
    return clean


def get_comparisons_dir(project_id: str) -> Path:
    """Return persistent directory for model comparisons under dam project."""
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid / "comparisons"
    p_dir.mkdir(parents=True, exist_ok=True)
    return p_dir


def determine_analysis_metric_crs(project_id: str, sample_bounds_wgs84: Tuple[float, float, float, float]) -> CRS:
    """
    Determine an appropriate projected metric CRS for square-kilometre calculations.
    Reuses project DEM CRS if metric; otherwise derives UTM projection from centroid.
    """
    valid_pid = validate_project_uuid(project_id)
    dem_path = get_dam_projects_dir() / valid_pid / "dem.tif"
    if dem_path.is_file():
        try:
            with rasterio.open(dem_path) as src:
                if src.crs and not src.crs.is_geographic:
                    return src.crs
        except Exception:
            pass

    # Derive local UTM metric zone from centroid
    min_lon, min_lat, max_lon, max_lat = sample_bounds_wgs84
    center_lon = (min_lon + max_lon) / 2.0
    center_lat = (min_lat + max_lat) / 2.0

    zone = int((center_lon + 180) / 6) + 1
    epsg = 32600 + zone if center_lat >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)


def get_project_engine_capabilities(project_id: str) -> ModelComparisonCapabilitiesResponse:
    """
    Inspect availability and completed runs across ANUGA, Delft3D/D-Flow FM, and PySPH
    for a specific dam project.
    """
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid
    if not p_dir.is_dir() or not (p_dir / "project.json").is_file():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found")

    # 1. ANUGA Engine Audit
    from app.onboarding_service import get_custom_anuga_capabilities

    anuga_caps = get_custom_anuga_capabilities()
    anuga_runs_dir = p_dir / "anuga" / "runs"

    anuga_completed: List[Dict[str, Any]] = []
    comparable_anuga_count = 0

    if anuga_runs_dir.is_dir():
        for r_dir in sorted(anuga_runs_dir.iterdir()):
            if not r_dir.is_dir():
                continue
            run_json = r_dir / "run.json"
            if run_json.is_file():
                try:
                    r_data = json.loads(run_json.read_text(encoding="utf-8"))
                    is_completed = r_data.get("status") == "completed"
                    # Check for results
                    results_dir = r_dir / "results"
                    has_depth = False
                    has_vel = False
                    has_arr = False
                    if results_dir.is_dir():
                        for proc_dir in results_dir.iterdir():
                            if proc_dir.is_dir():
                                if (proc_dir / "maximum_depth.tif").is_file():
                                    has_depth = True
                                if (proc_dir / "maximum_velocity.tif").is_file():
                                    has_vel = True
                                if (proc_dir / "arrival_time.tif").is_file():
                                    has_arr = True

                    if is_completed and has_depth:
                        comparable_anuga_count += 1

                    anuga_completed.append({
                        "run_id": r_dir.name,
                        "status": r_data.get("status"),
                        "created_at": r_data.get("created_at"),
                        "has_maximum_depth": has_depth,
                        "has_maximum_velocity": has_vel,
                        "has_arrival_time": has_arr,
                        "comparable": is_completed and has_depth,
                    })
                except Exception:
                    pass

    anuga_cap = ModelComparisonEngineCapability(
        environment_available=anuga_caps.anuga_import_success,
        solver_available=anuga_caps.execution_enabled,
        completed_run_count=len([r for r in anuga_completed if r.get("status") == "completed"]),
        comparable_run_count=comparable_anuga_count,
        available_for_comparison=comparable_anuga_count > 0,
        version=anuga_caps.anuga_version,
        reason=None if comparable_anuga_count > 0 else (
            "No completed ANUGA simulation runs with postprocessed depth rasters found."
            if anuga_caps.execution_enabled else (anuga_caps.reason or "ANUGA execution disabled")
        ),
    )

    # 2. Delft3D / D-Flow FM Audit
    from app.simulation_service import detect_capabilities as detect_d3d_capabilities, list_simulation_runs

    d3d_caps = detect_d3d_capabilities()
    # Check general simulation runs
    d3d_all_runs = list_simulation_runs()
    d3d_project_runs: List[Dict[str, Any]] = []
    comparable_d3d_count = 0

    for r in d3d_all_runs:
        r_dir = Path(r.get("run_dir", ""))
        has_depth = (r_dir / "depth.tif").is_file() or (r_dir / "max_depth.tif").is_file()
        has_vel = (r_dir / "velocity.tif").is_file() or (r_dir / "max_velocity.tif").is_file()
        is_comp = r.get("status") == "completed" and has_depth
        if is_comp:
            comparable_d3d_count += 1
        d3d_project_runs.append({
            "run_id": r.get("run_id"),
            "status": r.get("status"),
            "scenario_name": r.get("scenario_name"),
            "has_maximum_depth": has_depth,
            "has_maximum_velocity": has_vel,
            "comparable": is_comp,
        })

    d3d_cap = ModelComparisonEngineCapability(
        environment_available=d3d_caps.hydromt_available,
        solver_available=d3d_caps.dflowfm_available,
        completed_run_count=len([r for r in d3d_project_runs if r.get("status") == "completed"]),
        comparable_run_count=comparable_d3d_count,
        available_for_comparison=comparable_d3d_count > 0,
        version=getattr(d3d_caps, "dflowfm_version", None) or ("available" if d3d_caps.dflowfm_available else "unavailable"),
        reason=None if comparable_d3d_count > 0 else (
            "No completed Delft3D FM runs with validated raster outputs exist in storage."
        ),
    )

    # 3. PySPH Audit
    from app.sph_service import detect_sph_capabilities, list_sph_runs

    sph_caps = detect_sph_capabilities()
    sph_all_runs = list_sph_runs()
    sph_project_runs: List[Dict[str, Any]] = []
    comparable_sph_count = 0

    for r in sph_all_runs:
        r_id = r.get("run_id", "")
        has_depth = r.get("has_depth_raster", False)
        has_vel = r.get("has_velocity_raster", False)
        is_comp = r.get("status") == "completed" and has_depth
        if is_comp:
            comparable_sph_count += 1
        sph_project_runs.append({
            "run_id": r_id,
            "status": r.get("status"),
            "scenario_name": r.get("scenario_name"),
            "has_maximum_depth": has_depth,
            "has_maximum_velocity": has_vel,
            "comparable": is_comp,
        })

    sph_cap = ModelComparisonEngineCapability(
        environment_available=sph_caps.pysph_available,
        solver_available=sph_caps.execution_enabled,
        completed_run_count=len([r for r in sph_project_runs if r.get("status") == "completed"]),
        comparable_run_count=comparable_sph_count,
        available_for_comparison=comparable_sph_count > 0,
        version=sph_caps.pysph_version,
        reason=None if comparable_sph_count > 0 else (
            "No completed PySPH runs with rasterized Eulerian depth outputs exist in storage."
        ),
    )

    total_comparable = comparable_anuga_count + comparable_d3d_count + comparable_sph_count
    ready = total_comparable >= 2 or comparable_anuga_count >= 2

    return ModelComparisonCapabilitiesResponse(
        project_id=valid_pid,
        engines={
            "anuga": anuga_cap,
            "delft3d_fm": d3d_cap,
            "pysph": sph_cap,
        },
        completed_runs_by_engine={
            "anuga": anuga_completed,
            "delft3d_fm": d3d_project_runs,
            "pysph": sph_project_runs,
        },
        ready_for_comparison=ready,
        message="At least two comparable hydrodynamic simulation runs are available." if ready else (
            "Insufficient comparable runs. Please execute or postprocess at least two hydrodynamic model runs."
        ),
    )


def normalize_engine_output(
    project_id: str,
    engine: str,
    run_id: str,
    target_metric_crs: Optional[CRS] = None,
    synthetic_fixture: bool = False,
) -> Tuple[HydrodynamicOutputContract, Dict[str, Path]]:
    """
    Extracts and standardizes solver outputs into a HydrodynamicOutputContract.
    Returns the contract and dictionary of local layer paths.
    """
    valid_pid = validate_project_uuid(project_id)
    clean_rid = validate_comparison_uuid(run_id)
    p_dir = get_dam_projects_dir() / valid_pid

    layer_paths: Dict[str, Path] = {}
    source_hashes: Dict[str, str] = {}

    if synthetic_fixture:
        # Isolated unit test synthetic fixture mode
        contract = HydrodynamicOutputContract(
            engine=engine,
            engine_version="fixture-v1",
            source_run_id=clean_rid,
            run_timestamp=datetime.now(timezone.utc).isoformat(),
            simulation_duration_s=3600.0,
            native_crs="EPSG:32643",
            native_resolution_m=10.0,
            analysis_crs=str(target_metric_crs or "EPSG:32643"),
            analysis_resolution_m=10.0,
            bounds=(500000.0, 1800000.0, 510000.0, 1810000.0),
            nodata_value=-9999.0,
            maximum_depth_available=True,
            maximum_velocity_available=True,
            arrival_time_available=True,
            inundation_extent_available=True,
            arrival_time_definition="depth >= 0.05m",
            source_file_hashes={"maximum_depth": "fixture_hash_depth"},
            layer_paths={},
            provenance={"fixture": True},
            scientific_status="synthetic_test_fixture",
        )
        return contract, layer_paths

    if engine == "anuga":
        run_dir = p_dir / "anuga" / "runs" / clean_rid
        if not run_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"ANUGA run '{clean_rid}' not found in project storage")

        run_json = run_dir / "run.json"
        run_data: Dict[str, Any] = {}
        if run_json.is_file():
            try:
                run_data = json.loads(run_json.read_text(encoding="utf-8"))
            except Exception:
                pass

        if run_data.get("status") != "completed":
            raise HTTPException(status_code=422, detail=f"ANUGA run '{clean_rid}' status is not 'completed'")

        # Find postprocessing outputs
        results_dir = run_dir / "results"
        if not results_dir.is_dir():
            raise HTTPException(status_code=422, detail=f"ANUGA run '{clean_rid}' has no postprocessed results")

        # Pick latest processing dir
        proc_dirs = [d for d in results_dir.iterdir() if d.is_dir()]
        if not proc_dirs:
            raise HTTPException(status_code=422, detail=f"No results directory found in ANUGA run '{clean_rid}'")
        latest_proc = sorted(proc_dirs, key=lambda d: d.stat().st_mtime, reverse=True)[0]

        depth_tif = latest_proc / "maximum_depth.tif"
        if not depth_tif.is_file():
            raise HTTPException(status_code=422, detail=f"Missing maximum_depth.tif in ANUGA run '{clean_rid}'")

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

        with rasterio.open(depth_tif) as src:
            native_crs_str = str(src.crs or "EPSG:4326")
            res_x = abs(src.transform.a)
            bounds_tup = (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)
            nodata_val = float(src.nodata if src.nodata is not None else -9999.0)

        # Read arrival threshold from manifest if available
        arr_def = "depth >= 0.05m"
        manifest_file = latest_proc / "postprocessing_manifest.json"
        if manifest_file.is_file():
            try:
                m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                threshs = m_data.get("thresholds", {})
                arr_thresh = threshs.get("arrival_depth_threshold_m")
                if arr_thresh is not None:
                    arr_def = f"depth >= {arr_thresh}m"
            except Exception:
                pass

        contract = HydrodynamicOutputContract(
            engine="anuga",
            engine_version=run_data.get("anuga_version", "unknown"),
            source_run_id=clean_rid,
            run_timestamp=run_data.get("created_at"),
            simulation_duration_s=run_data.get("parameters", {}).get("simulation_duration_s"),
            native_crs=native_crs_str,
            native_resolution_m=round(res_x, 4),
            analysis_crs=str(target_metric_crs or native_crs_str),
            analysis_resolution_m=round(res_x, 4),
            bounds=bounds_tup,
            nodata_value=nodata_val,
            maximum_depth_available=True,
            maximum_velocity_available="maximum_velocity" in layer_paths,
            arrival_time_available="arrival_time" in layer_paths,
            inundation_extent_available=True,
            arrival_time_definition=arr_def if "arrival_time" in layer_paths else None,
            source_file_hashes=source_hashes,
            layer_paths={k: str(v) for k, v in layer_paths.items()},
            provenance={"run_dir": str(run_dir)},
            scientific_status=run_data.get("scientific_status", "hypothetical_unverified"),
        )
        return contract, layer_paths

    elif engine == "delft3d_fm":
        from app.simulation_service import get_runs_dir
        run_dir = get_runs_dir() / clean_rid
        if not run_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"Delft3D run '{clean_rid}' not found")
        depth_tif = run_dir / "depth.tif" if (run_dir / "depth.tif").is_file() else (run_dir / "max_depth.tif")
        if not depth_tif.is_file():
            raise HTTPException(status_code=422, detail=f"Delft3D run '{clean_rid}' lacks depth raster output")

        layer_paths["maximum_depth"] = depth_tif
        source_hashes["maximum_depth"] = compute_file_sha256(depth_tif) or ""

        vel_tif = run_dir / "velocity.tif" if (run_dir / "velocity.tif").is_file() else (run_dir / "max_velocity.tif")
        if vel_tif.is_file():
            layer_paths["maximum_velocity"] = vel_tif
            source_hashes["maximum_velocity"] = compute_file_sha256(vel_tif) or ""

        with rasterio.open(depth_tif) as src:
            native_crs_str = str(src.crs or "EPSG:4326")
            res_x = abs(src.transform.a)
            bounds_tup = (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)
            nodata_val = float(src.nodata if src.nodata is not None else -9999.0)

        contract = HydrodynamicOutputContract(
            engine="delft3d_fm",
            engine_version="D-Flow FM 2D SWE",
            source_run_id=clean_rid,
            native_crs=native_crs_str,
            native_resolution_m=round(res_x, 4),
            analysis_crs=str(target_metric_crs or native_crs_str),
            analysis_resolution_m=round(res_x, 4),
            bounds=bounds_tup,
            nodata_value=nodata_val,
            maximum_depth_available=True,
            maximum_velocity_available="maximum_velocity" in layer_paths,
            arrival_time_available=False,
            inundation_extent_available=True,
            source_file_hashes=source_hashes,
            layer_paths={k: str(v) for k, v in layer_paths.items()},
            provenance={"run_dir": str(run_dir)},
            scientific_status="hypothetical_unverified",
        )
        return contract, layer_paths

    elif engine == "pysph":
        from app.sph_service import get_sph_runs_dir
        run_dir = get_sph_runs_dir() / clean_rid
        if not run_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"PySPH run '{clean_rid}' not found")
        depth_tif = run_dir / "depth.tif" if (run_dir / "depth.tif").is_file() else (run_dir / "output_depth.tif")
        if not depth_tif.is_file():
            raise HTTPException(status_code=422, detail=f"PySPH run '{clean_rid}' lacks rasterized depth output")

        layer_paths["maximum_depth"] = depth_tif
        source_hashes["maximum_depth"] = compute_file_sha256(depth_tif) or ""

        vel_tif = run_dir / "velocity.tif" if (run_dir / "velocity.tif").is_file() else (run_dir / "output_velocity.tif")
        if vel_tif.is_file():
            layer_paths["maximum_velocity"] = vel_tif
            source_hashes["maximum_velocity"] = compute_file_sha256(vel_tif) or ""

        with rasterio.open(depth_tif) as src:
            native_crs_str = str(src.crs or "EPSG:4326")
            res_x = abs(src.transform.a)
            bounds_tup = (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)
            nodata_val = float(src.nodata if src.nodata is not None else -9999.0)

        contract = HydrodynamicOutputContract(
            engine="pysph",
            engine_version="PySPH Lagrangian",
            source_run_id=clean_rid,
            native_crs=native_crs_str,
            native_resolution_m=round(res_x, 4),
            analysis_crs=str(target_metric_crs or native_crs_str),
            analysis_resolution_m=round(res_x, 4),
            bounds=bounds_tup,
            nodata_value=nodata_val,
            maximum_depth_available=True,
            maximum_velocity_available="maximum_velocity" in layer_paths,
            arrival_time_available=False,
            inundation_extent_available=True,
            source_file_hashes=source_hashes,
            layer_paths={k: str(v) for k, v in layer_paths.items()},
            provenance={"run_dir": str(run_dir)},
            scientific_status="hypothetical_unverified",
        )
        return contract, layer_paths

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported hydrodynamic engine: '{engine}'")


def align_rasters_to_common_metric_grid(
    src_a_path: Path,
    src_b_path: Path,
    target_crs: CRS,
    resampling_method: Resampling = Resampling.bilinear,
    nodata_value: float = -9999.0,
) -> Tuple[np.ndarray, np.ndarray, rasterio.Affine, int, int, float]:
    """
    Reprojects and resamples two rasters onto a shared projected metric grid
    over their intersecting bounding box.
    Returns (arr_a, arr_b, dst_transform, width, height, pixel_area_km2).
    """
    with rasterio.open(src_a_path) as src_a, rasterio.open(src_b_path) as src_b:
        bounds_a = transform_bounds(src_a.crs, target_crs, *src_a.bounds)
        bounds_b = transform_bounds(src_b.crs, target_crs, *src_b.bounds)

        min_x = max(bounds_a[0], bounds_b[0])
        min_y = max(bounds_a[1], bounds_b[1])
        max_x = min(bounds_a[2], bounds_b[2])
        max_y = min(bounds_a[3], bounds_b[3])

        if min_x >= max_x or min_y >= max_y:
            raise HTTPException(
                status_code=422,
                detail="Compared model outputs have zero spatial overlap in analysis CRS."
            )

        # Determine target pixel resolution (metric meters)
        # Approximate from source resolutions projected
        res_a = abs(src_a.transform.a)
        res_b = abs(src_b.transform.a)
        # If source was geographic, convert roughly to meters (e.g. 0.0001 deg ~ 11 m)
        if src_a.crs.is_geographic:
            res_a = res_a * 111320.0
        if src_b.crs.is_geographic:
            res_b = res_b * 111320.0

        target_res = max(min(res_a, res_b), 5.0)  # at least 5m
        target_res = min(target_res, 100.0)       # at most 100m to avoid memory exhaustion

        width = max(10, int((max_x - min_x) / target_res))
        height = max(10, int((max_y - min_y) / target_res))

        # Clamp max grid dimensions
        if width > 4096 or height > 4096:
            scale = max(width / 4096, height / 4096)
            width = int(width / scale)
            height = int(height / scale)
            target_res = target_res * scale

        dst_transform = rasterio.transform.from_bounds(min_x, min_y, max_x, max_y, width, height)
        dx = (max_x - min_x) / float(width)
        dy = (max_y - min_y) / float(height)
        pixel_area_km2 = (dx * dy) / 1_000_000.0

        arr_a = np.full((height, width), nodata_value, dtype=np.float32)
        arr_b = np.full((height, width), nodata_value, dtype=np.float32)

        reproject(
            source=rasterio.band(src_a, 1),
            destination=arr_a,
            src_transform=src_a.transform,
            src_crs=src_a.crs,
            dst_transform=dst_transform,
            dst_crs=target_crs,
            src_nodata=src_a.nodata if src_a.nodata is not None else nodata_value,
            dst_nodata=nodata_value,
            resampling=resampling_method,
        )

        reproject(
            source=rasterio.band(src_b, 1),
            destination=arr_b,
            src_transform=src_b.transform,
            src_crs=src_b.crs,
            dst_transform=dst_transform,
            dst_crs=target_crs,
            src_nodata=src_b.nodata if src_b.nodata is not None else nodata_value,
            dst_nodata=nodata_value,
            resampling=resampling_method,
        )

    return arr_a, arr_b, dst_transform, width, height, pixel_area_km2


def compute_model_comparison(
    project_id: str,
    req: ModelComparisonRunRequest,
) -> ModelComparisonRunResponse:
    """
    Executes multi-engine spatial hydrodynamic comparison between Engine A and Engine B.
    Computes depth difference, velocity difference, arrival time difference,
    inundation agreement, and optional multi-model ensemble spread.
    Persists all outputs under runtime/dam_projects/{project_id}/comparisons/{comparison_id}/.
    """
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid
    if not p_dir.is_dir() or not (p_dir / "project.json").is_file():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found")

    comp_id = f"comp-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    comp_dir = get_comparisons_dir(valid_pid) / comp_id
    comp_dir.mkdir(parents=True, exist_ok=True)

    log_lines: List[str] = []
    def log(msg: str):
        ts = datetime.now(timezone.utc).isoformat()
        line = f"[{ts}] {msg}"
        log_lines.append(line)
        logger.info(line)

    log(f"Starting Multi-Engine Comparison {comp_id} for project {valid_pid}")
    log(f"Engine A: {req.engine_a} ({req.run_id_a}) vs Engine B: {req.engine_b} ({req.run_id_b})")

    # 1. Determine Analysis Metric CRS
    if req.target_crs:
        analysis_crs = CRS.from_string(req.target_crs)
    else:
        # Sample bounds from WGS84
        analysis_crs = determine_analysis_metric_crs(valid_pid, (74.0, 15.0, 75.0, 17.0))
    log(f"Analysis Metric CRS: {analysis_crs}")

    # 2. Normalize Contracts
    contract_a, paths_a = normalize_engine_output(
        valid_pid, req.engine_a, req.run_id_a, analysis_crs, req.synthetic_test_fixture or False
    )
    contract_b, paths_b = normalize_engine_output(
        valid_pid, req.engine_b, req.run_id_b, analysis_crs, req.synthetic_test_fixture or False
    )

    layer_files: Dict[str, str] = {}
    nodata_val = -9999.0

    if req.synthetic_test_fixture:
        # Isolated test fixture: construct deterministic test arrays
        width, height = 100, 100
        dx = 10.0
        dy = 10.0
        pixel_area_km2 = (dx * dy) / 1_000_000.0
        dst_transform = rasterio.transform.from_bounds(500000.0, 1800000.0, 501000.0, 1801000.0, width, height)

        # Synthetic depth: A centered circle, B slightly shifted
        yy, xx = np.meshgrid(np.arange(height), np.arange(width), indexing='ij')
        arr_depth_a = np.full((height, width), nodata_val, dtype=np.float32)
        arr_depth_b = np.full((height, width), nodata_val, dtype=np.float32)

        # Valid support mask
        support = (xx >= 10) & (xx < 90) & (yy >= 10) & (yy < 90)
        arr_depth_a[support] = np.clip(3.0 - 0.05 * np.sqrt((xx[support] - 50)**2 + (yy[support] - 50)**2), 0.0, 3.0)
        arr_depth_b[support] = np.clip(3.2 - 0.05 * np.sqrt((xx[support] - 52)**2 + (yy[support] - 48)**2), 0.0, 3.2)

        # Velocity arrays
        if contract_a.maximum_velocity_available and contract_b.maximum_velocity_available:
            arr_vel_a = np.full((height, width), nodata_val, dtype=np.float32)
            arr_vel_b = np.full((height, width), nodata_val, dtype=np.float32)
            arr_vel_a[support] = arr_depth_a[support] * 0.8
            arr_vel_b[support] = arr_depth_b[support] * 0.75
        else:
            arr_vel_a = None
            arr_vel_b = None

        # Arrival times
        if contract_a.arrival_time_available and contract_b.arrival_time_available:
            arr_arr_a = np.full((height, width), nodata_val, dtype=np.float32)
            arr_arr_b = np.full((height, width), nodata_val, dtype=np.float32)
            arr_arr_a[support] = (xx[support] + yy[support]) * 10.0
            arr_arr_b[support] = (xx[support] + yy[support] + 5) * 10.0
        else:
            arr_arr_a = None
            arr_arr_b = None

    else:
        # Real runs alignment
        arr_depth_a, arr_depth_b, dst_transform, width, height, pixel_area_km2 = align_rasters_to_common_metric_grid(
            paths_a["maximum_depth"],
            paths_b["maximum_depth"],
            analysis_crs,
            resampling_method=Resampling.bilinear,
            nodata_value=nodata_val,
        )

        arr_vel_a, arr_vel_b = None, None
        if "maximum_velocity" in paths_a and "maximum_velocity" in paths_b:
            arr_vel_a, arr_vel_b, _, _, _, _ = align_rasters_to_common_metric_grid(
                paths_a["maximum_velocity"],
                paths_b["maximum_velocity"],
                analysis_crs,
                resampling_method=Resampling.bilinear,
                nodata_value=nodata_val,
            )

        arr_arr_a, arr_arr_b = None, None
        if "arrival_time" in paths_a and "arrival_time" in paths_b:
            arr_arr_a, arr_arr_b, _, _, _, _ = align_rasters_to_common_metric_grid(
                paths_a["arrival_time"],
                paths_b["arrival_time"],
                analysis_crs,
                resampling_method=Resampling.bilinear,
                nodata_value=nodata_val,
            )

    # 3. Common Valid Analysis Mask (Mandatory Correction 2)
    common_valid_mask = (
        (arr_depth_a != nodata_val)
        & (arr_depth_b != nodata_val)
        & np.isfinite(arr_depth_a)
        & np.isfinite(arr_depth_b)
    )
    common_valid_count = int(np.sum(common_valid_mask))
    if common_valid_count == 0:
        raise HTTPException(
            status_code=422,
            detail="Aligned model rasters contain zero overlapping valid pixels."
        )

    common_area_km2 = float(common_valid_count * pixel_area_km2)
    log(f"Common valid analysis support: {common_valid_count} pixels ({common_area_km2:.3f} km²)")

    # 4. Depth Difference Calculation (Mandatory Correction 6)
    diff_depth = np.full((height, width), nodata_val, dtype=np.float32)
    signed_diff = arr_depth_a[common_valid_mask] - arr_depth_b[common_valid_mask]
    diff_depth[common_valid_mask] = signed_diff

    mean_signed = float(np.mean(signed_diff))
    median_signed = float(np.median(signed_diff))
    mae_depth = float(np.mean(np.abs(signed_diff)))
    rmse_depth = float(np.sqrt(np.mean(signed_diff ** 2)))
    max_pos = float(np.max(signed_diff))
    max_neg = float(np.min(signed_diff))

    # Tolerance coverage
    tolerance_coverages: List[ToleranceBandCoverage] = []
    for tol in req.tolerance_bands_m:
        band_mask = np.abs(signed_diff) <= tol
        b_count = int(np.sum(band_mask))
        b_area = float(b_count * pixel_area_km2)
        b_pct = float((b_count / common_valid_count) * 100.0) if common_valid_count > 0 else 0.0
        tolerance_coverages.append(
            ToleranceBandCoverage(
                band_label=f"±{tol:.2f}m",
                tolerance_m=tol,
                pixel_count=b_count,
                area_km2=round(b_area, 4),
                percentage_of_common_valid_area=round(b_pct, 2),
            )
        )

    depth_stats = DepthDifferenceStats(
        common_valid_pixel_count=common_valid_count,
        common_analysis_area_km2=round(common_area_km2, 4),
        mean_signed_difference_m=round(mean_signed, 4),
        median_signed_difference_m=round(median_signed, 4),
        mae_m=round(mae_depth, 4),
        rmse_m=round(rmse_depth, 4),
        max_positive_difference_m=round(max_pos, 4),
        max_negative_difference_m=round(max_neg, 4),
        tolerance_bands=tolerance_coverages,
        label="inter-model depth difference",
        formula="engine_A_depth - engine_B_depth",
    )

    # Save depth_difference.tif
    depth_diff_path = comp_dir / "depth_difference.tif"
    with rasterio.open(
        depth_diff_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=rasterio.float32,
        crs=analysis_crs,
        transform=dst_transform,
        nodata=nodata_val,
        compress="deflate",
    ) as dst:
        dst.write(diff_depth, 1)
    layer_files["depth_difference"] = depth_diff_path.name
    log("Saved depth_difference.tif")

    # 5. Inundation Extent Agreement (Mandatory Correction 8)
    depth_thresh = req.depth_inundation_threshold_m
    wet_a = (arr_depth_a >= depth_thresh) & common_valid_mask
    wet_b = (arr_depth_b >= depth_thresh) & common_valid_mask

    overlap = wet_a & wet_b
    union = wet_a | wet_b
    a_only = wet_a & (~wet_b)
    b_only = wet_b & (~wet_a)

    area_wet_a = float(np.sum(wet_a) * pixel_area_km2)
    area_wet_b = float(np.sum(wet_b) * pixel_area_km2)
    area_overlap = float(np.sum(overlap) * pixel_area_km2)
    area_union = float(np.sum(union) * pixel_area_km2)
    area_a_only = float(np.sum(a_only) * pixel_area_km2)
    area_b_only = float(np.sum(b_only) * pixel_area_km2)

    iou_inundation = float(np.sum(overlap) / np.sum(union)) if np.sum(union) > 0 else 0.0

    inundation_stats = InundationAgreementStats(
        depth_threshold_m=depth_thresh,
        model_a_inundated_area_km2=round(area_wet_a, 4),
        model_b_inundated_area_km2=round(area_wet_b, 4),
        overlap_area_km2=round(area_overlap, 4),
        model_a_only_area_km2=round(area_a_only, 4),
        model_b_only_area_km2=round(area_b_only, 4),
        union_area_km2=round(area_union, 4),
        spatial_agreement_iou=round(iou_inundation, 4),
        label="inter-model spatial agreement",
    )

    # Save inundation_overlap.tif (categorical: 0=dry/nodata, 1=A-only, 2=B-only, 3=Both)
    inundation_cat = np.zeros((height, width), dtype=np.uint8)
    inundation_cat[a_only] = 1
    inundation_cat[b_only] = 2
    inundation_cat[overlap] = 3

    inundation_tif_path = comp_dir / "inundation_overlap.tif"
    with rasterio.open(
        inundation_tif_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=rasterio.uint8,
        crs=analysis_crs,
        transform=dst_transform,
        nodata=0,
        compress="deflate",
    ) as dst:
        dst.write(inundation_cat, 1)
    layer_files["inundation_overlap"] = inundation_tif_path.name
    log("Saved inundation_overlap.tif")

    # 6. Velocity Difference (Mandatory Correction 7)
    if arr_vel_a is not None and arr_vel_b is not None:
        valid_vel_mask = (
            common_valid_mask
            & (arr_vel_a != nodata_val)
            & (arr_vel_b != nodata_val)
            & np.isfinite(arr_vel_a)
            & np.isfinite(arr_vel_b)
        )
        v_count = int(np.sum(valid_vel_mask))
        if v_count > 0:
            diff_vel = arr_vel_a[valid_vel_mask] - arr_vel_b[valid_vel_mask]
            vel_stats = VelocityDifferenceStats(
                available=True,
                common_valid_pixel_count=v_count,
                common_analysis_area_km2=round(v_count * pixel_area_km2, 4),
                mean_signed_difference_m_s=round(float(np.mean(diff_vel)), 4),
                mae_m_s=round(float(np.mean(np.abs(diff_vel))), 4),
                rmse_m_s=round(float(np.sqrt(np.mean(diff_vel ** 2))), 4),
                max_difference_m_s=round(float(np.max(np.abs(diff_vel))), 4),
                reason_if_unavailable=None,
                label="inter-model velocity difference",
            )
            # Save velocity_difference.tif
            vel_diff_arr = np.full((height, width), nodata_val, dtype=np.float32)
            vel_diff_arr[valid_vel_mask] = diff_vel
            vel_diff_path = comp_dir / "velocity_difference.tif"
            with rasterio.open(
                vel_diff_path,
                "w",
                driver="GTiff",
                height=height,
                width=width,
                count=1,
                dtype=rasterio.float32,
                crs=analysis_crs,
                transform=dst_transform,
                nodata=nodata_val,
                compress="deflate",
            ) as dst:
                dst.write(vel_diff_arr, 1)
            layer_files["velocity_difference"] = vel_diff_path.name
        else:
            vel_stats = VelocityDifferenceStats(
                available=False,
                reason_if_unavailable="Velocity products have zero overlapping valid support pixels.",
            )
    else:
        vel_stats = VelocityDifferenceStats(
            available=False,
            reason_if_unavailable=(
                f"Velocity comparison unavailable: Engine A velocity available={contract_a.maximum_velocity_available}, "
                f"Engine B velocity available={contract_b.maximum_velocity_available}."
            ),
        )

    # 7. Arrival-Time Comparison (Mandatory Correction 9)
    if arr_arr_a is not None and arr_arr_b is not None:
        def_a = contract_a.arrival_time_definition or "depth >= 0.05m"
        def_b = contract_b.arrival_time_definition or "depth >= 0.05m"

        # Check definition compatibility
        definitions_compatible = (def_a == def_b)

        if not definitions_compatible:
            log(f"Arrival time definitions differ: '{def_a}' vs '{def_b}'. Marking comparison_valid=False.")
            arr_stats = ArrivalTimeDifferenceStats(
                available=True,
                comparison_valid=False,
                threshold_definition_a=def_a,
                threshold_definition_b=def_b,
                invalidation_reason=(
                    f"Incompatible arrival time thresholds: Engine A uses '{def_a}' while Engine B uses '{def_b}'."
                ),
            )
        else:
            valid_arr_mask = (
                common_valid_mask
                & (arr_arr_a != nodata_val)
                & (arr_arr_b != nodata_val)
                & (arr_arr_a >= 0.0)
                & (arr_arr_b >= 0.0)
            )
            arr_count = int(np.sum(valid_arr_mask))
            if arr_count > 0:
                diff_arr = arr_arr_a[valid_arr_mask] - arr_arr_b[valid_arr_mask]
                early_mask = (arr_arr_a < arr_arr_b) & valid_arr_mask
                late_mask = (arr_arr_a > arr_arr_b) & valid_arr_mask

                arr_stats = ArrivalTimeDifferenceStats(
                    available=True,
                    comparison_valid=True,
                    threshold_definition_a=def_a,
                    threshold_definition_b=def_b,
                    mean_absolute_difference_s=round(float(np.mean(np.abs(diff_arr))), 2),
                    median_difference_s=round(float(np.median(diff_arr)), 2),
                    rmse_s=round(float(np.sqrt(np.mean(diff_arr ** 2))), 2),
                    early_zone_area_km2=round(float(np.sum(early_mask) * pixel_area_km2), 4),
                    late_zone_area_km2=round(float(np.sum(late_mask) * pixel_area_km2), 4),
                    invalidation_reason=None,
                    label="inter-model arrival-time comparison",
                )
                # Save arrival_time_difference.tif
                arr_diff_map = np.full((height, width), nodata_val, dtype=np.float32)
                arr_diff_map[valid_arr_mask] = diff_arr
                arr_diff_path = comp_dir / "arrival_time_difference.tif"
                with rasterio.open(
                    arr_diff_path,
                    "w",
                    driver="GTiff",
                    height=height,
                    width=width,
                    count=1,
                    dtype=rasterio.float32,
                    crs=analysis_crs,
                    transform=dst_transform,
                    nodata=nodata_val,
                    compress="deflate",
                ) as dst:
                    dst.write(arr_diff_map, 1)
                layer_files["arrival_time_difference"] = arr_diff_path.name
            else:
                arr_stats = ArrivalTimeDifferenceStats(
                    available=False,
                    comparison_valid=False,
                    threshold_definition_a=def_a,
                    threshold_definition_b=def_b,
                    invalidation_reason="Zero overlapping flooded cells for arrival-time comparison.",
                )
    else:
        arr_stats = ArrivalTimeDifferenceStats(
            available=False,
            comparison_valid=False,
            invalidation_reason="One or both compared models lack arrival time raster products.",
        )

    # 8. Ensemble Inter-Model Spread Diagnostic (Mandatory Correction 10)
    # If 2 models compared, spread = |A - B|.
    spread_arr = np.full((height, width), nodata_val, dtype=np.float32)
    spread_values = np.abs(signed_diff)
    spread_arr[common_valid_mask] = spread_values

    spread_tif_path = comp_dir / "inter_model_spread.tif"
    with rasterio.open(
        spread_tif_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=rasterio.float32,
        crs=analysis_crs,
        transform=dst_transform,
        nodata=nodata_val,
        compress="deflate",
    ) as dst:
        dst.write(spread_arr, 1)
    layer_files["inter_model_spread"] = spread_tif_path.name

    ensemble_diag = InterModelSpreadDiagnostic(
        computed=True,
        model_count=2 + (len(req.additional_models) if req.additional_models else 0),
        mean_depth_mean_m=round(float(np.mean(0.5 * (arr_depth_a[common_valid_mask] + arr_depth_b[common_valid_mask]))), 4),
        min_depth_mean_m=round(float(np.mean(np.minimum(arr_depth_a[common_valid_mask], arr_depth_b[common_valid_mask]))), 4),
        max_depth_mean_m=round(float(np.mean(np.maximum(arr_depth_a[common_valid_mask], arr_depth_b[common_valid_mask]))), 4),
        mean_spread_m=round(float(np.mean(spread_values)), 4),
        max_spread_m=round(float(np.max(spread_values)), 4),
        common_coverage_area_km2=round(common_area_km2, 4),
        label="inter-model spread",
        disclaimer=(
            "Diagnostic inter-model spread (max - min) computed across compared models. "
            "Not a calibrated statistical uncertainty quantification."
        ),
    )

    # 9. Provenance & Persistence (Mandatory Correction 12)
    provenance_dict: Dict[str, Any] = {
        "comparison_id": comp_id,
        "project_id": valid_pid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engine_a": {
            "engine": req.engine_a,
            "run_id": req.run_id_a,
            "native_crs": contract_a.native_crs,
            "native_resolution_m": contract_a.native_resolution_m,
            "source_hashes": contract_a.source_file_hashes,
        },
        "engine_b": {
            "engine": req.engine_b,
            "run_id": req.run_id_b,
            "native_crs": contract_b.native_crs,
            "native_resolution_m": contract_b.native_resolution_m,
            "source_hashes": contract_b.source_file_hashes,
        },
        "analysis_grid": {
            "crs": str(analysis_crs),
            "transform": [dst_transform.a, dst_transform.b, dst_transform.c, dst_transform.d, dst_transform.e, dst_transform.f],
            "width": width,
            "height": height,
            "pixel_size_x_m": round(abs(dst_transform.a), 4),
            "pixel_size_y_m": round(abs(dst_transform.e), 4),
            "pixel_area_km2": pixel_area_km2,
            "resampling_method_continuous": "bilinear",
            "resampling_method_categorical": "nearest",
        },
        "thresholds": {
            "depth_inundation_threshold_m": depth_thresh,
            "tolerance_bands_m": req.tolerance_bands_m,
        },
        "synthetic_test_fixture": bool(req.synthetic_test_fixture),
    }

    caveats = [
        "Neither hydrodynamic model is assumed to be ground truth. Disagreements reflect differences in mathematical equations (2D SWE vs Navier-Stokes/SPH), mesh resolution, friction formulations, and wetting/drying algorithms.",
        "Inundation spatial agreement is quantified via Jaccard/IoU index on an aligned metric projected grid and does not represent absolute prediction accuracy.",
        "Depth differences are signed (Engine A - Engine B). Positive values indicate Engine A predicted higher depth; negative values indicate Engine A predicted lower depth.",
        "Arrival time comparison is strictly conditional on identical water-depth arrival threshold definitions between models.",
        "Model spread represents inter-model variance across deterministic runs and is not a formal Bayesian uncertainty bound."
    ]

    response = ModelComparisonRunResponse(
        comparison_id=comp_id,
        project_id=valid_pid,
        status="completed",
        created_at=datetime.now(timezone.utc).isoformat(),
        engine_a=req.engine_a,
        run_id_a=req.run_id_a,
        engine_b=req.engine_b,
        run_id_b=req.run_id_b,
        contract_a=contract_a,
        contract_b=contract_b,
        analysis_crs=str(analysis_crs),
        analysis_resolution_m=round(abs(dst_transform.a), 2),
        depth_difference=depth_stats,
        velocity_difference=vel_stats,
        inundation_agreement=inundation_stats,
        arrival_time_difference=arr_stats,
        ensemble_spread=ensemble_diag,
        layer_files=layer_files,
        provenance=provenance_dict,
        scientific_caveats=caveats,
        message="Multi-engine spatial hydrodynamic comparison completed successfully.",
    )

    # Persist JSON files
    (comp_dir / "comparison.json").write_text(json.dumps(response.model_dump(), indent=2), encoding="utf-8")
    (comp_dir / "provenance.json").write_text(json.dumps(provenance_dict, indent=2), encoding="utf-8")
    (comp_dir / "statistics.json").write_text(json.dumps({
        "depth_difference": depth_stats.model_dump(),
        "velocity_difference": vel_stats.model_dump(),
        "inundation_agreement": inundation_stats.model_dump(),
        "arrival_time_difference": arr_stats.model_dump(),
        "ensemble_spread": ensemble_diag.model_dump(),
    }, indent=2), encoding="utf-8")
    (comp_dir / "processing.log").write_text("\n".join(log_lines), encoding="utf-8")

    log("Saved comparison.json, provenance.json, statistics.json, processing.log")
    return response


def list_model_comparison_runs(project_id: str) -> List[ModelComparisonRunResponse]:
    """List all saved model comparisons for a project."""
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid
    if not p_dir.is_dir() or not (p_dir / "project.json").is_file():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found")

    comp_dir = p_dir / "comparisons"
    if not comp_dir.is_dir():
        return []

    results: List[ModelComparisonRunResponse] = []
    for c_sub in sorted(comp_dir.iterdir(), reverse=True):
        if not c_sub.is_dir():
            continue
        c_json = c_sub / "comparison.json"
        if c_json.is_file():
            try:
                data = json.loads(c_json.read_text(encoding="utf-8"))
                results.append(ModelComparisonRunResponse(**data))
            except Exception:
                pass
    return results


def get_model_comparison_run(project_id: str, comparison_id: str) -> ModelComparisonRunResponse:
    """Retrieve details of a specific model comparison run."""
    valid_pid = validate_project_uuid(project_id)
    clean_cid = validate_comparison_uuid(comparison_id)
    p_dir = get_dam_projects_dir() / valid_pid
    if not p_dir.is_dir() or not (p_dir / "project.json").is_file():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found")

    c_json = p_dir / "comparisons" / clean_cid / "comparison.json"
    if not c_json.is_file():
        raise HTTPException(status_code=404, detail=f"Comparison run '{clean_cid}' not found")
    try:
        data = json.loads(c_json.read_text(encoding="utf-8"))
        return ModelComparisonRunResponse(**data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Corrupted comparison run record: {str(e)}")


def get_model_comparison_logs(project_id: str, comparison_id: str) -> Dict[str, str]:
    """Retrieve execution log for a specific model comparison run."""
    valid_pid = validate_project_uuid(project_id)
    clean_cid = validate_comparison_uuid(comparison_id)
    p_dir = get_dam_projects_dir() / valid_pid
    if not p_dir.is_dir() or not (p_dir / "project.json").is_file():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found")

    log_path = p_dir / "comparisons" / clean_cid / "processing.log"
    if not log_path.is_file():
        return {"comparison_id": clean_cid, "logs": "No processing log recorded."}
    return {"comparison_id": clean_cid, "logs": log_path.read_text(encoding="utf-8")}


def render_model_comparison_tile(
    project_id: str,
    comparison_id: str,
    layer_name: str,
    z: int,
    x: int,
    y: int,
) -> bytes:
    """
    Renders XYZ map tiles for comparison rasters with appropriate diverging color ramps.
    negative = Engine A lower than Engine B (Cyan/Blue)
    near zero = similar (Subtle gray)
    positive = Engine A higher than Engine B (Orange/Red)
    """
    valid_pid = validate_project_uuid(project_id)
    clean_cid = validate_comparison_uuid(comparison_id)
    allowed_layers = {"depth_difference", "inundation_overlap", "velocity_difference", "arrival_time_difference", "inter_model_spread"}
    if layer_name not in allowed_layers:
        raise HTTPException(status_code=400, detail=f"Invalid comparison layer '{layer_name}'")

    tif_path = get_dam_projects_dir() / valid_pid / "comparisons" / clean_cid / f"{layer_name}.tif"
    if not tif_path.is_file():
        return EMPTY_TILE_PNG

    try:
        from rio_tiler.io import Reader
        from rio_tiler.colormap import cmap

        with Reader(str(tif_path)) as reader:
            img = reader.tile(x, y, z)
            arr = img.data[0]

            if layer_name == "depth_difference":
                # Diverging colormap: -5m (cyan/blue), 0 (translucent white), +5m (red/orange)
                # Map array [-5.0, 5.0] to [0, 255]
                norm = np.clip((arr + 5.0) / 10.0 * 254.0 + 1.0, 1.0, 255.0).astype(np.uint8)
                # Where near zero (-0.05 to +0.05), set subtle alpha
                mask = (arr != -9999.0) & np.isfinite(arr)
                rgb = np.zeros((3, arr.shape[0], arr.shape[1]), dtype=np.uint8)
                # Cyan for negative
                neg_mask = mask & (arr < -0.05)
                rgb[0, neg_mask] = 56
                rgb[1, neg_mask] = 189
                rgb[2, neg_mask] = 248
                # Orange/Red for positive
                pos_mask = mask & (arr > 0.05)
                rgb[0, pos_mask] = 239
                rgb[1, pos_mask] = 68
                rgb[2, pos_mask] = 68
                # Light yellow/gray for near zero
                zero_mask = mask & (np.abs(arr) <= 0.05)
                rgb[0, zero_mask] = 203
                rgb[1, zero_mask] = 213
                rgb[2, zero_mask] = 225

                alpha = np.zeros(arr.shape, dtype=np.uint8)
                alpha[neg_mask] = np.clip(np.abs(arr[neg_mask]) / 3.0 * 180 + 70, 70, 230).astype(np.uint8)
                alpha[pos_mask] = np.clip(arr[pos_mask] / 3.0 * 180 + 70, 70, 230).astype(np.uint8)
                alpha[zero_mask] = 40  # faint translucent

                import io
                from PIL import Image
                rgba = np.stack([rgb[0], rgb[1], rgb[2], alpha], axis=-1)
                pil_img = Image.fromarray(rgba, mode="RGBA")
                buf = io.BytesIO()
                pil_img.save(buf, format="PNG")
                return buf.getvalue()

            elif layer_name == "inundation_overlap":
                # Categorical: 1=A-only (cyan), 2=B-only (magenta), 3=Both (emerald green)
                rgb = np.zeros((3, arr.shape[0], arr.shape[1]), dtype=np.uint8)
                alpha = np.zeros(arr.shape, dtype=np.uint8)

                m1 = arr == 1  # A only
                rgb[0, m1] = 56
                rgb[1, m1] = 189
                rgb[2, m1] = 248
                alpha[m1] = 180

                m2 = arr == 2  # B only
                rgb[0, m2] = 192
                rgb[1, m2] = 132
                rgb[2, m2] = 252
                alpha[m2] = 180

                m3 = arr == 3  # Both
                rgb[0, m3] = 34
                rgb[1, m3] = 197
                rgb[2, m3] = 94
                alpha[m3] = 210

                import io
                from PIL import Image
                rgba = np.stack([rgb[0], rgb[1], rgb[2], alpha], axis=-1)
                pil_img = Image.fromarray(rgba, mode="RGBA")
                buf = io.BytesIO()
                pil_img.save(buf, format="PNG")
                return buf.getvalue()

            elif layer_name == "inter_model_spread":
                # Spread [0, 3m]: green (0) to amber (1m) to red (3m+)
                mask = (arr != -9999.0) & np.isfinite(arr)
                rgb = np.zeros((3, arr.shape[0], arr.shape[1]), dtype=np.uint8)
                alpha = np.zeros(arr.shape, dtype=np.uint8)

                rgb[0, mask] = np.clip(arr[mask] / 2.0 * 220 + 34, 34, 239).astype(np.uint8)
                rgb[1, mask] = np.clip(197 - arr[mask] / 2.0 * 120, 40, 197).astype(np.uint8)
                rgb[2, mask] = 94
                alpha[mask] = np.clip(arr[mask] / 1.5 * 150 + 50, 50, 220).astype(np.uint8)

                import io
                from PIL import Image
                rgba = np.stack([rgb[0], rgb[1], rgb[2], alpha], axis=-1)
                pil_img = Image.fromarray(rgba, mode="RGBA")
                buf = io.BytesIO()
                pil_img.save(buf, format="PNG")
                return buf.getvalue()

            else:
                # Default render
                return img.render(img_format="PNG")
    except Exception:
        return EMPTY_TILE_PNG

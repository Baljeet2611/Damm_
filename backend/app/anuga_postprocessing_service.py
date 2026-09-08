"""ANUGA SWW Hydrodynamic Simulation Postprocessing Service.

Handles:
- SWW NetCDF reading, dimension validation, and geometry extraction
- Linear triangular mesh interpolation (timestep-first) without non-physical maxima
- Mesh boundary masking (strict NoData outside computational triangles)
- GeoTIFF generation (North-up affine transform, CRS preservation, Deflate compression)
- Multi-run processing isolation under runs/{run_id}/results/{processing_id}/
- Parameter preservation across multiple postprocessing runs
- Layer metadata, statistics, color ramps, legends, point coordinate queries, and tile rendering
"""

import hashlib
import json
import os
import shutil
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import rasterio
from rasterio.crs import CRS
from scipy.io import netcdf_file
from matplotlib.tri import Triangulation, LinearTriInterpolator
from pyproj import Transformer
from rio_tiler.io import Reader
from fastapi import HTTPException

from app.schemas import (
    DamProjectAnugaPostprocessRequest,
    DamProjectAnugaResultsResponse,
    DamProjectAnugaLayerStats,
    DamProjectAnugaPointValueResponse,
    RasterMetadataResponse,
    RasterBounds,
    RasterResolution,
    RasterLegendResponse,
    LegendItem,
    ColorRampStop,
)
from app.onboarding_service import (
    get_dam_projects_dir,
    verify_project_integrity,
    validate_project_uuid,
    validate_run_uuid,
    compute_file_sha256,
    DATASET_STYLES,
    apply_colormap_and_transparency,
    EMPTY_TILE_PNG,
)

VALID_ANUGA_RESULT_LAYERS = {"maximum_depth", "maximum_velocity", "arrival_time"}
ALGO_VERSION = "v1_linear_tri_timestep_first"
MAX_OUTPUT_PIXELS = 2048 * 2048
MAX_GRID_DIMENSION = 2048

_POSTPROCESS_LOCK = threading.Lock()


def validate_sww_file(sww_path: Path) -> Tuple[bool, Optional[str]]:
    """Validate produced SWW file as genuine NetCDF with hydrodynamic variables and valid dimensions."""
    if not sww_path.is_file():
        return False, "SWW file does not exist"
    if sww_path.stat().st_size < 1024:
        return False, f"SWW file size ({sww_path.stat().st_size} bytes) is suspiciously small"

    try:
        ds = netcdf_file(str(sww_path), "r", mmap=False)
        try:
            for req in ["time", "stage", "elevation", "xmomentum", "ymomentum", "x", "y", "volumes"]:
                if req not in ds.variables:
                    return False, f"Missing required variable '{req}' in SWW NetCDF"

            times = ds.variables["time"][:]
            if len(times.shape) != 1 or len(times) < 2:
                return False, f"Variable 'time' must be 1D array with at least 2 timesteps (got shape {times.shape})"

            xs = ds.variables["x"][:]
            ys = ds.variables["y"][:]
            if len(xs.shape) != 1 or len(ys.shape) != 1 or len(xs) != len(ys) or len(xs) < 3:
                return False, f"Variables 'x' and 'y' must be 1D arrays of equal length >= 3 (got x: {xs.shape}, y: {ys.shape})"

            n_points = len(xs)
            volumes = ds.variables["volumes"][:]
            if len(volumes.shape) != 2 or volumes.shape[1] != 3:
                return False, f"Variable 'volumes' must be 2D array of shape (M, 3) (got {volumes.shape})"

            if np.min(volumes) < 0 or np.max(volumes) >= n_points:
                return False, f"Variable 'volumes' contains indices outside point range [0, {n_points - 1}]"

            n_times = len(times)
            for v_name in ["stage", "xmomentum", "ymomentum"]:
                arr = ds.variables[v_name][:]
                if arr.shape != (n_times, n_points):
                    return False, f"Variable '{v_name}' shape {arr.shape} does not match expected (timesteps={n_times}, points={n_points})"
                if not np.all(np.isfinite(arr)):
                    return False, f"Variable '{v_name}' contains non-finite or NaN values"

            elev = ds.variables["elevation"][:]
            if elev.shape not in ((n_points,), (1, n_points), (n_times, n_points)):
                return False, f"Variable 'elevation' shape {elev.shape} is invalid. Expected ({n_points},), (1, {n_points}), or ({n_times}, {n_points})"

            return True, None
        finally:
            ds.close()
    except Exception as e:
        return False, f"Failed to parse SWW NetCDF: {str(e)}"


def compute_processing_identity(
    sww_sha256: str,
    dry_thresh: float,
    arr_thresh: float,
    res_m: Optional[float],
) -> Tuple[str, str]:
    """Calculate deterministic processing identity SHA-256 and processing ID."""
    res_str = f"{res_m:.4f}" if res_m is not None else "auto"
    identity_str = f"{sww_sha256}:{dry_thresh:.6f}:{arr_thresh:.6f}:{res_str}:{ALGO_VERSION}"
    proc_identity_sha256 = hashlib.sha256(identity_str.encode("utf-8")).hexdigest()
    processing_id = f"proc_{proc_identity_sha256[:16]}"
    return proc_identity_sha256, processing_id


def resolve_processing_dir(
    project_id: str,
    run_id: str,
    processing_id: Optional[str] = None,
) -> Tuple[Path, Dict[str, Any]]:
    """Locate results directory and load manifest.json for a given run and processing ID."""
    verify_project_integrity(project_id)
    valid_pid = validate_project_uuid(project_id)
    valid_rid = validate_run_uuid(run_id)

    run_dir = get_dam_projects_dir() / valid_pid / "runs" / valid_rid
    results_base = run_dir / "results"

    if not results_base.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"No postprocessed results found for run '{valid_rid}'. Run postprocessing first.",
        )

    target_proc_id = processing_id
    if not target_proc_id:
        # Check run.json for latest_processing_id
        run_json = run_dir / "run.json"
        if run_json.is_file():
            try:
                r_data = json.loads(run_json.read_text(encoding="utf-8"))
                target_proc_id = r_data.get("latest_processing_id")
            except Exception:
                pass

        if not target_proc_id:
            # Look for subdirectories under results/
            subdirs = [d for d in results_base.iterdir() if d.is_dir() and not d.name.startswith(".")]
            if subdirs:
                subdirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
                target_proc_id = subdirs[0].name
            elif (results_base / "manifest.json").is_file():
                # Legacy root results path fallback
                proc_dir = results_base
                manifest_file = proc_dir / "manifest.json"
                m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                return proc_dir, m_data

    if not target_proc_id:
        raise HTTPException(
            status_code=404,
            detail=f"No postprocessed results found for run '{valid_rid}'.",
        )

    proc_dir = results_base / target_proc_id
    manifest_file = proc_dir / "manifest.json"

    if not manifest_file.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Results manifest not found for processing identity '{target_proc_id}'.",
        )

    try:
        m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        return proc_dir, m_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read results manifest: {str(e)}")


def postprocess_dam_project_anuga_run(
    project_id: str,
    run_id: str,
    request: Optional[DamProjectAnugaPostprocessRequest] = None,
) -> DamProjectAnugaResultsResponse:
    """Convert a genuine completed ANUGA simulation SWW output into map-ready hazard rasters.

    Key algorithmic safeguards:
    - Linear triangular mesh interpolation evaluated timestep-by-timestep
    - Instantaneous depth, velocity, and arrival threshold evaluated per cell per timestep
    - Accumulates running maxima to eliminate artificial vertex-asynchrony peaks
    - Strictly masks cells outside the triangulation mesh as NoData (-9999.0)
    - Preserves unflooded cells as NoData (-9999.0) in arrival time rasters
    - North-up GeoTIFF affine transform and exact CRS preservation
    - Isolated storage at runs/{run_id}/results/{processing_id}/
    - Concurrent-safe atomic staging writes without overwriting previous parameter runs
    """
    if request is None:
        request = DamProjectAnugaPostprocessRequest()

    # 1. Validation & Preconditions
    verify_project_integrity(project_id)
    valid_pid = validate_project_uuid(project_id)
    valid_rid = validate_run_uuid(run_id)

    proj_dir = get_dam_projects_dir() / valid_pid
    run_dir = proj_dir / "runs" / valid_rid
    run_json = run_dir / "run.json"

    if not run_json.is_file():
        raise HTTPException(status_code=404, detail=f"ANUGA run '{valid_rid}' not found for project '{valid_pid}'.")

    try:
        run_data = json.loads(run_json.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read run manifest: {str(e)}")

    status = run_data.get("status")
    if status != "completed" or not run_data.get("simulation_executed") or run_data.get("exit_code") != 0:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "run_not_completed",
                "message": f"Cannot postprocess ANUGA run with status '{status}'. Only completed runs with verified exit code 0 can be postprocessed.",
            },
        )

    # Locate SWW file
    sww_files = list((run_dir / "workspace" / "output").glob("*.sww"))
    if not sww_files:
        raise HTTPException(status_code=404, detail="SWW simulation output file not found in run workspace.")
    sww_path = sww_files[0]

    sww_valid, sww_err = validate_sww_file(sww_path)
    if not sww_valid:
        raise HTTPException(status_code=400, detail=f"SWW file failed NetCDF validation: {sww_err}")

    sww_sha256 = compute_file_sha256(sww_path) or ""
    recorded_output = run_data.get("output_files", {})
    recorded_hash = recorded_output.get(f"output/{sww_path.name}")
    if recorded_hash and sww_sha256 != recorded_hash:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "sww_integrity_failed",
                "message": "SWW output file checksum does not match run manifest. The simulation output may have been modified or corrupted.",
            },
        )

    # Validate threshold parameters
    dry_thresh = float(request.dry_depth_threshold_m)
    arr_thresh = float(request.arrival_depth_threshold_m)
    if dry_thresh <= 0.0 or not np.isfinite(dry_thresh):
        raise HTTPException(status_code=422, detail="dry_depth_threshold_m must be a positive finite float.")
    if arr_thresh < dry_thresh or not np.isfinite(arr_thresh):
        raise HTTPException(status_code=422, detail="arrival_depth_threshold_m must be >= dry_depth_threshold_m.")

    # 2. Identity & Idempotency Check
    proc_identity_sha256, processing_id = compute_processing_identity(
        sww_sha256=sww_sha256,
        dry_thresh=dry_thresh,
        arr_thresh=arr_thresh,
        res_m=request.raster_resolution_m,
    )

    results_base = run_dir / "results"
    proc_dir = results_base / processing_id
    manifest_file = proc_dir / "manifest.json"

    # Fast return if existing valid results match processing identity
    if manifest_file.is_file():
        try:
            m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            if m_data.get("processing_identity_sha256") == proc_identity_sha256:
                all_tifs_exist = True
                for l_name in VALID_ANUGA_RESULT_LAYERS:
                    t_path = proc_dir / f"{l_name}.tif"
                    if not t_path.is_file():
                        all_tifs_exist = False
                        break
                if all_tifs_exist:
                    # Update run.json latest_processing_id
                    try:
                        run_data["latest_processing_id"] = processing_id
                        run_data["has_results"] = True
                        run_json.write_text(json.dumps(run_data, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                    return DamProjectAnugaResultsResponse(**m_data)
        except Exception:
            pass

    # 3. Load Project Metadata & Grid Parameters
    proj_json = proj_dir / "project.json"
    p_data = json.loads(proj_json.read_text(encoding="utf-8")) if proj_json.is_file() else {}
    user_meta = p_data.get("user_provided_metadata", {})
    sim_params = p_data.get("simulation_parameters", {})
    proj_crs = user_meta.get("geometry_crs", "EPSG:32643")

    # 4. Open SWW and Construct Linear Triangular Mesh
    ds = netcdf_file(str(sww_path), "r", mmap=False)
    try:
        x_raw = np.array(ds.variables["x"][:], dtype=np.float64)
        y_raw = np.array(ds.variables["y"][:], dtype=np.float64)
        xll = float(getattr(ds, "xllcorner", 0.0))
        yll = float(getattr(ds, "yllcorner", 0.0))
        xs = x_raw + xll
        ys = y_raw + yll
        volumes = np.array(ds.variables["volumes"][:], dtype=np.int32)
        times = [float(t) for t in ds.variables["time"][:]]
        n_times = len(times)

        # Build triangulation
        triangulation = Triangulation(xs, ys, triangles=volumes)

        # Mesh bounding box
        x_min, x_max = float(np.min(xs)), float(np.max(xs))
        y_min, y_max = float(np.min(ys)), float(np.max(ys))

        # Calculate characteristic mesh edge length
        v0, v1, v2 = volumes[:, 0], volumes[:, 1], volumes[:, 2]
        e0 = np.hypot(xs[v1] - xs[v0], ys[v1] - ys[v0])
        e1 = np.hypot(xs[v2] - xs[v1], ys[v2] - ys[v1])
        e2 = np.hypot(xs[v0] - xs[v2], ys[v0] - ys[v2])
        mean_edge_m = float(np.mean(np.concatenate([e0, e1, e2])))

        # Target grid resolution
        if request.raster_resolution_m is not None:
            res_m = float(request.raster_resolution_m)
        else:
            declared_res = float(sim_params.get("target_mesh_resolution_m") or user_meta.get("target_mesh_resolution_m") or 50.0)
            res_m = max(declared_res, mean_edge_m * 0.5)

        # Calculate dimensions and enforce MAX_OUTPUT_PIXELS / MAX_GRID_DIMENSION
        width = int(np.ceil((x_max - x_min) / res_m))
        height = int(np.ceil((y_max - y_min) / res_m))

        if width > MAX_GRID_DIMENSION or height > MAX_GRID_DIMENSION or (width * height) > MAX_OUTPUT_PIXELS:
            scale = max(width / MAX_GRID_DIMENSION, height / MAX_GRID_DIMENSION, np.sqrt((width * height) / MAX_OUTPUT_PIXELS))
            res_m = res_m * scale
            width = int(np.ceil((x_max - x_min) / res_m))
            height = int(np.ceil((y_max - y_min) / res_m))

        # Construct 2D grid coordinates (North-up: top-to-bottom for y)
        grid_x = x_min + (np.arange(width) + 0.5) * res_m
        grid_y = y_max - (np.arange(height) + 0.5) * res_m
        grid_X, grid_Y = np.meshgrid(grid_x, grid_y)

        # Elevation handling (static [points], [1, points], or time-dependent [time, points])
        elev_raw = np.array(ds.variables["elevation"][:], dtype=np.float64)
        is_time_dependent_elev = (len(elev_raw.shape) == 2 and elev_raw.shape[0] == n_times and n_times > 1)

        # Static / initial elevation linear interpolation and triangle mask
        init_elev_pts = elev_raw[0] if len(elev_raw.shape) == 2 else elev_raw
        interp_init_elev = LinearTriInterpolator(triangulation, init_elev_pts)
        masked_init_elev = interp_init_elev(grid_X, grid_Y)
        grid_mesh_mask = ~masked_init_elev.mask  # True strictly within valid triangles
        static_grid_elev = masked_init_elev.data

        # Initialize 2D grid accumulators
        grid_max_depth = np.zeros((height, width), dtype=np.float32)
        grid_max_vel = np.zeros((height, width), dtype=np.float32)
        grid_arrival = np.full((height, width), -9999.0, dtype=np.float32)

        # 5. Incremental Timestep Streaming & Evaluation
        for t_idx in range(n_times):
            t_val = float(times[t_idx])
            s_slice = np.array(ds.variables["stage"][t_idx, :], dtype=np.float64)
            xm_slice = np.array(ds.variables["xmomentum"][t_idx, :], dtype=np.float64)
            ym_slice = np.array(ds.variables["ymomentum"][t_idx, :], dtype=np.float64)

            interp_s = LinearTriInterpolator(triangulation, s_slice)
            interp_xm = LinearTriInterpolator(triangulation, xm_slice)
            interp_ym = LinearTriInterpolator(triangulation, ym_slice)

            g_s = interp_s(grid_X, grid_Y).data
            g_xm = interp_xm(grid_X, grid_Y).data
            g_ym = interp_ym(grid_X, grid_Y).data

            if is_time_dependent_elev:
                e_slice = np.array(elev_raw[t_idx, :], dtype=np.float64)
                interp_e = LinearTriInterpolator(triangulation, e_slice)
                g_e = interp_e(grid_X, grid_Y).data
            else:
                g_e = static_grid_elev

            # Instantaneous depth on valid computational mesh cells
            d_t = np.where(grid_mesh_mask, np.maximum(g_s - g_e, 0.0), 0.0)

            # Instantaneous velocity (only computed where depth >= dry_depth_threshold)
            v_t = np.where(
                grid_mesh_mask & (d_t >= dry_thresh),
                np.sqrt(g_xm**2 + g_ym**2) / np.maximum(d_t, 1e-4),
                0.0,
            )

            # Accumulate running maxima
            grid_max_depth = np.where(grid_mesh_mask, np.maximum(grid_max_depth, d_t.astype(np.float32)), 0.0)
            grid_max_vel = np.where(grid_mesh_mask, np.maximum(grid_max_vel, v_t.astype(np.float32)), 0.0)

            # Arrival crossing evaluation
            if t_idx == 0:
                init_wet = grid_mesh_mask & (d_t >= arr_thresh)
                grid_arrival[init_wet] = 0.0
            else:
                newly_wet = grid_mesh_mask & (d_t >= arr_thresh) & (grid_arrival < -9000.0)
                grid_arrival[newly_wet] = t_val

    finally:
        ds.close()

    # 6. Final Masking (NoData = -9999.0)
    out_depth = np.where(grid_mesh_mask, grid_max_depth, -9999.0).astype(np.float32)
    out_vel = np.where(grid_mesh_mask, grid_max_vel, -9999.0).astype(np.float32)
    out_arr = np.where(grid_mesh_mask & (grid_arrival >= 0.0), grid_arrival, -9999.0).astype(np.float32)

    # 7. Atomic Staging Write
    results_base.mkdir(parents=True, exist_ok=True)
    staging_dir = results_base / f".staging_{processing_id}_{uuid.uuid4().hex[:8]}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    transform = rasterio.transform.from_origin(x_min, y_max, res_m, res_m)
    crs_obj = CRS.from_user_input(proj_crs)

    layers_data = {
        "maximum_depth": (out_depth, user_meta.get("vertical_unit", "meters")),
        "maximum_velocity": (out_vel, "m/s"),
        "arrival_time": (out_arr, "seconds"),
    }

    layer_files_meta: Dict[str, Any] = {}
    layer_stats_meta: Dict[str, Any] = {}

    try:
        for layer_name, (layer_arr, unit_str) in layers_data.items():
            tif_filename = f"{layer_name}.tif"
            tif_path = staging_dir / tif_filename

            with rasterio.open(
                tif_path,
                "w",
                driver="GTiff",
                height=height,
                width=width,
                count=1,
                dtype=rasterio.float32,
                crs=crs_obj,
                transform=transform,
                nodata=-9999.0,
                compress="deflate",
            ) as dst:
                dst.write(layer_arr, 1)

            h_val = compute_file_sha256(tif_path) or ""
            layer_files_meta[layer_name] = {
                "filename": tif_filename,
                "sha256": h_val,
                "unit": unit_str,
            }

            # Calculate layer statistics
            valid_mask = (layer_arr != -9999.0) & np.isfinite(layer_arr)
            valid_count = int(np.sum(valid_mask))
            nodata_count = int(np.sum(~valid_mask))
            total_count = int(layer_arr.size)

            min_v = float(np.min(layer_arr[valid_mask])) if valid_count > 0 else None
            max_v = float(np.max(layer_arr[valid_mask])) if valid_count > 0 else None
            mean_v = float(np.mean(layer_arr[valid_mask])) if valid_count > 0 else None

            layer_stats_meta[layer_name] = DamProjectAnugaLayerStats(
                min=round(min_v, 4) if min_v is not None else None,
                max=round(max_v, 4) if max_v is not None else None,
                mean=round(mean_v, 4) if mean_v is not None else None,
                valid_pixels=valid_count,
                nodata_pixels=nodata_count,
                total_pixels=total_count,
                unit=unit_str,
            ).model_dump()

        # 8. Manifest Construction
        manifest_dict: Dict[str, Any] = {
            "project_id": valid_pid,
            "run_id": valid_rid,
            "processing_id": processing_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sww_sha256": sww_sha256,
            "package_sha256": run_data.get("package_sha256", ""),
            "processing_identity_sha256": proc_identity_sha256,
            "available_layers": list(VALID_ANUGA_RESULT_LAYERS),
            "layer_files": {k: v["filename"] for k, v in layer_files_meta.items()},
            "layer_statistics": layer_stats_meta,
            "formulas": {
                "depth": "depth(t) = max(stage(t) - elevation(t), 0.0)",
                "velocity": "velocity(t) = sqrt(xmom(t)^2 + ymom(t)^2) / depth(t) for depth >= dry_threshold",
                "arrival_time": "arrival_time = 0.0 for initial wet cells else first t where depth >= arrival_threshold else NoData(-9999.0)",
            },
            "thresholds": {
                "dry_depth_threshold_m": dry_thresh,
                "arrival_depth_threshold_m": arr_thresh,
            },
            "actual_sww_timesteps": times,
            "interpolation_method": "linear_triangular_mesh_interpolation",
            "mesh_mask_method": "triangulation_boundary_inclusion",
            "raster_crs": proj_crs,
            "raster_resolution_m": round(res_m, 4),
            "grid_dimensions": (height, width),
            "anuga_version": run_data.get("anuga_version") or "4.0.0",
            "version_source": run_data.get("version_source") or "conda_meta",
            "raw_distribution_version": run_data.get("raw_distribution_version"),
            "scientific_status": "hypothetical_unverified",
            "simulation_executed": True,
            "mass_balance_status": "not_assessed",
            "disclaimer": (
                "Derived raster visualization product from uncalibrated ANUGA hydrodynamic simulation. "
                "Not certified flood forecasting or official inundation mapping."
            ),
            "message": "ANUGA simulation outputs postprocessed into map-ready hazard rasters successfully.",
        }

        (staging_dir / "manifest.json").write_text(json.dumps(manifest_dict, indent=2), encoding="utf-8")

        # 9. Concurrency-Safe Atomic Move into proc_dir
        with _POSTPROCESS_LOCK:
            if proc_dir.exists():
                shutil.rmtree(proc_dir, ignore_errors=True)
            staging_dir.rename(proc_dir)

        # 10. Update run.json with latest_processing_id
        try:
            run_data["latest_processing_id"] = processing_id
            run_data["has_results"] = True
            run_json.write_text(json.dumps(run_data, indent=2), encoding="utf-8")
        except Exception:
            pass

        return DamProjectAnugaResultsResponse(**manifest_dict)

    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def get_dam_project_anuga_results(
    project_id: str,
    run_id: str,
    processing_id: Optional[str] = None,
) -> DamProjectAnugaResultsResponse:
    """Retrieve verified metadata and layer statistics for postprocessed ANUGA simulation rasters."""
    _, m_data = resolve_processing_dir(project_id, run_id, processing_id)
    return DamProjectAnugaResultsResponse(**m_data)


def get_dam_project_anuga_layer_geotiff_path(
    project_id: str,
    run_id: str,
    layer: str,
    processing_id: Optional[str] = None,
) -> Path:
    """Retrieve verified absolute path to a specific postprocessed ANUGA GeoTIFF raster."""
    if layer not in VALID_ANUGA_RESULT_LAYERS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown ANUGA layer '{layer}'. Must be one of {sorted(VALID_ANUGA_RESULT_LAYERS)}.",
        )

    proc_dir, _ = resolve_processing_dir(project_id, run_id, processing_id)
    tif_path = proc_dir / f"{layer}.tif"
    if not tif_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Layer raster '{layer}.tif' not found for processing identity '{proc_dir.name}'. Run postprocessing first.",
        )
    return tif_path


def get_dam_project_anuga_layer_metadata(
    project_id: str,
    run_id: str,
    layer: str,
    processing_id: Optional[str] = None,
) -> RasterMetadataResponse:
    """Retrieve raster metadata for a specific postprocessed ANUGA hazard layer."""
    tif_path = get_dam_project_anuga_layer_geotiff_path(project_id, run_id, layer, processing_id)

    try:
        with rasterio.open(tif_path) as src:
            bounds = src.bounds
            res_x, res_y = src.res
            nodata_val = src.nodata
            w, h = src.width, src.height
            crs_str = src.crs.to_string() if src.crs else "EPSG:4326"

            data = src.read(1)
            valid_mask = np.isfinite(data)
            if nodata_val is not None:
                valid_mask &= (data != nodata_val)
            min_e = float(np.min(data[valid_mask])) if np.any(valid_mask) else 0.0
            max_e = float(np.max(data[valid_mask])) if np.any(valid_mask) else 0.0

        return RasterMetadataResponse(
            id=layer,
            width=w,
            height=h,
            dtype=str(data.dtype),
            crs=crs_str,
            bounds=RasterBounds(
                left=float(bounds.left),
                bottom=float(bounds.bottom),
                right=float(bounds.right),
                top=float(bounds.top),
            ),
            resolution=RasterResolution(x=float(res_x), y=float(res_y)),
            nodata=nodata_val,
            valid_min=min_e,
            valid_max=max_e,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to inspect raster metadata: {str(e)}")


def get_dam_project_anuga_layer_legend(
    project_id: str,
    run_id: str,
    layer: str,
    processing_id: Optional[str] = None,
) -> RasterLegendResponse:
    """Retrieve color ramp legend for a specific postprocessed ANUGA hazard layer."""
    if layer not in VALID_ANUGA_RESULT_LAYERS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown ANUGA layer '{layer}'. Must be one of {sorted(VALID_ANUGA_RESULT_LAYERS)}.",
        )

    meta = get_dam_project_anuga_layer_metadata(project_id, run_id, layer, processing_id)
    min_v = meta.valid_min if meta.valid_min is not None else 0.0
    max_v = meta.valid_max if meta.valid_max is not None else 1.0
    if min_v >= max_v:
        max_v = min_v + 1.0

    if layer == "maximum_depth":
        stops_def = [
            (0.0, "#90e0ef", round(min_v, 2), f"{round(min_v, 2)} m (Shallow)"),
            (0.25, "#00b4d8", round(min_v + (max_v - min_v) * 0.25, 2), f"{round(min_v + (max_v - min_v) * 0.25, 2)} m"),
            (0.50, "#0077b6", round(min_v + (max_v - min_v) * 0.50, 2), f"{round(min_v + (max_v - min_v) * 0.50, 2)} m (Deep)"),
            (0.75, "#03045e", round(min_v + (max_v - min_v) * 0.75, 2), f"{round(min_v + (max_v - min_v) * 0.75, 2)} m"),
            (1.0, "#3c096c", round(max_v, 2), f"{round(max_v, 2)} m (Severe)"),
        ]
    elif layer == "maximum_velocity":
        stops_def = [
            (0.0, "#fee440", round(min_v, 2), f"{round(min_v, 2)} m/s (Low)"),
            (0.25, "#f77f00", round(min_v + (max_v - min_v) * 0.25, 2), f"{round(min_v + (max_v - min_v) * 0.25, 2)} m/s"),
            (0.50, "#e63946", round(min_v + (max_v - min_v) * 0.50, 2), f"{round(min_v + (max_v - min_v) * 0.50, 2)} m/s (Moderate)"),
            (0.75, "#9d0208", round(min_v + (max_v - min_v) * 0.75, 2), f"{round(min_v + (max_v - min_v) * 0.75, 2)} m/s"),
            (1.0, "#370617", round(max_v, 2), f"{round(max_v, 2)} m/s (High)"),
        ]
    else:  # arrival_time
        stops_def = [
            (0.0, "#d90429", round(min_v, 1), f"{round(min_v, 1)} s (Immediate Wave)"),
            (0.25, "#f77f00", round(min_v + (max_v - min_v) * 0.25, 1), f"{round(min_v + (max_v - min_v) * 0.25, 1)} s"),
            (0.50, "#ffd166", round(min_v + (max_v - min_v) * 0.50, 1), f"{round(min_v + (max_v - min_v) * 0.50, 1)} s (Mid Wave)"),
            (0.75, "#06d6a0", round(min_v + (max_v - min_v) * 0.75, 1), f"{round(min_v + (max_v - min_v) * 0.75, 1)} s"),
            (1.0, "#118ab2", round(max_v, 1), f"{round(max_v, 1)} s (Late Wave)"),
        ]

    color_ramp = [ColorRampStop(offset=offset, color=col, value=val) for (offset, col, val, _) in stops_def]
    items = [LegendItem(value=val, color=col, label=lbl) for (_, col, val, lbl) in stops_def]

    return RasterLegendResponse(
        id=layer,
        label=f"ANUGA {layer.replace('_', ' ').title()}",
        unit_status="unverified user metadata",
        provenance_status="derived ANUGA simulation raster",
        min_value=min_v,
        max_value=max_v,
        color_ramp=color_ramp,
        items=items,
    )


def get_dam_project_anuga_layer_point_value(
    project_id: str,
    run_id: str,
    layer: str,
    lon: float,
    lat: float,
    processing_id: Optional[str] = None,
) -> DamProjectAnugaPointValueResponse:
    """Query derived raster value at a specific geographical coordinate (lon, lat in WGS84)."""
    if layer not in VALID_ANUGA_RESULT_LAYERS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown ANUGA layer '{layer}'. Must be one of {sorted(VALID_ANUGA_RESULT_LAYERS)}.",
        )

    verify_project_integrity(project_id)
    valid_pid = validate_project_uuid(project_id)
    valid_rid = validate_run_uuid(run_id)

    tif_path = get_dam_project_anuga_layer_geotiff_path(project_id, run_id, layer, processing_id)

    try:
        with rasterio.open(tif_path) as src:
            crs_str = src.crs.to_string() if src.crs else "EPSG:4326"
            nodata_val = src.nodata

            # Reproject WGS84 lon, lat to native raster CRS if given as geographic coordinates
            if src.crs and src.crs.to_string().upper() != "EPSG:4326" and (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                transformer = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                cx, cy = transformer.transform(lon, lat)
            else:
                cx, cy = lon, lat

            # Check bounding box
            b = src.bounds
            if not (b.left <= cx <= b.right and b.bottom <= cy <= b.top):
                return DamProjectAnugaPointValueResponse(
                    project_id=valid_pid,
                    run_id=valid_rid,
                    layer=layer,
                    lon=lon,
                    lat=lat,
                    crs_x=round(cx, 2),
                    crs_y=round(cy, 2),
                    crs=crs_str,
                    value=None,
                    unit="meters" if layer == "maximum_depth" else ("m/s" if layer == "maximum_velocity" else "seconds"),
                    is_valid=False,
                    is_nodata=True,
                    disclaimer="Query point is outside model domain boundary.",
                )

            # Sample cell value
            sample_gen = src.sample([(cx, cy)])
            val = float(next(sample_gen)[0])

            is_nodata = (nodata_val is not None and val == nodata_val) or not np.isfinite(val) or val <= -9000.0
            return DamProjectAnugaPointValueResponse(
                project_id=valid_pid,
                run_id=valid_rid,
                layer=layer,
                lon=lon,
                lat=lat,
                crs_x=round(cx, 2),
                crs_y=round(cy, 2),
                crs=crs_str,
                value=round(val, 3) if not is_nodata else None,
                unit="meters" if layer == "maximum_depth" else ("m/s" if layer == "maximum_velocity" else "seconds"),
                is_valid=not is_nodata,
                is_nodata=is_nodata,
                disclaimer="Derived raster visualization value — not an exact certified solver prediction.",
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query point value: {str(e)}")


def get_dam_project_anuga_layer_tile(
    project_id: str,
    run_id: str,
    layer: str,
    z: int,
    x: int,
    y: int,
    processing_id: Optional[str] = None,
) -> bytes:
    """Render a postprocessed ANUGA hazard raster as a Web Mercator PNG tile."""
    if layer not in VALID_ANUGA_RESULT_LAYERS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown ANUGA layer '{layer}'. Must be one of {sorted(VALID_ANUGA_RESULT_LAYERS)}.",
        )

    try:
        tif_path = get_dam_project_anuga_layer_geotiff_path(project_id, run_id, layer, processing_id)
        with Reader(str(tif_path)) as reader:
            img = reader.tile(x, y, z)
            arr = img.data[0].astype(np.float32)
            nodata_val = reader.dataset.nodata

            valid_mask = np.isfinite(arr)
            if nodata_val is not None:
                valid_mask &= (arr != nodata_val)
            valid_mask &= (arr > -9000.0)

            # For depth and velocity, mask zero/dry cells as transparent
            if layer in ("maximum_depth", "maximum_velocity"):
                valid_mask &= (arr > 0.005)

            if not np.any(valid_mask):
                return EMPTY_TILE_PNG

            style_key = "depth" if layer == "maximum_depth" else ("velocity" if layer == "maximum_velocity" else "arrival")
            style_def = DATASET_STYLES.get(style_key, DATASET_STYLES["depth"])
            rgba_bytes = apply_colormap_and_transparency(arr, valid_mask, style_def)
            return rgba_bytes

    except Exception:
        return EMPTY_TILE_PNG

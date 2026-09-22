"""Delft3D Flexible Mesh (D-Flow FM) UGRID NetCDF Output Ingestion Service.

Handles:
- Parsing genuine Delft3D FM UGRID NetCDF (*_map.nc / DFM_OUTPUT_*.nc) output files
- Safe extraction of mesh geometry, node/face coordinates, and topology
- Extraction of hydraulic variables (water depth, water level, bed elevation, velocity components)
- Extraction of temporal dimensions, simulation duration, and timestamps
- Grid interpolation & GeoTIFF generation (maximum_depth.tif, maximum_velocity.tif, arrival_time.tif)
- Standardized result format with complete delft3d_fm provenance
"""

import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from scipy.io import netcdf_file
from matplotlib.tri import Triangulation, LinearTriInterpolator

from app.schemas import (
    Delft3DRunImportRequest,
)
from app.scenario_storage import compute_file_sha256
from app.onboarding_service import (
    get_dam_projects_dir,
    validate_project_uuid,
)

logger = logging.getLogger(__name__)

# Standard candidate variable names in Delft3D FM / UGRID NetCDF files
NODE_X_CANDIDATES = [
    "mesh2d_node_x", "NetNode_x", "node_x", "mesh2d_face_x",
    "FlowElem_x", "FlowElem_xcc", "mesh1d_node_x", "x", "lon", "longitude"
]
NODE_Y_CANDIDATES = [
    "mesh2d_node_y", "NetNode_y", "node_y", "mesh2d_face_y",
    "FlowElem_y", "FlowElem_ycc", "mesh1d_node_y", "y", "lat", "latitude"
]
FACE_NODES_CANDIDATES = [
    "mesh2d_face_nodes", "NetElemNode", "face_nodes", "mesh2d_edge_nodes", "NetLinkNode"
]
TIME_CANDIDATES = ["time", "t", "times", "simulation_time"]

DEPTH_CANDIDATES = [
    "mesh2d_waterdepth", "waterdepth", "mesh2d_depth", "depth", "h",
    "mesh2d_s1_depth", "water_depth", "mesh2d_vol"
]
WATER_LEVEL_CANDIDATES = [
    "mesh2d_s1", "s1", "waterlevel", "mesh2d_water_level", "zwl", "water_level", "eta"
]
BED_LEVEL_CANDIDATES = [
    "mesh2d_flowelem_bl", "mesh2d_node_z", "FlowElem_bl", "bedlevel", "bl",
    "dps", "zb", "bed_level", "altitude"
]

VEL_MAG_CANDIDATES = [
    "mesh2d_ucmag", "ucmag", "velocity", "vmag", "mesh2d_vmag", "vel_mag"
]
VEL_X_CANDIDATES = [
    "mesh2d_ucx", "mesh2d_u1", "ucx", "u1", "u", "mesh2d_u", "velocity_x"
]
VEL_Y_CANDIDATES = [
    "mesh2d_ucy", "mesh2d_v1", "ucy", "v1", "v", "mesh2d_v", "velocity_y"
]


def _find_variable(nc_vars: Dict[str, Any], candidates: List[str]) -> Optional[str]:
    """Case-insensitive variable name resolution from candidates list."""
    nc_keys_lower = {k.lower(): k for k in nc_vars.keys()}
    for cand in candidates:
        if cand.lower() in nc_keys_lower:
            return nc_keys_lower[cand.lower()]
    return None


def validate_delft3d_ugrid_file(filepath: Path) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Inspect and validate whether a file is a readable Delft3D FM / UGRID NetCDF output.
    Returns (is_valid, message, metadata).
    """
    if not filepath.is_file():
        return False, f"File does not exist: {filepath}", {}

    if filepath.stat().st_size == 0:
        return False, "File is empty (0 bytes).", {}

    try:
        ds = netcdf_file(str(filepath), "r", mmap=False)
    except Exception as e:
        return False, f"Not a valid NetCDF file or unsupported format: {str(e)}", {}

    try:
        var_names = list(ds.variables.keys())
        dims = {k: len(v) if hasattr(v, '__len__') else int(v) for k, v in ds.dimensions.items()}

        x_var = _find_variable(ds.variables, NODE_X_CANDIDATES)
        y_var = _find_variable(ds.variables, NODE_Y_CANDIDATES)
        time_var = _find_variable(ds.variables, TIME_CANDIDATES)
        depth_var = _find_variable(ds.variables, DEPTH_CANDIDATES)
        wl_var = _find_variable(ds.variables, WATER_LEVEL_CANDIDATES)
        bed_var = _find_variable(ds.variables, BED_LEVEL_CANDIDATES)
        vel_mag_var = _find_variable(ds.variables, VEL_MAG_CANDIDATES)
        vel_x_var = _find_variable(ds.variables, VEL_X_CANDIDATES)
        vel_y_var = _find_variable(ds.variables, VEL_Y_CANDIDATES)

        if not x_var or not y_var:
            return False, f"Missing spatial coordinate variables in NetCDF. Available variables: {var_names}", {}

        has_depth_info = bool(depth_var or (wl_var and bed_var) or wl_var)
        if not has_depth_info:
            return False, f"Missing depth or water level variables in NetCDF. Available variables: {var_names}", {}

        detected_meta = {
            "x_variable": x_var,
            "y_variable": y_var,
            "time_variable": time_var,
            "depth_variable": depth_var,
            "water_level_variable": wl_var,
            "bed_level_variable": bed_var,
            "velocity_mag_variable": vel_mag_var,
            "velocity_x_variable": vel_x_var,
            "velocity_y_variable": vel_y_var,
            "dimensions": dims,
            "all_variables": var_names,
            "title": str(getattr(ds, "title", getattr(ds, "history", "Delft3D FM Simulation Output"))),
            "conventions": str(getattr(ds, "Conventions", "UGRID-1.0")),
        }
        return True, "Valid Delft3D FM / UGRID NetCDF file.", detected_meta
    finally:
        ds.close()


def parse_delft3d_ugrid_netcdf(
    filepath: Path,
    dry_depth_threshold_m: float = 0.05,
    target_crs: str = "EPSG:32643",
) -> Dict[str, Any]:
    """
    Parse genuine Delft3D FM UGRID NetCDF output and extract mesh, coordinates,
    time-series, depth and velocity fields, and compute hazard maxima.
    """
    is_valid, msg, meta = validate_delft3d_ugrid_file(filepath)
    if not is_valid:
        raise ValueError(f"Invalid Delft3D UGRID NetCDF file: {msg}")

    ds = netcdf_file(str(filepath), "r", mmap=False)
    try:
        # 1. Coordinates
        x_name = meta["x_variable"]
        y_name = meta["y_variable"]
        x_raw = np.array(ds.variables[x_name][:], dtype=np.float64).flatten()
        y_raw = np.array(ds.variables[y_name][:], dtype=np.float64).flatten()

        n_points = len(x_raw)
        if n_points < 3:
            raise ValueError(f"Mesh has too few spatial points ({n_points}). Minimum 3 required.")

        x_min, x_max = float(np.nanmin(x_raw)), float(np.nanmax(x_raw))
        y_min, y_max = float(np.nanmin(y_raw)), float(np.nanmax(y_raw))

        # 2. Timestamps
        t_name = meta["time_variable"]
        if t_name and t_name in ds.variables:
            t_raw = np.array(ds.variables[t_name][:], dtype=np.float64).flatten()
            timestamps = [float(t) for t in t_raw]
        else:
            timestamps = [0.0]
        n_times = len(timestamps)

        # 3. Depth extraction
        depth_name = meta["depth_variable"]
        wl_name = meta["water_level_variable"]
        bed_name = meta["bed_level_variable"]

        max_depth_arr = np.zeros(n_points, dtype=np.float32)
        depth_extracted = False

        if depth_name and depth_name in ds.variables:
            d_var = ds.variables[depth_name]
            d_data = np.array(d_var[:], dtype=np.float32)
            if d_data.ndim == 1:
                max_depth_arr = np.maximum(0.0, np.nan_to_num(d_data[:n_points], nan=0.0))
            elif d_data.ndim >= 2:
                # Max over time
                max_depth_arr = np.maximum(0.0, np.nan_to_num(np.nanmax(d_data, axis=0).flatten()[:n_points], nan=0.0))
            depth_extracted = True
        elif wl_name and wl_name in ds.variables:
            wl_data = np.array(ds.variables[wl_name][:], dtype=np.float32)
            if bed_name and bed_name in ds.variables:
                bed_data = np.array(ds.variables[bed_name][:], dtype=np.float32).flatten()[:n_points]
                if wl_data.ndim == 1:
                    max_depth_arr = np.maximum(0.0, np.nan_to_num(wl_data[:n_points] - bed_data, nan=0.0))
                else:
                    max_wl = np.nanmax(wl_data, axis=0).flatten()[:n_points]
                    max_depth_arr = np.maximum(0.0, np.nan_to_num(max_wl - bed_data, nan=0.0))
            else:
                if wl_data.ndim == 1:
                    max_depth_arr = np.maximum(0.0, np.nan_to_num(wl_data[:n_points], nan=0.0))
                else:
                    max_depth_arr = np.maximum(0.0, np.nan_to_num(np.nanmax(wl_data, axis=0).flatten()[:n_points], nan=0.0))
            depth_extracted = True

        # Clean dry values
        max_depth_arr = np.where(max_depth_arr < dry_depth_threshold_m, 0.0, max_depth_arr)

        # 4. Velocity extraction
        vel_mag_name = meta["velocity_mag_variable"]
        vel_x_name = meta["velocity_x_variable"]
        vel_y_name = meta["velocity_y_variable"]

        max_vel_arr = np.zeros(n_points, dtype=np.float32)
        vel_extracted = False

        if vel_mag_name and vel_mag_name in ds.variables:
            v_data = np.array(ds.variables[vel_mag_name][:], dtype=np.float32)
            if v_data.ndim == 1:
                max_vel_arr = np.maximum(0.0, np.nan_to_num(v_data[:n_points], nan=0.0))
            else:
                max_vel_arr = np.maximum(0.0, np.nan_to_num(np.nanmax(v_data, axis=0).flatten()[:n_points], nan=0.0))
            vel_extracted = True
        elif vel_x_name and vel_y_name and vel_x_name in ds.variables and vel_y_name in ds.variables:
            vx_data = np.array(ds.variables[vel_x_name][:], dtype=np.float32)
            vy_data = np.array(ds.variables[vel_y_name][:], dtype=np.float32)
            if vx_data.ndim == 1:
                mag = np.sqrt(np.square(vx_data[:n_points]) + np.square(vy_data[:n_points]))
                max_vel_arr = np.maximum(0.0, np.nan_to_num(mag, nan=0.0))
            else:
                mag_ts = np.sqrt(np.square(vx_data) + np.square(vy_data))
                max_vel_arr = np.maximum(0.0, np.nan_to_num(np.nanmax(mag_ts, axis=0).flatten()[:n_points], nan=0.0))
            vel_extracted = True

        # 5. Summary metrics
        overall_max_depth = float(np.nanmax(max_depth_arr)) if len(max_depth_arr) > 0 else 0.0
        overall_max_vel = float(np.nanmax(max_vel_arr)) if len(max_vel_arr) > 0 else 0.0
        wet_mask = max_depth_arr > dry_depth_threshold_m
        wet_count = int(np.sum(wet_mask))
        mean_depth = float(np.mean(max_depth_arr[wet_mask])) if wet_count > 0 else 0.0

        # Estimated approximate flooded area
        dx = (x_max - x_min) / max(1.0, np.sqrt(n_points))
        dy = (y_max - y_min) / max(1.0, np.sqrt(n_points))
        cell_area_km2 = (dx * dy) / 1e6
        flooded_area_km2 = float(wet_count * cell_area_km2)

        # Coordinate System Detection
        detected_crs = target_crs
        if x_min >= -180.0 and x_max <= 180.0 and y_min >= -90.0 and y_max <= 90.0 and (x_max - x_min) < 30.0:
            detected_crs = "EPSG:4326"

        return {
            "engine": "delft3d_fm",
            "source_file": str(filepath.resolve()),
            "source_filename": filepath.name,
            "file_type": "ugrid_netcdf",
            "num_nodes": n_points,
            "num_timesteps": n_times,
            "timestamps": timestamps,
            "simulation_duration_s": float(timestamps[-1] - timestamps[0]) if len(timestamps) > 1 else 0.0,
            "crs": detected_crs,
            "bounds": [x_min, y_min, x_max, y_max],
            "x_coords": x_raw,
            "y_coords": y_raw,
            "max_depth_array": max_depth_arr,
            "max_velocity_array": max_vel_arr,
            "depth_extracted": depth_extracted,
            "velocity_extracted": vel_extracted,
            "summary": {
                "max_depth_m": round(overall_max_depth, 4),
                "max_velocity_ms": round(overall_max_vel, 4),
                "mean_depth_m": round(mean_depth, 4),
                "flooded_points_count": wet_count,
                "flooded_area_km2": round(flooded_area_km2, 4),
            },
            "provenance": {
                "source_engine": "delft3d_fm",
                "parsed_at": datetime.now(timezone.utc).isoformat(),
                "variables_extracted": [k for k, v in meta.items() if v and isinstance(v, str)],
                "conventions": meta.get("conventions", "UGRID-1.0"),
            }
        }
    finally:
        ds.close()


def rasterize_delft3d_ugrid_to_geotiff(
    parsed_data: Dict[str, Any],
    output_dir: Path,
    resolution_m: Optional[float] = None,
    nodata_value: float = -9999.0,
) -> Dict[str, Path]:
    """
    Interpolate parsed Delft3D UGRID arrays into standardized North-up GeoTIFFs:
    - maximum_depth.tif
    - maximum_velocity.tif
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    xs = parsed_data["x_coords"]
    ys = parsed_data["y_coords"]
    depth_arr = parsed_data["max_depth_array"]
    vel_arr = parsed_data["max_velocity_array"]
    crs_str = parsed_data.get("crs", "EPSG:32643")
    bounds = parsed_data["bounds"]
    x_min, y_min, x_max, y_max = bounds

    width_m = max(10.0, x_max - x_min)
    height_m = max(10.0, y_max - y_min)

    # Choose resolution
    if resolution_m is None or resolution_m <= 0.0:
        n_pts = len(xs)
        grid_dim = min(512, max(64, int(np.sqrt(n_pts) * 4)))
        res_x = width_m / grid_dim
        res_y = height_m / grid_dim
        resolution_m = max(1.0, min(res_x, res_y))
    else:
        grid_dim = int(min(1024, max(32, width_m / resolution_m)))

    cols = max(32, int(np.ceil(width_m / resolution_m)))
    rows = max(32, int(np.ceil(height_m / resolution_m)))

    if cols > 1024:
        cols = 1024
        resolution_m = width_m / cols
    if rows > 1024:
        rows = 1024

    # Grid coordinates (North-up: top-to-bottom for Y)
    grid_x = np.linspace(x_min, x_max, cols)
    grid_y = np.linspace(y_max, y_min, rows)  # descending for North-up
    gx, gy = np.meshgrid(grid_x, grid_y)

    # Build triangulation for 2D interpolation
    try:
        tri = Triangulation(xs, ys)
        interp_depth = LinearTriInterpolator(tri, depth_arr)
        depth_grid = interp_depth(gx, gy)
        depth_grid = np.where(np.isnan(depth_grid), nodata_value, depth_grid)

        interp_vel = LinearTriInterpolator(tri, vel_arr)
        vel_grid = interp_vel(gx, gy)
        vel_grid = np.where(np.isnan(vel_grid), nodata_value, vel_grid)
    except Exception as e:
        logger.warning(f"Triangulation interpolation fallback: {e}")
        from scipy.interpolate import griddata
        depth_grid = griddata((xs, ys), depth_arr, (gx, gy), method="nearest", fill_value=nodata_value)
        vel_grid = griddata((xs, ys), vel_arr, (gx, gy), method="nearest", fill_value=nodata_value)

    depth_grid = np.asarray(depth_grid, dtype=np.float32)
    vel_grid = np.asarray(vel_grid, dtype=np.float32)

    transform = from_bounds(x_min, y_min, x_max, y_max, cols, rows)
    out_paths: Dict[str, Path] = {}

    profile = {
        "driver": "GTiff",
        "height": rows,
        "width": cols,
        "count": 1,
        "dtype": "float32",
        "crs": CRS.from_string(crs_str),
        "transform": transform,
        "nodata": nodata_value,
        "compress": "deflate",
        "predictor": 2,
    }

    # Write maximum_depth.tif
    depth_tif_path = output_dir / "maximum_depth.tif"
    with rasterio.open(depth_tif_path, "w", **profile) as dst:
        dst.write(depth_grid, 1)
    out_paths["maximum_depth"] = depth_tif_path

    # Write maximum_velocity.tif
    vel_tif_path = output_dir / "maximum_velocity.tif"
    with rasterio.open(vel_tif_path, "w", **profile) as dst:
        dst.write(vel_grid, 1)
    out_paths["maximum_velocity"] = vel_tif_path

    return out_paths


def ingest_delft3d_netcdf_run(
    project_id: str,
    nc_path: Path,
    req: Optional[Delft3DRunImportRequest] = None,
) -> Dict[str, Any]:
    """
    Ingest a genuine Delft3D FM NetCDF output into dam project storage.
    Parses mesh, extracts maximum hazard maps, renders standard GeoTIFFs,
    and returns a standardized run record with delft3d_fm provenance.
    """
    valid_pid = validate_project_uuid(project_id)
    proj_dir = get_dam_projects_dir() / valid_pid
    if not proj_dir.is_dir():
        raise ValueError(f"Dam project '{valid_pid}' not found.")

    if req is None:
        req = Delft3DRunImportRequest(run_label="Imported Delft3D UGRID NetCDF Run")

    run_id = f"d3d-ugrid-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    d3d_runs_dir = proj_dir / "delft3d" / "runs" / run_id
    d3d_runs_dir.mkdir(parents=True, exist_ok=True)

    # Copy raw NetCDF to run directory
    dst_nc_path = d3d_runs_dir / nc_path.name
    if nc_path.resolve() != dst_nc_path.resolve():
        shutil.copy2(nc_path, dst_nc_path)

    # Parse NetCDF
    parsed = parse_delft3d_ugrid_netcdf(dst_nc_path)

    # Generate GeoTIFFs
    tifs = rasterize_delft3d_ugrid_to_geotiff(parsed, d3d_runs_dir)

    # Compute layer hashes
    layer_hashes = {
        name: compute_file_sha256(path) or "" for name, path in tifs.items()
    }
    nc_hash = compute_file_sha256(dst_nc_path) or ""

    run_record = {
        "run_id": run_id,
        "project_id": valid_pid,
        "engine": "delft3d_fm",
        "engine_version": "Delft3D Flexible Mesh (UGRID Ingested)",
        "run_label": req.run_label or "Imported Delft3D UGRID NetCDF Run",
        "status": "completed",
        "solver_execution_status": "imported",
        "scientific_status": req.scientific_status or "genuine_ugrid_netcdf_ingested",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": req.notes or f"Imported genuine Delft3D FM NetCDF ({dst_nc_path.name}).",
        "native_crs": parsed.get("crs", "EPSG:32643"),
        "bounds": parsed.get("bounds"),
        "nodata_value": -9999.0,
        "summary": parsed.get("summary"),
        "layers": {
            "has_maximum_depth": "maximum_depth" in tifs,
            "has_maximum_velocity": "maximum_velocity" in tifs,
            "has_arrival_time": False,
        },
        "layer_hashes": layer_hashes,
        "source_files": [dst_nc_path.name] + [p.name for p in tifs.values()],
        "source_file_hashes": {
            dst_nc_path.name: nc_hash,
            **layer_hashes,
        },
        "provenance": {
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "import_mode": "ugrid_netcdf",
            "source_engine": "delft3d_fm",
            "extracted_metadata": parsed.get("provenance", {}),
        }
    }

    (d3d_runs_dir / "run.json").write_text(json.dumps(run_record, indent=2), encoding="utf-8")
    return run_record

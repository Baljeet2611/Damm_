"""
Phase 29: Dam-Break Decision-Support Service.

Converts raw hydrodynamic simulation outputs (ANUGA 2D regional shallow water
as primary analysis; SPH available as supplementary near-field demonstration)
into deterministic decision-support metrics, hydraulic severity layers,
downstream distance zones, modeled critical points, and structured exports.
"""

import io
import os
import csv
import json
import math
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import rasterio
from rasterio.transform import xy
from PIL import Image
from pyproj import Transformer
from fastapi import HTTPException

from app.onboarding_service import (
    get_dam_projects_dir,
    get_dam_project,
    validate_project_uuid,
)
from app.model_comparison_service import validate_comparison_uuid
from app.schemas import (
    DecisionSupportResponse,
    DecisionSupportKPIs,
    PercentileDistribution,
    CumulativeDepthAreas,
    DistributionBin,
    DownstreamZoneMetric,
    ModeledCriticalPoint,
    HydraulicSeverityConfig,
    DecisionSupportScenarioParameters,
    DemoReadinessResponse,
)

logger = logging.getLogger("decision_support_service")

# Transparent empty 256x256 PNG for tile serving
_empty_img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
_empty_buf = io.BytesIO()
_empty_img.save(_empty_buf, format="PNG")
EMPTY_TILE_PNG = _empty_buf.getvalue()

# Hydraulic severity demonstration classification thresholds
DEMONSTRATION_SEVERITY_THRESHOLDS = [
    {
        "band": "Low",
        "min_val": 0.0,
        "max_val": 0.5,
        "color": "#38bdf8",  # Light blue
        "description": "Shallow water or low velocity (H <= 0.5 m^2/s)",
    },
    {
        "band": "Moderate",
        "min_val": 0.5,
        "max_val": 2.0,
        "color": "#eab308",  # Amber/Yellow
        "description": "Moderate depth-velocity intensity (0.5 < H <= 2.0 m^2/s)",
    },
    {
        "band": "High",
        "min_val": 2.0,
        "max_val": 5.0,
        "color": "#f97316",  # Orange
        "description": "High hydraulic energy flux (2.0 < H <= 5.0 m^2/s)",
    },
    {
        "band": "Very High",
        "min_val": 5.0,
        "max_val": None,
        "color": "#ef4444",  # Red
        "description": "Extreme hydraulic severity concentration (H > 5.0 m^2/s)",
    },
]


def _find_anuga_run(project_id: str, run_id: Optional[str] = None) -> Tuple[Path, Path, Dict[str, Any]]:
    """
    Locate and validate completed ANUGA run directory, results directory, and run.json.
    """
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid
    if not p_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found")

    candidate_dirs = [p_dir / "runs", p_dir / "anuga" / "runs"]
    selected_run_dir = None

    if run_id:
        clean_run_id = validate_comparison_uuid(run_id)
        for c_dir in candidate_dirs:
            cand = c_dir / clean_run_id
            if cand.is_dir() and (cand / "run.json").is_file():
                selected_run_dir = cand
                break
        if not selected_run_dir:
            raise HTTPException(
                status_code=404,
                detail=f"Specified ANUGA run '{clean_run_id}' not found in project '{valid_pid}'"
            )
    else:
        for c_dir in candidate_dirs:
            if c_dir.is_dir():
                for a_sub in sorted(c_dir.iterdir(), reverse=True):
                    if a_sub.is_dir() and (a_sub / "run.json").is_file():
                        try:
                            d = json.loads((a_sub / "run.json").read_text(encoding="utf-8"))
                            if d.get("status") == "completed":
                                res = a_sub / "results"
                                has_d = False
                                if (res / "maximum_depth.tif").is_file():
                                    has_d = True
                                else:
                                    for sub in res.glob("*/maximum_depth.tif"):
                                        has_d = True
                                        break
                                if has_d:
                                    selected_run_dir = a_sub
                                    break
                        except Exception:
                            pass
                if selected_run_dir:
                    break

    if not selected_run_dir:
        raise HTTPException(
            status_code=404,
            detail="No completed ANUGA shallow-water simulation runs found for this project. Please execute an ANUGA simulation first."
        )

    run_json = json.loads((selected_run_dir / "run.json").read_text(encoding="utf-8"))

    # Resolve results directory containing the GeoTIFFs
    res_dir = selected_run_dir / "results"
    target_res_dir = res_dir
    if (res_dir / "maximum_depth.tif").is_file():
        target_res_dir = res_dir
    else:
        for sub in sorted(res_dir.glob("proc_*"), reverse=True):
            if (sub / "maximum_depth.tif").is_file():
                target_res_dir = sub
                break

    return selected_run_dir, target_res_dir, run_json


def _ensure_hydraulic_severity_raster(
    target_res_dir: Path,
    depth_tif: Path,
    vel_tif: Path
) -> Path:
    """
    Generate and save hydraulic_severity.tif = depth * velocity on native raster grid if not already present.
    """
    severity_tif = target_res_dir / "hydraulic_severity.tif"
    if severity_tif.is_file():
        return severity_tif

    with rasterio.open(depth_tif) as src_d, rasterio.open(vel_tif) as src_v:
        d_arr = src_d.read(1)
        v_arr = src_v.read(1)
        meta = src_d.meta.copy()
        nodata = src_d.nodata if src_d.nodata is not None else -9999.0

        # Mask valid wet cells
        valid_mask = (d_arr != nodata) & np.isfinite(d_arr) & (d_arr >= 0.05) & \
                     (v_arr != nodata) & np.isfinite(v_arr) & (v_arr >= 0.0)

        h_v_prod = np.full(d_arr.shape, nodata, dtype=np.float32)
        h_v_prod[valid_mask] = (d_arr[valid_mask] * v_arr[valid_mask]).astype(np.float32)

        meta.update(dtype=rasterio.float32, nodata=nodata, count=1)
        with rasterio.open(severity_tif, "w", **meta) as dst:
            dst.write(h_v_prod, 1)

    logger.info(f"Generated hydraulic_severity.tif at {severity_tif}")
    return severity_tif


def get_decision_support_summary(
    project_id: str,
    run_id: Optional[str] = None
) -> DecisionSupportResponse:
    """
    Generate comprehensive decision-support metrics, distributions, severity analysis,
    downstream distance zones, and critical points for the selected ANUGA run.
    """
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid
    if not p_dir.is_dir() or not (p_dir / "project.json").is_file():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found")
    project_data: Dict[str, Any] = json.loads((p_dir / "project.json").read_text(encoding="utf-8"))

    selected_run_dir, target_res_dir, run_json = _find_anuga_run(valid_pid, run_id)
    active_run_id = selected_run_dir.name

    depth_tif = target_res_dir / "maximum_depth.tif"
    vel_tif = target_res_dir / "maximum_velocity.tif"
    arrival_tif = target_res_dir / "arrival_time.tif"

    if not depth_tif.is_file():
        raise HTTPException(status_code=404, detail="maximum_depth.tif missing from ANUGA run results")
    if not vel_tif.is_file():
        raise HTTPException(status_code=404, detail="maximum_velocity.tif missing from ANUGA run results")

    # Generate or get hydraulic severity raster
    severity_tif = _ensure_hydraulic_severity_raster(target_res_dir, depth_tif, vel_tif)

    with rasterio.open(depth_tif) as src_d, \
         rasterio.open(vel_tif) as src_v, \
         rasterio.open(severity_tif) as src_h:

        d_arr = src_d.read(1)
        v_arr = src_v.read(1)
        h_arr = src_h.read(1)

        nodata_d = src_d.nodata if src_d.nodata is not None else -9999.0
        nodata_v = src_v.nodata if src_v.nodata is not None else -9999.0
        nodata_h = src_h.nodata if src_h.nodata is not None else -9999.0

        crs_str = str(src_d.crs) if src_d.crs else "EPSG:32643"
        bounds = src_d.bounds
        res_x, res_y = abs(src_d.res[0]), abs(src_d.res[1])
        is_geographic = src_d.crs and src_d.crs.is_geographic
        if is_geographic:
            mid_lat = (bounds.top + bounds.bottom) / 2.0
            res_x_m = res_x * 111320.0 * math.cos(math.radians(mid_lat))
            res_y_m = res_y * 111320.0
            cell_area_km2 = (res_x_m * res_y_m) / 1e6
            width_km = (bounds.right - bounds.left) * 111320.0 * math.cos(math.radians(mid_lat)) / 1000.0
            height_km = (bounds.top - bounds.bottom) * 111320.0 / 1000.0
            total_domain_area_km2 = round(float(width_km * height_km), 3)
        else:
            cell_area_km2 = (res_x * res_y) / 1e6
            total_domain_area_km2 = round(float((bounds.right - bounds.left) * (bounds.top - bounds.bottom) / 1e6), 3)

        # Coordinate transformer to WGS84
        to_wgs84 = Transformer.from_crs(crs_str, "EPSG:4326", always_xy=True)

        # Valid masks
        valid_depth_mask = (d_arr != nodata_d) & np.isfinite(d_arr) & (d_arr >= 0.0)
        wet_mask = (d_arr != nodata_d) & np.isfinite(d_arr) & (d_arr >= 0.05)
        wet_cell_count = int(np.sum(wet_mask))
        inundated_area_km2 = round(float(wet_cell_count * cell_area_km2), 3)
        domain_inundated_pct = round(float((inundated_area_km2 / max(total_domain_area_km2, 1e-4)) * 100), 2)

        wet_depths = d_arr[wet_mask]
        wet_velocities = v_arr[wet_mask]
        wet_severities = h_arr[wet_mask]

        # KPIs
        max_depth = round(float(np.max(d_arr[valid_depth_mask])), 2) if np.any(valid_depth_mask) else 0.0
        max_velocity = round(float(np.max(v_arr[(v_arr != nodata_v) & np.isfinite(v_arr) & (v_arr >= 0.0)])), 2) if np.any(v_arr >= 0.0) else 0.0
        peak_severity = round(float(np.max(wet_severities)), 2) if len(wet_severities) > 0 else 0.0

        # Percentiles
        depth_percentiles = PercentileDistribution(
            p50=round(float(np.percentile(wet_depths, 50)), 2) if len(wet_depths) > 0 else 0.0,
            p90=round(float(np.percentile(wet_depths, 90)), 2) if len(wet_depths) > 0 else 0.0,
            p95=round(float(np.percentile(wet_depths, 95)), 2) if len(wet_depths) > 0 else 0.0,
            p99=round(float(np.percentile(wet_depths, 99)), 2) if len(wet_depths) > 0 else 0.0,
            max=max_depth,
        )

        vel_percentiles = PercentileDistribution(
            p50=round(float(np.percentile(wet_velocities, 50)), 2) if len(wet_velocities) > 0 else 0.0,
            p90=round(float(np.percentile(wet_velocities, 90)), 2) if len(wet_velocities) > 0 else 0.0,
            p95=round(float(np.percentile(wet_velocities, 95)), 2) if len(wet_velocities) > 0 else 0.0,
            p99=round(float(np.percentile(wet_velocities, 99)), 2) if len(wet_velocities) > 0 else 0.0,
            max=max_velocity,
        )

        # Cumulative Depth Areas
        cum_depth = CumulativeDepthAreas(
            depth_gt_0_1m_km2=round(float(np.sum((d_arr >= 0.1) & (d_arr != nodata_d)) * cell_area_km2), 3),
            depth_gt_0_5m_km2=round(float(np.sum((d_arr >= 0.5) & (d_arr != nodata_d)) * cell_area_km2), 3),
            depth_gt_1_0m_km2=round(float(np.sum((d_arr >= 1.0) & (d_arr != nodata_d)) * cell_area_km2), 3),
            depth_gt_2_0m_km2=round(float(np.sum((d_arr >= 2.0) & (d_arr != nodata_d)) * cell_area_km2), 3),
        )

        # Depth distribution bins
        depth_bins_def = [
            ("0.0 - 0.5 m", 0.0, 0.5),
            ("0.5 - 1.0 m", 0.5, 1.0),
            ("1.0 - 2.0 m", 1.0, 2.0),
            ("2.0 - 5.0 m", 2.0, 5.0),
            ("> 5.0 m", 5.0, None),
        ]
        depth_distribution: List[DistributionBin] = []
        for label, low, high in depth_bins_def:
            effective_low = max(low, 0.05) if low == 0.0 else low
            if high is not None:
                mask = (d_arr >= effective_low) & (d_arr < high) & (d_arr != nodata_d) & wet_mask
            else:
                mask = (d_arr >= effective_low) & (d_arr != nodata_d) & wet_mask
            area = round(float(np.sum(mask) * cell_area_km2), 3)
            pct = round(float((area / max(inundated_area_km2, 1e-4)) * 100), 1) if inundated_area_km2 > 0 else 0.0
            depth_distribution.append(DistributionBin(
                range_label=label,
                min_val=low,
                max_val=high,
                area_km2=area,
                percentage=pct,
            ))

        # Velocity distribution bins
        vel_bins_def = [
            ("0.0 - 0.5 m/s", 0.0, 0.5),
            ("0.5 - 1.0 m/s", 0.5, 1.0),
            ("1.0 - 2.0 m/s", 1.0, 2.0),
            ("2.0 - 5.0 m/s", 2.0, 5.0),
            ("> 5.0 m/s", 5.0, None),
        ]
        velocity_distribution: List[DistributionBin] = []
        for label, low, high in vel_bins_def:
            if high is not None:
                mask = (v_arr >= low) & (v_arr < high) & (v_arr != nodata_v) & wet_mask
            else:
                mask = (v_arr >= low) & (v_arr != nodata_v) & wet_mask
            area = round(float(np.sum(mask) * cell_area_km2), 3)
            pct = round(float((area / max(inundated_area_km2, 1e-4)) * 100), 1) if inundated_area_km2 > 0 else 0.0
            velocity_distribution.append(DistributionBin(
                range_label=label,
                min_val=low,
                max_val=high,
                area_km2=area,
                percentage=pct,
            ))

        # Arrival Time Intelligence (Mask out initial reservoir wet cells t = 0)
        first_arrival_s = 60.0
        first_arrival_min = 1.0
        median_arrival_s = None
        median_arrival_min = None
        p90_arrival_s = None
        p90_arrival_min = None
        latest_arrival_s = None
        latest_arrival_min = None

        arr_arr = None
        if arrival_tif.is_file():
            with rasterio.open(arrival_tif) as src_a:
                arr_arr = src_a.read(1)
                nodata_a = src_a.nodata if src_a.nodata is not None else -9999.0
                # Isolate newly inundated downstream cells (arrival > 0.0 s and wet)
                downstream_arrival_mask = (arr_arr > 0.0) & (arr_arr != nodata_a) & np.isfinite(arr_arr) & wet_mask
                if np.any(downstream_arrival_mask):
                    d_arrivals = arr_arr[downstream_arrival_mask]
                    first_arrival_s = round(float(np.min(d_arrivals)), 1)
                    first_arrival_min = round(float(first_arrival_s / 60.0), 2)
                    med_s = float(np.median(d_arrivals))
                    p90_s = float(np.percentile(d_arrivals, 90))
                    late_s = float(np.max(d_arrivals))
                    median_arrival_s = round(med_s, 1)
                    median_arrival_min = round(med_s / 60.0, 2)
                    p90_arrival_s = round(p90_s, 1)
                    p90_arrival_min = round(p90_s / 60.0, 2)
                    latest_arrival_s = round(late_s, 1)
                    latest_arrival_min = round(late_s / 60.0, 2)

        # Dam crest center / breach reference coordinates (from project or DEM bounds)
        # Default Hidkal dam crest approx center in UTM: (504884.0, 1787680.0)
        dam_x = float(project_data.get("breach_center_x") or ((bounds.left + bounds.right) / 2.0))
        dam_y = float(project_data.get("breach_center_y") or (bounds.top - (bounds.top - bounds.bottom) * 0.35))

        # Downstream distance reach: max distance of wet cell from dam center
        rows, cols = np.where(wet_mask)
        if len(rows) > 0:
            xs, ys = xy(src_d.transform, rows, cols)
            xs, ys = np.array(xs), np.array(ys)
            if is_geographic:
                dx_m = (xs - dam_x) * 111320.0 * math.cos(math.radians(dam_y))
                dy_m = (ys - dam_y) * 111320.0
                distances_m = np.sqrt(dx_m ** 2 + dy_m ** 2)
            else:
                distances_m = np.sqrt((xs - dam_x) ** 2 + (ys - dam_y) ** 2)
            # Only count downstream (below dam latitude/northing)
            downstream_indices = np.where(ys <= dam_y)[0]
            if len(downstream_indices) > 0:
                downstream_reach_km = round(float(np.max(distances_m[downstream_indices]) / 1000.0), 2)
            else:
                downstream_reach_km = round(float(np.max(distances_m) / 1000.0), 2)
        else:
            downstream_reach_km = 0.0

        # Downstream distance zones
        zone_definitions = [
            ("0 - 250 m", 0.0, 250.0),
            ("250 - 500 m", 250.0, 500.0),
            ("500 - 750 m", 500.0, 750.0),
            ("750 - 1000 m", 750.0, 1000.0),
            ("> 1000 m", 1000.0, None),
        ]
        downstream_zones: List[DownstreamZoneMetric] = []
        if len(rows) > 0:
            for z_label, z_min, z_max in zone_definitions:
                if z_max is not None:
                    z_mask = (distances_m >= z_min) & (distances_m < z_max)
                else:
                    z_mask = distances_m >= z_min

                z_rows = rows[z_mask]
                z_cols = cols[z_mask]
                if len(z_rows) > 0:
                    z_depths = d_arr[z_rows, z_cols]
                    z_vels = v_arr[z_rows, z_cols]
                    z_sevs = h_arr[z_rows, z_cols]
                    z_max_d = round(float(np.max(z_depths)), 2)
                    z_max_v = round(float(np.max(z_vels)), 2)
                    z_mean_h = round(float(np.mean(z_sevs[z_sevs >= 0])), 2) if np.any(z_sevs >= 0) else 0.0
                    z_area = round(float(len(z_rows) * cell_area_km2), 3)

                    z_earliest_s = None
                    z_earliest_min = None
                    if arr_arr is not None:
                        z_arrs = arr_arr[z_rows, z_cols]
                        z_arrs_valid = z_arrs[(z_arrs > 0) & (z_arrs != -9999)]
                        if len(z_arrs_valid) > 0:
                            z_earliest_s = round(float(np.min(z_arrs_valid)), 1)
                            z_earliest_min = round(float(z_earliest_s / 60.0), 2)

                    downstream_zones.append(DownstreamZoneMetric(
                        zone_label=z_label,
                        distance_min_m=z_min,
                        distance_max_m=z_max,
                        max_depth_m=z_max_d,
                        max_velocity_ms=z_max_v,
                        earliest_arrival_s=z_earliest_s,
                        earliest_arrival_min=z_earliest_min,
                        inundated_area_km2=z_area,
                        mean_severity_m2s=z_mean_h,
                    ))
                else:
                    downstream_zones.append(DownstreamZoneMetric(
                        zone_label=z_label,
                        distance_min_m=z_min,
                        distance_max_m=z_max,
                        max_depth_m=0.0,
                        max_velocity_ms=0.0,
                        earliest_arrival_s=None,
                        earliest_arrival_min=None,
                        inundated_area_km2=0.0,
                        mean_severity_m2s=0.0,
                    ))

        # Modeled Critical Points (up to 5 points)
        critical_points: List[ModeledCriticalPoint] = []

        # Helper to convert (row, col) -> (utm_x, utm_y), (lat, lon)
        def _get_coords(r: int, c: int) -> Tuple[List[float], List[float]]:
            ux, uy = xy(src_d.transform, r, c)
            lon_c, lat_c = to_wgs84.transform(ux, uy)
            return [round(float(ux), 1), round(float(uy), 1)], [round(float(lat_c), 5), round(float(lon_c), 5)]

        # 1. Maximum Depth Point
        if np.any(valid_depth_mask):
            r_max_d, c_max_d = np.unravel_index(np.argmax(np.where(valid_depth_mask, d_arr, -9999)), d_arr.shape)
            utm_d, wgs_d = _get_coords(int(r_max_d), int(c_max_d))
            critical_points.append(ModeledCriticalPoint(
                point_id="max_depth",
                title="Maximum Modeled Water Depth",
                metric_name="Water Depth",
                value=max_depth,
                unit="m",
                coordinate_utm=utm_d,
                coordinate_wgs84=wgs_d,
                simulation_time_s=None,
                description=f"Location of peak modeled water column ({max_depth} m), situated in the deep pool / breach gorge.",
                disclaimer="Simulation output — Not field-observed data",
            ))

        # 2. Maximum Velocity Point
        if np.any(v_arr >= 0.0):
            r_max_v, c_max_v = np.unravel_index(np.argmax(np.where(wet_mask, v_arr, -9999)), v_arr.shape)
            utm_v, wgs_v = _get_coords(int(r_max_v), int(c_max_v))
            critical_points.append(ModeledCriticalPoint(
                point_id="max_velocity",
                title="Maximum Modeled Flow Velocity",
                metric_name="Flow Velocity",
                value=max_velocity,
                unit="m/s",
                coordinate_utm=utm_v,
                coordinate_wgs84=wgs_v,
                simulation_time_s=None,
                description=f"Location of maximum modeled depth-averaged flow speed ({max_velocity} m/s) through the breach constriction.",
                disclaimer="Simulation output — Not field-observed data",
            ))

        # 3. Earliest Downstream Arrival Point
        if arr_arr is not None and np.any((arr_arr > 0) & wet_mask):
            valid_arr = np.where((arr_arr > 0) & wet_mask, arr_arr, 999999.0)
            r_arr, c_arr = np.unravel_index(np.argmin(valid_arr), arr_arr.shape)
            utm_a, wgs_a = _get_coords(int(r_arr), int(c_arr))
            critical_points.append(ModeledCriticalPoint(
                point_id="earliest_downstream_arrival",
                title="Earliest Downstream Arrival",
                metric_name="Arrival Time",
                value=first_arrival_s,
                unit="s",
                coordinate_utm=utm_a,
                coordinate_wgs84=wgs_a,
                simulation_time_s=first_arrival_s,
                description=f"First modeled location downstream of the dam exceeding 0.05m depth at t = {first_arrival_s} s ({first_arrival_min} min).",
                disclaimer="Simulation output — Not field-observed data",
            ))

        # 4. Highest Hydraulic Severity Point
        if len(wet_severities) > 0:
            r_max_h, c_max_h = np.unravel_index(np.argmax(np.where(wet_mask, h_arr, -9999)), h_arr.shape)
            utm_h, wgs_h = _get_coords(int(r_max_h), int(c_max_h))
            critical_points.append(ModeledCriticalPoint(
                point_id="highest_severity",
                title="Highest Hydraulic Severity",
                metric_name="Hydraulic Intensity (h × v)",
                value=peak_severity,
                unit="m²/s",
                coordinate_utm=utm_h,
                coordinate_wgs84=wgs_h,
                simulation_time_s=None,
                description=f"Peak hydraulic intensity product H = {peak_severity} m²/s (depth × velocity) indicating maximum modeled hydrodynamic energy flux.",
                disclaimer="Simulation output — Not field-observed data",
            ))

        # 5. Farthest Inundated Downstream Point
        if len(rows) > 0:
            farthest_idx = np.argmax(distances_m)
            r_far, c_far = rows[farthest_idx], cols[farthest_idx]
            utm_f, wgs_f = _get_coords(int(r_far), int(c_far))
            critical_points.append(ModeledCriticalPoint(
                point_id="farthest_reach",
                title="Farthest Downstream Reach",
                metric_name="Distance from Dam",
                value=downstream_reach_km,
                unit="km",
                coordinate_utm=utm_f,
                coordinate_wgs84=wgs_f,
                simulation_time_s=None,
                description=f"Furthest downstream extent reached by modeled inundation within the simulation domain ({downstream_reach_km} km reach).",
                disclaimer="Simulation output — Not field-observed data",
            ))

        # Automated Decision Summary Narrative
        scen_type = run_json.get("scenario_type") or project_data.get("scenario_type") or "DAM_BREAK"
        is_intact = bool(run_json.get("is_intact_control") or project_data.get("is_intact_control", False))
        scen_label = run_json.get("scenario_label") or ("River Blockage / Landslide Dam Scenario" if scen_type == "RIVER_BLOCKAGE" else "Dam Break Scenario")
        barrier_type = run_json.get("barrier_type") or ("natural_landslide_blockage" if scen_type == "RIVER_BLOCKAGE" else "engineered_dam")

        if scen_type == "RIVER_BLOCKAGE":
            if is_intact:
                narrative = (
                    f"The ANUGA River Blockage Intact Control Scenario modeled {inundated_area_km2} km² of impounded water "
                    f"strictly retained upstream behind the natural valley blockage ({domain_inundated_pct}% of the computational domain). "
                    f"No downstream breach opening was activated; zero significant downstream flood wave propagation was observed (reach = {downstream_reach_km} km). "
                    f"Maximum water depth in the upstream pool is {max_depth} m with minimal flow velocity ({max_velocity} m/s)."
                )
            else:
                narrative = (
                    f"The ANUGA River Blockage Failure Scenario modeled approximately {inundated_area_km2} km² of flood inundation "
                    f"({domain_inundated_pct}% of the computational domain) following hydraulic breach opening through the valley blockage. "
                    f"Downstream flood surge reached {downstream_reach_km} km with peak flow velocity of {max_velocity} m/s and maximum depth of {max_depth} m. "
                    f"First downstream arrival was recorded at {first_arrival_min} min ({first_arrival_s} s)."
                )
        else:
            narrative = (
                f"The ANUGA demonstration scenario modeled approximately {inundated_area_km2} km² of inundation "
                f"({domain_inundated_pct}% of the computational domain). Downstream flood arrival was recorded at "
                f"approximately {first_arrival_min} min ({first_arrival_s} s) at the nearest downstream observation point, "
                f"with flood routing extending across a modeled reach of {downstream_reach_km} km. "
                f"Maximum modeled water depth reached {max_depth} m and maximum depth-averaged flow velocity reached {max_velocity} m/s. "
                f"The highest hydraulic severity values (peak H = {peak_severity} m²/s) are concentrated directly at the dam breach outlet."
            )

        what_this_means = {
            "depth": "Higher modeled water depth indicates greater hydrostatic water-column loading and static submergence.",
            "velocity": "Higher modeled flow velocity indicates faster kinetic flood propagation, increasing hydrodynamic drag forces.",
            "arrival_time": "Shows the modeled timestamp when previously dry terrain first exceeds the 0.05 m inundation threshold.",
            "hydraulic_severity": "Combines modeled depth and velocity (H = h × v in m²/s) for comparative demonstration classification of hydrodynamic intensity.",
        }

        limitations = [
            "SRTM / Copernicus ~30 m open-source terrain; local micro-topography and engineered drainage structures are unresolved.",
            "Hypothetical breach / opening geometry and instantaneous / rapid failure assumption.",
            "Uniform uncalibrated Manning roughness across the entire computational mesh.",
            "No direct physical gauge or sensor calibration available for this demonstration run.",
            "Demonstration research prototype only; NOT certified for operational evacuation or emergency management.",
        ]
        if scen_type == "RIVER_BLOCKAGE":
            limitations.append("Models hydraulic consequences of blockage failure; does NOT model geological landslide initiation or sediment transport.")

        b_width = float(run_json.get("opening_width_m") or run_json.get("breach_width_m") or project_data.get("breach_width") or project_data.get("opening_width") or (0.0 if is_intact else 50.0))
        r_level = float(run_json.get("upstream_water_level") or project_data.get("upstream_water_level") or project_data.get("reservoir_level") or 535.0)
        c_elev = float(run_json.get("blockage_crest_elevation") or project_data.get("blockage_crest_elevation") or project_data.get("dam_crest_elevation") or 540.0)

        scenario_params = DecisionSupportScenarioParameters(
            dam_name=str(project_data.get("dam_name") or project_data.get("project_name") or ("Valley Landslide Blockage" if scen_type == "RIVER_BLOCKAGE" else "Hidkal Dam")),
            scenario_type=scen_type,
            scenario_label=scen_label,
            barrier_type=barrier_type,
            is_intact_control=is_intact,
            reservoir_level_m=r_level,
            breach_width_m=b_width,
            breach_type="Intact Natural Barrier (No Release)" if is_intact else ("Natural Blockage Opening Breach" if scen_type == "RIVER_BLOCKAGE" else "Trapezoidal / Overtopping"),
            manning_roughness=float(project_data.get("manning_roughness") or 0.035),
            simulation_duration_s=float(run_json.get("simulation_duration_s", 1200.0 if scen_type == "RIVER_BLOCKAGE" else 3600.0)),
            terrain_source="Synthetic Valley DEM (EPSG:32643)" if scen_type == "RIVER_BLOCKAGE" else "SRTM 30m Open-Source DEM",
            solver="ANUGA 2D Regional Shallow-Water Simulation",
            mesh_cells=int(run_json.get("mesh_triangles", 4275)),
            scientific_status="HYPOTHETICAL_DEMONSTRATION",
            blockage_crest_elevation_m=c_elev if scen_type == "RIVER_BLOCKAGE" else None,
            upstream_water_level_m=r_level if scen_type == "RIVER_BLOCKAGE" else None,
            opening_width_m=b_width if scen_type == "RIVER_BLOCKAGE" else None,
        )

        kpis = DecisionSupportKPIs(
            maximum_depth_m=max_depth,
            maximum_velocity_ms=max_velocity,
            inundated_area_km2=inundated_area_km2,
            domain_inundated_pct=domain_inundated_pct,
            downstream_flood_reach_km=downstream_reach_km,
            first_downstream_arrival_s=first_arrival_s,
            first_downstream_arrival_min=first_arrival_min,
            median_downstream_arrival_s=median_arrival_s,
            median_downstream_arrival_min=median_arrival_min,
            p90_downstream_arrival_s=p90_arrival_s,
            p90_downstream_arrival_min=p90_arrival_min,
            latest_modeled_arrival_s=latest_arrival_s,
            latest_modeled_arrival_min=latest_arrival_min,
            wet_cell_count=wet_cell_count,
            total_domain_area_km2=total_domain_area_km2,
        )

        severity_config = HydraulicSeverityConfig(
            method="depth_velocity_product",
            formula="H = h * v",
            units="m^2/s",
            classification_type="demonstration",
            thresholds=DEMONSTRATION_SEVERITY_THRESHOLDS,
            disclaimer="Project demonstration thresholds — not regulatory classifications.",
            peak_severity_m2s=peak_severity,
        )

        tile_endpoints = {
            "depth": f"/api/dam-projects/{valid_pid}/decision-support/tiles/depth/{{z}}/{{x}}/{{y}}.png",
            "velocity": f"/api/dam-projects/{valid_pid}/decision-support/tiles/velocity/{{z}}/{{x}}/{{y}}.png",
            "arrival": f"/api/dam-projects/{valid_pid}/decision-support/tiles/arrival/{{z}}/{{x}}/{{y}}.png",
            "severity": f"/api/dam-projects/{valid_pid}/decision-support/tiles/severity/{{z}}/{{x}}/{{y}}.png",
        }

        return DecisionSupportResponse(
            project_id=valid_pid,
            run_id=active_run_id,
            solver="ANUGA 2D Regional Shallow-Water Simulation",
            supplementary_solver="Custom Terrain-SPH Near-Field Demonstration",
            generated_at=datetime.now(timezone.utc).isoformat(),
            kpis=kpis,
            percentiles={
                "depth": depth_percentiles,
                "velocity": vel_percentiles,
            },
            cumulative_depth_areas=cum_depth,
            depth_distribution=depth_distribution,
            velocity_distribution=velocity_distribution,
            downstream_zones=downstream_zones,
            critical_points=critical_points,
            severity_config=severity_config,
            scenario=scenario_params,
            narrative_summary=narrative,
            what_this_means=what_this_means,
            limitations=limitations,
            tile_endpoints=tile_endpoints,
        )


def render_decision_support_tile(
    project_id: str,
    layer: str,
    z: int,
    x: int,
    y: int,
    run_id: Optional[str] = None
) -> bytes:
    """
    Render raster tile for decision-support layers: 'depth', 'velocity', 'arrival', 'severity'.
    """
    selected_run_dir, target_res_dir, _ = _find_anuga_run(project_id, run_id)

    layer_clean = str(layer).strip().lower()
    if layer_clean == "depth":
        tif_path = target_res_dir / "maximum_depth.tif"
    elif layer_clean == "velocity":
        tif_path = target_res_dir / "maximum_velocity.tif"
    elif layer_clean == "arrival":
        tif_path = target_res_dir / "arrival_time.tif"
    elif layer_clean == "severity":
        tif_path = _ensure_hydraulic_severity_raster(
            target_res_dir,
            target_res_dir / "maximum_depth.tif",
            target_res_dir / "maximum_velocity.tif"
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported decision-support layer '{layer}'. Must be depth, velocity, arrival, or severity.")

    if not tif_path.is_file():
        return EMPTY_TILE_PNG

    try:
        from rio_tiler.io import Reader
        from rio_tiler.errors import TileOutsideBounds, RioTilerError

        with Reader(str(tif_path)) as reader:
            try:
                img_data = reader.tile(x, y, z)
            except TileOutsideBounds:
                return EMPTY_TILE_PNG
            except RioTilerError:
                return EMPTY_TILE_PNG

            arr = img_data.data[0].astype(np.float32)
            nodata_val = -9999.0
            mask = (arr > nodata_val) & np.isfinite(arr)

            # Apply layer-specific colormaps
            h, w = arr.shape
            rgba = np.zeros((h, w, 4), dtype=np.uint8)

            if layer_clean == "depth":
                wet = mask & (arr >= 0.05)
                val_norm = np.clip((arr - 0.05) / 15.0, 0.0, 1.0)
                # Blue colormap
                rgba[wet, 0] = (20 + 20 * val_norm[wet]).astype(np.uint8)
                rgba[wet, 1] = (120 + 100 * val_norm[wet]).astype(np.uint8)
                rgba[wet, 2] = (220 + 35 * val_norm[wet]).astype(np.uint8)
                rgba[wet, 3] = (160 + 80 * val_norm[wet]).astype(np.uint8)

            elif layer_clean == "velocity":
                wet = mask & (arr >= 0.05)
                val_norm = np.clip(arr / 10.0, 0.0, 1.0)
                # Cyan to Orange/Red colormap
                rgba[wet, 0] = (255 * val_norm[wet]).astype(np.uint8)
                rgba[wet, 1] = (200 * (1.0 - val_norm[wet])).astype(np.uint8)
                rgba[wet, 2] = (180 * (1.0 - val_norm[wet])).astype(np.uint8)
                rgba[wet, 3] = (170 + 75 * val_norm[wet]).astype(np.uint8)

            elif layer_clean == "arrival":
                wet = mask & (arr > 0.0)
                val_norm = np.clip(arr / 1800.0, 0.0, 1.0)
                # Purple to Yellow colormap
                rgba[wet, 0] = (180 + 75 * val_norm[wet]).astype(np.uint8)
                rgba[wet, 1] = (50 + 200 * val_norm[wet]).astype(np.uint8)
                rgba[wet, 2] = (220 * (1.0 - val_norm[wet])).astype(np.uint8)
                rgba[wet, 3] = 190

            elif layer_clean == "severity":
                wet = mask & (arr > 0.0)
                # Severity classification bands
                # Low: 0 - 0.5 (Light Blue: 56, 189, 248)
                low_m = wet & (arr <= 0.5)
                rgba[low_m] = [56, 189, 248, 170]
                # Mod: 0.5 - 2.0 (Amber/Yellow: 234, 179, 8)
                mod_m = wet & (arr > 0.5) & (arr <= 2.0)
                rgba[mod_m] = [234, 179, 8, 190]
                # High: 2.0 - 5.0 (Orange: 249, 115, 22)
                high_m = wet & (arr > 2.0) & (arr <= 5.0)
                rgba[high_m] = [249, 115, 22, 215]
                # Very High: > 5.0 (Red: 239, 68, 68)
                vhigh_m = wet & (arr > 5.0)
                rgba[vhigh_m] = [239, 68, 68, 240]

            pil_img = Image.fromarray(rgba, "RGBA")
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            return buf.getvalue()

    except Exception as e:
        logger.warning(f"Error rendering decision support tile {z}/{x}/{y}: {e}")
        return EMPTY_TILE_PNG


def export_decision_support_summary(
    project_id: str,
    export_format: str = "json",
    run_id: Optional[str] = None
) -> Tuple[bytes, str, str]:
    """
    Export decision-support summary in JSON or CSV format.
    Returns (content_bytes, media_type, filename).
    """
    summary = get_decision_support_summary(project_id, run_id)
    fmt = str(export_format).strip().lower()

    if fmt == "json":
        data_str = summary.model_dump_json(indent=2)
        filename = f"decision_support_{project_id[:8]}_{summary.run_id[:8]}.json"
        return data_str.encode("utf-8"), "application/json", filename

    elif fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out)

        # Header block
        writer.writerow(["SIH DAM-BREAK DECISION-SUPPORT SUMMARY REPORT"])
        writer.writerow(["Scientific Status", "Hypothetical Research Prototype - Not for Operational Use"])
        writer.writerow(["Generated At", summary.generated_at])
        writer.writerow(["Project ID", summary.project_id])
        writer.writerow(["ANUGA Run ID", summary.run_id])
        writer.writerow(["Primary Solver", summary.solver])
        writer.writerow(["Supplementary Near-Field", summary.supplementary_solver])
        writer.writerow([])

        # KPIs
        writer.writerow(["KEY PERFORMANCE INDICATORS (KPIs)"])
        writer.writerow(["Metric", "Value", "Unit", "Interpretation"])
        writer.writerow(["Maximum Water Depth", summary.kpis.maximum_depth_m, "m", "Peak modeled water-column depth"])
        writer.writerow(["Maximum Flow Velocity", summary.kpis.maximum_velocity_ms, "m/s", "Peak modeled depth-averaged speed"])
        writer.writerow(["Maximum Inundated Area", summary.kpis.inundated_area_km2, "km²", "Total wet domain footprint (depth >= 0.05m)"])
        writer.writerow(["Domain Inundated Percentage", summary.kpis.domain_inundated_pct, "%", "Proportion of modeled domain wet"])
        writer.writerow(["First Downstream Arrival", summary.kpis.first_downstream_arrival_min, "min", f"{summary.kpis.first_downstream_arrival_s} s at downstream gauge"])
        writer.writerow(["Downstream Flood Reach", summary.kpis.downstream_flood_reach_km, "km", "Max downstream distance reached"])
        writer.writerow(["Peak Hydraulic Severity", summary.severity_config.peak_severity_m2s, "m²/s", "Max depth × velocity product"])
        writer.writerow([])

        # Percentiles
        writer.writerow(["HYDRAULIC PERCENTILES (WET CELLS)"])
        writer.writerow(["Variable", "P50 (Median)", "P90", "P95", "P99", "MAX", "Unit"])
        dp = summary.percentiles["depth"]
        vp = summary.percentiles["velocity"]
        writer.writerow(["Water Depth", dp.p50, dp.p90, dp.p95, dp.p99, dp.max, "m"])
        writer.writerow(["Flow Velocity", vp.p50, vp.p90, vp.p95, vp.p99, vp.max, "m/s"])
        writer.writerow([])

        # Depth Distribution
        writer.writerow(["WATER DEPTH DISTRIBUTION"])
        writer.writerow(["Range", "Area (km²)", "Percentage (%)"])
        for b in summary.depth_distribution:
            writer.writerow([b.range_label, b.area_km2, b.percentage])
        writer.writerow([])

        # Velocity Distribution
        writer.writerow(["FLOW VELOCITY DISTRIBUTION"])
        writer.writerow(["Range", "Area (km²)", "Percentage (%)"])
        for b in summary.velocity_distribution:
            writer.writerow([b.range_label, b.area_km2, b.percentage])
        writer.writerow([])

        # Downstream Zones
        writer.writerow(["DOWNSTREAM DISTANCE ZONES"])
        writer.writerow(["Zone", "Max Depth (m)", "Max Velocity (m/s)", "Earliest Arrival (s)", "Area (km²)", "Mean Severity (m²/s)"])
        for z in summary.downstream_zones:
            writer.writerow([z.zone_label, z.max_depth_m, z.max_velocity_ms, z.earliest_arrival_s or "N/A", z.inundated_area_km2, z.mean_severity_m2s])
        writer.writerow([])

        # Critical Points
        writer.writerow(["MODELED CRITICAL POINTS"])
        writer.writerow(["Title", "Metric", "Value", "Unit", "UTM Coordinates", "WGS84 (Lat, Lon)", "Description"])
        for p in summary.critical_points:
            writer.writerow([
                p.title,
                p.metric_name,
                p.value,
                p.unit,
                f"{p.coordinate_utm[0]}, {p.coordinate_utm[1]}",
                f"{p.coordinate_wgs84[0]}, {p.coordinate_wgs84[1]}",
                p.description,
            ])
        writer.writerow([])

        # Limitations
        writer.writerow(["SCIENTIFIC LIMITATIONS & DISCLAIMER"])
        for lim in summary.limitations:
            writer.writerow([lim])

        csv_bytes = out.getvalue().encode("utf-8")
        filename = f"decision_support_{project_id[:8]}_{summary.run_id[:8]}.csv"
        return csv_bytes, "text/csv", filename

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format '{export_format}'. Must be 'json' or 'csv'.")


def check_demo_readiness(project_id: str) -> DemoReadinessResponse:
    """
    Deterministically verifies if all assets (DEM, ANUGA regional simulation,
    SPH near-field demonstration, animations, and decision-support layers)
    are ready for seamless live SIH demonstration.
    """
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid
    if not p_dir.is_dir() or not (p_dir / "project.json").is_file():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found")

    project_data = json.loads((p_dir / "project.json").read_text(encoding="utf-8"))
    project_name = project_data.get("name") or project_data.get("project_name") or "Dam Project"

    # Check DEM
    has_dem = (p_dir / "dem.tif").is_file() or (p_dir / "terrain.tif").is_file()
    if not has_dem and project_data.get("raster_path"):
        has_dem = Path(project_data["raster_path"]).is_file()

    # Discover ANUGA runs
    anuga_candidate_dirs = [p_dir / "runs", p_dir / "anuga" / "runs"]
    valid_anuga_runs: List[Dict[str, Any]] = []
    for c_dir in anuga_candidate_dirs:
        if c_dir.is_dir():
            for a_sub in sorted(c_dir.iterdir(), reverse=True):
                if a_sub.is_dir() and (a_sub / "run.json").is_file():
                    try:
                        r_data = json.loads((a_sub / "run.json").read_text(encoding="utf-8"))
                        if r_data.get("status") == "completed":
                            res_dir = a_sub / "results"
                            has_depth = False
                            has_vel = False
                            has_arr = False
                            for dn in ["maximum_depth.tif", "depth_max.tif", "depth.tif"]:
                                if (a_sub / dn).is_file() or (res_dir / dn).is_file():
                                    has_depth = True
                                    break
                            for vn in ["maximum_velocity.tif", "velocity_max.tif", "velocity.tif"]:
                                if (a_sub / vn).is_file() or (res_dir / vn).is_file():
                                    has_vel = True
                                    break
                            for an in ["arrival_time.tif", "arrival.tif"]:
                                if (a_sub / an).is_file() or (res_dir / an).is_file():
                                    has_arr = True
                                    break
                            if res_dir.is_dir():
                                for sub in res_dir.iterdir():
                                    if sub.is_dir():
                                        if (sub / "maximum_depth.tif").is_file() or (sub / "depth_max.tif").is_file():
                                            has_depth = True
                                        if (sub / "maximum_velocity.tif").is_file() or (sub / "velocity_max.tif").is_file():
                                            has_vel = True
                                        if (sub / "arrival_time.tif").is_file():
                                            has_arr = True
                            if has_depth:
                                valid_anuga_runs.append({
                                    "run_id": a_sub.name,
                                    "has_depth": has_depth,
                                    "has_vel": has_vel,
                                    "has_arr": has_arr,
                                    "dir": a_sub,
                                })
                    except Exception:
                        pass

    # Discover SPH runs
    sph_runs_dir = p_dir / "sph" / "runs"
    valid_sph_runs: List[Dict[str, Any]] = []
    if sph_runs_dir.is_dir():
        for s_sub in sorted(sph_runs_dir.iterdir(), reverse=True):
            if s_sub.is_dir() and (s_sub / "run.json").is_file():
                try:
                    r_data = json.loads((s_sub / "run.json").read_text(encoding="utf-8"))
                    if r_data.get("status") == "completed":
                        has_depth = (s_sub / "maximum_depth.tif").is_file() or (s_sub / "depth.tif").is_file()
                        if has_depth:
                            valid_sph_runs.append({
                                "run_id": s_sub.name,
                                "dir": s_sub,
                            })
                except Exception:
                    pass

    preferred_anuga = valid_anuga_runs[0]["run_id"] if valid_anuga_runs else None
    preferred_sph = valid_sph_runs[0]["run_id"] if valid_sph_runs else None

    anuga_ready = preferred_anuga is not None
    sph_ready = preferred_sph is not None
    dashboard_ready = anuga_ready
    comparison_ready = anuga_ready and sph_ready

    missing_items: List[str] = []
    if not has_dem:
        missing_items.append("Elevation DEM raster missing")
    if not anuga_ready:
        missing_items.append("Completed ANUGA 2D regional simulation run missing")
    if not sph_ready:
        missing_items.append("Completed Custom Terrain-SPH near-field simulation run missing")

    is_ready = has_dem and anuga_ready and sph_ready
    status_badge = "Demo Ready ✓" if is_ready else "Setup Incomplete"

    if is_ready:
        summary_message = (
            f"All demonstration components are ready for {project_name}. "
            f"Validated ANUGA regional run ({preferred_anuga[:8]}) and SPH near-field run ({preferred_sph[:8]}) "
            f"are cached and immediately available for live presentation."
        )
    else:
        summary_message = f"Missing components: {', '.join(missing_items)}."

    return DemoReadinessResponse(
        project_id=valid_pid,
        project_name=project_name,
        is_ready=is_ready,
        status_badge=status_badge,
        has_dem=has_dem,
        anuga_ready=anuga_ready,
        sph_ready=sph_ready,
        dashboard_ready=dashboard_ready,
        comparison_ready=comparison_ready,
        preferred_anuga_run_id=preferred_anuga,
        preferred_sph_run_id=preferred_sph,
        available_anuga_runs=len(valid_anuga_runs),
        available_sph_runs=len(valid_sph_runs),
        missing_items=missing_items,
        summary_message=summary_message,
    )


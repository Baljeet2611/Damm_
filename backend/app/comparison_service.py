"""
Comparison Service: Multi-Engine Benchmark & Hydrodynamic Comparison Boundary

Compares Delft3D Flexible Mesh (Eulerian Shallow Water Equations) and Smoothed Particle
Hydrodynamics (Lagrangian PySPH) simulation runs.

SCIENTIFIC CONSTRAINTS & HONEST BENCHMARKING:
1. Hydrodynamic comparison requires GENUINE completed runs with verified physical units,
   consistent coordinate reference systems, and overlapping spatial extents.
2. Existing sample rasters in the repository are unverified hydraulic samples and are NEVER
   assigned to or claimed as Delft3D or SPH outputs.
3. If runs are missing, unverified, or incompatible, the service returns status:
   "comparison_unavailable" with explicit blockers rather than synthetic metrics.
4. Reprojection to a common reference grid is performed dynamically in temporary memory
   without altering original run artifacts.
"""

import json
import logging
from pathlib import Path
from typing import List, Optional
import numpy as np

try:
    import rasterio
    from rasterio.warp import reproject, Resampling
    from rasterio.crs import CRS
    RASTERIO_AVAILABLE = True
except ImportError:
    RASTERIO_AVAILABLE = False

from app.schemas import (
    ComparisonRunSummary,
    ComparisonReadinessResponse,
    ComparisonResponse,
    RasterMetricStats,
    MethodologyComparisonResponse,
)
from app.simulation_service import list_simulation_runs
from app.sph_service import list_sph_runs, SPH_RUNS_DIR

logger = logging.getLogger(__name__)


def check_comparison_readiness() -> ComparisonReadinessResponse:
    """
    Evaluates availability of completed Delft3D FM and PySPH simulation runs
    with verified output rasters and physical units.
    """
    delft3d_runs = list_simulation_runs()
    sph_runs = list_sph_runs()

    delft3d_summaries: List[ComparisonRunSummary] = []
    for r in delft3d_runs:
        run_id = r.get("run_id", "")
        run_dir = Path(r.get("run_dir", ""))
        has_depth = (run_dir / "depth.tif").exists() or (run_dir / "max_depth.tif").exists()
        has_vel = (run_dir / "velocity.tif").exists() or (run_dir / "max_velocity.tif").exists()
        manifest_file = run_dir / "run_manifest.json"
        units_verified = False
        if manifest_file.exists():
            try:
                mdata = json.loads(manifest_file.read_text(encoding="utf-8"))
                units_verified = mdata.get("units_verified", False)
            except Exception:
                pass
        
        delft3d_summaries.append(
            ComparisonRunSummary(
                run_id=run_id,
                scenario_id=r.get("scenario_id", ""),
                scenario_name=r.get("scenario_name", "Unknown"),
                engine="Delft3D Flexible Mesh (SWE)",
                status=r.get("status", "unknown"),
                completed_at=r.get("completed_at"),
                has_depth_raster=has_depth,
                has_velocity_raster=has_vel,
                units_verified=units_verified,
            )
        )

    sph_summaries: List[ComparisonRunSummary] = []
    for r in sph_runs:
        run_id = r.get("run_id", "")
        run_dir = SPH_RUNS_DIR / run_id
        has_depth = (run_dir / "depth.tif").exists() or (run_dir / "output_depth.tif").exists()
        has_vel = (run_dir / "velocity.tif").exists() or (run_dir / "output_velocity.tif").exists()
        manifest_file = run_dir / "run_manifest.json"
        units_verified = False
        if manifest_file.exists():
            try:
                mdata = json.loads(manifest_file.read_text(encoding="utf-8"))
                units_verified = mdata.get("units_verified", False)
            except Exception:
                pass

        sph_summaries.append(
            ComparisonRunSummary(
                run_id=run_id,
                scenario_id=r.get("scenario_id", ""),
                scenario_name=r.get("scenario_name", "Unknown"),
                engine="PySPH (Lagrangian Particles)",
                status=r.get("status", "unknown"),
                completed_at=r.get("completed_at"),
                has_depth_raster=has_depth,
                has_velocity_raster=has_vel,
                units_verified=units_verified,
            )
        )

    # Readiness check: require at least one completed run with verified units from each engine
    valid_delft = [s for s in delft3d_summaries if s.status == "completed" and s.has_depth_raster and s.units_verified]
    valid_sph = [s for s in sph_summaries if s.status == "completed" and s.has_depth_raster and s.units_verified]

    ready = len(valid_delft) > 0 and len(valid_sph) > 0
    blocker = None
    if not ready:
        blockers = []
        if len(valid_delft) == 0:
            blockers.append("No completed Delft3D FM simulation runs with verified unit manifests found.")
        if len(valid_sph) == 0:
            blockers.append("No completed PySPH simulation runs with verified unit manifests found.")
        blocker = " ".join(blockers)

    return ComparisonReadinessResponse(
        delft3d_completed_runs=delft3d_summaries,
        sph_completed_runs=sph_summaries,
        comparison_ready=ready,
        blocker_reason=blocker,
        methodology_summary=(
            "Multi-engine comparison matches Eulerian 2D shallow water hydrodynamic results "
            "against Lagrangian mesh-free SPH particle distributions resampled to a common grid. "
            "Requires verified CRS, depth (m), and velocity (m/s) raster outputs."
        )
    )


def _compute_raster_metrics(arr1: np.ndarray, arr2: np.ndarray, param: str, unit: str) -> Optional[RasterMetricStats]:
    """
    Computes MAE, RMSE, Mean Bias, and Max Absolute Delta between two aligned numpy arrays.
    Only considers cells where both values are valid non-NaN numbers.
    """
    valid_mask = np.isfinite(arr1) & np.isfinite(arr2)
    valid_count = int(np.sum(valid_mask))
    if valid_count == 0:
        return None

    v1 = arr1[valid_mask]
    v2 = arr2[valid_mask]

    diff = v2 - v1  # SPH minus Delft3D
    abs_diff = np.abs(diff)

    mae = float(np.mean(abs_diff))
    rmse = float(np.sqrt(np.mean(diff ** 2)))
    bias = float(np.mean(diff))
    max_d = float(np.max(abs_diff))

    return RasterMetricStats(
        parameter=param,
        unit=unit,
        valid_cells=valid_count,
        mae=round(mae, 4),
        rmse=round(rmse, 4),
        mean_bias=round(bias, 4),
        max_delta=round(max_d, 4),
    )


def compare_runs(delft3d_run_id: str, sph_run_id: str, reproject_crs: str = "EPSG:4326") -> ComparisonResponse:
    """
    Executes quantitative spatial and statistical comparison between a Delft3D run and a PySPH run.
    If runs or outputs are missing/incompatible, returns structured comparison_unavailable response.
    """
    blockers: List[str] = []
    notes: List[str] = [
        "Hydrodynamic multi-engine comparison protocol initialized.",
        "Reprojection and statistical alignment are performed strictly in temporary memory."
    ]

    from app.simulation_service import get_runs_dir
    from app.sph_service import get_sph_runs_dir

    runs_dir = get_runs_dir()
    sph_runs_dir = get_sph_runs_dir()

    d_dir = runs_dir / delft3d_run_id
    s_dir = sph_runs_dir / sph_run_id

    if not d_dir.is_dir():
        blockers.append(f"Delft3D run '{delft3d_run_id}' not found in simulation storage.")
    if not s_dir.is_dir():
        blockers.append(f"PySPH run '{sph_run_id}' not found in SPH storage.")

    if blockers:
        return ComparisonResponse(
            delft3d_run_id=delft3d_run_id,
            sph_run_id=sph_run_id,
            status="comparison_unavailable",
            common_crs=reproject_crs,
            common_grid_shape=(0, 0),
            valid_overlap_cells=0,
            overlap_area_km2=0.0,
            extent_iou=0.0,
            critical_success_index=0.0,
            projected_area_diff_km2=0.0,
            notes=notes,
            blockers=blockers,
        )

    # Check raster existence
    d_depth_path = d_dir / "depth.tif" if (d_dir / "depth.tif").exists() else (d_dir / "max_depth.tif")
    s_depth_path = s_dir / "depth.tif" if (s_dir / "depth.tif").exists() else (s_dir / "output_depth.tif")

    if not d_depth_path.exists():
        blockers.append(f"Delft3D run '{delft3d_run_id}' has no output depth raster (depth.tif).")
    if not s_depth_path.exists():
        blockers.append(f"PySPH run '{sph_run_id}' has no output depth raster (depth.tif).")

    # Check manifest verification
    d_manifest = d_dir / "run_manifest.json"
    s_manifest = s_dir / "run_manifest.json"

    d_verified = False
    s_verified = False

    if d_manifest.exists():
        try:
            m = json.loads(d_manifest.read_text(encoding="utf-8"))
            d_verified = m.get("units_verified", False)
        except Exception:
            pass
    if s_manifest.exists():
        try:
            m = json.loads(s_manifest.read_text(encoding="utf-8"))
            s_verified = m.get("units_verified", False)
        except Exception:
            pass

    if not d_verified:
        blockers.append(f"Delft3D run '{delft3d_run_id}' does not have verified units in run_manifest.json.")
    if not s_verified:
        blockers.append(f"PySPH run '{sph_run_id}' does not have verified units in run_manifest.json.")

    if blockers or not RASTERIO_AVAILABLE:
        if not RASTERIO_AVAILABLE:
            blockers.append("Rasterio library is required for spatial reprojection and cell alignment.")
        return ComparisonResponse(
            delft3d_run_id=delft3d_run_id,
            sph_run_id=sph_run_id,
            status="comparison_unavailable",
            common_crs=reproject_crs,
            common_grid_shape=(0, 0),
            valid_overlap_cells=0,
            overlap_area_km2=0.0,
            extent_iou=0.0,
            critical_success_index=0.0,
            projected_area_diff_km2=0.0,
            notes=notes,
            blockers=blockers,
        )

    try:
        # Reproject depth rasters to common bounding box in target CRS
        with rasterio.open(d_depth_path) as src_d, rasterio.open(s_depth_path) as src_s:
            dst_crs = CRS.from_string(reproject_crs)
            
            # Compute common bounding box in dst_crs
            bounds_d = rasterio.warp.transform_bounds(src_d.crs, dst_crs, *src_d.bounds)
            bounds_s = rasterio.warp.transform_bounds(src_s.crs, dst_crs, *src_s.bounds)

            # Intersection bounding box
            min_x = max(bounds_d[0], bounds_s[0])
            min_y = max(bounds_d[1], bounds_s[1])
            max_x = min(bounds_d[2], bounds_s[2])
            max_y = min(bounds_d[3], bounds_s[3])

            if min_x >= max_x or min_y >= max_y:
                blockers.append("Runs have disjoint spatial extents with zero spatial overlap.")
                return ComparisonResponse(
                    delft3d_run_id=delft3d_run_id,
                    sph_run_id=sph_run_id,
                    status="comparison_unavailable",
                    common_crs=reproject_crs,
                    common_grid_shape=(0, 0),
                    valid_overlap_cells=0,
                    overlap_area_km2=0.0,
                    extent_iou=0.0,
                    critical_success_index=0.0,
                    projected_area_diff_km2=0.0,
                    notes=notes,
                    blockers=blockers,
                )

            # Standard comparison grid resolution (approx 10m or 0.0001 deg)
            res = 0.0001
            width = max(10, int((max_x - min_x) / res))
            height = max(10, int((max_y - min_y) / res))
            dst_transform = rasterio.transform.from_bounds(min_x, min_y, max_x, max_y, width, height)

            arr_d = np.full((height, width), np.nan, dtype=np.float32)
            arr_s = np.full((height, width), np.nan, dtype=np.float32)

            reproject(
                source=rasterio.band(src_d, 1),
                destination=arr_d,
                src_transform=src_d.transform,
                src_crs=src_d.crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
            )

            reproject(
                source=rasterio.band(src_s, 1),
                destination=arr_s,
                src_transform=src_s.transform,
                src_crs=src_s.crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
            )

        # Depth Stats
        depth_stats = _compute_raster_metrics(arr_d, arr_s, "water_depth", "meters")

        # Spatial Extent Metrics (threshold > 0.05m flood depth)
        flood_d = np.isfinite(arr_d) & (arr_d > 0.05)
        flood_s = np.isfinite(arr_s) & (arr_s > 0.05)

        intersection = np.sum(flood_d & flood_s)
        union = np.sum(flood_d | flood_s)
        hits = intersection
        false_alarms = np.sum((~flood_d) & flood_s)
        misses = np.sum(flood_d & (~flood_s))

        iou = float(intersection / union) if union > 0 else 0.0
        csi_denom = hits + false_alarms + misses
        csi = float(hits / csi_denom) if csi_denom > 0 else 0.0

        # Approximate cell area in km2
        # At latitude ~16 deg: 1 deg lat ~ 111 km, 1 deg lon ~ 106 km
        cell_area_km2 = (res * 111.0) * (res * 106.0)
        area_d_km2 = float(np.sum(flood_d) * cell_area_km2)
        area_s_km2 = float(np.sum(flood_s) * cell_area_km2)
        area_diff_km2 = float(abs(area_s_km2 - area_d_km2))
        overlap_area_km2 = float(intersection * cell_area_km2)

        notes.append(f"Common evaluation grid: {width}x{height} cells at {res} deg spacing.")
        notes.append(f"Delft3D flooded area: {area_d_km2:.3f} km2; PySPH flooded area: {area_s_km2:.3f} km2.")

        # Check for velocity raster alignment
        velocity_stats = None
        d_vel_path = d_dir / "velocity.tif" if (d_dir / "velocity.tif").exists() else (d_dir / "max_velocity.tif")
        s_vel_path = s_dir / "velocity.tif" if (s_dir / "velocity.tif").exists() else (s_dir / "output_velocity.tif")
        if d_vel_path.exists() and s_vel_path.exists():
            with rasterio.open(d_vel_path) as v_d, rasterio.open(s_vel_path) as v_s:
                arr_vd = np.full((height, width), np.nan, dtype=np.float32)
                arr_vs = np.full((height, width), np.nan, dtype=np.float32)
                reproject(rasterio.band(v_d, 1), arr_vd, src_transform=v_d.transform, src_crs=v_d.crs, dst_transform=dst_transform, dst_crs=dst_crs, resampling=Resampling.bilinear)
                reproject(rasterio.band(v_s, 1), arr_vs, src_transform=v_s.transform, src_crs=v_s.crs, dst_transform=dst_transform, dst_crs=dst_crs, resampling=Resampling.bilinear)
                velocity_stats = _compute_raster_metrics(arr_vd, arr_vs, "flow_velocity", "m/s")

        return ComparisonResponse(
            delft3d_run_id=delft3d_run_id,
            sph_run_id=sph_run_id,
            status="completed",
            common_crs=reproject_crs,
            common_grid_shape=(height, width),
            valid_overlap_cells=int(np.sum(np.isfinite(arr_d) & np.isfinite(arr_s))),
            overlap_area_km2=round(overlap_area_km2, 4),
            extent_iou=round(iou, 4),
            critical_success_index=round(csi, 4),
            projected_area_diff_km2=round(area_diff_km2, 4),
            depth_stats=depth_stats,
            velocity_stats=velocity_stats,
            notes=notes,
            blockers=[],
        )

    except Exception as e:
        logger.exception("Error executing raster comparison")
        blockers.append(f"Spatial alignment error: {str(e)}")
        return ComparisonResponse(
            delft3d_run_id=delft3d_run_id,
            sph_run_id=sph_run_id,
            status="comparison_unavailable",
            common_crs=reproject_crs,
            common_grid_shape=(0, 0),
            valid_overlap_cells=0,
            overlap_area_km2=0.0,
            extent_iou=0.0,
            critical_success_index=0.0,
            projected_area_diff_km2=0.0,
            notes=notes,
            blockers=blockers,
        )


def get_methodology_comparison() -> MethodologyComparisonResponse:
    """
    Returns structured architectural and physical comparison matrix between
    Delft3D Flexible Mesh and Smoothed Particle Hydrodynamics (PySPH).
    """
    matrix = [
        {
            "dimension": "Governing Equations",
            "delft3d_fm": "2D / 3D Shallow Water Equations (SWE) based on Reynolds-Averaged Navier-Stokes with hydrostatic pressure assumption.",
            "pysph": "Full Navier-Stokes equations with weakly compressible (WCSPH) or incompressible formulations without hydrostatic assumptions.",
            "operational_implication": "Delft3D excels in broad floodplain propagation; SPH captures near-field 3D splash, wave overtopping, and structure impact."
        },
        {
            "dimension": "Computational Discretization",
            "delft3d_fm": "Eulerian unstructured grid (triangles, quadrilaterals, 1D channels) with curvilinear adaptation.",
            "pysph": "Lagrangian mesh-free particle discretization with kernel smoothing functions (Wendland quintic / Gaussian).",
            "operational_implication": "Eulerian grids handle massive river reaches (>100 km) efficiently; Lagrangian particles eliminate mesh distortion during rapid violent deformation."
        },
        {
            "dimension": "Free Surface & Wave Breaking",
            "delft3d_fm": "Single-valued water surface elevation per grid cell with shock-capturing Riemann solvers.",
            "pysph": "Naturally tracks multi-valued, violently overturning, plunging, and fragmenting free surfaces without surface tracking.",
            "operational_implication": "SPH is required for near-dam breach crest splash and turbulent bore collapse; Delft3D is required for downstream valley inundation."
        },
        {
            "dimension": "Boundary & Roughness Representation",
            "delft3d_fm": "Spatially variable Manning's n, Chezy, or White-Colebrook bottom friction applied directly to cell faces.",
            "pysph": "Solid boundary particles with ghost-particle/repulsive force models; macro-roughness requires explicit geometric resolution.",
            "operational_implication": "Calibrated land-use Manning roughness is standard in Delft3D; SPH boundary friction calibration over rough terrain is computationally intensive."
        },
        {
            "dimension": "Computational Scalability",
            "delft3d_fm": "Scalable for domain reaches of 10-100 km at 10-100m cell resolution with standard multi-core CPU architectures.",
            "pysph": "High computational cost (O(N*k) neighbor search); practical on standard CPUs only for small benchmarks (domains < 100m, N < 100k particles).",
            "operational_implication": "PySPH is documented as an academic/near-structure benchmark solver. Regional valley inundation must use Delft3D FM or SWE solvers."
        }
    ]

    limitations = (
        "SCALE LIMITATION DISCLAIMER: PySPH dam-break configurations generated in this system "
        "model laboratory-scale benchmark collapse experiments (e.g., Martin & Moyce column collapse). "
        "Applying PySPH to regional downstream domains (>25 km) requires massive GPU supercomputing "
        "or hybrid Eulerian-Lagrangian coupling and is not supported on single-node execution."
    )

    disclaimer = (
        "SCIENTIFIC INTEGRITY NOTICE: Comparison metrics are only computed when both solvers have "
        "completed authentic model executions with verified physical units. Existing sample rasters "
        "in the repository are unverified hydraulic samples and are never attributed to either engine."
    )

    return MethodologyComparisonResponse(
        comparison_matrix=matrix,
        scale_limitations=limitations,
        disclaimer=disclaimer,
    )

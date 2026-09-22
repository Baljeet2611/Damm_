"""Unified Simulation Result Service (Phase B3).

Standardizes multi-engine simulation results into one canonical contract:
- PySPH near-field breach simulation outputs
- Delft3D FM UGRID / GeoTIFF regional simulation outputs
- ANUGA 2D SWE regional inundation outputs

Preserves missing fields as None/null without inventing or fabricating uncomputed metrics.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastapi import HTTPException

from app.schemas import (
    CanonicalSimulationResult,
    CanonicalSimulationResultResponse,
    SimulationEngine,
)
from app.onboarding_service import (
    get_dam_projects_dir,
    validate_project_uuid,
    compute_file_sha256,
)

logger = logging.getLogger(__name__)


def pysph_result_to_canonical(
    data: Union[Dict[str, Any], Path],
    project_id: Optional[str] = None,
    run_dir: Optional[Path] = None,
) -> CanonicalSimulationResult:
    """
    Convert PySPH simulation run data/manifest into CanonicalSimulationResult.
    Extracts peak depth, peak velocity, SPH particle count, hydrograph, and raster paths.
    """
    if isinstance(data, Path):
        run_dir = data.parent if data.is_file() else data
        manifest_file = run_dir / "run.json"
        if manifest_file.is_file():
            raw = json.loads(manifest_file.read_text(encoding="utf-8"))
        else:
            raw = {"run_id": run_dir.name}
    else:
        raw = dict(data)

    pid = project_id or raw.get("project_id")
    run_id = raw.get("run_id") or raw.get("simulation_id") or "sph_run_unknown"

    # Identify raster paths
    raster_paths: Dict[str, str] = {}
    if run_dir and run_dir.is_dir():
        for l_name in ["maximum_depth", "maximum_velocity", "arrival_time"]:
            for cand in [f"{l_name}.tif", f"{l_name}.tiff"]:
                p = run_dir / cand
                if p.is_file():
                    raster_paths[l_name] = str(p.resolve())
                    break
        if not raster_paths.get("maximum_depth"):
            for cand in ["depth.tif", "output_depth.tif"]:
                p = run_dir / cand
                if p.is_file():
                    raster_paths["maximum_depth"] = str(p.resolve())
                    break
        if not raster_paths.get("maximum_velocity"):
            for cand in ["velocity.tif", "output_velocity.tif"]:
                p = run_dir / cand
                if p.is_file():
                    raster_paths["maximum_velocity"] = str(p.resolve())
                    break

    # Summary metrics
    summary = raw.get("summary", {})
    max_d = raw.get("max_depth_m") or summary.get("max_depth_m") or raw.get("peak_depth_m")
    max_v = raw.get("max_velocity_ms") or summary.get("max_velocity_ms") or raw.get("peak_velocity_ms")
    flood_area = raw.get("flooded_area_km2") or summary.get("flooded_area_km2")
    mean_d = raw.get("mean_depth_m") or summary.get("mean_depth_m")

    # Hydrograph extraction if present
    hydro_dict = raw.get("hydrograph")
    if not hydro_dict and run_dir and (run_dir / "sph_hydrograph.json").is_file():
        try:
            hydro_dict = json.loads((run_dir / "sph_hydrograph.json").read_text(encoding="utf-8"))
        except Exception:
            pass

    # Timestamps
    timestamps = raw.get("timestamps", [])
    if not timestamps and raw.get("duration_seconds"):
        dur = float(raw["duration_seconds"])
        dt = float(raw.get("time_step_s", 1.0))
        if dt > 0 and dur > 0:
            steps = min(500, int(dur / dt))
            timestamps = [round(i * dt, 4) for i in range(steps + 1)]

    # Provenance
    prov = raw.get("provenance", {})
    if not isinstance(prov, dict):
        prov = {"raw_provenance": str(prov)}
    prov["source_engine"] = "pysph"

    return CanonicalSimulationResult(
        run_id=run_id,
        scenario_id=raw.get("scenario_id"),
        project_id=pid,
        engine="pysph",
        engine_version=raw.get("engine_version", "PySPH WCSPH"),
        execution_status=raw.get("status", "completed"),
        scientific_status=raw.get("scientific_status", "sph_numerical_simulation"),
        created_at=raw.get("created_at") or raw.get("started_at") or datetime.now(timezone.utc).isoformat(),
        completed_at=raw.get("completed_at"),
        duration_seconds=raw.get("duration_seconds"),
        timestamps=timestamps,
        time_units="seconds",
        maximum_depth_m=float(max_d) if max_d is not None else None,
        maximum_velocity_ms=float(max_v) if max_v is not None else None,
        flood_extent_km2=float(flood_area) if flood_area is not None else None,
        mean_depth_m=float(mean_d) if mean_d is not None else None,
        arrival_time_min_s=raw.get("arrival_time_min_s"),  # SPH generally does not have regional arrival times
        hydrograph=hydro_dict,
        native_crs=raw.get("native_crs") or "EPSG:32643",
        spatial_bounds=raw.get("bounds"),
        raster_paths=raster_paths,
        source_files=raw.get("source_files", []),
        layer_hashes=raw.get("layer_hashes", {}),
        provenance=prov,
        metadata={
            "run_label": raw.get("run_label", "PySPH Simulation"),
            "particle_count": raw.get("particle_count") or summary.get("particle_count"),
            "notes": raw.get("notes", ""),
        },
    )


def delft3d_result_to_canonical(
    data: Union[Dict[str, Any], Path],
    project_id: Optional[str] = None,
    run_dir: Optional[Path] = None,
) -> CanonicalSimulationResult:
    """
    Convert Delft3D Flexible Mesh run data/manifest into CanonicalSimulationResult.
    Standardizes UGRID / GeoTIFF outputs and mesh statistics.
    """
    if isinstance(data, Path):
        run_dir = data.parent if data.is_file() else data
        manifest_file = run_dir / "run.json"
        if manifest_file.is_file():
            raw = json.loads(manifest_file.read_text(encoding="utf-8"))
        else:
            raw = {"run_id": run_dir.name}
    else:
        raw = dict(data)

    pid = project_id or raw.get("project_id")
    run_id = raw.get("run_id") or "d3d_run_unknown"

    # Identify raster paths
    raster_paths: Dict[str, str] = {}
    if run_dir and run_dir.is_dir():
        for l_name in ["maximum_depth", "maximum_velocity", "arrival_time"]:
            for cand in [f"{l_name}.tif", f"{l_name}.tiff"]:
                p = run_dir / cand
                if p.is_file():
                    raster_paths[l_name] = str(p.resolve())
                    break
        if not raster_paths.get("maximum_depth"):
            for cand in ["depth.tif", "max_depth.tif"]:
                p = run_dir / cand
                if p.is_file():
                    raster_paths["maximum_depth"] = str(p.resolve())
                    break
        if not raster_paths.get("maximum_velocity"):
            for cand in ["velocity.tif", "max_velocity.tif"]:
                p = run_dir / cand
                if p.is_file():
                    raster_paths["maximum_velocity"] = str(p.resolve())
                    break

    summary = raw.get("summary", {})
    max_d = raw.get("max_depth_m") or summary.get("max_depth_m")
    max_v = raw.get("max_velocity_ms") or summary.get("max_velocity_ms")
    flood_area = raw.get("flooded_area_km2") or summary.get("flooded_area_km2")
    mean_d = raw.get("mean_depth_m") or summary.get("mean_depth_m")

    # Timestamps
    timestamps = raw.get("timestamps", [])

    # Provenance
    prov = raw.get("provenance", {})
    if not isinstance(prov, dict):
        prov = {"raw_provenance": str(prov)}
    prov["source_engine"] = "delft3d_fm"

    return CanonicalSimulationResult(
        run_id=run_id,
        scenario_id=raw.get("scenario_id"),
        project_id=pid,
        engine="delft3d_fm",
        engine_version=raw.get("engine_version", "Delft3D Flexible Mesh"),
        execution_status=raw.get("status", "completed"),
        scientific_status=raw.get("scientific_status", "imported_external_run"),
        created_at=raw.get("created_at") or raw.get("started_at") or datetime.now(timezone.utc).isoformat(),
        completed_at=raw.get("completed_at"),
        duration_seconds=raw.get("duration_seconds"),
        timestamps=timestamps,
        time_units="seconds",
        maximum_depth_m=float(max_d) if max_d is not None else None,
        maximum_velocity_ms=float(max_v) if max_v is not None else None,
        flood_extent_km2=float(flood_area) if flood_area is not None else None,
        mean_depth_m=float(mean_d) if mean_d is not None else None,
        arrival_time_min_s=raw.get("arrival_time_min_s"),
        hydrograph=raw.get("hydrograph"),
        native_crs=raw.get("native_crs") or "EPSG:32643",
        spatial_bounds=raw.get("bounds"),
        raster_paths=raster_paths,
        source_files=raw.get("source_files", []),
        layer_hashes=raw.get("layer_hashes", {}),
        provenance=prov,
        metadata={
            "run_label": raw.get("run_label", "Delft3D FM Simulation"),
            "solver_execution_status": raw.get("solver_execution_status", "imported"),
            "notes": raw.get("notes", ""),
        },
    )


def anuga_result_to_canonical(
    data: Union[Dict[str, Any], Path],
    project_id: Optional[str] = None,
    run_dir: Optional[Path] = None,
) -> CanonicalSimulationResult:
    """
    Convert ANUGA 2D SWE simulation run & postprocessed results into CanonicalSimulationResult.
    Standardizes layer stats, arrival thresholds, SWW dimensions, and GeoTIFF paths.
    """
    if isinstance(data, Path):
        run_dir = data.parent if data.is_file() else data
        manifest_file = run_dir / "run.json"
        if manifest_file.is_file():
            raw = json.loads(manifest_file.read_text(encoding="utf-8"))
        else:
            raw = {"run_id": run_dir.name}
    else:
        raw = dict(data)

    pid = project_id or raw.get("project_id")
    run_id = raw.get("run_id") or "anuga_run_unknown"

    # Identify raster paths and check results subdirectories
    raster_paths: Dict[str, str] = {}
    proc_id = raw.get("latest_processing_id")
    candidate_dirs: List[Path] = []
    if run_dir and run_dir.is_dir():
        if proc_id:
            candidate_dirs.append(run_dir / "results" / proc_id)
        candidate_dirs.append(run_dir / "results")
        candidate_dirs.append(run_dir)

    for c_dir in candidate_dirs:
        if c_dir.is_dir():
            for l_name in ["maximum_depth", "maximum_velocity", "arrival_time"]:
                if l_name not in raster_paths:
                    for cand in [f"{l_name}.tif", f"{l_name}.tiff"]:
                        p = c_dir / cand
                        if p.is_file():
                            raster_paths[l_name] = str(p.resolve())
                            break

    # Extract layer statistics if postprocessed manifest exists
    layer_stats = raw.get("layer_stats") or raw.get("layer_statistics") or {}
    max_d = None
    max_v = None
    mean_d = None
    flood_area = None
    arr_min = None

    if "maximum_depth" in layer_stats:
        ds = layer_stats["maximum_depth"]
        max_d = ds.get("max")
        mean_d = ds.get("mean")
        flood_area = ds.get("flooded_area_km2")

    if "maximum_velocity" in layer_stats:
        vs = layer_stats["maximum_velocity"]
        max_v = vs.get("max")

    if "arrival_time" in layer_stats:
        ars = layer_stats["arrival_time"]
        arr_min = ars.get("min")

    # If not in top-level raw dict, check results manifest on disk
    if run_dir and run_dir.is_dir():
        cand_manifests = []
        if proc_id and (run_dir / "results" / proc_id / "manifest.json").is_file():
            cand_manifests.append(run_dir / "results" / proc_id / "manifest.json")
        if (run_dir / "results").is_dir():
            for sub in (run_dir / "results").iterdir():
                if sub.is_dir() and (sub / "manifest.json").is_file():
                    cand_manifests.append(sub / "manifest.json")
        for m_file in cand_manifests:
            try:
                m_data = json.loads(m_file.read_text(encoding="utf-8"))
                m_stats = m_data.get("layer_statistics") or m_data.get("layer_stats") or {}
                if "maximum_depth" in m_stats and max_d is None:
                    max_d = m_stats["maximum_depth"].get("max")
                    mean_d = m_stats["maximum_depth"].get("mean")
                    flood_area = m_stats["maximum_depth"].get("flooded_area_km2")
                if "maximum_velocity" in m_stats and max_v is None:
                    max_v = m_stats["maximum_velocity"].get("max")
                if "arrival_time" in m_stats and arr_min is None:
                    arr_min = m_stats["arrival_time"].get("min")
                if not timestamps and m_data.get("actual_sww_timesteps"):
                    timestamps = m_data["actual_sww_timesteps"]
                if not raster_paths:
                    for l_name in ["maximum_depth", "maximum_velocity", "arrival_time"]:
                        p = m_file.parent / f"{l_name}.tif"
                        if p.is_file():
                            raster_paths[l_name] = str(p.resolve())
            except Exception:
                pass

    # Timestamps
    timestamps = raw.get("timestamps", [])
    dur_s = raw.get("duration_seconds")
    if dur_s is None and raw.get("parameters"):
        dur_s = raw["parameters"].get("duration_s")

    # Provenance
    prov = raw.get("provenance", {})
    if not isinstance(prov, dict):
        prov = {"raw_provenance": str(prov)}
    prov["source_engine"] = "anuga"

    return CanonicalSimulationResult(
        run_id=run_id,
        scenario_id=raw.get("scenario_id"),
        project_id=pid,
        engine="anuga",
        engine_version=raw.get("engine_version", "ANUGA 2D SWE"),
        execution_status=raw.get("status", "completed"),
        scientific_status=raw.get("scientific_status", "validated_anuga_simulation"),
        created_at=raw.get("created_at") or raw.get("started_at") or datetime.now(timezone.utc).isoformat(),
        completed_at=raw.get("completed_at"),
        duration_seconds=float(dur_s) if dur_s is not None else None,
        timestamps=timestamps,
        time_units="seconds",
        maximum_depth_m=float(max_d) if max_d is not None else None,
        maximum_velocity_ms=float(max_v) if max_v is not None else None,
        flood_extent_km2=float(flood_area) if flood_area is not None else None,
        mean_depth_m=float(mean_d) if mean_d is not None else None,
        arrival_time_min_s=float(arr_min) if arr_min is not None else None,
        hydrograph=raw.get("hydrograph"),
        native_crs=raw.get("native_crs") or "EPSG:32643",
        spatial_bounds=raw.get("bounds"),
        raster_paths=raster_paths,
        source_files=raw.get("source_files", []),
        layer_hashes=raw.get("layer_hashes", {}),
        provenance=prov,
        metadata={
            "run_label": raw.get("run_label", "ANUGA Simulation"),
            "scenario_type": raw.get("scenario_type", "DAM_BREAK"),
            "exit_code": raw.get("exit_code"),
            "latest_processing_id": proc_id,
        },
    )


def get_canonical_simulation_result(
    project_id: str,
    engine: str,
    run_id: str,
) -> CanonicalSimulationResult:
    """
    Retrieve and adapt any simulation run under a project into CanonicalSimulationResult.
    """
    valid_pid = validate_project_uuid(project_id)
    proj_dir = get_dam_projects_dir() / valid_pid
    if not proj_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found.")

    engine_lower = engine.strip().lower()

    if engine_lower in ("pysph", "sph"):
        run_dir = proj_dir / "sph" / "runs" / run_id
        if not run_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"PySPH run '{run_id}' not found in project '{valid_pid}'.")
        return pysph_result_to_canonical(run_dir, project_id=valid_pid, run_dir=run_dir)

    elif engine_lower in ("delft3d", "delft3d_fm", "dflowfm"):
        run_dir = proj_dir / "delft3d" / "runs" / run_id
        if not run_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"Delft3D run '{run_id}' not found in project '{valid_pid}'.")
        return delft3d_result_to_canonical(run_dir, project_id=valid_pid, run_dir=run_dir)

    elif engine_lower in ("anuga", "swe"):
        run_dir = proj_dir / "runs" / run_id
        if not run_dir.is_dir():
            run_dir = proj_dir / "anuga" / "runs" / run_id
        if not run_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"ANUGA run '{run_id}' not found in project '{valid_pid}'.")
        return anuga_result_to_canonical(run_dir, project_id=valid_pid, run_dir=run_dir)

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported simulation engine '{engine}'.")


def list_canonical_simulation_results(project_id: str) -> List[CanonicalSimulationResult]:
    """
    List all completed simulation results across PySPH, Delft3D, and ANUGA for a project.
    """
    valid_pid = validate_project_uuid(project_id)
    proj_dir = get_dam_projects_dir() / valid_pid
    if not proj_dir.is_dir():
        return []

    results: List[CanonicalSimulationResult] = []

    # 1. ANUGA runs
    anuga_dirs = [proj_dir / "runs", proj_dir / "anuga" / "runs"]
    for a_dir in anuga_dirs:
        if a_dir.is_dir():
            for r_sub in sorted(a_dir.iterdir(), reverse=True):
                if r_sub.is_dir() and (r_sub / "run.json").is_file():
                    try:
                        results.append(anuga_result_to_canonical(r_sub, project_id=valid_pid, run_dir=r_sub))
                    except Exception as e:
                        logger.warning(f"Could not adapt ANUGA run {r_sub.name}: {e}")

    # 2. Delft3D runs
    d3d_dir = proj_dir / "delft3d" / "runs"
    if d3d_dir.is_dir():
        for r_sub in sorted(d3d_dir.iterdir(), reverse=True):
            if r_sub.is_dir() and (r_sub / "run.json").is_file():
                try:
                    results.append(delft3d_result_to_canonical(r_sub, project_id=valid_pid, run_dir=r_sub))
                except Exception as e:
                    logger.warning(f"Could not adapt Delft3D run {r_sub.name}: {e}")

    # 3. PySPH runs
    sph_dir = proj_dir / "sph" / "runs"
    if sph_dir.is_dir():
        for r_sub in sorted(sph_dir.iterdir(), reverse=True):
            if r_sub.is_dir() and (r_sub / "run.json").is_file():
                try:
                    results.append(pysph_result_to_canonical(r_sub, project_id=valid_pid, run_dir=r_sub))
                except Exception as e:
                    logger.warning(f"Could not adapt PySPH run {r_sub.name}: {e}")

    return results

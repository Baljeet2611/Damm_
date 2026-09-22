import os
import json
import uuid
import shutil
import zipfile
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import numpy as np
import rasterio
from rasterio.crs import CRS
from fastapi import HTTPException

from app.schemas import (
    SimulationCapabilitiesResponse,
    ModelPackageResponse,
    SimulationRunResponse,
    SimulationLogResponse,
    ProjectDelft3DPackageResponse,
    Delft3DRunImportRequest,
)
from app.scenario_storage import (
    get_runtime_dir,
    load_scenario_dict,
    atomic_save_scenario,
    validate_uuid_str,
    compute_file_sha256,
    compute_scenario_snapshot_checksum,
)
from app.raster_service import resolve_dataset_file
from app.onboarding_service import (
    get_dam_projects_dir,
    validate_project_uuid,
)


def get_packages_dir() -> Path:
    """Get runtime packages storage directory."""
    return get_runtime_dir() / "packages"


def get_runs_dir() -> Path:
    """Get runtime simulation runs directory."""
    return get_runtime_dir() / "runs"


def detect_capabilities() -> SimulationCapabilitiesResponse:
    """
    Detect local availability of HydroMT-Delft3D FM Python tools and D-Flow FM solver binary.
    Never misrepresents capabilities or fakes simulation availability.
    """
    # 1. HydroMT builder detection
    hydromt_avail = False
    hydromt_ver = None
    hydromt_path = None

    try:
        import hydromt  # type: ignore
        hydromt_avail = True
        hydromt_ver = getattr(hydromt, "__version__", "unknown")
        hydromt_path = getattr(hydromt, "__file__", "installed_module")
    except ImportError:
        # Check CLI executable in PATH
        cli_path = shutil.which("hydromt")
        if cli_path:
            hydromt_avail = True
            hydromt_path = cli_path

    # 2. D-Flow FM / DIMR engine detection
    engine_configured = os.environ.get("DFLOWFM_EXECUTABLE") or os.environ.get("DIMR_EXECUTABLE")
    engine_path = None
    dflowfm_avail = False

    if engine_configured and Path(engine_configured).is_file():
        engine_path = engine_configured
        dflowfm_avail = True
    else:
        # Check standard binary names in PATH
        for cand in ["dflowfm.exe", "dflowfm", "dimr.exe", "dimr"]:
            found = shutil.which(cand)
            if found:
                engine_path = found
                dflowfm_avail = True
                break

    execution_enabled = os.environ.get("ENABLE_DFLOWFM_EXECUTION", "false").strip().lower() in ("true", "1", "yes")

    disclaimer = (
        "HydroMT-Delft3D FM builds and updates hydrodynamic model inputs; the separate D-Flow FM/DIMR "
        "numerical solver executes 2D Shallow Water Equation simulations. Existing sample rasters "
        "are unverified placeholders of unknown provenance and must never be attributed to Delft3D output."
    )

    guidance = (
        "To enable full HydroMT-Delft3D FM model building, create the clean conda environment using "
        "'conda env create -f environment_hydromt_delft3dfm.yml'. To enable simulation runs, install "
        "Deltares D-Flow FM / DIMR and configure 'DFLOWFM_EXECUTABLE' and 'ENABLE_DFLOWFM_EXECUTION=true'."
    )

    return SimulationCapabilitiesResponse(
        hydromt_available=hydromt_avail,
        hydromt_version=hydromt_ver,
        hydromt_path=hydromt_path,
        dflowfm_available=dflowfm_avail,
        execution_enabled=execution_enabled,
        engine_executable=engine_path,
        disclaimer=disclaimer,
        guidance=guidance,
    )


def generate_delft3d_ini_template(scenario: Dict[str, Any]) -> str:
    """Generate draft D-Flow FM model configuration INI/MDU template."""
    return f"""# ==============================================================================
# Draft Delft3D Flexible Mesh (D-Flow FM) Model Configuration Template
# Scenario: {scenario.get('name', 'Untitled')} (ID: {scenario.get('id')})
# Revision: {scenario.get('revision', 1)}
# Status: DRAFT UNVALIDATED MODEL PACKAGE
# ==============================================================================

[general]
fileVersion           = 1.03
fileType              = modelDef
program               = D-Flow FM
version               = 2.0.0

[numerics]
CFLmax                = 0.70
advecType             = 3
limtypsup             = 3
timeStepType          = 1
minTimeStep           = 0.01
maxTimeStep           = {scenario.get('timestep_sec', 1.0)}

[physics]
UnifFrictCoef         = {scenario.get('manning_roughness', 0.035)}
UnifFrictType         = 1
gravity               = 9.81
waterDensity          = 1000.0

[time]
RefDate               = 20260905
Tunit                 = H
TStart                = 0.0
TStop                 = {scenario.get('simulation_duration_hr', 24.0)}
DtUser                = 60.0
DtMax                 = {scenario.get('timestep_sec', 1.0)}

[geometry]
NetFile               = dflowfm_net.nc
BathymetryFile        = bathymetry.xyz
WaterLevIni           = {scenario.get('assumed_reservoir_level_m', 660.0)}
BedLevType            = 3

[external forcing]
ExtForceFile          = boundary_conditions.ext
# Upstream Boundary Description: {scenario.get('upstream_boundary_desc', 'N/A')}
# Downstream Boundary Description: {scenario.get('downstream_boundary_desc', 'N/A')}

[dam breach assumption]
BreachWidthMeters     = {scenario.get('breach_width_m', 100.0)}
BreachFormationHours  = {scenario.get('breach_formation_time_hr', 2.0)}
# Note: Requires dynamic breach module calibration with soil geotechnical parameters.
"""


def generate_hydromt_yaml_template(scenario: Dict[str, Any]) -> str:
    """Generate draft HydroMT-Delft3D FM builder configuration YAML."""
    return f"""# ==============================================================================
# Draft HydroMT-Delft3D FM Pipeline Configuration
# Scenario: {scenario.get('name')}
# ==============================================================================

setup_config:
  starttime: '2026-09-05 00:00:00'
  endtime: '2026-09-06 00:00:00'
  timestep: {scenario.get('timestep_sec', 1.0)}

setup_grid:
  res: {scenario.get('mesh_resolution_m', 50.0)}
  crs: '{scenario.get('crs', 'EPSG:4326')}'

setup_bathymetry:
  elevation_fn: '{scenario.get('dem_dataset_id', 'dem')}'
  add_to_grid: true

setup_manning_roughness:
  manning_val: {scenario.get('manning_roughness', 0.035)}
"""


def generate_data_catalog_template(scenario: Dict[str, Any], dem_path_str: str) -> str:
    """Generate HydroMT data catalog referencing elevation data."""
    return f"""# HydroMT Data Catalog for {scenario.get('name')}
meta:
  version: 1.0.0

{scenario.get('dem_dataset_id', 'dem')}:
  path: '{dem_path_str}'
  data_type: raster
  driver: raster
  crs: '{scenario.get('crs', 'EPSG:4326')}'
  kwargs:
    nodata: -9999.0
"""


def generate_readme_requirements(scenario: Dict[str, Any], checksum: str) -> str:
    """Generate honest scientific README detailing exact missing inputs and prerequisites."""
    return f"""================================================================================
DAM BREAK DECISION SUPPORT SYSTEM - DRAFT DELFT3D FM MODEL PACKAGE
================================================================================
Scenario Name:     {scenario.get('name')}
Scenario UUID:     {scenario.get('id')}
Revision:          {scenario.get('revision', 1)}
Snapshot Checksum: {checksum}
Generated At:      {datetime.now(timezone.utc).isoformat()}

SCIENTIFIC STATUS: DRAFT UNVALIDATED MODEL PACKAGE
--------------------------------------------------------------------------------
This package contains draft input configuration templates, metadata manifests,
and parameter specifications for setting up a hydrodynamic model using HydroMT
and D-Flow Flexible Mesh (Deltares Delft3D FM).

CRITICAL PREREQUISITES REQUIRED BEFORE OPERATIONAL SIMULATION:
1. TOPOGRAPHY & VERTICAL DATUM:
   - The referenced DEM ('{scenario.get('dem_dataset_id')}') is an unverified sample raster.
   - The true vertical datum (MSL vs local gauge zero) is unknown.
   - High-resolution river bathymetry and hydro-enforced culvert geometry must be
     surveyed and merged with LiDAR / CartoDEM topography.

2. BREACH HYDROGRAPH & GEOTECHNICAL FAILURE:
   - Assumed breach width: {scenario.get('breach_width_m')} m
   - Assumed formation time: {scenario.get('breach_formation_time_hr')} hours
   - Initial reservoir level: {scenario.get('assumed_reservoir_level_m')} m
   - Structural failure, piping, or overtopping breach dynamics must be verified
     using geotechnical soil erodibility tests and stage-storage curves.

3. BOUNDARY CONDITIONS & HYDROLOGY:
   - Upstream inflow: {scenario.get('upstream_boundary_desc')}
   - Downstream boundary: {scenario.get('downstream_boundary_desc')}
   - Measured or calibrated discharge hydrographs are mandatory.

4. BED FRICTION & ROUGHNESS:
   - Assumed Manning's n: {scenario.get('manning_roughness')} s/m^(1/3)
   - Must be calibrated against observed flood marks and differentiated by land-cover.

5. COMPUTATIONAL SOLVER:
   - Requires Deltares D-Flow FM / DIMR 2D Shallow Water Equations solver.
   - Existing sample rasters must NEVER be treated as Delft3D outputs.
================================================================================
"""


def build_model_package(scenario_id: str) -> Tuple[ModelPackageResponse, Path]:
    """
    Build a structured, downloadable Delft3D FM draft model package ZIP archive.
    Includes immutable manifest, configuration templates, and requirements documentation.
    """
    data = load_scenario_dict(scenario_id)
    packages_dir = get_packages_dir()
    revision = int(data.get("revision", 1))

    pkg_folder_name = f"{scenario_id}_r{revision}"
    pkg_dir = packages_dir / pkg_folder_name
    zip_path = packages_dir / f"{pkg_folder_name}.zip"

    # Create directory structure
    for sub in ["config", "data", "logs"]:
        (pkg_dir / sub).mkdir(parents=True, exist_ok=True)

    # Resolve referenced DEM dataset
    dem_id = data.get("dem_dataset_id", "dem")
    _, dem_file = resolve_dataset_file(dem_id)
    dem_file_str = str(dem_file) if dem_file else "data/raw/data_hidkal/hidkal_dem.tif"
    dem_hash = compute_file_sha256(dem_file) if (dem_file and dem_file.is_file()) else None

    # Compute scenario snapshot checksum
    snapshot_checksum = compute_scenario_snapshot_checksum(data)

    # 1. Manifest
    caps = detect_capabilities()
    manifest_data = {
        "manifest_version": "1.0.0",
        "scenario_id": scenario_id,
        "revision": revision,
        "package_type": "draft_unvalidated_delft3d_package",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_checksum": snapshot_checksum,
        "referenced_datasets": {
            dem_id: {
                "path": dem_file_str,
                "sha256": dem_hash,
                "status": "unverified_sample_provenance",
            }
        },
        "scenario_parameters": {
            "name": data.get("name"),
            "site": data.get("site"),
            "crs": data.get("crs"),
            "breach_width_m": data.get("breach_width_m"),
            "breach_formation_time_hr": data.get("breach_formation_time_hr"),
            "assumed_reservoir_level_m": data.get("assumed_reservoir_level_m"),
            "manning_roughness": data.get("manning_roughness"),
            "mesh_resolution_m": data.get("mesh_resolution_m"),
            "simulation_duration_hr": data.get("simulation_duration_hr"),
            "timestep_sec": data.get("timestep_sec"),
        },
        "capabilities_at_build": {
            "hydromt_available": caps.hydromt_available,
            "dflowfm_available": caps.dflowfm_available,
        },
        "disclaimer": (
            "Illustrative draft model package. Not a validated hydrodynamic simulation. "
            "Requires verified vertical datum, measured inflow hydrograph, and D-Flow FM engine."
        ),
    }

    with open(pkg_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)

    # 2. Config templates
    with open(pkg_dir / "config" / "delft3d_fm_model_config.ini", "w", encoding="utf-8") as f:
        f.write(generate_delft3d_ini_template(data))

    with open(pkg_dir / "config" / "hydromt_delft3dfm.yaml", "w", encoding="utf-8") as f:
        f.write(generate_hydromt_yaml_template(data))

    with open(pkg_dir / "config" / "data_catalog.yaml", "w", encoding="utf-8") as f:
        f.write(generate_data_catalog_template(data, dem_file_str))

    # 3. Data note
    with open(pkg_dir / "data" / "README_DATA.txt", "w", encoding="utf-8") as f:
        f.write(f"Referenced DEM: {dem_file_str}\nSHA-256: {dem_hash}\n")

    # 4. Requirements README
    with open(pkg_dir / "README_REQUIREMENTS.txt", "w", encoding="utf-8") as f:
        f.write(generate_readme_requirements(data, snapshot_checksum))

    # 5. Build ZIP archive
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in pkg_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(pkg_dir)
                zf.write(file_path, arcname=arcname)

    pkg_size = zip_path.stat().st_size
    manifest_checksum = compute_file_sha256(pkg_dir / "manifest.json") or "unknown"

    # Update scenario status to package_built
    data["status"] = "package_built"
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_save_scenario(data)

    notes = [
        "Draft model package built successfully with configuration templates and manifest.",
        "Requires unzipped model building via HydroMT-Delft3D FM and execution in D-Flow FM.",
    ]

    response = ModelPackageResponse(
        scenario_id=scenario_id,
        revision=revision,
        package_filename=zip_path.name,
        package_size_bytes=pkg_size,
        created_at=manifest_data["created_at"],
        manifest_checksum=manifest_checksum,
        status="package_built",
        download_url=f"/api/scenarios/{scenario_id}/download-package",
        notes=notes,
    )

    return response, zip_path


def get_package_zip_path(scenario_id: str) -> Path:
    """Find and return existing package ZIP path for a scenario."""
    data = load_scenario_dict(scenario_id)
    revision = int(data.get("revision", 1))
    zip_path = get_packages_dir() / f"{scenario_id}_r{revision}.zip"
    if not zip_path.is_file():
        # Automatically build package if not already on disk
        _, zip_path = build_model_package(scenario_id)
    return zip_path


def execute_simulation_run(scenario_id: str, custom_notes: str = "") -> SimulationRunResponse:
    """
    Execute D-Flow FM simulation strictly gated by server policy and binary availability.
    Rejects with 409 Conflict if engine is unavailable or execution is disabled.
    Uses safe subprocess argument arrays without shell execution.
    """
    caps = detect_capabilities()

    if not caps.execution_enabled or not caps.dflowfm_available or not caps.engine_executable:
        raise HTTPException(
            status_code=409,
            detail="engine_unavailable: D-Flow FM / DIMR hydrodynamic simulation engine is not available or execution is disabled by server policy. Never faking a simulation run.",
        )

    scenario_data = load_scenario_dict(scenario_id)
    run_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    runs_dir = get_runs_dir()
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Ensure model package is prepared
    _, zip_path = build_model_package(scenario_id)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(run_dir)

    stdout_file = run_dir / "stdout.log"
    stderr_file = run_dir / "stderr.log"
    mdu_path = run_dir / "config" / "delft3d_fm_model_config.ini"

    # Subprocess execution using strict argument list (shell=False)
    cmd = [caps.engine_executable, "--mdu", str(mdu_path)]
    timeout_sec = int(os.environ.get("DFLOWFM_TIMEOUT_SECONDS", "300"))

    start_time = datetime.now(timezone.utc)
    status = "running"
    exit_code = None

    try:
        with open(stdout_file, "w", encoding="utf-8") as out_f, open(stderr_file, "w", encoding="utf-8") as err_f:
            proc = subprocess.run(
                cmd,
                cwd=str(run_dir),
                stdout=out_f,
                stderr=err_f,
                timeout=timeout_sec,
                shell=False,
            )
            exit_code = proc.returncode
            status = "completed" if exit_code == 0 else "failed"
    except subprocess.TimeoutExpired:
        status = "failed"
        exit_code = -1
        with open(stderr_file, "a", encoding="utf-8") as err_f:
            err_f.write(f"\n[ERROR] Simulation run exceeded timeout of {timeout_sec} seconds.\n")
    except Exception as e:
        status = "failed"
        exit_code = -2
        with open(stderr_file, "a", encoding="utf-8") as err_f:
            err_f.write(f"\n[ERROR] Failed to execute simulation subprocess: {str(e)}\n")

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()

    # Save run record
    run_record = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "scenario_name": scenario_data.get("name", "Untitled"),
        "revision": int(scenario_data.get("revision", 1)),
        "status": status,
        "started_at": start_time.isoformat(),
        "completed_at": end_time.isoformat(),
        "duration_seconds": round(duration, 2),
        "exit_code": exit_code,
        "custom_notes": custom_notes,
    }

    with open(run_dir / "run_metadata.json", "w", encoding="utf-8") as f:
        json.dump(run_record, f, indent=2)

    return SimulationRunResponse(
        run_id=run_id,
        scenario_id=scenario_id,
        scenario_name=scenario_data.get("name", "Untitled"),
        revision=int(scenario_data.get("revision", 1)),
        status=status,
        started_at=start_time.isoformat(),
        completed_at=end_time.isoformat(),
        duration_seconds=round(duration, 2),
        exit_code=exit_code,
        log_url=f"/api/runs/{run_id}/logs",
        notes=[
            f"Execution finished with status '{status}' (exit code: {exit_code}).",
            "Logs are available in run archive.",
        ],
    )


def list_simulation_runs() -> List[SimulationRunResponse]:
    """List all simulation runs from runtime storage."""
    runs_dir = get_runs_dir()
    results: List[SimulationRunResponse] = []

    for meta_file in runs_dir.glob("*/run_metadata.json"):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            results.append(
                SimulationRunResponse(
                    run_id=data["run_id"],
                    scenario_id=data["scenario_id"],
                    scenario_name=data.get("scenario_name", "Untitled"),
                    revision=data.get("revision", 1),
                    status=data.get("status", "completed"),
                    started_at=data["started_at"],
                    completed_at=data.get("completed_at"),
                    duration_seconds=data.get("duration_seconds"),
                    exit_code=data.get("exit_code"),
                    log_url=f"/api/runs/{data['run_id']}/logs",
                    notes=["Historical simulation run record."],
                )
            )
        except Exception:
            continue

    results.sort(key=lambda r: r.started_at, reverse=True)
    return results


def get_simulation_run(run_id: str) -> SimulationRunResponse:
    """Retrieve details for a single simulation run."""
    valid_id = validate_uuid_str(run_id)
    meta_path = get_runs_dir() / valid_id / "run_metadata.json"
    if not meta_path.is_file():
        raise HTTPException(status_code=404, detail=f"Simulation run '{valid_id}' not found.")

    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return SimulationRunResponse(
        run_id=data["run_id"],
        scenario_id=data["scenario_id"],
        scenario_name=data.get("scenario_name", "Untitled"),
        revision=data.get("revision", 1),
        status=data.get("status", "completed"),
        started_at=data["started_at"],
        completed_at=data.get("completed_at"),
        duration_seconds=data.get("duration_seconds"),
        exit_code=data.get("exit_code"),
        log_url=f"/api/runs/{valid_id}/logs",
        notes=["Simulation run record."],
    )


def get_simulation_logs(run_id: str) -> SimulationLogResponse:
    """Retrieve captured stdout and stderr logs for a run."""
    valid_id = validate_uuid_str(run_id)
    run_dir = get_runs_dir() / valid_id
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Simulation run '{valid_id}' not found.")

    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    meta_path = run_dir / "run_metadata.json"

    stdout_txt = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.is_file() else ""
    stderr_txt = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.is_file() else ""

    scenario_id = ""
    status = "unknown"
    if meta_path.is_file():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                scenario_id = meta.get("scenario_id", "")
                status = meta.get("status", "unknown")
        except Exception:
            pass

    return SimulationLogResponse(
        run_id=valid_id,
        scenario_id=scenario_id,
        status=status,
        stdout=stdout_txt,
        stderr=stderr_txt,
    )


# ==============================================================================
# Phase 25: Project-Scoped Delft3D / D-Flow FM Workflow & Run Importer
# ==============================================================================

def get_dam_project_delft3d_dir(project_id: str) -> Path:
    """Return root directory for Delft3D packages and runs under a dam project."""
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid / "delft3d"
    p_dir.mkdir(parents=True, exist_ok=True)
    return p_dir


def sanitize_filename(filename: str) -> str:
    """Sanitize uploaded filename against directory traversal and dangerous characters."""
    clean = Path(filename).name.strip()
    clean = clean.replace("..", "").replace("/", "").replace("\\", "")
    if not clean:
        clean = f"imported_file_{uuid.uuid4().hex[:6]}"
    return clean


def build_dam_project_delft3d_package(
    project_id: str,
    sph_run_id: Optional[str] = None,
) -> Tuple[ProjectDelft3DPackageResponse, Path]:
    """
    Build a project-specific Delft3D / D-Flow FM model package archive for the dam project.
    Generates D-Flow FM .mdu configuration, boundary conditions, bathymetry definitions, and manifest.
    Supports optional direct PySPH breach hydrograph coupling (Phase A1).
    """
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid
    if not p_dir.is_dir() or not (p_dir / "project.json").is_file():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found")

    project_data: Dict[str, Any] = json.loads((p_dir / "project.json").read_text(encoding="utf-8"))
    d3d_dir = get_dam_project_delft3d_dir(valid_pid)
    packages_dir = d3d_dir / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)

    pkg_name = f"{valid_pid}_delft3d_package" if not sph_run_id else f"{valid_pid}_delft3d_sph_coupled_package"
    pkg_work_dir = packages_dir / pkg_name
    zip_path = packages_dir / f"{pkg_name}.zip"

    for sub in ["config", "boundaries", "docs"]:
        (pkg_work_dir / sub).mkdir(parents=True, exist_ok=True)

    caps = detect_capabilities()
    dam_name = project_data.get("name", "Project Dam")
    dam_height = float(project_data.get("dam_height_m") or 60.0)
    crest_len = float(project_data.get("crest_length_m") or 200.0)
    norm_res = float(project_data.get("normal_reservoir_level_m") or 650.0)
    tailwater = float(project_data.get("tailwater_level_m") or 600.0)

    # 1. D-Flow FM MDU Configuration File
    mdu_content = f"""# ==============================================================================
# Delft3D Flexible Mesh (D-Flow FM) Model Definition
# Project: {dam_name} (ID: {valid_pid})
# Generated: {datetime.now(timezone.utc).isoformat()}
# ==============================================================================

[general]
fileVersion           = 1.03
fileType              = modelDef
program               = D-Flow FM
version               = 2.0.0

[numerics]
CFLmax                = 0.70
advecType             = 3
limtypsup             = 3
timeStepType          = 1
minTimeStep           = 0.01
maxTimeStep           = 1.0

[physics]
UnifFrictCoef         = 0.035
UnifFrictType         = 1
gravity               = 9.81
waterDensity          = 1000.0

[time]
RefDate               = 20260901
Tunit                 = S
TStart                = 0.0
TStop                 = 86400.0
DtUser                = 60.0
DtMax                 = 1.0

[geometry]
NetFile               = dflowfm_net.nc
BathymetryFile        = bathymetry.xyz
WaterLevIni           = {norm_res}
BedLevType            = 3

[external forcing]
ExtForceFile          = boundary_conditions.ext

[dam breach assumption]
DamHeightMeters       = {dam_height}
CrestLengthMeters     = {crest_len}
InitialWaterLevelM    = {norm_res}
TailwaterLevelM       = {tailwater}
"""
    (pkg_work_dir / "config" / "dflowfm.mdu").write_text(mdu_content, encoding="utf-8")

    # 2. Boundary Conditions & Hydrograph Coupling (Phase A1)
    coupled_info: Optional[Dict[str, Any]] = None
    if sph_run_id:
        from app.sph_service import extract_sph_breach_hydrograph, export_sph_breach_hydrograph_bc
        sph_hydro = extract_sph_breach_hydrograph(valid_pid, sph_run_id)
        export_sph_breach_hydrograph_bc(sph_hydro, pkg_work_dir / "boundaries" / "breach_inflow.bc")

        ext_content = f"""# External forcing boundary conditions for {dam_name} (PySPH Coupled Outflow)
# SPH Run ID: {sph_run_id} | Q_peak: {sph_hydro.q_peak_cms:.2f} m3/s at t={sph_hydro.time_to_peak_seconds:.2f} s
QUANTITY=dischargebnd
FILENAME=breach_inflow.bc
FILETYPE=9
METHOD=1
OPERAND=O

QUANTITY=waterlevelbnd
FILENAME=upstream_stage.tim
FILETYPE=1
METHOD=1
OPERAND=O
"""
        coupled_info = {
            "is_coupled": True,
            "source_engine": "pysph",
            "target_engine": "delft3d_fm",
            "source_sph_run_id": sph_run_id,
            "derived_from_sph": True,
            "solver_status": "package_generated_unexecuted",
            "sph_q_peak_cms": sph_hydro.q_peak_cms,
            "sph_time_to_peak_s": sph_hydro.time_to_peak_seconds,
            "sph_total_released_volume_m3": sph_hydro.total_released_volume_m3,
            "sph_reservoir_release_fraction": sph_hydro.reservoir_release_fraction,
            "sph_mass_balance_check": sph_hydro.mass_balance_check,
        }
    else:
        ext_content = f"""# External forcing boundary condition template for {dam_name}
QUANTITY=waterlevelbnd
FILENAME=upstream_stage.tim
FILETYPE=1
METHOD=1
OPERAND=O

QUANTITY=dischargebnd
FILENAME=breach_hydrograph.tim
FILETYPE=1
METHOD=1
OPERAND=O
"""
    (pkg_work_dir / "boundaries" / "boundary_conditions.ext").write_text(ext_content, encoding="utf-8")

    # 3. HydroMT Builder Template
    hydromt_yaml = f"""# HydroMT-Delft3D FM Configuration
setup_config:
  project_id: "{valid_pid}"
  model: "dflowfm"
  crs: "EPSG:32643"
  grid_resolution: 25.0
  bathymetry: "dem.tif"
  friction_manning: 0.035
"""
    (pkg_work_dir / "config" / "hydromt_delft3dfm.yaml").write_text(hydromt_yaml, encoding="utf-8")

    # 4. Scientific README
    readme_content = f"""================================================================================
PROJECT-SPECIFIC DELFT3D / D-FLOW FM MODEL PACKAGE
================================================================================
Project:               {dam_name}
Project ID:            {valid_pid}
Generated:             {datetime.now(timezone.utc).isoformat()}
D-Flow FM Available:   {caps.dflowfm_available}
Coupled with PySPH:    {bool(coupled_info)}

SCIENTIFIC REQUIREMENTS & OUTPUT CONTRACT:
1. EXECUTING D-FLOW FM:
   To run this simulation, install Deltares Delft3D Flexible Mesh (D-Flow FM) / DIMR
   and execute:
     dflowfm --autostartstop config/dflowfm.mdu

2. IMPORTING DELFT3D RESULTS:
   Upon simulation completion, postprocessed GeoTIFF outputs:
     - maximum_depth.tif    (m, NoData: -9999.0)
     - maximum_velocity.tif (m/s, NoData: -9999.0)
     - arrival_time.tif     (seconds/hours, NoData: -9999.0)
   or NetCDF map output files (DFM_OUTPUT_dflowfm_net.nc) can be imported into this
   system using:
     POST /api/dam-projects/{valid_pid}/delft3d/import-run
================================================================================
"""
    (pkg_work_dir / "docs" / "README_DELFT3D_REQUIREMENTS.txt").write_text(readme_content, encoding="utf-8")

    # 5. Manifest
    manifest_data = {
        "manifest_version": "1.0.0",
        "project_id": valid_pid,
        "package_type": "project_delft3d_package",
        "solver_framework": "Delft3D Flexible Mesh (D-Flow FM)",
        "solver_execution_status": "package_generated_unexecuted",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "capabilities_at_build": {
            "hydromt_available": caps.hydromt_available,
            "dflowfm_available": caps.dflowfm_available,
            "execution_enabled": caps.execution_enabled,
        },
        "coupling": coupled_info,
        "output_contract": {
            "required_rasters": ["maximum_depth.tif", "maximum_velocity.tif", "arrival_time.tif"],
            "target_crs": "EPSG:32643",
            "nodata_value": -9999.0,
        }
    }
    (pkg_work_dir / "manifest.json").write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    # 6. Build ZIP
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in pkg_work_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(pkg_work_dir)
                zf.write(file_path, arcname=arcname)

    pkg_size = zip_path.stat().st_size
    manifest_checksum = compute_file_sha256(pkg_work_dir / "manifest.json") or "unknown"

    notes = [
        f"Delft3D model package for project '{dam_name}' built successfully.",
        "Contains D-Flow FM MDU definition and boundary condition templates.",
    ]
    if coupled_info:
        notes.append(
            f"Coupled with PySPH run '{sph_run_id}': regional boundary condition forced by SPH breach hydrograph (Q_peak: {coupled_info['sph_q_peak_cms']} m3/s, Volume: {coupled_info['sph_total_released_volume_m3']} m3)."
        )

    response = ProjectDelft3DPackageResponse(
        project_id=valid_pid,
        package_filename=zip_path.name,
        package_size_bytes=pkg_size,
        created_at=manifest_data["created_at"],
        manifest_checksum=manifest_checksum,
        download_url=f"/api/dam-projects/{valid_pid}/delft3d/download-package",
        dflowfm_available=caps.dflowfm_available,
        execution_enabled=caps.execution_enabled,
        notes=notes,
    )
    return response, zip_path


def import_dam_project_delft3d_run(
    project_id: str,
    uploaded_files: List[Tuple[str, bytes]],
    req: Delft3DRunImportRequest,
) -> Dict[str, Any]:
    """
    Securely import an externally computed Delft3D / D-Flow FM simulation run into dam project storage.
    Accepts standardized GeoTIFFs (maximum_depth.tif, maximum_velocity.tif, arrival_time.tif) or NetCDF map output.
    Validates files, enforces size limits, blocks path traversal, and produces standardized products.
    """
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid
    if not p_dir.is_dir() or not (p_dir / "project.json").is_file():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found")

    if not uploaded_files:
        raise HTTPException(status_code=400, detail="No files provided for Delft3D run import.")

    total_bytes = sum(len(b) for _, b in uploaded_files)
    if total_bytes > 500 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Total uploaded size exceeds 500 MB limit.")

    run_id = f"d3d-import-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    d3d_dir = get_dam_project_delft3d_dir(valid_pid)
    run_dir = d3d_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    saved_files: Dict[str, Path] = {}
    file_hashes: Dict[str, str] = {}
    allowed_exts = {".tif", ".tiff", ".nc", ".nc4", ".json"}

    for filename, content in uploaded_files:
        clean_name = sanitize_filename(filename)
        ext = Path(clean_name).suffix.lower()
        if ext not in allowed_exts:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{ext}' for file '{clean_name}'. Allowed: {list(allowed_exts)}"
            )

        dst_path = run_dir / clean_name
        dst_path.write_bytes(content)
        saved_files[clean_name] = dst_path
        file_hashes[clean_name] = compute_file_sha256(dst_path) or ""

    # Identify GeoTIFFs and NetCDF files
    geotiffs = {k: v for k, v in saved_files.items() if v.suffix.lower() in [".tif", ".tiff"]}
    nc_files = {k: v for k, v in saved_files.items() if v.suffix.lower() in [".nc", ".nc4"]}
    depth_tif = None
    vel_tif = None
    arr_tif = None
    import_mode = "geotiff"
    ugrid_summary = None

    for name, path in geotiffs.items():
        name_lower = name.lower()
        if "depth" in name_lower or name_lower in ["maximum_depth.tif", "depth.tif", "max_depth.tif"]:
            depth_tif = path
            if path.name != "maximum_depth.tif":
                std_path = run_dir / "maximum_depth.tif"
                shutil.copy2(path, std_path)
                depth_tif = std_path
        elif "vel" in name_lower or name_lower in ["maximum_velocity.tif", "velocity.tif", "max_velocity.tif"]:
            vel_tif = path
            if path.name != "maximum_velocity.tif":
                std_path = run_dir / "maximum_velocity.tif"
                shutil.copy2(path, std_path)
                vel_tif = std_path
        elif "arr" in name_lower or name_lower in ["arrival_time.tif", "arrival.tif"]:
            arr_tif = path
            if path.name != "arrival_time.tif":
                std_path = run_dir / "arrival_time.tif"
                shutil.copy2(path, std_path)
                arr_tif = std_path

    # If no depth GeoTIFF was provided, but a NetCDF map output is present, parse UGRID mesh
    if not depth_tif and nc_files:
        from app.delft3d_ugrid_service import parse_delft3d_ugrid_netcdf, rasterize_delft3d_ugrid_to_geotiff
        primary_nc = list(nc_files.values())[0]
        try:
            parsed = parse_delft3d_ugrid_netcdf(primary_nc)
            ugrid_tifs = rasterize_delft3d_ugrid_to_geotiff(parsed, run_dir)
            if "maximum_depth" in ugrid_tifs:
                depth_tif = ugrid_tifs["maximum_depth"]
            if "maximum_velocity" in ugrid_tifs:
                vel_tif = ugrid_tifs["maximum_velocity"]
            import_mode = "ugrid_netcdf"
            ugrid_summary = parsed.get("summary")
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Failed to parse Delft3D UGRID NetCDF file '{primary_nc.name}': {str(e)}"
            )

    if not depth_tif:
        raise HTTPException(
            status_code=422,
            detail="Uploaded Delft3D run must contain at least maximum_depth.tif (or a recognized depth GeoTIFF / genuine Delft3D NetCDF map file)."
        )

    # Validate output GeoTIFF with rasterio
    with rasterio.open(depth_tif) as src:
        native_crs_str = str(src.crs or "EPSG:4326")
        res_x = abs(src.transform.a)
        bounds_tup = (float(src.bounds.left), float(src.bounds.bottom), float(src.bounds.right), float(src.bounds.top))
        nodata_val = float(src.nodata if src.nodata is not None else -9999.0)

    layer_hashes: Dict[str, str] = {
        "maximum_depth": compute_file_sha256(depth_tif) or "",
    }
    if vel_tif and vel_tif.is_file():
        layer_hashes["maximum_velocity"] = compute_file_sha256(vel_tif) or ""
    if arr_tif and arr_tif.is_file():
        layer_hashes["arrival_time"] = compute_file_sha256(arr_tif) or ""

    run_record = {
        "run_id": run_id,
        "project_id": valid_pid,
        "engine": "delft3d_fm",
        "engine_version": "Delft3D Flexible Mesh (Imported)",
        "run_label": req.run_label or "Imported Delft3D Run",
        "status": "completed",
        "solver_execution_status": "imported",
        "scientific_status": req.scientific_status or ("genuine_ugrid_netcdf_ingested" if import_mode == "ugrid_netcdf" else "imported_external_run"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": req.notes or "",
        "native_crs": native_crs_str,
        "native_resolution_m": round(res_x, 4),
        "bounds": bounds_tup,
        "nodata_value": nodata_val,
        "summary": ugrid_summary,
        "layers": {
            "has_maximum_depth": True,
            "has_maximum_velocity": vel_tif is not None and vel_tif.is_file(),
            "has_arrival_time": arr_tif is not None and arr_tif.is_file(),
        },
        "layer_hashes": layer_hashes,
        "source_files": list(saved_files.keys()),
        "source_file_hashes": file_hashes,
        "provenance": {
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "import_mode": import_mode,
            "source_engine": "delft3d_fm",
        }
    }

    (run_dir / "run.json").write_text(json.dumps(run_record, indent=2), encoding="utf-8")
    return run_record


def list_dam_project_delft3d_runs(project_id: str) -> List[Dict[str, Any]]:
    """List all completed/imported Delft3D runs for a dam project."""
    valid_pid = validate_project_uuid(project_id)
    d3d_dir = get_dam_project_delft3d_dir(valid_pid)
    runs_dir = d3d_dir / "runs"
    if not runs_dir.is_dir():
        return []

    results: List[Dict[str, Any]] = []
    for r_sub in sorted(runs_dir.iterdir(), reverse=True):
        if not r_sub.is_dir():
            continue
        r_json = r_sub / "run.json"
        if r_json.is_file():
            try:
                data = json.loads(r_json.read_text(encoding="utf-8"))
                results.append(data)
            except Exception:
                pass
    return results


def get_dam_project_delft3d_run_detail(project_id: str, run_id: str) -> Dict[str, Any]:
    """Retrieve full details of a Delft3D run under a dam project."""
    valid_pid = validate_project_uuid(project_id)
    clean_rid = sanitize_filename(run_id)
    d3d_dir = get_dam_project_delft3d_dir(valid_pid)
    r_json = d3d_dir / "runs" / clean_rid / "run.json"
    if not r_json.is_file():
        raise HTTPException(status_code=404, detail=f"Delft3D run '{clean_rid}' not found in project '{valid_pid}'.")
    return json.loads(r_json.read_text(encoding="utf-8"))

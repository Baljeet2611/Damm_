import os
import json
import uuid
import shutil
import zipfile
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Tuple
from fastapi import HTTPException

from app.schemas import (
    SimulationCapabilitiesResponse,
    ModelPackageResponse,
    SimulationRunResponse,
    SimulationLogResponse,
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

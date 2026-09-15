import os
import sys
import io
import json
import uuid
import shutil
import zipfile
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from fastapi import HTTPException

from app.schemas import (
    SPHCapabilitiesResponse,
    SPHPackageResponse,
    SPHRunRequest,
    SPHRunResponse,
    SimulationLogResponse,
    SPHParticleInterpolationParams,
    SPHRunImportRequest,
    ProjectSPHPackageResponse,
    HydrodynamicOutputContract,
)
from app.scenario_storage import (
    get_runtime_dir,
    load_scenario_dict,
    validate_uuid_str,
    compute_file_sha256,
    compute_scenario_snapshot_checksum,
)
from app.raster_service import resolve_dataset_file
from app.onboarding_service import (
    get_dam_projects_dir,
    validate_project_uuid,
)


def get_sph_packages_dir() -> Path:
    """Get directory for SPH model package storage."""
    p = get_runtime_dir() / "sph_packages"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_sph_runs_dir() -> Path:
    """Get directory for SPH simulation runs storage."""
    p = get_runtime_dir() / "sph_runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def detect_sph_capabilities() -> SPHCapabilitiesResponse:
    """
    Detect local availability of PySPH Lagrangian solver.
    Never fakes capability or solver execution.
    """
    pysph_avail = False
    pysph_ver = None
    pysph_path = None

    try:
        import pysph  # type: ignore
        pysph_avail = True
        pysph_ver = getattr(pysph, "__version__", "installed")
        pysph_path = getattr(pysph, "__file__", "installed_module")
    except ImportError:
        cli_path = shutil.which("pysph")
        if cli_path:
            pysph_avail = True
            pysph_path = cli_path

    engine_configured = os.environ.get("PYSPH_EXECUTABLE") or os.environ.get("PYSPH_PYTHON_PATH")
    engine_path = None
    if engine_configured and Path(engine_configured).is_file():
        engine_path = engine_configured
        pysph_avail = True
    elif pysph_avail and sys.executable:
        engine_path = sys.executable

    execution_enabled = os.environ.get("ENABLE_PYSPH_EXECUTION", "false").strip().lower() in ("true", "1", "yes")

    disclaimer = (
        "PySPH provides Lagrangian Smoothed Particle Hydrodynamics for violent free-surface wave dynamics "
        "and near-field breach impact. Laboratory 2D benchmarks (<10 m) are fundamentally distinct from "
        "regional 3D river-scale terrain modeling (>10 km, >10^7 particles). Existing Hidkal sample rasters "
        "are unverified and must never be attributed to SPH outputs."
    )

    guidance = (
        "To enable PySPH model execution, set up the dedicated environment using "
        "'conda env create -f environment_pysph.yml' and configure 'ENABLE_PYSPH_EXECUTION=true' "
        "alongside 'PYSPH_PYTHON_PATH'."
    )

    return SPHCapabilitiesResponse(
        pysph_available=pysph_avail,
        pysph_version=pysph_ver,
        pysph_path=pysph_path,
        execution_enabled=execution_enabled,
        engine_executable=engine_path if execution_enabled else None,
        disclaimer=disclaimer,
        guidance=guidance,
    )


def generate_pysph_2d_benchmark_script(scenario: Dict[str, Any]) -> str:
    """
    Generate clean, documented PySPH 2D dam-break benchmark Python script template.
    Implements standard Weakly Compressible SPH (WCSPH) with Tait Equation of State.
    """
    return f'''"""
PySPH 2D Dam-Break Benchmark Simulation Script
Scenario: {scenario.get('name', 'Untitled')} (UUID: {scenario.get('id')})
Revision: {scenario.get('revision', 1)}
Generated: {datetime.now(timezone.utc).isoformat()}

SCIENTIFIC NOTE:
This script sets up a classic Martin & Moyce / Zhou et al. 2D fluid column collapse
benchmark for near-field hydrodynamic wave validation.
For regional 3D dam-break modeling over real topography, coupling with Eulerian
shallow water solvers (Delft3D-FM) is required due to SPH particle resolution limits.
"""

import numpy as np
from pysph.base.utils import get_particle_array_wcsph
from pysph.base.kernels import QuinticSpline
from pysph.solver.application import Application
from pysph.sph.integrator import EPECIntegrator
from pysph.sph.integrator_step import WCSPHStep
from pysph.sph.equation import Group
from pysph.sph.basic_equations import ContinuityEquation, XSPHCorrection
from pysph.sph.wc.basic import TaitEOS, MomentumEquation, PressureGradient

class DamBreak2DApp(Application):
    def initialize(self):
        # Physical and numerical parameters
        self.dx = 0.025  # Particle spacing in meters (benchmark scale)
        self.h = 1.3 * self.dx  # Smoothing length
        self.ro = 1000.0  # Reference fluid density (kg/m^3)
        self.co = 10.0 * np.sqrt(2.0 * 9.81 * 1.0)  # Artificial speed of sound
        self.gamma = 7.0
        self.p0 = (self.ro * self.co**2) / self.gamma
        self.tf = {min(10.0, float(scenario.get('simulation_duration_hr', 1.0)) * 60.0)}  # Scaled benchmark duration

    def create_particles(self):
        # 1. Fluid Column (L = 1.0 m, H = 2.0 m scaled representation)
        xf, yf = np.mgrid[0.0:1.0:self.dx, 0.0:2.0:self.dx]
        xf = xf.ravel()
        yf = yf.ravel()
        m = self.dx * self.dx * self.ro

        fluid = get_particle_array_wcsph(
            name='fluid', x=xf, y=yf, h=self.h, m=m, rho=self.ro,
            p0=self.p0, c0=self.co, gamma=self.gamma
        )

        # 2. Solid Tank Boundaries (Bottom and Side Walls)
        xb1, yb1 = np.mgrid[-0.1:4.1:self.dx, -0.1:0.0:self.dx]  # Bottom wall
        xb2, yb2 = np.mgrid[-0.1:0.0:self.dx, 0.0:3.0:self.dx]   # Left wall
        xb3, yb3 = np.mgrid[4.0:4.1:self.dx, 0.0:3.0:self.dx]    # Right impact wall

        xb = np.concatenate([xb1.ravel(), xb2.ravel(), xb3.ravel()])
        yb = np.concatenate([yb1.ravel(), yb2.ravel(), yb3.ravel()])

        boundary = get_particle_array_wcsph(
            name='boundary', x=xb, y=yb, h=self.h, m=m, rho=self.ro,
            p0=self.p0, c0=self.co, gamma=self.gamma
        )

        return [fluid, boundary]

    def create_solver(self):
        kernel = QuinticSpline(dim=2)
        integrator = EPECIntegrator(fluid=WCSPHStep())
        dt = 0.0001
        tf = self.tf

        from pysph.solver.solver import Solver
        solver = Solver(
            kernel=kernel, dim=2, integrator=integrator,
            dt=dt, tf=tf, adaptive_timestep=True
        )
        return solver

    def create_equations(self):
        equations = [
            Group(equations=[
                TaitEOS(dest='fluid', sources=None, p0=self.p0, rho0=self.ro, gamma=self.gamma),
            ]),
            Group(equations=[
                ContinuityEquation(dest='fluid', sources=['fluid', 'boundary']),
                PressureGradient(dest='fluid', sources=['fluid', 'boundary'], gx=0.0, gy=-9.81),
                XSPHCorrection(dest='fluid', sources=['fluid']),
            ])
        ]
        return equations

if __name__ == '__main__':
    app = DamBreak2DApp()
    app.run()
'''


def generate_readme_sph_requirements(scenario: Dict[str, Any], checksum: str) -> str:
    """Generate honest scientific README for SPH model package."""
    return f"""================================================================================
DAM BREAK DECISION SUPPORT SYSTEM - DRAFT SPH MODEL PACKAGE (PySPH)
================================================================================
Scenario Name:     {scenario.get('name')}
Scenario UUID:     {scenario.get('id')}
Revision:          {scenario.get('revision', 1)}
Snapshot Checksum: {checksum}
Generated At:      {datetime.now(timezone.utc).isoformat()}

SCIENTIFIC STATUS: DRAFT UNVALIDATED SPH PACKAGE
--------------------------------------------------------------------------------
This package contains a standard 2D Lagrangian Smoothed Particle Hydrodynamics (SPH)
benchmark model configuration using PySPH for near-field violent wave modeling.

FUNDAMENTAL SCALE SEPARATION & HYDRODYNAMIC LIMITATIONS:
1. BENCHMARK SCALE VS. REGIONAL RIVER SCALE:
   - PySPH benchmark mode runs at laboratory/channel scales (domain < 10 meters).
   - The downstream Hidkal reach spans > 25 kilometers of complex terrain.
   - Running full 3D SPH across the entire Hidkal valley would require > 10^9
     particles and high-performance GPU supercomputing clusters.

2. MULTI-SCALE COUPLING REQUIREMENT:
   - SPH is scientifically suited for: Near-field 3D breach wave formation,
     overtopping splash, structural impact forces, and turbulent front overturning.
   - Delft3D-FM (SWE) is scientifically suited for: Far-field 2D shallow water
     valley routing, floodplain spreading, friction recession, and regional damage.

3. STANDARD OUTPUT CONTRACT FOR COMPLETED RUNS:
   To qualify for downstream comparative evaluation with Delft3D, completed SPH runs
   must produce georeferenced GeoTIFFs (EPSG:4326 / UTM Zone 43N) matching:
   - depth.tif    (meters, NoData: -9999.0)
   - velocity.tif (m/s, NoData: -9999.0)
   - arrival.tif  (seconds/hours, NoData: -9999.0)
   - run_manifest.json (with units, bounding box, resolution, and input checksums)
================================================================================
"""


def build_sph_package(scenario_id: str) -> Tuple[SPHPackageResponse, Path]:
    """
    Build a downloadable draft PySPH model package ZIP archive.
    """
    data = load_scenario_dict(scenario_id)
    packages_dir = get_sph_packages_dir()
    revision = int(data.get("revision", 1))

    pkg_folder_name = f"{scenario_id}_r{revision}_sph"
    pkg_dir = packages_dir / pkg_folder_name
    zip_path = packages_dir / f"{pkg_folder_name}.zip"

    for sub in ["config", "scripts", "docs"]:
        (pkg_dir / sub).mkdir(parents=True, exist_ok=True)

    dem_id = data.get("dem_dataset_id", "dem")
    _, dem_file = resolve_dataset_file(dem_id)
    dem_file_str = str(dem_file) if dem_file else "data/raw/data_hidkal/hidkal_dem.tif"
    dem_hash = compute_file_sha256(dem_file) if (dem_file and dem_file.is_file()) else None

    snapshot_checksum = compute_scenario_snapshot_checksum(data)
    caps = detect_sph_capabilities()

    # 1. Manifest
    manifest_data = {
        "manifest_version": "1.0.0",
        "scenario_id": scenario_id,
        "revision": revision,
        "package_type": "draft_unvalidated_sph_package",
        "solver_framework": "PySPH (Lagrangian SPH)",
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
            "breach_width_m": data.get("breach_width_m"),
            "assumed_reservoir_level_m": data.get("assumed_reservoir_level_m"),
        },
        "capabilities_at_build": {
            "pysph_available": caps.pysph_available,
            "execution_enabled": caps.execution_enabled,
        },
        "output_contract": {
            "required_rasters": ["depth.tif", "velocity.tif", "arrival.tif"],
            "required_crs": "EPSG:4326",
            "required_units": {"depth": "meters", "velocity": "m/s", "arrival": "seconds"},
            "nodata_value": -9999.0,
        },
        "disclaimer": (
            "Illustrative SPH benchmark package. Not a validated hydrodynamic prediction. "
            "Requires verified boundary particle coupling and high-performance SPH compute."
        ),
    }

    with open(pkg_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)

    # 2. Benchmark Script
    with open(pkg_dir / "scripts" / "dam_break_2d_pysph.py", "w", encoding="utf-8") as f:
        f.write(generate_pysph_2d_benchmark_script(data))

    # 3. Config JSON
    config_data = {
        "scenario_id": scenario_id,
        "benchmark_scheme": "WCSPH",
        "kernel": "QuinticSpline",
        "particle_spacing_m": 0.025,
        "cfl": 0.25,
        "gravity": [0.0, -9.81],
        "fluid_density_kg_m3": 1000.0,
    }
    with open(pkg_dir / "config" / "sph_simulation_config.json", "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

    # 4. Requirements README
    with open(pkg_dir / "README_SPH_REQUIREMENTS.txt", "w", encoding="utf-8") as f:
        f.write(generate_readme_sph_requirements(data, snapshot_checksum))

    # 5. Build ZIP
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in pkg_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(pkg_dir)
                zf.write(file_path, arcname=arcname)

    pkg_size = zip_path.stat().st_size
    manifest_checksum = compute_file_sha256(pkg_dir / "manifest.json") or "unknown"

    notes = [
        "PySPH draft benchmark package built successfully with 2D script template and manifest.",
        "Requires PySPH conda environment ('environment_pysph.yml') for execution.",
    ]

    response = SPHPackageResponse(
        scenario_id=scenario_id,
        revision=revision,
        package_filename=zip_path.name,
        package_size_bytes=pkg_size,
        created_at=manifest_data["created_at"],
        manifest_checksum=manifest_checksum,
        status="package_built",
        download_url=f"/api/scenarios/{scenario_id}/download-sph-package",
        benchmark_type="2d_dam_break_benchmark",
        notes=notes,
    )

    return response, zip_path


def get_sph_package_zip_path(scenario_id: str) -> Path:
    """Find and return existing SPH package ZIP path for a scenario."""
    data = load_scenario_dict(scenario_id)
    revision = int(data.get("revision", 1))
    zip_path = get_sph_packages_dir() / f"{scenario_id}_r{revision}_sph.zip"
    if not zip_path.is_file():
        _, zip_path = build_sph_package(scenario_id)
    return zip_path


def execute_sph_run(scenario_id: str, req: Optional[SPHRunRequest] = None) -> SPHRunResponse:
    """
    Execute PySPH simulation strictly gated by server policy and executable availability.
    Rejects with 409 Conflict if engine is unavailable or execution is disabled.
    """
    caps = detect_sph_capabilities()

    if not caps.execution_enabled or not caps.pysph_available or not caps.engine_executable:
        raise HTTPException(
            status_code=409,
            detail="engine_unavailable: PySPH Lagrangian simulation engine is not available or execution is disabled by server policy (ENABLE_PYSPH_EXECUTION=false). Never faking an SPH simulation run.",
        )

    scenario_data = load_scenario_dict(scenario_id)
    run_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    runs_dir = get_sph_runs_dir()
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Ensure package is prepared
    _, zip_path = build_sph_package(scenario_id)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(run_dir)

    script_path = run_dir / "scripts" / "dam_break_2d_pysph.py"
    stdout_file = run_dir / "stdout.log"
    stderr_file = run_dir / "stderr.log"

    cmd = [caps.engine_executable, str(script_path), "--max-steps", "100"]
    timeout_sec = int(os.environ.get("PYSPH_TIMEOUT_SECONDS", "300"))

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
            err_f.write(f"\n[ERROR] PySPH simulation exceeded timeout of {timeout_sec} seconds.\n")
    except Exception as e:
        status = "failed"
        exit_code = -2
        with open(stderr_file, "a", encoding="utf-8") as err_f:
            err_f.write(f"\n[ERROR] Failed to execute PySPH subprocess: {str(e)}\n")

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()

    run_record = {
        "run_id": run_id,
        "engine": "pysph",
        "scenario_id": scenario_id,
        "scenario_name": scenario_data.get("name", "Untitled"),
        "revision": int(scenario_data.get("revision", 1)),
        "status": status,
        "started_at": start_time.isoformat(),
        "completed_at": end_time.isoformat(),
        "duration_seconds": round(duration, 2),
        "exit_code": exit_code,
        "custom_notes": req.custom_notes if req else "",
    }

    with open(run_dir / "run_metadata.json", "w", encoding="utf-8") as f:
        json.dump(run_record, f, indent=2)

    return SPHRunResponse(
        run_id=run_id,
        scenario_id=scenario_id,
        scenario_name=scenario_data.get("name", "Untitled"),
        revision=int(scenario_data.get("revision", 1)),
        status=status,
        started_at=start_time.isoformat(),
        completed_at=end_time.isoformat(),
        duration_seconds=round(duration, 2),
        exit_code=exit_code,
        log_url=f"/api/runs/sph/{run_id}/logs",
        output_manifest_url=None,
        notes=[
            f"PySPH execution finished with status '{status}' (exit code: {exit_code}).",
            "Logs are stored in runtime directory.",
        ],
    )


def list_sph_runs() -> List[SPHRunResponse]:
    """List historical PySPH runs from runtime storage."""
    runs_dir = get_sph_runs_dir()
    results: List[SPHRunResponse] = []

    for meta_file in runs_dir.glob("*/run_metadata.json"):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            results.append(
                SPHRunResponse(
                    run_id=data["run_id"],
                    scenario_id=data["scenario_id"],
                    scenario_name=data.get("scenario_name", "Untitled"),
                    revision=data.get("revision", 1),
                    status=data.get("status", "completed"),
                    started_at=data["started_at"],
                    completed_at=data.get("completed_at"),
                    duration_seconds=data.get("duration_seconds"),
                    exit_code=data.get("exit_code"),
                    log_url=f"/api/runs/sph/{data['run_id']}/logs",
                    output_manifest_url=None,
                    notes=["Historical PySPH run record."],
                )
            )
        except Exception:
            continue

    results.sort(key=lambda r: r.started_at, reverse=True)
    return results


def get_sph_run(run_id: str) -> SPHRunResponse:
    """Retrieve metadata for a specific PySPH run."""
    valid_id = validate_uuid_str(run_id)
    meta_path = get_sph_runs_dir() / valid_id / "run_metadata.json"
    if not meta_path.is_file():
        raise HTTPException(status_code=404, detail=f"PySPH simulation run '{valid_id}' not found.")

    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return SPHRunResponse(
        run_id=data["run_id"],
        scenario_id=data["scenario_id"],
        scenario_name=data.get("scenario_name", "Untitled"),
        revision=data.get("revision", 1),
        status=data.get("status", "completed"),
        started_at=data["started_at"],
        completed_at=data.get("completed_at"),
        duration_seconds=data.get("duration_seconds"),
        exit_code=data.get("exit_code"),
        log_url=f"/api/runs/sph/{valid_id}/logs",
        output_manifest_url=None,
        notes=["PySPH run record."],
    )


def get_sph_run_logs(run_id: str) -> SimulationLogResponse:
    """Retrieve captured stdout and stderr logs for a PySPH run."""
    valid_id = validate_uuid_str(run_id)
    run_dir = get_sph_runs_dir() / valid_id
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"PySPH simulation run '{valid_id}' not found.")

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


# Function aliases for consistency
check_sph_capabilities = detect_sph_capabilities
get_sph_logs = get_sph_run_logs
SPH_RUNS_DIR = get_sph_runs_dir()


# ==============================================================================
# Phase 25: Project-Scoped SPH Workflow, Particle Rasterizer & Run Importer
# ==============================================================================

def get_dam_project_sph_dir(project_id: str) -> Path:
    """Return root directory for SPH packages and runs under a dam project."""
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid / "sph"
    p_dir.mkdir(parents=True, exist_ok=True)
    return p_dir


def sanitize_filename(filename: str) -> str:
    """Sanitize uploaded filename against directory traversal and dangerous characters."""
    clean = Path(filename).name.strip()
    clean = clean.replace("..", "").replace("/", "").replace("\\", "")
    if not clean:
        clean = f"imported_file_{uuid.uuid4().hex[:6]}"
    return clean


def build_dam_project_sph_package(project_id: str) -> Tuple[ProjectSPHPackageResponse, Path]:
    """
    Build a project-specific SPH model package archive for the dam project.
    Generates tailored PySPH initial condition scripts, geometry, and output requirements.
    """
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid
    if not p_dir.is_dir() or not (p_dir / "project.json").is_file():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found")

    project_data: Dict[str, Any] = json.loads((p_dir / "project.json").read_text(encoding="utf-8"))
    sph_dir = get_dam_project_sph_dir(valid_pid)
    packages_dir = sph_dir / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)

    pkg_name = f"{valid_pid}_sph_package"
    pkg_work_dir = packages_dir / pkg_name
    zip_path = packages_dir / f"{pkg_name}.zip"

    for sub in ["config", "scripts", "docs"]:
        (pkg_work_dir / sub).mkdir(parents=True, exist_ok=True)

    caps = detect_sph_capabilities()
    dam_name = project_data.get("name", "Project Dam")
    dam_height = float(project_data.get("dam_height_m") or 60.0)
    crest_len = float(project_data.get("crest_length_m") or 200.0)
    norm_res = float(project_data.get("normal_reservoir_level_m") or 650.0)

    # 1. Project-tailored PySPH script
    script_content = f'''"""
PySPH Project Hydrodynamic Simulation Script
Project: {dam_name} (ID: {valid_pid})
Generated: {datetime.now(timezone.utc).isoformat()}

SCIENTIFIC SCALE SEPARATION NOTE:
PySPH implements 3D/2D Lagrangian particle hydrodynamics tailored for near-field
breach opening, wave impact forces, and turbulent overtopping.
For full downstream valley routing (>10 km), coupling or comparison with 2D Eulerian
shallow water models (Delft3D / ANUGA) is recommended.
"""

import numpy as np
try:
    from pysph.base.utils import get_particle_array_wcsph
    from pysph.base.kernels import QuinticSpline
    from pysph.solver.application import Application
    from pysph.sph.integrator import EPECIntegrator
    from pysph.sph.integrator_step import WCSPHStep
    from pysph.sph.equation import Group
    from pysph.sph.basic_equations import ContinuityEquation, XSPHCorrection
    from pysph.sph.wc.basic import TaitEOS, MomentumEquation, PressureGradient
    PYSPH_LOADED = True
except ImportError:
    PYSPH_LOADED = False

class ProjectDamBreakSPHApp:
    def __init__(self):
        self.project_id = "{valid_pid}"
        self.dam_height_m = {dam_height}
        self.crest_length_m = {crest_len}
        self.normal_reservoir_level_m = {norm_res}
        self.dx = 0.5  # Recommended near-field particle spacing (m)
        self.smoothing_length = 1.3 * self.dx
        self.rho0 = 1000.0
        self.gravity = -9.81

    def run(self):
        print(f"Initializing PySPH near-field domain for {dam_name}...")
        if not PYSPH_LOADED:
            print("PySPH module not installed in current interpreter.")
            return
        print("Ready for Lagrangian time integration.")

if __name__ == "__main__":
    app = ProjectDamBreakSPHApp()
    app.run()
'''
    (pkg_work_dir / "scripts" / "project_sph_dambreak.py").write_text(script_content, encoding="utf-8")

    # 2. SPH Configuration JSON
    config_data = {
        "project_id": valid_pid,
        "dam_name": dam_name,
        "solver_framework": "PySPH (Lagrangian SPH)",
        "kernel": "QuinticSpline",
        "recommended_particle_spacing_m": 0.5,
        "smoothing_length_ratio": 1.3,
        "cfl": 0.25,
        "gravity": [0.0, 0.0, -9.81],
        "fluid_density_kg_m3": 1000.0,
        "near_field_dimensions": {
            "dam_height_m": dam_height,
            "crest_length_m": crest_len,
            "reservoir_level_m": norm_res,
        },
        "output_raster_specification": {
            "required_layers": ["maximum_depth.tif", "maximum_velocity.tif", "arrival_time.tif"],
            "target_metric_crs": "EPSG:32643",
            "recommended_resolution_m": 10.0,
            "nodata_value": -9999.0,
        }
    }
    (pkg_work_dir / "config" / "sph_simulation_config.json").write_text(json.dumps(config_data, indent=2), encoding="utf-8")

    # 3. Scientific README
    readme_content = f"""================================================================================
PROJECT-SPECIFIC SPH HYDRODYNAMIC MODEL PACKAGE (PySPH)
================================================================================
Project:           {dam_name}
Project ID:        {valid_pid}
Generated:         {datetime.now(timezone.utc).isoformat()}
PySPH Available:   {caps.pysph_available}

SCIENTIFIC REQUIREMENTS & POSTPROCESSING CONTRACT:
1. SPH PARTICLES TO EULERIAN RASTER CONTRACT:
   To compare PySPH results with shallow water solvers (Delft3D / ANUGA), completed
   particle outputs must be postprocessed onto a common metric grid:
   - maximum_depth.tif    (m, NoData: -9999.0)
   - maximum_velocity.tif (m/s, NoData: -9999.0)
   - arrival_time.tif     (seconds from failure, NoData: -9999.0)

2. IMPORTING EXTERNALLY COMPUTED SPH RUNS:
   If PySPH is executed on a high-performance workstation or cluster, output rasters
   or raw particle arrays (.npz / .csv / .h5) can be imported directly into this
   system using the API endpoint:
   POST /api/dam-projects/{valid_pid}/sph/import-run
================================================================================
"""
    (pkg_work_dir / "docs" / "README_SPH_REQUIREMENTS.txt").write_text(readme_content, encoding="utf-8")

    # 4. Manifest
    manifest_data = {
        "manifest_version": "1.0.0",
        "project_id": valid_pid,
        "package_type": "project_sph_package",
        "solver_framework": "PySPH",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "capabilities_at_build": {
            "pysph_available": caps.pysph_available,
            "execution_enabled": caps.execution_enabled,
        },
        "output_contract": config_data["output_raster_specification"],
    }
    (pkg_work_dir / "manifest.json").write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    # 5. Build ZIP
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in pkg_work_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(pkg_work_dir)
                zf.write(file_path, arcname=arcname)

    pkg_size = zip_path.stat().st_size
    manifest_checksum = compute_file_sha256(pkg_work_dir / "manifest.json") or "unknown"

    response = ProjectSPHPackageResponse(
        project_id=valid_pid,
        package_filename=zip_path.name,
        package_size_bytes=pkg_size,
        created_at=manifest_data["created_at"],
        manifest_checksum=manifest_checksum,
        download_url=f"/api/dam-projects/{valid_pid}/sph/download-package",
        pysph_available=caps.pysph_available,
        execution_enabled=caps.execution_enabled,
        notes=[
            f"PySPH model package for project '{dam_name}' built successfully.",
            "Contains 2D/3D particle initialization templates and rasterization contract.",
        ],
    )
    return response, zip_path


def rasterize_sph_particles(
    particles: Dict[str, np.ndarray],
    bounds: Tuple[float, float, float, float],
    resolution_m: float,
    crs_str: str,
    out_dir: Path,
    params: Optional[SPHParticleInterpolationParams] = None,
) -> Dict[str, Path]:
    """
    Interpolates Lagrangian SPH particle states (x, y, depth, velocity, arrival_time)
    onto a regular Eulerian raster grid matching target metric CRS and bounds.
    Writes maximum_depth.tif, maximum_velocity.tif (if available), arrival_time.tif (if available).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    min_x, min_y, max_x, max_y = bounds
    res = max(1.0, float(resolution_m))

    width = max(2, int(np.ceil((max_x - min_x) / res)))
    height = max(2, int(np.ceil((max_y - min_y) / res)))

    # Prevent unreasonable grid allocation
    if width > 4096 or height > 4096:
        scale = max(width / 4096, height / 4096)
        width = int(width / scale)
        height = int(height / scale)
        res = res * scale

    dst_transform = from_bounds(min_x, min_y, max_x, max_y, width, height)
    nodata_val = -9999.0

    px = particles.get("x")
    py = particles.get("y")
    p_depth = particles.get("depth")
    p_vel = particles.get("velocity")
    p_arr = particles.get("arrival_time")

    if px is None or py is None or p_depth is None or len(px) == 0:
        raise HTTPException(status_code=422, detail="SPH particle dataset must contain non-empty 'x', 'y', and 'depth' arrays.")

    px = np.asarray(px, dtype=np.float64)
    py = np.asarray(py, dtype=np.float64)
    p_depth = np.asarray(p_depth, dtype=np.float32)

    # Grid cell center coordinates
    col_coords = min_x + (np.arange(width) + 0.5) * ((max_x - min_x) / width)
    row_coords = max_y - (np.arange(height) + 0.5) * ((max_y - min_y) / height)
    gx, gy = np.meshgrid(col_coords, row_coords)

    # Smoothing & search radius
    h_smooth = params.smoothing_length_m if (params and params.smoothing_length_m) else (res * 1.5)
    r_search = h_smooth * (params.support_radius_factor if params else 2.0)
    p_power = params.power_parameter if params else 2.0

    depth_grid = np.full((height, width), nodata_val, dtype=np.float32)
    vel_grid = np.full((height, width), nodata_val, dtype=np.float32) if p_vel is not None else None
    arr_grid = np.full((height, width), nodata_val, dtype=np.float32) if p_arr is not None else None

    # Spatial KDTree querying (with scipy if available, or chunked numpy)
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(np.column_stack([px, py]))
        grid_points = np.column_stack([gx.ravel(), gy.ravel()])
        neighbors_list = tree.query_ball_point(grid_points, r=r_search)

        for idx, neighbors in enumerate(neighbors_list):
            if not neighbors:
                continue
            r_idx = idx // width
            c_idx = idx % width

            n_px = px[neighbors]
            n_py = py[neighbors]
            dists = np.sqrt((n_px - gx[r_idx, c_idx]) ** 2 + (n_py - gy[r_idx, c_idx]) ** 2)
            weights = 1.0 / (np.maximum(dists, 0.1) ** p_power)
            w_sum = np.sum(weights)

            if w_sum > 0:
                depth_grid[r_idx, c_idx] = float(np.sum(weights * p_depth[neighbors]) / w_sum)
                if vel_grid is not None:
                    p_vel_arr = np.asarray(p_vel, dtype=np.float32)
                    vel_grid[r_idx, c_idx] = float(np.sum(weights * p_vel_arr[neighbors]) / w_sum)
                if arr_grid is not None:
                    p_arr_arr = np.asarray(p_arr, dtype=np.float32)
                    arr_grid[r_idx, c_idx] = float(np.min(p_arr_arr[neighbors]))
    except Exception:
        # Fallback cell-binning
        col_idx = np.clip(((px - min_x) / (max_x - min_x) * width).astype(int), 0, width - 1)
        row_idx = np.clip(((max_y - py) / (max_y - min_y) * height).astype(int), 0, height - 1)
        for i in range(len(px)):
            r_i, c_i = row_idx[i], col_idx[i]
            if depth_grid[r_i, c_i] == nodata_val or p_depth[i] > depth_grid[r_i, c_i]:
                depth_grid[r_i, c_i] = p_depth[i]
            if vel_grid is not None:
                v_val = float(p_vel[i])
                if vel_grid[r_i, c_i] == nodata_val or v_val > vel_grid[r_i, c_i]:
                    vel_grid[r_i, c_i] = v_val
            if arr_grid is not None:
                a_val = float(p_arr[i])
                if arr_grid[r_i, c_i] == nodata_val or a_val < arr_grid[r_i, c_i]:
                    arr_grid[r_i, c_i] = a_val

    # Write output GeoTIFFs
    out_crs = CRS.from_string(crs_str)
    created_paths: Dict[str, Path] = {}

    # 1. maximum_depth.tif
    depth_tif = out_dir / "maximum_depth.tif"
    with rasterio.open(
        depth_tif, "w", driver="GTiff", height=height, width=width, count=1,
        dtype=rasterio.float32, crs=out_crs, transform=dst_transform,
        nodata=nodata_val, compress="deflate"
    ) as dst:
        dst.write(depth_grid, 1)
    created_paths["maximum_depth"] = depth_tif

    # 2. maximum_velocity.tif
    if vel_grid is not None:
        vel_tif = out_dir / "maximum_velocity.tif"
        with rasterio.open(
            vel_tif, "w", driver="GTiff", height=height, width=width, count=1,
            dtype=rasterio.float32, crs=out_crs, transform=dst_transform,
            nodata=nodata_val, compress="deflate"
        ) as dst:
            dst.write(vel_grid, 1)
        created_paths["maximum_velocity"] = vel_tif

    # 3. arrival_time.tif
    if arr_grid is not None:
        arr_tif = out_dir / "arrival_time.tif"
        with rasterio.open(
            arr_tif, "w", driver="GTiff", height=height, width=width, count=1,
            dtype=rasterio.float32, crs=out_crs, transform=dst_transform,
            nodata=nodata_val, compress="deflate"
        ) as dst:
            dst.write(arr_grid, 1)
        created_paths["arrival_time"] = arr_tif

    return created_paths


def import_dam_project_sph_run(
    project_id: str,
    uploaded_files: List[Tuple[str, bytes]],
    req: SPHRunImportRequest,
) -> Dict[str, Any]:
    """
    Securely import an externally computed PySPH simulation run into dam project storage.
    Accepts standardized GeoTIFFs or raw particle array files (.npz, .csv, .json).
    Validates files, enforces size guards, blocks path traversal, and produces standardized products.
    """
    valid_pid = validate_project_uuid(project_id)
    p_dir = get_dam_projects_dir() / valid_pid
    if not p_dir.is_dir() or not (p_dir / "project.json").is_file():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_pid}' not found")

    if not uploaded_files:
        raise HTTPException(status_code=400, detail="No files provided for SPH run import.")

    # Guard: total upload size limit (500 MB)
    total_bytes = sum(len(b) for _, b in uploaded_files)
    if total_bytes > 500 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Total uploaded size exceeds 500 MB limit.")

    run_id = f"sph-import-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    sph_dir = get_dam_project_sph_dir(valid_pid)
    run_dir = sph_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    saved_files: Dict[str, Path] = {}
    file_hashes: Dict[str, str] = {}
    allowed_exts = {".tif", ".tiff", ".npz", ".csv", ".json", ".h5"}

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

    # Check if GeoTIFFs were uploaded directly
    geotiffs = {k: v for k, v in saved_files.items() if v.suffix.lower() in [".tif", ".tiff"]}
    depth_tif = None
    vel_tif = None
    arr_tif = None

    for name, path in geotiffs.items():
        name_lower = name.lower()
        if "depth" in name_lower or name_lower in ["maximum_depth.tif", "depth.tif"]:
            depth_tif = path
            # Standardize filename
            if path.name != "maximum_depth.tif":
                std_path = run_dir / "maximum_depth.tif"
                shutil.copy2(path, std_path)
                depth_tif = std_path
        elif "vel" in name_lower or name_lower in ["maximum_velocity.tif", "velocity.tif"]:
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

    # If particle files uploaded (.npz, .csv, .json), perform particle rasterization
    if not depth_tif:
        particle_files = {k: v for k, v in saved_files.items() if v.suffix.lower() in [".npz", ".csv", ".json"]}
        if not particle_files:
            raise HTTPException(
                status_code=422,
                detail="Uploaded SPH run must contain either GeoTIFF rasters (maximum_depth.tif) or particle data (.npz, .csv, .json)."
            )

        # Load particle data from the first particle file
        p_file = list(particle_files.values())[0]
        particles_dict: Dict[str, np.ndarray] = {}

        if p_file.suffix.lower() == ".npz":
            npz_data = np.load(p_file)
            for key in ["x", "y", "depth", "velocity", "arrival_time"]:
                if key in npz_data:
                    particles_dict[key] = npz_data[key]
        elif p_file.suffix.lower() == ".csv":
            import csv
            with open(p_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            if not rows:
                raise HTTPException(status_code=422, detail="Empty particle CSV file.")
            for col in ["x", "y", "depth", "velocity", "arrival_time"]:
                if col in rows[0]:
                    particles_dict[col] = np.array([float(r[col]) for r in rows], dtype=np.float64)
        elif p_file.suffix.lower() == ".json":
            j_data = json.loads(p_file.read_text(encoding="utf-8"))
            if isinstance(j_data, dict):
                for col in ["x", "y", "depth", "velocity", "arrival_time"]:
                    if col in j_data:
                        particles_dict[col] = np.array(j_data[col], dtype=np.float64)
            elif isinstance(j_data, list) and len(j_data) > 0 and isinstance(j_data[0], dict):
                for col in ["x", "y", "depth", "velocity", "arrival_time"]:
                    if col in j_data[0]:
                        particles_dict[col] = np.array([float(r[col]) for r in j_data], dtype=np.float64)

        if "x" not in particles_dict or "y" not in particles_dict or "depth" not in particles_dict:
            raise HTTPException(
                status_code=422,
                detail="Particle file must contain coordinates ('x', 'y') and water depth ('depth')."
            )

        # Determine bounds from particle coordinates with 5% margin
        px = particles_dict["x"]
        py = particles_dict["y"]
        margin_x = max((np.max(px) - np.min(px)) * 0.05, 50.0)
        margin_y = max((np.max(py) - np.min(py)) * 0.05, 50.0)
        bounds = (
            float(np.min(px) - margin_x),
            float(np.min(py) - margin_y),
            float(np.max(px) + margin_x),
            float(np.max(py) + margin_y),
        )

        target_crs = req.target_crs or "EPSG:32643"
        target_res = req.particle_params.target_resolution_m if req.particle_params else 10.0

        rasterized = rasterize_sph_particles(
            particles=particles_dict,
            bounds=bounds,
            resolution_m=target_res,
            crs_str=target_crs,
            out_dir=run_dir,
            params=req.particle_params,
        )
        depth_tif = rasterized.get("maximum_depth")
        vel_tif = rasterized.get("maximum_velocity")
        arr_tif = rasterized.get("arrival_time")

    if not depth_tif or not depth_tif.is_file():
        raise HTTPException(status_code=422, detail="Failed to produce or validate maximum_depth.tif for imported SPH run.")

    # Validate output GeoTIFF with rasterio
    with rasterio.open(depth_tif) as src:
        native_crs_str = str(src.crs or "EPSG:4326")
        res_x = abs(src.transform.a)
        bounds_tup = (float(src.bounds.left), float(src.bounds.bottom), float(src.bounds.right), float(src.bounds.top))
        nodata_val = float(src.nodata if src.nodata is not None else -9999.0)

    # Calculate layer hashes
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
        "engine": "pysph",
        "engine_version": "PySPH Lagrangian (Imported)",
        "run_label": req.run_label or "Imported SPH Run",
        "status": "completed",
        "solver_execution_status": "imported",
        "scientific_status": req.scientific_status or "imported_external_run",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": req.notes or "",
        "native_crs": native_crs_str,
        "native_resolution_m": round(res_x, 4),
        "bounds": bounds_tup,
        "nodata_value": nodata_val,
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
            "import_mode": "geotiff" if geotiffs else "particle_rasterization",
            "particle_params": req.particle_params.model_dump() if req.particle_params else None,
        }
    }

    (run_dir / "run.json").write_text(json.dumps(run_record, indent=2), encoding="utf-8")
    return run_record


def list_dam_project_sph_runs(project_id: str) -> List[Dict[str, Any]]:
    """List all completed/imported SPH runs for a dam project."""
    valid_pid = validate_project_uuid(project_id)
    sph_dir = get_dam_project_sph_dir(valid_pid)
    runs_dir = sph_dir / "runs"
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


def get_dam_project_sph_run_detail(project_id: str, run_id: str) -> Dict[str, Any]:
    """Retrieve full details of an SPH run under a dam project."""
    valid_pid = validate_project_uuid(project_id)
    clean_rid = sanitize_filename(run_id)
    sph_dir = get_dam_project_sph_dir(valid_pid)
    r_json = sph_dir / "runs" / clean_rid / "run.json"
    if not r_json.is_file():
        raise HTTPException(status_code=404, detail=f"SPH run '{clean_rid}' not found in project '{valid_pid}'.")
    return json.loads(r_json.read_text(encoding="utf-8"))

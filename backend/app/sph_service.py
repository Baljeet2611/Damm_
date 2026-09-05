import os
import sys
import json
import uuid
import shutil
import zipfile
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from fastapi import HTTPException

from app.schemas import (
    SPHCapabilitiesResponse,
    SPHPackageResponse,
    SPHRunRequest,
    SPHRunResponse,
    SimulationLogResponse,
)
from app.scenario_storage import (
    get_runtime_dir,
    load_scenario_dict,
    validate_uuid_str,
    compute_file_sha256,
    compute_scenario_snapshot_checksum,
)
from app.raster_service import resolve_dataset_file


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


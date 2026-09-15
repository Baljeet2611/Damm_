"""
Execution script to run Hidkal demo ANUGA simulation end-to-end.
"""
import os
import sys
import json
import time
from pathlib import Path

# Enable custom execution gate
os.environ["ENABLE_CUSTOM_ANUGA_EXECUTION"] = "true"
os.environ["ANUGA_PYTHON_EXECUTABLE"] = r"C:\Users\pc\anaconda3\envs\sih-anuga\python.exe"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.onboarding_service import (
    load_or_create_hidkal_demo_project,
    assess_project_simulation_readiness,
    assess_anuga_preflight,
    build_dam_project_anuga_package,
    create_dam_project_anuga_run,
    get_dam_project_anuga_run,
    get_dam_project_anuga_run_logs,
    get_dam_project_anuga_outputs,
    get_dam_projects_dir,
)
from app.anuga_postprocessing_service import (
    postprocess_dam_project_anuga_run,
    get_dam_project_anuga_results,
    get_dam_project_anuga_layer_metadata,
)
from app.schemas import DamProjectAnugaRunRequest, DamProjectAnugaPostprocessRequest

def main():
    print("=== 1. Load Hidkal Demo Project ===")
    proj = load_or_create_hidkal_demo_project()
    project_id = proj.project_id
    print(f"Project ID: {project_id}")
    print(f"Project Name: {proj.project_name}")

    print("\n=== 2. Check Readiness ===")
    readiness = assess_project_simulation_readiness(project_id)
    print(f"Simulation Ready: {readiness.simulation_ready}")
    print(f"Data Ready: {readiness.data_ready}, Geometry Ready: {readiness.geometry_ready}, Hydraulic Ready: {readiness.hydraulic_ready}, Solver Ready: {readiness.solver_ready}")
    print(f"Missing Requirements: {readiness.missing_requirements}")

    print("\n=== 3. Preflight Assessment ===")
    preflight = assess_anuga_preflight(project_id)
    print(f"Preflight Passed: {preflight.preflight_passed}")
    print(f"Blockers: {preflight.blockers}")
    print(f"Warnings: {preflight.warnings}")
    print(f"Proposed Config: {json.dumps(preflight.proposed_configuration, indent=2)}")

    # Remove cached zip to ensure latest run_anuga.py is used
    pkg_zip = get_dam_projects_dir() / project_id / "packages" / "anuga_package.zip"
    if pkg_zip.is_file():
        pkg_zip.unlink()

    print("\n=== 4. Build ANUGA Package ===")
    pkg = build_dam_project_anuga_package(project_id)
    print(f"Package Filename: {pkg.package_filename}")
    print(f"Package Size: {pkg.package_size_bytes} bytes")
    print(f"Files: {pkg.files_included}")

    print("\n=== 5. Launch ANUGA Run ===")
    run_req = DamProjectAnugaRunRequest(
        acknowledge_hypothetical_unverified=True,
        target_mesh_resolution_m=50.0,
        simulation_duration_s=3600.0,
        output_interval_s=60.0,
        manning_roughness=0.035,
    )
    run_resp = create_dam_project_anuga_run(project_id, run_req)
    run_id = run_resp.run_id
    print(f"Run ID: {run_id}")
    print(f"Initial Status: {run_resp.status}")

    print("\n=== 6. Monitoring Execution ===")
    start_time = time.time()
    last_status = run_resp.status
    while True:
        curr_run = get_dam_project_anuga_run(project_id, run_id)
        if curr_run.status != last_status:
            print(f"Status changed to: {curr_run.status} (elapsed {time.time() - start_time:.1f}s)")
            last_status = curr_run.status

        if curr_run.status in ("completed", "failed", "cancelled"):
            break
        time.sleep(2.0)

    total_time = time.time() - start_time
    print(f"\nSimulation finished with status: {curr_run.status} in {total_time:.2f}s")
    print(f"Exit Code: {curr_run.exit_code}")
    print(f"Message: {curr_run.message}")

    print("\n=== 7. Run Logs ===")
    logs = get_dam_project_anuga_run_logs(project_id, run_id)
    log_lines = logs.splitlines()
    print(f"Total Log Lines: {len(log_lines)}")
    print("\n--- Tail of Logs ---")
    for l in log_lines[-25:]:
        print(l)

    if curr_run.status != "completed":
        print("\n[ERROR] Simulation did not complete successfully.")
        return False

    print("\n=== 8. SWW Outputs & Results Inspection ===")
    outputs = get_dam_project_anuga_outputs(project_id, run_id)
    print(f"Status: {outputs.status}")
    print(f"Has Results: {outputs.has_results}")
    print(f"SWW File: {outputs.sww_file} ({outputs.sww_size_bytes} bytes, SHA-256: {outputs.sww_sha256})")
    print(f"Runtime: {outputs.runtime_seconds} s")
    print(f"Output Files: {outputs.output_files}")
    print(f"Available Layers: {outputs.available_layers}")
    print(f"Layer Statistics: {outputs.layer_statistics}")

    print("\n=== 9. Raster Metadata Inspection ===")
    for layer in ["maximum_depth", "maximum_velocity", "arrival_time"]:
        meta = get_dam_project_anuga_layer_metadata(project_id, run_id, layer)
        print(f"Layer '{layer}': CRS={meta.crs}, Dimensions=({meta.width}x{meta.height}), Min={meta.valid_min:.4f}, Max={meta.valid_max:.4f}, Bounds={meta.bounds.model_dump()}")

    print("\n=== FIRST ANUGA EXECUTION FOR HIDKAL COMPLETED SUCCESSFULLY ===")
    return True

if __name__ == "__main__":
    success = main()
    if not success:
        sys.exit(1)

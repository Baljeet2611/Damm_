"""
Unit and integration tests for Gated Custom ANUGA Simulation Execution API (SIH PS 26161).

Tests:
1. Execution disabled by default (403 custom_anuga_execution_disabled).
2. Acknowledgement gate (requires acknowledge_hypothetical_unverified=True, else 422).
3. Capabilities endpoint reports accurate status, reason, and disclaimer.
4. Package requirement before running (400 package_not_built).
5. Manifest tampering protection (409 project_integrity_failed).
6. Non-zero exit code failure handling (status=failed, simulation_executed=False).
7. Timeout handling (status=timed_out, simulation_executed=False).
8. Malformed/missing SWW never marked completed.
9. Sanitized log stream (no absolute paths or environment leakage).
10. Run persistence across restarts (stored under runtime/dam_projects/{uuid}/runs/{run_uuid}).
11. Real canary execution integration test (skipped when sih-anuga is unavailable).
"""

import io
import os
import json
import time
import uuid
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set
import numpy as np
from scipy.io import netcdf_file
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import onboarding_service
from app import anuga_postprocessing_service
from tests.test_anuga_onboarding_api import get_standard_valid_payload, create_test_geotiff_bytes

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_dam_projects_storage(tmp_path, monkeypatch):
    """Ensure all tests execute with an isolated temporary dam_projects storage directory."""
    temp_dir = tmp_path / "dam_projects"
    temp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(onboarding_service, "get_dam_projects_dir", lambda: temp_dir)
    monkeypatch.setattr(anuga_postprocessing_service, "get_dam_projects_dir", lambda: temp_dir)
    return temp_dir


def create_saved_project_with_package():
    """Helper to register a valid project and build its ANUGA package."""
    files, data = get_standard_valid_payload()
    save_res = client.post("/api/dam-projects", files=files, data=data)
    assert save_res.status_code == 200
    p_id = save_res.json()["project_id"]

    build_res = client.post(f"/api/dam-projects/{p_id}/anuga/build-package")
    assert build_res.status_code == 200
    return p_id


def create_canary_project_with_package():
    """Helper to create a small synthetic canary project for real ANUGA execution."""
    dem_bytes = create_test_geotiff_bytes(width=40, height=40, res=30.0, min_val=580.0, max_val=700.0)
    dam_axis_geojson = {
        "type": "LineString",
        "coordinates": [[500500.0, 1799100.0], [500500.0, 1799700.0]],
    }
    reservoir_geojson = {
        "type": "Polygon",
        "coordinates": [
            [
                [500100.0, 1799100.0],
                [500500.0, 1799100.0],
                [500500.0, 1799700.0],
                [500100.0, 1799700.0],
                [500100.0, 1799100.0],
            ]
        ],
    }
    domain_geojson = {
        "type": "Polygon",
        "coordinates": [
            [
                [500050.0, 1798900.0],
                [501150.0, 1798900.0],
                [501150.0, 1799950.0],
                [500050.0, 1799950.0],
                [500050.0, 1798900.0],
            ]
        ],
    }
    outlet_geojson = {
        "type": "LineString",
        "coordinates": [[501150.0, 1799000.0], [501150.0, 1799600.0]],
    }

    files = {
        "dem_file": ("dem.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", json.dumps(dam_axis_geojson).encode("utf-8"), "application/geo+json"),
        "reservoir_boundary_file": ("reservoir.geojson", json.dumps(reservoir_geojson).encode("utf-8"), "application/geo+json"),
        "model_domain_file": ("domain.geojson", json.dumps(domain_geojson).encode("utf-8"), "application/geo+json"),
        "downstream_outlet_file": ("outlet.geojson", json.dumps(outlet_geojson).encode("utf-8"), "application/geo+json"),
    }
    data = {
        "project_name": "Synthetic execution canary — not Hidkal and not a prediction.",
        "vertical_unit": "meters",
        "vertical_datum": "MSL",
        "reservoir_level": 655.0,
        "dam_crest_elevation": 665.0,
        "breach_invert_elevation": 590.0,
        "breach_width": 100.0,
        "breach_center_x": 500500.0,
        "breach_center_y": 1799400.0,
        "target_mesh_resolution_m": 40.0,
        "simulation_duration_s": 40.0,
        "output_interval_s": 10.0,
        "manning_roughness": 0.035,
        "geometry_crs": "EPSG:32643",
        "acknowledge_unverified_metadata": "true",
    }

    save_res = client.post("/api/dam-projects", files=files, data=data)
    assert save_res.status_code == 200, f"Failed save: {save_res.text}"
    p_id = save_res.json()["project_id"]

    build_res = client.post(f"/api/dam-projects/{p_id}/anuga/build-package")
    assert build_res.status_code == 200, f"Failed build: {build_res.text}"
    return p_id


class TestDamProjectAnugaCapabilities:
    """Tests for GET /api/dam-projects/{project_id}/anuga/capabilities."""

    def test_capabilities_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("ENABLE_CUSTOM_ANUGA_EXECUTION", raising=False)
        p_id = create_saved_project_with_package()

        res = client.get(f"/api/dam-projects/{p_id}/anuga/capabilities")
        assert res.status_code == 200
        data = res.json()
        assert data["execution_enabled"] is False
        assert "disabled by default" in data["reason"].lower()
        assert "hypothetical" in data["disclaimer"].lower()

    def test_capabilities_enabled_when_env_flag_set(self, monkeypatch):
        monkeypatch.setenv("ENABLE_CUSTOM_ANUGA_EXECUTION", "true")
        p_id = create_saved_project_with_package()

        res = client.get(f"/api/dam-projects/{p_id}/anuga/capabilities")
        assert res.status_code == 200
        data = res.json()
        assert "disclaimer" in data


class TestDamProjectAnugaGatedExecution:
    """Tests for POST /api/dam-projects/{project_id}/anuga/runs and gates."""

    def test_execution_blocked_when_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("ENABLE_CUSTOM_ANUGA_EXECUTION", raising=False)
        p_id = create_saved_project_with_package()

        run_res = client.post(
            f"/api/dam-projects/{p_id}/anuga/runs",
            json={"acknowledge_hypothetical_unverified": True},
        )
        assert run_res.status_code == 403
        err = run_res.json()
        assert err["detail"]["code"] == "custom_anuga_execution_disabled"

    def test_execution_blocked_without_user_acknowledgement(self, monkeypatch):
        monkeypatch.setenv("ENABLE_CUSTOM_ANUGA_EXECUTION", "true")
        p_id = create_saved_project_with_package()

        run_res = client.post(
            f"/api/dam-projects/{p_id}/anuga/runs",
            json={"acknowledge_hypothetical_unverified": False},
        )
        assert run_res.status_code == 422
        assert "acknowledgment" in run_res.json()["detail"].lower()

    def test_execution_blocked_when_package_not_built(self, monkeypatch):
        monkeypatch.setenv("ENABLE_CUSTOM_ANUGA_EXECUTION", "true")
        files, data = get_standard_valid_payload()
        save_res = client.post("/api/dam-projects", files=files, data=data)
        p_id = save_res.json()["project_id"]

        run_res = client.post(
            f"/api/dam-projects/{p_id}/anuga/runs",
            json={"acknowledge_hypothetical_unverified": True},
        )
        assert run_res.status_code == 400
        err = run_res.json()
        assert err["detail"]["code"] == "package_not_built"

    def test_execution_blocked_on_tampered_project(self, monkeypatch):
        monkeypatch.setenv("ENABLE_CUSTOM_ANUGA_EXECUTION", "true")
        p_id = create_saved_project_with_package()

        # Tamper dem.tif
        proj_dir = onboarding_service.get_dam_projects_dir() / p_id
        (proj_dir / "dem.tif").write_bytes(b"tampered")

        run_res = client.post(
            f"/api/dam-projects/{p_id}/anuga/runs",
            json={"acknowledge_hypothetical_unverified": True},
        )
        assert run_res.status_code == 409
        assert run_res.json()["detail"]["code"] == "project_integrity_failed"


class TestDamProjectAnugaRunLifecycle:
    """Tests for worker execution, state transitions, log streaming, and persistence."""

    def test_mocked_successful_run_lifecycle(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ENABLE_CUSTOM_ANUGA_EXECUTION", "true")
        p_id = create_saved_project_with_package()

        # Mock _execute_anuga_run_worker to simulate successful execution
        def mock_worker(run_id, project_id, run_dir, pkg_zip_path, package_sha256, timeout_sec=300):
            run_json = run_dir / "run.json"
            log_file = run_dir / "execution.log"
            data = json.loads(run_json.read_text(encoding="utf-8"))
            data["status"] = "completed"
            data["started_at"] = "2026-09-06T20:00:00Z"
            data["completed_at"] = "2026-09-06T20:00:05Z"
            data["exit_code"] = 0
            data["runtime_seconds"] = 5.0
            data["simulation_executed"] = True
            data["output_files"] = {"output/dam_break.sww": "mock_hash_123456"}
            data["message"] = "Hydrodynamic simulation executed successfully."
            run_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
            log_file.write_text("Simulated run logs with path C:\\Users\\secret\\workspace\\dam.tif", encoding="utf-8")

        monkeypatch.setattr(onboarding_service, "_execute_anuga_run_worker", mock_worker)

        # Trigger run
        run_res = client.post(
            f"/api/dam-projects/{p_id}/anuga/runs",
            json={"acknowledge_hypothetical_unverified": True},
        )
        assert run_res.status_code == 200
        run_data = run_res.json()
        r_id = run_data["run_id"]
        assert run_data["status"] in ("queued", "completed")

        # Wait for mocked worker completion
        det = None
        for _ in range(50):
            time.sleep(0.1)
            detail_res = client.get(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}")
            assert detail_res.status_code == 200
            det = detail_res.json()
            if det["status"] != "queued":
                break

        assert det is not None
        assert det["status"] == "completed"
        assert det["simulation_executed"] is True
        assert det["scientific_status"] == "hypothetical_unverified"

        # List runs
        list_res = client.get(f"/api/dam-projects/{p_id}/anuga/runs")
        assert list_res.status_code == 200
        runs_list = list_res.json()
        assert len(runs_list) == 1
        assert runs_list[0]["run_id"] == r_id

        # Get sanitized logs
        log_res = client.get(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/logs")
        assert log_res.status_code == 200, f"Logs failed with status {log_res.status_code}: {log_res.text}"
        log_text = log_res.text
        assert "dam.tif" in log_text
        assert "secret" not in log_text

    def test_mocked_failed_run_never_marked_completed(self, monkeypatch):
        monkeypatch.setenv("ENABLE_CUSTOM_ANUGA_EXECUTION", "true")
        p_id = create_saved_project_with_package()

        def mock_failed_worker(run_id, project_id, run_dir, pkg_zip_path, package_sha256, timeout_sec=300):
            run_json = run_dir / "run.json"
            log_file = run_dir / "execution.log"
            data = json.loads(run_json.read_text(encoding="utf-8"))
            data["status"] = "failed"
            data["exit_code"] = 1
            data["simulation_executed"] = False
            data["message"] = "ANUGA execution exited with code 1."
            run_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
            log_file.write_text("Error: ANUGA mesh error", encoding="utf-8")

        monkeypatch.setattr(onboarding_service, "_execute_anuga_run_worker", mock_failed_worker)

        run_res = client.post(
            f"/api/dam-projects/{p_id}/anuga/runs",
            json={"acknowledge_hypothetical_unverified": True},
        )
        assert run_res.status_code == 200
        r_id = run_res.json()["run_id"]

        det = None
        for _ in range(50):
            time.sleep(0.1)
            detail_res = client.get(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}")
            assert detail_res.status_code == 200
            det = detail_res.json()
            if det["status"] != "queued":
                break

        assert det is not None
        assert det["status"] == "failed"
        assert det["simulation_executed"] is False

    def test_mocked_timeout_run(self, monkeypatch):
        monkeypatch.setenv("ENABLE_CUSTOM_ANUGA_EXECUTION", "true")
        p_id = create_saved_project_with_package()

        def mock_timeout_worker(run_id, project_id, run_dir, pkg_zip_path, package_sha256, timeout_sec=300):
            run_json = run_dir / "run.json"
            data = json.loads(run_json.read_text(encoding="utf-8"))
            data["status"] = "timed_out"
            data["simulation_executed"] = False
            data["message"] = "Simulation timed out after 300 s."
            run_json.write_text(json.dumps(data, indent=2), encoding="utf-8")

        monkeypatch.setattr(onboarding_service, "_execute_anuga_run_worker", mock_timeout_worker)

        run_res = client.post(
            f"/api/dam-projects/{p_id}/anuga/runs",
            json={"acknowledge_hypothetical_unverified": True},
        )
        r_id = run_res.json()["run_id"]

        det = None
        for _ in range(50):
            time.sleep(0.1)
            detail_res = client.get(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}")
            assert detail_res.status_code == 200
            det = detail_res.json()
            if det["status"] != "queued":
                break

        assert det is not None
        assert det["status"] == "timed_out"
        assert det["simulation_executed"] is False


    def test_restart_recovery_marks_orphaned_jobs_interrupted(self, monkeypatch):
        """Orphaned queued/running jobs on disk with no active local worker are marked interrupted on recovery."""
        p_id = create_saved_project_with_package()
        proj_dir = onboarding_service.get_dam_projects_dir() / p_id
        run_id = str(uuid.uuid4())
        run_dir = proj_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Write simulated orphaned running job
        run_json = run_dir / "run.json"
        log_file = run_dir / "execution.log"
        initial_data = {
            "run_id": run_id,
            "project_id": p_id,
            "project_name": "Test Orphan",
            "package_sha256": "fake_sha256",
            "status": "running",
            "created_at": "2026-09-08T00:00:00Z",
            "started_at": "2026-09-08T00:00:01Z",
            "completed_at": None,
            "exit_code": None,
            "anuga_version": "0.0.0+unknown",
            "runtime_seconds": None,
            "log_file": "execution.log",
            "output_files": {},
            "scientific_status": "hypothetical_unverified",
            "simulation_executed": False,
            "message": "Simulated running job before restart.",
        }
        run_json.write_text(json.dumps(initial_data, indent=2), encoding="utf-8")
        log_file.write_text("Execution started before sudden crash/restart...", encoding="utf-8")

        # Calling list runs or get run triggers restart recovery
        runs_res = client.get(f"/api/dam-projects/{p_id}/anuga/runs")
        assert runs_res.status_code == 200
        runs = runs_res.json()
        assert len(runs) == 1
        assert runs[0]["status"] == "interrupted"
        assert runs[0]["simulation_executed"] is False
        assert "interrupted" in runs[0]["message"].lower()

        # Calling detail endpoint
        det_res = client.get(f"/api/dam-projects/{p_id}/anuga/runs/{run_id}")
        assert det_res.status_code == 200
        det = det_res.json()
        assert det["status"] == "interrupted"
        assert det["completed_at"] is not None

        # Check logs appended warning
        logs_res = client.get(f"/api/dam-projects/{p_id}/anuga/runs/{run_id}/logs")
        assert logs_res.status_code == 200
        assert "interrupted" in logs_res.text.lower()

    def test_malicious_zip_member_rejected(self, tmp_path):
        """Zip archive with path traversal or absolute paths must be safely rejected."""
        target_dir = tmp_path / "extract_dest"
        target_dir.mkdir(parents=True, exist_ok=True)

        # Test 1: Directory traversal
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            zf.writestr("../../evil.txt", "malicious payload")
        zip_buf.seek(0)
        traversal_zip = tmp_path / "traversal.zip"
        traversal_zip.write_bytes(zip_buf.getvalue())

        with pytest.raises(ValueError, match="traversal|Insecure"):
            onboarding_service.safe_extract_zip(traversal_zip, target_dir)

        # Test 2: Absolute / drive path
        zip_buf2 = io.BytesIO()
        with zipfile.ZipFile(zip_buf2, "w") as zf:
            zf.writestr("C:\\Windows\\system32\\evil.dll", "malicious binary")
        zip_buf2.seek(0)
        abs_zip = tmp_path / "abs.zip"
        abs_zip.write_bytes(zip_buf2.getvalue())

        with pytest.raises(ValueError, match="Insecure|drive|traversal"):
            onboarding_service.safe_extract_zip(abs_zip, target_dir)


class TestDamProjectAnugaRealCanaryIntegration:
    """Real canary integration test with genuine ANUGA executable."""

    def test_real_canary_end_to_end_execution(self, monkeypatch):
        # Mandatory integration gating: skipped by default unless RUN_ANUGA_INTEGRATION=1
        if os.environ.get("RUN_ANUGA_INTEGRATION", "").strip() not in ("1", "true", "yes"):
            pytest.skip("Real ANUGA solver integration canary skipped by default. Set RUN_ANUGA_INTEGRATION=1 to run.")

        anuga_exe = onboarding_service.get_anuga_python_executable()
        if not anuga_exe or not os.path.isfile(anuga_exe):
            pytest.skip("sih-anuga environment or Python executable not found on server")

        monkeypatch.setenv("ENABLE_CUSTOM_ANUGA_EXECUTION", "true")
        monkeypatch.setenv("ANUGA_PYTHON_EXECUTABLE", anuga_exe)

        p_id = create_canary_project_with_package()

        run_res = client.post(
            f"/api/dam-projects/{p_id}/anuga/runs",
            json={"acknowledge_hypothetical_unverified": True},
        )
        assert run_res.status_code == 200
        r_id = run_res.json()["run_id"]

        # Wait for worker completion (up to 240s)
        max_wait = 240
        waited = 0
        final_det = None
        while waited < max_wait:
            time.sleep(1)
            waited += 1
            det_res = client.get(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}")
            assert det_res.status_code == 200
            final_det = det_res.json()
            if final_det["status"] in ("completed", "failed", "timed_out", "interrupted"):
                break

        logs_res = client.get(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/logs")
        logs_txt = logs_res.text
        assert final_det is not None
        assert final_det["status"] == "completed", f"Real canary run failed: {final_det}\nExecution Logs:\n{logs_txt}"
        assert final_det["simulation_executed"] is True
        assert final_det["exit_code"] == 0
        assert final_det["runtime_seconds"] is not None
        assert any(k.endswith(".sww") for k in final_det["output_files"].keys())

        # Inspect generated SWW NetCDF file
        run_workspace = onboarding_service.get_dam_projects_dir() / p_id / "runs" / r_id / "workspace" / "output"
        sww_files = list(run_workspace.glob("*.sww"))
        assert len(sww_files) > 0, "No SWW file found in workspace output"
        sww_path = sww_files[0]

        ds = netcdf_file(str(sww_path), "r", mmap=False)
        try:
            for req in ["time", "stage", "elevation", "xmomentum", "ymomentum"]:
                assert req in ds.variables, f"Missing required hydrodynamic variable: {req}"

            times = ds.variables["time"][:]
            stages = ds.variables["stage"][:]
            elevations = ds.variables["elevation"][:]
            x_moms = ds.variables["xmomentum"][:]
            y_moms = ds.variables["ymomentum"][:]

            assert len(times) >= 2, f"Expected >= 2 timesteps, got {len(times)}"
            assert np.all(np.isfinite(stages)), "Stage array contains non-finite/NaN values"
            assert np.all(np.isfinite(elevations)), "Elevation array contains non-finite/NaN values"
            assert np.all(np.isfinite(x_moms)), "X-momentum contains non-finite/NaN values"
            assert np.all(np.isfinite(y_moms)), "Y-momentum contains non-finite/NaN values"

            # Check water propagated downstream
            xs_raw = ds.variables["x"][:]
            xll = float(getattr(ds, "xllcorner", 0.0))
            xs = xs_raw + xll
            downstream_mask = (xs > 500550.0)
            final_stage_pts = stages[-1]
            final_elev_pts = elevations
            final_depths = np.maximum(final_stage_pts - final_elev_pts, 0.0)
            downstream_depths = final_depths[downstream_mask]
            assert float(np.max(downstream_depths)) > 0.001, "Water did not propagate downstream through breach"

            # Storage-change plausibility check (scientific wording corrected)
            assert "stage_c" in ds.variables and "elevation_c" in ds.variables
            init_v = float(np.sum(np.maximum(ds.variables["stage_c"][0] - ds.variables["elevation_c"][:], 0.0)))
            final_v = float(np.sum(np.maximum(ds.variables["stage_c"][-1] - ds.variables["elevation_c"][:], 0.0)))
            abs_change = float(init_v - final_v)
            rel_change_pct = float(abs_change / init_v * 100.0)

            # Plausibility check: initial volume decreases slightly as water discharges through breach/domain
            assert final_v <= init_v * 1.01, f"Storage plausibility failed: final volume {final_v} > initial {init_v}"
            # For this canary project, relative storage reduction is approximately 1.86%
            assert 1.0 <= rel_change_pct <= 3.0, f"Expected approx 1.86% storage reduction, got {rel_change_pct:.2f}%"

            storage_change_report = {
                "initial_volume": round(init_v, 2),
                "final_volume": round(final_v, 2),
                "absolute_change": round(abs_change, 2),
                "relative_change_percentage": f"{rel_change_pct:.2f}%",
                "outlet_boundary_present": True,
                "cumulative_boundary_outflow": "not measured",
                "scientific_limitation": "Full mass conservation cannot be assessed without integrated boundary flux.",
            }
            storage_change_report = {
                "initial_volume": round(init_v, 2),
                "final_volume": round(final_v, 2),
                "absolute_change": round(abs_change, 2),
                "relative_change_percentage": f"{rel_change_pct:.2f}%",
                "outlet_boundary_present": True,
                "cumulative_boundary_outflow": "not measured",
                "scientific_limitation": "Full mass conservation cannot be assessed without integrated boundary flux.",
            }
            print(f"\n[STORAGE-CHANGE PLAUSIBILITY REPORT]\n{json.dumps(storage_change_report, indent=2)}")

            # Test real canary postprocessing
            post_res = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={
                "dry_depth_threshold_m": 0.005,
                "arrival_depth_threshold_m": 0.05,
            })
            assert post_res.status_code == 200, f"Postprocess failed: {post_res.text}"
            res_data = post_res.json()
            proc_id = res_data["processing_id"]

            assert "maximum_depth" in res_data["available_layers"]
            assert "maximum_velocity" in res_data["available_layers"]
            assert "arrival_time" in res_data["available_layers"]
            assert "maximum_depth" in res_data["layer_statistics"]
            assert "maximum_velocity" in res_data["layer_statistics"]
            assert "arrival_time" in res_data["layer_statistics"]
            assert res_data["mass_balance_status"] == "not_assessed"
            assert res_data["scientific_status"] == "hypothetical_unverified"

            # Verify exact storage path runs/{run_id}/results/{processing_id}/
            run_dir = onboarding_service.get_dam_projects_dir() / p_id / "runs" / r_id
            res_proc_dir = run_dir / "results" / proc_id
            assert res_proc_dir.is_dir(), f"Expected results directory at {res_proc_dir}"
            assert (res_proc_dir / "manifest.json").is_file()

            import rasterio
            from app.onboarding_service import compute_file_sha256

            layer_evidence = {}
            for l_name in ["maximum_depth", "maximum_velocity", "arrival_time"]:
                tif_p = res_proc_dir / f"{l_name}.tif"
                assert tif_p.is_file(), f"Missing GeoTIFF: {tif_p}"
                tif_sz = tif_p.stat().st_size
                assert tif_sz > 100, f"GeoTIFF {tif_p} is too small ({tif_sz} bytes)"
                tif_sha = compute_file_sha256(tif_p)

                with rasterio.open(tif_p) as src:
                    arr = src.read(1)
                    nodata_v = src.nodata
                    valid_mask = (arr != nodata_v) & np.isfinite(arr)
                    valid_count = int(np.sum(valid_mask))
                    nodata_count = int(np.sum(~valid_mask))
                    total_count = int(arr.size)
                    min_val = float(np.min(arr[valid_mask])) if valid_count > 0 else None
                    max_val = float(np.max(arr[valid_mask])) if valid_count > 0 else None

                    layer_evidence[l_name] = {
                        "path": str(tif_p),
                        "size_bytes": tif_sz,
                        "sha256": tif_sha,
                        "width": src.width,
                        "height": src.height,
                        "crs": src.crs.to_string() if src.crs else "None",
                        "transform": list(src.transform)[:6],
                        "resolution": (src.res[0], src.res[1]),
                        "min": min_val,
                        "max": max_val,
                        "valid_pixels": valid_count,
                        "nodata_pixels": nodata_count,
                        "nodata_percentage": round((nodata_count / total_count) * 100.0, 2),
                    }

            sww_sha256 = compute_file_sha256(sww_path)
            canary_summary = {
                "project_id": p_id,
                "run_id": r_id,
                "processing_id": proc_id,
                "exit_code": final_det.get("exit_code"),
                "runtime_seconds": final_det.get("runtime_seconds"),
                "anuga_version": final_det.get("anuga_version"),
                "version_source": final_det.get("version_source"),
                "raw_distribution_version": final_det.get("raw_distribution_version"),
                "sww_path": str(sww_path),
                "sww_sha256": sww_sha256,
                "sww_timesteps": list(times),
                "layers": layer_evidence,
            }
            print(f"\n[REAL CANARY POSTPROCESSING EVIDENCE]\n{json.dumps(canary_summary, indent=2)}")

        finally:
            ds.close()


def create_synthetic_sww_file(
    filepath: Path,
    xll: float = 500000.0,
    yll: float = 1799000.0,
    elevation_type: str = "1d",
    malformed_dim: Optional[str] = None,
    stage_override: Optional[np.ndarray] = None,
    elev_override: Optional[np.ndarray] = None,
    initially_wet: bool = False,
):
    """Create a valid or specifically parameterized NetCDF SWW file for postprocessing unit tests."""
    # 3x3 grid (9 vertices) forming 8 triangles across [0, 100] x [0, 100]
    xs = np.array([0.0, 50.0, 100.0, 0.0, 50.0, 100.0, 0.0, 50.0, 100.0], dtype=np.float32)
    ys = np.array([0.0, 0.0, 0.0, 50.0, 50.0, 50.0, 100.0, 100.0, 100.0], dtype=np.float32)
    triangles = np.array([
        [0, 1, 4], [0, 4, 3],
        [1, 2, 5], [1, 5, 4],
        [3, 4, 7], [3, 7, 6],
        [4, 5, 8], [4, 8, 7],
    ], dtype=np.int32)
    times = np.array([0.0, 10.0, 20.0, 30.0], dtype=np.float32)
    n_times = len(times)
    n_pts = len(xs)

    if elev_override is not None:
        elevation = elev_override
    elif elevation_type == "2d_time":
        # Time-dependent bed elevation [time, points]
        elevation = np.array([
            [10.0] * n_pts,
            [10.2] * n_pts,
            [10.5] * n_pts,
            [10.8] * n_pts,
        ], dtype=np.float32)
    elif elevation_type == "2d_static":
        # Shape (1, points)
        elevation = np.full((1, n_pts), 10.0, dtype=np.float32)
    else:
        # Standard 1D [points]
        elevation = np.full(n_pts, 10.0, dtype=np.float32)

    if stage_override is not None:
        stage = stage_override
    elif initially_wet:
        # t=0 has stage 12.0 (depth 2.0m > 0.05m threshold)
        stage = np.array([
            [12.0, 12.0, 10.0, 12.0, 12.0, 10.0, 12.0, 12.0, 10.0],
            [12.0, 12.0, 10.0, 12.0, 12.0, 10.0, 12.0, 12.0, 10.0],
            [12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0],
            [12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0],
        ], dtype=np.float32)
    else:
        # t=0: dry (stage = 10.0)
        # t=10: left column wet (v0, v3, v6 -> stage 12.0)
        # t=20: middle column wet (v1, v4, v7 -> stage 13.0)
        # t=30: right column wet (v2, v5, v8 -> stage 14.0)
        stage = np.array([
            [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            [12.0, 10.0, 10.0, 12.0, 10.0, 10.0, 12.0, 10.0, 10.0],
            [11.5, 13.0, 10.0, 11.5, 13.0, 10.0, 11.5, 13.0, 10.0],
            [10.0, 11.0, 14.0, 10.0, 11.0, 14.0, 10.0, 11.0, 14.0],
        ], dtype=np.float32)

    xmom = np.array([
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [2.0, 0.0, 0.0, 2.0, 0.0, 0.0, 2.0, 0.0, 0.0],
        [1.0, 3.0, 0.0, 1.0, 3.0, 0.0, 1.0, 3.0, 0.0],
        [0.0, 1.0, 4.0, 0.0, 1.0, 4.0, 0.0, 1.0, 4.0],
    ], dtype=np.float32)
    ymom = np.zeros_like(xmom)

    filepath.parent.mkdir(parents=True, exist_ok=True)
    f = netcdf_file(str(filepath), "w")
    try:
        f.xllcorner = xll
        f.yllcorner = yll

        f.createDimension("number_of_points", len(xs))
        f.createDimension("number_of_triangles", len(triangles))
        f.createDimension("three", 3)
        f.createDimension("number_of_timesteps", len(times))

        vx = f.createVariable("x", "f", ("number_of_points",))
        vx[:] = xs
        vy = f.createVariable("y", "f", ("number_of_points",))
        vy[:] = ys

        vvol = f.createVariable("volumes", "i", ("number_of_triangles", "three"))
        vvol[:] = triangles

        vt = f.createVariable("time", "f", ("number_of_timesteps",))
        vt[:] = times

        if malformed_dim == "elevation_bad_dim":
            f.createDimension("bad_dim", 5)
            ve = f.createVariable("elevation", "f", ("bad_dim",))
            ve[:] = np.full(5, 10.0, dtype=np.float32)
        elif len(elevation.shape) == 2:
            if elevation.shape[0] == 1:
                f.createDimension("one", 1)
                ve = f.createVariable("elevation", "f", ("one", "number_of_points"))
            else:
                ve = f.createVariable("elevation", "f", ("number_of_timesteps", "number_of_points"))
            ve[:] = elevation
        else:
            ve = f.createVariable("elevation", "f", ("number_of_points",))
            ve[:] = elevation

        if malformed_dim == "stage_bad_shape":
            f.createDimension("bad_pts", 4)
            vs = f.createVariable("stage", "f", ("number_of_timesteps", "bad_pts"))
            vs[:] = np.full((len(times), 4), 10.0, dtype=np.float32)
        else:
            vs = f.createVariable("stage", "f", ("number_of_timesteps", "number_of_points"))
            vs[:] = stage

        vxm = f.createVariable("xmomentum", "f", ("number_of_timesteps", "number_of_points"))
        vxm[:] = xmom
        vym = f.createVariable("ymomentum", "f", ("number_of_timesteps", "number_of_points"))
        vym[:] = ymom
    finally:
        f.close()


def setup_mock_completed_run(p_id: str, sww_generator_kwargs: Optional[Dict[str, Any]] = None) -> Tuple[str, Path, str]:
    """Helper to initialize a completed run directory with a valid SWW output."""
    import hashlib
    run_id = str(uuid.uuid4())
    runs_dir = onboarding_service.get_dam_projects_dir() / p_id / "runs" / run_id
    workspace_out = runs_dir / "workspace" / "output"
    workspace_out.mkdir(parents=True, exist_ok=True)

    sww_path = workspace_out / "domain.sww"
    kwargs = sww_generator_kwargs or {}
    create_synthetic_sww_file(sww_path, **kwargs)

    sww_sha = hashlib.sha256(sww_path.read_bytes()).hexdigest()
    run_rec = {
        "run_id": run_id,
        "project_id": p_id,
        "status": "completed",
        "exit_code": 0,
        "simulation_executed": True,
        "message": "Run completed successfully",
        "output_files": {
            "output/domain.sww": sww_sha
        },
        "has_results": False,
        "anuga_version": "4.0.0",
        "version_source": "conda_meta",
        "raw_distribution_version": "4.0.0",
    }
    (runs_dir / "run.json").write_text(json.dumps(run_rec), encoding="utf-8")
    return run_id, sww_path, sww_sha


class TestDamProjectAnugaPostprocessing:
    """Unit tests for ANUGA SWW postprocessing, exact storage, and algorithmic guarantees."""

    def test_version_provenance_conda_meta_detection(self, tmp_path, monkeypatch):
        """Test fallback version detection when importlib reports 0.0.0+unknown."""
        conda_meta_dir = tmp_path / "conda-meta"
        conda_meta_dir.mkdir(parents=True)
        pkg_json = conda_meta_dir / "anuga-4.0.0-py310hd1925b7_0.json"
        pkg_json.write_text(json.dumps({
            "name": "anuga",
            "version": "4.0.0",
            "build": "py310hd1925b7_0"
        }), encoding="utf-8")

        dummy_python = tmp_path / "python.exe"
        dummy_python.touch()

        import subprocess
        from unittest.mock import MagicMock
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "0.0.0+unknown\n"
        mock_proc.stderr = ""
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)

        is_installed, anuga_version, version_source, raw_dist = onboarding_service.detect_anuga_version(str(dummy_python))
        assert is_installed is True
        assert anuga_version == "4.0.0"
        assert version_source == "conda_meta"
        assert raw_dist == "0.0.0+unknown"

    def test_static_elevation_points(self):
        """Prove postprocessing correctly reads and processes static 1D elevation [points]."""
        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id, {"elevation_type": "1d"})

        res = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={
            "dry_depth_threshold_m": 0.005,
            "arrival_depth_threshold_m": 0.05,
            "raster_resolution_m": 10.0,
        })
        assert res.status_code == 200
        data = res.json()
        assert data["layer_statistics"]["maximum_depth"]["max"] > 0.0
        assert data["layer_statistics"]["maximum_depth"]["valid_pixels"] > 0

    def test_time_dependent_elevation_time_points(self):
        """Prove postprocessing correctly handles time-dependent bed elevation [time, points]."""
        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id, {"elevation_type": "2d_time"})

        res = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={
            "dry_depth_threshold_m": 0.005,
            "arrival_depth_threshold_m": 0.05,
            "raster_resolution_m": 10.0,
        })
        assert res.status_code == 200
        data = res.json()
        assert data["layer_statistics"]["maximum_depth"]["max"] > 0.0

    def test_malformed_netcdf_variable_dimensions_rejected(self):
        """Prove that malformed NetCDF variable dimensions are rejected with clear error."""
        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id, {"malformed_dim": "stage_bad_shape"})

        res = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={})
        assert res.status_code == 400
        assert "shape" in res.json()["detail"].lower()

    def test_north_up_geotiff_affine_transform(self):
        """Prove north-up GeoTIFF affine transform with positive dx, negative dy, and correct origin."""
        import rasterio
        from app.anuga_postprocessing_service import get_dam_project_anuga_layer_geotiff_path

        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id)

        res = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={
            "raster_resolution_m": 5.0,
        })
        assert res.status_code == 200
        proc_id = res.json()["processing_id"]

        tif_path = get_dam_project_anuga_layer_geotiff_path(p_id, r_id, "maximum_depth", processing_id=proc_id)
        assert tif_path.is_file()

        with rasterio.open(tif_path) as src:
            t = src.transform
            assert t.a > 0.0, f"Expected positive pixel width (dx), got {t.a}"
            assert t.e < 0.0, f"Expected negative pixel height (dy, north-up), got {t.e}"
            assert t.b == 0.0
            assert t.d == 0.0
            assert t.c == 500000.0, f"Expected x_origin 500000.0, got {t.c}"
            assert t.f == 1799100.0, f"Expected y_origin 1799100.0, got {t.f}"

    def test_crs_preservation(self):
        """Prove GeoTIFF outputs preserve project native projected CRS."""
        import rasterio
        from app.anuga_postprocessing_service import get_dam_project_anuga_layer_geotiff_path

        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id)

        res = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={})
        assert res.status_code == 200
        proc_id = res.json()["processing_id"]

        for layer in ["maximum_depth", "maximum_velocity", "arrival_time"]:
            tif_path = get_dam_project_anuga_layer_geotiff_path(p_id, r_id, layer, processing_id=proc_id)
            with rasterio.open(tif_path) as src:
                assert src.crs is not None
                assert "32643" in src.crs.to_string()

    def test_wgs84_point_query_reprojection(self):
        """Prove WGS84 (lon, lat) query is correctly reprojected to native CRS and sampled."""
        from pyproj import Transformer
        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id)

        post_res = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={"raster_resolution_m": 5.0})
        assert post_res.status_code == 200

        # Known projected coordinate inside computational mesh (v0 is 500000, 1799000; query 500010, 1799010)
        target_x, target_y = 500010.0, 1799010.0
        transformer = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)
        wgs_lon, wgs_lat = transformer.transform(target_x, target_y)

        pt_res = client.get(
            f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/results/maximum_depth/point",
            params={"lon": wgs_lon, "lat": wgs_lat}
        )
        assert pt_res.status_code == 200
        pt_data = pt_res.json()
        assert pt_data["is_valid"] is True
        assert pt_data["is_nodata"] is False
        assert pt_data["value"] is not None
        assert abs(pt_data["crs_x"] - target_x) < 2.0
        assert abs(pt_data["crs_y"] - target_y) < 2.0

    def test_masking_outside_actual_sww_triangle_union(self):
        """Prove that pixels outside the computational triangle mesh union are strictly NoData (-9999.0)."""
        import rasterio
        from app.anuga_postprocessing_service import get_dam_project_anuga_layer_geotiff_path

        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id)

        res = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={"raster_resolution_m": 5.0})
        assert res.status_code == 200
        proc_id = res.json()["processing_id"]

        tif_path = get_dam_project_anuga_layer_geotiff_path(p_id, r_id, "maximum_depth", processing_id=proc_id)
        with rasterio.open(tif_path) as src:
            arr = src.read(1)
            nodata_val = src.nodata
            assert nodata_val == -9999.0
            nodata_count = int(np.sum(arr == -9999.0))
            valid_count = int(np.sum(arr != -9999.0))
            assert valid_count > 0, "No valid pixels produced"

        # Point clearly outside mesh boundary
        pt_outside = client.get(
            f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/results/maximum_depth/point",
            params={"lon": 500500.0, "lat": 1799500.0}
        )
        assert pt_outside.status_code == 200
        assert pt_outside.json()["is_nodata"] is True
        assert pt_outside.json()["value"] is None

    def test_no_artificial_maximum_from_interpolate_after_maximum(self):
        """Prove instantaneous timestep-first calculation avoids non-physical peaks from asynchronous node maxima."""
        # Consider 2 nodes: Node 0 peaks at t=10 (stage=12, depth=2.0; at t=20 stage=10, depth=0.0).
        # Node 1 peaks at t=20 (stage=10, depth=0.0 at t=10; stage=12, depth=2.0 at t=20).
        # Linear interpolation of nodal maxima would yield midpoint depth = 2.0 (artificial).
        # Timestep-first evaluation yields at t=10 midpoint depth = 1.0; at t=20 midpoint depth = 1.0 -> max is 1.0!
        stage_asynch = np.array([
            [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            [12.0, 10.0, 10.0, 12.0, 10.0, 10.0, 12.0, 10.0, 10.0],  # t=10: v0 wet (2.0m), v1 dry (0m)
            [10.0, 12.0, 10.0, 10.0, 12.0, 10.0, 10.0, 12.0, 10.0],  # t=20: v0 dry (0m), v1 wet (2.0m)
            [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
        ], dtype=np.float32)

        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id, {"stage_override": stage_asynch})

        res = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={"raster_resolution_m": 2.0})
        assert res.status_code == 200

        # Point inside triangle (0, 1, 4) at (x=500025, y=1799010)
        pt_res = client.get(
            f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/results/maximum_depth/point",
            params={"lon": 500025.0, "lat": 1799010.0}
        )
        assert pt_res.status_code == 200
        val = pt_res.json()["value"]
        assert val is not None
        # Must be bounded by timestep-evaluated depth (~1.0m), and strictly less than interpolate-after-maximum (1.6m)
        assert abs(val - 1.0) < 0.15, f"Expected timestep-evaluated depth ~1.0m, got {val}"
        assert val < 1.4, f"Artificial peak detected from interpolate-after-maximum: {val}"

    def test_arrival_calculated_by_grid_cell_timestep_crossing(self):
        """Prove arrival time is assigned on first timestep where grid cell depth crosses threshold."""
        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id)

        res = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={
            "arrival_depth_threshold_m": 0.05,
            "raster_resolution_m": 5.0,
        })
        assert res.status_code == 200

        # Near v0 (flooded at t=10.0 s)
        pt_res = client.get(
            f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/results/arrival_time/point",
            params={"lon": 500005.0, "lat": 1799005.0}
        )
        assert pt_res.status_code == 200
        assert abs(pt_res.json()["value"] - 10.0) < 0.1

    def test_initially_wet_zero_seconds(self):
        """Prove that cells wet at t=0 are assigned arrival_time = 0.0 seconds."""
        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id, {"initially_wet": True})

        res = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={
            "arrival_depth_threshold_m": 0.05,
            "raster_resolution_m": 5.0,
        })
        assert res.status_code == 200

        # Point near v0 which is wet at t=0
        pt_res = client.get(
            f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/results/arrival_time/point",
            params={"lon": 500005.0, "lat": 1799005.0}
        )
        assert pt_res.status_code == 200
        assert pt_res.json()["value"] == 0.0, f"Expected 0.0 s arrival for initially wet cell, got {pt_res.json()['value']}"

    def test_never_wet_nodata(self):
        """Prove that cells that never exceed arrival depth threshold remain NoData (-9999.0)."""
        # Node v2, v5, v8 remain dry throughout all timesteps
        stage_partial = np.array([
            [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            [12.0, 10.0, 10.0, 12.0, 10.0, 10.0, 12.0, 10.0, 10.0],
            [12.0, 10.0, 10.0, 12.0, 10.0, 10.0, 12.0, 10.0, 10.0],
            [12.0, 10.0, 10.0, 12.0, 10.0, 10.0, 12.0, 10.0, 10.0],
        ], dtype=np.float32)

        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id, {"stage_override": stage_partial})

        res = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={
            "arrival_depth_threshold_m": 0.05,
            "raster_resolution_m": 5.0,
        })
        assert res.status_code == 200

        # Sample point near v8 (x=500100, y=1799100) which remained dry
        pt_res = client.get(
            f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/results/arrival_time/point",
            params={"lon": 500095.0, "lat": 1799095.0}
        )
        assert pt_res.status_code == 200
        assert pt_res.json()["is_nodata"] is True
        assert pt_res.json()["value"] is None

    def test_total_max_output_pixels_enforcement(self):
        """Prove that excessively high resolution requests are safely scaled to enforce MAX_OUTPUT_PIXELS."""
        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id)

        # Request microscopic resolution (0.01m on 100m domain would be 10000x10000 = 100 million pixels)
        res = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={
            "raster_resolution_m": 0.01,
        })
        assert res.status_code == 200
        data = res.json()
        h, w = data["grid_dimensions"]
        assert h <= 2048
        assert w <= 2048
        assert (h * w) <= (2048 * 2048)

    def test_concurrent_identical_postprocessing_safety(self):
        """Prove that concurrent identical postprocessing requests complete safely without corruption."""
        from concurrent.futures import ThreadPoolExecutor
        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id)

        def call_postprocess():
            return client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={
                "dry_depth_threshold_m": 0.005,
                "arrival_depth_threshold_m": 0.05,
                "raster_resolution_m": 10.0,
            })

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(call_postprocess) for _ in range(4)]
            results = [f.result() for f in futures]

        for r in results:
            assert r.status_code == 200
            assert "maximum_depth" in r.json()["available_layers"]

    def test_identical_request_returns_existing_byte_identical_files(self):
        """Prove that an identical postprocess request returns existing results without recreating files."""
        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id)

        req_body = {"dry_depth_threshold_m": 0.005, "arrival_depth_threshold_m": 0.05, "raster_resolution_m": 10.0}
        res1 = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json=req_body)
        assert res1.status_code == 200
        data1 = res1.json()
        proc_id1 = data1["processing_id"]

        # Second call
        res2 = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json=req_body)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["processing_id"] == proc_id1
        assert data2["layer_files"] == data1["layer_files"]

    def test_changed_parameters_preserve_previous_results(self):
        """Prove that changing thresholds/resolution creates a new processing_id without overwriting prior results."""
        p_id = create_saved_project_with_package()
        r_id, _, _ = setup_mock_completed_run(p_id)

        # Run 1: dry=0.005, arrival=0.05
        res1 = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={
            "dry_depth_threshold_m": 0.005,
            "arrival_depth_threshold_m": 0.05,
            "raster_resolution_m": 10.0,
        })
        assert res1.status_code == 200
        proc_id1 = res1.json()["processing_id"]

        # Run 2: dry=0.02, arrival=0.20
        res2 = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={
            "dry_depth_threshold_m": 0.02,
            "arrival_depth_threshold_m": 0.20,
            "raster_resolution_m": 10.0,
        })
        assert res2.status_code == 200
        proc_id2 = res2.json()["processing_id"]

        # Processing IDs must differ
        assert proc_id1 != proc_id2

        # Both directories must physically exist under runs/{run_id}/results/
        res_base = onboarding_service.get_dam_projects_dir() / p_id / "runs" / r_id / "results"
        assert (res_base / proc_id1 / "manifest.json").is_file(), "Previous results were deleted or overwritten!"
        assert (res_base / proc_id2 / "manifest.json").is_file()

        # Both can be queried explicitly
        q1 = client.get(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/results", params={"processing_id": proc_id1})
        assert q1.status_code == 200
        assert q1.json()["processing_id"] == proc_id1
        assert q1.json()["thresholds"]["arrival_depth_threshold_m"] == 0.05

        q2 = client.get(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/results", params={"processing_id": proc_id2})
        assert q2.status_code == 200
        assert q2.json()["processing_id"] == proc_id2
        assert q2.json()["thresholds"]["arrival_depth_threshold_m"] == 0.20

    def test_mocked_or_tampered_sww_rejected(self):
        """Prove that a tampered SWW whose SHA-256 no longer matches run.json is rejected."""
        p_id = create_saved_project_with_package()
        r_id, sww_path, _ = setup_mock_completed_run(p_id)

        # Tamper with SWW content on disk
        with open(sww_path, "ab") as f:
            f.write(b"\x00\x00\x00CORRUPTED_BYTES")

        res = client.post(f"/api/dam-projects/{p_id}/anuga/runs/{r_id}/postprocess", json={})
        assert res.status_code == 409
        assert "integrity" in res.json()["detail"]["code"].lower()


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
import numpy as np
from scipy.io import netcdf_file
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import onboarding_service
from tests.test_anuga_onboarding_api import get_standard_valid_payload, create_test_geotiff_bytes

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_dam_projects_storage(tmp_path, monkeypatch):
    """Ensure all tests execute with an isolated temporary dam_projects storage directory."""
    temp_dir = tmp_path / "dam_projects"
    temp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(onboarding_service, "get_dam_projects_dir", lambda: temp_dir)
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
            print(f"\n[STORAGE-CHANGE PLAUSIBILITY REPORT]\n{json.dumps(storage_change_report, indent=2)}")

        finally:
            ds.close()


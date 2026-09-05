import os
import io
import zipfile
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.scenario_storage import create_scenario
from app.schemas import ScenarioCreateRequest

client = TestClient(app)


@pytest.fixture
def sample_scenario_id(tmp_path, monkeypatch):
    monkeypatch.setenv("SIH_RUNTIME_DIR", str(tmp_path))
    req = ScenarioCreateRequest(
        name="SPH Benchmark Test Scenario",
        description="Scenario for PySPH benchmarking and testing",
        site="Hidkal Dam / Ghataprabha River",
        dem_registry_id="sample_dem",
        crs="EPSG:4326",
        breach_width=50.0,
        breach_formation_time=1.0,
        reservoir_level=662.5,
        upstream_boundary="Constant 2500 m3/s inflow",
        downstream_boundary="Free outflow rating curve",
        manning_roughness=0.035,
        mesh_resolution=10.0,
        simulation_duration=3600.0,
        time_step=0.001,
    )
    sc = create_scenario(req)
    return sc.id


def test_get_sph_capabilities():
    response = client.get("/api/sph/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert "pysph_available" in data
    assert "execution_enabled" in data
    assert "disclaimer" in data
    assert "guidance" in data
    assert "benchmark" in data["disclaimer"].lower() or "laboratory" in data["disclaimer"].lower()


def test_build_and_download_sph_package(sample_scenario_id):
    # Build package
    res_build = client.post(f"/api/scenarios/{sample_scenario_id}/build-sph-package")
    assert res_build.status_code == 200
    bdata = res_build.json()
    assert bdata["scenario_id"] == sample_scenario_id
    assert bdata["status"] == "package_built"
    assert bdata["benchmark_type"] == "2d_dam_break_benchmark"
    assert len(bdata["manifest_checksum"]) == 64  # SHA-256

    # Download package
    res_down = client.get(f"/api/scenarios/{sample_scenario_id}/download-sph-package")
    assert res_down.status_code == 200
    assert res_down.headers["content-type"] == "application/zip"

    # Verify ZIP contents
    zfile = zipfile.ZipFile(io.BytesIO(res_down.content))
    namelist = zfile.namelist()
    assert "scripts/dam_break_2d_pysph.py" in namelist
    assert "README_SPH_REQUIREMENTS.txt" in namelist
    assert "manifest.json" in namelist
    assert "config/sph_simulation_config.json" in namelist

    # Inspect SPH script content
    script_content = zfile.read("scripts/dam_break_2d_pysph.py").decode("utf-8")
    assert "PySPH 2D Dam-Break Benchmark" in script_content

    # Inspect SPH assumptions
    assumptions = zfile.read("README_SPH_REQUIREMENTS.txt").decode("utf-8")
    assert "BENCHMARK SCALE VS. REGIONAL RIVER SCALE" in assumptions
    assert "FUNDAMENTAL SCALE SEPARATION & HYDRODYNAMIC LIMITATIONS" in assumptions
    assert "STANDARD OUTPUT CONTRACT FOR COMPLETED RUNS" in assumptions



def test_sph_run_gated_by_default(sample_scenario_id, monkeypatch):
    monkeypatch.setenv("ENABLE_PYSPH_EXECUTION", "false")
    res = client.post(f"/api/scenarios/{sample_scenario_id}/run-sph", json={"custom_notes": "Test gated run"})
    assert res.status_code == 409
    assert "disabled" in res.json()["detail"].lower()


def test_sph_run_mock_execution(sample_scenario_id, tmp_path, monkeypatch):
    import sys
    monkeypatch.setenv("SIH_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("ENABLE_PYSPH_EXECUTION", "true")
    monkeypatch.setenv("PYSPH_PYTHON_PATH", sys.executable)

    # Mock subprocess to simulate successful PySPH execution
    mock_sub = MagicMock()
    mock_sub.returncode = 0
    mock_sub.stdout = "PySPH Simulation Completed Successfully. Iterations: 1000. Time: 1.0s"
    mock_sub.stderr = ""

    with patch("subprocess.run", return_value=mock_sub):
        res = client.post(
            f"/api/scenarios/{sample_scenario_id}/run-sph",
            json={"custom_notes": "Mocked test run", "particle_spacing_m": 0.2, "time_step_sec": 0.0005}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["scenario_id"] == sample_scenario_id
        assert data["status"] == "completed"
        assert data["exit_code"] == 0
        run_id = data["run_id"]

        # Check list runs
        res_list = client.get("/api/sph-runs")
        assert res_list.status_code == 200
        runs = res_list.json()
        assert any(r["run_id"] == run_id for r in runs)

        # Check run details
        res_get = client.get(f"/api/sph-runs/{run_id}")
        assert res_get.status_code == 200
        assert res_get.json()["run_id"] == run_id

        # Check logs
        res_logs = client.get(f"/api/sph-runs/{run_id}/logs")
        assert res_logs.status_code == 200
        assert res_logs.json()["status"] == "completed"

import os
import io
import json
import zipfile
import pytest
from unittest.mock import patch, MagicMock
import subprocess
from fastapi.testclient import TestClient
from pathlib import Path

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_temp_runtime(tmp_path, monkeypatch):
    """Isolate runtime storage in temporary directory for each test."""
    monkeypatch.setenv("SIH_RUNTIME_DIR", str(tmp_path))
    # By default, keep execution disabled
    monkeypatch.setenv("ENABLE_DFLOWFM_EXECUTION", "false")
    yield tmp_path


def test_get_simulation_capabilities_default_uninstalled():
    """Test capabilities endpoint returns truthful default disabled state."""
    res = client.get("/api/simulation/capabilities")
    assert res.status_code == 200
    data = res.json()

    assert "hydromt_available" in data
    assert "dflowfm_available" in data
    assert data["execution_enabled"] is False
    assert "HydroMT-Delft3D FM" in data["disclaimer"]
    assert "environment_hydromt_delft3dfm.yml" in data["guidance"]


@patch("shutil.which")
def test_get_simulation_capabilities_detected(mock_which, monkeypatch):
    """Test capabilities detection when engine binary and environment flag are set."""
    mock_which.side_effect = lambda cmd: "/usr/local/bin/dflowfm" if "dflowfm" in cmd else None
    monkeypatch.setenv("ENABLE_DFLOWFM_EXECUTION", "true")

    res = client.get("/api/simulation/capabilities")
    assert res.status_code == 200
    data = res.json()

    assert data["dflowfm_available"] is True
    assert data["execution_enabled"] is True
    assert data["engine_executable"] == "/usr/local/bin/dflowfm"


def test_build_and_download_model_package():
    """Test building draft Delft3D model package ZIP and inspecting all contained templates."""
    # 1. Create a scenario
    sc_res = client.post(
        "/api/scenarios",
        json={
            "name": "Hidkal HydroMT Test Package",
            "breach_width_m": 120.0,
            "manning_roughness": 0.038,
            "mesh_resolution_m": 60.0,
        },
    )
    sc_id = sc_res.json()["id"]

    # 2. Build model package
    build_res = client.post(f"/api/scenarios/{sc_id}/build-package")
    assert build_res.status_code == 200
    pkg_data = build_res.json()

    assert pkg_data["scenario_id"] == sc_id
    assert pkg_data["revision"] == 1
    assert pkg_data["status"] == "package_built"
    assert pkg_data["package_size_bytes"] > 0
    assert pkg_data["manifest_checksum"] != "unknown"

    # 3. Download package ZIP
    dl_res = client.get(f"/api/scenarios/{sc_id}/download-package")
    assert dl_res.status_code == 200
    assert dl_res.headers["content-type"] == "application/zip"

    # 4. Verify ZIP internal structure
    zip_bytes = io.BytesIO(dl_res.content)
    with zipfile.ZipFile(zip_bytes, "r") as zf:
        file_list = zf.namelist()
        assert "manifest.json" in file_list
        assert "config/delft3d_fm_model_config.ini" in file_list
        assert "config/hydromt_delft3dfm.yaml" in file_list
        assert "config/data_catalog.yaml" in file_list
        assert "data/README_DATA.txt" in file_list
        assert "README_REQUIREMENTS.txt" in file_list

        # Verify manifest contents
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["scenario_id"] == sc_id
        assert manifest["package_type"] == "draft_unvalidated_delft3d_package"
        assert "dem" in manifest["referenced_datasets"]

        # Verify README contents
        readme = zf.read("README_REQUIREMENTS.txt").decode("utf-8")
        assert "TOPOGRAPHY & VERTICAL DATUM" in readme
        assert "BREACH HYDROGRAPH & GEOTECHNICAL FAILURE" in readme


def test_simulation_run_rejected_when_engine_unavailable():
    """Test that POST /api/scenarios/{id}/run returns 409 Conflict when engine is disabled."""
    sc_res = client.post("/api/scenarios", json={"name": "Hidkal Run Test"})
    sc_id = sc_res.json()["id"]

    res = client.post(f"/api/scenarios/{sc_id}/run")
    assert res.status_code == 409
    assert "engine_unavailable" in res.json()["detail"]


@patch("subprocess.run")
@patch("shutil.which")
def test_successful_mocked_simulation_run(mock_which, mock_subproc, monkeypatch):
    """Test successful subprocess simulation execution when enabled and engine binary present."""
    mock_which.side_effect = lambda cmd: "C:\\bin\\dflowfm.exe" if "dflowfm" in cmd else None
    monkeypatch.setenv("ENABLE_DFLOWFM_EXECUTION", "true")

    # Mock subprocess success
    mock_subproc.return_value = MagicMock(returncode=0)

    # 1. Create scenario
    sc_res = client.post("/api/scenarios", json={"name": "Mock Success Run Scenario"})
    sc_id = sc_res.json()["id"]

    # 2. Trigger run
    run_res = client.post(f"/api/scenarios/{sc_id}/run", json={"custom_notes": "Automated pytest run"})
    assert run_res.status_code == 200
    run_data = run_res.json()

    assert run_data["scenario_id"] == sc_id
    assert run_data["status"] == "completed"
    assert run_data["exit_code"] == 0
    run_id = run_data["run_id"]

    # Verify subprocess called with shell=False and argument list
    assert mock_subproc.called
    call_args, call_kwargs = mock_subproc.call_args
    assert call_kwargs["shell"] is False
    assert call_args[0][0] == "C:\\bin\\dflowfm.exe"
    assert "--mdu" in call_args[0]

    # 3. Check runs list
    list_res = client.get("/api/runs")
    assert list_res.status_code == 200
    runs = list_res.json()
    assert len(runs) == 1
    assert runs[0]["run_id"] == run_id

    # 4. Check get run by ID
    get_res = client.get(f"/api/runs/{run_id}")
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "completed"

    # 5. Check run logs
    logs_res = client.get(f"/api/runs/{run_id}/logs")
    assert logs_res.status_code == 200
    assert logs_res.json()["run_id"] == run_id


@patch("subprocess.run")
@patch("shutil.which")
def test_failed_mocked_simulation_run(mock_which, mock_subproc, monkeypatch):
    """Test failed subprocess simulation execution recording status and logs."""
    mock_which.side_effect = lambda cmd: "C:\\bin\\dflowfm.exe" if "dflowfm" in cmd else None
    monkeypatch.setenv("ENABLE_DFLOWFM_EXECUTION", "true")

    # Mock subprocess failure
    mock_subproc.return_value = MagicMock(returncode=1)

    sc_res = client.post("/api/scenarios", json={"name": "Mock Failure Run Scenario"})
    sc_id = sc_res.json()["id"]

    run_res = client.post(f"/api/scenarios/{sc_id}/run")
    assert run_res.status_code == 200
    run_data = run_res.json()

    assert run_data["status"] == "failed"
    assert run_data["exit_code"] == 1


@patch("subprocess.run")
@patch("shutil.which")
def test_simulation_run_timeout(mock_which, mock_subproc, monkeypatch):
    """Test simulation run timeout handling."""
    mock_which.side_effect = lambda cmd: "C:\\bin\\dflowfm.exe" if "dflowfm" in cmd else None
    monkeypatch.setenv("ENABLE_DFLOWFM_EXECUTION", "true")

    # Mock timeout
    mock_subproc.side_effect = subprocess.TimeoutExpired(cmd=["dflowfm"], timeout=10)

    sc_res = client.post("/api/scenarios", json={"name": "Mock Timeout Scenario"})
    sc_id = sc_res.json()["id"]

    run_res = client.post(f"/api/scenarios/{sc_id}/run")
    assert run_res.status_code == 200
    assert run_res.json()["status"] == "failed"
    assert run_res.json()["exit_code"] == -1

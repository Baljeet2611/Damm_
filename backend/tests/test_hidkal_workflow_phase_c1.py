"""Phase C1: End-to-End Hidkal PS-161 Workflow Tests.

Verifies:
1. Creation / loading of canonical Hidkal scenario
2. Attachment of multi-engine availability with honest Delft3D local solver status
3. Canonical simulation results attachment
4. Comparison readiness and status integration
5. Exposure, damage, and HADR decision-support attachment
6. GIS export endpoints and GEE satellite validation status attachment
7. Graceful degradation when optional subsystems have no historical runs
8. REST API endpoint: GET /api/dam-projects/{project_id}/workflow-summary
"""

import json
import shutil
import uuid
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import HidkalWorkflowSummaryResponse, CanonicalScenario
from app.hidkal_workflow_service import (
    get_or_create_hidkal_canonical_scenario,
    get_hidkal_workflow_summary,
)
from app.onboarding_service import get_dam_projects_dir


@pytest.fixture
def test_client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def test_hidkal_project_id() -> Generator[str, None, None]:
    """Create isolated test Hidkal dam project on disk."""
    pid = str(uuid.uuid4())
    p_dir = get_dam_projects_dir() / pid
    p_dir.mkdir(parents=True, exist_ok=True)
    proj_json = p_dir / "project.json"
    proj_json.write_text(json.dumps({
        "id": pid,
        "name": "Raja Lakhamagouda (Hidkal) Dam",
        "dam_height_m": 62.48,
        "crest_length_m": 4818.0,
        "normal_reservoir_level_m": 662.94,
        "tailwater_level_m": 600.0,
        "status": "onboarded_validated",
        "user_provided_metadata": {
            "geometry_crs": "EPSG:32643",
        },
    }), encoding="utf-8")

    yield pid

    if p_dir.is_dir():
        shutil.rmtree(p_dir, ignore_errors=True)


def test_01_hidkal_canonical_scenario_creation(test_hidkal_project_id: str):
    """Test standard canonical scenario generation for Hidkal Dam."""
    pid = test_hidkal_project_id
    scenario: CanonicalScenario = get_or_create_hidkal_canonical_scenario(pid)

    assert scenario.project_id == pid
    assert "Hidkal" in scenario.scenario_name
    assert scenario.dam_crest_elevation_m == 662.94
    assert scenario.initial_water_level_m == 662.94
    assert scenario.breach_width_m == 120.0
    assert scenario.breach_depth_m == 35.0
    assert scenario.simulation_duration_s == 14400.0
    assert scenario.selected_engine.value in ["ANUGA", "anuga"]
    assert scenario.provenance["dam_height_m"] == 62.48
    assert scenario.provenance["crest_length_m"] == 4818.0


def test_02_workflow_summary_truthful_engines(test_hidkal_project_id: str):
    """Test engine status audit in workflow summary (Delft3D must report solver_unavailable)."""
    pid = test_hidkal_project_id
    summary: HidkalWorkflowSummaryResponse = get_hidkal_workflow_summary(pid)

    assert summary.project_id == pid
    assert summary.project_name == "Raja Lakhamagouda (Hidkal) Dam"
    assert "delft3d_fm" in summary.available_engines
    assert "anuga" in summary.available_engines
    assert "pysph" in summary.available_engines

    # Delft3D solver must be truthfully reported as solver_unavailable
    d3d = summary.available_engines["delft3d_fm"]
    assert d3d.solver_status == "solver_unavailable"
    assert d3d.package_generation_ready is True
    assert d3d.result_ingestion_ready is True
    assert "dflowfm" in d3d.reason.lower()


def test_03_workflow_summary_with_mocked_results(test_hidkal_project_id: str):
    """Test workflow summary with multi-engine simulation runs attached."""
    pid = test_hidkal_project_id
    p_dir = get_dam_projects_dir() / pid

    # 1. Mock ANUGA run
    anuga_run_dir = p_dir / "runs" / "anuga_hidkal_001"
    anuga_run_dir.mkdir(parents=True, exist_ok=True)
    (anuga_run_dir / "run.json").write_text(json.dumps({
        "run_id": "anuga_hidkal_001",
        "project_id": pid,
        "engine": "anuga",
        "status": "completed",
        "duration_seconds": 14400.0,
        "layer_stats": {
            "maximum_depth": {"max": 12.5, "mean": 4.2, "flooded_area_km2": 18.5},
            "maximum_velocity": {"max": 14.8},
            "arrival_time": {"min": 240.0, "max": 14400.0},
        },
    }), encoding="utf-8")
    (anuga_run_dir / "maximum_depth.tif").write_bytes(b"MOCK_TIF")

    # 2. Mock PySPH run
    sph_run_dir = p_dir / "sph" / "runs" / "sph_hidkal_001"
    sph_run_dir.mkdir(parents=True, exist_ok=True)
    (sph_run_dir / "run.json").write_text(json.dumps({
        "run_id": "sph_hidkal_001",
        "project_id": pid,
        "engine": "pysph",
        "status": "completed",
        "summary": {"max_depth_m": 15.2, "max_velocity_ms": 22.0, "flooded_area_km2": 0.8},
        "hydrograph": {"q_peak_cms": 8500.0, "time_to_peak_seconds": 25.0},
    }), encoding="utf-8")
    (sph_run_dir / "maximum_depth.tif").write_bytes(b"MOCK_TIF")

    # 3. Mock Exposure run
    exp_run_dir = p_dir / "exposure_runs" / "exp_hidkal_001"
    exp_run_dir.mkdir(parents=True, exist_ok=True)
    (exp_run_dir / "exposure_manifest.json").write_text(json.dumps({
        "run_id": "exp_hidkal_001",
        "created_at": "2026-09-22T00:00:00Z",
        "population": {"total_exposed_population": 42500},
        "buildings": {"total_exposed_buildings": 8300},
        "roads": {"total_flooded_length_km": 145.2},
        "critical_infrastructure": {"total_critical_assets_exposed": 12},
    }), encoding="utf-8")

    summary: HidkalWorkflowSummaryResponse = get_hidkal_workflow_summary(pid)

    assert summary.latest_canonical_results["anuga"] is not None
    assert summary.latest_canonical_results["anuga"].maximum_depth_m == 12.5
    assert summary.latest_canonical_results["pysph"] is not None
    assert summary.latest_canonical_results["pysph"].maximum_depth_m == 15.2

    # Exposure attached
    assert summary.exposure_summary is not None
    assert summary.exposure_summary["total_exposed_population"] == 42500
    assert summary.exposure_summary["critical_facilities_exposed"] == 12

    # GIS export links attached
    assert "assets_geojson" in summary.gis_export.endpoints
    assert "roads_geojson" in summary.gis_export.endpoints
    assert "assets_shapefile_zip" in summary.gis_export.endpoints

    # GEE status attached
    assert summary.gee_validation.tasks_enabled is False
    assert "COPERNICUS/S1_GRD" in summary.gee_validation.whitelisted_datasets


def test_04_graceful_degradation_empty_project(test_hidkal_project_id: str):
    """Test workflow summary handles an empty project without crashing."""
    pid = test_hidkal_project_id
    summary: HidkalWorkflowSummaryResponse = get_hidkal_workflow_summary(pid)

    assert summary.scenario is not None
    assert summary.latest_canonical_results["anuga"] is None
    assert summary.latest_canonical_results["pysph"] is None
    assert summary.latest_canonical_results["delft3d_fm"] is None
    assert summary.exposure_summary is None
    assert summary.damage_summary is not None
    assert len(summary.provenance_warnings) > 0


def test_05_rest_api_workflow_summary(test_client: TestClient, test_hidkal_project_id: str):
    """Test GET /api/dam-projects/{project_id}/workflow-summary REST endpoint."""
    pid = test_hidkal_project_id

    response = test_client.get(f"/api/dam-projects/{pid}/workflow-summary")
    assert response.status_code == 200
    data = response.json()

    assert data["project_id"] == pid
    assert data["scenario"]["project_id"] == pid
    assert data["available_engines"]["delft3d_fm"]["solver_status"] == "solver_unavailable"
    assert "gis_export" in data
    assert "gee_validation" in data
    assert "provenance_warnings" in data

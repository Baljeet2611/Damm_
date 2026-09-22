"""Phase B3: Canonical Multi-Engine Simulation Result Contract Tests.

Verifies:
1. PySPH result translation to CanonicalSimulationResult
2. Delft3D FM result translation to CanonicalSimulationResult
3. ANUGA result translation to CanonicalSimulationResult
4. Strict preservation of missing optional fields as None/null
5. Provenance correctness for all three hydrodynamic engines
6. Multi-engine comparison compatibility
7. REST API endpoints for canonical result retrieval
"""

import json
import shutil
import uuid
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import CanonicalSimulationResult
from app.unified_result_service import (
    pysph_result_to_canonical,
    delft3d_result_to_canonical,
    anuga_result_to_canonical,
    get_canonical_simulation_result,
    list_canonical_simulation_results,
)
from app.onboarding_service import get_dam_projects_dir


@pytest.fixture
def test_client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def test_project_id() -> Generator[str, None, None]:
    """Create isolated test dam project on disk for testing with valid UUID v4."""
    pid = str(uuid.uuid4())
    p_dir = get_dam_projects_dir() / pid
    p_dir.mkdir(parents=True, exist_ok=True)
    proj_json = p_dir / "project.json"
    proj_json.write_text(json.dumps({
        "id": pid,
        "name": "Phase B3 Test Dam",
        "dam_height_m": 65.0,
        "crest_length_m": 280.0,
        "normal_reservoir_level_m": 650.0,
        "tailwater_level_m": 590.0,
    }), encoding="utf-8")

    yield pid

    if p_dir.is_dir():
        shutil.rmtree(p_dir, ignore_errors=True)


def test_01_pysph_result_to_canonical():
    """Verify PySPH dictionary/manifest maps to canonical contract."""
    raw_sph = {
        "run_id": "sph_run_20260921_abc123",
        "project_id": "proj_demo_1",
        "engine": "pysph",
        "status": "completed",
        "scientific_status": "sph_numerical_simulation",
        "created_at": "2026-09-21T10:00:00Z",
        "duration_seconds": 120.0,
        "max_depth_m": 8.45,
        "max_velocity_ms": 14.2,
        "flooded_area_km2": 0.35,
        "hydrograph": {
            "q_peak_cms": 3450.0,
            "time_to_peak_seconds": 18.5,
            "total_released_volume_m3": 1250000.0,
        },
        "native_crs": "EPSG:32643",
        "bounds": [500000.0, 1700000.0, 502000.0, 1702000.0],
        "source_files": ["sph_particles.npz", "sph_hydrograph.json"],
    }

    res: CanonicalSimulationResult = pysph_result_to_canonical(raw_sph)

    assert res.run_id == "sph_run_20260921_abc123"
    assert res.project_id == "proj_demo_1"
    assert res.engine == "pysph"
    assert res.execution_status == "completed"
    assert res.maximum_depth_m == 8.45
    assert res.maximum_velocity_ms == 14.2
    assert res.flood_extent_km2 == 0.35
    assert res.hydrograph is not None
    assert res.hydrograph["q_peak_cms"] == 3450.0
    # Arrival time is not computed in near-field SPH and must be None
    assert res.arrival_time_min_s is None
    assert res.provenance["source_engine"] == "pysph"


def test_02_delft3d_result_to_canonical():
    """Verify Delft3D FM UGRID/GeoTIFF run maps to canonical contract."""
    raw_d3d = {
        "run_id": "d3d-ugrid-20260921_def456",
        "project_id": "proj_demo_1",
        "engine": "delft3d_fm",
        "status": "completed",
        "scientific_status": "genuine_ugrid_netcdf_ingested",
        "created_at": "2026-09-21T11:00:00Z",
        "summary": {
            "max_depth_m": 6.82,
            "max_velocity_ms": 7.95,
            "flooded_area_km2": 4.12,
            "mean_depth_m": 2.15,
        },
        "native_crs": "EPSG:32643",
        "bounds": [500000.0, 1700000.0, 510000.0, 1715000.0],
        "timestamps": [0.0, 3600.0, 7200.0, 10800.0],
        "source_files": ["DFM_OUTPUT_ghataprabha_map.nc", "maximum_depth.tif", "maximum_velocity.tif"],
        "provenance": {
            "import_mode": "ugrid_netcdf",
            "conventions": "UGRID-1.0",
        },
    }

    res: CanonicalSimulationResult = delft3d_result_to_canonical(raw_d3d)

    assert res.run_id == "d3d-ugrid-20260921_def456"
    assert res.engine == "delft3d_fm"
    assert res.execution_status == "completed"
    assert res.maximum_depth_m == 6.82
    assert res.maximum_velocity_ms == 7.95
    assert res.flood_extent_km2 == 4.12
    assert res.mean_depth_m == 2.15
    assert len(res.timestamps) == 4
    assert res.provenance["source_engine"] == "delft3d_fm"
    assert res.provenance["import_mode"] == "ugrid_netcdf"


def test_03_anuga_result_to_canonical():
    """Verify ANUGA run maps to canonical contract with arrival times and layer stats."""
    raw_anuga = {
        "run_id": "anuga-run-20260921_ghi789",
        "project_id": "proj_demo_1",
        "engine": "anuga",
        "status": "completed",
        "scientific_status": "validated_anuga_simulation",
        "created_at": "2026-09-21T12:00:00Z",
        "duration_seconds": 14400.0,
        "timestamps": [0.0, 60.0, 120.0, 180.0],
        "layer_stats": {
            "maximum_depth": {
                "max": 9.12,
                "mean": 3.45,
                "flooded_area_km2": 5.85,
            },
            "maximum_velocity": {
                "max": 11.3,
            },
            "arrival_time": {
                "min": 180.0,
                "max": 14400.0,
            },
        },
        "native_crs": "EPSG:32643",
        "bounds": [500000.0, 1700000.0, 515000.0, 1720000.0],
    }

    res: CanonicalSimulationResult = anuga_result_to_canonical(raw_anuga)

    assert res.run_id == "anuga-run-20260921_ghi789"
    assert res.engine == "anuga"
    assert res.maximum_depth_m == 9.12
    assert res.maximum_velocity_ms == 11.3
    assert res.flood_extent_km2 == 5.85
    assert res.mean_depth_m == 3.45
    assert res.arrival_time_min_s == 180.0
    assert res.provenance["source_engine"] == "anuga"


def test_04_preservation_of_missing_fields():
    """Verify missing metrics remain None and are never fabricated."""
    empty_sph = {
        "run_id": "sph_incomplete_1",
        "engine": "pysph",
        "status": "completed",
        "created_at": "2026-09-21T00:00:00Z",
    }
    res_sph = pysph_result_to_canonical(empty_sph)
    assert res_sph.maximum_depth_m is None
    assert res_sph.maximum_velocity_ms is None
    assert res_sph.flood_extent_km2 is None
    assert res_sph.arrival_time_min_s is None
    assert res_sph.hydrograph is None

    empty_d3d = {
        "run_id": "d3d_incomplete_1",
        "engine": "delft3d_fm",
        "status": "failed",
        "created_at": "2026-09-21T00:00:00Z",
    }
    res_d3d = delft3d_result_to_canonical(empty_d3d)
    assert res_d3d.execution_status == "failed"
    assert res_d3d.maximum_depth_m is None
    assert res_d3d.maximum_velocity_ms is None


def test_05_disk_ingestion_and_multi_engine_listing(test_project_id: str):
    """Test retrieving all canonical runs across PySPH, Delft3D, and ANUGA for a dam project."""
    pid = test_project_id
    p_dir = get_dam_projects_dir() / pid

    # 1. Mock PySPH run on disk
    sph_run_dir = p_dir / "sph" / "runs" / "sph_001"
    sph_run_dir.mkdir(parents=True, exist_ok=True)
    (sph_run_dir / "run.json").write_text(json.dumps({
        "run_id": "sph_001",
        "project_id": pid,
        "engine": "pysph",
        "status": "completed",
        "summary": {"max_depth_m": 5.5, "max_velocity_ms": 10.0, "flooded_area_km2": 0.2},
    }), encoding="utf-8")
    (sph_run_dir / "maximum_depth.tif").write_bytes(b"MOCK_TIF_DATA")

    # 2. Mock Delft3D run on disk
    d3d_run_dir = p_dir / "delft3d" / "runs" / "d3d_001"
    d3d_run_dir.mkdir(parents=True, exist_ok=True)
    (d3d_run_dir / "run.json").write_text(json.dumps({
        "run_id": "d3d_001",
        "project_id": pid,
        "engine": "delft3d_fm",
        "status": "completed",
        "summary": {"max_depth_m": 4.8, "max_velocity_ms": 6.5, "flooded_area_km2": 3.5},
    }), encoding="utf-8")
    (d3d_run_dir / "maximum_depth.tif").write_bytes(b"MOCK_TIF_DATA")

    # 3. Mock ANUGA run on disk
    anuga_run_dir = p_dir / "runs" / "anuga_001"
    anuga_run_dir.mkdir(parents=True, exist_ok=True)
    (anuga_run_dir / "run.json").write_text(json.dumps({
        "run_id": "anuga_001",
        "project_id": pid,
        "engine": "anuga",
        "status": "completed",
        "layer_stats": {"maximum_depth": {"max": 7.2, "mean": 2.8, "flooded_area_km2": 4.2}},
    }), encoding="utf-8")
    (anuga_run_dir / "maximum_depth.tif").write_bytes(b"MOCK_TIF_DATA")

    # List all canonical results
    all_results = list_canonical_simulation_results(pid)
    assert len(all_results) == 3

    engines = {r.engine for r in all_results}
    assert engines == {"pysph", "delft3d_fm", "anuga"}

    # Individual retrieval
    sph_res = get_canonical_simulation_result(pid, "pysph", "sph_001")
    assert sph_res.maximum_depth_m == 5.5

    d3d_res = get_canonical_simulation_result(pid, "delft3d_fm", "d3d_001")
    assert d3d_res.maximum_depth_m == 4.8

    anuga_res = get_canonical_simulation_result(pid, "anuga", "anuga_001")
    assert anuga_res.maximum_depth_m == 7.2


def test_06_rest_api_canonical_results(test_client: TestClient, test_project_id: str):
    """Test REST API endpoints for canonical results."""
    pid = test_project_id
    p_dir = get_dam_projects_dir() / pid

    # Create mock run
    anuga_run_dir = p_dir / "runs" / "anuga_api_test"
    anuga_run_dir.mkdir(parents=True, exist_ok=True)
    (anuga_run_dir / "run.json").write_text(json.dumps({
        "run_id": "anuga_api_test",
        "project_id": pid,
        "engine": "anuga",
        "status": "completed",
        "layer_stats": {"maximum_depth": {"max": 8.0, "mean": 3.0, "flooded_area_km2": 5.0}},
    }), encoding="utf-8")
    (anuga_run_dir / "maximum_depth.tif").write_bytes(b"MOCK_TIF_DATA")

    # 1. GET /api/dam-projects/{project_id}/canonical-results
    resp_list = test_client.get(f"/api/dam-projects/{pid}/canonical-results")
    assert resp_list.status_code == 200
    items = resp_list.json()
    assert len(items) >= 1
    assert items[0]["engine"] == "anuga"
    assert items[0]["maximum_depth_m"] == 8.0

    # 2. GET /api/dam-projects/{project_id}/canonical-results/{engine}/{run_id}
    resp_single = test_client.get(f"/api/dam-projects/{pid}/canonical-results/anuga/anuga_api_test")
    assert resp_single.status_code == 200
    data = resp_single.json()
    assert data["result"]["run_id"] == "anuga_api_test"
    assert data["result"]["maximum_depth_m"] == 8.0
    assert data["is_comparable"] is True

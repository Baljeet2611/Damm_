import os
import json
import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_temp_runtime(tmp_path, monkeypatch):
    """Isolate runtime storage in temporary directory for each test."""
    monkeypatch.setenv("SIH_RUNTIME_DIR", str(tmp_path))
    yield tmp_path


def test_create_scenario():
    """Test scenario creation with automatic UUID v4, assumptions, and validation notes."""
    payload = {
        "name": "Hidkal Sunny Day Breach - High Sensitivity",
        "description": "Baseline simulation scenario for Hidkal dam overtopping.",
        "site": "Hidkal Dam, Belagavi, Karnataka",
        "dem_dataset_id": "dem",
        "crs": "EPSG:4326",
        "breach_width_m": 150.0,
        "breach_formation_time_hr": 1.5,
        "assumed_reservoir_level_m": 662.5,
        "upstream_boundary_desc": "Hydrograph inflow peak 5000 m3/s",
        "downstream_boundary_desc": "Normal depth outflow slope 0.001",
        "manning_roughness": 0.04,
        "mesh_resolution_m": 45.0,
        "simulation_duration_hr": 36.0,
        "timestep_sec": 0.5,
    }

    res = client.post("/api/scenarios", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert "id" in data
    assert len(data["id"]) == 36  # Valid UUID length
    assert data["name"] == payload["name"]
    assert data["revision"] == 1
    assert data["archived"] is False
    assert data["status"] == "input_review_required"
    assert len(data["validation_notes"]) > 0
    assert data["snapshot_checksum"] is not None
    assert len(data["snapshot_checksum"]) == 64  # SHA-256 hex length
    assert len(data["assumptions"]) == 6


def test_list_and_get_scenario():
    """Test listing scenarios and fetching by UUID."""
    # Create two scenarios
    res1 = client.post("/api/scenarios", json={"name": "Scenario Alpha"})
    assert res1.status_code == 200
    id1 = res1.json()["id"]

    res2 = client.post("/api/scenarios", json={"name": "Scenario Beta"})
    assert res2.status_code == 200
    id2 = res2.json()["id"]

    # List all
    res_list = client.get("/api/scenarios")
    assert res_list.status_code == 200
    scenarios = res_list.json()
    assert len(scenarios) == 2
    ids = [s["id"] for s in scenarios]
    assert id1 in ids
    assert id2 in ids

    # Get specific scenario
    res_get = client.get(f"/api/scenarios/{id1}")
    assert res_get.status_code == 200
    assert res_get.json()["name"] == "Scenario Alpha"


def test_update_scenario_increments_revision():
    """Test updating scenario fields and verifying revision increments."""
    res_create = client.post("/api/scenarios", json={"name": "Original Name", "breach_width_m": 100.0})
    sc_id = res_create.json()["id"]
    orig_updated_at = res_create.json()["updated_at"]

    update_payload = {
        "name": "Updated Scenario Name",
        "breach_width_m": 250.0,
        "manning_roughness": 0.05,
    }
    res_update = client.put(f"/api/scenarios/{sc_id}", json=update_payload)
    assert res_update.status_code == 200
    data = res_update.json()

    assert data["name"] == "Updated Scenario Name"
    assert data["breach_width_m"] == 250.0
    assert data["manning_roughness"] == 0.05
    assert data["revision"] == 2
    assert data["id"] == sc_id


def test_clone_scenario():
    """Test cloning creates an independent copy with new UUID and revision 1."""
    res_create = client.post("/api/scenarios", json={"name": "Source Scenario", "breach_width_m": 120.0})
    orig_id = res_create.json()["id"]

    res_clone = client.post(f"/api/scenarios/{orig_id}/clone")
    assert res_clone.status_code == 200
    clone_data = res_clone.json()

    assert clone_data["id"] != orig_id
    assert clone_data["name"] == "Clone of Source Scenario"
    assert clone_data["breach_width_m"] == 120.0
    assert clone_data["revision"] == 1
    assert clone_data["archived"] is False


def test_archive_and_unarchive_scenario():
    """Test archiving soft-hides scenario without permanent deletion."""
    res_create = client.post("/api/scenarios", json={"name": "To Archive"})
    sc_id = res_create.json()["id"]

    # Archive
    res_arch = client.post(f"/api/scenarios/{sc_id}/archive")
    assert res_arch.status_code == 200
    assert res_arch.json()["archived"] is True

    # Check default list excludes archived
    res_list_active = client.get("/api/scenarios")
    assert len(res_list_active.json()) == 0

    # Check include_archived=True returns it
    res_list_all = client.get("/api/scenarios?include_archived=true")
    assert len(res_list_all.json()) == 1
    assert res_list_all.json()[0]["id"] == sc_id

    # Unarchive
    res_unarch = client.post(f"/api/scenarios/{sc_id}/unarchive")
    assert res_unarch.status_code == 200
    assert res_unarch.json()["archived"] is False


def test_uuid_validation_and_traversal_rejection():
    """Test that invalid IDs and path traversal strings are rejected."""
    for bad_id in ["not-a-uuid", "12345", "invalid_id_format"]:
        res = client.get(f"/api/scenarios/{bad_id}")
        assert res.status_code == 422
        assert "Invalid scenario ID format" in res.json()["detail"]

    for bad_path in ["../etc/passwd", "../../scenarios/foo"]:
        res = client.get(f"/api/scenarios/{bad_path}")
        assert res.status_code in (404, 422)


def test_get_nonexistent_valid_uuid_returns_404():
    """Test that a valid UUID that does not exist returns 404."""
    import uuid
    dummy_uuid = str(uuid.uuid4())
    res = client.get(f"/api/scenarios/{dummy_uuid}")
    assert res.status_code == 404
    assert "not found in runtime storage" in res.json()["detail"]

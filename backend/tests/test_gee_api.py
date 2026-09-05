import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_gee_capabilities():
    response = client.get("/api/gee/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert "gee_available" in data
    assert "authenticated" in data
    assert "tasks_enabled" in data
    assert "whitelisted_collections" in data
    assert len(data["whitelisted_collections"]) == 3
    assert "COPERNICUS/S1_GRD" in data["whitelisted_collections"]
    assert "NASA/GPM_L3/IMERG_V07" in data["whitelisted_collections"]
    assert "JRC/GSW1_4/GlobalSurfaceWater" in data["whitelisted_collections"]
    assert "disclaimer" in data


def test_gee_list_and_get_datasets():
    # List
    response = client.get("/api/gee/datasets")
    assert response.status_code == 200
    datasets = response.json()
    assert len(datasets) == 3
    ids = [d["id"] for d in datasets]
    assert "COPERNICUS/S1_GRD" in ids

    # Get specific
    res_s1 = client.get("/api/gee/datasets/COPERNICUS/S1_GRD")
    assert res_s1.status_code == 200
    s1_data = res_s1.json()
    assert s1_data["title"] == "Sentinel-1 SAR GRD (Ground Range Detected)"
    assert "VV" in s1_data["bands"]
    assert "candidate water-change" in s1_data["disclaimer"].lower()

    # Get invalid
    res_inv = client.get("/api/gee/datasets/INVALID/DATASET_ID")
    assert res_inv.status_code == 404


def test_gee_export_plan_valid():
    payload = {
        "dataset_id": "COPERNICUS/S1_GRD",
        "start_date": "2024-07-01",
        "end_date": "2024-07-15",
        "roi_min_lon": 74.65,
        "roi_min_lat": 16.15,
        "roi_max_lon": 74.85,
        "roi_max_lat": 16.30,
        "target_scale_meters": 20.0,
        "max_pixels": 10000000
    }
    response = client.post("/api/gee/export-plan", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["dataset_id"] == "COPERNICUS/S1_GRD"
    assert data["candidate_observation_label"] == "candidate_water_change_observation"
    assert data["estimated_pixels"] > 0
    assert data["target_scale_meters"] == 20.0
    assert "EARTH OBSERVATION DISCLAIMER" in data["disclaimer"]
    assert data["cloud_task_submitted"] is False  # Gated by default


def test_gee_export_plan_validation_errors():
    # Invalid dataset
    payload_bad_ds = {
        "dataset_id": "UNAUTHORIZED/DATASET",
        "start_date": "2024-07-01",
        "end_date": "2024-07-15"
    }
    res1 = client.post("/api/gee/export-plan", json=payload_bad_ds)
    assert res1.status_code == 400
    assert "whitelist" in res1.json()["detail"].lower()

    # Invalid dates
    payload_bad_dates = {
        "dataset_id": "COPERNICUS/S1_GRD",
        "start_date": "2024-08-15",
        "end_date": "2024-07-01"
    }
    res2 = client.post("/api/gee/export-plan", json=payload_bad_dates)
    assert res2.status_code == 400
    assert "precede" in res2.json()["detail"].lower()

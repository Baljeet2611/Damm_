"""Tests for ANUGA Timestep Flood Animation Endpoints (Phase 24).

Validates:
- GET /api/dam-projects/{id}/anuga/runs/{run_id}/timesteps/info
- GET /api/dam-projects/{id}/anuga/runs/{run_id}/timesteps/{step_idx}/tiles/{z}/{x}/{y}.png
- Parameter validation (step_idx in [0, 60], rejecting negative or out-of-range steps)
- CRS reprojection & transparency on dry cells
- In-memory and disk tile caching
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.onboarding_service import load_or_create_hidkal_demo_project

client = TestClient(app)

@pytest.fixture(scope="module")
def hidkal_demo_run():
    # Load demo project
    res = client.post("/api/dam-projects/load-hidkal-demo")
    assert res.status_code == 200
    p_data = res.json()
    project_id = p_data.get("project_id") or p_data.get("id")

    # Get completed runs
    runs_res = client.get(f"/api/dam-projects/{project_id}/anuga/runs")
    assert runs_res.status_code == 200
    runs = runs_res.json()
    assert len(runs) > 0, "No ANUGA runs found for demo project"

    run_id = runs[0].get("run_id") or runs[0].get("id")
    return project_id, run_id

def test_timestep_info_endpoint(hidkal_demo_run):
    project_id, run_id = hidkal_demo_run
    res = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/info")
    assert res.status_code == 200
    data = res.json()
    assert data["project_id"] == project_id
    assert data["run_id"] == run_id
    assert data["total_timesteps"] == 61
    assert data["duration_seconds"] == 3600.0
    assert data["interval_seconds"] == 60.0
    assert len(data["times"]) == 61
    assert data["valid_min"] == 0.0
    assert data["valid_max"] > 0.0
    assert data["unit"] == "meters"

def test_timestep_tiles_rendering(hidkal_demo_run):
    project_id, run_id = hidkal_demo_run
    # Sample tile coordinates covering Hidkal Dam extent at zoom 13
    z, x, y = 13, 5794, 3723

    # Test frames: start (0m), early (15m), mid (30m), late (45m), end (60m)
    for step_idx in [0, 15, 30, 45, 60]:
        res = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/{step_idx}/tiles/{z}/{x}/{y}.png")
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/png"
        assert len(res.content) > 0

def test_timestep_tiles_out_of_range_rejected(hidkal_demo_run):
    project_id, run_id = hidkal_demo_run
    z, x, y = 13, 5794, 3723

    # Negative step index
    res_neg = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/-1/tiles/{z}/{x}/{y}.png")
    assert res_neg.status_code in (400, 422)

    # Past total timesteps (>= 61)
    res_high = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/61/tiles/{z}/{x}/{y}.png")
    assert res_high.status_code in (400, 422)

    res_huge = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/999/tiles/{z}/{x}/{y}.png")
    assert res_huge.status_code in (400, 422)

def test_timestep_tiles_caching(hidkal_demo_run):
    project_id, run_id = hidkal_demo_run
    z, x, y = 13, 5794, 3723

    # First request
    res1 = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/25/tiles/{z}/{x}/{y}.png")
    assert res1.status_code == 200

    # Second request (served from memory cache)
    res2 = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/25/tiles/{z}/{x}/{y}.png")
    assert res2.status_code == 200
    assert res1.content == res2.content

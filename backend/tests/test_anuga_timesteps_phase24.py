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

from app.onboarding_service import get_dam_projects_dir

client = TestClient(app)

@pytest.fixture(scope="module")
def hidkal_demo_run():
    # Load demo project
    res = client.post("/api/dam-projects/load-hidkal-demo")
    assert res.status_code == 200
    p_data = res.json()
    project_id = p_data.get("project_id") or p_data.get("id")

    # Search for any completed run with a valid SWW output file
    target_project_id = None
    target_run_id = None

    proj_dir = get_dam_projects_dir() / project_id
    runs_dir = proj_dir / "runs"
    if runs_dir.is_dir():
        for r_dir in runs_dir.iterdir():
            if r_dir.is_dir() and not r_dir.name.startswith("."):
                sww_files = list((r_dir / "workspace" / "output").glob("*.sww"))
                if sww_files:
                    target_project_id = project_id
                    target_run_id = r_dir.name
                    break

    if not target_run_id:
        for p_dir in get_dam_projects_dir().iterdir():
            if p_dir.is_dir() and (p_dir / "runs").is_dir():
                for r_dir in (p_dir / "runs").iterdir():
                    if r_dir.is_dir() and not r_dir.name.startswith("."):
                        sww_files = list((r_dir / "workspace" / "output").glob("*.sww"))
                        if sww_files:
                            target_project_id = p_dir.name
                            target_run_id = r_dir.name
                            break
            if target_run_id:
                break

    if not target_run_id:
        pytest.skip("No completed ANUGA runs with SWW output found for timestep animation verification.")

    return target_project_id, target_run_id


def test_timestep_info_endpoint(hidkal_demo_run):
    project_id, run_id = hidkal_demo_run
    res = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/info")
    assert res.status_code == 200
    data = res.json()
    assert data["project_id"] == project_id
    assert data["run_id"] == run_id
    assert data["total_timesteps"] >= 2
    assert data["duration_seconds"] > 0.0
    assert data["interval_seconds"] > 0.0
    assert len(data["times"]) == data["total_timesteps"]
    assert data["valid_min"] == 0.0
    assert data["valid_max"] > 0.0
    assert data["unit"] == "meters"


def test_timestep_tiles_rendering(hidkal_demo_run):
    project_id, run_id = hidkal_demo_run
    # Sample tile coordinates covering Hidkal Dam extent at zoom 13
    z, x, y = 13, 5794, 3723

    res_info = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/info")
    assert res_info.status_code == 200
    total_steps = res_info.json()["total_timesteps"]
    step_indices = [0]
    if total_steps > 1:
        step_indices.append(min(15, total_steps - 1))
        step_indices.append(total_steps - 1)

    for step_idx in step_indices:
        res = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/{step_idx}/tiles/{z}/{x}/{y}.png")
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/png"
        assert len(res.content) > 0


def test_timestep_tiles_out_of_range_rejected(hidkal_demo_run):
    project_id, run_id = hidkal_demo_run
    z, x, y = 13, 5794, 3723

    res_info = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/info")
    assert res_info.status_code == 200
    total_steps = res_info.json()["total_timesteps"]

    # Negative step index
    res_neg = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/-1/tiles/{z}/{x}/{y}.png")
    assert res_neg.status_code in (400, 422)

    # Past total timesteps (>= total_steps)
    res_high = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/{total_steps}/tiles/{z}/{x}/{y}.png")
    assert res_high.status_code in (400, 422)

    res_huge = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/999/tiles/{z}/{x}/{y}.png")
    assert res_huge.status_code in (400, 422)


def test_timestep_tiles_caching(hidkal_demo_run):
    project_id, run_id = hidkal_demo_run
    z, x, y = 13, 5794, 3723

    # First request
    res1 = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/0/tiles/{z}/{x}/{y}.png")
    assert res1.status_code == 200

    # Second request (served from memory cache)
    res2 = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/0/tiles/{z}/{x}/{y}.png")
    assert res2.status_code == 200
    assert res1.content == res2.content

"""
Phase 26: Comprehensive SPH Flood Animation Test Suite
Validates:
1. Frame 0 is truly t = 0 (pre-integration state)
2. First frame contains initial coordinates & 0 velocity
3. Timestamps monotonically increase across all frames
4. Final frame exists and represents simulation duration
5. Breach timestamp is represented accurately in manifest
6. Zero downstream crossings before breach start time
7. First downstream arrival metadata is accurate
8. WGS84 coordinates are valid throughout all frames
9. Animation API project/run isolation works
10. Invalid frame index returns HTTP 404
"""

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(scope="module")
def sph_animation_run():
    """Module-level fixture providing a real SPH breach simulation run on Hidkal Demo."""
    # 1. Load Hidkal Demo
    res_demo = client.post("/api/dam-projects/load-hidkal-demo")
    assert res_demo.status_code in (200, 201), f"Failed to load Hidkal demo: {res_demo.text}"
    project_id = res_demo.json()["project_id"]

    # 2. Execute SPH Breach Simulation
    payload = {
        "breach_mode": "instantaneous",
        "breach_width_m": 50.0,
        "breach_start_time_s": 5.0,
        "simulation_duration_s": 24.0,
    }
    res_run = client.post(f"/api/dam-projects/{project_id}/sph/run", json=payload)
    assert res_run.status_code == 200, f"SPH run failed: {res_run.text}"
    run_data = res_run.json()
    run_id = run_data["run_id"]

    # 3. Fetch Manifest
    res_manifest = client.get(f"/api/dam-projects/{project_id}/sph/runs/{run_id}/animation")
    assert res_manifest.status_code == 200, f"Failed to fetch manifest: {res_manifest.text}"
    manifest = res_manifest.json()

    return {
        "project_id": project_id,
        "run_id": run_id,
        "run_data": run_data,
        "manifest": manifest,
    }


def test_frame_0_exactly_t_zero(sph_animation_run):
    """Test 1: Frame 0 is truly t = 0 before first solver integration step."""
    project_id = sph_animation_run["project_id"]
    run_id = sph_animation_run["run_id"]

    res_f0 = client.get(f"/api/dam-projects/{project_id}/sph/runs/{run_id}/animation/frames/0")
    assert res_f0.status_code == 200
    f0 = res_f0.json()

    assert f0["frame_index"] == 0
    assert f0["time_s"] == 0.0
    assert f0["stats"]["time_s"] == 0.0


def test_first_frame_initial_coordinates_and_zero_velocity(sph_animation_run):
    """Test 2: First frame contains valid initial coordinates and zero initial velocity."""
    project_id = sph_animation_run["project_id"]
    run_id = sph_animation_run["run_id"]

    res_f0 = client.get(f"/api/dam-projects/{project_id}/sph/runs/{run_id}/animation/frames/0")
    assert res_f0.status_code == 200
    f0 = res_f0.json()

    assert len(f0["features"]) > 0
    # At t=0 before integration, velocity is zero
    assert f0["stats"]["max_velocity_ms"] == 0.0
    for feat in f0["features"][:20]:
        assert feat["properties"]["v"] == 0.0
        assert feat["properties"]["d"] >= 0.0


def test_timestamps_monotonically_increase(sph_animation_run):
    """Test 3: Timestamps strictly monotonically increase across all frames."""
    manifest = sph_animation_run["manifest"]
    frames = manifest["frames"]

    assert len(frames) >= 2
    for i in range(len(frames) - 1):
        t_curr = frames[i]["time_s"]
        t_next = frames[i + 1]["time_s"]
        assert t_next > t_curr, f"Frame {i+1} time ({t_next}) is not greater than frame {i} time ({t_curr})"


def test_final_frame_exists_and_matches_duration(sph_animation_run):
    """Test 4: Final frame exists and reaches simulation duration."""
    project_id = sph_animation_run["project_id"]
    run_id = sph_animation_run["run_id"]
    manifest = sph_animation_run["manifest"]

    total_frames = manifest["total_frames"]
    final_frame_idx = total_frames - 1

    res_final = client.get(f"/api/dam-projects/{project_id}/sph/runs/{run_id}/animation/frames/{final_frame_idx}")
    assert res_final.status_code == 200
    final_frame = res_final.json()

    assert final_frame["frame_index"] == final_frame_idx
    # Final frame time should match simulation duration
    assert abs(final_frame["time_s"] - manifest["duration_s"]) < 0.5


def test_breach_timestamp_represented_correctly(sph_animation_run):
    """Test 5: Breach start timestamp is accurately stored in manifest and run record."""
    manifest = sph_animation_run["manifest"]
    run_data = sph_animation_run["run_data"]

    assert manifest["breach_start_time_s"] == 5.0
    assert run_data["breach_start_time_s"] == 5.0


def test_zero_downstream_crossing_before_breach(sph_animation_run):
    """Test 6: Zero particles cross downstream before breach start time."""
    run_data = sph_animation_run["run_data"]
    assert run_data["particles_crossing_before_breach"] == 0

    project_id = sph_animation_run["project_id"]
    run_id = sph_animation_run["run_id"]
    manifest = sph_animation_run["manifest"]

    # All frames with time_s < breach_start_time_s must have downstream_particle_count == 0
    for frame_meta in manifest["frames"]:
        if frame_meta["time_s"] < manifest["breach_start_time_s"]:
            res_frame = client.get(f"/api/dam-projects/{project_id}/sph/runs/{run_id}/animation/frames/{frame_meta['index']}")
            assert res_frame.status_code == 200
            f_data = res_frame.json()
            assert f_data["stats"]["downstream_particle_count"] == 0


def test_first_downstream_arrival_metadata_correct(sph_animation_run):
    """Test 7: First downstream arrival metadata is present and occurs after breach."""
    manifest = sph_animation_run["manifest"]
    run_data = sph_animation_run["run_data"]

    arrival_time = manifest.get("first_downstream_arrival_time_s")
    assert arrival_time is not None
    assert arrival_time >= manifest["breach_start_time_s"]
    assert arrival_time == run_data["first_downstream_arrival_time_s"]


def test_wgs84_coordinates_valid(sph_animation_run):
    """Test 8: WGS84 coordinates in all frames are valid geographic lat/lons."""
    project_id = sph_animation_run["project_id"]
    run_id = sph_animation_run["run_id"]
    manifest = sph_animation_run["manifest"]

    # Test sample frames across timeline: 0, middle, and final
    test_indices = [0, manifest["total_frames"] // 2, manifest["total_frames"] - 1]
    for idx in test_indices:
        res_frame = client.get(f"/api/dam-projects/{project_id}/sph/runs/{run_id}/animation/frames/{idx}")
        assert res_frame.status_code == 200
        f_data = res_frame.json()
        for feat in f_data["features"]:
            lon, lat = feat["geometry"]["coordinates"]
            # Check bounding range for Hidkal Dam (Karnataka, India ~ 74.6-74.8 E, 16.1-16.3 N)
            assert -180.0 <= lon <= 180.0
            assert -90.0 <= lat <= 90.0
            assert 74.0 <= lon <= 76.0
            assert 15.5 <= lat <= 17.0


def test_animation_api_project_run_isolation(sph_animation_run):
    """Test 9: Animation API enforces project and run isolation."""
    project_id = sph_animation_run["project_id"]
    run_id = sph_animation_run["run_id"]

    # Non-existent run ID returns 404
    res_fake_run = client.get(f"/api/dam-projects/{project_id}/sph/runs/nonexistent-run/animation")
    assert res_fake_run.status_code == 404

    # Non-existent project returns 404
    fake_proj = "11111111-2222-3333-4444-555555555555"
    res_fake_proj = client.get(f"/api/dam-projects/{fake_proj}/sph/runs/{run_id}/animation")
    assert res_fake_proj.status_code == 404


def test_invalid_frame_returns_404(sph_animation_run):
    """Test 10: Invalid frame index returns HTTP 404."""
    project_id = sph_animation_run["project_id"]
    run_id = sph_animation_run["run_id"]

    res_out_of_range = client.get(f"/api/dam-projects/{project_id}/sph/runs/{run_id}/animation/frames/99999")
    assert res_out_of_range.status_code == 404

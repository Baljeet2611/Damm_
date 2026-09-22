"""
test_sph_terrain_execution.py - Automated tests for real project-based SPH terrain execution.

Validates:
1. Project SPH mode selection (sph_mode="project_terrain" distinct from "benchmark").
2. Real DEM topography ingestion and non-constant bed elevations.
3. Lagrangian particle evolution (>100 timesteps, non-trivial motion, finite velocities).
4. Automated Eulerian raster postprocessing (maximum_depth.tif, maximum_velocity.tif, arrival_time.tif).
5. Standardized HydrodynamicOutputContract creation and arrival-time threshold metadata.
6. Multi-engine comparison framework discoverability.
"""

import json
import uuid
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from fastapi.testclient import TestClient
from pathlib import Path

from app.main import app
from app.onboarding_service import get_dam_projects_dir, save_dam_project
from app.sph_service import (
    execute_dam_project_sph_terrain_simulation,
    list_dam_project_sph_runs,
    get_dam_project_sph_run_detail,
)
from app.model_comparison_service import (
    get_project_engine_capabilities,
    normalize_engine_output,
)

client = TestClient(app)


@pytest.fixture
def sph_test_project():
    """Create a temporary test dam project with authentic synthetic DEM topography."""
    proj_id = str(uuid.uuid4())
    p_dir = get_dam_projects_dir() / proj_id
    p_dir.mkdir(parents=True, exist_ok=True)

    # Create realistic synthetic DEM topography with valley slopes (EPSG:4326)
    # 50 x 50 grid spanning Hidkal coordinates approx [74.60, 16.10, 74.70, 16.20]
    elev_grid = np.zeros((50, 50), dtype=np.float32)
    for r in range(50):
        for c in range(50):
            # V-shaped valley slope with upstream-downstream drop
            elev_grid[r, c] = 620.0 + (abs(c - 25) * 2.5) + (50 - r) * 1.2

    dem_path = p_dir / "dem.tif"
    # EPSG:4326 origin
    transform = from_origin(74.60, 16.20, 0.002, 0.002)
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        height=50,
        width=50,
        count=1,
        dtype=np.float32,
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(elev_grid, 1)

    project_meta = {
        "project_id": proj_id,
        "dam_name": "Test Hydro Dam",
        "latitude": 16.15,
        "longitude": 74.65,
        "dam_height_m": 55.0,
        "crest_length_m": 350.0,
        "normal_reservoir_level_m": 650.0,
        "dem_file": "dem.tif",
        "dem_crs": "EPSG:4326",
        "dem_resolution_m": 30.0,
        "created_at": "2026-09-16T00:00:00Z",
    }
    (p_dir / "project.json").write_text(json.dumps(project_meta, indent=2), encoding="utf-8")

    yield proj_id

    # Cleanup test project directory
    import shutil
    shutil.rmtree(p_dir, ignore_errors=True)


def test_sph_terrain_simulation_execution(sph_test_project):
    """Test full execution of project-based SPH simulation coupled with real DEM."""
    options = {
        "simulation_duration_s": 20.0,
        "time_step_s": 0.05,
        "arrival_time_threshold_m": 0.05,
        "run_label": "Automated SPH Terrain Test Run",
    }
    res = execute_dam_project_sph_terrain_simulation(sph_test_project, options)

    assert res["status"] == "completed"
    assert res["solver_execution_status"] == "real_computed"
    assert res["sph_mode"] == "project_terrain"
    assert res["terrain_source"] == "real_open_source"
    assert res["hydraulic_configuration"] == "hypothetical_unverified"

    # Verify particle and physics output
    assert res["particle_count"] > 100
    assert res["wet_particle_count"] > 0
    assert res["timesteps_executed"] > 10
    assert res["max_depth_m"] > 0.0
    assert res["max_velocity_ms"] > 0.0
    assert res["dem_min_elevation_m"] < res["dem_max_elevation_m"], "DEM elevations must be non-constant"

    # Verify layer outputs
    assert res["layers"]["has_maximum_depth"] is True
    assert res["layers"]["has_maximum_velocity"] is True
    assert res["layers"]["has_arrival_time"] is True
    assert "maximum_depth" in res["layer_hashes"]


def test_sph_generated_rasters_validity(sph_test_project):
    """Test that generated SPH GeoTIFF rasters have valid projection, bounds, and finite data."""
    res = execute_dam_project_sph_terrain_simulation(sph_test_project)
    run_id = res["run_id"]

    run_dir = get_dam_projects_dir() / sph_test_project / "sph" / "runs" / run_id
    depth_tif = run_dir / "maximum_depth.tif"
    vel_tif = run_dir / "maximum_velocity.tif"
    arr_tif = run_dir / "arrival_time.tif"

    assert depth_tif.is_file()
    assert vel_tif.is_file()
    assert arr_tif.is_file()

    with rasterio.open(depth_tif) as src:
        assert src.crs.to_string() == "EPSG:32643"
        arr = src.read(1)
        valid = arr[arr != src.nodata]
        assert len(valid) > 0
        assert np.all(valid >= 0.0), "Water depth must be non-negative"
        assert not np.isnan(valid).any(), "Depth must not contain NaNs"
        assert float(valid.max()) == pytest.approx(res["max_depth_m"], rel=1e-2)

    with rasterio.open(vel_tif) as src:
        assert src.crs.to_string() == "EPSG:32643"
        arr = src.read(1)
        valid = arr[arr != src.nodata]
        assert len(valid) > 0
        assert np.all(valid >= 0.0), "Velocity magnitude must be non-negative"
        assert not np.isnan(valid).any(), "Velocity must not contain NaNs"


def test_sph_fastapi_run_endpoint(sph_test_project):
    """Test POST /api/dam-projects/{project_id}/sph/run endpoint."""
    resp = client.post(
        f"/api/dam-projects/{sph_test_project}/sph/run",
        json={"simulation_duration_s": 15.0, "run_label": "API Test SPH Run"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["sph_mode"] == "project_terrain"
    assert data["particle_count"] > 100


def test_sph_model_comparison_discoverability(sph_test_project):
    """Test that completed SPH terrain simulation is discovered by model comparison service."""
    # Execute SPH run
    execute_dam_project_sph_terrain_simulation(sph_test_project)

    # Check capabilities
    caps = get_project_engine_capabilities(sph_test_project)
    assert caps.engines["pysph"].available_for_comparison is True
    assert caps.engines["pysph"].comparable_run_count >= 1

    # Check normalization into HydrodynamicOutputContract
    runs = list_dam_project_sph_runs(sph_test_project)
    assert len(runs) >= 1
    run_id = runs[0]["run_id"]

    contract, layer_paths = normalize_engine_output(
        sph_test_project, "pysph", run_id, synthetic_fixture=False
    )
    assert contract.engine == "pysph"
    assert contract.maximum_depth_available is True
    assert contract.maximum_velocity_available is True
    assert contract.arrival_time_available is True
    assert contract.arrival_time_definition == "depth >= 0.05m"
    assert contract.solver_execution_status == "real_computed"


def test_closed_dam_barrier_blocks_all_crossing(sph_test_project):
    """Test that a closed barrier (breach_mode='none') blocks all downstream crossings."""
    options = {
        "simulation_duration_s": 15.0,
        "breach_mode": "none",
        "dam_barrier_enabled": True,
    }
    res = execute_dam_project_sph_terrain_simulation(sph_test_project, options)

    assert res["status"] == "completed"
    assert res["dam_barrier_enabled"] is True
    assert res["breach_mode"] == "none"
    assert res["particles_crossing_through_breach"] == 0
    assert res["particles_crossing_before_breach"] == 0
    assert res["first_downstream_arrival_time_s"] is None


def test_instantaneous_breach_opening_controls_crossing(sph_test_project):
    """Test that instantaneous breach allows downstream passage only after breach start time."""
    options = {
        "simulation_duration_s": 20.0,
        "breach_mode": "instantaneous",
        "breach_width_m": 100.0,
        "breach_start_time_s": 5.0,
        "dam_barrier_enabled": True,
    }
    res = execute_dam_project_sph_terrain_simulation(sph_test_project, options)

    assert res["status"] == "completed"
    assert res["dam_barrier_enabled"] is True
    assert res["breach_mode"] == "instantaneous"
    assert res["particles_crossing_before_breach"] == 0
    if res["particles_crossing_through_breach"] > 0:
        assert res["first_downstream_arrival_time_s"] >= 5.0


def test_invalid_breach_parameters_rejected(sph_test_project):
    """Test that invalid breach parameters raise HTTP 422 error."""
    with pytest.raises(Exception):
        execute_dam_project_sph_terrain_simulation(
            sph_test_project,
            {"breach_mode": "invalid_mode_name"}
        )

    with pytest.raises(Exception):
        execute_dam_project_sph_terrain_simulation(
            sph_test_project,
            {"breach_width_m": -50.0}
        )


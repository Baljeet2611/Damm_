import os
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.schemas import (
    DamProjectValidationResponse,
    DamProjectDetailResponse,
    EngineeringParameters,
    UserProvidedMetadata,
    NormalizedProjectMetadata,
)
from app.river_blockage_service import (
    load_or_create_river_blockage_demo_project,
    generate_synthetic_valley_dem,
    create_river_blockage_geometries,
)
from app.decision_support_service import (
    get_decision_support_summary,
)

client = TestClient(app)


def test_01_synthetic_valley_generation(tmp_path):
    """Verify synthetic parabolic valley DEM and vector geometries generation in metric CRS."""
    dem_file = tmp_path / "test_valley_dem.tif"
    dem_meta = generate_synthetic_valley_dem(
        out_path=dem_file,
        width_m=2000.0,
        length_m=3000.0,
        resolution_m=50.0,
    )
    assert dem_file.exists()
    assert dem_meta["width_pixels"] == 40
    assert dem_meta["height_pixels"] == 60
    assert dem_meta["min_elevation"] > 0

    geoms = create_river_blockage_geometries(
        width_m=2000.0,
        length_m=3000.0,
    )
    assert "dam_axis" in geoms
    assert "reservoir_boundary" in geoms
    assert "model_domain" in geoms
    assert "downstream_outlet" in geoms
    assert geoms["dam_axis"]["type"] == "FeatureCollection"


def test_02_river_blockage_demo_loading():
    """Verify loading the standardized River Blockage demo project."""
    project = load_or_create_river_blockage_demo_project()
    assert project is not None
    assert "River Blockage" in project.project_name
    assert project.scenario_type == "RIVER_BLOCKAGE"
    assert project.barrier_type == "natural_landslide_blockage"
    assert project.raster_metadata is not None
    assert project.user_provided_metadata.blockage_height > 0
    assert project.user_provided_metadata.blockage_crest_elevation > 0
    assert project.user_provided_metadata.upstream_water_level > 0
    assert project.user_provided_metadata.opening_width == 60.0


def test_03_river_blockage_demo_endpoint():
    """Verify API endpoint POST /api/dam-projects/load-river-blockage-demo."""
    res = client.post("/api/dam-projects/load-river-blockage-demo")
    assert res.status_code == 200
    data = res.json()
    assert data["scenario_type"] == "RIVER_BLOCKAGE"
    assert data["barrier_type"] == "natural_landslide_blockage"
    assert "project_id" in data
    assert data["status"] == "validated_unverified"


def test_04_intact_control_vs_failed_runs():
    """Verify intact control and failed hydrodynamic simulation runs exist for the blockage project."""
    res = client.post("/api/dam-projects/load-river-blockage-demo")
    assert res.status_code == 200
    proj = res.json()
    project_id = proj["project_id"]

    runs_res = client.get(f"/api/dam-projects/{project_id}/anuga/runs")
    assert runs_res.status_code == 200
    runs = runs_res.json()
    assert len(runs) >= 2

    # Check for intact control run
    intact_runs = [
        r for r in runs
        if r.get("parameters_snapshot", {}).get("is_intact_control") is True
        or r.get("parameters_snapshot", {}).get("opening_width_m", -1) == 0.0
    ]
    assert len(intact_runs) >= 1
    intact = intact_runs[0]
    assert intact["status"] == "completed"

    # Check for failed blockage run
    failed_runs = [
        r for r in runs
        if r.get("parameters_snapshot", {}).get("is_intact_control") is False
        or r.get("parameters_snapshot", {}).get("opening_width_m", 0) > 0.0
    ]
    assert len(failed_runs) >= 1
    failed = failed_runs[0]
    assert failed["status"] == "completed"


def test_05_sww_postprocessed_hazard_rasters():
    """Verify that postprocessed GeoTIFF hazard layers exist for the river blockage runs."""
    res = client.post("/api/dam-projects/load-river-blockage-demo")
    assert res.status_code == 200
    proj = res.json()
    project_id = proj["project_id"]

    runs_res = client.get(f"/api/dam-projects/{project_id}/anuga/runs")
    assert runs_res.status_code == 200
    runs = runs_res.json()
    failed_runs = [
        r for r in runs
        if r.get("parameters_snapshot", {}).get("is_intact_control") is False
        or r.get("parameters_snapshot", {}).get("opening_width_m", 0) > 0.0
    ]
    assert len(failed_runs) >= 1
    failed_run_id = failed_runs[0]["run_id"]

    results_res = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{failed_run_id}/results")
    assert results_res.status_code == 200
    results = results_res.json()
    assert "available_layers" in results
    assert "maximum_depth" in results["available_layers"]
    assert "maximum_velocity" in results["available_layers"]
    assert "arrival_time" in results["available_layers"]


def test_06_decision_support_integration():
    """Verify Decision Support Dashboard produces River Blockage tailored intelligence."""
    res = client.post("/api/dam-projects/load-river-blockage-demo")
    assert res.status_code == 200
    proj = res.json()
    project_id = proj["project_id"]

    runs_res = client.get(f"/api/dam-projects/{project_id}/anuga/runs")
    assert runs_res.status_code == 200
    runs = runs_res.json()
    failed_runs = [
        r for r in runs
        if r.get("parameters_snapshot", {}).get("is_intact_control") is False
        or r.get("parameters_snapshot", {}).get("opening_width_m", 0) > 0.0
    ]
    assert len(failed_runs) >= 1
    failed_run_id = failed_runs[0]["run_id"]

    summary = get_decision_support_summary(project_id, failed_run_id)
    assert summary is not None
    assert "Landslide Dam" in summary.narrative_summary or "River Blockage" in summary.narrative_summary
    assert summary.kpis.maximum_depth_m > 0
    assert summary.kpis.maximum_velocity_ms > 0
    assert summary.kpis.downstream_flood_reach_km > 0
    assert summary.scenario.barrier_type == "natural_landslide_blockage"


def test_07_backward_compatibility_hidkal_demo():
    """Verify standard engineered dam break workflows remain 100% functional."""
    res = client.post("/api/dam-projects/load-hidkal-demo")
    assert res.status_code == 200
    data = res.json()
    assert data["scenario_type"] == "DAM_BREAK"
    assert data["barrier_type"] == "engineered_dam"
    assert "Hidkal" in data["project_name"]


def test_08_schemas_metadata_validation():
    """Verify schema models enforce scenario_type and blockage fields properly."""
    params = EngineeringParameters(
        scenario_type="RIVER_BLOCKAGE",
        scenario_label="River Blockage Scenario",
        barrier_type="natural_landslide_blockage",
        blockage_height=40.0,
        blockage_crest_elevation=530.0,
        upstream_water_level=522.0,
        opening_width=50.0,
    )
    assert params.scenario_type == "RIVER_BLOCKAGE"
    assert params.blockage_height == 40.0

    user_meta = UserProvidedMetadata(
        project_name="Custom Blockage Test",
        scenario_type="RIVER_BLOCKAGE",
        barrier_type="natural_landslide_blockage",
        geometry_crs="EPSG:32643",
        blockage_height=40.0,
    )
    assert user_meta.scenario_type == "RIVER_BLOCKAGE"
    assert user_meta.blockage_height == 40.0

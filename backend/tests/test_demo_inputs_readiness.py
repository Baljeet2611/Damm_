"""
Tests for PS-161 Hypothetical Demo Inputs & Simulation Readiness Pipeline.

Validates:
1. GeoJSON [longitude, latitude] coordinate order across all generated geometries.
2. Model domain strictly derived from and contained within DEM bounds (100% inside raster).
3. Reservoir boundary closed polygon contained within DEM and within model domain.
4. Dam crest axis LineString inside DEM, inside model domain, and intersecting reservoir.
5. Physical hydraulic consistency: crest elevation > reservoir level > breach invert >= 0.
6. 5-Tier Readiness transition from Incomplete to Complete.
7. Explicit unverified provenance tagging: provenance='HYPOTHETICAL_UNVERIFIED'.
"""

import io
import json
import math
import os
import uuid
import numpy as np
import pytest
import rasterio
from affine import Affine
from fastapi.testclient import TestClient
from shapely.geometry import box, shape, Polygon, LineString

from app.main import app
from app import onboarding_service
from app.schemas import DemoInputsRequest

client = TestClient(app)


def create_mock_hidkal_dem_bytes(
    width: int = 100,
    height: int = 100,
    min_lon: float = 74.55,
    max_lon: float = 74.77,
    min_lat: float = 16.05,
    max_lat: float = 16.25,
    base_elev: float = 659.0,
) -> bytes:
    """Creates an in-memory EPSG:4326 GeoTIFF matching the Hidkal demo extent."""
    buf = io.BytesIO()
    res_x = (max_lon - min_lon) / width
    res_y = (max_lat - min_lat) / height
    transform = Affine(res_x, 0.0, min_lon, 0.0, -res_y, max_lat)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": transform,
        "nodata": -9999.0,
    }
    # Sloping terrain towards Northeast (elev decreasing towards NE)
    data = np.zeros((height, width), dtype=np.float32)
    for r in range(height):
        for c in range(width):
            # Higher in SW, lower in NE
            data[r, c] = base_elev + (height - r) * 0.2 - c * 0.2

    with rasterio.open(buf, "w", **profile) as dst:
        dst.write(data, 1)

    return buf.getvalue()


@pytest.fixture
def registered_demo_project(tmp_path, monkeypatch):
    """Isolate project storage and register a clean Hidkal dam project."""
    temp_dir = tmp_path / "dam_projects"
    temp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(onboarding_service, "get_dam_projects_dir", lambda: temp_dir)

    dem_bytes = create_mock_hidkal_dem_bytes()
    files = {"dem_file": ("hidkal_dem.tif", dem_bytes, "image/tiff")}
    data = {
        "project_name": "Hidkal Demo Dam Study",
        "dam_name": "Hidkal Dam",
        "latitude": "16.215",
        "longitude": "74.632",
        "acknowledge_unverified_metadata": "true",
    }
    res = client.post("/api/dam-projects", files=files, data=data)
    assert res.status_code == 200, res.text
    return res.json()["project_id"]


def test_initial_readiness_is_missing_geometry_and_hydraulic(registered_demo_project):
    """Verify that prior to preparing demo inputs, Tier 2 and Tier 3 are incomplete."""
    res = client.get(f"/api/dam-projects/{registered_demo_project}/readiness")
    assert res.status_code == 200
    r = res.json()

    assert r["data_ready"] is True
    assert r["geometry_ready"] is False
    assert r["hydraulic_ready"] is False
    assert "Model domain computational mesh boundary not provided." in r["missing_requirements"]
    assert "Dam crest axis polyline not provided." in r["missing_requirements"]
    assert "Reservoir boundary polygon not provided." in r["missing_requirements"]
    assert "Dam structural height or crest elevation not specified." in r["missing_requirements"]
    assert "Normal pool / reservoir storage level not specified." in r["missing_requirements"]


def test_prepare_demo_inputs_geojson_lon_lat_coordinate_order(registered_demo_project):
    """Task Requirement: Verify GeoJSON coordinate order is strictly [longitude, latitude]."""
    res = client.post(f"/api/dam-projects/{registered_demo_project}/demo-inputs")
    assert res.status_code == 200, res.text
    data = res.json()

    # Load the persisted GeoJSON files
    proj_dir = onboarding_service.get_dam_projects_dir() / registered_demo_project
    axis_data = json.loads((proj_dir / "dam_axis.geojson").read_text(encoding="utf-8"))
    res_data = json.loads((proj_dir / "reservoir_boundary.geojson").read_text(encoding="utf-8"))
    dom_data = json.loads((proj_dir / "model_domain.geojson").read_text(encoding="utf-8"))
    out_data = json.loads((proj_dir / "downstream_outlet.geojson").read_text(encoding="utf-8"))

    # Inspect coordinates of each
    axis_coords = axis_data["features"][0]["geometry"]["coordinates"]
    for pt in axis_coords:
        lon, lat = pt[0], pt[1]
        assert 74.0 <= lon <= 75.0, f"Expected longitude near 74.6, got {lon}"
        assert 16.0 <= lat <= 17.0, f"Expected latitude near 16.2, got {lat}"

    res_coords = res_data["features"][0]["geometry"]["coordinates"][0]
    for pt in res_coords:
        lon, lat = pt[0], pt[1]
        assert 74.0 <= lon <= 75.0, f"Expected longitude near 74.6, got {lon}"
        assert 16.0 <= lat <= 17.0, f"Expected latitude near 16.2, got {lat}"

    dom_coords = dom_data["features"][0]["geometry"]["coordinates"][0]
    for pt in dom_coords:
        lon, lat = pt[0], pt[1]
        assert 74.0 <= lon <= 75.0, f"Expected longitude near 74.6, got {lon}"
        assert 16.0 <= lat <= 17.0, f"Expected latitude near 16.2, got {lat}"

    out_coords = out_data["features"][0]["geometry"]["coordinates"]
    for pt in out_coords:
        lon, lat = pt[0], pt[1]
        assert 74.0 <= lon <= 75.0, f"Expected longitude near 74.6, got {lon}"
        assert 16.0 <= lat <= 17.0, f"Expected latitude near 16.2, got {lat}"


def test_prepare_demo_inputs_geometries_strictly_contained_within_dem(registered_demo_project):
    """Task Requirement: Verify domain and reservoir are 100% inside DEM bounds and valid."""
    res = client.post(f"/api/dam-projects/{registered_demo_project}/demo-inputs")
    assert res.status_code == 200

    proj_dir = onboarding_service.get_dam_projects_dir() / registered_demo_project
    with rasterio.open(proj_dir / "dem.tif") as ds:
        dem_box = box(*ds.bounds)

    axis_geo = json.loads((proj_dir / "dam_axis.geojson").read_text(encoding="utf-8"))
    res_geo = json.loads((proj_dir / "reservoir_boundary.geojson").read_text(encoding="utf-8"))
    dom_geo = json.loads((proj_dir / "model_domain.geojson").read_text(encoding="utf-8"))
    out_geo = json.loads((proj_dir / "downstream_outlet.geojson").read_text(encoding="utf-8"))

    axis_shape = shape(axis_geo["features"][0]["geometry"])
    res_shape = shape(res_geo["features"][0]["geometry"])
    dom_shape = shape(dom_geo["features"][0]["geometry"])
    out_shape = shape(out_geo["features"][0]["geometry"])

    # 1. Validity
    assert axis_shape.is_valid
    assert res_shape.is_valid
    assert dom_shape.is_valid
    assert out_shape.is_valid

    # 2. DEM containment
    assert dem_box.contains(dom_shape), "Model domain must be 100% inside DEM bounds"
    assert dem_box.contains(res_shape), "Reservoir must be 100% inside DEM bounds"
    assert dem_box.contains(axis_shape), "Dam axis must be 100% inside DEM bounds"

    # 3. Model domain containment
    assert dom_shape.contains(res_shape), "Reservoir boundary must be fully contained within model domain"
    assert dom_shape.contains(axis_shape), "Dam crest axis must lie within model domain"

    # 4. Axis intersects reservoir
    touches_res = res_shape.intersects(axis_shape) or res_shape.distance(axis_shape) < 1e-4
    assert touches_res, "Dam axis must touch or intersect reservoir boundary"

    # 5. Outlet touches model domain boundary
    assert dom_shape.boundary.intersects(out_shape) or dom_shape.boundary.distance(out_shape) < 1e-4


def test_prepare_demo_inputs_hydraulic_consistency(registered_demo_project):
    """Task Requirement: Verify physical hydraulic consistency (crest > pool > invert >= 0)."""
    res = client.post(f"/api/dam-projects/{registered_demo_project}/demo-inputs")
    assert res.status_code == 200
    data = res.json()

    crest = data["dam_crest_elevation"]
    pool = data["reservoir_level"]
    invert = data["breach_invert_elevation"]
    height = data["dam_height"]
    freeboard = data["freeboard_m"]

    assert crest > pool, f"Dam crest elevation ({crest}) must exceed pool level ({pool})"
    assert pool > invert, f"Pool level ({pool}) must exceed breach invert ({invert})"
    assert invert >= 0.0, "Invert elevation must be non-negative"
    assert height > 0.0, "Dam structural height must be positive"
    assert freeboard > 0.0, "Freeboard must be positive"
    assert round(crest - pool, 2) == round(freeboard, 2)
    assert data["manning_roughness"] > 0.0
    assert data["simulation_duration_s"] > 0.0


def test_prepare_demo_inputs_readiness_transition(registered_demo_project, monkeypatch):
    """Task Requirement: Verify 5-Tier readiness becomes Complete after preparing demo inputs."""
    monkeypatch.setenv("ENABLE_CUSTOM_ANUGA_EXECUTION", "true")

    res = client.post(f"/api/dam-projects/{registered_demo_project}/demo-inputs")
    assert res.status_code == 200
    data = res.json()
    r = data["readiness"]

    assert r["data_ready"] is True
    assert r["geometry_ready"] is True
    assert r["hydraulic_ready"] is True
    assert r["solver_ready"] is True
    assert r["simulation_ready"] is True
    assert r["missing_requirements"] == []

    # Check that GET /readiness reflects the same complete state
    get_res = client.get(f"/api/dam-projects/{registered_demo_project}/readiness")
    assert get_res.status_code == 200
    get_r = get_res.json()
    assert get_r["data_ready"] is True
    assert get_r["geometry_ready"] is True
    assert get_r["hydraulic_ready"] is True
    assert get_r["simulation_ready"] is True
    assert get_r["missing_requirements"] == []


def test_prepare_demo_inputs_provenance_and_caveats(registered_demo_project):
    """Task Requirement: Stored provenance must be HYPOTHETICAL_UNVERIFIED."""
    res = client.post(f"/api/dam-projects/{registered_demo_project}/demo-inputs")
    assert res.status_code == 200
    data = res.json()

    assert data["provenance"] == "HYPOTHETICAL_UNVERIFIED"
    assert data["scientifically_verified"] is False
    assert "HYPOTHETICAL / UNVERIFIED" in data["disclaimer"]


def test_load_hidkal_demo_endpoint_and_anuga_package_readiness(tmp_path, monkeypatch):
    """Verify loading Hidkal demo via /api/dam-projects/load-hidkal-demo and generating ANUGA package."""
    temp_dir = tmp_path / "dam_projects"
    temp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(onboarding_service, "get_dam_projects_dir", lambda: temp_dir)
    monkeypatch.setenv("ENABLE_CUSTOM_ANUGA_EXECUTION", "true")

    # 1. Load Hidkal Demo
    res = client.post("/api/dam-projects/load-hidkal-demo")
    assert res.status_code == 200, res.text
    demo_data = res.json()

    project_id = demo_data["project_id"]
    assert demo_data["project_name"] == "Hidkal Dam Demonstration Study"
    assert demo_data["model_domain_file"] == "model_domain.geojson"
    assert demo_data["reservoir_boundary_file"] == "reservoir_boundary.geojson"
    assert demo_data["dam_axis_file"] == "dam_axis.geojson"
    assert demo_data["downstream_outlet_file"] == "downstream_outlet.geojson"

    # 2. Check 5-tier readiness is 100% complete
    readiness_res = client.get(f"/api/dam-projects/{project_id}/readiness")
    assert readiness_res.status_code == 200
    r = readiness_res.json()
    assert r["data_ready"] is True
    assert r["geometry_ready"] is True
    assert r["hydraulic_ready"] is True
    assert r["simulation_ready"] is True
    assert r["missing_requirements"] == []

    # 3. Check ANUGA Preflight
    preflight_res = client.post(f"/api/dam-projects/{project_id}/anuga/preflight")
    assert preflight_res.status_code == 200
    pf = preflight_res.json()
    assert pf["preflight_passed"] is True
    assert pf["blockers"] == []

    # 4. Generate ANUGA Package ZIP
    pkg_res = client.post(f"/api/dam-projects/{project_id}/anuga/build-package")
    assert pkg_res.status_code == 200, pkg_res.text
    pkg = pkg_res.json()
    assert pkg["package_filename"] == "anuga_package.zip"
    assert pkg["package_size_bytes"] > 0
    assert "config.json" in pkg["files_included"]
    assert "run_anuga.py" in pkg["files_included"]
    assert "dem.tif" in pkg["files_included"]
    assert "dam_axis.geojson" in pkg["files_included"]
    assert "reservoir_boundary.geojson" in pkg["files_included"]
    assert "model_domain.geojson" in pkg["files_included"]
    assert "downstream_outlet.geojson" in pkg["files_included"]

    # 5. Verify Package Download Endpoint
    dl_res = client.get(f"/api/dam-projects/{project_id}/anuga/package")
    assert dl_res.status_code == 200
    assert len(dl_res.content) == pkg["package_size_bytes"]

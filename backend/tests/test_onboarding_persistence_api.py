"""
Unit and integration tests for Dam Project Persistence & DEM Inspection API (SIH PS 26161).

Tests:
1. Atomic project save with manifest SHA-256 verification and status flags.
2. Requirement for acknowledge_unverified_metadata (HTTP 422 if false).
3. Invalid inputs create no directory or leftover temporary artifacts.
4. Strict UUID validation and path traversal protection.
5. List and get persistence across multiple queries.
6. Custom project DEM raster metadata retrieval.
7. Custom project DEM point value querying (valid coords and out-of-bounds).
8. Custom project DEM Web Mercator PNG tile rendering.
9. Invariant scientific flags: scientifically_verified remains False across all endpoints.
"""

import io
import json
import uuid
import shutil
import hashlib
from pathlib import Path
import pytest
import numpy as np
import rasterio
from affine import Affine
from fastapi.testclient import TestClient

from app.main import app
from app import onboarding_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_dam_projects_storage(tmp_path, monkeypatch):
    """Ensure all onboarding tests run with an isolated temporary dam_projects directory."""
    temp_dir = tmp_path / "dam_projects"
    temp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(onboarding_service, "get_dam_projects_dir", lambda: temp_dir)
    return temp_dir


def create_test_geotiff_bytes(
    width: int = 50,
    height: int = 50,
    crs: str = "EPSG:32643",
    bands: int = 1,
    nodata: float = -9999.0,
    min_val: float = 600.0,
    max_val: float = 750.0,
    origin_x: float = 500000.0,
    origin_y: float = 1800000.0,
    res: float = 30.0,
) -> bytes:
    """Create in-memory GeoTIFF raster bytes."""
    buf = io.BytesIO()
    transform = Affine(res, 0.0, origin_x, 0.0, -res, origin_y)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": bands,
        "dtype": "float32",
        "crs": crs if crs else None,
        "transform": transform,
        "nodata": nodata,
    }
    with rasterio.open(buf, "w", **profile) as dst:
        data = np.linspace(min_val, max_val, width * height, dtype=np.float32).reshape((height, width))
        for b_idx in range(1, bands + 1):
            dst.write(data, b_idx)

    return buf.getvalue()


def create_dam_axis_geojson(coords: list) -> bytes:
    """Create valid GeoJSON FeatureCollection for dam axis LineString."""
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords,
                },
                "properties": {"name": "Test Dam Axis"},
            }
        ],
    }
    return json.dumps(fc).encode("utf-8")


def create_reservoir_geojson(coords: list) -> bytes:
    """Create valid GeoJSON FeatureCollection for reservoir boundary Polygon."""
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [coords],
                },
                "properties": {"name": "Test Reservoir Pool"},
            }
        ],
    }
    return json.dumps(fc).encode("utf-8")


# Common UTM 43N test coordinates (inside DEM extent: origin 500000, 1800000, size 50x50 at 30m = 500000 to 501500, 1798500 to 1800000)
VALID_AXIS_COORDS = [[500200.0, 1799200.0], [500800.0, 1799200.0]]
VALID_RES_COORDS = [
    [500200.0, 1799200.0],
    [500800.0, 1799200.0],
    [500800.0, 1799600.0],
    [500200.0, 1799600.0],
    [500200.0, 1799200.0],
]


@pytest.fixture(autouse=True)
def clean_test_dam_projects():
    """Clean up any temporary test dam project directories before and after test runs."""
    base_dir = onboarding_service.get_dam_projects_dir()
    for p in list(base_dir.iterdir()):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
    yield
    for p in list(base_dir.iterdir()):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


def test_dam_project_registration_acknowledgement_required():
    """Test that POST /api/dam-projects requires acknowledge_unverified_metadata=true."""
    dem_bytes = create_test_geotiff_bytes()
    axis_bytes = create_dam_axis_geojson(VALID_AXIS_COORDS)

    files = {
        "dem_file": ("dem.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", axis_bytes, "application/geo+json"),
    }
    data = {
        "project_name": "Ack Test Dam",
        "reservoir_level": 700.0,
        "breach_width": 150.0,
        "breach_center_x": 500500.0,
        "breach_center_y": 1799200.0,
        "geometry_crs": "EPSG:32643",
        "acknowledge_unverified_metadata": "false",  # Unacknowledged
    }

    res = client.post("/api/dam-projects", files=files, data=data)
    assert res.status_code == 422
    assert "acknowledgment" in res.text.lower()


def test_dam_project_registration_atomic_save_and_manifest():
    """Test successful atomic save of a dam project with SHA-256 manifest generation."""
    dem_bytes = create_test_geotiff_bytes()
    axis_bytes = create_dam_axis_geojson(VALID_AXIS_COORDS)
    res_bytes = create_reservoir_geojson(VALID_RES_COORDS)

    files = {
        "dem_file": ("custom_dem.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", axis_bytes, "application/geo+json"),
        "reservoir_boundary_file": ("reservoir.geojson", res_bytes, "application/geo+json"),
    }
    data = {
        "project_name": "Atomic Save Test Dam",
        "vertical_unit": "meters",
        "vertical_datum": "MSL",
        "reservoir_level": 710.0,
        "breach_width": 180.0,
        "breach_center_x": 500500.0,
        "breach_center_y": 1799200.0,
        "breach_formation_time_hr": 1.5,
        "manning_roughness": 0.032,
        "geometry_crs": "EPSG:32643",
        "acknowledge_unverified_metadata": "true",
    }

    res = client.post("/api/dam-projects", files=files, data=data)
    assert res.status_code == 200, res.text
    json_data = res.json()

    project_id = json_data["project_id"]
    # Check valid UUID
    parsed_uuid = uuid.UUID(project_id, version=4)
    assert str(parsed_uuid) == project_id

    assert json_data["project_name"] == "Atomic Save Test Dam"
    assert json_data["status"] == "validated_unverified"
    assert json_data["scientifically_verified"] is False
    assert json_data["onboarding_validation_passed"] is True
    assert json_data["metadata_declared"] is True

    # Verify physical file storage under runtime/dam_projects/{uuid}/
    proj_dir = onboarding_service.get_dam_projects_dir() / project_id
    assert proj_dir.is_dir()

    dem_path = proj_dir / "dem.tif"
    axis_path = proj_dir / "dam_axis.geojson"
    res_path = proj_dir / "reservoir_boundary.geojson"
    proj_json_path = proj_dir / "project.json"
    manifest_path = proj_dir / "manifest.json"

    assert dem_path.is_file()
    assert axis_path.is_file()
    assert res_path.is_file()
    assert proj_json_path.is_file()
    assert manifest_path.is_file()

    # Verify SHA-256 hashes in manifest match actual files
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["project_id"] == project_id
    assert manifest_data["scientifically_verified"] is False

    for rel_name, sha in manifest_data["files"].items():
        target_file = proj_dir / rel_name
        assert target_file.is_file()
        computed_sha = hashlib.sha256(target_file.read_bytes()).hexdigest()
        assert computed_sha == sha, f"Hash mismatch for {rel_name}"


def test_invalid_input_creates_no_directory():
    """Test that invalid inputs fail validation and leave no leftover directories in runtime."""
    dem_bytes = create_test_geotiff_bytes()
    # Dam axis completely outside DEM extent
    outside_axis_bytes = create_dam_axis_geojson([[100000.0, 100000.0], [100500.0, 100000.0]])

    files = {
        "dem_file": ("dem.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", outside_axis_bytes, "application/geo+json"),
    }
    data = {
        "project_name": "Invalid Project",
        "reservoir_level": 700.0,
        "breach_width": 100.0,
        "breach_center_x": 100250.0,
        "breach_center_y": 100000.0,
        "geometry_crs": "EPSG:32643",
        "acknowledge_unverified_metadata": "true",
    }

    base_dir = onboarding_service.get_dam_projects_dir()
    count_before = len(list(base_dir.iterdir()))

    res = client.post("/api/dam-projects", files=files, data=data)
    assert res.status_code == 422

    count_after = len(list(base_dir.iterdir()))
    assert count_after == count_before, "Failed save must not create any persistent directory or temporary files"


def test_uuid_and_path_traversal_protection():
    """Test strict UUID v4 validation prevents path traversal attacks."""
    # Invalid UUID strings that fail strict UUID v4 parsing
    for bad_id in ["invalid-uuid", "12345", "not-a-uuid-format", "b16f3938-1234", "99999999-9999-9999-9999-99999999999g", ".._..", "admin--path"]:
        res = client.get(f"/api/dam-projects/{bad_id}")
        assert res.status_code == 422, f"Expected 422 for invalid UUID '{bad_id}'"

        res_dem = client.get(f"/api/dam-projects/{bad_id}/dem/metadata")
        assert res_dem.status_code == 422

        res_val = client.get(f"/api/dam-projects/{bad_id}/dem/value?lon=75.0&lat=16.0")
        assert res_val.status_code == 422

        res_tile = client.get(f"/api/dam-projects/{bad_id}/dem/tiles/10/500/500.png")
        assert res_tile.status_code == 422

    # Valid UUID format but non-existent project
    random_uuid = str(uuid.uuid4())
    res_404 = client.get(f"/api/dam-projects/{random_uuid}")
    assert res_404.status_code == 404


def test_list_and_get_dam_projects_persistence():
    """Test listing and fetching saved projects via GET endpoints."""
    dem_bytes = create_test_geotiff_bytes()
    axis_bytes = create_dam_axis_geojson(VALID_AXIS_COORDS)

    files = {
        "dem_file": ("dem.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", axis_bytes, "application/geo+json"),
    }
    data = {
        "project_name": "Persistent Listing Test",
        "reservoir_level": 680.0,
        "breach_width": 120.0,
        "breach_center_x": 500500.0,
        "breach_center_y": 1799200.0,
        "geometry_crs": "EPSG:32643",
        "acknowledge_unverified_metadata": "true",
    }

    create_res = client.post("/api/dam-projects", files=files, data=data)
    assert create_res.status_code == 200
    created_id = create_res.json()["project_id"]

    # List endpoint
    list_res = client.get("/api/dam-projects")
    assert list_res.status_code == 200
    project_list = list_res.json()
    assert isinstance(project_list, list)
    matching = [p for p in project_list if p["project_id"] == created_id]
    assert len(matching) == 1
    assert matching[0]["project_name"] == "Persistent Listing Test"
    assert matching[0]["status"] == "validated_unverified"
    assert matching[0]["scientifically_verified"] is False
    assert len(matching[0]["manifest_sha256"]) == 64

    # Detail endpoint
    detail_res = client.get(f"/api/dam-projects/{created_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["project_id"] == created_id
    assert detail["project_name"] == "Persistent Listing Test"
    assert detail["scientifically_verified"] is False
    assert detail["raster_metadata"]["width"] == 50
    assert detail["raster_metadata"]["height"] == 50


def test_custom_dem_metadata_and_point_query():
    """Test DEM metadata and point elevation probing on a registered project."""
    dem_bytes = create_test_geotiff_bytes(min_val=550.0, max_val=720.0)
    axis_bytes = create_dam_axis_geojson(VALID_AXIS_COORDS)

    files = {
        "dem_file": ("dem.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", axis_bytes, "application/geo+json"),
    }
    data = {
        "project_name": "DEM Query Test",
        "reservoir_level": 690.0,
        "breach_width": 140.0,
        "breach_center_x": 500500.0,
        "breach_center_y": 1799200.0,
        "geometry_crs": "EPSG:32643",
        "acknowledge_unverified_metadata": "true",
    }

    create_res = client.post("/api/dam-projects", files=files, data=data)
    assert create_res.status_code == 200
    proj_id = create_res.json()["project_id"]

    # DEM Metadata
    meta_res = client.get(f"/api/dam-projects/{proj_id}/dem/metadata")
    assert meta_res.status_code == 200
    meta = meta_res.json()
    assert meta["width"] == 50
    assert meta["height"] == 50
    assert meta["crs"] == "EPSG:32643"
    assert meta["valid_min"] is not None
    assert meta["valid_max"] is not None

    # Point Probe (Query coordinate within UTM 43N extent transformed or direct)
    # Origin: (500000, 1800000), 500750, 1799250 corresponds roughly to lon 75.006, lat 16.273 in UTM 43N
    from pyproj import Transformer
    t_to_geo = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)
    query_lon, query_lat = t_to_geo.transform(500750.0, 1799250.0)

    val_res = client.get(f"/api/dam-projects/{proj_id}/dem/value?lon={query_lon}&lat={query_lat}")
    assert val_res.status_code == 200
    val_data = val_res.json()
    assert val_data["value"] is not None
    assert 550.0 <= val_data["value"] <= 720.0
    assert val_data["is_nodata"] is False

    # Out of bounds coordinate query
    oob_res = client.get(f"/api/dam-projects/{proj_id}/dem/value?lon=10.0&lat=10.0")
    assert oob_res.status_code == 422


def test_custom_dem_tile_endpoint():
    """Test that GET /api/dam-projects/{id}/dem/tiles/{z}/{x}/{y}.png returns a valid PNG image."""
    dem_bytes = create_test_geotiff_bytes()
    axis_bytes = create_dam_axis_geojson(VALID_AXIS_COORDS)

    files = {
        "dem_file": ("dem.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", axis_bytes, "application/geo+json"),
    }
    data = {
        "project_name": "Tile Render Test",
        "reservoir_level": 700.0,
        "breach_width": 150.0,
        "breach_center_x": 500500.0,
        "breach_center_y": 1799200.0,
        "geometry_crs": "EPSG:32643",
        "acknowledge_unverified_metadata": "true",
    }

    create_res = client.post("/api/dam-projects", files=files, data=data)
    assert create_res.status_code == 200
    proj_id = create_res.json()["project_id"]

    # Calculate tile coordinates for UTM 43N region (lon ~ 75.0, lat ~ 16.2) at zoom 12
    # At zoom 12, lon 75.0 -> x=2901, lat 16.2 -> y=1864
    tile_res = client.get(f"/api/dam-projects/{proj_id}/dem/tiles/12/2901/1864.png")
    assert tile_res.status_code == 200
    assert tile_res.headers["content-type"] == "image/png"
    # Check PNG magic bytes: \x89PNG\r\n\x1a\n
    assert tile_res.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_tampered_files_integrity_failure_409_and_sanitized_errors():
    """Test that tampering with DEM, GeoJSON, or manifest returns sanitized HTTP 409 without leaking absolute paths."""
    dem_bytes = create_test_geotiff_bytes()
    axis_bytes = create_dam_axis_geojson(VALID_AXIS_COORDS)
    res_bytes = create_reservoir_geojson(VALID_RES_COORDS)

    files = {
        "dem_file": ("dem.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", axis_bytes, "application/geo+json"),
        "reservoir_boundary_file": ("reservoir.geojson", res_bytes, "application/geo+json"),
    }
    data = {
        "project_name": "Tamper Test Dam",
        "reservoir_level": 700.0,
        "breach_width": 150.0,
        "breach_center_x": 500500.0,
        "breach_center_y": 1799200.0,
        "geometry_crs": "EPSG:32643",
        "acknowledge_unverified_metadata": "true",
    }

    create_res = client.post("/api/dam-projects", files=files, data=data)
    assert create_res.status_code == 200
    proj_id = create_res.json()["project_id"]
    proj_dir = onboarding_service.get_dam_projects_dir() / proj_id

    # 1. Tamper with dem.tif
    dem_file = proj_dir / "dem.tif"
    dem_file.write_bytes(dem_file.read_bytes() + b"TAMPERED")

    detail_res = client.get(f"/api/dam-projects/{proj_id}")
    assert detail_res.status_code == 409
    err_json = detail_res.json()
    assert err_json["detail"]["code"] == "project_integrity_failed"
    assert "SHA-256 integrity check failed" in err_json["detail"]["message"]

    # Ensure no absolute paths leaked in detail message
    assert str(proj_dir) not in err_json["detail"]["message"]
    assert "C:" not in err_json["detail"]["message"] and "Users" not in err_json["detail"]["message"]

    # Verify other endpoints also return 409 on corrupted project
    assert client.get(f"/api/dam-projects/{proj_id}/dem/metadata").status_code == 409
    assert client.get(f"/api/dam-projects/{proj_id}/dem/value?lon=75.0&lat=16.0").status_code == 409
    assert client.get(f"/api/dam-projects/{proj_id}/dem/tiles/12/2901/1864.png").status_code == 409
    assert client.get(f"/api/dam-projects/{proj_id}/geometry/dam-axis").status_code == 409
    assert client.get(f"/api/dam-projects/{proj_id}/geometry/reservoir").status_code == 409
    assert client.get(f"/api/dam-projects/{proj_id}/geometry/breach").status_code == 409

    # 2. Verify corrupted project is listed with available=False and corrupted status
    list_res = client.get("/api/dam-projects")
    assert list_res.status_code == 200
    corrupted_entry = next((p for p in list_res.json() if p["project_id"] == proj_id), None)
    assert corrupted_entry is not None
    assert corrupted_entry["available"] is False
    assert corrupted_entry["integrity_status"] == "integrity_failed"
    assert corrupted_entry["status"] == "integrity_failed"
    assert corrupted_entry["integrity_error"] is not None


def test_geometry_endpoints_and_reprojection():
    """Test GET /geometry/dam-axis, reservoir, and breach reproject stored UTM coordinates to EPSG:4326."""
    dem_bytes = create_test_geotiff_bytes()
    axis_bytes = create_dam_axis_geojson(VALID_AXIS_COORDS)
    res_bytes = create_reservoir_geojson(VALID_RES_COORDS)

    files = {
        "dem_file": ("dem.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", axis_bytes, "application/geo+json"),
        "reservoir_boundary_file": ("reservoir.geojson", res_bytes, "application/geo+json"),
    }
    data = {
        "project_name": "Geometry Reprojection Dam",
        "reservoir_level": 705.0,
        "breach_width": 160.0,
        "breach_center_x": 500500.0,
        "breach_center_y": 1799200.0,
        "breach_formation_time_hr": 1.2,
        "geometry_crs": "EPSG:32643",
        "acknowledge_unverified_metadata": "true",
    }

    create_res = client.post("/api/dam-projects", files=files, data=data)
    assert create_res.status_code == 200
    proj_id = create_res.json()["project_id"]

    # 1. Dam Axis Geometry (EPSG:4326)
    axis_res = client.get(f"/api/dam-projects/{proj_id}/geometry/dam-axis")
    assert axis_res.status_code == 200
    axis_fc = axis_res.json()
    assert axis_fc["type"] == "FeatureCollection"
    assert len(axis_fc["features"]) == 1
    feat = axis_fc["features"][0]
    assert feat["geometry"]["type"] == "LineString"
    first_coord = feat["geometry"]["coordinates"][0]
    # Check degree ranges (longitude ~ 75.0, latitude ~ 16.27)
    assert 74.0 <= first_coord[0] <= 76.0
    assert 15.0 <= first_coord[1] <= 17.0
    assert feat["properties"]["label"] == "User-provided Dam Axis"
    assert feat["properties"]["provenance"] == "user_declared_unverified"

    # 2. Reservoir Geometry (EPSG:4326)
    res_res = client.get(f"/api/dam-projects/{proj_id}/geometry/reservoir")
    assert res_res.status_code == 200
    res_fc = res_res.json()
    assert res_fc["type"] == "FeatureCollection"
    assert len(res_fc["features"]) == 1
    r_feat = res_fc["features"][0]
    assert r_feat["geometry"]["type"] == "Polygon"
    r_coord = r_feat["geometry"]["coordinates"][0][0]
    assert 74.0 <= r_coord[0] <= 76.0
    assert 15.0 <= r_coord[1] <= 17.0
    assert r_feat["properties"]["label"] == "User-provided Reservoir Boundary"

    # 3. Breach Location Geometry (Point in EPSG:4326)
    breach_res = client.get(f"/api/dam-projects/{proj_id}/geometry/breach")
    assert breach_res.status_code == 200
    breach_fc = breach_res.json()
    assert breach_fc["type"] == "FeatureCollection"
    assert len(breach_fc["features"]) == 1
    b_feat = breach_fc["features"][0]
    assert b_feat["geometry"]["type"] == "Point"
    b_coords = b_feat["geometry"]["coordinates"]
    assert 74.0 <= b_coords[0] <= 76.0
    assert 15.0 <= b_coords[1] <= 17.0
    assert b_feat["properties"]["label"] == "Hypothetical Breach Location"
    assert b_feat["properties"]["breach_width_m"] == 160.0
    assert b_feat["properties"]["reservoir_level"] == 705.0


def test_missing_optional_reservoir_returns_404():
    """Test that requesting reservoir geometry on a project without reservoir returns clean 404."""
    dem_bytes = create_test_geotiff_bytes()
    axis_bytes = create_dam_axis_geojson(VALID_AXIS_COORDS)

    files = {
        "dem_file": ("dem.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", axis_bytes, "application/geo+json"),
    }
    data = {
        "project_name": "No Reservoir Dam",
        "reservoir_level": 680.0,
        "breach_width": 100.0,
        "breach_center_x": 500500.0,
        "breach_center_y": 1799200.0,
        "geometry_crs": "EPSG:32643",
        "acknowledge_unverified_metadata": "true",
    }

    create_res = client.post("/api/dam-projects", files=files, data=data)
    assert create_res.status_code == 200
    proj_id = create_res.json()["project_id"]

    res_res = client.get(f"/api/dam-projects/{proj_id}/geometry/reservoir")
    assert res_res.status_code == 404
    assert "no reservoir boundary geometry" in res_res.text.lower()


def test_real_runtime_storage_isolated_and_untouched(isolate_dam_projects_storage):
    """Verify that test project registration never writes into the real runtime/dam_projects folder."""
    # Current active storage must point to the temporary fixture directory
    current_storage = onboarding_service.get_dam_projects_dir()
    assert current_storage == isolate_dam_projects_storage
    assert "pytest" in str(current_storage) or "tmp" in str(current_storage).lower() or "temp" in str(current_storage).lower()

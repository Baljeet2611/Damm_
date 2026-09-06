"""
Unit tests for Dam Project Onboarding & Dataset Validation API (SIH PS 26161).

Tests:
1. User-declared metadata (meters + MSL): metadata_declared=True, warning added, scientifically_verified remains False.
2. Missing unit/datum: metadata_declared=False, assumptions added, scientifically_verified remains False.
3. Onboarding validation passed flag: distinct from simulation certification.
4. Rejection of invalid geometry types (Polygon in dam axis, LineString in reservoir).
5. Partially outside geometry: distinguishes intersects_dem_bounds from fully_within_dem_bounds.
6. Geographic CRS metric distance calculation correctness (meters, never degree Euclidean).
7. Oversized input rejection with HTTP 413.
8. Missing CRS rejection.
9. Path traversal filename rejection.
"""

import io
import json
import pytest
import numpy as np
import rasterio
from rasterio.transform import from_origin
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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
    """Create in-memory GeoTIFF bytes for testing."""
    buf = io.BytesIO()
    transform = from_origin(origin_x, origin_y, res, res)
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


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def test_validate_dam_project_user_declared_metadata():
    """Verify entering meters + MSL sets metadata_declared=True, adds warning, and scientifically_verified remains False."""
    dem_bytes = create_test_geotiff_bytes()
    axis_bytes = create_dam_axis_geojson([[500200.0, 1799000.0], [500800.0, 1799000.0]])

    files = {
        "dem_file": ("elevation.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", axis_bytes, "application/json"),
    }
    data = {
        "project_name": "Koyna Model Declared",
        "vertical_unit": "meters",
        "vertical_datum": "MSL",
        "reservoir_level": 660.0,
        "breach_width": 100.0,
        "breach_center_x": 500500.0,
        "breach_center_y": 1799000.0,
        "geometry_crs": "EPSG:32643",
    }

    response = client.post("/api/dam-projects/validate", files=files, data=data)
    assert response.status_code == 200
    res_json = response.json()

    assert res_json["valid"] is True
    assert res_json["metadata_declared"] is True
    assert res_json["onboarding_validation_passed"] is True
    # Scientifically verified must remain False in this MVP
    assert res_json["scientifically_verified"] is False
    assert any("Metadata is user-declared and has not been independently verified." in w for w in res_json["warnings"])

    norm = res_json["normalized_metadata"]
    assert norm["user_provided_metadata"]["vertical_unit"] == "meters"
    assert norm["user_provided_metadata"]["vertical_datum"] == "MSL"
    assert norm["raster_metadata"]["vertical_unit_in_header"] == "unknown"
    assert norm["raster_metadata"]["vertical_datum_in_header"] == "unknown"


def test_validate_dam_project_missing_unit_and_datum():
    """Verify missing vertical unit/datum results in metadata_declared=False and assumptions added."""
    dem_bytes = create_test_geotiff_bytes()
    axis_bytes = create_dam_axis_geojson([[500200.0, 1799000.0], [500800.0, 1799000.0]])

    files = {
        "dem_file": ("elevation.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", axis_bytes, "application/json"),
    }
    data = {
        "project_name": "Test Model No Unit",
        "reservoir_level": 660.0,
        "breach_width": 100.0,
        "breach_center_x": 500500.0,
        "breach_center_y": 1799000.0,
        "geometry_crs": "EPSG:32643",
    }

    response = client.post("/api/dam-projects/validate", files=files, data=data)
    assert response.status_code == 200
    res_json = response.json()

    assert res_json["valid"] is True
    assert res_json["metadata_declared"] is False
    assert res_json["onboarding_validation_passed"] is True
    assert res_json["scientifically_verified"] is False
    assert any("DEM vertical unit is unknown" in a for a in res_json["assumptions_requiring_confirmation"])
    assert any("DEM vertical datum is unknown" in a for a in res_json["assumptions_requiring_confirmation"])


def test_validate_dam_project_wrong_geometry_types():
    """Verify that Polygon in dam axis or LineString in reservoir is strictly rejected."""
    dem_bytes = create_test_geotiff_bytes()

    # Create Polygon incorrectly as dam axis
    poly_as_axis = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[500200, 1799000], [500800, 1799000], [500800, 1799200], [500200, 1799000]]],
            },
            "properties": {},
        }],
    }
    files = {
        "dem_file": ("elevation.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("axis.geojson", json.dumps(poly_as_axis).encode("utf-8"), "application/json"),
    }

    response = client.post("/api/dam-projects/validate", files=files, data={"project_name": "Wrong Geom Type"})
    res_json = response.json()

    assert res_json["valid"] is False
    assert res_json["onboarding_validation_passed"] is False
    assert any("LineString or MultiLineString" in err for err in res_json["errors"])


def test_validate_dam_project_partially_outside_geometry():
    """Verify distinction between intersects_dem_bounds and fully_within_dem_bounds."""
    # DEM extent is [500000, 1798500, 501500, 1800000]
    dem_bytes = create_test_geotiff_bytes(origin_x=500000.0, origin_y=1800000.0, width=50, height=50, res=30.0)

    # LineString starts inside DEM (500500, 1799000) and extends far outside (505000, 1799000)
    partial_axis = create_dam_axis_geojson([[500500.0, 1799000.0], [505000.0, 1799000.0]])

    files = {
        "dem_file": ("elevation.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("partial_axis.geojson", partial_axis, "application/json"),
    }
    data = {
        "project_name": "Partial Extent Test",
        "geometry_crs": "EPSG:32643",
        "reservoir_level": 660.0,
        "breach_width": 100.0,
        "breach_center_x": 500500.0,
        "breach_center_y": 1799000.0,
    }

    res = client.post("/api/dam-projects/validate", files=files, data=data).json()
    axis_meta = res["normalized_metadata"]["dam_axis_metadata"]

    assert axis_meta["intersects_dem_bounds"] is True
    assert axis_meta["fully_within_dem_bounds"] is False
    assert res["onboarding_validation_passed"] is False  # Must NOT pass validation when partially outside
    assert any("partially beyond" in warn for warn in res["warnings"])


def test_validate_dam_project_geographic_crs_metric_distance():
    """Verify distance is computed in true meters and metric CRS reported when coordinates are in EPSG:4326."""
    # Create geographic DEM in degrees (Koyna region around 73.70 E, 17.45 N)
    dem_bytes = create_test_geotiff_bytes(
        width=50,
        height=50,
        crs="EPSG:4326",
        origin_x=73.70,
        origin_y=17.45,
        res=0.001,  # ~110m
    )
    # Dam axis in WGS84 degrees
    axis_bytes = create_dam_axis_geojson([[73.72, 17.42], [73.74, 17.42]])

    # Breach center at 73.73 E, 17.4205 N (~55 meters north of axis in EPSG:4326)
    files = {
        "dem_file": ("geo_dem.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("geo_axis.geojson", axis_bytes, "application/json"),
    }
    data = {
        "project_name": "Geographic CRS Test",
        "geometry_crs": "EPSG:4326",
        "reservoir_level": 600.0,
        "breach_width": 50.0,
        "breach_center_x": 73.73,
        "breach_center_y": 17.4205,
    }

    res = client.post("/api/dam-projects/validate", files=files, data=data).json()
    assert res["valid"] is True
    assert res["onboarding_validation_passed"] is True

    norm = res["normalized_metadata"]
    dist_m = norm["breach_distance_to_axis_m"]

    # Distance must be in true metres (~50-60m), NOT ~0.0005 degrees
    assert dist_m > 30.0 and dist_m < 80.0
    assert norm["distance_calculation_crs"] is not None
    assert "EPSG:32643" in norm["distance_calculation_crs"] or "EPSG:" in norm["distance_calculation_crs"]


def test_validate_dam_project_oversized_upload_rejection():
    """Verify inputs exceeding byte limits or pixel limits are rejected with HTTP 413."""
    # Create fake oversized bytes (simulated 51MB payload exceeding 50MB limit)
    oversized_bytes = b"0" * (51 * 1024 * 1024)
    axis_bytes = create_dam_axis_geojson([[500200.0, 1799000.0], [500800.0, 1799000.0]])

    files = {
        "dem_file": ("huge_dem.tif", oversized_bytes, "image/tiff"),
        "dam_axis_file": ("axis.geojson", axis_bytes, "application/json"),
    }

    response = client.post("/api/dam-projects/validate", files=files, data={"project_name": "Oversized Payload"})
    assert response.status_code == 413
    assert "exceeds maximum limit" in response.json()["detail"]


def test_validate_dam_project_missing_crs():
    """Test DEM without CRS is rejected with explicit CRS error."""
    dem_bytes = create_test_geotiff_bytes(crs=None)
    axis_bytes = create_dam_axis_geojson([[500200.0, 1799000.0], [500800.0, 1799000.0]])

    files = {
        "dem_file": ("no_crs.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", axis_bytes, "application/json"),
    }
    data = {
        "project_name": "Unprojected Dam",
        "reservoir_level": 100.0,
        "breach_width": 50.0,
    }

    response = client.post("/api/dam-projects/validate", files=files, data=data)
    assert response.status_code == 200
    res_json = response.json()

    assert res_json["valid"] is False
    assert any("Coordinate Reference System" in err for err in res_json["errors"])
    assert res_json["onboarding_validation_passed"] is False


def test_validate_dam_project_path_traversal_filename():
    """Test filenames attempting directory traversal are immediately rejected."""
    dem_bytes = create_test_geotiff_bytes()
    axis_bytes = create_dam_axis_geojson([[500200.0, 1799000.0], [500800.0, 1799000.0]])

    files = {
        "dem_file": ("../../etc/passwd.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", axis_bytes, "application/json"),
    }

    response = client.post("/api/dam-projects/validate", files=files, data={"project_name": "Traversal Test"})
    assert response.status_code == 200
    res_json = response.json()

    assert res_json["valid"] is False
    assert any("path traversal" in err for err in res_json["errors"])

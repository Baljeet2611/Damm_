"""
Phase 18 Generalized Dam / River Ingestion Integration & Security Tests.

Covers:
1. Minimal dataset onboarding (DEM GeoTIFF + project_name + dam_name + latitude + longitude).
2. No required vector axis or reservoir boundaries.
3. GeoTIFF CRS detection and rejection of rasters missing spatial reference.
4. Decimal degree coordinate validation (-90 <= lat <= 90, -180 <= lon <= 180).
5. Automatic DEM elevation sampling at user-specified dam point.
6. Optional engineering parameters ingestion (dam_height, crest_elevation, pool_elevation, manning_n, freeboard).
7. Pre-simulation readiness assessment endpoint (/api/dam-projects/{id}/readiness).
8. Dynamic DEM color ramp legend endpoint (/api/dam-projects/{id}/dem/legend).
9. Dam marker GeoJSON endpoint (/api/dam-projects/{id}/geometry/dam-marker).
10. Point elevation inspection (/api/dam-projects/{id}/dem/value).
11. Preserved scientific invariants: scientific_status = 'validated_unverified', scientifically_verified = False.
12. Backwards compatibility with Phase 14-17 legacy vector onboarding.
"""

import io
import json
import uuid
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
    """Ensure all tests run against an isolated temporary dam_projects directory."""
    temp_dir = tmp_path / "dam_projects"
    temp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(onboarding_service, "get_dam_projects_dir", lambda: temp_dir)
    return temp_dir


def create_test_wgs84_geotiff_bytes(
    width: int = 50,
    height: int = 50,
    crs: str = "EPSG:4326",
    nodata: float = -9999.0,
    min_val: float = 600.0,
    max_val: float = 750.0,
    origin_x: float = 73.70,
    origin_y: float = 17.50,
    res: float = 0.005,
) -> bytes:
    """Create in-memory GeoTIFF raster in WGS84 degrees."""
    buf = io.BytesIO()
    transform = Affine(res, 0.0, origin_x, 0.0, -res, origin_y)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": crs if crs else None,
        "transform": transform,
        "nodata": nodata,
    }
    with rasterio.open(buf, "w", **profile) as dst:
        data = np.linspace(min_val, max_val, width * height, dtype=np.float32).reshape((height, width))
        dst.write(data, 1)

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


class TestPhase18MinimalGeneralizedOnboarding:
    """Tests for minimal required onboarding without vector files."""

    def test_minimal_generalized_onboarding_validate_and_save(self):
        """Verify successful validation and save with only DEM GeoTIFF and point metadata."""
        dem_bytes = create_test_wgs84_geotiff_bytes()

        files = {
            "dem_file": ("koyna_dem.tif", dem_bytes, "image/tiff"),
        }
        data = {
            "project_name": "Koyna River Basin Generalized Study",
            "dam_name": "Koyna Dam",
            "latitude": "17.4005",
            "longitude": "73.7482",
        }

        # 1. Validation Step
        val_res = client.post("/api/dam-projects/validate", files=files, data=data)
        assert val_res.status_code == 200, f"Validation failed: {val_res.text}"
        val_data = val_res.json()

        assert val_data["valid"] is True
        assert val_data["onboarding_validation_passed"] is True
        assert val_data["project_name"] == "Koyna River Basin Generalized Study"
        assert val_data["dam_name"] == "Koyna Dam"
        assert val_data["scientific_status"] == "validated_unverified"
        assert val_data["scientifically_verified"] is False

        # Verify normalized metadata
        norm = val_data["normalized_metadata"]
        assert norm is not None
        assert norm["dam_name"] == "Koyna Dam"
        assert norm["scientific_status"] == "validated_unverified"

        # Check dam point
        dam_point = norm["dam_point"]
        assert dam_point is not None
        assert dam_point["dam_name"] == "Koyna Dam"
        assert abs(dam_point["latitude"] - 17.4005) < 1e-4
        assert abs(dam_point["longitude"] - 73.7482) < 1e-4
        assert dam_point["sampled_from_dem"] is True
        assert dam_point["elevation_at_point"] is not None
        assert 600.0 <= dam_point["elevation_at_point"] <= 750.0

        # Check raster metadata
        raster_meta = norm["raster_metadata"]
        assert raster_meta is not None
        assert raster_meta["width"] == 50
        assert raster_meta["height"] == 50
        assert raster_meta["crs"] == "EPSG:4326"
        assert raster_meta["mean_elevation"] is not None
        assert 600.0 <= raster_meta["mean_elevation"] <= 750.0
        assert raster_meta["valid_pixel_count"] == 2500
        assert raster_meta["nodata_pixel_count"] == 0

        # Vector metadata should be None
        assert norm["dam_axis_metadata"] is None
        assert norm["reservoir_metadata"] is None

        # 2. Persistence Save Step
        save_files = {
            "dem_file": ("koyna_dem.tif", dem_bytes, "image/tiff"),
        }
        save_data = {
            **data,
            "acknowledge_unverified_metadata": "true",
        }
        save_res = client.post("/api/dam-projects", files=save_files, data=save_data)
        assert save_res.status_code == 200, f"Save failed: {save_res.text}"
        proj = save_res.json()

        project_id = proj["project_id"]
        assert proj["project_name"] == "Koyna River Basin Generalized Study"
        assert proj["dam_name"] == "Koyna Dam"
        assert proj["scientific_status"] == "validated_unverified"
        assert proj["scientifically_verified"] is False
        assert proj["dam_axis_file"] is None
        assert proj["dam_point"] is not None
        assert abs(proj["dam_point"]["latitude"] - 17.4005) < 1e-4

        # Verify disk persistence & manifest
        proj_dir = onboarding_service.get_dam_projects_dir() / project_id
        assert (proj_dir / "dem.tif").is_file()
        assert (proj_dir / "project.json").is_file()
        assert (proj_dir / "manifest.json").is_file()
        assert not (proj_dir / "dam_axis.geojson").exists()

        manifest = json.loads((proj_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["scientifically_verified"] is False
        assert "dem.tif" in manifest["files"]
        assert "project.json" in manifest["files"]


class TestPhase18ValidationEdgeCasesAndSecurity:
    """Tests for coordinate bounds, missing CRS, and file validation."""

    def test_rejection_of_missing_crs(self):
        """A GeoTIFF without a defined spatial reference system must fail validation."""
        dem_no_crs = create_test_wgs84_geotiff_bytes(crs="")

        files = {"dem_file": ("no_crs.tif", dem_no_crs, "image/tiff")}
        data = {
            "project_name": "No CRS Study",
            "dam_name": "Invalid Dam",
            "latitude": "17.4005",
            "longitude": "73.7482",
        }

        res = client.post("/api/dam-projects/validate", files=files, data=data)
        assert res.status_code == 200
        val = res.json()
        assert val["valid"] is False
        assert val["onboarding_validation_passed"] is False
        assert any("CRS" in err or "spatial reference" in err for err in val["errors"])

    def test_rejection_of_invalid_coordinate_ranges(self):
        """Latitude must be between -90 and 90; longitude between -180 and 180."""
        dem_bytes = create_test_wgs84_geotiff_bytes()

        # Test latitude out of bounds
        res_lat = client.post(
            "/api/dam-projects/validate",
            files={"dem_file": ("test.tif", dem_bytes, "image/tiff")},
            data={"project_name": "Bad Lat", "dam_name": "Test", "latitude": "99.5", "longitude": "73.0"},
        )
        assert res_lat.status_code == 200
        val_lat = res_lat.json()
        assert val_lat["valid"] is False
        assert any("outside valid WGS84" in err for err in val_lat["errors"])

        # Test longitude out of bounds
        res_lon = client.post(
            "/api/dam-projects/validate",
            files={"dem_file": ("test.tif", dem_bytes, "image/tiff")},
            data={"project_name": "Bad Lon", "dam_name": "Test", "latitude": "17.0", "longitude": "-195.0"},
        )
        assert res_lon.status_code == 200
        val_lon = res_lon.json()
        assert val_lon["valid"] is False
        assert any("outside valid WGS84" in err for err in val_lon["errors"])

    def test_coordinates_outside_dem_extent(self):
        """Coordinates outside the DEM extent should raise a warning and not crash."""
        dem_bytes = create_test_wgs84_geotiff_bytes()

        # Place dam point far away (e.g. 10 degrees east of the raster)
        files = {"dem_file": ("test.tif", dem_bytes, "image/tiff")}
        data = {
            "project_name": "Far Coordinates",
            "dam_name": "Far Dam",
            "latitude": "17.40",
            "longitude": "85.00",
        }
        res = client.post("/api/dam-projects/validate", files=files, data=data)
        assert res.status_code == 200
        val = res.json()
        assert val["valid"] is False
        assert any("outside the DEM bounding extent" in err for err in val["errors"])


class TestPhase18EngineeringParameters:
    """Tests for optional engineering parameters and hydraulic calculations."""

    def test_engineering_parameters_and_freeboard_calculation(self):
        """Verify dam_height, crest_elevation, pool_elevation, manning_n, and freeboard."""
        dem_bytes = create_test_wgs84_geotiff_bytes()

        files = {"dem_file": ("koyna.tif", dem_bytes, "image/tiff")}
        data = {
            "project_name": "Koyna Engineering Test",
            "dam_name": "Koyna Dam",
            "latitude": "17.4005",
            "longitude": "73.7482",
            "dam_height": "103.0",
            "crest_elevation": "665.0",
            "pool_elevation": "657.9",
            "manning_n": "0.035",
        }

        val_res = client.post("/api/dam-projects/validate", files=files, data=data)
        assert val_res.status_code == 200
        val = val_res.json()
        assert val["valid"] is True
        assert val["onboarding_validation_passed"] is True

        eng = val["normalized_metadata"]["engineering_parameters"]
        assert eng is not None
        assert eng["dam_height"] == 103.0
        assert eng["crest_elevation"] == 665.0
        assert eng["pool_elevation"] == 657.9
        assert eng["manning_n"] == 0.035
        assert abs(eng["freeboard"] - 7.1) < 1e-4

        # Save and verify persistence of engineering parameters
        save_res = client.post(
            "/api/dam-projects",
            files={"dem_file": ("koyna.tif", dem_bytes, "image/tiff")},
            data={**data, "acknowledge_unverified_metadata": "true"},
        )
        assert save_res.status_code == 200
        saved = save_res.json()
        saved_eng = saved["engineering_parameters"]
        assert saved_eng["dam_height"] == 103.0
        assert abs(saved_eng["freeboard"] - 7.1) < 1e-4

    def test_out_of_range_engineering_parameters_warnings(self):
        """Verify warnings for unrealistic manning_n or negative dam_height."""
        dem_bytes = create_test_wgs84_geotiff_bytes()

        files = {"dem_file": ("test.tif", dem_bytes, "image/tiff")}
        data = {
            "project_name": "Extreme Parameters",
            "dam_name": "Extreme Dam",
            "latitude": "17.4005",
            "longitude": "73.7482",
            "dam_height": "-5.0",
            "manning_n": "0.45",
            "crest_elevation": "600.0",
            "pool_elevation": "620.0",  # pool > crest
        }
        res = client.post("/api/dam-projects/validate", files=files, data=data)
        assert res.status_code == 200
        val = res.json()
        # Should flag negative height, high manning_n, and pool > crest
        warn_text = " ".join(val["warnings"]).lower()
        assert "manning" in warn_text or "roughness" in warn_text
        assert "freeboard" in warn_text or "exceeds" in warn_text


class TestPhase18ReadinessAndSpatialEndpoints:
    """Tests for /readiness, /dem/legend, /geometry/dam-marker, and /dem/value."""

    @pytest.fixture
    def saved_minimal_project(self):
        dem_bytes = create_test_wgs84_geotiff_bytes()
        files = {"dem_file": ("koyna.tif", dem_bytes, "image/tiff")}
        data = {
            "project_name": "Ready Test Project",
            "dam_name": "Koyna Dam",
            "latitude": "17.4005",
            "longitude": "73.7482",
            "dam_height": "103.0",
            "crest_elevation": "665.0",
            "pool_elevation": "657.9",
            "acknowledge_unverified_metadata": "true",
        }
        res = client.post("/api/dam-projects", files=files, data=data)
        assert res.status_code == 200
        return res.json()["project_id"]

    def test_get_dam_project_dem_legend(self, saved_minimal_project):
        """Verify dynamic elevation color ramp legend."""
        res = client.get(f"/api/dam-projects/{saved_minimal_project}/dem/legend")
        assert res.status_code == 200
        legend = res.json()
        assert "dem" in legend["id"]
        assert "unverified" in legend["unit_status"] or "metres" in legend["unit_status"]
        assert legend["min_value"] is not None
        assert legend["max_value"] is not None
        assert len(legend["color_ramp"]) >= 3
        assert len(legend["items"]) >= 3

    def test_get_dam_project_readiness_assessment(self, saved_minimal_project):
        """Verify simulation readiness assessment distinguishes screening from full 2D simulation."""
        res = client.get(f"/api/dam-projects/{saved_minimal_project}/readiness")
        assert res.status_code == 200
        readiness = res.json()

        assert readiness["project_id"] == saved_minimal_project
        assert readiness["dam_name"] == "Koyna Dam"
        assert readiness["scientific_status"] == "validated_unverified"
        assert readiness["scientifically_verified"] is False

        # Component flags
        assert readiness["has_dem"] is True
        assert readiness["has_dam_point"] is True
        assert readiness["has_engineering_parameters"] is True
        assert readiness["has_dam_axis"] is False
        assert readiness["has_reservoir_boundary"] is False
        assert readiness["has_model_domain"] is False
        assert readiness["has_downstream_outlet"] is False

        # Operational statuses
        assert readiness["ready_for_screening"] is True
        assert readiness["ready_for_anuga_simulation"] is False

        # Missing components
        assert len(readiness["missing_for_anuga"]) >= 2
        missing_str = " ".join(readiness["missing_for_anuga"]).lower()
        assert "domain" in missing_str or "axis" in missing_str

        # Recommendations
        assert len(readiness["recommended_next_steps"]) >= 1

    def test_get_dam_project_dam_marker_geometry(self, saved_minimal_project):
        """Verify dam marker GeoJSON endpoint returns valid Point feature."""
        res = client.get(f"/api/dam-projects/{saved_minimal_project}/geometry/dam-marker")
        assert res.status_code == 200
        fc = res.json()

        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) == 1

        feat = fc["features"][0]
        assert feat["geometry"]["type"] == "Point"
        coords = feat["geometry"]["coordinates"]
        assert abs(coords[0] - 73.7482) < 1e-4  # lon
        assert abs(coords[1] - 17.4005) < 1e-4  # lat

        props = feat["properties"]
        assert props["dam_name"] == "Koyna Dam"
        assert props["elevation_at_point"] is not None

    def test_get_dam_project_dem_value_point_query(self, saved_minimal_project):
        """Verify sampling elevation value at point coordinates."""
        res = client.get(
            f"/api/dam-projects/{saved_minimal_project}/dem/value",
            params={"lon": 73.7482, "lat": 17.4005},
        )
        assert res.status_code == 200
        data = res.json()
        assert "dem" in data["id"]
        assert data["value"] is not None
        assert data["is_nodata"] is False
        assert 600.0 <= data["value"] <= 750.0

    def test_dam_projects_list_contains_phase18_metadata(self, saved_minimal_project):
        """Verify project listing contains dam_name, dam_point, and scientific_status."""
        res = client.get("/api/dam-projects")
        assert res.status_code == 200
        projects = res.json()
        assert len(projects) >= 1

        target = next((p for p in projects if p["project_id"] == saved_minimal_project), None)
        assert target is not None
        assert target["dam_name"] == "Koyna Dam"
        assert target["scientific_status"] == "validated_unverified"
        assert target["dam_point"] is not None
        assert abs(target["dam_point"]["latitude"] - 17.4005) < 1e-4


class TestPhase18BackwardsCompatibility:
    """Ensure legacy vector onboarding payloads continue to function seamlessly."""

    def test_legacy_payload_with_dam_axis_vector_still_works(self):
        """Verify that providing dam_axis_file along with legacy breach parameters works as expected."""
        dem_bytes = create_test_wgs84_geotiff_bytes()
        axis_coords = [[73.72, 17.42], [73.76, 17.42]]
        axis_bytes = create_dam_axis_geojson(axis_coords)

        files = {
            "dem_file": ("dem.tif", dem_bytes, "image/tiff"),
            "dam_axis_file": ("dam_axis.geojson", axis_bytes, "application/geo+json"),
        }
        data = {
            "project_name": "Legacy Compatibility Project",
            "breach_center_x": "73.74",
            "breach_center_y": "17.42",
            "breach_width": "200",
            "reservoir_level": "650",
            "geometry_crs": "EPSG:4326",
            "acknowledge_unverified_metadata": "true",
        }

        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200, f"Legacy save failed: {save_res.text}"
        proj = save_res.json()

        assert proj["dam_axis_file"] == "dam_axis.geojson"
        assert proj["dam_axis_metadata"] is not None
        assert proj["dam_axis_metadata"]["feature_count"] == 1
        assert proj["scientific_status"] == "validated_unverified"
        assert proj["scientifically_verified"] is False

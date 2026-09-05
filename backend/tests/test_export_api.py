import io
import json
import zipfile
import xml.etree.ElementTree as ET
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.export_service import (
    sanitize_gdf_for_shapefile,
    coords_to_kml_string,
    filter_geojson_features,
)
from app.vector_service import resolve_vector_file
import geopandas as gpd
from shapely.geometry import Point, LineString, Polygon

client = TestClient(app)


def test_sanitize_gdf_for_shapefile():
    """Test column shortening, deterministic names, and complex type sanitization."""
    gdf = gpd.GeoDataFrame(
        {
            "long_column_name_exceeding_ten": ["abc"],
            "long_column_name_exceeding_ten_2": ["def"],
            "nested_dict": [{"a": 1, "b": 2}],
            "nested_list": [["item1", "item2"]],
            "boolean_col": [True],
            "geometry": [Point(74.7, 16.2)],
        },
        crs="EPSG:4326",
    )
    clean_gdf, col_map = sanitize_gdf_for_shapefile(gdf)

    for col in clean_gdf.columns:
        if col != "geometry":
            assert len(col) <= 10

    assert "geometry" in clean_gdf.columns
    # Check that nested dict/list got turned into JSON string
    assert isinstance(clean_gdf["nested_dic"].iloc[0], str)
    assert isinstance(clean_gdf["nested_lis"].iloc[0], str)
    assert int(clean_gdf["boolean_co"].iloc[0]) == 1



def test_coords_to_kml_string():
    """Test KML coordinate generation for Point, LineString, Polygon."""
    # Point
    kml_pt = coords_to_kml_string("Point", [74.7, 16.2])
    assert "<Point><coordinates>74.7,16.2,0</coordinates></Point>" in kml_pt

    # LineString
    kml_line = coords_to_kml_string("LineString", [[74.7, 16.2], [74.8, 16.3]])
    assert "<LineString><tessellate>1</tessellate><coordinates>74.7,16.2,0 74.8,16.3,0</coordinates></LineString>" in kml_line

    # Polygon
    kml_poly = coords_to_kml_string(
        "Polygon", [[[74.7, 16.2], [74.8, 16.2], [74.8, 16.3], [74.7, 16.3], [74.7, 16.2]]]
    )
    assert "<Polygon><outerBoundaryIs><LinearRing><coordinates>" in kml_poly


def test_filter_geojson_features():
    """Test filtering by exposure status."""
    features = [
        {"properties": {"assessed": True, "exposed": True, "title": "feat1"}},
        {"properties": {"assessed": True, "exposed": False, "title": "feat2"}},
        {"properties": {"assessed": False, "exposed": False, "title": "feat3"}},
    ]
    fc = {"type": "FeatureCollection", "features": features}

    # All
    assert len(filter_geojson_features(fc, "all")["features"]) == 3
    # Screening positive
    res_pos = filter_geojson_features(fc, "screening_positive")["features"]
    assert len(res_pos) == 1
    assert res_pos[0]["properties"]["title"] == "feat1"
    # Not exposed
    res_not_exp = filter_geojson_features(fc, "not_exposed")["features"]
    assert len(res_not_exp) == 1
    assert res_not_exp[0]["properties"]["title"] == "feat2"
    # Not assessed
    res_not_ass = filter_geojson_features(fc, "not_assessed")["features"]
    assert len(res_not_ass) == 1
    assert res_not_ass[0]["properties"]["title"] == "feat3"


def test_get_export_route_rejected_with_422():
    """Test that GET /api/export/route is explicitly rejected with 422."""
    res = client.get("/api/export/route")
    assert res.status_code == 422
    assert "Route export is not supported via GET" in res.json()["detail"]


def test_export_invalid_layer_rejected():
    """Test that invalid layers are rejected."""
    res = client.get("/api/export/secret_files")
    assert res.status_code == 422


def test_export_invalid_format_rejected():
    """Test that unsupported formats are rejected."""
    res = client.get("/api/export/assets?format=exe")
    assert res.status_code == 422


@patch("app.export_service.get_exposure_assets")
def test_export_assets_geojson(mock_assets):
    """Test GeoJSON export for assets."""
    mock_assets.return_value = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [74.7, 16.2]},
                "properties": {"category": "healthcare", "assessed": True, "exposed": True},
            }
        ],
    }

    res = client.get("/api/export/assets?format=geojson&exposure_filter=all")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/geo+json"
    data = res.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1


@patch("app.export_service.get_exposure_assets")
def test_export_assets_kml(mock_assets):
    """Test KML export for assets and validate XML structure."""
    mock_assets.return_value = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [74.7, 16.2]},
                "properties": {"category": "healthcare", "assessed": True, "exposed": True, "name": "Hospital <Alpha> & Beta"},
            }
        ],
    }

    res = client.get("/api/export/assets?format=kml&exposure_filter=all")
    assert res.status_code == 200
    assert "application/vnd.google-earth.kml+xml" in res.headers["content-type"]

    # Parse XML content to confirm it's well-formed
    root = ET.fromstring(res.text)
    assert root.tag.endswith("kml")
    assert "Hospital &lt;Alpha&gt; &amp; Beta" in res.text or "Hospital <Alpha> & Beta" in root.find(".//{http://www.opengis.net/kml/2.2}name").text


@patch("app.export_service.get_exposure_assets")
def test_export_assets_shapefile_zip(mock_assets):
    """Test Shapefile ZIP export, verifying all component files and metadata."""
    mock_assets.return_value = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [74.7, 16.2]},
                "properties": {"category": "healthcare", "assessed": True, "exposed": True},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[74.7, 16.2], [74.8, 16.2], [74.8, 16.3], [74.7, 16.3], [74.7, 16.2]]],
                },
                "properties": {"category": "building", "assessed": True, "exposed": False},
            },
        ],
    }

    res = client.get("/api/export/assets?format=shp&exposure_filter=all")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"

    # Open ZIP in memory and inspect contents
    zip_bytes = io.BytesIO(res.content)
    with zipfile.ZipFile(zip_bytes, "r") as zf:
        namelist = zf.namelist()
        # Verify metadata file is present
        assert "README_METADATA.txt" in namelist
        meta_content = zf.read("README_METADATA.txt").decode("utf-8")
        assert "EPSG:4326" in meta_content
        assert "DISCLAIMER" in meta_content
        assert "ATTRIBUTE FIELD MAPPINGS" in meta_content

        # Verify mixed geometry partition into points and polygons
        has_points_shp = any(n.endswith("_points.shp") for n in namelist)
        has_polygons_shp = any(n.endswith("_polygons.shp") for n in namelist)
        assert has_points_shp
        assert has_polygons_shp

        # Verify all shapefile sidecars exist
        for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
            assert any(n.endswith(f"_points{ext}") for n in namelist)


@patch("app.export_service.calculate_screening_route")
def test_post_export_route_geojson(mock_calc):
    """Test POST route export recomputing from RouteScreeningRequest."""
    mock_calc.return_value.route_found = True
    mock_calc.return_value.geojson = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[74.70, 16.20], [74.72, 16.20]]},
        "properties": {"title": "Screened Shortest Route", "total_distance_km": 2.2},
    }

    res = client.post(
        "/api/export/route",
        json={
            "format": "geojson",
            "route_request": {
                "start_lon": 74.70,
                "start_lat": 16.20,
                "end_lon": 74.72,
                "end_lat": 16.20,
                "avoid_screening_positive": True,
            },
        },
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/geo+json"
    data = res.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1


@pytest.mark.skipif(
    resolve_vector_file("assets")[1] is None or not resolve_vector_file("assets")[1].is_file(),
    reason="Local Hidkal dataset not present",
)
def test_real_hidkal_export_integration():
    """Integration test exporting real Hidkal assets dataset."""
    res = client.get("/api/export/assets?format=geojson&exposure_filter=screening_positive")
    assert res.status_code == 200
    data = res.json()
    assert "features" in data

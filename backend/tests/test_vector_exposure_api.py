import os
import json
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds
import networkx as nx
from fastapi.testclient import TestClient

from app.main import app
from app.raster_service import (
    set_registered_datasets,
    reset_registered_datasets,
    clear_cache as clear_raster_cache,
)
from app.vector_service import (
    set_registered_vector_datasets,
    reset_registered_vector_datasets,
    clear_vector_cache,
    categorize_osm_asset,
    normalize_road_highway,
)

client = TestClient(app)


def create_tiny_raster(file_path: Path, data: np.ndarray, nodata: float = -9999.0, crs: str = "EPSG:4326"):
    height, width = data.shape
    transform = from_bounds(74.0, 16.0, 75.0, 17.0, width, height)
    with rasterio.open(
        file_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=data.dtype,
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)


@pytest.fixture
def mock_vector_and_raster_environment(tmp_path: Path):
    """
    Creates temporary mock GeoJSON, GraphML, and rasters in tmp_path.
    Configures registries so tests run isolated from data/raw.
    """
    data_dir = tmp_path / "mock_data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create Mock Rasters (4x4, bounds 74.0-75.0 lon, 16.0-17.0 lat)
    # Depth: Top half wet (col 0,1,2,3 at row 0,1 > 0), bottom half dry (row 2,3 = 0)
    depth_arr = np.array(
        [
            [1.5, 2.5, 3.5, 4.0],
            [2.0, 3.0, 4.5, 5.0],
            [0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    depth_file = data_dir / "mock_depth.tif"
    create_tiny_raster(depth_file, depth_arr, nodata=-9999.0)

    velocity_arr = np.array(
        [
            [0.5, 1.0, 1.5, 2.0],
            [0.8, 1.2, 2.0, 2.5],
            [0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    velocity_file = data_dir / "mock_velocity.tif"
    create_tiny_raster(velocity_file, velocity_arr, nodata=-9999.0)

    arrival_arr = np.array(
        [
            [10.0, 15.0, 20.0, 25.0],
            [12.0, 18.0, 22.0, 28.0],
            [9999.0, 9999.0, 9999.0, 9999.0],
            [9999.0, 9999.0, 9999.0, 9999.0],
        ],
        dtype=np.float32,
    )
    arrival_file = data_dir / "mock_arrival.tif"
    create_tiny_raster(arrival_file, arrival_arr, nodata=-9999.0)

    dem_arr = np.array(
        [
            [610.0, 620.0, 630.0, 640.0],
            [615.0, 625.0, 635.0, 645.0],
            [620.0, 630.0, 640.0, 650.0],
            [625.0, 635.0, 645.0, 655.0],
        ],
        dtype=np.float32,
    )
    dem_file = data_dir / "mock_dem.tif"
    create_tiny_raster(dem_file, dem_arr, nodata=-9999.0)

    # 2. Create Mock GeoJSON Assets (7 features representing different categories and locations)
    # (x, y) coordinates in top-half (lat > 16.5) are flooded (exposed), bottom-half (lat < 16.5) are dry (not exposed)
    assets_data = {
        "type": "FeatureCollection",
        "features": [
            # Healthcare (Flooded, Point)
            {
                "type": "Feature",
                "id": "node/1",
                "geometry": {"type": "Point", "coordinates": [74.2, 16.8]},
                "properties": {"amenity": "hospital", "name": "Community Hospital"},
            },
            # Education (Dry, Polygon)
            {
                "type": "Feature",
                "id": "way/2",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[74.2, 16.2], [74.3, 16.2], [74.3, 16.3], [74.2, 16.3], [74.2, 16.2]]],
                },
                "properties": {"amenity": "school", "name": "Primary School"},
            },
            # Emergency (Flooded, Point)
            {
                "type": "Feature",
                "id": "node/3",
                "geometry": {"type": "Point", "coordinates": [74.6, 16.7]},
                "properties": {"amenity": "fire_station", "name": "Fire Station 1"},
            },
            # Settlement (Dry, Point)
            {
                "type": "Feature",
                "id": "node/4",
                "geometry": {"type": "Point", "coordinates": [74.8, 16.1]},
                "properties": {"place": "village", "name": "River Village"},
            },
            # Transport (Flooded, LineString)
            {
                "type": "Feature",
                "id": "way/5",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[74.1, 16.7], [74.5, 16.7]],
                },
                "properties": {"highway": "primary", "bridge": "yes"},
            },
            # Building (Flooded, Polygon)
            {
                "type": "Feature",
                "id": "way/6",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[74.6, 16.6], [74.7, 16.6], [74.7, 16.7], [74.6, 16.7], [74.6, 16.6]]],
                },
                "properties": {"building": "yes"},
            },
            # Other (Dry, Point)
            {
                "type": "Feature",
                "id": "node/7",
                "geometry": {"type": "Point", "coordinates": [74.5, 16.2]},
                "properties": {"amenity": "place_of_worship", "name": "Old Temple"},
            },
        ],
    }
    assets_file = data_dir / "mock_assets.geojson"
    with open(assets_file, "w", encoding="utf-8") as f:
        json.dump(assets_data, f)

    # 3. Create Mock GraphML Roads
    # 4 nodes and 3 edges: one with WKT geometry in wet zone, one without WKT in wet zone, one in dry zone
    G = nx.MultiDiGraph()
    G.add_node("n1", x="74.1", y="16.8", street_count="2")
    G.add_node("n2", x="74.4", y="16.8", street_count="3")
    G.add_node("n3", x="74.2", y="16.2", street_count="2")
    G.add_node("n4", x="74.6", y="16.2", street_count="2")

    # Edge 1: Flooded with explicit geometry
    G.add_edge(
        "n1",
        "n2",
        key=0,
        osmid="101",
        highway="primary",
        length="500",
        geometry="LINESTRING (74.1 16.8, 74.25 16.85, 74.4 16.8)",
    )
    # Edge 2: Flooded without geometry (uses node x/y)
    G.add_edge(
        "n1",
        "n2",
        key=1,
        osmid="102",
        highway="residential",
        length="450",
    )
    # Edge 3: Dry without geometry (lat=16.2)
    G.add_edge(
        "n3",
        "n4",
        key=0,
        osmid="103",
        highway="tertiary",
        length="800",
    )

    roads_file = data_dir / "mock_roads.graphml"
    nx.write_graphml(G, str(roads_file))

    # Configure mock registries
    os.environ["SIH_PROJECT_ROOT"] = str(tmp_path)

    test_rasters = {
        "dem": {"label": "Test DEM", "relative_path": "mock_data/mock_dem.tif", "data_type": "elevation", "unit_status": "unverified", "provenance_status": "test"},
        "depth": {"label": "Test Depth", "relative_path": "mock_data/mock_depth.tif", "data_type": "depth", "unit_status": "unverified", "provenance_status": "test"},
        "velocity": {"label": "Test Velocity", "relative_path": "mock_data/mock_velocity.tif", "data_type": "velocity", "unit_status": "unverified", "provenance_status": "test"},
        "arrival": {"label": "Test Arrival", "relative_path": "mock_data/mock_arrival.tif", "data_type": "arrival_time", "unit_status": "unverified", "provenance_status": "test"},
    }
    set_registered_datasets(test_rasters)

    test_vectors = {
        "assets": {"label": "Test Assets", "relative_path": "mock_data/mock_assets.geojson", "format": "geojson"},
        "roads": {"label": "Test Roads", "relative_path": "mock_data/mock_roads.graphml", "format": "graphml"},
    }
    set_registered_vector_datasets(test_vectors)

    yield {
        "tmp_path": tmp_path,
        "assets_file": assets_file,
        "roads_file": roads_file,
    }

    # Teardown
    reset_registered_datasets()
    reset_registered_vector_datasets()
    if "SIH_PROJECT_ROOT" in os.environ:
        del os.environ["SIH_PROJECT_ROOT"]


def test_categorize_osm_asset():
    """Test OSM property categorization into the 7 required categories."""
    assert categorize_osm_asset({"amenity": "hospital"}) == "healthcare"
    assert categorize_osm_asset({"healthcare": "clinic"}) == "healthcare"
    assert categorize_osm_asset({"building": "hospital"}) == "healthcare"

    assert categorize_osm_asset({"amenity": "school"}) == "education"
    assert categorize_osm_asset({"building": "college"}) == "education"

    assert categorize_osm_asset({"amenity": "fire_station"}) == "emergency"
    assert categorize_osm_asset({"emergency": "phone"}) == "emergency"

    assert categorize_osm_asset({"place": "village"}) == "settlement"
    assert categorize_osm_asset({"place": "town"}) == "settlement"

    assert categorize_osm_asset({"highway": "primary"}) == "transport"
    assert categorize_osm_asset({"railway": "rail"}) == "transport"
    assert categorize_osm_asset({"amenity": "bus_station"}) == "transport"

    assert categorize_osm_asset({"building": "yes"}) == "building"
    assert categorize_osm_asset({"building": "house"}) == "building"

    assert categorize_osm_asset({"amenity": "place_of_worship"}) == "other"
    assert categorize_osm_asset({}) == "other"


def test_normalize_road_highway():
    """Test highway normalization."""
    assert normalize_road_highway({"highway": "primary"}) == "primary"
    assert normalize_road_highway({"highway": "tertiary"}) == "tertiary"
    assert normalize_road_highway({"highway": "['unclassified', 'tertiary']"}) == "unclassified"
    assert normalize_road_highway({"highway": ["secondary", "residential"]}) == "secondary"
    assert normalize_road_highway({}) == "unclassified"


def test_get_raw_assets(mock_vector_and_raster_environment):
    """GET /api/assets returns valid GeoJSON with category attached and no filesystem paths."""
    res = client.get("/api/assets")
    assert res.status_code == 200
    data = res.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 7

    for feat in data["features"]:
        assert "geometry" in feat
        assert "properties" in feat
        assert "category" in feat["properties"]
        # Security: No path leakage
        for k, v in feat["properties"].items():
            if isinstance(v, str):
                assert ":\\" not in v
                assert "/mock_data" not in v


def test_get_raw_roads(mock_vector_and_raster_environment):
    """GET /api/roads returns valid GeoJSON LineStrings converted from GraphML."""
    res = client.get("/api/roads")
    assert res.status_code == 200
    data = res.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 3

    for feat in data["features"]:
        assert feat["geometry"]["type"] == "LineString"
        assert len(feat["geometry"]["coordinates"]) >= 2
        assert "category" in feat["properties"]
        assert "u" in feat["properties"]
        assert "v" in feat["properties"]


def test_get_exposure_assets(mock_vector_and_raster_environment):
    """
    GET /api/exposure/assets returns GeoJSON with preliminary exposure screening attributes:
    assessed, exposed, depth_value, velocity_value, arrival_value, sampling_method.
    """
    res = client.get("/api/exposure/assets")
    assert res.status_code == 200
    data = res.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 7

    exposed_count = 0
    not_exposed_count = 0

    for feat in data["features"]:
        props = feat["properties"]
        assert "assessed" in props
        assert props["assessed"] is True
        assert "exposed" in props
        assert "depth_value" in props
        assert "velocity_value" in props
        assert "arrival_value" in props
        assert "sampling_method" in props
        assert "category" in props
        assert "preliminary_screening_note" in props

        if props["exposed"]:
            exposed_count += 1
            assert props["depth_value"] > 0
        else:
            not_exposed_count += 1
            assert props["depth_value"] == 0.0

    # 4 flooded assets (lat > 16.5) and 3 dry assets (lat < 16.5)
    assert exposed_count == 4
    assert not_exposed_count == 3


def test_get_exposure_roads(mock_vector_and_raster_environment):
    """
    GET /api/exposure/roads returns GeoJSON with road exposure flags.
    """
    res = client.get("/api/exposure/roads")
    assert res.status_code == 200
    data = res.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 3

    exposed_roads = [f for f in data["features"] if f["properties"]["exposed"]]
    dry_roads = [f for f in data["features"] if not f["properties"]["exposed"]]

    assert len(exposed_roads) == 2  # Edge 1 (primary) and Edge 2 (residential) at lat=16.8
    assert len(dry_roads) == 1      # Edge 3 (tertiary) at lat=16.2

    for f in exposed_roads:
        assert f["properties"]["assessed"] is True
        assert f["properties"]["depth_value"] > 0
        assert f["properties"]["sampling_method"] == "line_midpoint"


def test_get_exposure_summary(mock_vector_and_raster_environment):
    """
    GET /api/exposure/summary returns consistent totals, counts, and category breakdowns.
    """
    res = client.get("/api/exposure/summary")
    assert res.status_code == 200
    summary = res.json()

    assert "disclaimer" in summary
    assert "preliminary" in summary["disclaimer"].lower()
    assert "assets" in summary
    assert "roads" in summary

    # Asset summary checks
    assets = summary["assets"]
    assert assets["total"] == 7
    assert assets["assessed"] == 7
    assert assets["exposed"] == 4
    assert assets["not_exposed"] == 3
    assert assets["not_assessed"] == 0

    # Consistency math
    assert assets["total"] == assets["assessed"] + assets["not_assessed"]
    assert assets["assessed"] == assets["exposed"] + assets["not_exposed"]

    # Category breakdown checks
    cat_counts = assets["by_category"]
    assert cat_counts["healthcare"]["exposed"] == 1
    assert cat_counts["education"]["exposed"] == 0
    assert cat_counts["education"]["not_exposed"] == 1
    assert cat_counts["emergency"]["exposed"] == 1
    assert cat_counts["building"]["exposed"] == 1
    assert cat_counts["transport"]["exposed"] == 1
    assert cat_counts["settlement"]["exposed"] == 0
    assert cat_counts["other"]["exposed"] == 0

    # Category sum matches total
    sum_cat_total = sum(c["total"] for c in cat_counts.values())
    sum_cat_exposed = sum(c["exposed"] for c in cat_counts.values())
    assert sum_cat_total == assets["total"]
    assert sum_cat_exposed == assets["exposed"]

    # Road summary checks
    roads = summary["roads"]
    assert roads["total"] == 3
    assert roads["assessed"] == 3
    assert roads["exposed"] == 2
    assert roads["not_exposed"] == 1
    assert roads["not_assessed"] == 0


def test_missing_raster_data_graceful_fallback(mock_vector_and_raster_environment):
    """When rasters are missing, vector endpoints still respond with assessed: false."""
    # Temporarily point rasters to non-existent files
    set_registered_datasets({
        "dem": {"label": "None", "relative_path": "mock_data/non_existent_dem.tif", "data_type": "elevation", "unit_status": "unverified", "provenance_status": "test"},
        "depth": {"label": "None", "relative_path": "mock_data/non_existent_depth.tif", "data_type": "depth", "unit_status": "unverified", "provenance_status": "test"},
        "velocity": {"label": "None", "relative_path": "mock_data/non_existent_vel.tif", "data_type": "velocity", "unit_status": "unverified", "provenance_status": "test"},
        "arrival": {"label": "None", "relative_path": "mock_data/non_existent_arr.tif", "data_type": "arrival_time", "unit_status": "unverified", "provenance_status": "test"},
    })
    clear_vector_cache()

    res = client.get("/api/exposure/assets")
    assert res.status_code == 200
    data = res.json()
    assert len(data["features"]) == 7
    for f in data["features"]:
        assert f["properties"]["assessed"] is False
        assert f["properties"]["exposed"] is False
        assert f["properties"]["depth_value"] is None

    summary_res = client.get("/api/exposure/summary")
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["assets"]["total"] == 7
    assert summary["assets"]["assessed"] == 0
    assert summary["assets"]["not_assessed"] == 7
    assert summary["assets"]["exposed"] == 0


# Real Hidkal integration test (skipped when data/raw is absent)
HIDKAL_ASSETS_PATH = Path(__file__).resolve().parents[2] / "data" / "raw" / "data_hidkal" / "hidkal_assets.geojson"
HIDKAL_ROADS_PATH = Path(__file__).resolve().parents[2] / "data" / "raw" / "data_hidkal" / "hidkal_roads.graphml"


@pytest.mark.skipif(not (HIDKAL_ASSETS_PATH.exists() and HIDKAL_ROADS_PATH.exists()), reason="Local Hidkal dataset is not present in data/raw")
def test_real_hidkal_vector_exposure_integration():
    """
    Integration test on actual Hidkal data:
    513 assets and 8,047 road edges with real depth, velocity, and arrival rasters.
    """
    reset_registered_datasets()
    reset_registered_vector_datasets()

    # 1. Assets raw endpoint
    res_assets = client.get("/api/assets")
    assert res_assets.status_code == 200
    assets_data = res_assets.json()
    assert len(assets_data["features"]) == 513

    # 2. Roads raw endpoint
    res_roads = client.get("/api/roads")
    assert res_roads.status_code == 200
    roads_data = res_roads.json()
    assert len(roads_data["features"]) == 8047

    # 3. Assets exposure endpoint
    res_exp_assets = client.get("/api/exposure/assets")
    assert res_exp_assets.status_code == 200
    exp_assets = res_exp_assets.json()
    assert len(exp_assets["features"]) == 513

    # 4. Roads exposure endpoint
    res_exp_roads = client.get("/api/exposure/roads")
    assert res_exp_roads.status_code == 200
    exp_roads = res_exp_roads.json()
    assert len(exp_roads["features"]) == 8047

    # 5. Summary endpoint
    res_summary = client.get("/api/exposure/summary")
    assert res_summary.status_code == 200
    summary = res_summary.json()

    assert summary["assets"]["total"] == 513
    assert summary["assets"]["assessed"] == 513
    assert summary["assets"]["exposed"] == 135
    assert summary["assets"]["not_exposed"] == 378
    assert summary["assets"]["not_assessed"] == 0

    assert summary["roads"]["total"] == 8047
    assert summary["roads"]["assessed"] == 8045
    assert summary["roads"]["exposed"] == 2060
    assert summary["roads"]["not_exposed"] == 5985
    assert summary["roads"]["not_assessed"] == 2

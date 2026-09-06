import os
import json
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds
from fastapi.testclient import TestClient

from app.main import app
from app.raster_service import (
    set_registered_datasets,
    reset_registered_datasets,
)
from app.vector_service import (
    set_registered_vector_datasets,
    reset_registered_vector_datasets,
)
from app.damage_service import (
    interpolate_damage_ratio,
    DamageCurvePoint,
    DEFAULT_REPLACEMENT_VALUES,
    DEFAULT_DEPTH_DAMAGE_CURVE,
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
def mock_damage_environment(tmp_path: Path):
    """
    Creates temporary mock rasters and assets GeoJSON in tmp_path.
    """
    data_dir = tmp_path / "mock_data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Mock Depth raster: 4x4
    depth_arr = np.array(
        [
            [1.0, 2.0, 3.0, 4.0],
            [0.5, 1.5, 2.5, 0.0],
            [0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    depth_file = data_dir / "mock_depth.tif"
    create_tiny_raster(depth_file, depth_arr, nodata=-9999.0)

    # Mock Velocity raster
    velocity_arr = np.zeros((4, 4), dtype=np.float32)
    velocity_file = data_dir / "mock_velocity.tif"
    create_tiny_raster(velocity_file, velocity_arr, nodata=-9999.0)

    # Mock Arrival raster
    arrival_arr = np.full((4, 4), 9999.0, dtype=np.float32)
    arrival_file = data_dir / "mock_arrival.tif"
    create_tiny_raster(arrival_file, arrival_arr, nodata=-9999.0)

    # Mock DEM raster
    dem_arr = np.full((4, 4), 620.0, dtype=np.float32)
    dem_file = data_dir / "mock_dem.tif"
    create_tiny_raster(dem_file, dem_arr, nodata=-9999.0)

    # Mock Assets GeoJSON (3 assets: 1 building at depth 2.0, 1 healthcare at depth 0.0, 1 education at depth 3.0)
    assets_data = {
        "type": "FeatureCollection",
        "features": [
            # Building at col=1, row=0 -> depth = 2.0
            {
                "type": "Feature",
                "id": "node/1",
                "geometry": {"type": "Point", "coordinates": [74.375, 16.875]},
                "properties": {"building": "yes", "name": "Residential Building"},
            },
            # Healthcare at col=1, row=2 -> depth = 0.0 (dry)
            {
                "type": "Feature",
                "id": "node/2",
                "geometry": {"type": "Point", "coordinates": [74.375, 16.375]},
                "properties": {"amenity": "hospital", "name": "Local Clinic"},
            },
            # Education at col=2, row=0 -> depth = 3.0
            {
                "type": "Feature",
                "id": "node/3",
                "geometry": {"type": "Point", "coordinates": [74.625, 16.875]},
                "properties": {"amenity": "school", "name": "High School"},
            },
        ],
    }
    assets_file = data_dir / "mock_assets.geojson"
    with open(assets_file, "w", encoding="utf-8") as f:
        json.dump(assets_data, f)

    # Mock roads (empty graph for damage test isolation)
    import networkx as nx
    G = nx.MultiDiGraph()
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
    }

    # Teardown
    reset_registered_datasets()
    reset_registered_vector_datasets()
    if "SIH_PROJECT_ROOT" in os.environ:
        del os.environ["SIH_PROJECT_ROOT"]


def test_interpolate_damage_ratio():
    """Test piecewise linear depth-damage interpolation function."""
    curve = [
        DamageCurvePoint(depth=0.0, damage_ratio=0.0),
        DamageCurvePoint(depth=1.0, damage_ratio=0.20),
        DamageCurvePoint(depth=3.0, damage_ratio=0.60),
        DamageCurvePoint(depth=5.0, damage_ratio=1.00),
    ]

    # Zero / negative depth
    assert interpolate_damage_ratio(0.0, curve) == 0.0
    assert interpolate_damage_ratio(-1.0, curve) == 0.0

    # Exact stops
    assert interpolate_damage_ratio(1.0, curve) == pytest.approx(0.20)
    assert interpolate_damage_ratio(3.0, curve) == pytest.approx(0.60)
    assert interpolate_damage_ratio(5.0, curve) == pytest.approx(1.00)

    # In-between interpolation
    # depth=0.5 -> 0.0 + 0.5 * 0.20 = 0.10
    assert interpolate_damage_ratio(0.5, curve) == pytest.approx(0.10)
    # depth=2.0 -> 0.20 + (1.0/2.0) * (0.60 - 0.20) = 0.40
    assert interpolate_damage_ratio(2.0, curve) == pytest.approx(0.40)

    # Above max depth -> capped at 1.0
    assert interpolate_damage_ratio(10.0, curve) == pytest.approx(1.00)


def test_get_damage_config():
    """GET /api/damage/config returns editable defaults with required categories and disclaimer."""
    res = client.get("/api/damage/config")
    assert res.status_code == 200
    config = res.json()

    assert "assumed_depth_unit" in config
    assert "currency_label" in config
    assert "replacement_values" in config
    assert "depth_damage_curve" in config
    assert "sensitivity_percentage" in config
    assert "disclaimer" in config
    assert "methodology" in config

    # Required asset categories
    expected_categories = {"building", "healthcare", "education", "emergency", "settlement", "transport", "other"}
    assert expected_categories.issubset(set(config["replacement_values"].keys()))
    assert len(config["depth_damage_curve"]) >= 2
    assert config["sensitivity_percentage"] == 20.0


def test_damage_estimate_unacknowledged_rejected(mock_damage_environment):
    """POST /api/damage/estimate rejects calculation with 422 if acknowledge_unverified_inputs is False."""
    payload = {
        "replacement_values": DEFAULT_REPLACEMENT_VALUES,
        "depth_damage_curve": [p.model_dump() for p in DEFAULT_DEPTH_DAMAGE_CURVE],
        "sensitivity_percentage": 20.0,
        "acknowledge_unverified_inputs": False,
    }
    res = client.post("/api/damage/estimate", json=payload)
    assert res.status_code == 422
    assert "explicit user acknowledgement" in res.json()["detail"].lower()


def test_damage_estimate_deterministic_calculation(mock_damage_environment):
    """
    POST /api/damage/estimate calculates deterministic losses on mock assets.
    Mock assets:
      - Building: depth 2.0 (curve: 1.5 -> 0.40, 3.0 -> 0.70; at 2.0 ratio = 0.40 + 0.5/1.5 * 0.30 = 0.50)
        Value = 2,500,000 -> Loss = 0.50 * 2,500,000 = 1,250,000
      - Healthcare: depth 0.0 (dry) -> Loss = 0
      - Education: depth 3.0 (curve: 3.0 -> 0.70)
        Value = 8,000,000 -> Loss = 0.70 * 8,000,000 = 5,600,000
      - Total Base Loss = 1,250,000 + 5,600,000 = 6,850,000
      - Low Loss (-20%) = 6,850,000 * 0.8 = 5,480,000
      - High Loss (+20%) = 6,850,000 * 1.2 = 8,220,000
    """
    payload = {
        "assumed_depth_unit": "assumed meters (unverified)",
        "currency_label": "INR (₹)",
        "replacement_values": DEFAULT_REPLACEMENT_VALUES,
        "depth_damage_curve": [p.model_dump() for p in DEFAULT_DEPTH_DAMAGE_CURVE],
        "sensitivity_percentage": 20.0,
        "acknowledge_unverified_inputs": True,
    }
    res = client.post("/api/damage/estimate", json=payload)
    assert res.status_code == 200
    data = res.json()

    # Total loss checks
    totals = data["total_estimates"]
    assert totals["base_loss"] == pytest.approx(6850000.0)
    assert totals["low_loss"] == pytest.approx(5480000.0)
    assert totals["high_loss"] == pytest.approx(8220000.0)

    # Asset counts
    counts = data["asset_counts"]
    assert counts["total_assets"] == 3
    assert counts["assessed_assets"] == 3
    assert counts["screening_positive_assets"] == 2
    assert counts["not_exposed_assets"] == 1
    assert counts["not_assessed_assets"] == 0

    # Category breakdown
    by_cat = data["by_category"]
    assert by_cat["building"]["base_loss"] == pytest.approx(1250000.0)
    assert by_cat["building"]["screening_positive_count"] == 1
    assert by_cat["healthcare"]["base_loss"] == pytest.approx(0.0)
    assert by_cat["healthcare"]["screening_positive_count"] == 0
    assert by_cat["education"]["base_loss"] == pytest.approx(5600000.0)
    assert by_cat["education"]["screening_positive_count"] == 1

    # Warnings and disclaimer
    assert "disclaimer" in data
    assert "methodology" in data
    assert len(data["warnings"]) >= 2


def test_damage_estimate_validation_rules():
    """Test validation errors for invalid curve and inputs."""
    # 1. Negative replacement value
    payload = {
        "replacement_values": {"building": -500.0},
        "depth_damage_curve": [{"depth": 0.0, "damage_ratio": 0.0}, {"depth": 1.0, "damage_ratio": 1.0}],
        "acknowledge_unverified_inputs": True,
    }
    res = client.post("/api/damage/estimate", json=payload)
    assert res.status_code == 422

    # 2. Sensitivity > 100
    payload["replacement_values"] = {"building": 1000.0}
    payload["sensitivity_percentage"] = 150.0
    res = client.post("/api/damage/estimate", json=payload)
    assert res.status_code == 422

    # 3. Non-ascending depth curve
    payload["sensitivity_percentage"] = 20.0
    payload["depth_damage_curve"] = [{"depth": 2.0, "damage_ratio": 0.0}, {"depth": 1.0, "damage_ratio": 1.0}]
    res = client.post("/api/damage/estimate", json=payload)
    assert res.status_code == 422

    # 4. Non-monotonic damage ratio (decreasing damage ratio)
    payload["depth_damage_curve"] = [{"depth": 0.0, "damage_ratio": 0.8}, {"depth": 2.0, "damage_ratio": 0.2}]
    res = client.post("/api/damage/estimate", json=payload)
    assert res.status_code == 422

    # 5. Curve with fewer than 2 points
    payload["depth_damage_curve"] = [{"depth": 0.0, "damage_ratio": 0.0}]
    res = client.post("/api/damage/estimate", json=payload)
    assert res.status_code == 422


HIDKAL_ASSETS_PATH = Path(__file__).resolve().parents[2] / "data" / "raw" / "data_hidkal" / "hidkal_assets.geojson"


@pytest.mark.skipif(not HIDKAL_ASSETS_PATH.exists(), reason="Local Hidkal dataset is not present in data/raw")
def test_real_hidkal_damage_scenario_integration():
    """
    Integration test using actual Hidkal screening assets:
    Validates damage estimation on 513 assets and ensures no crash or NaN.
    """
    reset_registered_datasets()
    reset_registered_vector_datasets()

    payload = {
        "assumed_depth_unit": "assumed meters (unverified)",
        "currency_label": "INR (₹)",
        "replacement_values": DEFAULT_REPLACEMENT_VALUES,
        "depth_damage_curve": [p.model_dump() for p in DEFAULT_DEPTH_DAMAGE_CURVE],
        "sensitivity_percentage": 20.0,
        "acknowledge_unverified_inputs": True,
    }
    res = client.post("/api/damage/estimate", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert data["asset_counts"]["total_assets"] == 513
    assert data["asset_counts"]["screening_positive_assets"] == 135
    assert data["total_estimates"]["base_loss"] > 0
    assert data["total_estimates"]["low_loss"] < data["total_estimates"]["base_loss"]
    assert data["total_estimates"]["high_loss"] > data["total_estimates"]["base_loss"]

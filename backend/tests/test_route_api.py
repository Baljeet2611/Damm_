import pytest
from unittest.mock import patch
import networkx as nx
from shapely.geometry import LineString
from shapely import wkt
from fastapi.testclient import TestClient

from app.main import app
from app.route_service import (
    haversine_distance,
    find_nearest_node,
    calculate_screening_route,
    clear_route_cache,
)
from app.schemas import RouteScreeningRequest
from app.vector_service import resolve_vector_file

client = TestClient(app)


def create_mock_road_graph() -> nx.MultiDiGraph:
    """
    Create a mock road network graph for testing:
    Node A (74.70, 16.20) -> Node B (74.71, 16.20) -> Node C (74.72, 16.20)
    Node A (74.70, 16.20) -> Node D (74.70, 16.21) -> Node C (74.72, 16.20)
    """
    G = nx.MultiDiGraph()
    G.add_node("A", x=74.70, y=16.20)
    G.add_node("B", x=74.71, y=16.20)
    G.add_node("C", x=74.72, y=16.20)
    G.add_node("D", x=74.70, y=16.21)

    # Edge A->B: length 1000m
    G.add_edge("A", "B", key=0, length=1000.0, highway="primary")
    # Edge B->C: length 1000m (flooded edge in tests)
    G.add_edge("B", "C", key=0, length=1000.0, highway="primary")
    # Edge A->D: length 1500m
    G.add_edge("A", "D", key=0, length=1500.0, highway="secondary")
    # Edge D->C: length 1500m
    G.add_edge("D", "C", key=0, length=1500.0, highway="secondary")

    return G


def test_haversine_distance():
    """Test haversine calculation between known points."""
    # Approx distance for 0.01 deg lon at lat 16.2 is ~1070 meters
    d = haversine_distance(74.70, 16.20, 74.71, 16.20)
    assert 1000 < d < 1200
    # Same point distance is 0
    assert haversine_distance(74.70, 16.20, 74.70, 16.20) == 0.0


def test_find_nearest_node():
    """Test nearest node lookup and snapping distance."""
    nodes_data = [
        ("A", 74.70, 16.20),
        ("B", 74.71, 16.20),
        ("C", 74.72, 16.20),
    ]
    node_id, snap_lon, snap_lat, snap_dist = find_nearest_node(74.7001, 16.2001, nodes_data)
    assert node_id == "A"
    assert snap_lon == 74.70
    assert snap_lat == 16.20
    assert snap_dist < 50.0


def test_route_coordinate_bounds_validation():
    """Test rejection of invalid lat/lon coordinates."""
    res = client.post(
        "/api/routes/screening",
        json={
            "start_lon": 200.0,  # Invalid lon
            "start_lat": 16.20,
            "end_lon": 74.72,
            "end_lat": 16.20,
        },
    )
    assert res.status_code == 422


@patch("app.route_service.load_routing_graph")
@patch("app.route_service.get_exposure_roads")
def test_route_max_snap_distance_rejection(mock_exposure, mock_load):
    """Test rejection of coordinates exceeding max_snap_distance_meters."""
    G = create_mock_road_graph()
    nodes_data = [("A", 74.70, 16.20), ("B", 74.71, 16.20), ("C", 74.72, 16.20), ("D", 74.70, 16.21)]
    mock_load.return_value = (G, nodes_data)
    mock_exposure.return_value = {"type": "FeatureCollection", "features": []}

    # Point very far from graph (e.g. 75.50, 18.00) with default max_snap=5000m
    res = client.post(
        "/api/routes/screening",
        json={
            "start_lon": 75.50,
            "start_lat": 18.00,
            "end_lon": 74.72,
            "end_lat": 16.20,
            "max_snap_distance_meters": 5000.0,
        },
    )
    assert res.status_code == 422
    assert "exceeds maximum allowable snap distance" in res.json()["detail"]


@patch("app.route_service.load_routing_graph")
@patch("app.route_service.get_exposure_roads")
def test_shortest_path_avoiding_flooded_edges(mock_exposure, mock_load):
    """
    Test shortest path routing avoiding flooded edges:
    Path A->B->C is 2000m.
    If edge B->C is exposed/flooded, routing takes detour A->D->C (3000m).
    """
    G = create_mock_road_graph()
    nodes_data = [("A", 74.70, 16.20), ("B", 74.71, 16.20), ("C", 74.72, 16.20), ("D", 74.70, 16.21)]
    mock_load.return_value = (G, nodes_data)

    # Mock exposure result: edge B->C (key=0) is screening-positive (depth > 0 at sample)
    mock_exposure.return_value = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[74.71, 16.20], [74.72, 16.20]]},
                "properties": {"u": "B", "v": "C", "key": 0, "exposed": True},
            }
        ],
    }

    # 1. With avoid_screening_positive=True -> takes detour A->D->C
    req = RouteScreeningRequest(
        start_lon=74.70,
        start_lat=16.20,
        end_lon=74.72,
        end_lat=16.20,
        avoid_screening_positive=True,
    )
    resp = calculate_screening_route(req)
    assert resp.route_found is True
    assert resp.total_distance_meters == 3000.0
    assert resp.segment_count == 2
    assert resp.geojson is not None
    assert resp.geojson["geometry"]["type"] == "LineString"
    assert len(resp.geojson["geometry"]["coordinates"]) >= 3

    # 2. With avoid_screening_positive=False -> takes shorter route A->B->C
    req_no_avoid = RouteScreeningRequest(
        start_lon=74.70,
        start_lat=16.20,
        end_lon=74.72,
        end_lat=16.20,
        avoid_screening_positive=False,
    )
    resp_no_avoid = calculate_screening_route(req_no_avoid)
    assert resp_no_avoid.route_found is True
    assert resp_no_avoid.total_distance_meters == 2000.0


@patch("app.route_service.load_routing_graph")
@patch("app.route_service.get_exposure_roads")
def test_no_route_when_all_paths_flooded(mock_exposure, mock_load):
    """Test fallback when all paths to destination are flooded."""
    G = create_mock_road_graph()
    nodes_data = [("A", 74.70, 16.20), ("B", 74.71, 16.20), ("C", 74.72, 16.20), ("D", 74.70, 16.21)]
    mock_load.return_value = (G, nodes_data)

    # Both B->C and D->C are exposed/flooded
    mock_exposure.return_value = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[74.71, 16.20], [74.72, 16.20]]},
                "properties": {"u": "B", "v": "C", "key": 0, "exposed": True},
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[74.70, 16.21], [74.72, 16.20]]},
                "properties": {"u": "D", "v": "C", "key": 0, "exposed": True},
            },
        ],
    }

    req = RouteScreeningRequest(
        start_lon=74.70,
        start_lat=16.20,
        end_lon=74.72,
        end_lat=16.20,
        avoid_screening_positive=True,
    )
    resp = calculate_screening_route(req)
    assert resp.route_found is False
    assert resp.geojson is None
    assert len(resp.warnings) > 0


@pytest.mark.skipif(
    resolve_vector_file("roads")[1] is None or not resolve_vector_file("roads")[1].is_file(),
    reason="Local Hidkal dataset not present",
)
def test_real_hidkal_route_screening_integration():
    """Integration test with real Hidkal GraphML dataset if present."""
    clear_route_cache()
    # Coordinates inside Hidkal road network extent
    res = client.post(
        "/api/routes/screening",
        json={
            "start_lon": 74.71,
            "start_lat": 16.21,
            "end_lon": 74.73,
            "end_lat": 16.23,
            "avoid_screening_positive": True,
            "max_snap_distance_meters": 5000.0,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "route_found" in data
    assert "disclaimer" in data
    assert "methodology" in data

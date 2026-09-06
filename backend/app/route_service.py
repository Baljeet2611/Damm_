import math
from typing import List, Tuple, Optional
import networkx as nx
from shapely import wkt
from shapely.geometry import LineString, mapping
from fastapi import HTTPException

from app.schemas import RouteScreeningRequest, RouteScreeningResponse
from app.vector_service import resolve_vector_file, get_exposure_roads

# Cache for routing graph and spatial index
_graph_cache: Optional[Tuple[float, nx.Graph, List[Tuple[str, float, float]]]] = None


def clear_route_cache() -> None:
    """Clear in-memory routing graph cache."""
    global _graph_cache
    _graph_cache = None


def haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """
    Calculate the great circle distance between two points
    on the earth in meters using the spherical Haversine formula.
    """
    r = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def load_routing_graph() -> Tuple[nx.Graph, List[Tuple[str, float, float]]]:
    """
    Load NetworkX graph from registered roads dataset and build node coordinate list.
    Caches parsed graph by file mtime.
    """
    global _graph_cache
    info, file_path = resolve_vector_file("roads")
    if info is None or file_path is None or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Roads dataset is not available for route screening")

    mtime = file_path.stat().st_mtime
    if _graph_cache is not None and _graph_cache[0] == mtime:
        return _graph_cache[1], _graph_cache[2]

    G = nx.read_graphml(str(file_path))
    nodes_data: List[Tuple[str, float, float]] = []
    for n, d in G.nodes(data=True):
        try:
            x = float(d.get("x", 0.0))
            y = float(d.get("y", 0.0))
            nodes_data.append((str(n), x, y))
        except (ValueError, TypeError):
            continue

    if not nodes_data:
        raise HTTPException(status_code=500, detail="Road graph contains no valid spatial nodes")

    _graph_cache = (mtime, G, nodes_data)
    return G, nodes_data


def find_nearest_node(
    lon: float, lat: float, nodes_data: List[Tuple[str, float, float]]
) -> Tuple[str, float, float, float]:
    """
    Find the closest graph node to (lon, lat) using Haversine distance in meters.
    Returns: (node_id, snapped_lon, snapped_lat, snap_distance_meters)
    """
    best_node = ""
    best_dist = float("inf")
    best_lon = 0.0
    best_lat = 0.0

    for n_id, n_lon, n_lat in nodes_data:
        dist = haversine_distance(lon, lat, n_lon, n_lat)
        if dist < best_dist:
            best_dist = dist
            best_node = n_id
            best_lon = n_lon
            best_lat = n_lat

    return best_node, best_lon, best_lat, round(best_dist, 2)


def calculate_screening_route(req: RouteScreeningRequest) -> RouteScreeningResponse:
    """
    Calculate shortest path route screening between start and destination coordinates.
    Snaps to nearest graph nodes, rejects points exceeding max_snap_distance_meters,
    filters out screening-positive road edges when requested, respects directed MultiDiGraph topology,
    and returns route geometry and diagnostic warnings.
    """
    disclaimer = (
        "Screening route only — road closures, structural bridge integrity, carrying capacity, "
        "and real-time accessibility are not validated. Not an official emergency evacuation route."
    )
    methodology = (
        "Dijkstra shortest-path routing on road network graph weighted by segment length in meters. "
        "Nearest node snapping computed via spherical Haversine distance. "
        "Road edges screened positive during sample raster intersection are excluded when avoid_screening_positive is enabled."
    )
    warnings: List[str] = []

    # 1. Load routing graph and spatial nodes
    G, nodes_data = load_routing_graph()

    # 2. Snap start and destination
    start_node, snap_s_lon, snap_s_lat, snap_s_dist = find_nearest_node(req.start_lon, req.start_lat, nodes_data)
    end_node, snap_e_lon, snap_e_lat, snap_e_dist = find_nearest_node(req.end_lon, req.end_lat, nodes_data)

    # Validate snap distance against max_snap_distance_meters
    max_snap = req.max_snap_distance_meters
    if snap_s_dist > max_snap:
        raise HTTPException(
            status_code=422,
            detail=f"Start point snap distance ({snap_s_dist:.1f} m) exceeds maximum allowable snap distance ({max_snap:.1f} m). Choose coordinates closer to the road network.",
        )
    if snap_e_dist > max_snap:
        raise HTTPException(
            status_code=422,
            detail=f"Destination point snap distance ({snap_e_dist:.1f} m) exceeds maximum allowable snap distance ({max_snap:.1f} m). Choose coordinates closer to the road network.",
        )

    if snap_s_dist > 2000.0:
        warnings.append(f"Start point was snapped {snap_s_dist:.1f} m to nearest road network node ({start_node}).")
    if snap_e_dist > 2000.0:
        warnings.append(f"Destination point was snapped {snap_e_dist:.1f} m to nearest road network node ({end_node}).")

    # 3. Query road exposure screening results using stable (u, v, key) matching
    h_src = req.hazard_source or "sample_hidkal"
    t_val = req.screening_threshold if req.screening_threshold is not None else (0.10 if h_src in ("anuga_hidkal_pilot", "anuga_hidkal_refined") else 0.0)
    exposure_roads = get_exposure_roads(hazard_source=h_src, threshold=t_val)
    exposed_edge_keys = set()
    for feat in exposure_roads.get("features", []):
        props = feat.get("properties") or {}
        if props.get("exposed") is True:
            u_str = str(props.get("u", ""))
            v_str = str(props.get("v", ""))
            k_val = props.get("key", 0)
            exposed_edge_keys.add((u_str, v_str, k_val))
            exposed_edge_keys.add((u_str, v_str, str(k_val)))

    excluded_edges_count = len(exposed_edge_keys) // 2

    # 4. Build filtered routing graph respecting directed MultiDiGraph topology
    is_directed = G.is_directed()
    G_routing = nx.MultiDiGraph() if is_directed else nx.MultiGraph()
    G_routing.add_nodes_from(G.nodes(data=True))

    for u, v, k, d in G.edges(keys=True, data=True):
        u_str, v_str = str(u), str(v)
        is_edge_exposed = (
            (u_str, v_str, k) in exposed_edge_keys
            or (u_str, v_str, str(k)) in exposed_edge_keys
        )
        if not is_directed:
            is_edge_exposed = is_edge_exposed or (
                (v_str, u_str, k) in exposed_edge_keys
                or (v_str, u_str, str(k)) in exposed_edge_keys
            )

        if req.avoid_screening_positive and is_edge_exposed:
            continue

        try:
            length = float(d.get("length", 1.0))
        except (ValueError, TypeError):
            length = 1.0

        edge_data = dict(d)
        edge_data["weight"] = length
        G_routing.add_edge(u, v, key=k, **edge_data)

    if start_node == end_node:
        warnings.append("Start and destination snapped to the exact same road node.")
        path_nodes = [start_node]
        total_length = 0.0
    else:
        try:
            path_nodes = nx.shortest_path(G_routing, source=start_node, target=end_node, weight="weight")
            total_length = float(nx.shortest_path_length(G_routing, source=start_node, target=end_node, weight="weight"))
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            run_id = "anuga_hidkal_refined_hypothetical_v1" if h_src == "anuga_hidkal_refined" else ("anuga_hidkal_pilot_hypothetical_v1" if h_src == "anuga_hidkal_pilot" else None)
            return RouteScreeningResponse(
                hazard_source=h_src,
                run_id=run_id,
                screening_threshold=t_val,
                route_found=False,
                geojson=None,
                total_distance_meters=None,
                total_distance_km=None,
                segment_count=0,
                start_coords=(req.start_lon, req.start_lat),
                end_coords=(req.end_lon, req.end_lat),
                snapped_start_coords=(snap_s_lon, snap_s_lat),
                snapped_end_coords=(snap_e_lon, snap_e_lat),
                start_snap_distance_meters=snap_s_dist,
                end_snap_distance_meters=snap_e_dist,
                excluded_edges_count=excluded_edges_count,
                avoid_screening_positive=req.avoid_screening_positive,
                disclaimer=disclaimer,
                methodology=methodology,
                warnings=["No viable connected route exists between the selected points under current avoidance constraints."] + warnings,
            )

    # 5. Extract accurate geometry from graph edges
    route_coords: List[Tuple[float, float]] = []
    for i in range(len(path_nodes) - 1):
        u = path_nodes[i]
        v = path_nodes[i + 1]
        edge_data_dict = G_routing.get_edge_data(u, v)
        if not edge_data_dict:
            continue

        best_k = min(edge_data_dict.keys(), key=lambda k: edge_data_dict[k].get("weight", float("inf")))
        best_edge = edge_data_dict[best_k]

        geom_wkt = best_edge.get("geometry")
        if geom_wkt:
            try:
                line_geom = wkt.loads(geom_wkt)
                coords = list(line_geom.coords)
            except Exception:
                coords = None
        else:
            coords = None

        if not coords:
            u_node = G.nodes[u]
            v_node = G.nodes[v]
            coords = [(float(u_node["x"]), float(u_node["y"])), (float(v_node["x"]), float(v_node["y"]))]
        else:
            u_node = G.nodes[u]
            u_x, u_y = float(u_node["x"]), float(u_node["y"])
            if len(coords) >= 2:
                first_pt = coords[0]
                last_pt = coords[-1]
                dist_first_sq = (first_pt[0] - u_x) ** 2 + (first_pt[1] - u_y) ** 2
                dist_last_sq = (last_pt[0] - u_x) ** 2 + (last_pt[1] - u_y) ** 2
                if dist_last_sq < dist_first_sq:
                    coords.reverse()

        for pt in coords:
            pt_tuple = (round(pt[0], 6), round(pt[1], 6))
            if not route_coords or route_coords[-1] != pt_tuple:
                route_coords.append(pt_tuple)

    if len(route_coords) < 2:
        route_coords = [(snap_s_lon, snap_s_lat), (snap_e_lon, snap_e_lat)]

    route_line = LineString(route_coords)
    total_km = round(total_length / 1000.0, 3)
    segment_count = max(1, len(path_nodes) - 1)

    geojson_feature = {
        "type": "Feature",
        "geometry": mapping(route_line),
        "properties": {
            "title": "Screening-Filtered Shortest Route",
            "hazard_source": h_src,
            "screening_threshold": t_val,
            "total_distance_meters": round(total_length, 2),
            "total_distance_km": total_km,
            "segment_count": segment_count,
            "avoid_screening_positive": req.avoid_screening_positive,
            "start_snap_distance_meters": snap_s_dist,
            "end_snap_distance_meters": snap_e_dist,
            "excluded_edges_count": excluded_edges_count,
            "disclaimer": disclaimer,
            "status": "not exposed at sample (edges screened positive excluded)",
        },
    }

    run_id = "anuga_hidkal_refined_hypothetical_v1" if h_src == "anuga_hidkal_refined" else ("anuga_hidkal_pilot_hypothetical_v1" if h_src == "anuga_hidkal_pilot" else None)
    return RouteScreeningResponse(
        hazard_source=h_src,
        run_id=run_id,
        screening_threshold=t_val,
        route_found=True,
        geojson=geojson_feature,
        total_distance_meters=round(total_length, 2),
        total_distance_km=total_km,
        segment_count=segment_count,
        start_coords=(req.start_lon, req.start_lat),
        end_coords=(req.end_lon, req.end_lat),
        snapped_start_coords=(snap_s_lon, snap_s_lat),
        snapped_end_coords=(snap_e_lon, snap_e_lat),
        start_snap_distance_meters=snap_s_dist,
        end_snap_distance_meters=snap_e_dist,
        excluded_edges_count=excluded_edges_count,
        avoid_screening_positive=req.avoid_screening_positive,
        disclaimer=disclaimer,
        methodology=methodology,
        warnings=warnings,
    )

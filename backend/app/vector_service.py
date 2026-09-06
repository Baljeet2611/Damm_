import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import numpy as np
import rasterio
import networkx as nx
from shapely import wkt
from shapely.geometry import shape, LineString, mapping
from fastapi import HTTPException

from app.schemas import (
    ExposureDatasetSummary,
    ExposureSummaryResponse,
)
from app.raster_service import get_project_root, resolve_dataset_file

DEFAULT_VECTOR_DATASETS: Dict[str, Dict[str, Any]] = {
    "assets": {
        "label": "Hidkal Infrastructure Assets",
        "relative_path": "data/raw/data_hidkal/hidkal_assets.geojson",
        "format": "geojson",
    },
    "roads": {
        "label": "Hidkal Road Network Graph",
        "relative_path": "data/raw/data_hidkal/hidkal_roads.graphml",
        "format": "graphml",
    },
}

_active_vector_datasets: Dict[str, Dict[str, Any]] = dict(DEFAULT_VECTOR_DATASETS)

# Caches
_assets_cache: Optional[Tuple[float, Dict[str, Any]]] = None
_roads_cache: Optional[Tuple[float, Dict[str, Any]]] = None
_exposure_assets_cache: Optional[Tuple[Tuple, Dict[str, Any]]] = None
_exposure_roads_cache: Optional[Tuple[Tuple, Dict[str, Any]]] = None
_exposure_summary_cache: Optional[Tuple[Tuple, ExposureSummaryResponse]] = None


def set_registered_vector_datasets(datasets: Dict[str, Dict[str, Any]]) -> None:
    """Override registered vector datasets (used in tests)."""
    global _active_vector_datasets
    _active_vector_datasets = dict(datasets)
    clear_vector_cache()


def reset_registered_vector_datasets() -> None:
    """Reset to default registered vector datasets."""
    global _active_vector_datasets
    _active_vector_datasets = dict(DEFAULT_VECTOR_DATASETS)
    clear_vector_cache()


def clear_vector_cache() -> None:
    """Clear in-memory vector and exposure caches."""
    global _assets_cache, _roads_cache, _exposure_assets_cache, _exposure_roads_cache, _exposure_summary_cache
    _assets_cache = None
    _roads_cache = None
    _exposure_assets_cache = None
    _exposure_roads_cache = None
    _exposure_summary_cache = None


def resolve_vector_file(dataset_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    """
    Resolve vector dataset strictly by whitelisted dataset_id.
    Prevents path traversal and arbitrary filesystem paths.
    """
    if dataset_id not in _active_vector_datasets:
        return None, None
    info = _active_vector_datasets[dataset_id]
    rel_path = info["relative_path"]
    resolved = (get_project_root() / rel_path).resolve()
    return info, resolved


def categorize_osm_asset(props: Dict[str, Any]) -> str:
    """
    Categorise OSM asset feature into one of 7 standardized categories:
    - healthcare
    - education
    - emergency
    - settlement
    - transport
    - building
    - other
    """
    amenity = props.get("amenity")
    building = props.get("building")
    place = props.get("place")
    highway = props.get("highway")
    railway = props.get("railway")
    healthcare = props.get("healthcare")
    emergency = props.get("emergency")
    bridge = props.get("bridge")
    public_transport = props.get("public_transport")

    if (
        healthcare
        or amenity in {"hospital", "clinic", "pharmacy", "doctors", "dentist", "health_post"}
        or building == "hospital"
    ):
        return "healthcare"

    if (
        amenity in {"school", "college", "university", "kindergarten"}
        or building in {"school", "college", "university", "kindergarten"}
    ):
        return "education"

    if (
        emergency
        or amenity in {"fire_station", "police", "ambulance_station", "emergency_phone_box"}
    ):
        return "emergency"

    if place is not None:
        return "settlement"

    if (
        highway is not None
        or railway is not None
        or bridge is not None
        or public_transport is not None
        or amenity in {"bus_station", "fuel", "parking", "ferry_terminal"}
    ):
        return "transport"

    if building is not None:
        return "building"

    return "other"


def normalize_road_highway(props: Dict[str, Any]) -> str:
    """Normalize road highway type into a clean category string."""
    hway = props.get("highway", "unclassified")
    if isinstance(hway, list):
        hway = hway[0] if hway else "unclassified"
    elif isinstance(hway, str):
        hway = hway.strip()
        if hway.startswith("[") and hway.endswith("]"):
            # Parse string representation of list, e.g. "['unclassified', 'tertiary']"
            cleaned = hway.strip("[]'\" ").split(",")[0].strip(" '\"")
            hway = cleaned if cleaned else "unclassified"

    known_highways = {"primary", "secondary", "tertiary", "residential", "unclassified", "trunk", "motorway", "track", "service", "footway", "path"}
    return hway if hway in known_highways else "other"


def load_raw_assets() -> Dict[str, Any]:
    """
    Load raw assets GeoJSON, attach 'category' property to each feature,
    and return GeoJSON FeatureCollection. Caches parsed result by mtime.
    """
    global _assets_cache
    info, file_path = resolve_vector_file("assets")
    if info is None or file_path is None or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Assets dataset is not available")

    mtime = file_path.stat().st_mtime
    if _assets_cache is not None and _assets_cache[0] == mtime:
        return _assets_cache[1]

    with open(file_path, "r", encoding="utf-8") as f:
        geojson_data = json.load(f)

    # Ensure FeatureCollection format and attach category
    features = []
    for feat in geojson_data.get("features", []):
        props = dict(feat.get("properties") or {})
        props["category"] = categorize_osm_asset(props)
        features.append({
            "type": "Feature",
            "id": feat.get("id"),
            "geometry": feat.get("geometry"),
            "properties": props,
        })

    result = {
        "type": "FeatureCollection",
        "features": features,
    }
    _assets_cache = (mtime, result)
    return result


def load_raw_roads() -> Dict[str, Any]:
    """
    Load GraphML road network, convert edges to GeoJSON LineStrings
    using stored geometry when available, otherwise source/target node coordinates.
    Caches parsed result by mtime.
    """
    global _roads_cache
    info, file_path = resolve_vector_file("roads")
    if info is None or file_path is None or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Roads dataset is not available")

    mtime = file_path.stat().st_mtime
    if _roads_cache is not None and _roads_cache[0] == mtime:
        return _roads_cache[1]

    G = nx.read_graphml(str(file_path))
    features = []

    for u, v, k, d in G.edges(keys=True, data=True):
        # Determine geometry
        if "geometry" in d and d["geometry"]:
            geom = wkt.loads(d["geometry"])
        else:
            u_node = G.nodes[u]
            v_node = G.nodes[v]
            u_x, u_y = float(u_node["x"]), float(u_node["y"])
            v_x, v_y = float(v_node["x"]), float(v_node["y"])
            geom = LineString([(u_x, u_y), (v_x, v_y)])

        props = {k_attr: v_attr for k_attr, v_attr in d.items() if k_attr != "geometry"}
        props["u"] = str(u)
        props["v"] = str(v)
        props["key"] = k
        props["category"] = normalize_road_highway(props)

        features.append({
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": props,
        })

    result = {
        "type": "FeatureCollection",
        "features": features,
    }
    _roads_cache = (mtime, result)
    return result


from pyproj import Transformer
from app.anuga_service import resolve_anuga_layer_file

# Transformer from EPSG:4326 to EPSG:32643 for ANUGA pilot
_wgs84_to_utm43n = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)


class RasterSampler:
    """Helper to sample depth, velocity, and arrival rasters efficiently in memory."""
    def __init__(self, hazard_source: str = "sample_hidkal", threshold: float = 0.0):
        self.hazard_source = hazard_source or "sample_hidkal"
        self.threshold = threshold if threshold is not None else (0.10 if self.hazard_source in ("anuga_hidkal_pilot", "anuga_hidkal_refined") else 0.0)
        self.depth_arr = None
        self.velocity_arr = None
        self.arrival_arr = None
        self.inv_transform = None
        self.bounds = None
        self.nodata = None
        self.available = False
        self.is_projected = False
        self.mtimes = []

        self._load_rasters()

    def _load_rasters(self):
        if self.hazard_source in ("anuga_hidkal_pilot", "anuga_hidkal_refined"):
            self.is_projected = True
            try:
                _, depth_path = resolve_anuga_layer_file("depth", hazard_source=self.hazard_source)
                _, velocity_path = resolve_anuga_layer_file("velocity", hazard_source=self.hazard_source)
                _, arrival_path = resolve_anuga_layer_file("arrival", hazard_source=self.hazard_source)
            except Exception:
                depth_path, velocity_path, arrival_path = None, None, None

            if depth_path and depth_path.is_file():
                self.mtimes.append(depth_path.stat().st_mtime)
                with rasterio.open(depth_path) as ds:
                    self.depth_arr = ds.read(1)
                    self.inv_transform = ~ds.transform
                    self.bounds = ds.bounds
                    self.nodata = ds.nodata
                    self.height, self.width = self.depth_arr.shape
                self.available = True
            else:
                self.mtimes.append(0.0)

            if velocity_path and velocity_path.is_file():
                self.mtimes.append(velocity_path.stat().st_mtime)
                with rasterio.open(velocity_path) as ds:
                    self.velocity_arr = ds.read(1)
            else:
                self.mtimes.append(0.0)

            if arrival_path and arrival_path.is_file():
                self.mtimes.append(arrival_path.stat().st_mtime)
                with rasterio.open(arrival_path) as ds:
                    self.arrival_arr = ds.read(1)
            else:
                self.mtimes.append(0.0)
        else:
            self.is_projected = False
            _, depth_path = resolve_dataset_file("depth")
            _, velocity_path = resolve_dataset_file("velocity")
            _, arrival_path = resolve_dataset_file("arrival")

            if depth_path and depth_path.is_file():
                self.mtimes.append(depth_path.stat().st_mtime)
                with rasterio.open(depth_path) as ds:
                    self.depth_arr = ds.read(1)
                    self.inv_transform = ~ds.transform
                    self.bounds = ds.bounds
                    self.nodata = ds.nodata
                    self.height, self.width = self.depth_arr.shape
                self.available = True
            else:
                self.mtimes.append(0.0)

            if velocity_path and velocity_path.is_file():
                self.mtimes.append(velocity_path.stat().st_mtime)
                with rasterio.open(velocity_path) as ds:
                    self.velocity_arr = ds.read(1)
            else:
                self.mtimes.append(0.0)

            if arrival_path and arrival_path.is_file():
                self.mtimes.append(arrival_path.stat().st_mtime)
                with rasterio.open(arrival_path) as ds:
                    self.arrival_arr = ds.read(1)
            else:
                self.mtimes.append(0.0)

    def sample_coordinate(self, lon: float, lat: float) -> Tuple[bool, bool, Optional[float], Optional[float], Optional[float], bool]:
        """
        Sample depth, velocity, and arrival at (lon, lat).
        Returns: (assessed, exposed, depth_value, velocity_value, arrival_value, is_initially_wet)
        """
        if not self.available or self.bounds is None or self.inv_transform is None:
            return False, False, None, None, None, False

        # Transform coordinates if raster is in projected CRS (EPSG:32643)
        if self.is_projected:
            x_samp, y_samp = _wgs84_to_utm43n.transform(lon, lat)
        else:
            x_samp, y_samp = lon, lat

        if not (self.bounds.left <= x_samp <= self.bounds.right and self.bounds.bottom <= y_samp <= self.bounds.top):
            return False, False, None, None, None, False

        col, row = [int(v) for v in self.inv_transform @ (x_samp, y_samp)]
        # Clamp boundary edges
        if col >= self.width:
            col = self.width - 1
        if row >= self.height:
            row = self.height - 1

        if 0 <= row < self.height and 0 <= col < self.width:
            d = float(self.depth_arr[row, col]) if self.depth_arr is not None else None
            v = float(self.velocity_arr[row, col]) if self.velocity_arr is not None else None
            a = float(self.arrival_arr[row, col]) if self.arrival_arr is not None else None

            # Process depth
            d_val = None
            if d is not None and not np.isnan(d) and not (self.nodata is not None and np.isclose(d, self.nodata)):
                d_val = round(d, 4)

            # Process velocity
            v_val = None
            if v is not None and not np.isnan(v) and not (self.nodata is not None and np.isclose(v, self.nodata)):
                if v >= 0.0:
                    v_val = round(v, 4)

            # Process arrival: filter +9999, -9999, nan
            a_val = None
            is_initially_wet = False
            if a is not None and not np.isnan(a):
                if np.isclose(a, 0.0) and self.hazard_source in ("anuga_hidkal_pilot", "anuga_hidkal_refined"):
                    is_initially_wet = True
                    a_val = 0.0
                elif not (np.isclose(a, 9999.0) or np.isclose(a, -9999.0) or a >= 9000.0 or a <= 0.0):
                    a_val = round(a, 4)

            assessed = d_val is not None
            # Exposed check against screening threshold
            exposed = bool(assessed and d_val is not None and d_val > self.threshold)
            return assessed, exposed, d_val, v_val, a_val, is_initially_wet

        return False, False, None, None, None, False


def sample_geometry_exposure(geom_shape, sampler: RasterSampler) -> Tuple[bool, bool, Optional[float], Optional[float], Optional[float], bool, str]:
    """
    Perform geometric screening for a geometry:
    - Point: direct coordinate sampling ('point_direct')
    - Polygon/MultiPolygon: representative point ('polygon_representative_point')
    - LineString/MultiLineString: line midpoint ('line_midpoint')
    - Other: centroid ('geometry_centroid')
    """
    if geom_shape.is_empty:
        return False, False, None, None, None, False, "empty_geometry"

    g_type = geom_shape.geom_type
    if g_type == "Point":
        pt = geom_shape
        method = "point_direct"
    elif g_type in ("Polygon", "MultiPolygon"):
        pt = geom_shape.representative_point()
        method = "polygon_representative_point"
    elif g_type in ("LineString", "MultiLineString"):
        pt = geom_shape.interpolate(0.5, normalized=True)
        method = "line_midpoint"
    else:
        pt = geom_shape.centroid
        method = "geometry_centroid"

    assessed, exposed, d_val, v_val, a_val, is_init_wet = sampler.sample_coordinate(pt.x, pt.y)
    return assessed, exposed, d_val, v_val, a_val, is_init_wet, method


def get_exposure_assets(hazard_source: str = "sample_hidkal", threshold: float = 0.0) -> Dict[str, Any]:
    """
    Calculate and return assets GeoJSON with exposure screening attributes.
    Supports hazard_source ('sample_hidkal', 'anuga_hidkal_pilot', or 'anuga_hidkal_refined') and configurable threshold.
    """
    global _exposure_assets_cache
    h_src = hazard_source or "sample_hidkal"
    t_val = float(threshold) if threshold is not None else (0.10 if h_src in ("anuga_hidkal_pilot", "anuga_hidkal_refined") else 0.0)

    raw_assets = load_raw_assets()
    _, assets_path = resolve_vector_file("assets")
    assets_mtime = assets_path.stat().st_mtime if assets_path else 0.0

    sampler = RasterSampler(hazard_source=h_src, threshold=t_val)
    cache_key = (h_src, t_val, assets_mtime, *sampler.mtimes)

    if _exposure_assets_cache is not None and _exposure_assets_cache[0] == cache_key:
        return _exposure_assets_cache[1]

    if h_src == "anuga_hidkal_refined":
        disclaimer_text = "Hypothetical refined ANUGA pilot screening — not a forecast or validated Hidkal prediction. Assumed vertical units from source interpretation."
    elif h_src == "anuga_hidkal_pilot":
        disclaimer_text = "Hypothetical ANUGA pilot screening — not a forecast or validated Hidkal prediction. Assumed vertical units from source interpretation."
    else:
        disclaimer_text = "preliminary exposure screening based on unverified sample rasters"

    features = []
    for feat in raw_assets["features"]:
        geom_json = feat.get("geometry")
        props = dict(feat.get("properties") or {})
        category = props.get("category") or categorize_osm_asset(props)
        props["category"] = category

        if geom_json:
            geom_obj = shape(geom_json)
            assessed, exposed, d_val, v_val, a_val, is_init_wet, method = sample_geometry_exposure(geom_obj, sampler)
        else:
            assessed, exposed, d_val, v_val, a_val, is_init_wet, method = False, False, None, None, None, False, "no_geometry"

        props["hazard_source"] = h_src
        props["screening_threshold"] = t_val
        props["assessed"] = assessed
        props["exposed"] = exposed
        props["depth_value"] = d_val
        props["velocity_value"] = v_val
        props["arrival_value"] = a_val
        props["is_initially_wet"] = is_init_wet
        props["sampling_method"] = method
        props["preliminary_screening_note"] = disclaimer_text

        features.append({
            "type": "Feature",
            "id": feat.get("id"),
            "geometry": geom_json,
            "properties": props,
        })

    result = {
        "type": "FeatureCollection",
        "features": features,
    }
    _exposure_assets_cache = (cache_key, result)
    return result


def get_exposure_roads(hazard_source: str = "sample_hidkal", threshold: float = 0.0) -> Dict[str, Any]:
    """
    Calculate and return roads GeoJSON with exposure screening attributes.
    Supports hazard_source ('sample_hidkal', 'anuga_hidkal_pilot', or 'anuga_hidkal_refined') and configurable threshold.
    """
    global _exposure_roads_cache
    h_src = hazard_source or "sample_hidkal"
    t_val = float(threshold) if threshold is not None else (0.10 if h_src in ("anuga_hidkal_pilot", "anuga_hidkal_refined") else 0.0)

    raw_roads = load_raw_roads()
    _, roads_path = resolve_vector_file("roads")
    roads_mtime = roads_path.stat().st_mtime if roads_path else 0.0

    sampler = RasterSampler(hazard_source=h_src, threshold=t_val)
    cache_key = (h_src, t_val, roads_mtime, *sampler.mtimes)

    if _exposure_roads_cache is not None and _exposure_roads_cache[0] == cache_key:
        return _exposure_roads_cache[1]

    if h_src == "anuga_hidkal_refined":
        disclaimer_text = "Hypothetical refined ANUGA pilot screening — not a forecast or validated Hidkal prediction. Assumed vertical units from source interpretation."
    elif h_src == "anuga_hidkal_pilot":
        disclaimer_text = "Hypothetical ANUGA pilot screening — not a forecast or validated Hidkal prediction. Assumed vertical units from source interpretation."
    else:
        disclaimer_text = "preliminary exposure screening based on unverified sample rasters"

    features = []
    for feat in raw_roads["features"]:
        geom_json = feat.get("geometry")
        props = dict(feat.get("properties") or {})
        category = props.get("category") or normalize_road_highway(props)
        props["category"] = category

        if geom_json:
            geom_obj = shape(geom_json)
            assessed, exposed, d_val, v_val, a_val, is_init_wet, method = sample_geometry_exposure(geom_obj, sampler)
        else:
            assessed, exposed, d_val, v_val, a_val, is_init_wet, method = False, False, None, None, None, False, "no_geometry"

        props["hazard_source"] = h_src
        props["screening_threshold"] = t_val
        props["assessed"] = assessed
        props["exposed"] = exposed
        props["depth_value"] = d_val
        props["velocity_value"] = v_val
        props["arrival_value"] = a_val
        props["is_initially_wet"] = is_init_wet
        props["sampling_method"] = method
        props["preliminary_screening_note"] = disclaimer_text

        features.append({
            "type": "Feature",
            "geometry": geom_json,
            "properties": props,
        })

    result = {
        "type": "FeatureCollection",
        "features": features,
    }
    _exposure_roads_cache = (cache_key, result)
    return result


def get_exposure_summary(hazard_source: str = "sample_hidkal", threshold: float = 0.0) -> ExposureSummaryResponse:
    """
    Compute full exposure summary metrics (total, assessed, exposed, not-exposed, not-assessed)
    plus categorical breakdowns for both assets and road network.
    """
    global _exposure_summary_cache
    h_src = hazard_source or "sample_hidkal"
    t_val = float(threshold) if threshold is not None else (0.10 if h_src in ("anuga_hidkal_pilot", "anuga_hidkal_refined") else 0.0)

    # Get processed assets and roads
    assets_fc = get_exposure_assets(hazard_source=h_src, threshold=t_val)
    roads_fc = get_exposure_roads(hazard_source=h_src, threshold=t_val)

    _, assets_path = resolve_vector_file("assets")
    _, roads_path = resolve_vector_file("roads")
    a_mtime = assets_path.stat().st_mtime if assets_path else 0.0
    r_mtime = roads_path.stat().st_mtime if roads_path else 0.0

    sampler = RasterSampler(hazard_source=h_src, threshold=t_val)
    cache_key = (h_src, t_val, a_mtime, r_mtime, *sampler.mtimes)

    if _exposure_summary_cache is not None and _exposure_summary_cache[0] == cache_key:
        return _exposure_summary_cache[1]

    # Aggregate Assets
    asset_total = len(assets_fc["features"])
    asset_assessed = 0
    asset_exposed = 0
    asset_not_exposed = 0
    asset_not_assessed = 0
    asset_init_wet = 0
    asset_by_cat: Dict[str, Any] = {}

    for feat in assets_fc["features"]:
        props = feat.get("properties") or {}
        cat = props.get("category", "other")
        if cat not in asset_by_cat:
            asset_by_cat[cat] = {"total": 0, "assessed": 0, "exposed": 0, "not_exposed": 0, "not_assessed": 0}

        asset_by_cat[cat]["total"] += 1
        assessed = props.get("assessed", False)
        exposed = props.get("exposed", False)
        init_wet = props.get("is_initially_wet", False)

        if assessed:
            asset_assessed += 1
            asset_by_cat[cat]["assessed"] += 1
            if exposed:
                asset_exposed += 1
                asset_by_cat[cat]["exposed"] += 1
                if init_wet:
                    asset_init_wet += 1
            else:
                asset_not_exposed += 1
                asset_by_cat[cat]["not_exposed"] += 1
        else:
            asset_not_assessed += 1
            asset_by_cat[cat]["not_assessed"] += 1

    # Aggregate Roads
    road_total = len(roads_fc["features"])
    road_assessed = 0
    road_exposed = 0
    road_not_exposed = 0
    road_not_assessed = 0
    road_init_wet = 0
    road_by_cat: Dict[str, Any] = {}

    for feat in roads_fc["features"]:
        props = feat.get("properties") or {}
        cat = props.get("category", "unclassified")
        if cat not in road_by_cat:
            road_by_cat[cat] = {"total": 0, "assessed": 0, "exposed": 0, "not_exposed": 0, "not_assessed": 0}

        road_by_cat[cat]["total"] += 1
        assessed = props.get("assessed", False)
        exposed = props.get("exposed", False)
        init_wet = props.get("is_initially_wet", False)

        if assessed:
            road_assessed += 1
            road_by_cat[cat]["assessed"] += 1
            if exposed:
                road_exposed += 1
                road_by_cat[cat]["exposed"] += 1
                if init_wet:
                    road_init_wet += 1
            else:
                road_not_exposed += 1
                road_by_cat[cat]["not_exposed"] += 1
        else:
            road_not_assessed += 1
            road_by_cat[cat]["not_assessed"] += 1

    assets_summary = ExposureDatasetSummary(
        total=asset_total,
        assessed=asset_assessed,
        exposed=asset_exposed,
        not_exposed=asset_not_exposed,
        not_assessed=asset_not_assessed,
        by_category=asset_by_cat,
    )

    roads_summary = ExposureDatasetSummary(
        total=road_total,
        assessed=road_assessed,
        exposed=road_exposed,
        not_exposed=road_not_exposed,
        not_assessed=road_not_assessed,
        by_category=road_by_cat,
    )

    is_anuga = h_src in ("anuga_hidkal_pilot", "anuga_hidkal_refined")
    if h_src == "anuga_hidkal_refined":
        disclaimer = "Hypothetical refined ANUGA pilot screening — not a forecast or validated Hidkal prediction. Assumed vertical units from source interpretation."
        unit_status = "assumed metres based on source interpretation"
        run_id = "anuga_hidkal_refined_hypothetical_v1"
    elif h_src == "anuga_hidkal_pilot":
        disclaimer = "Hypothetical ANUGA pilot screening — not a forecast or validated Hidkal prediction. Assumed vertical units from source interpretation."
        unit_status = "assumed metres based on source interpretation"
        run_id = "anuga_hidkal_pilot_hypothetical_v1"
    else:
        disclaimer = "preliminary exposure screening based on unverified sample rasters. Not a validated hydrodynamic risk assessment or damage analysis."
        unit_status = "unverified"
        run_id = None

    response = ExposureSummaryResponse(
        hazard_source=h_src,
        run_id=run_id,
        screening_threshold=t_val,
        unit_status=unit_status,
        disclaimer=disclaimer,
        methodology_note="Point sampling for points; representative-point/midpoint geometric screening for polygons and lines.",
        assets=assets_summary,
        roads=roads_summary,
        initially_wet_reservoir_assets=asset_init_wet if is_anuga else None,
        initially_wet_reservoir_roads=road_init_wet if is_anuga else None,
        newly_inundated_assets=(asset_exposed - asset_init_wet) if is_anuga else None,
        newly_inundated_roads=(road_exposed - road_init_wet) if is_anuga else None,
    )

    _exposure_summary_cache = (cache_key, response)
    return response

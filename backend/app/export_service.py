import io
import json
import zipfile
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import xml.sax.saxutils as saxutils
import geopandas as gpd
from shapely.geometry import shape, Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon
from fastapi import HTTPException
from fastapi.responses import Response

from app.schemas import RouteScreeningRequest
from app.vector_service import get_exposure_assets, get_exposure_roads
from app.route_service import calculate_screening_route

GET_WHITELISTED_LAYERS = {"assets", "roads"}
ALL_WHITELISTED_LAYERS = {"assets", "roads", "route"}
SUPPORTED_FORMATS = {"geojson", "kml", "shp"}
SUPPORTED_FILTERS = {"all", "screening_positive", "not_exposed", "not_assessed"}


def filter_geojson_features(
    feature_collection: Dict[str, Any], exposure_filter: str
) -> Dict[str, Any]:
    """Filter GeoJSON features by exposure classification."""
    features = feature_collection.get("features", [])
    if exposure_filter == "all" or not exposure_filter:
        return {"type": "FeatureCollection", "features": list(features)}

    filtered = []
    for feat in features:
        props = feat.get("properties") or {}
        assessed = props.get("assessed", False)
        exposed = props.get("exposed", False)

        if exposure_filter == "screening_positive" and exposed is True:
            filtered.append(feat)
        elif exposure_filter == "not_exposed" and assessed is True and exposed is False:
            filtered.append(feat)
        elif exposure_filter == "not_assessed" and assessed is False:
            filtered.append(feat)

    return {"type": "FeatureCollection", "features": filtered}


def get_layer_feature_collection(
    layer: str,
    exposure_filter: str = "all",
    route_request: Optional[RouteScreeningRequest] = None,
    hazard_source: str = "sample_hidkal",
    threshold: float = 0.0,
) -> Dict[str, Any]:
    """
    Retrieve and filter GeoJSON FeatureCollection for the requested layer.
    For route export, recomputes route from a validated RouteScreeningRequest.
    """
    if layer not in ALL_WHITELISTED_LAYERS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid layer '{layer}'. Whitelisted layers are: {', '.join(sorted(ALL_WHITELISTED_LAYERS))}",
        )

    if exposure_filter not in SUPPORTED_FILTERS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid exposure_filter '{exposure_filter}'. Supported filters are: {', '.join(sorted(SUPPORTED_FILTERS))}",
        )

    h_src = hazard_source or "sample_hidkal"
    t_val = float(threshold) if threshold is not None else (0.10 if h_src in ("anuga_hidkal_pilot", "anuga_hidkal_refined") else 0.0)

    if layer == "assets":
        raw = get_exposure_assets(hazard_source=h_src, threshold=t_val)
        return filter_geojson_features(raw, exposure_filter)
    elif layer == "roads":
        raw = get_exposure_roads(hazard_source=h_src, threshold=t_val)
        return filter_geojson_features(raw, exposure_filter)
    elif layer == "route":
        if not route_request:
            raise HTTPException(
                status_code=422,
                detail="A valid RouteScreeningRequest must be provided to recompute and export the route layer.",
            )
        route_response = calculate_screening_route(route_request)
        if not route_response.route_found or not route_response.geojson:
            raise HTTPException(
                status_code=422,
                detail="No valid route could be found with the provided screening parameters to export.",
            )
        return {"type": "FeatureCollection", "features": [route_response.geojson]}

    raise HTTPException(status_code=400, detail="Unknown layer request")


def export_to_geojson_response(
    geojson_data: Dict[str, Any], layer: str, exposure_filter: str
) -> Response:
    """Generate GeoJSON file response with proper headers."""
    content = json.dumps(geojson_data, indent=2)
    filename = f"dam_break_{layer}_{exposure_filter}.geojson"
    return Response(
        content=content,
        media_type="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def coords_to_kml_string(geom_type: str, coordinates: Any) -> str:
    """Format GeoJSON coordinates into KML coordinate tags."""
    if geom_type == "Point":
        lon, lat = coordinates[:2]
        return f"<Point><coordinates>{lon},{lat},0</coordinates></Point>"
    elif geom_type == "LineString":
        coords_str = " ".join(f"{c[0]},{c[1]},0" for c in coordinates)
        return f"<LineString><tessellate>1</tessellate><coordinates>{coords_str}</coordinates></LineString>"
    elif geom_type == "Polygon":
        outer_ring = coordinates[0]
        coords_str = " ".join(f"{c[0]},{c[1]},0" for c in outer_ring)
        return (
            f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords_str}</coordinates></LinearRing></outerBoundaryIs></Polygon>"
        )
    elif geom_type == "MultiLineString":
        multigeoms = []
        for line in coordinates:
            coords_str = " ".join(f"{c[0]},{c[1]},0" for c in line)
            multigeoms.append(
                f"<LineString><tessellate>1</tessellate><coordinates>{coords_str}</coordinates></LineString>"
            )
        return f"<MultiGeometry>{''.join(multigeoms)}</MultiGeometry>"
    elif geom_type == "MultiPolygon":
        multigeoms = []
        for poly in coordinates:
            outer_ring = poly[0]
            coords_str = " ".join(f"{c[0]},{c[1]},0" for c in outer_ring)
            multigeoms.append(
                f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords_str}</coordinates></LinearRing></outerBoundaryIs></Polygon>"
            )
        return f"<MultiGeometry>{''.join(multigeoms)}</MultiGeometry>"
    return ""


def export_to_kml_response(
    geojson_data: Dict[str, Any], layer: str, exposure_filter: str
) -> Response:
    """Generate Google Earth KML file response with safe XML escaping."""
    layer_title = saxutils.escape(f"Dam Break - {layer.title()} ({exposure_filter})")
    disclaimer = saxutils.escape(
        "Illustrative screening data based on unverified sample rasters. Not validated risk or evacuation advice."
    )

    placemarks: List[str] = []
    for idx, feat in enumerate(geojson_data.get("features", [])):
        geom = feat.get("geometry")
        if not geom:
            continue

        props = feat.get("properties") or {}
        name = saxutils.escape(str(props.get("title") or props.get("name") or props.get("category") or f"Feature_{idx + 1}"))
        category = saxutils.escape(str(props.get("category", "unclassified")))
        exposed = (
            "Screening-Positive (depth > 0 at sample)"
            if props.get("exposed") is True
            else "Not Exposed at Sample"
            if props.get("assessed") is True
            else "Not Assessed"
        )

        extended_data_items = []
        for k, v in props.items():
            if v is not None and not isinstance(v, (dict, list)):
                k_esc = saxutils.escape(str(k))
                v_esc = saxutils.escape(str(v))
                extended_data_items.append(f'<Data name="{k_esc}"><value>{v_esc}</value></Data>')

        kml_geom = coords_to_kml_string(geom.get("type", ""), geom.get("coordinates", []))
        if not kml_geom:
            continue

        placemark = f"""    <Placemark>
      <name>{name}</name>
      <description>Category: {category} | Status: {exposed}</description>
      <ExtendedData>
        {''.join(extended_data_items)}
      </ExtendedData>
      {kml_geom}
    </Placemark>"""
        placemarks.append(placemark)

    kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{layer_title}</name>
    <description>{disclaimer}</description>
{chr(10).join(placemarks)}
  </Document>
</kml>"""

    filename = f"dam_break_{layer}_{exposure_filter}.kml"
    return Response(
        content=kml_content,
        media_type="application/vnd.google-earth.kml+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def sanitize_gdf_for_shapefile(gdf: gpd.GeoDataFrame) -> Tuple[gpd.GeoDataFrame, Dict[str, str]]:
    """
    Sanitize GeoDataFrame column names and data types for ESRI Shapefile export:
    - Truncate column names deterministically to <= 10 alphanumeric characters.
    - Convert complex nested types (dict, list, tuple, set) safely to JSON strings.
    - Truncate string values exceeding 254 chars to satisfy DBF constraints.
    - Returns sanitized GeoDataFrame and column name mapping dict (orig -> short).
    """
    clean_gdf = gdf.copy()
    col_map: Dict[str, str] = {}
    used_names: set = set()

    for col in clean_gdf.columns:
        if col == "geometry":
            continue

        # Deterministic 10-character name
        base_short = "".join(c for c in str(col).lower() if c.isalnum() or c == "_")[:10]
        if not base_short:
            base_short = "field"

        short_name = base_short
        counter = 1
        while short_name in used_names:
            suffix = f"_{counter}"
            short_name = f"{base_short[:10 - len(suffix)]}{suffix}"
            counter += 1

        used_names.add(short_name)
        col_map[col] = short_name

        def sanitize_val(v: Any) -> Any:
            if v is None:
                return None
            if isinstance(v, (dict, list, tuple, set)):
                val_str = json.dumps(v, ensure_ascii=False)
                return val_str[:254]
            if isinstance(v, bool):
                return int(v)
            if isinstance(v, str) and len(v) > 254:
                return v[:254]
            return v

        clean_gdf[col] = clean_gdf[col].apply(sanitize_val)

    return clean_gdf.rename(columns=col_map), col_map


def export_to_shapefile_zip_response(
    geojson_data: Dict[str, Any], layer: str, exposure_filter: str
) -> Response:
    """
    Generate ESRI Shapefile Zipped archive in-memory:
    - Splits mixed geometries into separate shapefiles (_points.shp, _lines.shp, _polygons.shp).
    - Writes full shapefile component sets (.shp, .shx, .dbf, .prj, .cpg).
    - Includes detailed README_METADATA.txt with attribute field mapping and scientific disclaimer.
    - Entire ZIP is built in-memory before temporary directory cleanup to avoid premature file deletion.
    """
    features = geojson_data.get("features", [])
    if not features:
        # Dummy placeholder point if dataset empty
        features = [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [74.7, 16.2]},
            "properties": {"status": "no features matching filter"}
        }]

    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        gdf, col_map = sanitize_gdf_for_shapefile(gdf)

        # Categorize by geometry types
        geom_subsets = {
            "points": gdf[gdf.geometry.type.isin(["Point", "MultiPoint"])],
            "lines": gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])],
            "polygons": gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])],
        }

        non_empty_subsets = {k: v for k, v in geom_subsets.items() if not v.empty}
        if not non_empty_subsets:
            non_empty_subsets = {"all": gdf}

        is_homogeneous = len(non_empty_subsets) == 1 and "all" not in non_empty_subsets

        for sub_name, sub_gdf in non_empty_subsets.items():
            base_name = f"{layer}" if is_homogeneous else f"{layer}_{sub_name}"
            shp_path = temp_dir / f"{base_name}.shp"
            sub_gdf.to_file(shp_path, driver="ESRI Shapefile", encoding="utf-8")

        # Write README_METADATA.txt
        meta_path = temp_dir / "README_METADATA.txt"
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(
                f"Dam Break Decision Support System - Geospatial Export\n"
                f"=======================================================\n"
                f"Layer: {layer}\n"
                f"Exposure Filter: {exposure_filter}\n"
                f"Coordinate Reference System: EPSG:4326 (WGS84 Longitude/Latitude)\n"
                f"Total Feature Count: {len(geojson_data.get('features', []))}\n\n"
                f"GEOMETRY PARTITIONS:\n"
            )
            for sub_name, sub_gdf in non_empty_subsets.items():
                f.write(f"- {sub_name}: {len(sub_gdf)} features\n")

            f.write(f"\nATTRIBUTE FIELD MAPPINGS (Original -> Shapefile 10-char):\n")
            for orig_name, short_name in sorted(col_map.items()):
                f.write(f"- {orig_name:<30} -> {short_name}\n")

            f.write(
                f"\nDISCLAIMER:\n"
                f"This geospatial dataset represents preliminary illustrative screening results\n"
                f"derived from sample raster outputs of unverified provenance.\n"
                f"Features classified as 'not exposed at sample' reflect zero depth at sample locations\n"
                f"under unverified test rasters. It must not be used as a validated hydrodynamic simulation,\n"
                f"official risk prediction, or emergency evacuation instruction.\n"
            )

        # Build in-memory ZIP archive
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in temp_dir.iterdir():
                if file_path.is_file():
                    zf.write(file_path, arcname=file_path.name)

        zip_bytes = zip_buffer.getvalue()

    filename = f"dam_break_{layer}_{exposure_filter}_shp.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def handle_export(
    layer: str,
    format_type: str = "geojson",
    exposure_filter: str = "all",
    route_request: Optional[RouteScreeningRequest] = None,
    hazard_source: str = "sample_hidkal",
    threshold: float = 0.0,
) -> Response:
    """Main export handler dispatching to GeoJSON, KML, or Shapefile (ZIP) generator."""
    fmt = format_type.lower().strip()
    if fmt not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid format '{format_type}'. Supported formats are: {', '.join(sorted(SUPPORTED_FORMATS))}",
        )

    geojson_data = get_layer_feature_collection(
        layer=layer,
        exposure_filter=exposure_filter,
        route_request=route_request,
        hazard_source=hazard_source,
        threshold=threshold,
    )

    if fmt == "geojson":
        return export_to_geojson_response(geojson_data, layer, exposure_filter)
    elif fmt == "kml":
        return export_to_kml_response(geojson_data, layer, exposure_filter)
    elif fmt == "shp":
        return export_to_shapefile_zip_response(geojson_data, layer, exposure_filter)

    raise HTTPException(status_code=400, detail="Unsupported export combination")


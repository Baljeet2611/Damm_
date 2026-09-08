"""
Dam Project Onboarding & Dataset Validation Service (SIH PS 26161).

Validates user-submitted custom dam and river datasets without running simulation:
1. Validates single-band numeric DEM GeoTIFF, CRS, bounds, resolution, and valid min/max block-wise.
2. Validates dam axis (LineString/MultiLineString only) and reservoir boundary (Polygon/MultiPolygon only) GeoJSON.
3. Reprojects RFC 7946 (EPSG:4326) geometries into DEM CRS and calculates breach-to-axis distance in true metric metres.
4. Distinguishes fully_within_dem_bounds from intersects_dem_bounds.
5. Enforces resource limits (max bytes, max pixels, max features) with HTTP 413.
6. Clearly separates raster-derived metadata (with unknown vertical datum/units) from user-provided metadata.
7. Distinguishes computational readiness from scientific verification.
8. Provides atomic project registration, metadata inspection, point probing, and tile rendering.
"""

import io
import os
import json
import uuid
import shutil
import hashlib
import tempfile
import zipfile
import re
import time
import subprocess
import threading
from scipy.io import netcdf_file
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set

import numpy as np
import rasterio
from rasterio.windows import Window
from PIL import Image
from rio_tiler.io import Reader
from shapely.geometry import shape, Point, box, LineString, MultiLineString, Polygon, MultiPolygon
from shapely.ops import transform as shapely_transform
from pyproj import CRS, Transformer
from fastapi import HTTPException

from app.schemas import (
    RasterBounds,
    RasterResolution,
    RasterMetadataResponse,
    RasterPointValueResponse,
    RasterDerivedMetadata,
    UserProvidedMetadata,
    GeometryValidationMetadata,
    NormalizedProjectMetadata,
    DamProjectValidationResponse,
    DamProjectSummary,
    DamProjectDetailResponse,
    DamProjectAnugaPreflightResponse,
    DamProjectAnugaPackageResponse,
    DamProjectAnugaCapabilitiesResponse,
    DamProjectAnugaRunRequest,
    DamProjectAnugaRunResponse,
)
from app.raster_service import EMPTY_TILE_PNG, apply_colormap_and_transparency
from app.scenario_storage import get_runtime_dir, compute_file_sha256

# Configurable resource limits
MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024       # 50 MB per file
MAX_RASTER_PIXELS = 100_000_000                # 100 Million pixels
MAX_GEOJSON_FEATURES = 5_000                   # 5,000 features

# Allowed file extensions
ALLOWED_DEM_EXTENSIONS = {".tif", ".tiff"}
ALLOWED_GEOJSON_EXTENSIONS = {".geojson", ".json"}


def get_dam_projects_dir() -> Path:
    """Get persistent storage directory for registered dam projects."""
    p = get_runtime_dir() / "dam_projects"
    p.mkdir(parents=True, exist_ok=True)
    return p


def validate_project_uuid(project_id: str) -> str:
    """Validate that the provided project_id is a valid UUID v4; prevents path traversal."""
    try:
        parsed = uuid.UUID(str(project_id).strip(), version=4)
        return str(parsed)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid dam project ID format '{project_id}'. Must be a valid UUID v4 identifier.",
        )


def validate_filename_security(filename: str, allowed_extensions: set) -> Tuple[bool, Optional[str]]:
    """
    Validates that filename does not contain path traversal characters
    and has an allowed file extension.
    """
    if not filename:
        return False, "Filename cannot be empty."

    # Prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        return False, f"Filename '{filename}' contains invalid path traversal characters."

    ext = Path(filename).suffix.lower()
    if ext not in allowed_extensions:
        return False, f"File '{filename}' has unsupported extension '{ext}'. Allowed: {sorted(list(allowed_extensions))}"

    return True, None


def is_geographic_coords(minx: float, miny: float, maxx: float, maxy: float) -> bool:
    """Check if coordinates fall within WGS84 geographic degree boundaries."""
    return -180.0 <= minx <= 180.0 and -180.0 <= maxx <= 180.0 and -90.0 <= miny <= 90.0 and -90.0 <= maxy <= 90.0


def get_utm_epsg_for_lon_lat(lon: float, lat: float) -> str:
    """Determine local UTM EPSG code for a given WGS84 longitude/latitude coordinate."""
    zone = int((lon + 180) / 6) + 1
    if lat >= 0:
        return f"EPSG:{32600 + zone}"
    else:
        return f"EPSG:{32700 + zone}"


def validate_dam_project_dataset(
    dem_bytes: bytes,
    dem_filename: str,
    dam_axis_bytes: bytes,
    dam_axis_filename: str,
    reservoir_bytes: Optional[bytes] = None,
    reservoir_filename: Optional[str] = None,
    model_domain_bytes: Optional[bytes] = None,
    model_domain_filename: Optional[str] = None,
    downstream_outlet_bytes: Optional[bytes] = None,
    downstream_outlet_filename: Optional[str] = None,
    project_name: str = "New Dam Project",
    vertical_unit: Optional[str] = None,
    vertical_datum: Optional[str] = None,
    reservoir_level: Optional[float] = None,
    breach_width: Optional[float] = None,
    breach_center_x: Optional[float] = None,
    breach_center_y: Optional[float] = None,
    breach_formation_time_hr: Optional[float] = 1.0,
    manning_roughness: Optional[float] = 0.035,
    dam_crest_elevation: Optional[float] = None,
    breach_invert_elevation: Optional[float] = None,
    target_mesh_resolution_m: Optional[float] = None,
    simulation_duration_s: Optional[float] = None,
    output_interval_s: Optional[float] = None,
    geometry_crs: str = "EPSG:4326",
) -> DamProjectValidationResponse:
    """
    Performs rigorous spatial, geometric, and physical validation on uploaded dam project files.
    Calculates statistics block-wise, enforces HTTP 413 limits, calculates metric distances,
    and separates computational readiness from scientific verification.
    """
    # 1. Enforce payload size limits (HTTP 413)
    if len(dem_bytes) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"DEM file '{dem_filename}' size ({len(dem_bytes) / (1024*1024):.1f} MB) exceeds maximum limit of {MAX_UPLOAD_SIZE_BYTES / (1024*1024):.0f} MB.",
        )
    if len(dam_axis_bytes) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Dam axis file '{dam_axis_filename}' size exceeds maximum limit of {MAX_UPLOAD_SIZE_BYTES / (1024*1024):.0f} MB.",
        )
    if reservoir_bytes and len(reservoir_bytes) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Reservoir boundary file '{reservoir_filename}' size exceeds maximum limit of {MAX_UPLOAD_SIZE_BYTES / (1024*1024):.0f} MB.",
        )
    if model_domain_bytes and len(model_domain_bytes) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Model domain file '{model_domain_filename}' size exceeds maximum limit of {MAX_UPLOAD_SIZE_BYTES / (1024*1024):.0f} MB.",
        )
    if downstream_outlet_bytes and len(downstream_outlet_bytes) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Downstream outlet file '{downstream_outlet_filename}' size exceeds maximum limit of {MAX_UPLOAD_SIZE_BYTES / (1024*1024):.0f} MB.",
        )

    errors: List[str] = []
    warnings: List[str] = []
    assumptions: List[str] = []

    clean_project_name = (project_name or "New Dam Project").strip()
    if not clean_project_name:
        errors.append("Project name cannot be empty.")

    # 2. Filename Security Checks
    dem_safe, dem_err = validate_filename_security(dem_filename, ALLOWED_DEM_EXTENSIONS)
    if not dem_safe and dem_err:
        errors.append(dem_err)

    axis_safe, axis_err = validate_filename_security(dam_axis_filename, ALLOWED_GEOJSON_EXTENSIONS)
    if not axis_safe and axis_err:
        errors.append(axis_err)

    if reservoir_bytes and reservoir_filename:
        res_safe, res_err = validate_filename_security(reservoir_filename, ALLOWED_GEOJSON_EXTENSIONS)
        if not res_safe and res_err:
            errors.append(res_err)

    if model_domain_bytes and model_domain_filename:
        dom_safe, dom_err = validate_filename_security(model_domain_filename, ALLOWED_GEOJSON_EXTENSIONS)
        if not dom_safe and dom_err:
            errors.append(dom_err)

    if downstream_outlet_bytes and downstream_outlet_filename:
        out_safe, out_err = validate_filename_security(downstream_outlet_filename, ALLOWED_GEOJSON_EXTENSIONS)
        if not out_safe and out_err:
            errors.append(out_err)

    if errors:
        return DamProjectValidationResponse(
            valid=False,
            project_name=clean_project_name,
            errors=errors,
            warnings=warnings,
            normalized_metadata=None,
            assumptions_requiring_confirmation=assumptions,
            metadata_declared=False,
            onboarding_validation_passed=False,
            scientifically_verified=False,
        )

    raster_derived_meta: Optional[RasterDerivedMetadata] = None
    axis_meta: Optional[GeometryValidationMetadata] = None
    res_meta: Optional[GeometryValidationMetadata] = None
    domain_meta: Optional[GeometryValidationMetadata] = None
    outlet_meta: Optional[GeometryValidationMetadata] = None
    breach_on_axis = False
    breach_dist_m: Optional[float] = None
    distance_crs_used: Optional[str] = None

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        temp_dem_path = temp_path / "temp_dem.tif"
        temp_dem_path.write_bytes(dem_bytes)

        # 3. Comprehensive DEM Inspection
        dem_box = None
        dem_crs_obj = None
        dam_axis_geom_dem_crs = None
        dam_axis_centroid_lon_lat = None
        domain_geom_src = None

        try:
            with rasterio.open(temp_dem_path) as src:
                if src.count != 1:
                    errors.append(f"GeoTIFF has {src.count} bands. Exactly single-band (1 band) numeric elevation raster is required.")

                dtype_str = str(src.dtypes[0])
                if not ("int" in dtype_str or "float" in dtype_str):
                    errors.append(f"Unsupported raster data type '{dtype_str}'. Must be a numeric elevation band.")

                crs_wkt = src.crs.to_wkt() if src.crs else ""
                if not crs_wkt or not src.crs:
                    errors.append("GeoTIFF does not specify a valid Coordinate Reference System (CRS).")
                else:
                    dem_crs_obj = src.crs

                res_x, res_y = abs(src.res[0]), abs(src.res[1])
                bounds_left, bounds_bottom, bounds_right, bounds_top = src.bounds
                total_pixels = src.width * src.height

                if total_pixels > MAX_RASTER_PIXELS:
                    raise HTTPException(
                        status_code=413,
                        detail=f"DEM dimensions ({src.width}x{src.height} = {total_pixels:,} pixels) exceed maximum limit of {MAX_RASTER_PIXELS:,} pixels.",
                    )

                nodata_val = float(src.nodata) if src.nodata is not None else None
                dem_box = box(bounds_left, bounds_bottom, bounds_right, bounds_top)

                # Block-wise min/max computation
                min_elev = float("inf")
                max_elev = float("-inf")
                has_valid_pixels = False

                for _, window in src.block_windows(1):
                    block = src.read(1, window=window)
                    if nodata_val is not None:
                        valid_mask = ~np.isnan(block) & ~np.isclose(block, nodata_val)
                    else:
                        valid_mask = ~np.isnan(block)

                    if np.any(valid_mask):
                        has_valid_pixels = True
                        valid_data = block[valid_mask]
                        min_elev = min(min_elev, float(np.min(valid_data)))
                        max_elev = max(max_elev, float(np.max(valid_data)))

                if not has_valid_pixels:
                    errors.append("DEM GeoTIFF contains no valid numeric elevation pixels (all NoData/NaN).")
                    min_elev_res = None
                    max_elev_res = None
                else:
                    min_elev_res = min_elev
                    max_elev_res = max_elev

                raster_derived_meta = RasterDerivedMetadata(
                    width=src.width,
                    height=src.height,
                    band_count=src.count,
                    total_pixels=total_pixels,
                    dtype=dtype_str,
                    crs=src.crs.to_string() if src.crs else "UNKNOWN",
                    bounds=RasterBounds(
                        left=bounds_left,
                        bottom=bounds_bottom,
                        right=bounds_right,
                        top=bounds_top,
                    ),
                    resolution=RasterResolution(x=res_x, y=res_y),
                    nodata=nodata_val,
                    min_elevation=min_elev_res,
                    max_elevation=max_elev_res,
                    vertical_unit_in_header="unknown",
                    vertical_datum_in_header="unknown",
                )

        except HTTPException:
            raise
        except Exception as e:
            errors.append(f"Failed to read DEM raster file: {str(e)}")

        # 4. Dam Axis GeoJSON Inspection (Only LineString / MultiLineString permitted)
        try:
            axis_data = json.loads(dam_axis_bytes.decode("utf-8"))
            features = []
            if axis_data.get("type") == "FeatureCollection":
                features = axis_data.get("features", [])
            elif axis_data.get("type") == "Feature":
                features = [axis_data]
            elif "type" in axis_data and axis_data["type"] in ("LineString", "MultiLineString"):
                features = [{"type": "Feature", "geometry": axis_data, "properties": {}}]

            if len(features) > MAX_GEOJSON_FEATURES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Dam axis feature count ({len(features)}) exceeds maximum limit of {MAX_GEOJSON_FEATURES}.",
                )

            if not features:
                errors.append("Dam axis GeoJSON contains no valid features or geometries.")
            else:
                geom_types = set()
                geoms = []
                for idx, feat in enumerate(features):
                    g_dict = feat.get("geometry")
                    if g_dict:
                        sh_geom = shape(g_dict)
                        if not sh_geom.is_valid:
                            errors.append(f"Dam axis feature {idx} geometry is topologically invalid.")
                        g_type = sh_geom.geom_type
                        geom_types.add(g_type)
                        if g_type not in ("LineString", "MultiLineString"):
                            errors.append(f"Dam axis must contain only LineString or MultiLineString geometries. Found '{g_type}' in feature {idx}.")
                        geoms.append(sh_geom)

                if geoms and not any(t not in ("LineString", "MultiLineString") for t in geom_types):
                    dam_axis_geom_src = geoms[0] if len(geoms) == 1 else MultiLineString([g for g in geoms if isinstance(g, (LineString, MultiLineString))])
                    raw_centroid = (float(dam_axis_geom_src.centroid.x), float(dam_axis_geom_src.centroid.y))

                    src_geom_crs = CRS.from_user_input(geometry_crs or "EPSG:4326")
                    intersects_dem = False
                    fully_within_dem = False

                    if dem_box and dem_crs_obj:
                        try:
                            if src_geom_crs != dem_crs_obj:
                                transformer = Transformer.from_crs(src_geom_crs, dem_crs_obj, always_xy=True)
                                dam_axis_geom_dem_crs = shapely_transform(transformer.transform, dam_axis_geom_src)
                            else:
                                dam_axis_geom_dem_crs = dam_axis_geom_src

                            intersects_dem = bool(dem_box.intersects(dam_axis_geom_dem_crs))
                            fully_within_dem = bool(dem_box.contains(dam_axis_geom_dem_crs))

                            if not intersects_dem:
                                errors.append(f"Dam axis geometry is completely outside the DEM bounding extent.")
                            elif not fully_within_dem:
                                warnings.append(f"Dam axis geometry extends partially beyond the DEM raster bounding extent.")
                        except Exception as e:
                            errors.append(f"Failed to reproject dam axis geometry into DEM CRS: {e}")
                            dam_axis_geom_dem_crs = dam_axis_geom_src

                    if src_geom_crs.is_geographic:
                        dam_axis_centroid_lon_lat = raw_centroid
                    elif dem_crs_obj and dem_crs_obj.is_geographic:
                        dam_axis_centroid_lon_lat = (float(dam_axis_geom_dem_crs.centroid.x), float(dam_axis_geom_dem_crs.centroid.y)) if dam_axis_geom_dem_crs else raw_centroid
                    else:
                        try:
                            t_to_geo = Transformer.from_crs(src_geom_crs, "EPSG:4326", always_xy=True)
                            dam_axis_centroid_lon_lat = t_to_geo.transform(raw_centroid[0], raw_centroid[1])
                        except Exception:
                            dam_axis_centroid_lon_lat = (75.0, 15.0)

                    axis_meta = GeometryValidationMetadata(
                        layer_name="dam_axis",
                        feature_count=len(features),
                        geometry_types=list(geom_types),
                        is_valid=dam_axis_geom_src.is_valid if dam_axis_geom_src else False,
                        intersects_dem_bounds=intersects_dem,
                        fully_within_dem_bounds=fully_within_dem,
                        centroid_coords=raw_centroid,
                    )
        except Exception as e:
            errors.append(f"Failed to process dam axis: {e}")

        # 5. Reservoir Boundary GeoJSON Inspection (Only Polygon / MultiPolygon permitted)
        if reservoir_bytes and reservoir_filename:
            try:
                res_data = json.loads(reservoir_bytes.decode("utf-8"))
                r_features = []
                if res_data.get("type") == "FeatureCollection":
                    r_features = res_data.get("features", [])
                elif res_data.get("type") == "Feature":
                    r_features = [res_data]
                elif "type" in res_data and res_data["type"] in ("Polygon", "MultiPolygon"):
                    r_features = [{"type": "Feature", "geometry": res_data, "properties": {}}]

                if len(r_features) > MAX_GEOJSON_FEATURES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Reservoir feature count ({len(r_features)}) exceeds maximum limit of {MAX_GEOJSON_FEATURES}.",
                    )

                if r_features:
                    r_types = set()
                    r_geoms = []
                    for idx, feat in enumerate(r_features):
                        g_dict = feat.get("geometry")
                        if g_dict:
                            sh_geom = shape(g_dict)
                            if not sh_geom.is_valid:
                                errors.append(f"Reservoir feature {idx} geometry is topologically invalid.")
                            rg_type = sh_geom.geom_type
                            r_types.add(rg_type)
                            if rg_type not in ("Polygon", "MultiPolygon"):
                                errors.append(f"Reservoir boundary must contain only Polygon or MultiPolygon geometries. Found '{rg_type}' in feature {idx}.")
                            r_geoms.append(sh_geom)

                    if r_geoms and not any(t not in ("Polygon", "MultiPolygon") for t in r_types):
                        res_geom_src = r_geoms[0] if len(r_geoms) == 1 else MultiPolygon([g for g in r_geoms if isinstance(g, (Polygon, MultiPolygon))])
                        r_centroid = (float(res_geom_src.centroid.x), float(res_geom_src.centroid.y))

                        src_geom_crs = CRS.from_user_input(geometry_crs or "EPSG:4326")
                        r_intersects_dem = False
                        r_fully_within_dem = False

                        if dem_box and dem_crs_obj:
                            try:
                                if src_geom_crs != dem_crs_obj:
                                    transformer = Transformer.from_crs(src_geom_crs, dem_crs_obj, always_xy=True)
                                    res_geom_dem_crs = shapely_transform(transformer.transform, res_geom_src)
                                else:
                                    res_geom_dem_crs = res_geom_src

                                r_intersects_dem = bool(dem_box.intersects(res_geom_dem_crs))
                                r_fully_within_dem = bool(dem_box.contains(res_geom_dem_crs))

                                if not r_intersects_dem:
                                    errors.append("Reservoir boundary geometry is completely outside the DEM bounding extent.")
                                elif not r_fully_within_dem:
                                    warnings.append("Reservoir boundary geometry extends partially outside the DEM bounding extent.")
                            except Exception as e:
                                errors.append(f"Failed to reproject reservoir boundary geometry into DEM CRS: {e}")

                        res_meta = GeometryValidationMetadata(
                            layer_name="reservoir_boundary",
                            feature_count=len(r_features),
                            geometry_types=list(r_types),
                            is_valid=res_geom_src.is_valid if res_geom_src else False,
                            intersects_dem_bounds=r_intersects_dem,
                            fully_within_dem_bounds=r_fully_within_dem,
                            centroid_coords=r_centroid,
                        )

            except HTTPException:
                raise
            except json.JSONDecodeError as e:
                errors.append(f"Reservoir boundary file '{reservoir_filename}' is not valid JSON: {str(e)}")
            except Exception as e:
                errors.append(f"Failed to process reservoir boundary GeoJSON '{reservoir_filename}': {str(e)}")

        # 6. Model Domain GeoJSON Inspection (Polygon / MultiPolygon)
        if model_domain_bytes and model_domain_filename:
            try:
                dom_data = json.loads(model_domain_bytes.decode("utf-8"))
                d_features = []
                if dom_data.get("type") == "FeatureCollection":
                    d_features = dom_data.get("features", [])
                elif dom_data.get("type") == "Feature":
                    d_features = [dom_data]
                elif "type" in dom_data and dom_data["type"] in ("Polygon", "MultiPolygon"):
                    d_features = [{"type": "Feature", "geometry": dom_data, "properties": {}}]

                if len(d_features) > MAX_GEOJSON_FEATURES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Model domain feature count ({len(d_features)}) exceeds maximum limit of {MAX_GEOJSON_FEATURES}.",
                    )

                if d_features:
                    d_types = set()
                    d_geoms = []
                    for idx, feat in enumerate(d_features):
                        g_dict = feat.get("geometry")
                        if g_dict:
                            sh_geom = shape(g_dict)
                            if not sh_geom.is_valid:
                                errors.append(f"Model domain feature {idx} geometry is topologically invalid.")
                            dg_type = sh_geom.geom_type
                            d_types.add(dg_type)
                            if dg_type not in ("Polygon", "MultiPolygon"):
                                errors.append(f"Model domain must contain only Polygon or MultiPolygon geometries. Found '{dg_type}' in feature {idx}.")
                            d_geoms.append(sh_geom)

                    if d_geoms and not any(t not in ("Polygon", "MultiPolygon") for t in d_types):
                        domain_geom_src = d_geoms[0] if len(d_geoms) == 1 else MultiPolygon([g for g in d_geoms if isinstance(g, (Polygon, MultiPolygon))])
                        d_centroid = (float(domain_geom_src.centroid.x), float(domain_geom_src.centroid.y))

                        src_geom_crs = CRS.from_user_input(geometry_crs or "EPSG:4326")
                        d_intersects_dem = False
                        d_fully_within_dem = False

                        if dem_box and dem_crs_obj:
                            try:
                                if src_geom_crs != dem_crs_obj:
                                    transformer = Transformer.from_crs(src_geom_crs, dem_crs_obj, always_xy=True)
                                    dom_geom_dem_crs = shapely_transform(transformer.transform, domain_geom_src)
                                else:
                                    dom_geom_dem_crs = domain_geom_src

                                d_intersects_dem = bool(dem_box.intersects(dom_geom_dem_crs))
                                d_fully_within_dem = bool(dem_box.contains(dom_geom_dem_crs))

                                if not d_intersects_dem:
                                    errors.append("Model domain geometry is completely outside the DEM bounding extent.")
                                elif not d_fully_within_dem:
                                    warnings.append("Model domain geometry extends partially outside the DEM bounding extent.")
                            except Exception as e:
                                errors.append(f"Failed to reproject model domain geometry into DEM CRS: {e}")

                        domain_meta = GeometryValidationMetadata(
                            layer_name="model_domain",
                            feature_count=len(d_features),
                            geometry_types=list(d_types),
                            is_valid=domain_geom_src.is_valid if domain_geom_src else False,
                            intersects_dem_bounds=d_intersects_dem,
                            fully_within_dem_bounds=d_fully_within_dem,
                            centroid_coords=d_centroid,
                        )

            except HTTPException:
                raise
            except json.JSONDecodeError as e:
                errors.append(f"Model domain file '{model_domain_filename}' is not valid JSON: {str(e)}")
            except Exception as e:
                errors.append(f"Failed to process model domain GeoJSON '{model_domain_filename}': {str(e)}")

        # 7. Downstream Outlet GeoJSON Inspection (Point / LineString)
        if downstream_outlet_bytes and downstream_outlet_filename:
            try:
                out_data = json.loads(downstream_outlet_bytes.decode("utf-8"))
                o_features = []
                if out_data.get("type") == "FeatureCollection":
                    o_features = out_data.get("features", [])
                elif out_data.get("type") == "Feature":
                    o_features = [out_data]
                elif "type" in out_data and out_data["type"] in ("Point", "MultiPoint", "LineString", "MultiLineString"):
                    o_features = [{"type": "Feature", "geometry": out_data, "properties": {}}]

                if len(o_features) > MAX_GEOJSON_FEATURES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Downstream outlet feature count ({len(o_features)}) exceeds maximum limit of {MAX_GEOJSON_FEATURES}.",
                    )

                if o_features:
                    o_types = set()
                    o_geoms = []
                    for idx, feat in enumerate(o_features):
                        g_dict = feat.get("geometry")
                        if g_dict:
                            sh_geom = shape(g_dict)
                            if not sh_geom.is_valid:
                                errors.append(f"Downstream outlet feature {idx} geometry is topologically invalid.")
                            og_type = sh_geom.geom_type
                            o_types.add(og_type)
                            if og_type not in ("Point", "MultiPoint", "LineString", "MultiLineString"):
                                errors.append(f"Downstream outlet must contain only Point or LineString geometries. Found '{og_type}' in feature {idx}.")
                            o_geoms.append(sh_geom)

                    if o_geoms and not any(t not in ("Point", "MultiPoint", "LineString", "MultiLineString") for t in o_types):
                        outlet_geom_src = o_geoms[0] if len(o_geoms) == 1 else MultiPoint([g for g in o_geoms if isinstance(g, (Point, MultiPoint))])
                        o_centroid = (float(outlet_geom_src.centroid.x), float(outlet_geom_src.centroid.y))

                        src_geom_crs = CRS.from_user_input(geometry_crs or "EPSG:4326")
                        o_intersects_dem = False
                        o_fully_within_dem = False

                        if dem_box and dem_crs_obj:
                            try:
                                if src_geom_crs != dem_crs_obj:
                                    transformer = Transformer.from_crs(src_geom_crs, dem_crs_obj, always_xy=True)
                                    outlet_geom_dem_crs = shapely_transform(transformer.transform, outlet_geom_src)
                                else:
                                    outlet_geom_dem_crs = outlet_geom_src

                                o_intersects_dem = bool(dem_box.intersects(outlet_geom_dem_crs))
                                o_fully_within_dem = bool(dem_box.contains(outlet_geom_dem_crs))

                                if not o_intersects_dem:
                                    errors.append("Downstream outlet geometry is completely outside the DEM bounding extent.")
                            except Exception as e:
                                errors.append(f"Failed to reproject downstream outlet geometry into DEM CRS: {e}")

                        outlet_meta = GeometryValidationMetadata(
                            layer_name="downstream_outlet",
                            feature_count=len(o_features),
                            geometry_types=list(o_types),
                            is_valid=outlet_geom_src.is_valid if outlet_geom_src else False,
                            intersects_dem_bounds=o_intersects_dem,
                            fully_within_dem_bounds=o_fully_within_dem,
                            centroid_coords=o_centroid,
                        )

            except HTTPException:
                raise
            except json.JSONDecodeError as e:
                errors.append(f"Downstream outlet file '{downstream_outlet_filename}' is not valid JSON: {str(e)}")
            except Exception as e:
                errors.append(f"Failed to process downstream outlet GeoJSON '{downstream_outlet_filename}': {str(e)}")

        # 8. Breach Parameters & Metric Distance Calculation
        breach_pt_in_dem = False
        if reservoir_level is not None:
            if reservoir_level <= 0.0:
                errors.append(f"Reservoir level ({reservoir_level}) must be a positive numeric value.")
            elif raster_derived_meta and raster_derived_meta.min_elevation is not None and reservoir_level < raster_derived_meta.min_elevation:
                warnings.append(
                    f"Specified reservoir level ({reservoir_level}) is lower than the minimum DEM elevation ({raster_derived_meta.min_elevation:.1f})."
                )

        if breach_width is not None:
            if breach_width <= 0.0:
                errors.append(f"Breach width ({breach_width}) must be a positive numeric value.")
            elif breach_width > 5000.0:
                warnings.append(f"Breach width ({breach_width}) is exceptionally large (> 5000).")

        if breach_formation_time_hr is not None:
            if breach_formation_time_hr <= 0.0 or breach_formation_time_hr > 168.0:
                errors.append(f"Breach formation time ({breach_formation_time_hr} hr) must be between 0.01 and 168 hours.")

        if manning_roughness is not None:
            if manning_roughness <= 0.005 or manning_roughness > 0.3:
                warnings.append(f"Manning roughness n={manning_roughness} is outside standard hydraulic channel bounds (0.01 - 0.20).")

        if dam_crest_elevation is not None:
            if dam_crest_elevation <= 0.0:
                errors.append(f"Dam crest elevation ({dam_crest_elevation}) must be a positive numeric value.")

        if breach_invert_elevation is not None:
            if breach_invert_elevation <= 0.0:
                errors.append(f"Breach invert elevation ({breach_invert_elevation}) must be a positive numeric value.")

        if target_mesh_resolution_m is not None:
            if target_mesh_resolution_m <= 0.0 or target_mesh_resolution_m > 5000.0:
                errors.append(f"Target mesh resolution ({target_mesh_resolution_m} m) must be a positive numeric value <= 5000 m.")

        if simulation_duration_s is not None:
            if simulation_duration_s <= 0.0 or simulation_duration_s > 604800.0:
                errors.append(f"Simulation duration ({simulation_duration_s} s) must be between 1 and 604800 seconds (7 days).")

        if output_interval_s is not None:
            if output_interval_s <= 0.0:
                errors.append(f"Output interval ({output_interval_s} s) must be a positive numeric value.")
            elif simulation_duration_s is not None and output_interval_s > simulation_duration_s:
                errors.append(f"Output interval ({output_interval_s} s) cannot exceed simulation duration ({simulation_duration_s} s).")

        # Metric Distance Calculation (True Metres, Never Degree Euclidean Distance)
        if breach_center_x is not None and breach_center_y is not None:
            b_pt_raw = Point(breach_center_x, breach_center_y)
            src_geom_crs = CRS.from_user_input(geometry_crs or "EPSG:4326")

            if dem_box and dem_crs_obj:
                try:
                    if src_geom_crs != dem_crs_obj:
                        t_to_dem = Transformer.from_crs(src_geom_crs, dem_crs_obj, always_xy=True)
                        b_pt_dem = shapely_transform(t_to_dem.transform, b_pt_raw)
                    else:
                        b_pt_dem = b_pt_raw

                    breach_pt_in_dem = bool(dem_box.contains(b_pt_dem))
                    if not breach_pt_in_dem:
                        errors.append(f"Breach center coordinates lie outside the DEM bounding extent.")
                except Exception as e:
                    errors.append(f"Failed to project breach center into DEM CRS: {e}")

            if dam_axis_geom_dem_crs is not None:
                try:
                    if dem_crs_obj and not dem_crs_obj.is_geographic:
                        metric_crs_str = str(dem_crs_obj)
                        axis_metric = dam_axis_geom_dem_crs
                        if src_geom_crs != dem_crs_obj:
                            t_to_metric = Transformer.from_crs(src_geom_crs, dem_crs_obj, always_xy=True)
                            b_pt_metric = shapely_transform(t_to_metric.transform, b_pt_raw)
                        else:
                            b_pt_metric = b_pt_raw
                    else:
                        ref_lon = dam_axis_centroid_lon_lat[0] if dam_axis_centroid_lon_lat else breach_center_x
                        ref_lat = dam_axis_centroid_lon_lat[1] if dam_axis_centroid_lon_lat else breach_center_y
                        metric_crs_str = get_utm_epsg_for_lon_lat(ref_lon, ref_lat)
                        utm_crs = CRS.from_user_input(metric_crs_str)

                        t_axis_to_utm = Transformer.from_crs(dem_crs_obj if dem_crs_obj else "EPSG:4326", utm_crs, always_xy=True)
                        axis_metric = shapely_transform(t_axis_to_utm.transform, dam_axis_geom_dem_crs)

                        t_pt_to_utm = Transformer.from_crs(src_geom_crs, utm_crs, always_xy=True)
                        b_pt_metric = shapely_transform(t_pt_to_utm.transform, b_pt_raw)

                    dist_m = float(axis_metric.distance(b_pt_metric))
                    breach_dist_m = dist_m
                    distance_crs_used = metric_crs_str

                    tol_m = max(200.0, (raster_derived_meta.resolution.x * 5.0) if raster_derived_meta else 200.0)
                    if dist_m <= tol_m:
                        breach_on_axis = True
                    else:
                        warnings.append(
                            f"Breach center is located {dist_m:.1f} metres from the dam axis geometry (tolerance: {tol_m:.1f} m)."
                        )
                except Exception as e:
                    warnings.append(f"Could not compute metric distance between breach center and dam axis: {e}")

    # 9. Explicit Assumptions Requiring Confirmation
    metadata_declared = bool(vertical_unit and str(vertical_unit).strip() and vertical_datum and str(vertical_datum).strip())
    if metadata_declared:
        warnings.append("Metadata is user-declared and has not been independently verified.")
    else:
        if not (vertical_unit and str(vertical_unit).strip()):
            assumptions.append("DEM vertical unit is unknown in raster header and must be confirmed by the project engineer.")
        if not (vertical_datum and str(vertical_datum).strip()):
            assumptions.append("DEM vertical datum is unknown in raster header and must be confirmed by the project engineer.")

    if reservoir_level is not None:
        assumptions.append(f"Full reservoir level ({reservoir_level} {vertical_unit or 'units'}) must be verified against official dam structural records.")
    if breach_width is not None:
        assumptions.append(f"Breach parameterization (width = {breach_width} m, formation = {breach_formation_time_hr} hr) represents an idealized parametric failure scenario.")
    if manning_roughness is not None:
        assumptions.append(f"Channel Manning's roughness coefficient n={manning_roughness} is an uncalibrated baseline assumption.")

    # 10. Readiness Flags
    is_valid = len(errors) == 0

    onboarding_validation_passed = (
        is_valid
        and raster_derived_meta is not None
        and axis_meta is not None
        and axis_meta.fully_within_dem_bounds
        and (res_meta is None or res_meta.fully_within_dem_bounds)
        and (domain_meta is None or domain_meta.fully_within_dem_bounds)
        and (outlet_meta is None or outlet_meta.fully_within_dem_bounds)
        and breach_center_x is not None
        and breach_center_y is not None
        and breach_pt_in_dem
        and reservoir_level is not None
        and breach_width is not None
    )

    # Scientific verification remains false in this MVP because no authoritative evidence verification exists
    scientifically_verified = False

    user_meta = UserProvidedMetadata(
        project_name=clean_project_name,
        vertical_unit=vertical_unit,
        vertical_datum=vertical_datum,
        reservoir_level=reservoir_level,
        breach_width=breach_width,
        breach_center=(breach_center_x, breach_center_y) if breach_center_x is not None and breach_center_y is not None else None,
        breach_formation_time_hr=breach_formation_time_hr,
        manning_roughness=manning_roughness,
        dam_crest_elevation=dam_crest_elevation,
        breach_invert_elevation=breach_invert_elevation,
        target_mesh_resolution_m=target_mesh_resolution_m,
        simulation_duration_s=simulation_duration_s,
        output_interval_s=output_interval_s,
        geometry_crs=geometry_crs or "EPSG:4326",
    )

    normalized_meta = NormalizedProjectMetadata(
        project_name=clean_project_name,
        raster_metadata=raster_derived_meta,
        user_provided_metadata=user_meta,
        dam_axis_metadata=axis_meta,
        reservoir_metadata=res_meta,
        model_domain_metadata=domain_meta,
        downstream_outlet_metadata=outlet_meta,
        breach_on_dam_axis=breach_on_axis,
        breach_distance_to_axis_m=breach_dist_m,
        distance_calculation_crs=distance_crs_used,
    )

    return DamProjectValidationResponse(
        valid=is_valid,
        project_name=clean_project_name,
        errors=errors,
        warnings=warnings,
        normalized_metadata=normalized_meta,
        assumptions_requiring_confirmation=assumptions,
        metadata_declared=metadata_declared,
        onboarding_validation_passed=onboarding_validation_passed,
        scientifically_verified=scientifically_verified,
    )


def save_dam_project(
    dem_bytes: bytes,
    dem_filename: str,
    dam_axis_bytes: bytes,
    dam_axis_filename: str,
    reservoir_bytes: Optional[bytes] = None,
    reservoir_filename: Optional[str] = None,
    model_domain_bytes: Optional[bytes] = None,
    model_domain_filename: Optional[str] = None,
    downstream_outlet_bytes: Optional[bytes] = None,
    downstream_outlet_filename: Optional[str] = None,
    project_name: str = "New Dam Project",
    vertical_unit: Optional[str] = None,
    vertical_datum: Optional[str] = None,
    reservoir_level: Optional[float] = None,
    breach_width: Optional[float] = None,
    breach_center_x: Optional[float] = None,
    breach_center_y: Optional[float] = None,
    breach_formation_time_hr: Optional[float] = 1.0,
    manning_roughness: Optional[float] = 0.035,
    dam_crest_elevation: Optional[float] = None,
    breach_invert_elevation: Optional[float] = None,
    target_mesh_resolution_m: Optional[float] = None,
    simulation_duration_s: Optional[float] = None,
    output_interval_s: Optional[float] = None,
    geometry_crs: str = "EPSG:4326",
    acknowledge_unverified_metadata: bool = False,
) -> DamProjectDetailResponse:
    """
    Atomically persists a validated dam onboarding project to runtime storage:
    - Reuses validate_dam_project_dataset.
    - Requires onboarding_validation_passed=True.
    - Requires acknowledge_unverified_metadata=True.
    - Generates server-side UUID v4.
    - Stores dem.tif, dam_axis.geojson, reservoir_boundary.geojson, model_domain.geojson, downstream_outlet.geojson, project.json, and manifest.json.
    - Status is validated_unverified; scientifically_verified remains False.
    """
    if not acknowledge_unverified_metadata:
        raise HTTPException(
            status_code=422,
            detail="User acknowledgment of unverified metadata and simulation disclaimers is required to register project.",
        )

    val_res = validate_dam_project_dataset(
        dem_bytes=dem_bytes,
        dem_filename=dem_filename,
        dam_axis_bytes=dam_axis_bytes,
        dam_axis_filename=dam_axis_filename,
        reservoir_bytes=reservoir_bytes,
        reservoir_filename=reservoir_filename,
        model_domain_bytes=model_domain_bytes,
        model_domain_filename=model_domain_filename,
        downstream_outlet_bytes=downstream_outlet_bytes,
        downstream_outlet_filename=downstream_outlet_filename,
        project_name=project_name,
        vertical_unit=vertical_unit,
        vertical_datum=vertical_datum,
        reservoir_level=reservoir_level,
        breach_width=breach_width,
        breach_center_x=breach_center_x,
        breach_center_y=breach_center_y,
        breach_formation_time_hr=breach_formation_time_hr,
        manning_roughness=manning_roughness,
        dam_crest_elevation=dam_crest_elevation,
        breach_invert_elevation=breach_invert_elevation,
        target_mesh_resolution_m=target_mesh_resolution_m,
        simulation_duration_s=simulation_duration_s,
        output_interval_s=output_interval_s,
        geometry_crs=geometry_crs,
    )

    if not val_res.valid or not val_res.onboarding_validation_passed or not val_res.normalized_metadata:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Dam project onboarding validation failed.",
                "errors": val_res.errors,
                "warnings": val_res.warnings,
            },
        )

    project_id = str(uuid.uuid4())
    base_dir = get_dam_projects_dir()
    staging_dir = base_dir / f".tmp_{project_id}"
    final_dir = base_dir / project_id
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        staging_dir.mkdir(parents=True, exist_ok=True)

        # 1. Store standardized safe filenames
        dem_file_path = staging_dir / "dem.tif"
        dem_file_path.write_bytes(dem_bytes)

        axis_file_path = staging_dir / "dam_axis.geojson"
        axis_file_path.write_bytes(dam_axis_bytes)

        res_rel_name: Optional[str] = None
        if reservoir_bytes:
            res_file_path = staging_dir / "reservoir_boundary.geojson"
            res_file_path.write_bytes(reservoir_bytes)
            res_rel_name = "reservoir_boundary.geojson"

        dom_rel_name: Optional[str] = None
        if model_domain_bytes:
            dom_file_path = staging_dir / "model_domain.geojson"
            dom_file_path.write_bytes(model_domain_bytes)
            dom_rel_name = "model_domain.geojson"

        out_rel_name: Optional[str] = None
        if downstream_outlet_bytes:
            out_file_path = staging_dir / "downstream_outlet.geojson"
            out_file_path.write_bytes(downstream_outlet_bytes)
            out_rel_name = "downstream_outlet.geojson"

        norm_meta = val_res.normalized_metadata
        sim_params = {
            "dam_crest_elevation": dam_crest_elevation,
            "breach_invert_elevation": breach_invert_elevation,
            "target_mesh_resolution_m": target_mesh_resolution_m,
            "simulation_duration_s": simulation_duration_s,
            "output_interval_s": output_interval_s,
        }

        project_dict: Dict[str, Any] = {
            "project_id": project_id,
            "project_name": norm_meta.project_name,
            "status": "validated_unverified",
            "created_at": created_at,
            "dem_file": "dem.tif",
            "dam_axis_file": "dam_axis.geojson",
            "reservoir_boundary_file": res_rel_name,
            "model_domain_file": dom_rel_name,
            "downstream_outlet_file": out_rel_name,
            "raster_metadata": norm_meta.raster_metadata.model_dump() if norm_meta.raster_metadata else {},
            "user_provided_metadata": norm_meta.user_provided_metadata.model_dump() if norm_meta.user_provided_metadata else {},
            "dam_axis_metadata": norm_meta.dam_axis_metadata.model_dump() if norm_meta.dam_axis_metadata else {},
            "reservoir_metadata": norm_meta.reservoir_metadata.model_dump() if norm_meta.reservoir_metadata else None,
            "model_domain_metadata": norm_meta.model_domain_metadata.model_dump() if norm_meta.model_domain_metadata else None,
            "downstream_outlet_metadata": norm_meta.downstream_outlet_metadata.model_dump() if norm_meta.downstream_outlet_metadata else None,
            "breach_parameters": {
                "reservoir_level": reservoir_level,
                "breach_width": breach_width,
                "breach_center": [breach_center_x, breach_center_y] if breach_center_x is not None and breach_center_y is not None else None,
                "breach_formation_time_hr": breach_formation_time_hr,
                "manning_roughness": manning_roughness,
                "breach_on_dam_axis": norm_meta.breach_on_dam_axis,
                "breach_distance_to_axis_m": norm_meta.breach_distance_to_axis_m,
                "distance_calculation_crs": norm_meta.distance_calculation_crs,
            },
            "simulation_parameters": sim_params,
            "anuga_package_built": False,
            "assumptions_requiring_confirmation": val_res.assumptions_requiring_confirmation,
            "metadata_declared": val_res.metadata_declared,
            "onboarding_validation_passed": True,
            "scientifically_verified": False,
            "warnings": val_res.warnings,
        }

        proj_json_path = staging_dir / "project.json"
        proj_json_path.write_text(json.dumps(project_dict, indent=2), encoding="utf-8")

        # 2. Build immutable SHA-256 manifest
        file_hashes: Dict[str, str] = {
            "dem.tif": compute_file_sha256(dem_file_path) or "",
            "dam_axis.geojson": compute_file_sha256(axis_file_path) or "",
            "project.json": compute_file_sha256(proj_json_path) or "",
        }
        if res_rel_name:
            file_hashes[res_rel_name] = compute_file_sha256(staging_dir / res_rel_name) or ""
        if dom_rel_name:
            file_hashes[dom_rel_name] = compute_file_sha256(staging_dir / dom_rel_name) or ""
        if out_rel_name:
            file_hashes[out_rel_name] = compute_file_sha256(staging_dir / out_rel_name) or ""

        manifest_dict: Dict[str, Any] = {
            "manifest_version": "1.0",
            "project_id": project_id,
            "project_name": norm_meta.project_name,
            "created_at": created_at,
            "status": "validated_unverified",
            "scientifically_verified": False,
            "files": file_hashes,
        }
        manifest_path = staging_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_dict, indent=2), encoding="utf-8")

        project_dict["manifest"] = manifest_dict

        # 3. Atomic rename to final directory
        staging_dir.rename(final_dir)

    except Exception as e:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        if final_dir.exists():
            shutil.rmtree(final_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to persist dam project: {str(e)}")

    return DamProjectDetailResponse(**project_dict)


def verify_project_integrity(project_id: str) -> Dict[str, Any]:
    """
    Validates project UUID, verifies the physical directory, reads manifest.json,
    and recalculates SHA-256 for each registered file.
    Raises sanitized HTTP 409 if any file is missing, modified, or corrupted.
    Never exposes absolute paths or tracebacks.
    Returns the parsed manifest dictionary.
    """
    valid_id = validate_project_uuid(project_id)
    proj_dir = get_dam_projects_dir() / valid_id
    if not proj_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_id}' not found.")

    manifest_path = proj_dir / "manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "project_integrity_failed",
                "message": f"Project integrity manifest is missing for project '{valid_id}'."
            },
        )

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        files_dict = manifest_data.get("files", {})
        if not files_dict:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "project_integrity_failed",
                    "message": f"Manifest contains no recorded file hashes for project '{valid_id}'."
                },
            )

        for rel_name, expected_sha in files_dict.items():
            # Security check on manifest filenames: prevent traversal outside project directory
            if ".." in rel_name or rel_name.startswith("/") or rel_name.startswith("\\"):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "project_integrity_failed",
                        "message": f"Manifest contains invalid file reference '{rel_name}'."
                    },
                )
            target_file = (proj_dir / rel_name).resolve()
            if not str(target_file).startswith(str(proj_dir.resolve())):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "project_integrity_failed",
                        "message": f"Manifest contains invalid file reference '{rel_name}'."
                    },
                )
            target_file = proj_dir / rel_name
            if not target_file.is_file():
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "project_integrity_failed",
                        "message": f"Registered file '{rel_name}' is missing in project '{valid_id}'."
                    },
                )
            computed_sha = compute_file_sha256(target_file)
            if computed_sha != expected_sha:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "project_integrity_failed",
                        "message": f"SHA-256 integrity check failed for file '{rel_name}' in project '{valid_id}'."
                    },
                )

        return manifest_data
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "project_integrity_failed",
                "message": f"Integrity verification encountered an unreadable file or manifest in project '{valid_id}'."
            },
        )


def check_project_integrity_safe(project_id: str) -> Tuple[bool, Optional[str]]:
    """Safe integrity check for listing projects without raising exceptions."""
    try:
        verify_project_integrity(project_id)
        return True, None
    except HTTPException as e:
        if isinstance(e.detail, dict):
            return False, e.detail.get("message", "Integrity check failed")
        return False, str(e.detail)
    except Exception:
        return False, "Project files are unreadable or corrupted"


def list_dam_projects() -> List[DamProjectSummary]:
    """List all registered custom dam projects from runtime storage."""
    base_dir = get_dam_projects_dir()
    results: List[DamProjectSummary] = []

    for entry in base_dir.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            proj_json = entry / "project.json"
            manifest_json = entry / "manifest.json"
            if proj_json.is_file():
                try:
                    data = json.loads(proj_json.read_text(encoding="utf-8"))
                    r_meta = data.get("raster_metadata", {})
                    bounds_dict = r_meta.get("bounds", {"left": 0, "bottom": 0, "right": 0, "top": 0})
                    res_dict = r_meta.get("resolution", {"x": 0, "y": 0})

                    manifest_hash = ""
                    if manifest_json.is_file():
                        manifest_hash = compute_file_sha256(manifest_json) or ""

                    p_id = data.get("project_id", entry.name)
                    is_intact, integrity_err = check_project_integrity_safe(p_id)

                    notes = [
                        "Custom user-onboarded dam dataset",
                        "Validated geometry and parameter bounds; unverified physical datum",
                    ]
                    if not is_intact:
                        notes.append(f"Integrity check failed: {integrity_err}")

                    results.append(
                        DamProjectSummary(
                            project_id=p_id,
                            project_name=data.get("project_name", "Untitled Dam Project"),
                            status="integrity_failed" if not is_intact else data.get("status", "validated_unverified"),
                            available=is_intact,
                            integrity_status="integrity_ok" if is_intact else "integrity_failed",
                            integrity_error=integrity_err if not is_intact else None,
                            created_at=data.get("created_at", ""),
                            crs=r_meta.get("crs", "UNKNOWN"),
                            bounds=RasterBounds(**bounds_dict),
                            resolution=RasterResolution(**res_dict),
                            has_reservoir_boundary=data.get("reservoir_boundary_file") is not None,
                            metadata_declared=data.get("metadata_declared", False),
                            onboarding_validation_passed=data.get("onboarding_validation_passed", True),
                            scientifically_verified=False,
                            manifest_sha256=manifest_hash,
                            notes=notes,
                        )
                    )
                except Exception:
                    continue

    results.sort(key=lambda p: p.created_at, reverse=True)
    return results


def get_dam_project(project_id: str) -> DamProjectDetailResponse:
    """Retrieve full detail for a registered dam project by UUID v4."""
    manifest_data = verify_project_integrity(project_id)
    valid_id = validate_project_uuid(project_id)
    proj_dir = get_dam_projects_dir() / valid_id
    proj_json = proj_dir / "project.json"

    if not proj_json.is_file():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_id}' not found.")

    try:
        data = json.loads(proj_json.read_text(encoding="utf-8"))
        data["manifest"] = manifest_data
        zip_path = proj_dir / "packages" / "anuga_package.zip"
        if zip_path.is_file():
            data["anuga_package_built"] = True
            data["anuga_package_sha256"] = compute_file_sha256(zip_path)
        return DamProjectDetailResponse(**data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load dam project data: {str(e)}")


def get_dam_project_dem_metadata(project_id: str) -> RasterMetadataResponse:
    """Retrieve raster metadata for an onboarded dam project DEM."""
    verify_project_integrity(project_id)
    valid_id = validate_project_uuid(project_id)
    dem_path = get_dam_projects_dir() / valid_id / "dem.tif"

    if not dem_path.is_file():
        raise HTTPException(status_code=404, detail=f"DEM raster file for project '{valid_id}' not found.")

    with rasterio.open(dem_path) as src:
        b = src.bounds
        res_x = abs(src.res[0])
        res_y = abs(src.res[1])

        # Min/max from project.json cache if available
        proj_json = get_dam_projects_dir() / valid_id / "project.json"
        min_v = None
        max_v = None
        if proj_json.is_file():
            try:
                p_data = json.loads(proj_json.read_text(encoding="utf-8"))
                min_v = p_data.get("raster_metadata", {}).get("min_elevation")
                max_v = p_data.get("raster_metadata", {}).get("max_elevation")
            except Exception:
                pass

        return RasterMetadataResponse(
            id=f"custom_dem_{valid_id}",
            width=src.width,
            height=src.height,
            dtype=src.dtypes[0],
            crs=str(src.crs) if src.crs else None,
            bounds=RasterBounds(left=b.left, bottom=b.bottom, right=b.right, top=b.top),
            resolution=RasterResolution(x=res_x, y=res_y),
            nodata=src.nodata,
            valid_min=min_v,
            valid_max=max_v,
        )


def get_dam_project_dem_point_value(project_id: str, lon: float, lat: float) -> RasterPointValueResponse:
    """Query single point elevation value on an onboarded dam project DEM."""
    verify_project_integrity(project_id)
    valid_id = validate_project_uuid(project_id)
    dem_path = get_dam_projects_dir() / valid_id / "dem.tif"

    if not dem_path.is_file():
        raise HTTPException(status_code=404, detail=f"DEM raster for project '{valid_id}' not found.")

    with rasterio.open(dem_path) as src:
        query_x, query_y = lon, lat

        # Reproject WGS84 coordinate if DEM is in a projected CRS
        if src.crs and not src.crs.is_geographic:
            try:
                t = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                query_x, query_y = t.transform(lon, lat)
            except Exception:
                pass

        min_x = min(src.bounds.left, src.bounds.right)
        max_x = max(src.bounds.left, src.bounds.right)
        min_y = min(src.bounds.bottom, src.bounds.top)
        max_y = max(src.bounds.bottom, src.bounds.top)

        if not (min_x <= query_x <= max_x and min_y <= query_y <= max_y):
            raise HTTPException(
                status_code=422,
                detail=f"Coordinates ({lon}, {lat}) map outside project DEM bounding extent.",
            )

        row, col = src.index(query_x, query_y)
        if row < 0 or row >= src.height or col < 0 or col >= src.width:
            raise HTTPException(
                status_code=422,
                detail=f"Coordinates ({lon}, {lat}) map outside raster grid dimensions [{src.width}x{src.height}].",
            )

        pixel_window = Window(col, row, 1, 1)
        pixel_arr = src.read(1, window=pixel_window)
        raw_val = float(pixel_arr[0, 0])

        is_nodata = False
        if np.isnan(raw_val) or (src.nodata is not None and np.isclose(raw_val, src.nodata)) or raw_val <= -9000.0:
            is_nodata = True
            raw_val = None

        return RasterPointValueResponse(
            id=f"custom_dem_{valid_id}",
            row=int(row),
            column=int(col),
            value=raw_val,
            is_nodata=is_nodata,
        )


def get_dam_project_dem_tile(project_id: str, z: int, x: int, y: int) -> bytes:
    """Render 256x256 Web Mercator PNG tile for an onboarded dam project DEM."""
    verify_project_integrity(project_id)
    valid_id = validate_project_uuid(project_id)
    dem_path = get_dam_projects_dir() / valid_id / "dem.tif"

    if not dem_path.is_file():
        raise HTTPException(status_code=404, detail=f"DEM file for project '{valid_id}' not found.")

    if z < 0 or z > 24:
        return EMPTY_TILE_PNG
    max_coord = 1 << z
    if x < 0 or x >= max_coord or y < 0 or y >= max_coord:
        return EMPTY_TILE_PNG

    try:
        with Reader(str(dem_path)) as reader:
            nodata = getattr(reader.dataset, "nodata", None)
            img_data = reader.tile(tile_x=x, tile_y=y, tile_z=z)
            if img_data.data.shape[0] == 0:
                return EMPTY_TILE_PNG

            band_2d = img_data.data[0].astype(np.float32)
            rgba = apply_colormap_and_transparency(band_2d, dataset_id="dem", meta_nodata=nodata)

            out_img = Image.fromarray(rgba, mode="RGBA")
            buf = io.BytesIO()
            out_img.save(buf, format="PNG", optimize=True)
            return buf.getvalue()

    except Exception:
        return EMPTY_TILE_PNG


def get_dam_project_dam_axis_geometry(project_id: str) -> Dict[str, Any]:
    """Retrieve dam axis geometry as EPSG:4326 GeoJSON FeatureCollection."""
    verify_project_integrity(project_id)
    valid_id = validate_project_uuid(project_id)
    proj_dir = get_dam_projects_dir() / valid_id
    axis_path = proj_dir / "dam_axis.geojson"
    proj_json = proj_dir / "project.json"

    if not axis_path.is_file():
        raise HTTPException(status_code=404, detail=f"Dam axis geometry file not found for project '{valid_id}'.")

    geometry_crs = "EPSG:4326"
    if proj_json.is_file():
        try:
            p_data = json.loads(proj_json.read_text(encoding="utf-8"))
            geometry_crs = p_data.get("user_provided_metadata", {}).get("geometry_crs", "EPSG:4326")
        except Exception:
            pass

    try:
        axis_raw = json.loads(axis_path.read_text(encoding="utf-8"))
        features = []
        if axis_raw.get("type") == "FeatureCollection":
            features = axis_raw.get("features", [])
        elif axis_raw.get("type") == "Feature":
            features = [axis_raw]
        elif "type" in axis_raw and axis_raw["type"] in ("LineString", "MultiLineString"):
            features = [{"type": "Feature", "geometry": axis_raw, "properties": {}}]

        src_crs = CRS.from_user_input(geometry_crs)
        target_crs = CRS.from_user_input("EPSG:4326")
        needs_transform = (src_crs != target_crs)
        transformer = Transformer.from_crs(src_crs, target_crs, always_xy=True) if needs_transform else None

        out_features = []
        for feat in features:
            geom_dict = feat.get("geometry")
            if not geom_dict:
                continue
            sh_geom = shape(geom_dict)
            if needs_transform and transformer:
                sh_geom = shapely_transform(transformer.transform, sh_geom)

            out_features.append({
                "type": "Feature",
                "geometry": json.loads(json.dumps(sh_geom.__geo_interface__)),
                "properties": {
                    "layer": "dam_axis",
                    "label": "User-provided Dam Axis",
                    "provenance": "user_declared_unverified",
                    "original_crs": geometry_crs,
                    "simulation_status": "no_simulation_executed",
                }
            })

        return {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
            "features": out_features,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process dam axis geometry: {str(e)}")


def get_dam_project_reservoir_geometry(project_id: str) -> Dict[str, Any]:
    """Retrieve reservoir boundary geometry as EPSG:4326 GeoJSON FeatureCollection."""
    verify_project_integrity(project_id)
    valid_id = validate_project_uuid(project_id)
    proj_dir = get_dam_projects_dir() / valid_id
    res_path = proj_dir / "reservoir_boundary.geojson"
    proj_json = proj_dir / "project.json"

    if not res_path.is_file():
        raise HTTPException(status_code=404, detail=f"No reservoir boundary geometry registered for project '{valid_id}'.")

    geometry_crs = "EPSG:4326"
    if proj_json.is_file():
        try:
            p_data = json.loads(proj_json.read_text(encoding="utf-8"))
            if not p_data.get("reservoir_boundary_file"):
                raise HTTPException(status_code=404, detail=f"No reservoir boundary geometry registered for project '{valid_id}'.")
            geometry_crs = p_data.get("user_provided_metadata", {}).get("geometry_crs", "EPSG:4326")
        except HTTPException:
            raise
        except Exception:
            pass

    try:
        res_raw = json.loads(res_path.read_text(encoding="utf-8"))
        features = []
        if res_raw.get("type") == "FeatureCollection":
            features = res_raw.get("features", [])
        elif res_raw.get("type") == "Feature":
            features = [res_raw]
        elif "type" in res_raw and res_raw["type"] in ("Polygon", "MultiPolygon"):
            features = [{"type": "Feature", "geometry": res_raw, "properties": {}}]

        src_crs = CRS.from_user_input(geometry_crs)
        target_crs = CRS.from_user_input("EPSG:4326")
        needs_transform = (src_crs != target_crs)
        transformer = Transformer.from_crs(src_crs, target_crs, always_xy=True) if needs_transform else None

        out_features = []
        for feat in features:
            geom_dict = feat.get("geometry")
            if not geom_dict:
                continue
            sh_geom = shape(geom_dict)
            if needs_transform and transformer:
                sh_geom = shapely_transform(transformer.transform, sh_geom)

            out_features.append({
                "type": "Feature",
                "geometry": json.loads(json.dumps(sh_geom.__geo_interface__)),
                "properties": {
                    "layer": "reservoir_boundary",
                    "label": "User-provided Reservoir Boundary",
                    "provenance": "user_declared_unverified",
                    "original_crs": geometry_crs,
                    "simulation_status": "no_simulation_executed",
                }
            })

        return {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
            "features": out_features,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process reservoir boundary geometry: {str(e)}")


def get_dam_project_breach_geometry(project_id: str) -> Dict[str, Any]:
    """Retrieve hypothetical breach location Point as EPSG:4326 GeoJSON FeatureCollection."""
    verify_project_integrity(project_id)
    valid_id = validate_project_uuid(project_id)
    proj_dir = get_dam_projects_dir() / valid_id
    proj_json = proj_dir / "project.json"

    if not proj_json.is_file():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_id}' not found.")

    try:
        p_data = json.loads(proj_json.read_text(encoding="utf-8"))
        user_meta = p_data.get("user_provided_metadata", {})
        breach_params = p_data.get("breach_parameters", {})

        breach_center = user_meta.get("breach_center") or breach_params.get("breach_center")
        if not breach_center or len(breach_center) != 2:
            raise HTTPException(status_code=404, detail=f"No breach center coordinates found for project '{valid_id}'.")

        bx, by = float(breach_center[0]), float(breach_center[1])
        geometry_crs = user_meta.get("geometry_crs", "EPSG:4326")

        src_crs = CRS.from_user_input(geometry_crs)
        target_crs = CRS.from_user_input("EPSG:4326")
        if src_crs != target_crs:
            t = Transformer.from_crs(src_crs, target_crs, always_xy=True)
            lon_wgs84, lat_wgs84 = t.transform(bx, by)
        else:
            lon_wgs84, lat_wgs84 = bx, by

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon_wgs84, lat_wgs84]
            },
            "properties": {
                "layer": "breach_point",
                "label": "Hypothetical Breach Location",
                "provenance": "user_declared_unverified",
                "breach_width_m": breach_params.get("breach_width") or user_meta.get("breach_width"),
                "reservoir_level": breach_params.get("reservoir_level") or user_meta.get("reservoir_level"),
                "breach_formation_time_hr": breach_params.get("breach_formation_time_hr") or user_meta.get("breach_formation_time_hr"),
                "original_coordinates": [bx, by],
                "original_crs": geometry_crs,
                "simulation_status": "no_simulation_executed",
            }
        }

        return {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
            "features": [feature],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process breach location geometry: {str(e)}")


def get_dam_project_model_domain_geometry(project_id: str) -> Dict[str, Any]:
    """Retrieve model domain geometry as EPSG:4326 GeoJSON FeatureCollection."""
    verify_project_integrity(project_id)
    valid_id = validate_project_uuid(project_id)
    proj_dir = get_dam_projects_dir() / valid_id
    dom_path = proj_dir / "model_domain.geojson"
    proj_json = proj_dir / "project.json"

    if not dom_path.is_file():
        raise HTTPException(status_code=404, detail=f"No model domain geometry registered for project '{valid_id}'.")

    geometry_crs = "EPSG:4326"
    if proj_json.is_file():
        try:
            p_data = json.loads(proj_json.read_text(encoding="utf-8"))
            if not p_data.get("model_domain_file"):
                raise HTTPException(status_code=404, detail=f"No model domain geometry registered for project '{valid_id}'.")
            geometry_crs = p_data.get("user_provided_metadata", {}).get("geometry_crs", "EPSG:4326")
        except HTTPException:
            raise
        except Exception:
            pass

    try:
        dom_raw = json.loads(dom_path.read_text(encoding="utf-8"))
        features = []
        if dom_raw.get("type") == "FeatureCollection":
            features = dom_raw.get("features", [])
        elif dom_raw.get("type") == "Feature":
            features = [dom_raw]
        elif "type" in dom_raw and dom_raw["type"] in ("Polygon", "MultiPolygon"):
            features = [{"type": "Feature", "geometry": dom_raw, "properties": {}}]

        src_crs = CRS.from_user_input(geometry_crs)
        target_crs = CRS.from_user_input("EPSG:4326")
        needs_transform = (src_crs != target_crs)
        transformer = Transformer.from_crs(src_crs, target_crs, always_xy=True) if needs_transform else None

        out_features = []
        for feat in features:
            geom_dict = feat.get("geometry")
            if not geom_dict:
                continue
            sh_geom = shape(geom_dict)
            if needs_transform and transformer:
                sh_geom = shapely_transform(transformer.transform, sh_geom)

            out_features.append({
                "type": "Feature",
                "geometry": json.loads(json.dumps(sh_geom.__geo_interface__)),
                "properties": {
                    "layer": "model_domain",
                    "label": "User-provided Model Domain",
                    "provenance": "user_declared_unverified",
                    "original_crs": geometry_crs,
                    "simulation_status": "no_simulation_executed",
                }
            })

        return {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
            "features": out_features,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process model domain geometry: {str(e)}")


def get_dam_project_outlet_geometry(project_id: str) -> Dict[str, Any]:
    """Retrieve downstream outlet boundary geometry as EPSG:4326 GeoJSON FeatureCollection."""
    verify_project_integrity(project_id)
    valid_id = validate_project_uuid(project_id)
    proj_dir = get_dam_projects_dir() / valid_id
    out_path = proj_dir / "downstream_outlet.geojson"
    proj_json = proj_dir / "project.json"

    if not out_path.is_file():
        raise HTTPException(status_code=404, detail=f"No downstream outlet geometry registered for project '{valid_id}'.")

    geometry_crs = "EPSG:4326"
    if proj_json.is_file():
        try:
            p_data = json.loads(proj_json.read_text(encoding="utf-8"))
            if not p_data.get("downstream_outlet_file"):
                raise HTTPException(status_code=404, detail=f"No downstream outlet geometry registered for project '{valid_id}'.")
            geometry_crs = p_data.get("user_provided_metadata", {}).get("geometry_crs", "EPSG:4326")
        except HTTPException:
            raise
        except Exception:
            pass

    try:
        out_raw = json.loads(out_path.read_text(encoding="utf-8"))
        features = []
        if out_raw.get("type") == "FeatureCollection":
            features = out_raw.get("features", [])
        elif out_raw.get("type") == "Feature":
            features = [out_raw]
        elif "type" in out_raw and out_raw["type"] in ("Point", "MultiPoint", "LineString", "MultiLineString"):
            features = [{"type": "Feature", "geometry": out_raw, "properties": {}}]

        src_crs = CRS.from_user_input(geometry_crs)
        target_crs = CRS.from_user_input("EPSG:4326")
        needs_transform = (src_crs != target_crs)
        transformer = Transformer.from_crs(src_crs, target_crs, always_xy=True) if needs_transform else None

        out_features = []
        for feat in features:
            geom_dict = feat.get("geometry")
            if not geom_dict:
                continue
            sh_geom = shape(geom_dict)
            if needs_transform and transformer:
                sh_geom = shapely_transform(transformer.transform, sh_geom)

            out_features.append({
                "type": "Feature",
                "geometry": json.loads(json.dumps(sh_geom.__geo_interface__)),
                "properties": {
                    "layer": "downstream_outlet",
                    "label": "User-provided Downstream Outlet",
                    "provenance": "user_declared_unverified",
                    "original_crs": geometry_crs,
                    "simulation_status": "no_simulation_executed",
                }
            })

        return {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
            "features": out_features,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process downstream outlet geometry: {str(e)}")


def assess_anuga_preflight(project_id: str) -> DamProjectAnugaPreflightResponse:
    """Assess simulation-readiness for an onboarded dam project against ANUGA requirements.

    Never modifies project files. Verifies integrity prior to assessment.
    """
    verify_project_integrity(project_id)
    valid_id = validate_project_uuid(project_id)
    proj_dir = get_dam_projects_dir() / valid_id
    proj_json = proj_dir / "project.json"

    if not proj_json.is_file():
        raise HTTPException(status_code=404, detail=f"Dam project '{valid_id}' not found.")

    try:
        p_data = json.loads(proj_json.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load project manifest: {str(e)}")

    user_meta = p_data.get("user_provided_metadata", {})
    norm_meta = p_data.get("normalized_metadata", {})
    raster_meta = p_data.get("raster_metadata", {})
    sim_params = p_data.get("simulation_parameters", {})

    blockers: List[str] = []
    warnings: List[str] = []
    derived_checks: Dict[str, Any] = {}
    proposed_configuration: Dict[str, Any] = {}

    # 1. Reservoir boundary requirement
    has_res = bool(p_data.get("reservoir_boundary_file"))
    res_meta = p_data.get("reservoir_metadata")
    res_shape = None
    if not has_res or not res_meta:
        blockers.append("Reservoir boundary geometry is required for hydrodynamic initial condition specification.")
    elif not res_meta.get("is_valid", False):
        blockers.append("Reservoir boundary geometry is topologically invalid.")
    elif not res_meta.get("fully_within_dem_bounds", False):
        blockers.append("Reservoir boundary geometry extends outside the DEM bounding extent.")
    else:
        res_file = proj_dir / "reservoir_boundary.geojson"
        if res_file.is_file():
            try:
                res_raw = json.loads(res_file.read_text(encoding="utf-8"))
                r_feats = res_raw.get("features", [res_raw]) if res_raw.get("type") in ("FeatureCollection", "Feature") else [{"geometry": res_raw}]
                r_geoms = [shape(f["geometry"]) for f in r_feats if f.get("geometry")]
                if r_geoms:
                    res_shape = r_geoms[0] if len(r_geoms) == 1 else MultiPolygon([g for g in r_geoms if isinstance(g, (Polygon, MultiPolygon))])
            except Exception:
                pass

    # 2. Model domain requirement (Must be fully inside DEM coverage)
    has_domain = bool(p_data.get("model_domain_file"))
    domain_meta = p_data.get("model_domain_metadata")
    dom_shape = None
    if not has_domain or not domain_meta:
        blockers.append("Model domain boundary (Polygon) is required to generate the ANUGA 2D triangular computational mesh.")
    elif not domain_meta.get("is_valid", False):
        blockers.append("Model domain geometry is topologically invalid.")
    elif not domain_meta.get("fully_within_dem_bounds", False):
        blockers.append("Model domain geometry extends outside the DEM bounding extent.")
    else:
        dom_file = proj_dir / "model_domain.geojson"
        if dom_file.is_file():
            try:
                dom_raw = json.loads(dom_file.read_text(encoding="utf-8"))
                feats = dom_raw.get("features", [dom_raw]) if dom_raw.get("type") in ("FeatureCollection", "Feature") else [{"geometry": dom_raw}]
                geoms = [shape(f["geometry"]) for f in feats if f.get("geometry")]
                if geoms:
                    dom_shape = geoms[0] if len(geoms) == 1 else MultiPolygon([g for g in geoms if isinstance(g, (Polygon, MultiPolygon))])
            except Exception:
                pass

    # Reservoir must be fully inside model domain
    if dom_shape is not None and res_shape is not None:
        try:
            diff = res_shape.difference(dom_shape)
            if not diff.is_empty and diff.area > 1e-7:
                blockers.append("Reservoir boundary geometry must be fully contained within the computational model domain polygon.")
        except Exception as e:
            warnings.append(f"Could not verify containment of reservoir within model domain: {e}")

    # 3. Downstream outlet requirement (Must be LineString/MultiLineString touching model domain exterior boundary)
    has_outlet = bool(p_data.get("downstream_outlet_file"))
    outlet_meta = p_data.get("downstream_outlet_metadata")
    outlet_shape = None
    if not has_outlet or not outlet_meta:
        blockers.append("Downstream outlet boundary (LineString) is required to establish hydrodynamic open boundary conditions.")
    elif not outlet_meta.get("is_valid", False):
        blockers.append("Downstream outlet geometry is topologically invalid.")
    elif not outlet_meta.get("fully_within_dem_bounds", False):
        blockers.append("Downstream outlet geometry extends outside the DEM bounding extent.")
    else:
        out_types = outlet_meta.get("geometry_types", [])
        if any(t in ("Point", "MultiPoint") for t in out_types):
            blockers.append(
                "Downstream outlet for ANUGA simulation must be a LineString or MultiLineString along the model domain boundary "
                "(Point geometries cannot establish open boundary condition segments)."
            )

        out_file = proj_dir / "downstream_outlet.geojson"
        if out_file.is_file():
            try:
                out_raw = json.loads(out_file.read_text(encoding="utf-8"))
                feats = out_raw.get("features", [out_raw]) if out_raw.get("type") in ("FeatureCollection", "Feature") else [{"geometry": out_raw}]
                geoms = [shape(f["geometry"]) for f in feats if f.get("geometry")]
                if geoms:
                    outlet_shape = geoms[0]
            except Exception:
                pass

        if dom_shape is not None and outlet_shape is not None:
            try:
                # Must touch or intersect exterior boundary of model domain
                boundary_geom = dom_shape.boundary if hasattr(dom_shape, "boundary") else None
                touches_ext = False
                if boundary_geom is not None:
                    touches_ext = boundary_geom.intersects(outlet_shape) or boundary_geom.distance(outlet_shape) < 1e-4
                if not touches_ext:
                    blockers.append("Downstream outlet LineString must touch or intersect the exterior boundary of the model domain.")
            except Exception as e:
                warnings.append(f"Could not verify outlet boundary contact: {e}")

    # 4. Dam Axis requirement (Single LineString, inside domain, touches reservoir)
    axis_file = proj_dir / "dam_axis.geojson"
    axis_shape = None
    if axis_file.is_file():
        try:
            axis_raw = json.loads(axis_file.read_text(encoding="utf-8"))
            ax_feats = axis_raw.get("features", [axis_raw]) if axis_raw.get("type") in ("FeatureCollection", "Feature") else [{"geometry": axis_raw}]
            ax_geoms = [shape(f["geometry"]) for f in ax_feats if f.get("geometry")]
            if len(ax_geoms) == 1 and ax_geoms[0].geom_type == "LineString":
                axis_shape = ax_geoms[0]
            elif len(ax_geoms) > 1 or (ax_geoms and ax_geoms[0].geom_type != "LineString"):
                blockers.append("Dam axis geometry must resolve to a single continuous LineString for hydrodynamic crest burning.")
        except Exception:
            blockers.append("Failed to load dam axis geometry.")

    if dom_shape is not None and axis_shape is not None:
        try:
            diff_axis = axis_shape.difference(dom_shape)
            if not diff_axis.is_empty and diff_axis.length > 1e-5:
                blockers.append("Dam axis geometry must lie within the computational model domain polygon.")
        except Exception as e:
            warnings.append(f"Could not verify dam axis containment within model domain: {e}")

    if res_shape is not None and axis_shape is not None:
        try:
            touches_res = res_shape.intersects(axis_shape) or res_shape.boundary.intersects(axis_shape) or res_shape.distance(axis_shape) < 1e-4
            if not touches_res:
                blockers.append("Dam axis must touch or intersect the reservoir boundary geometry.")
        except Exception as e:
            warnings.append(f"Could not verify dam axis intersection with reservoir boundary: {e}")

    # 5. Vertical Unit & Datum
    v_unit = user_meta.get("vertical_unit")
    v_datum = user_meta.get("vertical_datum")
    if not v_unit or str(v_unit).strip().lower() in ("unknown", ""):
        blockers.append("DEM vertical unit is missing or unknown. An authoritative unit (e.g. 'meters') is required to define physical elevation heads.")
    if not v_datum or str(v_datum).strip().lower() in ("unknown", ""):
        blockers.append("DEM vertical datum is missing or unknown. An authoritative datum (e.g. 'MSL', 'EGM96') is required for hydrodynamic water level reference.")

    # 6. Reservoir Level & Physical Elevations (Dam crest > Reservoir level > Breach invert)
    res_lvl = user_meta.get("reservoir_level")
    crest_elev = user_meta.get("dam_crest_elevation")
    invert_elev = user_meta.get("breach_invert_elevation")

    if res_lvl is None or res_lvl <= 0.0:
        blockers.append("Reservoir full supply water level (FSL) is missing or invalid.")

    if crest_elev is None or crest_elev <= 0.0:
        blockers.append("Dam crest elevation is missing or invalid.")

    if invert_elev is None or invert_elev <= 0.0:
        blockers.append("Breach invert elevation is missing or invalid.")

    if crest_elev is not None and res_lvl is not None:
        if crest_elev <= res_lvl:
            blockers.append(f"Dam crest elevation ({crest_elev:.2f} {v_unit or 'm'}) must be strictly greater than reservoir water level ({res_lvl:.2f} {v_unit or 'm'}).")

    if invert_elev is not None and res_lvl is not None:
        if invert_elev >= res_lvl:
            blockers.append(f"Breach invert elevation ({invert_elev:.2f} {v_unit or 'm'}) must be strictly less than reservoir water level ({res_lvl:.2f} {v_unit or 'm'}).")

    if invert_elev is not None and crest_elev is not None:
        if invert_elev >= crest_elev:
            blockers.append(f"Breach invert elevation ({invert_elev:.2f} {v_unit or 'm'}) must be strictly less than dam crest elevation ({crest_elev:.2f} {v_unit or 'm'}).")

    # Sample local DEM at breach center
    breach_center = user_meta.get("breach_center")
    if breach_center and len(breach_center) == 2 and invert_elev is not None:
        dem_file_path = proj_dir / "dem.tif"
        if dem_file_path.is_file():
            try:
                with rasterio.open(dem_file_path) as d_src:
                    bx, by = float(breach_center[0]), float(breach_center[1])
                    geom_crs_str = user_meta.get("geometry_crs", "EPSG:4326")
                    src_crs = CRS.from_user_input(geom_crs_str)
                    if d_src.crs and src_crs != d_src.crs:
                        t = Transformer.from_crs(src_crs, d_src.crs, always_xy=True)
                        bx, by = t.transform(bx, by)
                    row, col = d_src.index(bx, by)
                    if 0 <= row < d_src.height and 0 <= col < d_src.width:
                        local_val = float(d_src.read(1, window=Window(col, row, 1, 1))[0, 0])
                        if not np.isnan(local_val) and local_val > -9000:
                            if invert_elev < local_val:
                                warnings.append(
                                    f"Breach invert elevation ({invert_elev:.2f} m) is lower than local baseline DEM terrain ({local_val:.2f} m) at breach location; verify scour/invert assumption."
                                )
            except Exception:
                pass

    # 7. Breach Parameters & Proximity to Axis
    b_width = user_meta.get("breach_width")
    if b_width is None or b_width <= 0.0:
        blockers.append("Breach width is missing or invalid.")

    if not breach_center or len(breach_center) != 2:
        blockers.append("Breach center coordinates are missing.")

    breach_params = p_data.get("breach_parameters", {})
    breach_on_axis = breach_params.get("breach_on_dam_axis", True)
    breach_dist_m = breach_params.get("breach_distance_to_axis_m", 0.0)
    if not breach_on_axis:
        blockers.append(f"Breach center is located {breach_dist_m:.1f} m from the dam axis geometry (exceeds allowable tolerance).")

    # 8. Mesh and Simulation Time Parameters
    mesh_res_m = user_meta.get("target_mesh_resolution_m") or sim_params.get("target_mesh_resolution_m")
    sim_dur_s = user_meta.get("simulation_duration_s") or sim_params.get("simulation_duration_s")
    out_int_s = user_meta.get("output_interval_s") or sim_params.get("output_interval_s")

    if mesh_res_m is None or mesh_res_m <= 0.0 or mesh_res_m > 5000.0:
        blockers.append("Target mesh resolution is missing or invalid (must be between 1 and 5000 metres).")

    if sim_dur_s is None or sim_dur_s <= 0.0 or sim_dur_s > 604800.0:
        blockers.append("Simulation duration is missing or invalid (must be between 1 and 604800 seconds).")

    if out_int_s is None or out_int_s <= 0.0:
        blockers.append("Output interval is missing or invalid (must be a positive numeric value in seconds).")
    elif sim_dur_s is not None and out_int_s > sim_dur_s:
        blockers.append(f"Output interval ({out_int_s} s) cannot exceed simulation duration ({sim_dur_s} s).")

    # 9. Formation Time and Manning Roughness Warnings
    form_time_hr = user_meta.get("breach_formation_time_hr")
    if form_time_hr is not None and form_time_hr > 0.0:
        warnings.append(
            f"Breach formation time ({form_time_hr} hr) is reported as unsupported in this ANUGA script release; "
            "an instantaneous hypothetical dam-break formulation is implemented instead."
        )

    warnings.append("All simulation parameters and elevation records are user-declared and have not been independently verified.")

    manning_n = user_meta.get("manning_roughness")
    if manning_n is not None and (manning_n < 0.01 or manning_n > 0.20):
        warnings.append(f"Manning roughness coefficient n={manning_n} is outside standard hydraulic channel bounds (0.01 - 0.20).")

    # 10. Derived Computations
    domain_area_km2 = None
    estimated_triangles = None
    max_triangle_area_m2 = None

    if dom_shape is not None:
        try:
            geom_crs_str = user_meta.get("geometry_crs", "EPSG:4326")
            src_crs = CRS.from_user_input(geom_crs_str)
            if src_crs.is_geographic:
                c_lon, c_lat = dom_shape.centroid.x, dom_shape.centroid.y
                utm_crs_str = get_utm_epsg_for_lon_lat(c_lon, c_lat)
                utm_crs = CRS.from_user_input(utm_crs_str)
                transformer = Transformer.from_crs(src_crs, utm_crs, always_xy=True)
                dom_shape_metric = shapely_transform(transformer.transform, dom_shape)
            else:
                dom_shape_metric = dom_shape

            area_m2 = float(dom_shape_metric.area)
            domain_area_km2 = round(area_m2 / 1_000_000.0, 4)

            if mesh_res_m and mesh_res_m > 0:
                max_triangle_area_m2 = round(0.5 * (mesh_res_m ** 2), 2)
                estimated_triangles = int(area_m2 / max_triangle_area_m2) if max_triangle_area_m2 > 0 else None
        except Exception:
            pass

    water_head_m = None
    if res_lvl is not None and invert_elev is not None and res_lvl > invert_elev:
        water_head_m = round(res_lvl - invert_elev, 2)

    freeboard_m = None
    if crest_elev is not None and res_lvl is not None and crest_elev > res_lvl:
        freeboard_m = round(crest_elev - res_lvl, 2)

    output_steps = None
    if sim_dur_s and out_int_s and out_int_s > 0:
        output_steps = int(sim_dur_s / out_int_s)

    derived_checks = {
        "model_domain_area_km2": domain_area_km2,
        "estimated_mesh_triangles": estimated_triangles,
        "water_head_above_invert_m": water_head_m,
        "freeboard_m": freeboard_m,
        "output_steps_count": output_steps,
        "breach_distance_to_axis_m": breach_dist_m,
        "notes": "estimated_mesh_triangles is a pre-triangulation geometric estimate based on domain area and target resolution.",
    }

    proposed_configuration = {
        "target_mesh_resolution_m": mesh_res_m,
        "max_triangle_area_m2": max_triangle_area_m2,
        "simulation_duration_s": sim_dur_s,
        "output_interval_s": out_int_s,
        "output_steps_count": output_steps,
        "manning_roughness": manning_n or 0.035,
        "solver_type": "anuga_shallow_water_2d",
        "breach_formulation": "instantaneous_hypothetical",
        "datum_declared": f"{v_unit} ({v_datum})" if (v_unit and v_datum) else "unknown",
    }

    preflight_passed = (len(blockers) == 0)

    return DamProjectAnugaPreflightResponse(
        project_id=valid_id,
        project_name=p_data.get("project_name", "Untitled Dam Project"),
        preflight_passed=preflight_passed,
        blockers=blockers,
        warnings=warnings,
        derived_checks=derived_checks,
        proposed_configuration=proposed_configuration,
        scientific_status="hypothetical_unverified",
    )


def generate_anuga_run_script() -> str:
    """Generate reproducible, standalone ANUGA 2D shallow water hydrodynamic dam-break simulation script.

    PURE STATIC SCRIPT: Reads all configuration dynamically from config.json.
    Zero string interpolation of user text (eliminates code injection risk).
    Burns hypothetical dam crest and exact breach gap into working terrain without modifying original dem.tif.
    """
    return '''"""
ANUGA Hydrodynamic Dam-Break Simulation Script
Generated by Dam Safety Intelligence Hub (SIH PS 26161)
Scientific Status: Hypothetical Unverified Simulation Scenario
WARNING: This script defines a hypothetical scenario. It has not been field calibrated or certified.
"""

import os
import sys
import json
import logging
from pathlib import Path
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("anuga_simulation")

try:
    import anuga
except ImportError:
    logger.error("ANUGA is not installed in the active environment.")
    logger.error("Please install ANUGA (e.g. via conda-forge: `conda install -c conda-forge anuga`) to execute.")
    sys.exit(1)

try:
    import rasterio
    import matplotlib.path as mpath
    from scipy.interpolate import RegularGridInterpolator
except ImportError as e:
    logger.error(f"Missing required spatial dependency: {e}")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.json"


def extract_coords_from_geojson(geojson_obj):
    """Extract coordinates array from GeoJSON dict."""
    if isinstance(geojson_obj, dict):
        if geojson_obj.get("type") == "FeatureCollection":
            feats = geojson_obj.get("features", [])
            if feats:
                return extract_coords_from_geojson(feats[0])
        elif geojson_obj.get("type") == "Feature":
            return extract_coords_from_geojson(geojson_obj.get("geometry", {}))
        elif "coordinates" in geojson_obj:
            return geojson_obj["coordinates"]
    return []


def point_to_polyline_distance(pts_x, pts_y, polyline_pts):
    """Compute minimum distance from 2D points to a polyline."""
    pts_xy = np.column_stack([pts_x, pts_y])
    p_arr = np.array(polyline_pts, dtype=np.float64)
    if len(p_arr) < 2:
        if len(p_arr) == 1:
            return np.linalg.norm(pts_xy - p_arr[0], axis=1)
        return np.full(len(pts_x), 1e9)

    min_dists = np.full(len(pts_x), 1e9)
    for i in range(len(p_arr) - 1):
        p1 = p_arr[i]
        p2 = p_arr[i + 1]
        seg = p2 - p1
        l2 = np.sum(seg ** 2)
        if l2 < 1e-9:
            d = np.linalg.norm(pts_xy - p1, axis=1)
        else:
            t = np.clip(np.sum((pts_xy - p1) * seg, axis=1) / l2, 0.0, 1.0)
            proj = p1 + t[:, None] * seg
            d = np.linalg.norm(pts_xy - proj, axis=1)
        min_dists = np.minimum(min_dists, d)
    return min_dists


def run():
    logger.info("Initializing ANUGA Dam-Break Hydrodynamic Simulation...")

    if not CONFIG_FILE.is_file():
        logger.error(f"Configuration file '{CONFIG_FILE}' not found.")
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # 1. Inspect and load input files
    dem_path = SCRIPT_DIR / cfg.get("dem_file", "dem.tif")
    domain_path = SCRIPT_DIR / cfg.get("model_domain_file", "model_domain.geojson")
    reservoir_path = SCRIPT_DIR / cfg.get("reservoir_boundary_file", "reservoir_boundary.geojson")
    outlet_path = SCRIPT_DIR / cfg.get("downstream_outlet_file", "downstream_outlet.geojson")
    dam_axis_path = SCRIPT_DIR / cfg.get("dam_axis_file", "dam_axis.geojson")

    for p in [dem_path, domain_path, reservoir_path, outlet_path, dam_axis_path]:
        if not p.is_file():
            logger.error(f"Required input file '{p}' is missing.")
            sys.exit(1)

    # 2. Simulation parameters
    sim_params = cfg.get("simulation_parameters", {})
    target_res_m = float(sim_params.get("target_mesh_resolution_m", 50.0))
    duration_s = float(sim_params.get("simulation_duration_s", 3600.0))
    interval_s = float(sim_params.get("output_interval_s", 60.0))
    manning_n = float(sim_params.get("manning_roughness", 0.035))

    reservoir_level = float(cfg.get("reservoir_level", 0.0))
    breach_width = float(cfg.get("breach_width", 50.0))
    breach_invert = float(cfg.get("breach_invert_elevation", 0.0))
    dam_crest = float(cfg.get("dam_crest_elevation", 0.0))
    breach_center = cfg.get("breach_center")

    logger.info(f"Target Mesh Resolution: {target_res_m} m (Max Triangle Area: {0.5 * (target_res_m ** 2)} m2)")
    logger.info(f"Simulation Duration: {duration_s} s, Output Interval: {interval_s} s")
    logger.info(f"Reservoir Level: {reservoir_level} m, Breach Invert: {breach_invert} m, Crest: {dam_crest} m")

    # 3. Load Domain Geometry
    with open(domain_path, "r", encoding="utf-8") as f:
        dom_data = json.load(f)
    dom_raw_coords = extract_coords_from_geojson(dom_data)
    if isinstance(dom_raw_coords[0][0], list):
        poly_coords = dom_raw_coords[0]
    else:
        poly_coords = dom_raw_coords

    # Remove duplicated closing vertex for ANUGA mesh creation
    if len(poly_coords) > 2 and poly_coords[0] == poly_coords[-1]:
        poly_coords = poly_coords[:-1]

    # 4. Load Downstream Outlet Geometry & Classify Boundary Segments
    with open(outlet_path, "r", encoding="utf-8") as f:
        out_data = json.load(f)
    out_coords = extract_coords_from_geojson(out_data)
    if out_coords and isinstance(out_coords[0], list) and isinstance(out_coords[0][0], list):
        out_pts = out_coords[0]
    else:
        out_pts = out_coords

    n_segs = len(poly_coords)
    boundary_tags = {"wall": [], "outlet": []}

    for seg_idx in range(n_segs):
        p1 = np.array(poly_coords[seg_idx], dtype=np.float64)
        p2 = np.array(poly_coords[(seg_idx + 1) % n_segs], dtype=np.float64)
        mid_pt = 0.5 * (p1 + p2)
        d_out = point_to_polyline_distance(np.array([mid_pt[0]]), np.array([mid_pt[1]]), out_pts)[0]
        if d_out < max(target_res_m, 50.0):
            boundary_tags["outlet"].append(seg_idx)
        else:
            boundary_tags["wall"].append(seg_idx)

    # Clean empty tag keys
    tag_dict = {k: v for k, v in boundary_tags.items() if len(v) > 0}
    if not tag_dict:
        tag_dict = {"exterior": list(range(n_segs))}

    # 5. Create ANUGA Domain
    max_triangle_area = max(0.5 * (target_res_m ** 2), 100.0)
    output_dir = SCRIPT_DIR / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    scenario_name = f"dam_break_{cfg.get('project_id', 'sim')}"

    logger.info("Generating 2D unstructured triangular mesh...")
    domain = anuga.create_domain_from_regions(
        bounding_polygon=poly_coords,
        boundary_tags=tag_dict,
        maximum_triangle_area=max_triangle_area,
        use_cache=False,
        verbose=False
    )

    domain.set_name(scenario_name)
    domain.set_datadir(str(output_dir))

    # 6. Read DEM Raster & Build Interpolator
    logger.info("Reading DEM raster and initializing spatial interpolator...")
    with rasterio.open(dem_path) as src:
        dem_data = src.read(1).astype(np.float64)
        transform = src.transform
        cols = np.arange(src.width)
        rows = np.arange(src.height)
        xs = transform.c + cols * transform.a
        ys = transform.f + rows * transform.e
        if transform.e < 0:
            ys = ys[::-1]
            dem_data = np.flipud(dem_data)
        dem_interp = RegularGridInterpolator((ys, xs), dem_data, bounds_error=False, fill_value=np.nanmin(dem_data))

    # 7. Build Explicit Dam Crest Ridge & Breach Gap on Working Terrain
    # Original dem.tif is preserved unchanged.
    logger.info("Burning explicit dam crest and instantaneous breach gap into working terrain...")
    with open(dam_axis_path, "r", encoding="utf-8") as f:
        axis_data = json.load(f)
    axis_coords = extract_coords_from_geojson(axis_data)
    if axis_coords and isinstance(axis_coords[0], list) and isinstance(axis_coords[0][0], list):
        axis_pts = axis_coords[0]
    else:
        axis_pts = axis_coords

    dam_buffer_width = max(target_res_m, 15.0)
    bx = float(breach_center[0]) if breach_center else 0.0
    by = float(breach_center[1]) if breach_center else 0.0

    # Get coordinate origin offset from ANUGA domain geo_reference
    try:
        x_orig = float(domain.geo_reference.get_xllcorner())
        y_orig = float(domain.geo_reference.get_yllcorner())
    except Exception:
        x_orig = 0.0
        y_orig = 0.0

    def elevation_func(x, y):
        x_flat = np.asarray(x).ravel() + x_orig
        y_flat = np.asarray(y).ravel() + y_orig
        pts_yx = np.column_stack([y_flat, x_flat])
        dem_z = dem_interp(pts_yx)

        dist_to_axis = point_to_polyline_distance(x_flat, y_flat, axis_pts)
        dist_to_breach = np.hypot(x_flat - bx, y_flat - by)

        is_dam = dist_to_axis <= (dam_buffer_width / 2.0)
        is_breach = is_dam & (dist_to_breach <= (breach_width / 2.0))

        elev_flat = np.where(
            is_breach,
            np.minimum(dem_z, breach_invert),
            np.where(is_dam, np.maximum(dem_z, dam_crest), dem_z)
        )
        return elev_flat.reshape(np.shape(x))

    domain.set_quantity('elevation', function=elevation_func)

    # 8. Set Friction (Manning's n)
    domain.set_quantity('friction', manning_n)

    # 9. Set Initial Water Stage (Reservoir Boundary)
    with open(reservoir_path, "r", encoding="utf-8") as f:
        res_data = json.load(f)
    res_raw = extract_coords_from_geojson(res_data)
    if isinstance(res_raw[0][0], list):
        res_coords = res_raw[0]
    else:
        res_coords = res_raw
    res_path = mpath.Path(res_coords)

    logger.info("Setting initial reservoir stage inside reservoir boundary polygon...")
    def stage_func(x, y):
        elev = elevation_func(x, y)
        x_flat = np.asarray(x).ravel() + x_orig
        y_flat = np.asarray(y).ravel() + y_orig
        pts_xy = np.column_stack([x_flat, y_flat])
        in_res = res_path.contains_points(pts_xy).reshape(np.shape(x))
        return np.where(in_res, np.maximum(elev, reservoir_level), elev)

    domain.set_quantity('stage', function=stage_func)

    # 10. Boundary Conditions (Transmissive Outlet / Reflective walls)
    logger.info("Configuring boundary conditions...")
    b_trans = anuga.Transmissive_boundary(domain)
    b_refl = anuga.Reflective_boundary(domain)

    bc_map = {}
    for tag in tag_dict.keys():
        if tag == "outlet":
            bc_map[tag] = b_trans
        elif tag == "wall":
            bc_map[tag] = b_refl
        else:
            bc_map[tag] = b_trans

    domain.set_boundary(bc_map)

    # 11. Execute Evolution Loop
    logger.info(f"Starting ANUGA evolution (0 -> {duration_s}s with step {interval_s}s)...")
    for t in domain.evolve(yieldstep=interval_s, finaltime=duration_s):
        logger.info(domain.timestepping_statistics())

    sww_file = output_dir / f"{scenario_name}.sww"
    logger.info("Hydrodynamic simulation execution completed successfully.")
    logger.info(f"Output SWW file written to: {sww_file}")


if __name__ == "__main__":
    run()
'''



def build_dam_project_anuga_package(project_id: str) -> DamProjectAnugaPackageResponse:
    """Build immutable reproducible ANUGA simulation package ZIP for an onboarded dam project.

    Only builds when preflight assessment passes (preflight_passed=True).
    Never fabricates fake simulation results or SWW files.
    """
    preflight = assess_anuga_preflight(project_id)
    if not preflight.preflight_passed:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Cannot generate ANUGA simulation package: project failed preflight assessment.",
                "blockers": preflight.blockers,
            },
        )

    valid_id = validate_project_uuid(project_id)
    proj_dir = get_dam_projects_dir() / valid_id
    proj_json = proj_dir / "project.json"

    p_data = json.loads(proj_json.read_text(encoding="utf-8"))
    project_name = p_data.get("project_name", "dam_project")
    user_meta = p_data.get("user_provided_metadata", {})
    sim_params = p_data.get("simulation_parameters", {})

    # Package output directory
    packages_dir = proj_dir / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    zip_path = packages_dir / "anuga_package.zip"

    # Deterministic caching: If package already built and exists, return existing package
    if zip_path.is_file():
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                if "manifest.json" in zf.namelist():
                    cached_manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                    return DamProjectAnugaPackageResponse(
                        project_id=valid_id,
                        project_name=project_name,
                        package_filename="anuga_package.zip",
                        package_size_bytes=zip_path.stat().st_size,
                        package_sha256=compute_file_sha256(zip_path) or "",
                        created_at=cached_manifest.get("created_at", datetime.now(timezone.utc).isoformat()),
                        files_included=zf.namelist(),
                        scientific_status="hypothetical_unverified",
                        simulation_executed=False,
                        message="ANUGA simulation package ready (existing package returned).",
                    )
        except Exception:
            pass

    # Create config.json content
    config_dict = {
        "project_id": valid_id,
        "project_name": project_name,
        "scientific_status": "hypothetical_unverified",
        "dem_file": "dem.tif",
        "dam_axis_file": "dam_axis.geojson",
        "reservoir_boundary_file": "reservoir_boundary.geojson",
        "model_domain_file": "model_domain.geojson",
        "downstream_outlet_file": "downstream_outlet.geojson",
        "reservoir_level": user_meta.get("reservoir_level"),
        "dam_crest_elevation": user_meta.get("dam_crest_elevation"),
        "breach_invert_elevation": user_meta.get("breach_invert_elevation"),
        "breach_width": user_meta.get("breach_width"),
        "breach_center": user_meta.get("breach_center"),
        "breach_formation_time_hr": user_meta.get("breach_formation_time_hr"),
        "vertical_unit": user_meta.get("vertical_unit"),
        "vertical_datum": user_meta.get("vertical_datum"),
        "geometry_crs": user_meta.get("geometry_crs", "EPSG:4326"),
        "simulation_parameters": {
            "target_mesh_resolution_m": sim_params.get("target_mesh_resolution_m") or user_meta.get("target_mesh_resolution_m", 50.0),
            "simulation_duration_s": sim_params.get("simulation_duration_s") or user_meta.get("simulation_duration_s", 3600.0),
            "output_interval_s": sim_params.get("output_interval_s") or user_meta.get("output_interval_s", 60.0),
            "manning_roughness": user_meta.get("manning_roughness", 0.035),
            "solver": "anuga_shallow_water_2d",
            "breach_formulation": "instantaneous_hypothetical",
        },
        "disclaimer": "This package defines a hypothetical simulation scenario. Simulation has NOT been executed.",
    }

    config_bytes = json.dumps(config_dict, indent=2).encode("utf-8")

    # Generate Python run script (static template reading dynamically from config.json)
    run_script_str = generate_anuga_run_script()
    run_script_bytes = run_script_str.encode("utf-8")

    # Generate README_LIMITATIONS.txt
    readme_text = f"""================================================================================
ANUGA DAM-BREAK HYDRODYNAMIC SIMULATION PACKAGE
Project: {project_name} ({valid_id})
Generated: {datetime.now(timezone.utc).isoformat()}
================================================================================

SCIENTIFIC STATUS: HYPOTHETICAL UNVERIFIED

IMPORTANT NOTICES & SCIENTIFIC LIMITATIONS:
1. NO SIMULATION HAS BEEN EXECUTED on the server. No SWW or result files have
   been fabricated or included in this package.
2. The model parameters (elevations, breach geometry, Manning roughness) are
   user-declared and have not been field-verified against official dam-safety records.
3. BREACH FORMULATION: The generated script utilizes an instantaneous hypothetical
   breach formulation. Progressive breach formation time is reported as unsupported
   in this baseline ANUGA script release.
4. COORDINATE & VERTICAL REFERENCE:
   - Geometry CRS: {user_meta.get('geometry_crs', 'EPSG:4326')}
   - Declared Unit / Datum: {user_meta.get('vertical_unit', 'unknown')} ({user_meta.get('vertical_datum', 'unknown')})
5. This package is intended strictly for research and numerical method validation.
   It MUST NOT be used for real-time flood warning, emergency operations, or official
   evacuation planning without independent hydrological verification.

EXECUTION INSTRUCTIONS:
1. Ensure ANUGA is installed in your Python environment:
   conda env create -f environment_anuga.yml
   conda activate sih-anuga
   pip install -r requirements.txt
2. Run the simulation:
   python run_anuga.py
3. Hydrodynamic SWW outputs will be written to the `output/` directory.
================================================================================
"""
    readme_bytes = readme_text.encode("utf-8")

    # Generate requirements.txt with pinned dependencies
    requirements_text = """# Pinned Python dependencies for reproducible ANUGA Dam-Break Simulation
anuga>=3.1.0,<=4.0.0
numpy>=1.20.0,<2.0.0
scipy>=1.7.0
rasterio>=1.2.0
shapely>=2.0.0
pyproj>=3.0.0
"""
    requirements_bytes = requirements_text.encode("utf-8")

    # Collect all package files and compute package manifest
    package_files_content: Dict[str, bytes] = {
        "config.json": config_bytes,
        "run_anuga.py": run_script_bytes,
        "requirements.txt": requirements_bytes,
        "README_LIMITATIONS.txt": readme_bytes,
    }

    # Include environment_anuga.yml from root repo if available
    repo_env_yml = Path(__file__).resolve().parent.parent.parent / "environment_anuga.yml"
    if repo_env_yml.is_file():
        package_files_content["environment_anuga.yml"] = repo_env_yml.read_bytes()

    # Add source input files from project directory
    source_filenames = [
        "dem.tif",
        "dam_axis.geojson",
        "reservoir_boundary.geojson",
        "model_domain.geojson",
        "downstream_outlet.geojson",
    ]
    for fn in source_filenames:
        src_path = proj_dir / fn
        if src_path.is_file():
            package_files_content[fn] = src_path.read_bytes()

    # Compute manifest with SHA-256 for each bundled file
    internal_manifest: Dict[str, Any] = {
        "project_id": valid_id,
        "project_name": project_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scientific_status": "hypothetical_unverified",
        "simulation_executed": False,
        "files": {},
    }

    for fn, content in package_files_content.items():
        h = hashlib.sha256(content).hexdigest()
        internal_manifest["files"][fn] = {
            "size_bytes": len(content),
            "sha256": h,
        }

    manifest_bytes = json.dumps(internal_manifest, indent=2).encode("utf-8")
    package_files_content["manifest.json"] = manifest_bytes

    # Write atomic ZIP archive
    temp_zip = packages_dir / f"anuga_package_{uuid.uuid4().hex[:8]}.tmp"
    try:
        with zipfile.ZipFile(temp_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fn, content in package_files_content.items():
                zf.writestr(fn, content)

        if zip_path.is_file():
            zip_path.unlink()
        temp_zip.rename(zip_path)
    except Exception as e:
        if temp_zip.is_file():
            temp_zip.unlink()
        raise HTTPException(status_code=500, detail=f"Failed to generate ANUGA package ZIP: {str(e)}")

    package_sha256 = compute_file_sha256(zip_path) or ""

    return DamProjectAnugaPackageResponse(
        project_id=valid_id,
        project_name=project_name,
        package_filename="anuga_package.zip",
        package_size_bytes=zip_path.stat().st_size,
        package_sha256=package_sha256,
        created_at=datetime.now(timezone.utc).isoformat(),
        files_included=list(package_files_content.keys()),
        scientific_status="hypothetical_unverified",
        simulation_executed=False,
        message="ANUGA simulation package generated successfully. Simulation has not been executed.",
    )


def get_dam_project_anuga_package_path(project_id: str) -> Path:
    """Retrieve absolute file path of built ANUGA package ZIP after integrity verification."""
    verify_project_integrity(project_id)
    valid_id = validate_project_uuid(project_id)
    zip_path = get_dam_projects_dir() / valid_id / "packages" / "anuga_package.zip"

    if not zip_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"ANUGA package has not been built for project '{valid_id}'. Please run preflight and generate package first.",
        )

    return zip_path


# ==============================================================================
# Gated ANUGA Execution Service (Stage 2)
# ==============================================================================

EXECUTION_THREAD_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="anuga_worker")


def validate_run_uuid(run_id: str) -> str:
    """Validate UUID format for run ID."""
    try:
        val = uuid.UUID(run_id, version=4)
        return str(val)
    except Exception:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid run ID '{run_id}'. Must be a valid UUID v4.",
        )


def get_anuga_python_executable() -> Optional[str]:
    """Resolve configured ANUGA python executable from server environment only."""
    env_exe = os.environ.get("ANUGA_PYTHON_EXECUTABLE")
    if env_exe and os.path.isfile(env_exe):
        return env_exe

    # Default conda environment locations
    candidates = [
        Path(os.environ.get("USERPROFILE", "")) / "miniforge3" / "envs" / "sih-anuga" / "python.exe",
        Path(os.environ.get("USERPROFILE", "")) / "anaconda3" / "envs" / "sih-anuga" / "python.exe",
        Path(os.environ.get("USERPROFILE", "")) / "miniconda3" / "envs" / "sih-anuga" / "python.exe",
        Path("/opt/conda/envs/sih-anuga/bin/python"),
        Path("/root/miniforge3/envs/sih-anuga/bin/python"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)

    return None


def detect_anuga_version(python_exe: Optional[str] = None) -> Tuple[bool, str]:
    """Detect ANUGA package installation and version using importlib.metadata.version('anuga').

    Returns (is_installed, version_str). Fallback to 'unknown' only if metadata cannot be read.
    """
    if not python_exe:
        python_exe = get_anuga_python_executable()
    if not python_exe or not os.path.isfile(python_exe):
        return False, "unavailable"

    exe_path = Path(python_exe)
    site_candidates = [
        exe_path.parent / "Lib" / "site-packages" / "anuga",
        exe_path.parent.parent / "lib" / "python3.10" / "site-packages" / "anuga",
        exe_path.parent.parent / "lib" / "python3.11" / "site-packages" / "anuga",
        exe_path.parent.parent / "lib" / "python3.12" / "site-packages" / "anuga",
    ]
    has_dir = any(c.is_dir() for c in site_candidates)

    cmd = (
        "try:\n"
        "    import importlib.metadata\n"
        "    v = importlib.metadata.version('anuga')\n"
        "    print(v.strip() if v else 'unknown')\n"
        "except Exception:\n"
        "    try:\n"
        "        import anuga\n"
        "        print(getattr(anuga, '__version__', 'unknown'))\n"
        "    except Exception:\n"
        "        print('unknown')\n"
    )

    try:
        proc = subprocess.run(
            [python_exe, "-c", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            shell=False,
        )
        if proc.returncode == 0:
            out_lines = [l.strip() for l in proc.stdout.splitlines() if l.strip() and not l.startswith("WARNING")]
            ver = out_lines[-1] if out_lines else "unknown"
            return True, ver
        elif has_dir:
            return True, "unknown"
        else:
            return False, "unavailable"
    except Exception:
        if has_dir:
            return True, "unknown"
        return False, "unavailable"


_ANUGA_VERSION_CACHE: Dict[str, Tuple[bool, str]] = {}


def get_custom_anuga_capabilities() -> DamProjectAnugaCapabilitiesResponse:
    """Retrieve capability status for custom ANUGA hydrodynamic simulation runs."""
    enabled_str = os.environ.get("ENABLE_CUSTOM_ANUGA_EXECUTION", "false").strip().lower()
    is_enabled = enabled_str in ("true", "1", "yes")

    python_exe = get_anuga_python_executable()
    anuga_installed = False
    anuga_version = "unavailable"

    if python_exe:
        if python_exe in _ANUGA_VERSION_CACHE:
            anuga_installed, anuga_version = _ANUGA_VERSION_CACHE[python_exe]
        else:
            anuga_installed, anuga_version = detect_anuga_version(python_exe)
            if anuga_installed:
                _ANUGA_VERSION_CACHE[python_exe] = (anuga_installed, anuga_version)

    reason = None
    if not is_enabled:
        reason = "Custom ANUGA execution is disabled by default via ENABLE_CUSTOM_ANUGA_EXECUTION=false."
    elif not python_exe:
        reason = "ANUGA Python executable (sih-anuga) is not configured or found on the server."
    elif not anuga_installed:
        reason = "ANUGA module could not be loaded in the configured Python environment."

    return DamProjectAnugaCapabilitiesResponse(
        execution_enabled=is_enabled and anuga_installed,
        anuga_installed=anuga_installed,
        anuga_version=anuga_version,
        python_executable_configured=bool(python_exe),
        reason=reason,
    )


def sanitize_log_output(text: str) -> str:
    """Strip server filesystem paths and sensitive environment details from log output."""
    if not text:
        return ""
    sanitized = text
    user_home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if user_home:
        sanitized = sanitized.replace(user_home, "~")
    sanitized = re.sub(r"[A-Za-z]:\\[^ \n\r\t\"']+", lambda m: Path(m.group(0)).name, sanitized)
    sanitized = re.sub(r"/(?:home|var|tmp|opt|usr)/[^ \n\r\t\"']+", lambda m: Path(m.group(0)).name, sanitized)
    return sanitized


def safe_extract_zip(zip_path: Path, target_dir: Path) -> List[str]:
    """Safely extract all members from a ZIP archive into target_dir.

    Rejects any member with:
    - Absolute paths
    - Windows drive paths (e.g. C:...)
    - Parent directory traversal ('..')
    - Resolved destination outside target_dir
    """
    resolved_target = target_dir.resolve()
    extracted_files: List[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            raw_name = member.filename
            if not raw_name:
                continue

            # Reject absolute or Windows drive paths
            if os.path.isabs(raw_name) or bool(re.match(r"^[a-zA-Z]:", raw_name)):
                raise ValueError(f"Insecure absolute or drive path in zip member: '{raw_name}'")

            # Check path parts for traversal tokens
            norm_parts = Path(raw_name).parts
            if any(p in ("..", "/", "\\") for p in norm_parts):
                raise ValueError(f"Directory traversal detected in zip member: '{raw_name}'")

            dest_path = (resolved_target / raw_name).resolve()
            try:
                dest_path.relative_to(resolved_target)
            except ValueError:
                raise ValueError(f"Zip member '{raw_name}' resolves outside target directory '{resolved_target}'")

            if member.is_dir():
                dest_path.mkdir(parents=True, exist_ok=True)
            else:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member, "r") as src_file, open(dest_path, "wb") as dst_file:
                    shutil.copyfileobj(src_file, dst_file)
                extracted_files.append(raw_name)

    return extracted_files


_ACTIVE_RUN_IDS: Set[str] = set()
_ACTIVE_RUNS_LOCK = threading.Lock()


def register_active_run(run_id: str) -> None:
    """Register an actively executing local worker run."""
    with _ACTIVE_RUNS_LOCK:
        _ACTIVE_RUN_IDS.add(run_id)


def unregister_active_run(run_id: str) -> None:
    """Unregister a finished worker run."""
    with _ACTIVE_RUNS_LOCK:
        _ACTIVE_RUN_IDS.discard(run_id)


def is_run_active(run_id: str) -> bool:
    """Check if a run worker is actively running in this process."""
    with _ACTIVE_RUNS_LOCK:
        return run_id in _ACTIVE_RUN_IDS


def recover_interrupted_anuga_runs() -> int:
    """Detect persisted queued/running jobs that have no active local worker.

    Marks them status='interrupted' with a sanitized reason and finished timestamp.
    Never marks them completed.
    """
    projects_dir = get_dam_projects_dir()
    recovered_count = 0
    if not projects_dir.is_dir():
        return 0

    for proj_entry in projects_dir.iterdir():
        if not proj_entry.is_dir() or proj_entry.name.startswith("."):
            continue
        runs_dir = proj_entry / "runs"
        if not runs_dir.is_dir():
            continue
        for run_entry in runs_dir.iterdir():
            if not run_entry.is_dir() or run_entry.name.startswith("."):
                continue
            run_json = run_entry / "run.json"
            if not run_json.is_file():
                continue
            try:
                data = json.loads(run_json.read_text(encoding="utf-8"))
                status = data.get("status")
                r_id = data.get("run_id", run_entry.name)
                if status in ("queued", "running") and not is_run_active(r_id):
                    now_iso = datetime.now(timezone.utc).isoformat()
                    data["status"] = "interrupted"
                    data["completed_at"] = now_iso
                    data["simulation_executed"] = False
                    data["message"] = "Simulation was interrupted due to server restart or process termination."
                    run_json.write_text(json.dumps(data, indent=2), encoding="utf-8")

                    log_file = run_entry / "execution.log"
                    if log_file.is_file():
                        try:
                            current_log = log_file.read_text(encoding="utf-8", errors="replace")
                            updated_log = current_log + f"\n\n[WARNING] Simulation execution interrupted by server restart or worker shutdown at {now_iso}.\n"
                            log_file.write_text(updated_log, encoding="utf-8")
                        except Exception:
                            pass
                    recovered_count += 1
            except Exception:
                pass

    return recovered_count


def validate_sww_file(sww_path: Path) -> Tuple[bool, Optional[str]]:
    """Validate produced SWW file as genuine NetCDF with hydrodynamic variables."""
    if not sww_path.is_file():
        return False, "SWW file does not exist"
    if sww_path.stat().st_size < 1024:
        return False, f"SWW file size ({sww_path.stat().st_size} bytes) is suspiciously small"

    try:
        ds = netcdf_file(str(sww_path), "r", mmap=False)
        for req in ["time", "stage", "elevation", "xmomentum", "ymomentum"]:
            if req not in ds.variables:
                return False, f"Missing required hydrodynamic variable '{req}' in SWW NetCDF"

        times = ds.variables["time"][:]
        if len(times) < 2:
            return False, f"Insufficient timesteps ({len(times)}) in SWW file"

        stages = ds.variables["stage"][:]
        if not np.all(np.isfinite(stages)):
            return False, "Stage array contains non-finite or NaN values"

        return True, None
    except Exception as e:
        return False, f"Failed to parse SWW NetCDF: {str(e)}"


def _execute_anuga_run_worker(
    run_id: str,
    project_id: str,
    run_dir: Path,
    pkg_zip_path: Path,
    package_sha256: str,
    timeout_sec: int = 300,
):
    """Background worker executing the extracted ANUGA package in isolation."""
    register_active_run(run_id)
    run_json = run_dir / "run.json"
    log_file = run_dir / "execution.log"
    workspace_dir = run_dir / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    try:
        data = json.loads(run_json.read_text(encoding="utf-8")) if run_json.is_file() else {}
        data["status"] = "running"
        data["started_at"] = datetime.now(timezone.utc).isoformat()
        run_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        log_file.write_text(f"[ERROR] Failed to update run.json at start: {exc}", encoding="utf-8")
        unregister_active_run(run_id)
        return

    try:
        # Extract package ZIP safely rejecting traversal and absolute paths
        try:
            safe_extract_zip(pkg_zip_path, workspace_dir)
        except Exception as e:
            data["status"] = "failed"
            data["completed_at"] = datetime.now(timezone.utc).isoformat()
            data["message"] = f"Failed to safely extract simulation package: {str(e)}"
            run_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
            log_file.write_text(f"[ERROR] Failed to safely extract simulation package: {str(e)}", encoding="utf-8")
            return

        python_exe = get_anuga_python_executable()
        if not python_exe:
            data["status"] = "failed"
            data["completed_at"] = datetime.now(timezone.utc).isoformat()
            data["message"] = "Configured ANUGA Python executable is missing on the server."
            run_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
            log_file.write_text("[ERROR] Configured ANUGA Python executable is missing on the server.", encoding="utf-8")
            return

        script_path = workspace_dir / "run_anuga.py"
        if not script_path.is_file():
            data["status"] = "failed"
            data["completed_at"] = datetime.now(timezone.utc).isoformat()
            data["message"] = "run_anuga.py is missing in extracted package."
            run_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
            log_file.write_text("[ERROR] run_anuga.py is missing in extracted package.", encoding="utf-8")
            return

        # Run subprocess with clean environment and absolute script path
        start_t = time.time()
        log_lines: List[str] = [
            f"=== ANUGA Simulation Execution Started: {datetime.now(timezone.utc).isoformat()} ===",
            f"Project ID: {project_id} | Run ID: {run_id}",
            f"Package SHA-256: {package_sha256}",
            f"Scientific Status: hypothetical_unverified",
            "--------------------------------------------------------------------------------\n",
        ]
        log_file.write_text("\n".join(log_lines), encoding="utf-8")

        is_timed_out = False
        exit_code = -1

        clean_env = os.environ.copy()
        clean_env.pop("PYTHONPATH", None)
        clean_env.pop("PYTHONHOME", None)

        # Prepend target conda environment paths to avoid host DLL conflicts
        exe_p = Path(python_exe).parent
        conda_paths = [
            str(exe_p),
            str(exe_p / "Library" / "mingw-w64" / "bin"),
            str(exe_p / "Library" / "usr" / "bin"),
            str(exe_p / "Library" / "bin"),
            str(exe_p / "Scripts"),
            str(exe_p / "bin"),
        ]
        existing_path = clean_env.get("PATH", "")
        clean_env["PATH"] = os.pathsep.join(conda_paths) + os.pathsep + existing_path
        clean_env["CONDA_PREFIX"] = str(exe_p)

        try:
            proc = subprocess.Popen(
                [python_exe, str(script_path)],
                cwd=str(workspace_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=clean_env,
                shell=False,
            )

            try:
                stdout_text, stderr_text = proc.communicate(timeout=timeout_sec)
                exit_code = proc.returncode
                if stdout_text:
                    log_lines.append(stdout_text)
                if stderr_text:
                    log_lines.append(stderr_text)
            except subprocess.TimeoutExpired:
                is_timed_out = True
                proc.kill()
                stdout_text, stderr_text = proc.communicate()
                if stdout_text:
                    log_lines.append(stdout_text)
                if stderr_text:
                    log_lines.append(stderr_text)
                log_lines.append(f"\n[ERROR] Simulation exceeded maximum timeout limit ({timeout_sec} s). Process killed.")

        except Exception as e:
            log_lines.append(f"\n[ERROR] Process execution failed to spawn: {str(e)}")
            exit_code = -1

        runtime_s = round(time.time() - start_t, 3)
        log_lines.append(f"\n--------------------------------------------------------------------------------")
        log_lines.append(f"Execution finished in {runtime_s:.2f} s with Exit Code: {exit_code}")

        # Write log file (limited to 10MB)
        combined_logs = "\n".join(log_lines)
        if len(combined_logs) > 10 * 1024 * 1024:
            combined_logs = combined_logs[: 10 * 1024 * 1024] + "\n[LOG TRUNCATED AT 10MB LIMIT]"
        log_file.write_text(combined_logs, encoding="utf-8")

        # Inspect outputs
        output_hashes: Dict[str, str] = {}
        output_dir = workspace_dir / "output"
        sww_valid = False
        sww_err: Optional[str] = None

        if output_dir.is_dir():
            for out_entry in output_dir.iterdir():
                if out_entry.is_file():
                    h = compute_file_sha256(out_entry) or ""
                    output_hashes[f"output/{out_entry.name}"] = h
                    if out_entry.name.endswith(".sww"):
                        sww_valid, sww_err = validate_sww_file(out_entry)

        # Finalize status
        if is_timed_out:
            final_status = "timed_out"
            sim_executed = False
            final_msg = f"Simulation timed out after {timeout_sec} s."
        elif exit_code == 0 and sww_valid:
            final_status = "completed"
            sim_executed = True
            final_msg = "Hydrodynamic simulation executed successfully and generated valid SWW results."
        else:
            final_status = "failed"
            sim_executed = False
            if exit_code != 0:
                final_msg = f"ANUGA execution exited with code {exit_code}."
            else:
                final_msg = f"Simulation completed with exit code 0 but SWW validation failed: {sww_err or 'missing SWW output'}."

        data["status"] = final_status
        data["completed_at"] = datetime.now(timezone.utc).isoformat()
        data["exit_code"] = exit_code
        data["runtime_seconds"] = runtime_s
        data["output_files"] = output_hashes
        data["simulation_executed"] = sim_executed
        data["message"] = final_msg

        run_json.write_text(json.dumps(data, indent=2), encoding="utf-8")

    except Exception as fatal_e:
        try:
            data["status"] = "failed"
            data["completed_at"] = datetime.now(timezone.utc).isoformat()
            data["message"] = f"Fatal worker exception: {fatal_e}"
            run_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
            log_file.write_text(f"[FATAL WORKER ERROR] {fatal_e}", encoding="utf-8")
        except Exception:
            pass
    finally:
        unregister_active_run(run_id)


def create_dam_project_anuga_run(
    project_id: str,
    request: DamProjectAnugaRunRequest,
) -> DamProjectAnugaRunResponse:
    """Queue a gated, isolated ANUGA simulation execution run for an onboarded dam project."""
    caps = get_custom_anuga_capabilities()
    if not caps.execution_enabled:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "custom_anuga_execution_disabled",
                "message": caps.reason or "Custom ANUGA execution is disabled.",
            },
        )

    if not request.acknowledge_hypothetical_unverified:
        raise HTTPException(
            status_code=422,
            detail="User acknowledgment of hypothetical unverified simulation terms is required to execute.",
        )

    verify_project_integrity(project_id)
    valid_id = validate_project_uuid(project_id)
    proj_dir = get_dam_projects_dir() / valid_id
    pkg_path = proj_dir / "packages" / "anuga_package.zip"

    if not pkg_path.is_file():
        raise HTTPException(
            status_code=400,
            detail={
                "code": "package_not_built",
                "message": f"ANUGA package has not been built for project '{valid_id}'. Please run preflight and generate package first.",
            },
        )

    package_sha256 = compute_file_sha256(pkg_path) or ""
    proj_json = proj_dir / "project.json"
    p_data = json.loads(proj_json.read_text(encoding="utf-8")) if proj_json.is_file() else {}
    project_name = p_data.get("project_name", "Untitled Dam Project")

    run_id = str(uuid.uuid4())
    runs_dir = proj_dir / "runs"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now(timezone.utc).isoformat()
    run_dict: Dict[str, Any] = {
        "run_id": run_id,
        "project_id": valid_id,
        "project_name": project_name,
        "package_sha256": package_sha256,
        "status": "queued",
        "created_at": created_at,
        "started_at": None,
        "completed_at": None,
        "exit_code": None,
        "anuga_version": caps.anuga_version,
        "runtime_seconds": None,
        "log_file": "execution.log",
        "output_files": {},
        "scientific_status": "hypothetical_unverified",
        "simulation_executed": False,
        "message": "ANUGA hydrodynamic simulation queued for execution.",
    }

    run_json = run_dir / "run.json"
    run_json.write_text(json.dumps(run_dict, indent=2), encoding="utf-8")

    # Initialize execution log immediately
    log_file = run_dir / "execution.log"
    initial_log_header = (
        f"=== ANUGA Simulation Execution Queued: {created_at} ===\n"
        f"Project ID: {valid_id} | Run ID: {run_id}\n"
        f"Package SHA-256: {package_sha256}\n"
        f"Scientific Status: hypothetical_unverified\n"
        "--------------------------------------------------------------------------------\n"
    )
    log_file.write_text(initial_log_header, encoding="utf-8")

    # Dispatch to background thread pool
    EXECUTION_THREAD_POOL.submit(
        _execute_anuga_run_worker,
        run_id=run_id,
        project_id=valid_id,
        run_dir=run_dir,
        pkg_zip_path=pkg_path,
        package_sha256=package_sha256,
    )

    return DamProjectAnugaRunResponse(**run_dict)


def list_dam_project_anuga_runs(project_id: str) -> List[DamProjectAnugaRunResponse]:
    """List all simulation execution runs for a custom dam project."""
    recover_interrupted_anuga_runs()
    verify_project_integrity(project_id)
    valid_id = validate_project_uuid(project_id)
    runs_dir = get_dam_projects_dir() / valid_id / "runs"
    results: List[DamProjectAnugaRunResponse] = []

    if runs_dir.is_dir():
        for entry in runs_dir.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                run_json = entry / "run.json"
                if run_json.is_file():
                    try:
                        r_data = json.loads(run_json.read_text(encoding="utf-8"))
                        results.append(DamProjectAnugaRunResponse(**r_data))
                    except Exception:
                        pass

    results.sort(key=lambda r: r.created_at, reverse=True)
    return results


def get_dam_project_anuga_run(project_id: str, run_id: str) -> DamProjectAnugaRunResponse:
    """Retrieve detailed status of an ANUGA simulation execution run."""
    recover_interrupted_anuga_runs()
    verify_project_integrity(project_id)
    valid_pid = validate_project_uuid(project_id)
    valid_rid = validate_run_uuid(run_id)

    run_json = get_dam_projects_dir() / valid_pid / "runs" / valid_rid / "run.json"
    if not run_json.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"ANUGA run '{valid_rid}' not found for project '{valid_pid}'.",
        )

    try:
        r_data = json.loads(run_json.read_text(encoding="utf-8"))
        return DamProjectAnugaRunResponse(**r_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read run record: {str(e)}")


def get_dam_project_anuga_run_logs(project_id: str, run_id: str) -> str:
    """Retrieve sanitized execution logs for a specific ANUGA run."""
    verify_project_integrity(project_id)
    valid_pid = validate_project_uuid(project_id)
    valid_rid = validate_run_uuid(run_id)

    log_file = get_dam_projects_dir() / valid_pid / "runs" / valid_rid / "execution.log"
    if not log_file.is_file():
        return "Log file not yet generated or run is still initializing."

    try:
        raw_logs = log_file.read_text(encoding="utf-8", errors="replace")
        return sanitize_log_output(raw_logs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read log file: {str(e)}")

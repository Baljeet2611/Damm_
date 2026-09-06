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
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

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
    project_name: str = "New Dam Project",
    vertical_unit: Optional[str] = None,
    vertical_datum: Optional[str] = None,
    reservoir_level: Optional[float] = None,
    breach_width: Optional[float] = None,
    breach_center_x: Optional[float] = None,
    breach_center_y: Optional[float] = None,
    breach_formation_time_hr: Optional[float] = 1.0,
    manning_roughness: Optional[float] = 0.035,
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
    breach_on_axis = False
    breach_dist_m: Optional[float] = None
    distance_crs_used: Optional[str] = None

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        temp_dem_path = temp_path / "temp_dem.tif"
        temp_dem_path.write_bytes(dem_bytes)

        # 3. DEM GeoTIFF Inspection
        dem_crs_obj: Optional[CRS] = None
        dem_box: Optional[box] = None
        try:
            with rasterio.open(temp_dem_path) as src:
                # Pixel count check (HTTP 413)
                total_pixels = src.width * src.height
                if total_pixels > MAX_RASTER_PIXELS:
                    raise HTTPException(
                        status_code=413,
                        detail=f"DEM raster dimension ({src.width}x{src.height} = {total_pixels:,} pixels) exceeds maximum allowed {MAX_RASTER_PIXELS:,} pixels.",
                    )

                # Validate single band
                if src.count != 1:
                    errors.append(f"DEM raster must be single-band. Found {src.count} bands in '{dem_filename}'.")

                # Validate numeric dtype
                dtype_name = src.dtypes[0]
                if not np.issubdtype(np.dtype(dtype_name), np.number):
                    errors.append(f"DEM raster dtype '{dtype_name}' is not numeric.")

                # Validate CRS
                if src.crs is None or not str(src.crs).strip():
                    errors.append(f"DEM raster '{dem_filename}' has no defined Coordinate Reference System (CRS).")
                else:
                    dem_crs_obj = src.crs

                # Bounding box & resolution
                b = src.bounds
                res_x = abs(src.res[0])
                res_y = abs(src.res[1])

                if b.left >= b.right or b.bottom >= b.top:
                    errors.append(f"DEM raster '{dem_filename}' has invalid spatial bounds: {b}.")
                else:
                    dem_box = box(b.left, b.bottom, b.right, b.top)

                # Min / Max Elevation Calculation via Block Windows (Streaming / Memory Safe)
                min_elev = float("inf")
                max_elev = float("-inf")
                valid_cells = 0
                try:
                    for _, window in src.block_windows(1):
                        block_arr = src.read(1, window=window, masked=True)
                        if block_arr.count() > 0:
                            b_min = float(np.nanmin(block_arr))
                            b_max = float(np.nanmax(block_arr))
                            if b_min < min_elev:
                                min_elev = b_min
                            if b_max > max_elev:
                                max_elev = b_max
                            valid_cells += int(block_arr.count())

                    if valid_cells == 0:
                        errors.append(f"DEM raster '{dem_filename}' contains only NoData values.")
                        min_elev_val = None
                        max_elev_val = None
                    else:
                        min_elev_val = min_elev
                        max_elev_val = max_elev
                except Exception as e:
                    warnings.append(f"Could not calculate DEM min/max elevation: {e}")
                    min_elev_val = None
                    max_elev_val = None

                raster_derived_meta = RasterDerivedMetadata(
                    width=src.width,
                    height=src.height,
                    band_count=src.count,
                    dtype=dtype_name,
                    crs=str(src.crs) if src.crs else "UNKNOWN",
                    bounds=RasterBounds(left=b.left, bottom=b.bottom, right=b.right, top=b.top),
                    resolution=RasterResolution(x=res_x, y=res_y),
                    nodata=src.nodata,
                    min_elevation=min_elev_val,
                    max_elevation=max_elev_val,
                    vertical_unit_in_header="unknown",
                    vertical_datum_in_header="unknown",
                )

                if res_x > 100.0 or res_y > 100.0:
                    warnings.append(f"DEM resolution is coarse ({res_x:.1f} x {res_y:.1f}). Simulation accuracy may require spatial mesh refinement.")

        except HTTPException:
            raise
        except Exception as e:
            errors.append(f"Failed to parse DEM GeoTIFF '{dem_filename}': {str(e)}")

        # 4. Dam Axis GeoJSON Inspection (Only LineString / MultiLineString permitted)
        dam_axis_geom_dem_crs = None
        dam_axis_centroid_lon_lat: Optional[Tuple[float, float]] = None
        try:
            axis_data = json.loads(dam_axis_bytes.decode("utf-8"))
            features = []
            if axis_data.get("type") == "FeatureCollection":
                features = axis_data.get("features", [])
            elif axis_data.get("type") == "Feature":
                features = [axis_data]
            elif "type" in axis_data and axis_data["type"] in ("LineString", "MultiLineString"):
                features = [{"type": "Feature", "geometry": axis_data, "properties": {}}]
            else:
                errors.append(f"Dam axis file '{dam_axis_filename}' is not a valid GeoJSON object or FeatureCollection.")

            if len(features) > MAX_GEOJSON_FEATURES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Dam axis feature count ({len(features)}) exceeds maximum limit of {MAX_GEOJSON_FEATURES}.",
                )

            if not features:
                errors.append(f"Dam axis file '{dam_axis_filename}' contains 0 geometric features.")
            else:
                geom_types = set()
                all_geoms = []
                for idx, feat in enumerate(features):
                    g_dict = feat.get("geometry")
                    if not g_dict:
                        errors.append(f"Dam axis feature {idx} has no geometry.")
                        continue
                    sh_geom = shape(g_dict)
                    if not sh_geom.is_valid:
                        errors.append(f"Dam axis feature {idx} geometry is topologically invalid.")
                    g_type = sh_geom.geom_type
                    geom_types.add(g_type)
                    if g_type not in ("LineString", "MultiLineString"):
                        errors.append(f"Dam axis must contain only LineString or MultiLineString geometries. Found '{g_type}' in feature {idx}.")
                    all_geoms.append(sh_geom)

                if all_geoms and not any(t not in ("LineString", "MultiLineString") for t in geom_types):
                    dam_axis_geom_src = all_geoms[0] if len(all_geoms) == 1 else MultiLineString([g for g in all_geoms if isinstance(g, (LineString, MultiLineString))])
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

        except HTTPException:
            raise
        except json.JSONDecodeError as e:
            errors.append(f"Dam axis file '{dam_axis_filename}' is not valid JSON: {str(e)}")
        except Exception as e:
            errors.append(f"Failed to process dam axis GeoJSON '{dam_axis_filename}': {str(e)}")

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

        # 6. Breach Parameters & Metric Distance Calculation
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

    # 7. Explicit Assumptions Requiring Confirmation
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

    # 8. Readiness Flags
    is_valid = len(errors) == 0

    onboarding_validation_passed = (
        is_valid
        and raster_derived_meta is not None
        and axis_meta is not None
        and axis_meta.fully_within_dem_bounds
        and (res_meta is None or res_meta.fully_within_dem_bounds)
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
        geometry_crs=geometry_crs or "EPSG:4326",
    )

    normalized_meta = NormalizedProjectMetadata(
        project_name=clean_project_name,
        raster_metadata=raster_derived_meta,
        user_provided_metadata=user_meta,
        dam_axis_metadata=axis_meta,
        reservoir_metadata=res_meta,
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
    project_name: str = "New Dam Project",
    vertical_unit: Optional[str] = None,
    vertical_datum: Optional[str] = None,
    reservoir_level: Optional[float] = None,
    breach_width: Optional[float] = None,
    breach_center_x: Optional[float] = None,
    breach_center_y: Optional[float] = None,
    breach_formation_time_hr: Optional[float] = 1.0,
    manning_roughness: Optional[float] = 0.035,
    geometry_crs: str = "EPSG:4326",
    acknowledge_unverified_metadata: bool = False,
) -> DamProjectDetailResponse:
    """
    Atomically persists a validated dam onboarding project to runtime storage:
    - Reuses validate_dam_project_dataset.
    - Requires onboarding_validation_passed=True.
    - Requires acknowledge_unverified_metadata=True.
    - Generates server-side UUID v4.
    - Stores dem.tif, dam_axis.geojson, reservoir_boundary.geojson, project.json, and manifest.json.
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
        project_name=project_name,
        vertical_unit=vertical_unit,
        vertical_datum=vertical_datum,
        reservoir_level=reservoir_level,
        breach_width=breach_width,
        breach_center_x=breach_center_x,
        breach_center_y=breach_center_y,
        breach_formation_time_hr=breach_formation_time_hr,
        manning_roughness=manning_roughness,
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

        norm_meta = val_res.normalized_metadata
        project_dict: Dict[str, Any] = {
            "project_id": project_id,
            "project_name": norm_meta.project_name,
            "status": "validated_unverified",
            "created_at": created_at,
            "dem_file": "dem.tif",
            "dam_axis_file": "dam_axis.geojson",
            "reservoir_boundary_file": res_rel_name,
            "raster_metadata": norm_meta.raster_metadata.model_dump() if norm_meta.raster_metadata else {},
            "user_provided_metadata": norm_meta.user_provided_metadata.model_dump() if norm_meta.user_provided_metadata else {},
            "dam_axis_metadata": norm_meta.dam_axis_metadata.model_dump() if norm_meta.dam_axis_metadata else {},
            "reservoir_metadata": norm_meta.reservoir_metadata.model_dump() if norm_meta.reservoir_metadata else None,
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
            # Security check on manifest filenames: prevent traversal
            if ".." in rel_name or "/" in rel_name or "\\" in rel_name:
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

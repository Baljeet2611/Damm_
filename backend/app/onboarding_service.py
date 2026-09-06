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
"""

import os
import json
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import rasterio
from shapely.geometry import shape, Point, box, LineString, MultiLineString, Polygon, MultiPolygon
from shapely.ops import transform as shapely_transform
from pyproj import CRS, Transformer
from fastapi import HTTPException

from app.schemas import (
    RasterBounds,
    RasterResolution,
    RasterDerivedMetadata,
    UserProvidedMetadata,
    GeometryValidationMetadata,
    NormalizedProjectMetadata,
    DamProjectValidationResponse,
)

# Configurable resource limits
MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024       # 50 MB per file
MAX_RASTER_PIXELS = 100_000_000                # 100 Million pixels
MAX_GEOJSON_FEATURES = 5_000                   # 5,000 features

# Allowed file extensions
ALLOWED_DEM_EXTENSIONS = {".tif", ".tiff"}
ALLOWED_GEOJSON_EXTENSIONS = {".geojson", ".json"}


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
                    # Strict geometry type check
                    if g_type not in ("LineString", "MultiLineString"):
                        errors.append(f"Dam axis must contain only LineString or MultiLineString geometries. Found '{g_type}' in feature {idx}.")
                    all_geoms.append(sh_geom)

                if all_geoms and not any(t not in ("LineString", "MultiLineString") for t in geom_types):
                    dam_axis_geom_src = all_geoms[0] if len(all_geoms) == 1 else MultiLineString([g for g in all_geoms if isinstance(g, (LineString, MultiLineString))])
                    raw_centroid = (float(dam_axis_geom_src.centroid.x), float(dam_axis_geom_src.centroid.y))

                    # Parse geometry CRS
                    src_geom_crs = CRS.from_user_input(geometry_crs or "EPSG:4326")

                    # Reproject to DEM CRS for spatial bounding checks
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

                    # Store geographic centroid for metric UTM determination
                    if src_geom_crs.is_geographic:
                        dam_axis_centroid_lon_lat = raw_centroid
                    elif dem_crs_obj and dem_crs_obj.is_geographic:
                        dam_axis_centroid_lon_lat = (float(dam_axis_geom_dem_crs.centroid.x), float(dam_axis_geom_dem_crs.centroid.y)) if dam_axis_geom_dem_crs else raw_centroid
                    else:
                        # Reproject centroid to WGS84 for UTM zone derivation if needed
                        try:
                            t_to_geo = Transformer.from_crs(src_geom_crs, "EPSG:4326", always_xy=True)
                            dam_axis_centroid_lon_lat = t_to_geo.transform(raw_centroid[0], raw_centroid[1])
                        except Exception:
                            dam_axis_centroid_lon_lat = (75.0, 15.0)  # Default central India

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

            # First verify breach center is inside DEM bounds in DEM CRS
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

            # Now calculate metric distance in metres
            if dam_axis_geom_dem_crs is not None:
                try:
                    # Case A: DEM CRS is already a projected metric CRS (e.g. UTM)
                    if dem_crs_obj and not dem_crs_obj.is_geographic:
                        metric_crs_str = str(dem_crs_obj)
                        axis_metric = dam_axis_geom_dem_crs
                        if src_geom_crs != dem_crs_obj:
                            t_to_metric = Transformer.from_crs(src_geom_crs, dem_crs_obj, always_xy=True)
                            b_pt_metric = shapely_transform(t_to_metric.transform, b_pt_raw)
                        else:
                            b_pt_metric = b_pt_raw
                    else:
                        # Case B: Geographic CRS — Reproject both into local UTM zone for accurate metric measurement
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

    # Onboarding validation passed requires complete valid geometry and fully contained coverage
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

    # Scientific verification remains false in this MVP because no authoritative evidence/document verification workflow exists
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


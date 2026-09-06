"""
Preprocessing Script for ANUGA Hidkal Regional Pilot (Phase 15).
Reads raw EPSG:4326 DEM, verifies checksums, reprojects to EPSG:32643 (UTM 43N),
preserves the valid source footprint mask, and generates clean elevation arrays.
"""

import os
import sys
import json
import hashlib
from pathlib import Path
import numpy as np
from scipy import ndimage
import pyproj
from PIL import Image


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 checksum of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def preprocess_dem():
    print("=" * 75)
    print("Preflight Topography & DEM Reprojection for ANUGA Hidkal Pilot")
    print("=" * 75)

    repo_root = Path(__file__).resolve().parent.parent.parent
    raw_dem_path = repo_root / "data" / "raw" / "data_hidkal" / "hidkal_dem.tif"
    output_dir = repo_root / "validation" / "anuga_hidkal_pilot" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not raw_dem_path.is_file():
        raise FileNotFoundError(f"Raw DEM not found at: {raw_dem_path}")

    # 1. Check raw hash and dimensions
    raw_hash = compute_sha256(raw_dem_path)
    expected_hash = "ed4c97474857ef24845f0954baa36b8de2555ccc2a0d468cfa99fdd39fab5baf"
    print(f"Raw DEM SHA-256: {raw_hash}")
    assert raw_hash == expected_hash, f"Raw DEM hash mismatch: expected {expected_hash}, got {raw_hash}"

    # Read raw image
    img = Image.open(raw_dem_path)
    dem_src = np.array(img, dtype=float)
    src_rows, src_cols = dem_src.shape
    total_src_cells = src_rows * src_cols
    src_nodata_count = int(np.sum((dem_src <= -9990.0) | np.isnan(dem_src)))

    print(f"Source DEM: {src_rows} rows x {src_cols} cols ({total_src_cells} cells)")
    print(f"Source NoData count: {src_nodata_count} cells")
    print(f"Source Elevation Range: {dem_src.min():.4f} to {dem_src.max():.4f} assumed metres based on source interpretation")

    # 2. Coordinate Reprojection to EPSG:32643
    dst_crs = "EPSG:32643"
    dst_resolution = 50.0  # meters

    from scipy.interpolate import RegularGridInterpolator
    lon_src = np.linspace(74.60, 74.88, src_cols)
    lat_src = np.linspace(16.32, 16.12, src_rows)  # top to bottom
    interp = RegularGridInterpolator((lat_src[::-1], lon_src), dem_src[::-1, :], bounds_error=False, fill_value=np.nan)

    transformer_inv = pyproj.Transformer.from_crs(dst_crs, "EPSG:4326", always_xy=True)
    x_min, x_max = 457200.0, 487200.0
    y_min, y_max = 1782250.0, 1804350.0
    x_coords = np.arange(x_min, x_max + dst_resolution, dst_resolution)
    y_coords = np.arange(y_max, y_min - dst_resolution, -dst_resolution)

    XX, YY = np.meshgrid(x_coords, y_coords)
    lons, lats = transformer_inv.transform(XX, YY)
    pts = np.column_stack([lats.ravel(), lons.ravel()])
    dem_grid_raw = interp(pts).reshape(XX.shape)

    # 3. Footprint Mask and Filling Statistics
    reprojection_nan_mask = np.isnan(dem_grid_raw) | (dem_grid_raw < 0)
    reprojection_nan_count = int(np.sum(reprojection_nan_mask))
    total_reprojected_cells = dem_grid_raw.size
    valid_cells_count = total_reprojected_cells - reprojection_nan_count
    filled_area_km2 = (reprojection_nan_count * dst_resolution * dst_resolution) / 1e6
    valid_area_km2 = (valid_cells_count * dst_resolution * dst_resolution) / 1e6

    print(f"Reprojected Grid: {dem_grid_raw.shape[0]} rows x {dem_grid_raw.shape[1]} cols ({total_reprojected_cells} cells)")
    print(f"Reprojection Corner NaNs: {reprojection_nan_count} cells ({filled_area_km2:.2f} km^2, {reprojection_nan_count/total_reprojected_cells*100:.2f}%)")
    print(f"Valid Source Footprint: {valid_cells_count} cells ({valid_area_km2:.2f} km^2, {valid_cells_count/total_reprojected_cells*100:.2f}%)")

    # Valid footprint mask (True inside valid geographic footprint)
    valid_footprint_mask = ~reprojection_nan_mask

    # Nearest-neighbor fill strictly for numerical domain boundary elevation smoothness
    if reprojection_nan_count > 0:
        ind = ndimage.distance_transform_edt(reprojection_nan_mask, return_distances=False, return_indices=True)
        dem_cleaned = dem_grid_raw[tuple(ind)]
    else:
        dem_cleaned = dem_grid_raw.copy()

    # 4. Save Processed Artifacts
    grid_meta = {
        "source_raw_dem": str(raw_dem_path.name),
        "source_raw_sha256": raw_hash,
        "source_nodata_count": src_nodata_count,
        "source_elevation_range_assumed_m": [float(dem_src.min()), float(dem_src.max())],
        "elevation_units_statement": "assumed metres based on source interpretation",
        "vertical_datum_statement": "unverified",
        "target_crs": dst_crs,
        "resolution_m": dst_resolution,
        "total_cells": total_reprojected_cells,
        "valid_source_footprint_cells": valid_cells_count,
        "valid_source_area_km2": round(valid_area_km2, 2),
        "reprojection_created_nan_cells": reprojection_nan_count,
        "filled_corner_area_km2": round(filled_area_km2, 2),
        "filling_method": "nearest_neighbor_edt_for_mesh_boundary_smoothness",
        "x_min": float(x_coords.min()),
        "x_max": float(x_coords.max()),
        "y_min": float(y_coords.min()),
        "y_max": float(y_coords.max()),
        "min_elevation_assumed_m": round(float(np.min(dem_cleaned)), 2),
        "max_elevation_assumed_m": round(float(np.max(dem_cleaned)), 2),
        "mean_elevation_assumed_m": round(float(np.mean(dem_cleaned)), 2),
    }

    grid_meta_path = output_dir / "dem_utm43n_metadata.json"
    with open(grid_meta_path, "w") as f:
        json.dump(grid_meta, f, indent=2)

    np.save(output_dir / "dem_utm43n_array.npy", dem_cleaned)
    np.save(output_dir / "dem_utm43n_x.npy", x_coords)
    np.save(output_dir / "dem_utm43n_y.npy", y_coords)
    np.save(output_dir / "valid_footprint_mask.npy", valid_footprint_mask)

    print("\nReprojection Summary:")
    print(f"  Target CRS: {dst_crs}")
    print(f"  Elevation Range: {grid_meta['min_elevation_assumed_m']} to {grid_meta['max_elevation_assumed_m']} assumed metres")
    print(f"  Grid Metadata: {grid_meta_path}")
    print("=" * 75)
    return grid_meta


if __name__ == "__main__":
    preprocess_dem()

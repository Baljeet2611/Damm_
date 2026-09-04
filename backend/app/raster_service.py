import os
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import numpy as np
import rasterio
from rasterio.windows import Window
from fastapi import HTTPException

from app.schemas import (
    DatasetResponse,
    RasterBounds,
    RasterResolution,
    RasterMetadataResponse,
    RasterPointValueResponse,
)

# Fixed registered dataset catalog
DEFAULT_REGISTERED_DATASETS: Dict[str, Dict[str, Any]] = {
    "dem": {
        "label": "Hidkal Digital Elevation Model (DEM)",
        "relative_path": "data/raw/data_hidkal/hidkal_dem.tif",
        "data_type": "elevation",
        "unit_status": "unverified (elevation unit and vertical datum unverified)",
        "provenance_status": "unverified sample raster of unknown provenance",
    },
    "depth": {
        "label": "Hidkal Inundation Depth",
        "relative_path": "data/raw/data_hidkal/hidkal_depth.tif",
        "data_type": "depth",
        "unit_status": "unverified",
        "provenance_status": "unverified sample raster of unknown provenance",
    },
    "velocity": {
        "label": "Hidkal Flow Velocity",
        "relative_path": "data/raw/data_hidkal/hidkal_velocity.tif",
        "data_type": "velocity",
        "unit_status": "unverified",
        "provenance_status": "unverified sample raster of unknown provenance",
    },
    "arrival": {
        "label": "Hidkal Flood Wave Arrival Time",
        "relative_path": "data/raw/data_hidkal/hidkal_arrival.tif",
        "data_type": "arrival_time",
        "unit_status": "unknown (unit unknown, header NoData -9999 vs data +9999)",
        "provenance_status": "unverified sample raster of unknown provenance",
    },
}

_active_datasets: Dict[str, Dict[str, Any]] = dict(DEFAULT_REGISTERED_DATASETS)
_metadata_cache: Dict[str, Tuple[float, RasterMetadataResponse]] = {}


def get_project_root() -> Path:
    """Return the workspace/project root directory."""
    if "SIH_PROJECT_ROOT" in os.environ:
        return Path(os.environ["SIH_PROJECT_ROOT"]).resolve()
    # backend/app/raster_service.py -> backend/app -> backend -> project_root
    return Path(__file__).resolve().parents[2]


def set_registered_datasets(datasets: Dict[str, Dict[str, Any]]) -> None:
    """Override registered datasets (primarily used in tests)."""
    global _active_datasets
    _active_datasets = dict(datasets)
    clear_cache()


def reset_registered_datasets() -> None:
    """Reset to default registered datasets."""
    global _active_datasets
    _active_datasets = dict(DEFAULT_REGISTERED_DATASETS)
    clear_cache()


def clear_cache() -> None:
    """Clear in-memory metadata cache."""
    global _metadata_cache
    _metadata_cache.clear()


def resolve_dataset_file(dataset_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    """
    Resolve dataset information and path strictly against registered IDs.
    Prevents path traversal and arbitrary filesystem input.
    """
    if dataset_id not in _active_datasets:
        return None, None
    info = _active_datasets[dataset_id]
    rel_path = info["relative_path"]
    resolved = (get_project_root() / rel_path).resolve()
    return info, resolved


def list_datasets() -> list[DatasetResponse]:
    """
    List all registered datasets with metadata without exposing absolute filesystem paths.
    """
    results: list[DatasetResponse] = []
    for dataset_id, info in _active_datasets.items():
        _, file_path = resolve_dataset_file(dataset_id)
        is_available = file_path is not None and file_path.is_file()
        results.append(
            DatasetResponse(
                id=dataset_id,
                label=info["label"],
                availability=is_available,
                available=is_available,
                data_type=info["data_type"],
                unit_status=info["unit_status"],
                provenance_status=info["provenance_status"],
            )
        )
    return results


def get_raster_metadata(dataset_id: str) -> RasterMetadataResponse:
    """
    Fetch and cache raster metadata (width, height, dtype, CRS, bounds, resolution, NoData, valid min/max).
    Never returns full raster arrays.
    """
    info, file_path = resolve_dataset_file(dataset_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Unknown raster dataset ID: '{dataset_id}'")
    if file_path is None or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Raster file for dataset '{dataset_id}' is not available")

    mtime = file_path.stat().st_mtime
    cached = _metadata_cache.get(dataset_id)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    with rasterio.open(file_path) as src:
        bounds = RasterBounds(
            left=float(src.bounds.left),
            bottom=float(src.bounds.bottom),
            right=float(src.bounds.right),
            top=float(src.bounds.top),
        )
        res_x = float(src.res[0])
        res_y = float(src.res[1])
        resolution = RasterResolution(x=res_x, y=res_y)

        crs_str = src.crs.to_string() if src.crs else None
        meta_nodata = float(src.nodata) if src.nodata is not None else None

        # Compute valid min/max considering nodata rules without retaining array in cache
        raw_arr = src.read(1)
        mask = np.isnan(raw_arr)
        if meta_nodata is not None:
            mask |= np.isclose(raw_arr, meta_nodata)
        if dataset_id == "arrival":
            # Treat both +9999 and -9999 as nodata for arrival
            mask |= np.isclose(raw_arr, 9999.0) | np.isclose(raw_arr, -9999.0)

        valid_vals = raw_arr[~mask]
        valid_min = float(valid_vals.min()) if valid_vals.size > 0 else None
        valid_max = float(valid_vals.max()) if valid_vals.size > 0 else None

        meta_response = RasterMetadataResponse(
            id=dataset_id,
            width=int(src.width),
            height=int(src.height),
            dtype=str(src.dtypes[0]),
            crs=crs_str,
            bounds=bounds,
            resolution=resolution,
            nodata=meta_nodata,
            valid_min=valid_min,
            valid_max=valid_max,
        )

    _metadata_cache[dataset_id] = (mtime, meta_response)
    return meta_response


def get_raster_point_value(dataset_id: str, lon: float, lat: float) -> RasterPointValueResponse:
    """
    Validate coordinates and query single pixel value using Rasterio window.
    Returns row, column, value, and is_nodata.
    Returns 404 for unknown ID and 422 outside raster bounds.
    Treats both +9999 and -9999 as NoData for arrival (value: null).
    """
    info, file_path = resolve_dataset_file(dataset_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Unknown raster dataset ID: '{dataset_id}'")
    if file_path is None or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Raster file for dataset '{dataset_id}' is not available")

    with rasterio.open(file_path) as src:
        min_x = min(src.bounds.left, src.bounds.right)
        max_x = max(src.bounds.left, src.bounds.right)
        min_y = min(src.bounds.bottom, src.bounds.top)
        max_y = max(src.bounds.bottom, src.bounds.top)

        if not (min_x <= lon <= max_x and min_y <= lat <= max_y):
            raise HTTPException(
                status_code=422,
                detail=f"Coordinates ({lon}, {lat}) are outside raster bounds: [{min_x}, {min_y}, {max_x}, {max_y}]",
            )

        row, col = src.index(lon, lat)

        # Handle boundary edges
        if col == src.width and np.isclose(lon, max_x):
            col = src.width - 1
        if row == src.height and np.isclose(lat, min_y):
            row = src.height - 1

        if row < 0 or row >= src.height or col < 0 or col >= src.width:
            raise HTTPException(
                status_code=422,
                detail=f"Coordinates ({lon}, {lat}) map outside raster grid dimensions [{src.width}x{src.height}]",
            )

        # Point window query: 1x1 pixel read
        pixel_window = Window(col, row, 1, 1)
        pixel_arr = src.read(1, window=pixel_window)
        raw_val = float(pixel_arr[0, 0])

        is_nodata = False
        if np.isnan(raw_val):
            is_nodata = True
        elif src.nodata is not None and np.isclose(raw_val, src.nodata):
            is_nodata = True
        elif dataset_id == "arrival" and (np.isclose(raw_val, 9999.0) or np.isclose(raw_val, -9999.0)):
            is_nodata = True

        return RasterPointValueResponse(
            id=dataset_id,
            row=int(row),
            column=int(col),
            value=None if is_nodata else raw_val,
            is_nodata=is_nodata,
        )

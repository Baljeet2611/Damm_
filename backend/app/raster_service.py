import io
import os
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
import numpy as np
import rasterio
from rasterio.windows import Window
from PIL import Image
from rio_tiler.io import Reader
from rio_tiler.errors import TileOutsideBounds, PointOutsideBounds, RioTilerError
from fastapi import HTTPException

from app.schemas import (
    DatasetResponse,
    RasterBounds,
    RasterResolution,
    RasterMetadataResponse,
    RasterPointValueResponse,
    ColorRampStop,
    LegendItem,
    RasterLegendResponse,
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

# Precomputed empty transparent 256x256 PNG
_empty_img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
_empty_buf = io.BytesIO()
_empty_img.save(_empty_buf, format="PNG")
EMPTY_TILE_PNG = _empty_buf.getvalue()


# Colormap and legend definitions for display
DATASET_STYLES: Dict[str, Dict[str, Any]] = {
    "dem": {
        "min": 600.0,
        "max": 685.0,
        "stops": [
            (600.0, (45, 106, 79, 255), "#2d6a4f", "600 (Valley Floor, unit unverified)"),
            (620.0, (82, 183, 136, 255), "#52b788", "620 (unit unverified)"),
            (640.0, (216, 243, 220, 255), "#d8f3dc", "640 (Mid Slope, unit unverified)"),
            (660.0, (233, 196, 106, 255), "#e9c46a", "660 (unit unverified)"),
            (685.0, (188, 108, 37, 255), "#bc6c25", "685 (Ridge Top, unit unverified)"),
        ],
    },
    "depth": {
        "min": 0.1,
        "max": 14.0,
        "stops": [
            (0.1, (144, 224, 239, 230), "#90e0ef", "0.1 (Shallow Water, unit unverified)"),
            (1.0, (0, 180, 216, 240), "#00b4d8", "1.0 (Moderate Inundation, unit unverified)"),
            (3.0, (0, 119, 182, 245), "#0077b6", "3.0 (Deep Water, unit unverified)"),
            (6.0, (3, 4, 94, 255), "#03045e", "6.0 (Severe Flood, unit unverified)"),
            (14.0, (60, 9, 108, 255), "#3c096c", "> 10 (Extreme Hydrodynamic Depth, unit unverified)"),
        ],
    },
    "velocity": {
        "min": 0.1,
        "max": 22.0,
        "stops": [
            (0.1, (254, 228, 64, 230), "#fee440", "0.1 (Low Velocity, unit unverified)"),
            (2.0, (247, 127, 0, 240), "#f77f00", "2.0 (Moderate Flow, unit unverified)"),
            (5.0, (230, 57, 70, 245), "#e63946", "5.0 (Fast Flow, unit unverified)"),
            (10.0, (157, 2, 8, 255), "#9d0208", "10.0 (High Hazard Wave, unit unverified)"),
            (22.0, (55, 6, 23, 255), "#370617", "> 20 (Extreme Kinetic Force, unit unverified)"),
        ],
    },
    "arrival": {
        "min": 7.0,
        "max": 66.5,
        "stops": [
            (7.0, (217, 4, 41, 245), "#d90429", "7.0 (Immediate Impact / Early Wave, unit unverified)"),
            (15.0, (247, 127, 0, 240), "#f77f00", "15.0 (unit unverified)"),
            (25.0, (255, 209, 102, 235), "#ffd166", "25.0 (Mid Wave Progression, unit unverified)"),
            (40.0, (6, 214, 160, 235), "#06d6a0", "40.0 (unit unverified)"),
            (66.5, (17, 138, 178, 245), "#118ab2", "66.5 (Late Wave / Recession, unit unverified)"),
        ],
    },
}


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


def _apply_colormap(dataset_id: str, data_2d: np.ndarray, meta_nodata: Optional[float]) -> np.ndarray:
    """
    Apply dataset-specific color ramps and enforce transparency rules:
    - dem: NoData is transparent (alpha = 0).
    - depth: depth <= 0.0 (dry pixels) is transparent (alpha = 0).
    - velocity: velocity <= 0.0 is transparent (alpha = 0).
    - arrival: +9999, -9999, and values <= 0 are transparent (alpha = 0).
    """
    h, w = data_2d.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)

    style = DATASET_STYLES.get(dataset_id)
    if style is None:
        # Fallback to dem style if not explicitly registered
        style = DATASET_STYLES["dem"]

    # Compute valid mask based on dataset transparency rules
    mask = ~np.isnan(data_2d)
    if meta_nodata is not None:
        mask &= ~np.isclose(data_2d, meta_nodata)

    if dataset_id == "dem":
        mask &= ~np.isclose(data_2d, -9999.0) & (data_2d > -9000.0)
    elif dataset_id in ("depth", "velocity"):
        # Zero cells (dry / zero velocity) must be completely transparent
        mask &= (data_2d > 0.0) & ~np.isclose(data_2d, -9999.0)
    elif dataset_id == "arrival":
        # Arrival +9999.0 and -9999.0 must be completely transparent
        mask &= (
            ~np.isclose(data_2d, 9999.0)
            & ~np.isclose(data_2d, -9999.0)
            & (data_2d < 9000.0)
            & (data_2d > 0.0)
        )

    if not np.any(mask):
        return rgba

    vals = data_2d[mask]
    stops = style["stops"]
    v_stops = np.array([s[0] for s in stops], dtype=np.float32)
    c_stops = np.array([s[1] for s in stops], dtype=np.float32)

    # Interpolate RGBA channels
    r_chan = np.interp(vals, v_stops, c_stops[:, 0])
    g_chan = np.interp(vals, v_stops, c_stops[:, 1])
    b_chan = np.interp(vals, v_stops, c_stops[:, 2])
    a_chan = np.interp(vals, v_stops, c_stops[:, 3])

    rgba[mask, 0] = np.clip(r_chan, 0, 255).astype(np.uint8)
    rgba[mask, 1] = np.clip(g_chan, 0, 255).astype(np.uint8)
    rgba[mask, 2] = np.clip(b_chan, 0, 255).astype(np.uint8)
    rgba[mask, 3] = np.clip(a_chan, 0, 255).astype(np.uint8)

    return rgba


def get_raster_tile(dataset_id: str, z: int, x: int, y: int) -> bytes:
    """
    Render standard Web Mercator tile (z, x, y) as PNG bytes using rio-tiler.
    - Whitelists dataset IDs: dem, depth, velocity, arrival (404 on unknown/unavailable).
    - Gracefully returns transparent 256x256 PNG for out-of-bounds tiles without 500 errors.
    - Applies custom styling and transparency rules.
    - Never exposes absolute filesystem paths.
    """
    info, file_path = resolve_dataset_file(dataset_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Unknown raster dataset ID: '{dataset_id}'")
    if file_path is None or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Raster file for dataset '{dataset_id}' is not available")

    # Validate tile coordinate bounds
    if z < 0 or z > 24:
        return EMPTY_TILE_PNG
    max_coord = 1 << z
    if x < 0 or x >= max_coord or y < 0 or y >= max_coord:
        return EMPTY_TILE_PNG

    try:
        with Reader(str(file_path)) as reader:
            nodata = getattr(reader.dataset, "nodata", None)
            img_data = reader.tile(tile_x=x, tile_y=y, tile_z=z)
            tile_arr = img_data.data[0].astype(np.float32)
    except (TileOutsideBounds, PointOutsideBounds, RioTilerError, ValueError, IndexError):
        # Out-of-bounds tiles return empty transparent tile gracefully
        return EMPTY_TILE_PNG
    except Exception as exc:
        # Fallback to empty tile on unexpected read error if outside extent
        return EMPTY_TILE_PNG

    rgba = _apply_colormap(dataset_id, tile_arr, nodata)
    img = Image.fromarray(rgba, "RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_raster_legend(dataset_id: str) -> RasterLegendResponse:
    """
    Return legend metadata, color ramp stops, and discrete legend items for a raster layer.
    """
    info, file_path = resolve_dataset_file(dataset_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Unknown raster dataset ID: '{dataset_id}'")
    if file_path is None or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Raster file for dataset '{dataset_id}' is not available")

    style = DATASET_STYLES.get(dataset_id)
    if style is None:
        style = DATASET_STYLES["dem"]

    min_val = style["min"]
    max_val = style["max"]

    color_ramp: List[ColorRampStop] = []
    items: List[LegendItem] = []

    for val, _, color_hex, label in style["stops"]:
        offset = 0.0 if max_val == min_val else (val - min_val) / (max_val - min_val)
        offset = max(0.0, min(1.0, float(offset)))
        color_ramp.append(
            ColorRampStop(
                offset=round(offset, 4),
                color=color_hex,
                value=float(val),
            )
        )
        items.append(
            LegendItem(
                value=float(val),
                color=color_hex,
                label=label,
            )
        )

    return RasterLegendResponse(
        id=dataset_id,
        label=info["label"],
        unit_status=info["unit_status"],
        provenance_status=info["provenance_status"],
        min_value=min_val,
        max_value=max_val,
        color_ramp=color_ramp,
        items=items,
    )


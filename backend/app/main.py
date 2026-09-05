from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import (
    DatasetResponse,
    RasterMetadataResponse,
    RasterPointValueResponse,
    RasterLegendResponse,
)
from app.raster_service import (
    list_datasets,
    get_raster_metadata,
    get_raster_point_value,
    get_raster_tile,
    get_raster_legend,
)

app = FastAPI(
    title="Dam Break Decision Support System API",
    description="Automated dam-break hydrodynamic inspection and inundation analysis API",
    version="0.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/datasets", response_model=list[DatasetResponse])
def get_datasets() -> list[DatasetResponse]:
    """
    Return registered dataset catalog including ID, label, availability,
    data type, unit status, and provenance status without exposing absolute paths.
    """
    return list_datasets()


@app.get("/api/rasters/{id}/metadata", response_model=RasterMetadataResponse)
def get_metadata(id: str) -> RasterMetadataResponse:
    """
    Return cached raster dimensions, dtype, CRS, bounds, resolution,
    metadata NoData, and valid min/max.
    """
    return get_raster_metadata(dataset_id=id)


@app.get("/api/rasters/{id}/value", response_model=RasterPointValueResponse)
def get_point_value(
    id: str,
    lon: float = Query(..., description="Query longitude coordinate"),
    lat: float = Query(..., description="Query latitude coordinate"),
) -> RasterPointValueResponse:
    """
    Point query at given coordinates (lon, lat).
    Validates coordinates against raster bounds (422 outside bounds),
    returns row, column, value, and is_nodata.
    Treats +9999 and -9999 as NoData for arrival raster without modifying original file.
    """
    return get_raster_point_value(dataset_id=id, lon=lon, lat=lat)


@app.get("/api/rasters/{id}/tiles/{z}/{x}/{y}.png")
def get_tile(
    id: str,
    z: int,
    x: int,
    y: int,
) -> Response:
    """
    Web Mercator XYZ tile endpoint for raster visualization.
    Returns 256x256 PNG with customized color ramp and layer transparency.
    Out-of-bounds tiles return empty transparent PNGs without 500 errors.
    """
    tile_bytes = get_raster_tile(dataset_id=id, z=z, x=x, y=y)
    return Response(
        content=tile_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/rasters/{id}/legend", response_model=RasterLegendResponse)
def get_legend(id: str) -> RasterLegendResponse:
    """
    Return colormap stops, discrete legend classifications, and value range
    for the specified raster layer.
    """
    return get_raster_legend(dataset_id=id)


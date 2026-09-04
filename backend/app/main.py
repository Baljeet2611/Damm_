from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import (
    DatasetResponse,
    RasterMetadataResponse,
    RasterPointValueResponse,
)
from app.raster_service import (
    list_datasets,
    get_raster_metadata,
    get_raster_point_value,
)

app = FastAPI(
    title="Dam Break Decision Support System API",
    description="Automated dam-break hydrodynamic inspection and inundation analysis API",
    version="0.3.0",
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

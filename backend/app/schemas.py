from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class DatasetResponse(BaseModel):
    id: str
    label: str
    availability: bool
    available: bool
    data_type: str
    unit_status: str
    provenance_status: str


class RasterBounds(BaseModel):
    left: float
    bottom: float
    right: float
    top: float


class RasterResolution(BaseModel):
    x: float
    y: float


class RasterMetadataResponse(BaseModel):
    id: str
    width: int
    height: int
    dtype: str
    crs: Optional[str] = None
    bounds: RasterBounds
    resolution: RasterResolution
    nodata: Optional[float] = None
    valid_min: Optional[float] = None
    valid_max: Optional[float] = None


class RasterPointValueResponse(BaseModel):
    id: str
    row: int
    column: int
    value: Optional[float] = None
    is_nodata: bool


class LegendItem(BaseModel):
    value: float
    color: str
    label: str


class ColorRampStop(BaseModel):
    offset: float
    color: str
    value: float


class RasterLegendResponse(BaseModel):
    id: str
    label: str
    unit_status: str
    provenance_status: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    color_ramp: list[ColorRampStop]
    items: list[LegendItem]


# Vector & Preliminary Exposure Analysis Schemas

class CategoryCount(BaseModel):
    total: int
    assessed: int
    exposed: int
    not_exposed: int
    not_assessed: int


class ExposureDatasetSummary(BaseModel):
    total: int
    assessed: int
    exposed: int
    not_exposed: int
    not_assessed: int
    by_category: Dict[str, CategoryCount]


class ExposureSummaryResponse(BaseModel):
    disclaimer: str = "Preliminary exposure screening based on unverified sample rasters. Not a validated hydrodynamic risk assessment or damage analysis."
    methodology_note: str = "Direct coordinate sampling for points; representative-point/midpoint geometric screening for polygons and lines."
    assets: ExposureDatasetSummary
    roads: ExposureDatasetSummary


# Phase 7: Illustrative Damage Scenario Schemas

class DamageCurvePoint(BaseModel):
    depth: float = Field(..., ge=0.0, description="Flood depth (assumed unit)")
    damage_ratio: float = Field(..., ge=0.0, le=1.0, description="Damage ratio between 0.0 and 1.0")


class DamageConfigResponse(BaseModel):
    assumed_depth_unit: str
    currency_label: str
    replacement_values: Dict[str, float]
    depth_damage_curve: List[DamageCurvePoint]
    sensitivity_percentage: float
    disclaimer: str
    methodology: str


class DamageScenarioRequest(BaseModel):
    assumed_depth_unit: Optional[str] = "assumed meters (unverified)"
    currency_label: Optional[str] = "INR (₹)"
    replacement_values: Dict[str, float]
    depth_damage_curve: List[DamageCurvePoint]
    sensitivity_percentage: float = Field(default=20.0, ge=0.0, le=100.0)
    acknowledge_unverified_inputs: bool = False


class TotalEstimates(BaseModel):
    base_loss: float
    low_loss: float
    high_loss: float


class AssetCountSummary(BaseModel):
    total_assets: int
    assessed_assets: int
    screening_positive_assets: int
    not_exposed_assets: int
    not_assessed_assets: int


class CategoryDamageResult(BaseModel):
    total_count: int
    screening_positive_count: int
    not_exposed_count: int
    not_assessed_count: int
    unit_replacement_value: float
    base_loss: float
    low_loss: float
    high_loss: float


class DamageScenarioResponse(BaseModel):
    disclaimer: str
    methodology: str
    currency_label: str
    assumed_depth_unit: str
    sensitivity_percentage: float
    total_estimates: TotalEstimates
    asset_counts: AssetCountSummary
    by_category: Dict[str, CategoryDamageResult]
    warnings: List[str]

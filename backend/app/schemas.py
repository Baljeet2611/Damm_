from typing import Optional, Dict, Any, List, Tuple
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


# Phase 8: Route Screening Schemas

class RouteScreeningRequest(BaseModel):
    start_lon: float = Field(..., ge=-180.0, le=180.0, description="Start longitude in decimal degrees")
    start_lat: float = Field(..., ge=-90.0, le=90.0, description="Start latitude in decimal degrees")
    end_lon: float = Field(..., ge=-180.0, le=180.0, description="Destination longitude in decimal degrees")
    end_lat: float = Field(..., ge=-90.0, le=90.0, description="Destination latitude in decimal degrees")
    avoid_screening_positive: bool = Field(default=True, description="Remove screening-positive (depth > 0 at sample) road segments from routing graph")
    max_snap_distance_meters: float = Field(
        default=5000.0,
        ge=10.0,
        le=50000.0,
        description="Maximum allowed snapping distance in meters to nearest road network node. Points exceeding this are rejected.",
    )


class RouteScreeningResponse(BaseModel):
    route_found: bool
    geojson: Optional[Dict[str, Any]] = None
    total_distance_meters: Optional[float] = None
    total_distance_km: Optional[float] = None
    segment_count: Optional[int] = None
    start_coords: Tuple[float, float]
    end_coords: Tuple[float, float]
    snapped_start_coords: Optional[Tuple[float, float]] = None
    snapped_end_coords: Optional[Tuple[float, float]] = None
    start_snap_distance_meters: Optional[float] = None
    end_snap_distance_meters: Optional[float] = None
    excluded_edges_count: int
    avoid_screening_positive: bool
    disclaimer: str
    methodology: str
    warnings: List[str]


# Phase 9: Geospatial Export Schemas

class ExportRouteRequest(BaseModel):
    format: str = Field(default="geojson", description="Export format: geojson, kml, or shp")
    route_request: RouteScreeningRequest = Field(..., description="Route screening parameters to compute route for export")


class ExportRequest(BaseModel):
    layer: str = Field(..., description="Target layer: assets, roads, or route")
    format: str = Field(default="geojson", description="Export format: geojson, kml, or shp")
    exposure_filter: Optional[str] = Field(default="all", description="Exposure filter: all, screening_positive, not_exposed, not_assessed")
    route_request: Optional[RouteScreeningRequest] = Field(default=None, description="Route screening parameters if layer is route")


# Phase 10: Scenario Management Schemas

class ScenarioAssumption(BaseModel):
    parameter: str
    value: Any
    unit: str
    status: str = Field(
        default="unverified_illustrative",
        description="Verification status: unverified_illustrative, unverified_datum, estimated, verified"
    )
    note: str = ""


class ScenarioCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, description="Scenario title")
    description: Optional[str] = Field(default="", max_length=1000)
    site: str = Field(default="Hidkal Dam, Belagavi, Karnataka", max_length=200)
    dem_dataset_id: str = Field(default="dem", description="Referenced elevation dataset ID from catalog")
    crs: str = Field(default="EPSG:4326", description="Horizontal coordinate reference system")
    breach_width_m: float = Field(default=100.0, ge=1.0, le=5000.0, description="Assumed final breach width in meters")
    breach_formation_time_hr: float = Field(default=2.0, ge=0.01, le=100.0, description="Assumed breach formation time in hours")
    assumed_reservoir_level_m: float = Field(default=660.0, ge=0.0, le=5000.0, description="Assumed initial reservoir water level in meters")
    upstream_boundary_desc: str = Field(default="Dam breach failure hydrograph (illustrative)", max_length=300)
    downstream_boundary_desc: str = Field(default="Free water-level slope outflow", max_length=300)
    manning_roughness: float = Field(default=0.035, ge=0.001, le=1.0, description="Assumed uniform Manning bed friction coefficient n")
    mesh_resolution_m: float = Field(default=50.0, ge=1.0, le=1000.0, description="Target flexible mesh cell size in meters")
    simulation_duration_hr: float = Field(default=24.0, ge=0.1, le=720.0, description="Total simulation duration in hours")
    timestep_sec: float = Field(default=1.0, ge=0.001, le=3600.0, description="Target computational time step in seconds")
    assumptions: Optional[List[ScenarioAssumption]] = None


class ScenarioUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    site: Optional[str] = Field(default=None, max_length=200)
    dem_dataset_id: Optional[str] = None
    crs: Optional[str] = None
    breach_width_m: Optional[float] = Field(default=None, ge=1.0, le=5000.0)
    breach_formation_time_hr: Optional[float] = Field(default=None, ge=0.01, le=100.0)
    assumed_reservoir_level_m: Optional[float] = Field(default=None, ge=0.0, le=5000.0)
    upstream_boundary_desc: Optional[str] = Field(default=None, max_length=300)
    downstream_boundary_desc: Optional[str] = Field(default=None, max_length=300)
    manning_roughness: Optional[float] = Field(default=None, ge=0.001, le=1.0)
    mesh_resolution_m: Optional[float] = Field(default=None, ge=1.0, le=1000.0)
    simulation_duration_hr: Optional[float] = Field(default=None, ge=0.1, le=720.0)
    timestep_sec: Optional[float] = Field(default=None, ge=0.001, le=3600.0)
    assumptions: Optional[List[ScenarioAssumption]] = None


class ScenarioResponse(BaseModel):
    id: str = Field(..., description="UUID v4 scenario identifier")
    name: str
    description: str
    site: str
    dem_dataset_id: str
    crs: str
    breach_width_m: float
    breach_formation_time_hr: float
    assumed_reservoir_level_m: float
    upstream_boundary_desc: str
    downstream_boundary_desc: str
    manning_roughness: float
    mesh_resolution_m: float
    simulation_duration_hr: float
    timestep_sec: float
    assumptions: List[ScenarioAssumption]
    created_at: str
    updated_at: str
    revision: int
    archived: bool
    status: str = Field(
        ...,
        description="Scenario status: draft, input_review_required, build_ready, package_built, engine_unavailable, running, completed, failed"
    )
    validation_notes: List[str]
    snapshot_checksum: Optional[str] = None


# Phase 11: Delft3D Capabilities & Simulation Schemas

class SimulationCapabilitiesResponse(BaseModel):
    hydromt_available: bool
    hydromt_version: Optional[str] = None
    hydromt_path: Optional[str] = None
    dflowfm_available: bool
    execution_enabled: bool
    engine_executable: Optional[str] = None
    disclaimer: str
    guidance: str


class ModelPackageResponse(BaseModel):
    scenario_id: str
    revision: int
    package_filename: str
    package_size_bytes: int
    created_at: str
    manifest_checksum: str
    status: str
    download_url: str
    notes: List[str]


class SimulationRunRequest(BaseModel):
    custom_notes: Optional[str] = ""


class SimulationRunResponse(BaseModel):
    run_id: str
    scenario_id: str
    scenario_name: str
    revision: int
    status: str = Field(..., description="Status: running, completed, failed, engine_unavailable")
    started_at: str
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    exit_code: Optional[int] = None
    log_url: str
    notes: List[str]


class SimulationLogResponse(BaseModel):
    run_id: str
    scenario_id: str
    status: str
    stdout: str
    stderr: str




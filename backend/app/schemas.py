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
    hazard_source: str = "sample_hidkal"
    run_id: Optional[str] = None
    screening_threshold: float = 0.0
    unit_status: Optional[str] = "unverified"
    disclaimer: str = "Preliminary exposure screening based on unverified sample rasters. Not a validated hydrodynamic risk assessment or damage analysis."
    methodology_note: str = "Direct coordinate sampling for points; representative-point/midpoint geometric screening for polygons and lines."
    assets: ExposureDatasetSummary
    roads: ExposureDatasetSummary
    initially_wet_reservoir_assets: Optional[int] = None
    initially_wet_reservoir_roads: Optional[int] = None
    newly_inundated_assets: Optional[int] = None
    newly_inundated_roads: Optional[int] = None


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
    hazard_source: Optional[str] = Field(default="sample_hidkal", description="Hazard source: sample_hidkal, anuga_hidkal_pilot, or anuga_hidkal_refined")
    screening_threshold: Optional[float] = Field(default=0.0, ge=0.0, description="Minimum depth threshold for exposure screening")
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
    hazard_source: str = "sample_hidkal"
    run_id: Optional[str] = None
    screening_threshold: float = 0.0
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
    hazard_source: Optional[str] = Field(default="sample_hidkal", description="Hazard source: sample_hidkal, anuga_hidkal_pilot, or anuga_hidkal_refined")
    screening_threshold: Optional[float] = Field(default=0.0, ge=0.0, description="Minimum depth threshold for road avoidance")
    start_lon: float = Field(..., ge=-180.0, le=180.0, description="Start longitude in decimal degrees")
    start_lat: float = Field(..., ge=-90.0, le=90.0, description="Start latitude in decimal degrees")
    end_lon: float = Field(..., ge=-180.0, le=180.0, description="Destination longitude in decimal degrees")
    end_lat: float = Field(..., ge=-90.0, le=90.0, description="Destination latitude in decimal degrees")
    avoid_screening_positive: bool = Field(default=True, description="Remove screening-positive (depth > threshold) road segments from routing graph")
    max_snap_distance_meters: float = Field(
        default=5000.0,
        ge=10.0,
        le=50000.0,
        description="Maximum allowed snapping distance in meters to nearest road network node. Points exceeding this are rejected.",
    )


class RouteScreeningResponse(BaseModel):
    hazard_source: str = "sample_hidkal"
    run_id: Optional[str] = None
    screening_threshold: float = 0.0
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
    hazard_source: Optional[str] = Field(default="sample_hidkal", description="Hazard source: sample_hidkal, anuga_hidkal_pilot, or anuga_hidkal_refined")
    screening_threshold: Optional[float] = Field(default=0.0, ge=0.0, description="Screening threshold")
    route_request: RouteScreeningRequest = Field(..., description="Route screening parameters to compute route for export")


class ExportRequest(BaseModel):
    layer: str = Field(..., description="Target layer: assets, roads, or route")
    format: str = Field(default="geojson", description="Export format: geojson, kml, or shp")
    hazard_source: Optional[str] = Field(default="sample_hidkal", description="Hazard source: sample_hidkal, anuga_hidkal_pilot, or anuga_hidkal_refined")
    screening_threshold: Optional[float] = Field(default=0.0, ge=0.0, description="Screening threshold")
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


# Phase 12: SPH (PySPH) Schemas

class SPHCapabilitiesResponse(BaseModel):
    pysph_available: bool
    pysph_version: Optional[str] = None
    pysph_path: Optional[str] = None
    execution_enabled: bool
    engine_executable: Optional[str] = None
    disclaimer: str
    guidance: str


class SPHPackageResponse(BaseModel):
    scenario_id: str
    revision: int
    package_filename: str
    package_size_bytes: int
    created_at: str
    manifest_checksum: str
    status: str
    download_url: str
    benchmark_type: str = "2d_dam_break_benchmark"
    notes: List[str]


class SPHRunRequest(BaseModel):
    custom_notes: Optional[str] = ""
    particle_spacing_m: float = Field(default=0.5, ge=0.01, le=10.0, description="Initial particle spacing dx in meters")
    time_step_sec: float = Field(default=0.0001, ge=0.000001, le=0.1, description="Adaptive time step in seconds")


class SPHRunResponse(BaseModel):
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
    output_manifest_url: Optional[str] = None
    notes: List[str]


# Phase 12: Delft3D vs SPH Comparison Schemas

class ComparisonRunSummary(BaseModel):
    run_id: str
    scenario_id: str
    scenario_name: str
    engine: str
    status: str
    completed_at: Optional[str] = None
    has_depth_raster: bool
    has_velocity_raster: bool
    units_verified: bool


class ComparisonReadinessResponse(BaseModel):
    delft3d_completed_runs: List[ComparisonRunSummary]
    sph_completed_runs: List[ComparisonRunSummary]
    comparison_ready: bool
    blocker_reason: Optional[str] = None
    methodology_summary: str


class ComparisonRequest(BaseModel):
    delft3d_run_id: str
    sph_run_id: str
    reproject_crs: Optional[str] = "EPSG:4326"


class RasterMetricStats(BaseModel):
    parameter: str
    unit: str
    valid_cells: int
    mae: float
    rmse: float
    mean_bias: float
    max_delta: float


class ComparisonResponse(BaseModel):
    delft3d_run_id: str
    sph_run_id: str
    status: str = Field(..., description="completed or comparison_unavailable")
    common_crs: str
    common_grid_shape: Tuple[int, int]
    valid_overlap_cells: int
    overlap_area_km2: float
    extent_iou: float
    critical_success_index: float
    projected_area_diff_km2: float
    depth_stats: Optional[RasterMetricStats] = None
    velocity_stats: Optional[RasterMetricStats] = None
    arrival_stats: Optional[RasterMetricStats] = None
    notes: List[str]
    blockers: List[str]


class MethodologyComparisonResponse(BaseModel):
    comparison_matrix: List[Dict[str, Any]]
    scale_limitations: str
    disclaimer: str


# Phase 12: Google Earth Engine (GEE) Schemas

class GEECapabilitiesResponse(BaseModel):
    gee_available: bool
    authenticated: bool
    project_id: Optional[str] = None
    auth_mode: str
    tasks_enabled: bool
    whitelisted_collections: List[str]
    disclaimer: str
    guidance: str


class GEEDatasetInfo(BaseModel):
    id: str
    title: str
    provider: str
    type: str
    temporal_range: str
    spatial_resolution: str
    bands: List[str]
    usage_guidance: str
    disclaimer: str


class GEEExportPlanRequest(BaseModel):
    dataset_id: str
    start_date: str
    end_date: str
    roi_min_lon: float = Field(default=74.60, ge=-180.0, le=180.0)
    roi_min_lat: float = Field(default=16.12, ge=-90.0, le=90.0)
    roi_max_lon: float = Field(default=74.88, ge=-180.0, le=180.0)
    roi_max_lat: float = Field(default=16.32, ge=-90.0, le=90.0)
    target_scale_meters: float = Field(default=30.0, ge=10.0, le=5000.0)
    max_pixels: int = Field(default=10000000, le=10000000)


class GEEExportPlanResponse(BaseModel):
    task_id: str
    dataset_id: str
    status: str
    date_range: Tuple[str, str]
    roi_bounds: Tuple[float, float, float, float]
    estimated_pixels: int
    target_scale_meters: float
    candidate_observation_label: str
    acquisition_timestamps: List[str]
    cloud_task_submitted: bool
    notes: List[str]
    disclaimer: str


# ==========================================
# Phase 16: Hazard Sources & ANUGA Pilot Schemas
# ==========================================

class HazardSourceInfo(BaseModel):
    id: str
    label: str
    status: str
    disclaimer: str
    vertical_unit_status: str
    available: bool
    availability_reason: Optional[str] = None
    default_screening_threshold: float = 0.0
    layers: List[str]
    run_id: Optional[str] = None


class HazardSourcesResponse(BaseModel):
    default_source: str
    sources: List[HazardSourceInfo]
    scientific_notice: str


class ANUGARunSummary(BaseModel):
    run_id: str
    scenario_status: str
    title: str
    site: str
    timestamp_utc: Optional[str] = None
    available: bool
    availability_reason: Optional[str] = None
    breach_width_m: float
    simulated_duration_sec: float
    saved_yield_frames: int
    arrival_time_resolution_sec: float
    initial_volume_assumed_mcm: Optional[float] = None
    mesh_triangles: Optional[int] = None
    mesh_vertices: Optional[int] = None
    raster_cells_total: Optional[int] = None
    raster_cells_valid: Optional[int] = None
    screening_threshold_label: str = "0.10 assumed metres"
    velocity_unit_label: str = "assumed m/s"
    volume_unit_label: str = "assumed MCM"
    disclaimer: str


class ANUGARunDetailResponse(BaseModel):
    run_id: str
    scenario_status: str
    title: str
    site: str
    timestamp_utc: Optional[str] = None
    available: bool
    availability_reason: Optional[str] = None
    disclaimer: str
    assumptions: Dict[str, Any]
    breach_mechanics: Dict[str, Any]
    spatial_parameters: Dict[str, Any]
    computational_statistics: Dict[str, Any]
    boundary_analysis: Dict[str, Any]
    area_partitioning_km2: Dict[str, Any]
    volume_conservation: Dict[str, Any]
    inundation_results: Dict[str, Any]
    mesh_sensitivity: Optional[Dict[str, Any]] = None
    scientific_validity_note: Optional[str] = None
    provenance_metrics: Optional[Dict[str, Any]] = None
    layers: Dict[str, Dict[str, Any]]
    manifest: Dict[str, Any]


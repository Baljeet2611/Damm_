from enum import Enum
from typing import Optional, Dict, Any, List, Tuple, Literal, Union
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
    project_configured: bool = False
    earthengine_import_success: bool = False
    gee_project_id: Optional[str] = None
    project_id: Optional[str] = None
    auth_mode: str = "none"
    tasks_enabled: bool = False
    reason: str = ""
    supported_datasets: List[Dict[str, Any]] = []
    whitelisted_collections: List[str] = []
    disclaimer: str = ""
    guidance: str = ""


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


# Phase 20: Project-Scoped Earth Observation & Model-Observation Comparison Schemas

class ProjectAOIResponse(BaseModel):
    project_id: str
    aoi_bounds: Tuple[float, float, float, float] = Field(..., description="(min_lon, min_lat, max_lon, max_lat) in WGS84")
    aoi_geojson: Dict[str, Any]
    aoi_area_km2: float
    source: str = Field(..., description="simulation_domain, dem_extent, or buffered_dam_point")
    buffer_applied_meters: float = 1000.0


class Sentinel1ProcessingParams(BaseModel):
    polarization: Literal["VV", "VH", "both"] = "VV"
    change_threshold_db: float = Field(default=-3.0, description="Configurable initial heuristic threshold for backscatter drop")
    post_event_water_threshold_db: float = Field(default=-15.0, description="Configurable initial heuristic threshold for absolute water backscatter")
    threshold_source: str = "configurable_heuristic"


class EarthObservationRunRequest(BaseModel):
    datasets: List[Literal["sentinel1", "jrc_water", "gpm_imerg"]] = Field(default=["sentinel1", "jrc_water", "gpm_imerg"])
    event_date: str = Field(..., description="Event reference date formatted as YYYY-MM-DD")
    pre_event_window_days: int = Field(default=30, ge=7, le=90)
    post_event_window_days: int = Field(default=7, ge=1, le=30)
    rainfall_start_date: Optional[str] = Field(default=None, description="Optional custom start date for rainfall (YYYY-MM-DD)")
    rainfall_end_date: Optional[str] = Field(default=None, description="Optional custom end date for rainfall (YYYY-MM-DD)")
    aoi_buffer_meters: float = Field(default=1000.0, ge=0.0, le=10000.0)
    s1_params: Optional[Sentinel1ProcessingParams] = None


class RainfallTimeSeriesPoint(BaseModel):
    timestamp: str
    precipitation_mm_hr: float
    accumulated_precipitation_mm: float


class EarthObservationRunResponse(BaseModel):
    eo_run_id: str
    project_id: str
    status: Literal[
        "queued",
        "retrieving",
        "processing",
        "completed",
        "failed",
        "dry_run_unauthenticated",
        "gee_unavailable",
        "authentication_required",
        "project_not_configured",
        "no_imagery_available",
    ]
    created_at: str
    completed_at: Optional[str] = None
    aoi_bounds: Tuple[float, float, float, float]
    aoi_area_km2: float
    requested_datasets: List[str]
    layers: Dict[str, Any] = {}
    candidate_inundation_area_km2: Optional[float] = None
    permanent_water_area_km2: Optional[float] = None
    rainfall_accumulation_mm: Optional[float] = None
    rainfall_time_series: List[RainfallTimeSeriesPoint] = []
    provenance: Dict[str, Any] = {}
    scientific_disclaimer: str = (
        "EARTH OBSERVATION DISCLAIMER: Satellite-derived layers represent observational context "
        "and candidate water-change observations. They are subject to radar speckle, cloud gaps, "
        "and temporal revisit intervals. They do NOT constitute ground-truth validation of dam failure."
    )
    message: str = ""


class ModelObservationComparisonRequest(BaseModel):
    anuga_run_id: str
    eo_run_id: str
    depth_threshold_m: float = Field(default=0.10, ge=0.0, le=5.0, description="Minimum ANUGA inundation depth to consider flooded")
    jrc_permanent_threshold_pct: float = Field(default=80.0, ge=0.0, le=100.0, description="Threshold above which historical JRC water is considered permanent")
    max_observation_time_delta_hours: float = Field(default=72.0, ge=1.0, le=720.0, description="Configurable maximum allowed time offset between event and observation")


class TemporalValidityMetadata(BaseModel):
    comparison_valid: bool
    event_reference_time: str
    satellite_acquisition_time: str
    absolute_delta_hours: float
    configured_tolerance_hours: float
    warning: Optional[str] = None


class ModelObservationComparisonResponse(BaseModel):
    comparison_id: str
    project_id: str
    anuga_run_id: str
    eo_run_id: str
    created_at: str
    model_inundated_area_km2: float
    satellite_candidate_area_km2: float
    overlap_area_km2: float
    model_only_area_km2: float
    satellite_only_area_km2: float
    union_area_km2: float
    spatial_agreement_iou: float = Field(..., description="Intersection over Union (IoU / Jaccard Index)")
    temporal_validity: TemporalValidityMetadata
    label: str = "model-observation spatial agreement"
    provenance: Dict[str, Any] = {}
    scientific_caveats: List[str] = [
        "Satellite-derived inundation is observational evidence with classification, timing, resolution, vegetation, radar-shadow, and permanent-water uncertainties.",
        "Model-observation spatial agreement (IoU) measures spatial concordance, NOT hydraulic solver accuracy.",
        "Unobserved flood peaks occurring between satellite overpasses cannot be captured by remote sensing.",
    ]



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


# ==============================================================================
# Dam Project Onboarding & Validation Schemas (SIH PS 26161)
# ==============================================================================

class RasterDerivedMetadata(BaseModel):
    width: int
    height: int
    band_count: int
    dtype: str
    crs: str
    bounds: RasterBounds
    resolution: RasterResolution
    nodata: Optional[float] = None
    min_elevation: Optional[float] = None
    max_elevation: Optional[float] = None
    mean_elevation: Optional[float] = None
    valid_pixel_count: Optional[int] = None
    nodata_pixel_count: Optional[int] = None
    file_sha256: Optional[str] = None
    vertical_unit_in_header: str = "unknown"
    vertical_datum_in_header: str = "unknown"


class DamPointMetadata(BaseModel):
    dam_name: Optional[str] = None
    longitude: float
    latitude: float
    crs_x: Optional[float] = None
    crs_y: Optional[float] = None
    sampled_elevation: Optional[float] = None
    elevation_at_point: Optional[float] = None
    sampled_from_dem: bool = True
    is_nodata: bool = False


class EngineeringParameters(BaseModel):
    scenario_type: Literal["DAM_BREAK", "RIVER_BLOCKAGE"] = "DAM_BREAK"
    scenario_label: Optional[str] = None
    barrier_type: Optional[str] = None
    is_intact_control: Optional[bool] = False
    dam_height: Optional[float] = None
    crest_elevation: Optional[float] = None
    pool_elevation: Optional[float] = None
    reservoir_level: Optional[float] = None
    freeboard: Optional[float] = None
    breach_width: Optional[float] = None
    breach_formation_time_hr: Optional[float] = None
    manning_n: Optional[float] = None
    simulation_duration_s: Optional[float] = None
    blockage_height: Optional[float] = None
    blockage_crest_elevation: Optional[float] = None
    blockage_width: Optional[float] = None
    upstream_water_level: Optional[float] = None
    opening_width: Optional[float] = None


class UserProvidedMetadata(BaseModel):
    project_name: str
    scenario_type: Literal["DAM_BREAK", "RIVER_BLOCKAGE"] = "DAM_BREAK"
    scenario_label: Optional[str] = None
    barrier_type: Optional[str] = None
    is_intact_control: Optional[bool] = False
    dam_name: Optional[str] = None
    vertical_unit: Optional[str] = None
    vertical_datum: Optional[str] = None
    reservoir_level: Optional[float] = None
    breach_width: Optional[float] = None
    breach_center: Optional[Tuple[float, float]] = None
    breach_formation_time_hr: Optional[float] = None
    manning_roughness: Optional[float] = None
    dam_crest_elevation: Optional[float] = None
    dam_height: Optional[float] = None
    dam_latitude: Optional[float] = None
    dam_longitude: Optional[float] = None
    breach_invert_elevation: Optional[float] = None
    blockage_height: Optional[float] = None
    blockage_crest_elevation: Optional[float] = None
    blockage_width: Optional[float] = None
    upstream_water_level: Optional[float] = None
    opening_width: Optional[float] = None
    target_mesh_resolution_m: Optional[float] = None
    simulation_duration_s: Optional[float] = None
    output_interval_s: Optional[float] = None
    geometry_crs: str = "EPSG:4326"


class GeometryValidationMetadata(BaseModel):
    layer_name: str
    feature_count: int
    geometry_types: List[str]
    is_valid: bool
    intersects_dem_bounds: bool
    fully_within_dem_bounds: bool
    centroid_coords: Optional[Tuple[float, float]] = None


class NormalizedProjectMetadata(BaseModel):
    project_name: str
    scenario_type: Literal["DAM_BREAK", "RIVER_BLOCKAGE"] = "DAM_BREAK"
    scenario_label: Optional[str] = "Dam Break Scenario"
    barrier_type: Optional[str] = "engineered_dam"
    is_intact_control: Optional[bool] = False
    dam_name: Optional[str] = None
    raster_metadata: Optional[RasterDerivedMetadata] = None
    user_provided_metadata: Optional[UserProvidedMetadata] = None
    dam_point: Optional[DamPointMetadata] = None
    engineering_parameters: Optional[EngineeringParameters] = None
    dam_axis_metadata: Optional[GeometryValidationMetadata] = None
    reservoir_metadata: Optional[GeometryValidationMetadata] = None
    model_domain_metadata: Optional[GeometryValidationMetadata] = None
    downstream_outlet_metadata: Optional[GeometryValidationMetadata] = None
    breach_on_dam_axis: bool = False
    breach_distance_to_axis_m: Optional[float] = None
    distance_calculation_crs: Optional[str] = None
    scientific_status: str = "validated_unverified"


class DamProjectValidationResponse(BaseModel):
    valid: bool
    project_name: str
    scenario_type: Literal["DAM_BREAK", "RIVER_BLOCKAGE"] = "DAM_BREAK"
    scenario_label: Optional[str] = "Dam Break Scenario"
    barrier_type: Optional[str] = "engineered_dam"
    dam_name: Optional[str] = None
    errors: List[str]
    warnings: List[str]
    normalized_metadata: Optional[NormalizedProjectMetadata] = None
    dam_point: Optional[DamPointMetadata] = None
    sampled_dam_elevation: Optional[float] = None
    assumptions_requiring_confirmation: List[str]
    metadata_declared: bool
    onboarding_validation_passed: bool
    scientific_status: str = "validated_unverified"
    scientifically_verified: bool = False


class DamProjectSummary(BaseModel):
    project_id: str
    project_name: str
    scenario_type: Literal["DAM_BREAK", "RIVER_BLOCKAGE"] = "DAM_BREAK"
    scenario_label: Optional[str] = "Dam Break Scenario"
    barrier_type: Optional[str] = "engineered_dam"
    is_intact_control: Optional[bool] = False
    dam_name: Optional[str] = None
    status: str = "validated_unverified"
    scientific_status: str = "validated_unverified"
    available: bool = True
    integrity_status: str = "integrity_ok"
    integrity_error: Optional[str] = None
    created_at: str
    crs: str
    bounds: RasterBounds
    resolution: RasterResolution
    has_reservoir_boundary: bool
    has_model_domain: bool = False
    has_downstream_outlet: bool = False
    dam_point: Optional[DamPointMetadata] = None
    metadata_declared: bool
    onboarding_validation_passed: bool
    scientifically_verified: bool = False
    manifest_sha256: str
    provenance: Optional[Union[Dict[str, Any], str]] = None
    notes: List[str] = []


class DamProjectDetailResponse(BaseModel):
    project_id: str
    project_name: str
    scenario_type: Literal["DAM_BREAK", "RIVER_BLOCKAGE"] = "DAM_BREAK"
    scenario_label: Optional[str] = "Dam Break Scenario"
    barrier_type: Optional[str] = "engineered_dam"
    is_intact_control: Optional[bool] = False
    dam_name: Optional[str] = None
    status: str = "validated_unverified"
    scientific_status: str = "validated_unverified"
    created_at: str
    updated_at: Optional[str] = None
    dem_file: str
    dam_axis_file: Optional[str] = None
    original_dem_filename: Optional[str] = "dem.tif"
    safe_internal_dem_path: Optional[str] = "dem.tif"
    dem_sha256: Optional[str] = None
    reservoir_boundary_file: Optional[str] = None
    model_domain_file: Optional[str] = None
    downstream_outlet_file: Optional[str] = None
    raster_metadata: RasterDerivedMetadata
    user_provided_metadata: UserProvidedMetadata
    dam_point: Optional[DamPointMetadata] = None
    engineering_parameters: Optional[EngineeringParameters] = None
    dam_axis_metadata: Optional[GeometryValidationMetadata] = None
    reservoir_metadata: Optional[GeometryValidationMetadata] = None
    model_domain_metadata: Optional[GeometryValidationMetadata] = None
    downstream_outlet_metadata: Optional[GeometryValidationMetadata] = None
    breach_parameters: Optional[Dict[str, Any]] = None
    simulation_parameters: Optional[Dict[str, Any]] = None
    anuga_package_built: bool = False
    manifest: Dict[str, Any]
    provenance: Optional[Union[Dict[str, Any], str]] = None
    assumptions_requiring_confirmation: List[str] = []
    metadata_declared: bool = False
    onboarding_validation_passed: bool = True
    scientifically_verified: bool = False
    warnings: List[str] = []


class DamProjectReadinessResponse(BaseModel):
    project_id: str
    project_name: str
    dam_name: Optional[str] = None
    dem_valid: bool = True
    dam_location_valid: bool = True
    dam_elevation_available: bool = True
    engineering_parameters_complete: bool = False
    anuga_ready: bool = False
    has_dem: bool = True
    has_dam_point: bool = True
    has_engineering_parameters: bool = False
    has_dam_axis: bool = False
    has_reservoir_boundary: bool = False
    has_model_domain: bool = False
    has_downstream_outlet: bool = False
    ready_for_screening: bool = True
    ready_for_anuga_simulation: bool = False
    # Phase 19: 5-tier simulation readiness model
    data_ready: bool = False
    geometry_ready: bool = False
    hydraulic_ready: bool = False
    solver_ready: bool = False
    simulation_ready: bool = False
    tier_breakdown: Dict[str, Dict[str, Any]] = {}
    missing_requirements: List[str] = []
    missing_for_anuga: List[str] = []
    recommended_next_steps: List[str] = []
    scientific_status: str = "validated_unverified"
    scientifically_verified: bool = False
    sampled_elevation: Optional[float] = None
    dam_point: Optional[DamPointMetadata] = None
    engineering_parameters: Optional[EngineeringParameters] = None
    disclaimer: str = (
        "Input data validated. Scientific model verification has not yet been performed."
    )


class DamProjectAnugaPreflightResponse(BaseModel):
    project_id: str
    project_name: str
    preflight_passed: bool
    blockers: List[str] = []
    warnings: List[str] = []
    derived_checks: Dict[str, Any] = {}
    proposed_configuration: Dict[str, Any] = {}
    scientific_status: str = "hypothetical_unverified"


class DamProjectAnugaPackageResponse(BaseModel):
    project_id: str
    project_name: str
    package_filename: str
    package_size_bytes: int
    package_sha256: str
    created_at: str
    files_included: List[str] = []
    scientific_status: str = "hypothetical_unverified"
    simulation_executed: bool = False
    message: str = "Package generated; simulation has not been executed."


class DamProjectAnugaCapabilitiesResponse(BaseModel):
    execution_enabled: bool
    anuga_installed: bool
    anuga_environment_available: bool = False
    python_executable_path: Optional[str] = None
    anuga_import_success: bool = False
    anuga_version: str
    version_source: Literal["importlib_metadata", "conda_meta", "fallback_runtime", "unavailable"] = "unavailable"
    raw_distribution_version: Optional[str] = None
    python_executable_configured: bool
    reason: Optional[str] = None
    disclaimer: str = (
        "Custom ANUGA execution runs uncalibrated hypothetical simulation scenarios. "
        "It is not an official forecast or certified flood safety prediction."
    )


class HeuristicAssistRequest(BaseModel):
    search_radius_cells: int = Field(50, ge=10, le=500, description="Pixel search radius for local slope aspect analysis")
    downstream_length_m: float = Field(5000.0, ge=500.0, le=50000.0, description="Approximate downstream corridor extent in meters")
    corridor_width_m: float = Field(1000.0, ge=100.0, le=10000.0, description="Approximate downstream corridor width in meters")
    dam_crest_length_m: float = Field(500.0, ge=50.0, le=5000.0, description="Approximate dam axis length in meters")


class HeuristicAssistResponse(BaseModel):
    project_id: str
    downstream_bearing_deg: float
    downstream_direction: str
    slope_gradient: float
    dam_point_elevation: Optional[float] = None
    estimated_crest_elevation: Optional[float] = None
    suggested_dam_axis: Dict[str, Any]
    suggested_breach_line: Dict[str, Any]
    suggested_model_domain: Dict[str, Any]
    suggested_outlet_boundary: Dict[str, Any]
    suggested_reservoir_boundary: Dict[str, Any]
    source: Literal["terrain_heuristic"] = "terrain_heuristic"
    scientifically_verified: bool = False
    confidence: str = "low_unverified"
    caveats: List[str] = [
        "Terrain heuristic estimate derived solely from surface DEM gradient.",
        "Does not reflect bathymetric soundings, true structural dam crest alignment, or surveyed channel cross-sections.",
        "Requires explicit user review and confirmation before use in hydrodynamic simulations."
    ]


class SimulationInputsUpdateRequest(BaseModel):
    scenario_type: Optional[Literal["DAM_BREAK", "RIVER_BLOCKAGE"]] = None
    is_intact_control: Optional[bool] = False
    reservoir_level: Optional[float] = None
    dam_crest_elevation: Optional[float] = None
    dam_height: Optional[float] = None
    breach_width: Optional[float] = None
    breach_invert_elevation: Optional[float] = None
    breach_formation_time_hr: Optional[float] = None
    blockage_height: Optional[float] = None
    blockage_crest_elevation: Optional[float] = None
    blockage_width: Optional[float] = None
    upstream_water_level: Optional[float] = None
    opening_width: Optional[float] = None
    manning_roughness: Optional[float] = None
    simulation_duration_s: Optional[float] = None
    output_interval_s: Optional[float] = None
    target_mesh_resolution_m: Optional[float] = None
    dam_axis_geometry: Optional[Dict[str, Any]] = None
    reservoir_geometry: Optional[Dict[str, Any]] = None
    model_domain_geometry: Optional[Dict[str, Any]] = None
    downstream_outlet_geometry: Optional[Dict[str, Any]] = None
    accept_heuristic_inputs: bool = False
    custom_notes: Optional[str] = None


class DemoInputsRequest(BaseModel):
    scenario_type: Optional[Literal["DAM_BREAK", "RIVER_BLOCKAGE"]] = "DAM_BREAK"
    is_intact_control: Optional[bool] = False
    corridor_length_m: Optional[float] = Field(default=2500.0, ge=500.0, le=20000.0, description="Approximate downstream corridor extent in meters")
    corridor_width_m: Optional[float] = Field(default=1000.0, ge=200.0, le=5000.0, description="Approximate model domain corridor width in meters")
    dam_axis_length_m: Optional[float] = Field(default=400.0, ge=50.0, le=2000.0, description="Approximate demo dam axis length in meters")
    reservoir_extent_m: Optional[float] = Field(default=700.0, ge=100.0, le=5000.0, description="Approximate demo reservoir upstream extent in meters")
    dam_height_m: Optional[float] = Field(default=25.0, ge=5.0, le=200.0, description="Hypothetical structural dam height in meters")
    freeboard_m: Optional[float] = Field(default=5.0, ge=0.5, le=30.0, description="Hypothetical freeboard (crest minus normal pool) in meters")
    manning_n: Optional[float] = Field(default=0.035, ge=0.01, le=0.2, description="Channel roughness Manning's n")
    simulation_duration_s: Optional[float] = Field(default=3600.0, ge=60.0, le=86400.0, description="Simulation duration in seconds")
    accept_hypothetical: bool = Field(default=True, description="Acknowledgment that inputs are synthetic demo approximations")


class DemoInputsGeometryItem(BaseModel):
    name: str
    geometry_type: str
    feature_count: int = 1
    crs: str = "EPSG:4326"
    is_valid: bool = True
    contained_in_dem: bool = True
    summary: str


class DemoInputsResponse(BaseModel):
    project_id: str
    project_name: str
    scenario_type: Literal["DAM_BREAK", "RIVER_BLOCKAGE"] = "DAM_BREAK"
    scenario_label: Optional[str] = "Dam Break Scenario"
    barrier_type: Optional[str] = "engineered_dam"
    is_intact_control: Optional[bool] = False
    dam_name: Optional[str] = None
    provenance: Literal["HYPOTHETICAL_UNVERIFIED"] = "HYPOTHETICAL_UNVERIFIED"
    scientifically_verified: bool = False
    dam_point_elevation: float
    dam_crest_elevation: float
    reservoir_level: float
    dam_height: float
    breach_invert_elevation: float
    freeboard_m: float
    manning_roughness: float
    simulation_duration_s: float
    geometry_crs: str = "EPSG:4326"
    geometries: Dict[str, DemoInputsGeometryItem]
    readiness: DamProjectReadinessResponse
    disclaimer: str = (
        "HYPOTHETICAL / UNVERIFIED DEMO INPUTS: Geometries (model domain, dam crest axis, reservoir boundary) "
        "and hydraulic parameters are synthesized from DEM terrain for exploratory pipeline validation only. "
        "They do NOT represent certified real-world engineering conclusions."
    )


class DamProjectAnugaRunRequest(BaseModel):
    acknowledge_hypothetical_unverified: bool = False
    scenario_type: Optional[Literal["DAM_BREAK", "RIVER_BLOCKAGE"]] = None
    is_intact_control: Optional[bool] = None
    opening_width: Optional[float] = None
    custom_notes: Optional[str] = None
    simulation_duration_s: Optional[float] = None
    output_interval_s: Optional[float] = None
    target_mesh_resolution_m: Optional[float] = None
    custom_notes: Optional[str] = None
    simulation_duration_s: Optional[float] = None
    output_interval_s: Optional[float] = None
    target_mesh_resolution_m: Optional[float] = None


class DamProjectAnugaRunResponse(BaseModel):
    run_id: str
    project_id: str
    project_name: str
    package_sha256: str
    status: Literal["queued", "preparing", "running", "postprocessing", "completed", "failed", "cancelled", "timed_out", "interrupted"] = Field(
        ..., description="queued, preparing, running, postprocessing, completed, failed, cancelled, timed_out, interrupted"
    )
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    exit_code: Optional[int] = None
    anuga_version: Optional[str] = None
    version_source: Optional[Literal["importlib_metadata", "conda_meta", "fallback_runtime", "unavailable"]] = None
    raw_distribution_version: Optional[str] = None
    runtime_seconds: Optional[float] = None
    log_file: Optional[str] = None
    output_files: Dict[str, str] = {}
    parameters_snapshot: Dict[str, Any] = {}
    run_manifest_sha256: Optional[str] = None
    scientific_status: str = "hypothetical_unverified"
    simulation_executed: bool = False
    has_results: bool = False
    message: str


class DamProjectAnugaOutputsResponse(BaseModel):
    project_id: str
    run_id: str
    status: str
    sww_file: Optional[str] = None
    sww_size_bytes: Optional[int] = None
    sww_sha256: Optional[str] = None
    output_files: Dict[str, str] = {}
    has_results: bool = False
    available_layers: List[str] = []
    layer_statistics: Dict[str, Any] = {}
    runtime_seconds: Optional[float] = None
    scientific_status: str = "hypothetical_unverified"
    simulation_executed: bool = False
    message: str = ""


class DamProjectAnugaPostprocessRequest(BaseModel):
    dry_depth_threshold_m: float = Field(0.005, gt=0.0, le=1.0, description="Minimum depth in meters below which velocity is zeroed")
    arrival_depth_threshold_m: float = Field(0.05, gt=0.0, le=10.0, description="Water depth threshold in meters for arrival detection")
    raster_resolution_m: Optional[float] = Field(None, gt=0.0001, le=500.0, description="Optional target grid resolution in meters")


class DamProjectAnugaLayerStats(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None
    mean: Optional[float] = None
    valid_pixels: int
    nodata_pixels: int
    total_pixels: int
    unit: str


class DamProjectAnugaResultsResponse(BaseModel):
    project_id: str
    run_id: str
    processing_id: str
    created_at: str
    sww_sha256: str
    package_sha256: str
    processing_identity_sha256: str
    available_layers: List[str]
    layer_files: Dict[str, str]
    layer_statistics: Dict[str, DamProjectAnugaLayerStats]
    formulas: Dict[str, str]
    thresholds: Dict[str, float]
    actual_sww_timesteps: List[float]
    interpolation_method: str
    mesh_mask_method: str
    raster_crs: str
    raster_resolution_m: float
    grid_dimensions: Tuple[int, int]
    anuga_version: str
    version_source: str
    raw_distribution_version: Optional[str] = None
    scientific_status: str = "hypothetical_unverified"
    simulation_executed: bool = True
    mass_balance_status: str = "not_assessed"
    disclaimer: str = (
        "Derived raster visualization product from uncalibrated ANUGA hydrodynamic simulation. "
        "Not certified flood forecasting or official inundation mapping."
    )
    message: str


class DamProjectAnugaPointValueResponse(BaseModel):
    project_id: str
    run_id: str
    layer: str
    lon: float
    lat: float
    crs_x: Optional[float] = None
    crs_y: Optional[float] = None
    crs: str
    value: Optional[float] = None
    unit: str
    value_type: str = "derived_raster_value"
    description: str = "Interpolated derived model value from ANUGA simulation raster"
    is_valid: bool
    is_nodata: bool
    disclaimer: str = "Derived raster visualization value — not an exact certified solver prediction."


# Phase 21: Multi-Engine Spatial Hydrodynamic Comparison Schemas

class ModelComparisonEngineCapability(BaseModel):
    environment_available: bool = Field(..., description="Whether the required software environment/libraries exist")
    solver_available: bool = Field(..., description="Whether the actual solver binary/engine executable is discovered")
    completed_run_count: int = Field(default=0, description="Total completed runs in disk storage")
    comparable_run_count: int = Field(default=0, description="Runs with verified output rasters ready for comparison")
    available_for_comparison: bool = Field(..., description="True only if comparable_run_count > 0")
    version: Optional[str] = None
    reason: Optional[str] = None


class ModelComparisonCapabilitiesResponse(BaseModel):
    project_id: str
    engines: Dict[str, ModelComparisonEngineCapability]
    completed_runs_by_engine: Dict[str, List[Dict[str, Any]]]
    ready_for_comparison: bool = Field(..., description="True if at least 2 distinct comparable runs or engines exist")
    message: str


class SPHParticleInterpolationParams(BaseModel):
    particle_spacing_m: Optional[float] = Field(default=None, ge=0.001, le=100.0)
    smoothing_length_m: Optional[float] = Field(default=None, ge=0.001, le=200.0)
    target_resolution_m: float = Field(default=10.0, ge=1.0, le=100.0)
    interpolation_method: Literal["idw", "sph_cubic_spline", "sph_wendland_c2", "nearest"] = "idw"
    support_radius_factor: float = Field(default=2.0, ge=1.0, le=5.0)
    power_parameter: float = Field(default=2.0, ge=1.0, le=4.0)


class SPHRunImportRequest(BaseModel):
    run_label: Optional[str] = "Imported SPH Run"
    notes: Optional[str] = ""
    target_crs: Optional[str] = "EPSG:32643"
    particle_params: Optional[SPHParticleInterpolationParams] = None
    scientific_status: str = "imported_external_run"


class Delft3DRunImportRequest(BaseModel):
    run_label: Optional[str] = "Imported Delft3D Run"
    notes: Optional[str] = ""
    target_crs: Optional[str] = None
    scientific_status: str = "imported_external_run"


class ProjectDelft3DPackageResponse(BaseModel):
    project_id: str
    package_filename: str
    package_size_bytes: int
    created_at: str
    manifest_checksum: str
    download_url: str
    dflowfm_available: bool
    execution_enabled: bool
    notes: List[str]


class ProjectSPHPackageResponse(BaseModel):
    project_id: str
    package_filename: str
    package_size_bytes: int
    created_at: str
    manifest_checksum: str
    download_url: str
    pysph_available: bool
    execution_enabled: bool
    notes: List[str]


class HydrodynamicOutputContract(BaseModel):
    engine: str = Field(..., description="Solver engine name, e.g. anuga, delft3d_fm, pysph")
    engine_version: Optional[str] = None
    source_run_id: str
    run_id: Optional[str] = None
    project_id: Optional[str] = None
    run_timestamp: Optional[str] = None
    simulation_duration_s: Optional[float] = None
    native_crs: str
    native_resolution_m: Optional[float] = None
    analysis_crs: str
    analysis_resolution_m: Optional[float] = None
    bounds: Tuple[float, float, float, float] = Field(..., description="(west, south, east, north) in analysis_crs")
    nodata_value: float = -9999.0
    maximum_depth_available: bool = False
    maximum_velocity_available: bool = False
    arrival_time_available: bool = False
    inundation_extent_available: bool = False
    arrival_time_definition: Optional[str] = None
    source_output_files: List[str] = []
    source_file_hashes: Dict[str, str] = {}
    layer_paths: Dict[str, str] = {}
    provenance: Dict[str, Any] = {}
    scientific_status: str = "hypothetical_unverified"
    solver_execution_status: str = "completed"


class ToleranceBandCoverage(BaseModel):
    band_label: str
    tolerance_m: float
    pixel_count: int
    area_km2: float
    percentage_of_common_valid_area: float


class DepthDifferenceStats(BaseModel):
    common_valid_pixel_count: int
    common_analysis_area_km2: float
    mean_signed_difference_m: float
    median_signed_difference_m: float
    mae_m: float
    rmse_m: float
    max_positive_difference_m: float = Field(..., description="Max where Engine A > Engine B")
    max_negative_difference_m: float = Field(..., description="Max where Engine A < Engine B")
    tolerance_bands: List[ToleranceBandCoverage]
    label: str = "inter-model depth difference"
    formula: str = "engine_A_depth - engine_B_depth"


class VelocityDifferenceStats(BaseModel):
    available: bool
    common_valid_pixel_count: Optional[int] = None
    common_analysis_area_km2: Optional[float] = None
    mean_signed_difference_m_s: Optional[float] = None
    mae_m_s: Optional[float] = None
    rmse_m_s: Optional[float] = None
    max_difference_m_s: Optional[float] = None
    reason_if_unavailable: Optional[str] = None
    label: str = "inter-model velocity difference"


class InundationAgreementStats(BaseModel):
    depth_threshold_m: float
    model_a_inundated_area_km2: float
    model_b_inundated_area_km2: float
    overlap_area_km2: float
    model_a_only_area_km2: float
    model_b_only_area_km2: float
    union_area_km2: float
    spatial_agreement_iou: float
    label: str = "inter-model spatial agreement"
    disclaimer: str = (
        "Neither model is ground truth. Inundation agreement reflects spatial overlap of simulated footprints."
    )


class ArrivalTimeDifferenceStats(BaseModel):
    available: bool
    comparison_valid: bool
    threshold_definition_a: Optional[str] = None
    threshold_definition_b: Optional[str] = None
    mean_absolute_difference_s: Optional[float] = None
    median_difference_s: Optional[float] = None
    rmse_s: Optional[float] = None
    early_zone_area_km2: Optional[float] = None
    late_zone_area_km2: Optional[float] = None
    invalidation_reason: Optional[str] = None
    label: str = "inter-model arrival-time comparison"


class InterModelSpreadDiagnostic(BaseModel):
    computed: bool
    model_count: int
    mean_depth_mean_m: Optional[float] = None
    min_depth_mean_m: Optional[float] = None
    max_depth_mean_m: Optional[float] = None
    mean_spread_m: Optional[float] = None
    max_spread_m: Optional[float] = None
    common_coverage_area_km2: Optional[float] = None
    label: str = "inter-model spread"
    disclaimer: str = (
        "Diagnostic inter-model spread (max - min). Not a calibrated uncertainty quantification or confidence interval."
    )


class ModelComparisonRunRequest(BaseModel):
    engine_a: str = Field(..., description="Engine A identifier, e.g. anuga")
    run_id_a: str = Field(..., description="Run ID A")
    engine_b: str = Field(..., description="Engine B identifier, e.g. anuga, delft3d_fm, pysph")
    run_id_b: str = Field(..., description="Run ID B")
    additional_models: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Optional list of {'engine': str, 'run_id': str} for 3+ model ensemble spread",
    )
    depth_inundation_threshold_m: float = Field(default=0.10, ge=0.01, le=5.0)
    tolerance_bands_m: List[float] = Field(default=[0.10, 0.25, 0.50])
    target_crs: Optional[str] = Field(default=None, description="Optional target projected metric CRS, e.g. EPSG:32643")
    synthetic_test_fixture: Optional[bool] = Field(
        default=False,
        description="Explicit test-only fixture flag for offline unit testing without real engine assets",
    )


class ModelComparisonRunResponse(BaseModel):
    comparison_id: str
    project_id: str
    status: Literal["completed", "failed", "unavailable"]
    created_at: str
    engine_a: str
    run_id_a: str
    engine_b: str
    run_id_b: str
    contract_a: HydrodynamicOutputContract
    contract_b: HydrodynamicOutputContract
    analysis_crs: str
    analysis_resolution_m: float
    depth_difference: DepthDifferenceStats
    velocity_difference: VelocityDifferenceStats
    inundation_agreement: InundationAgreementStats
    arrival_time_difference: ArrivalTimeDifferenceStats
    ensemble_spread: Optional[InterModelSpreadDiagnostic] = None
    layer_files: Dict[str, str] = {}
    provenance: Dict[str, Any] = {}
    scientific_caveats: List[str]
    message: str = ""


# Phase 28: SPH vs ANUGA Comparison Specialization Schemas

class ScenarioCompatibilityItem(BaseModel):
    parameter_name: str
    sph_value: str
    anuga_value: str
    classification: Literal["SAME", "SIMILAR", "DIFFERENT", "NOT_APPLICABLE"]
    scientific_explanation: str


class SolverRoleProfile(BaseModel):
    solver_name: str
    solver_type: str
    numerical_formulation: str
    spatial_focus: str
    best_represented_for: List[str]
    limitations: List[str]


class PercentileMetrics(BaseModel):
    p50: float
    p90: float
    p95: float
    p99: float
    max: float
    unit: str = "m"
    location_description: Optional[str] = None


class SolverMetricSummary(BaseModel):
    solver_key: str
    solver_name: str
    solver_type: str
    run_id: str
    status: str = "completed"
    simulation_duration_s: float
    wall_clock_runtime_s: float
    time_ratio: Optional[float] = None
    domain_area_km2: float
    downstream_extent_m: float
    inundated_area_km2: float
    spatial_resolution_m: float
    discrete_element_count: int
    discrete_element_type: str  # "particles" or "mesh triangles"
    first_downstream_arrival_s: float
    arrival_threshold_m: float
    depth_percentiles: PercentileMetrics
    velocity_percentiles: PercentileMetrics
    output_type: str


class TimeSyncStep(BaseModel):
    simulation_time_s: float
    sph_frame_index: int
    sph_frame_time_s: float
    anuga_timestep_index: int
    anuga_timestep_time_s: float
    status: str = "synchronized"


class SPHvsANUGAComparisonResponse(BaseModel):
    project_id: str
    project_name: str
    sph_run_id: str
    anuga_run_id: str
    same_project: bool = True
    disclaimers: List[str]
    judge_30s_explanation: str
    solver_roles: Dict[str, SolverRoleProfile]
    scenario_compatibility: List[ScenarioCompatibilityItem]
    sph_metrics: SolverMetricSummary
    anuga_metrics: SolverMetricSummary
    spatial_comparison: InundationAgreementStats
    depth_comparison: DepthDifferenceStats
    velocity_comparison: VelocityDifferenceStats
    arrival_comparison: ArrivalTimeDifferenceStats
    factual_insights: List[str]
    time_sync_map: List[TimeSyncStep] = []
    layer_tiles: Dict[str, str] = {}
    created_at: str



# Phase 22: Exposure & Vulnerability Assessment Schemas

class ExposureDepthBandConfig(BaseModel):
    name: str
    min_depth: float
    max_depth: Optional[float] = None


class PopulationExposureSummary(BaseModel):
    available: bool = False
    status: str = "not_provided"  # available, not_provided, error, unsupported_unit
    reason_if_unavailable: Optional[str] = None
    population_source: Optional[str] = None
    population_unit: Optional[str] = None  # count_per_cell, persons_per_km2, etc.
    native_resolution: Optional[float] = None
    native_crs: Optional[str] = None
    analysis_crs: Optional[str] = None
    resampling_or_aggregation_method: Optional[str] = None
    count_conservation_method: Optional[str] = None
    total_population_in_aoi: Optional[float] = None
    population_in_inundation_extent: Optional[float] = None
    population_percentage_exposed: Optional[float] = None
    population_by_depth_band: Dict[str, float] = {}
    population_by_arrival_window: Dict[str, float] = {}


class BuildingExposureSummary(BaseModel):
    available: bool = False
    status: str = "not_provided"
    reason_if_unavailable: Optional[str] = None
    source_dataset: Optional[str] = None
    total_buildings: int = 0
    buildings_exposed: int = 0
    buildings_exposed_percentage: float = 0.0
    building_footprint_area_exposed_m2: float = 0.0
    building_footprint_area_exposed_km2: float = 0.0
    buildings_by_depth_band: Dict[str, int] = {}
    buildings_by_usage: Dict[str, int] = {}  # residential, commercial, industrial, public, unknown
    sampling_method: str = "polygon_zonal_overlay_with_fallback"


class RoadExposureSummary(BaseModel):
    available: bool = False
    status: str = "not_provided"
    reason_if_unavailable: Optional[str] = None
    source_dataset: Optional[str] = None
    total_road_length_km: float = 0.0
    affected_road_length_km: float = 0.0
    affected_percentage: float = 0.0
    max_depth_m: Optional[float] = None
    mean_depth_m: Optional[float] = None
    road_length_by_depth_band_km: Dict[str, float] = {}
    road_class_breakdown_km: Dict[str, Dict[str, float]] = {}  # class -> {total_km, affected_km}
    road_passability_available: bool = False
    passability_rule_note: str = (
        "Road passability rule not configured. Flooded segments are reported as potentially affected road segments only."
    )


class CriticalAssetItem(BaseModel):
    asset_id: str
    name: Optional[str] = None
    source_category: str
    normalized_category: str  # hospital, school, police, fire_station, power_substation, water_facility, bridge, evacuation_shelter, unknown
    depth_m: Optional[float] = None
    velocity_mps: Optional[float] = None
    arrival_time_s: Optional[float] = None
    hazard_band: Optional[str] = None
    arrival_window: Optional[str] = None
    source_provenance: str


class CriticalInfrastructureSummary(BaseModel):
    available: bool = False
    status: str = "not_provided"
    reason_if_unavailable: Optional[str] = None
    source_dataset: Optional[str] = None
    total_critical_assets: int = 0
    exposed_critical_assets: int = 0
    exposed_by_category: Dict[str, int] = {}
    assets: List[CriticalAssetItem] = []


class LULCClassExposure(BaseModel):
    class_id: int
    class_name: str
    flooded_area_m2: float
    flooded_area_km2: float
    flooded_percentage_of_class: Optional[float] = None


class LULCExposureSummary(BaseModel):
    available: bool = False
    status: str = "not_provided"
    reason_if_unavailable: Optional[str] = None
    source_dataset: Optional[str] = None
    total_flooded_area_km2: float = 0.0
    classes: List[LULCClassExposure] = []
    resampling_method: str = "nearest_neighbour"


class VulnerabilityCurveInfo(BaseModel):
    curve_id: str
    curve_source: str
    asset_class: str
    hazard_variable: str
    units: str
    curve_provenance: str
    region_applicability: str = "Asia / Continental (uncalibrated reference)"
    curve_status: str = "unverified_reference"
    version_year: Optional[int] = 2017


class DamageEstimationSummary(BaseModel):
    vulnerability_available: bool = False
    monetary_damage_available: bool = False
    reason_if_unavailable: Optional[str] = None
    relative_damage_index: Optional[float] = None  # average relative damage ratio across exposed assets (0-1)
    monetary_damage: Optional[float] = None
    currency: Optional[str] = None
    valuation_year: Optional[int] = None
    value_source: Optional[str] = None
    methodology_note: str = (
        "Separation of exposure from vulnerability: vulnerability curves are only applied if documented and matched. "
        "Monetary loss is suppressed unless authoritative valuation exists; rupee losses are never fabricated."
    )


class DecisionSupportHotspot(BaseModel):
    hotspot_id: str
    name: str
    latitude: float
    longitude: float
    priority_score: float  # 0 - 100
    reasons: List[str]
    hazard_depth_m: float
    exposed_features: List[str]


class DecisionSupportPrioritySummary(BaseModel):
    composite_index: float  # 0 - 100
    formula: str
    weights: Dict[str, float]
    weights_label: str = "heuristic_default"
    normalization_method: str
    hotspots: List[DecisionSupportHotspot] = []
    caveat: str = (
        "Decision-support priority index is a heuristic prioritization metric for planning. "
        "It is NOT true disaster risk, casualty probability, or fatality forecast."
    )


class ExposureCapabilitiesResponse(BaseModel):
    project_id: str
    hazard_sources: List[Dict[str, Any]]
    available_exposure_datasets: Dict[str, Dict[str, Any]]
    supported_vulnerability_curves: List[VulnerabilityCurveInfo]
    default_depth_bands: List[Dict[str, Any]]
    default_arrival_windows: List[Dict[str, Any]]
    default_priority_weights: Dict[str, float]


class ExposureRunRequest(BaseModel):
    hazard_engine: str = Field(default="anuga", description="anuga, delft3d, pysph, or legacy_hidkal")
    hazard_run_id: Optional[str] = Field(default=None, description="Run ID in project storage (or None for legacy_hidkal)")
    depth_threshold_m: float = Field(default=0.10, ge=0.0, le=10.0)
    depth_bands: Optional[List[Dict[str, Any]]] = None
    arrival_windows: Optional[List[Dict[str, Any]]] = None
    population_unit_override: Optional[str] = None  # count_per_cell, persons_per_km2
    priority_weights: Optional[Dict[str, float]] = None  # custom heuristic weights
    passability_depth_threshold_m: Optional[float] = None  # only if user explicitly configures
    target_analysis_crs: Optional[str] = None
    synthetic_test_fixture: Optional[bool] = False


class ExposureRunSummary(BaseModel):
    run_id: str
    project_id: str
    hazard_engine: str
    hazard_run_id: Optional[str]
    status: Literal["completed", "failed", "partial"]
    created_at: str
    depth_threshold_m: float
    population_exposed: Optional[float] = None
    buildings_exposed: Optional[int] = None
    affected_road_length_km: Optional[float] = None
    critical_assets_exposed: Optional[int] = None
    priority_score: Optional[float] = None
    scientific_status: str


class ExposureRunDetailResponse(BaseModel):
    run_id: str
    project_id: str
    status: Literal["completed", "failed", "partial"]
    created_at: str
    hazard_contract: Dict[str, Any]
    depth_threshold_m: float
    depth_bands: List[Dict[str, Any]]
    arrival_windows: List[Dict[str, Any]]
    population: PopulationExposureSummary
    buildings: BuildingExposureSummary
    roads: RoadExposureSummary
    critical_infrastructure: CriticalInfrastructureSummary
    lulc: LULCExposureSummary
    vulnerability_and_damage: DamageEstimationSummary
    decision_support_priority: DecisionSupportPrioritySummary
    provenance: Dict[str, Any]
    scientific_caveats: List[str]
    message: str = ""


# Phase 23: System Capability & Health Schemas

class SubsystemHealth(BaseModel):
    id: str
    name: str
    status: Literal[
        "ready",
        "available_not_configured",
        "unavailable",
        "missing_data",
        "failed",
        "execution_disabled",
    ]
    status_label: str
    version: Optional[str] = None
    environment: Optional[str] = None
    details: str
    is_optional: bool = False
    scientific_caveat: Optional[str] = None


class SystemHealthSummaryResponse(BaseModel):
    overall_status: str
    timestamp: str
    subsystems: List[SubsystemHealth]


# Phase 29: Dam-Break Decision-Support Dashboard Schemas

class DecisionSupportKPIs(BaseModel):
    maximum_depth_m: float
    maximum_velocity_ms: float
    inundated_area_km2: float
    domain_inundated_pct: float
    downstream_flood_reach_km: float
    first_downstream_arrival_s: float
    first_downstream_arrival_min: float
    median_downstream_arrival_s: Optional[float] = None
    median_downstream_arrival_min: Optional[float] = None
    p90_downstream_arrival_s: Optional[float] = None
    p90_downstream_arrival_min: Optional[float] = None
    latest_modeled_arrival_s: Optional[float] = None
    latest_modeled_arrival_min: Optional[float] = None
    wet_cell_count: int
    total_domain_area_km2: float


class PercentileDistribution(BaseModel):
    p50: float
    p90: float
    p95: float
    p99: float
    max: float


class CumulativeDepthAreas(BaseModel):
    depth_gt_0_1m_km2: float
    depth_gt_0_5m_km2: float
    depth_gt_1_0m_km2: float
    depth_gt_2_0m_km2: float


class DistributionBin(BaseModel):
    range_label: str
    min_val: float
    max_val: Optional[float] = None
    area_km2: float
    percentage: float


class DownstreamZoneMetric(BaseModel):
    zone_label: str
    distance_min_m: float
    distance_max_m: Optional[float] = None
    max_depth_m: float
    max_velocity_ms: float
    earliest_arrival_s: Optional[float] = None
    earliest_arrival_min: Optional[float] = None
    inundated_area_km2: float
    mean_severity_m2s: float


class ModeledCriticalPoint(BaseModel):
    point_id: str
    title: str
    metric_name: str
    value: float
    unit: str
    coordinate_utm: List[float]
    coordinate_wgs84: List[float]
    simulation_time_s: Optional[float] = None
    description: str
    disclaimer: str = "Simulation output — Not field-observed data"


class HydraulicSeverityConfig(BaseModel):
    method: str = "depth_velocity_product"
    formula: str = "H = h * v"
    units: str = "m^2/s"
    classification_type: str = "demonstration"
    thresholds: List[Dict[str, Any]]
    disclaimer: str = "Project demonstration thresholds — not regulatory classifications."
    peak_severity_m2s: float


class DecisionSupportScenarioParameters(BaseModel):
    dam_name: str
    scenario_type: str = "DAM_BREAK"
    scenario_label: str = "Dam Break Scenario"
    barrier_type: str = "engineered_dam"
    is_intact_control: bool = False
    reservoir_level_m: float
    breach_width_m: float
    breach_type: str
    manning_roughness: float
    simulation_duration_s: float
    terrain_source: str
    solver: str
    mesh_cells: Optional[int] = None
    scientific_status: str = "HYPOTHETICAL_DEMONSTRATION"
    blockage_crest_elevation_m: Optional[float] = None
    upstream_water_level_m: Optional[float] = None
    opening_width_m: Optional[float] = None


class DecisionSupportResponse(BaseModel):
    project_id: str
    run_id: str
    solver: str = "ANUGA 2D Regional Shallow-Water Simulation"
    supplementary_solver: str = "Custom Terrain-SPH Near-Field Demonstration"
    generated_at: str
    kpis: DecisionSupportKPIs
    percentiles: Dict[str, PercentileDistribution]
    cumulative_depth_areas: CumulativeDepthAreas
    depth_distribution: List[DistributionBin]
    velocity_distribution: List[DistributionBin]
    downstream_zones: List[DownstreamZoneMetric]
    critical_points: List[ModeledCriticalPoint]
    severity_config: HydraulicSeverityConfig
    scenario: DecisionSupportScenarioParameters
    narrative_summary: str
    what_this_means: Dict[str, str]
    limitations: List[str]
    tile_endpoints: Dict[str, str]


class DemoReadinessResponse(BaseModel):
    project_id: str
    project_name: str
    is_ready: bool
    status_badge: str
    has_dem: bool
    anuga_ready: bool
    sph_ready: bool
    dashboard_ready: bool
    comparison_ready: bool
    preferred_anuga_run_id: Optional[str] = None
    preferred_sph_run_id: Optional[str] = None
    available_anuga_runs: int = 0
    available_sph_runs: int = 0
    missing_items: List[str] = []
    summary_message: str


# ==============================================================================
# Phase A1: PySPH -> Delft3D Breach Hydrograph Coupling Schemas
# ==============================================================================

class HydrographPoint(BaseModel):
    time_seconds: float = Field(..., description="Timestamp in seconds from simulation start")
    discharge_cms: float = Field(..., ge=0.0, description="Instantaneous outflow discharge in m^3/s")


class BreachHydrographResponse(BaseModel):
    source_engine: str = "pysph"
    target_engine: Optional[str] = "delft3d_fm"
    run_id: str
    project_id: Optional[str] = None
    created_at: str
    time_unit: str = "s"
    discharge_unit: str = "m3/s"
    point_count: int
    duration_seconds: float
    q_peak_cms: float
    time_to_peak_seconds: float
    total_released_volume_m3: float
    initial_reservoir_volume_m3: Optional[float] = None
    reservoir_release_fraction: Optional[float] = Field(
        None, description="Ratio of total released breach outflow volume to total initial reservoir storage volume"
    )
    mass_balance_check: str = Field(
        "not_available",
        description="Status of global mass balance verification ('verified', 'evaluated', or 'not_available')",
    )
    mass_balance_error_pct: Optional[float] = Field(
        None, description="Global numerical mass balance error percentage if evaluated"
    )
    points: List[HydrographPoint]
    metadata: Dict[str, Any] = {}


# ==============================================================================
# Phase A2: Canonical Unified Scenario Schema & Engine Translation Models
# ==============================================================================

class ScenarioType(str, Enum):
    DAM_BREAK = "DAM_BREAK"
    RIVER_BLOCKAGE = "RIVER_BLOCKAGE"
    LANDSLIDE_DAM_FAILURE = "LANDSLIDE_DAM_FAILURE"


class SimulationEngine(str, Enum):
    ANUGA = "ANUGA"
    PYSPH = "PYSPH"
    DELFT3D = "DELFT3D"
    COUPLED_SPH_DELFT3D = "COUPLED_SPH_DELFT3D"


class CanonicalScenario(BaseModel):
    scenario_id: str = Field(..., description="Unique UUID identifier for the canonical scenario")
    project_id: str = Field(..., description="Parent dam project ID or site ID")
    scenario_name: str = Field(..., min_length=1, max_length=120, description="Human-readable scenario name")
    scenario_type: ScenarioType = Field(default=ScenarioType.DAM_BREAK, description="DAM_BREAK, RIVER_BLOCKAGE, or LANDSLIDE_DAM_FAILURE")
    description: Optional[str] = Field(default=None, max_length=1000, description="Scenario description or narrative notes")

    # Terrain & Spatial Reference
    dem_dataset_id: Optional[str] = Field(default=None, description="DEM raster reference ID or filename")
    crs: str = Field(default="EPSG:4326", description="Coordinate reference system")
    dam_crest_elevation_m: Optional[float] = Field(default=None, ge=-500.0, le=9000.0, description="Dam crest / blockage crest elevation in meters")
    dam_location_lon_lat: Optional[Tuple[float, float]] = Field(default=None, description="(Longitude, Latitude) center coordinates")

    # Hydraulic & Initial Conditions
    initial_water_level_m: Optional[float] = Field(default=None, ge=0.0, le=9000.0, description="Initial reservoir / upstream water surface elevation in meters")
    reservoir_volume_m3: Optional[float] = Field(default=None, ge=0.0, description="Total initial reservoir volume in m^3")

    # Breach & Failure Parameters
    is_intact_control: bool = Field(default=False, description="True for intact baseline control scenario without failure")
    breach_width_m: float = Field(default=100.0, ge=0.0, le=5000.0, description="Breach / opening final width in meters")
    breach_depth_m: Optional[float] = Field(default=None, ge=0.0, le=500.0, description="Assumed vertical breach scour depth in meters")
    breach_start_time_s: float = Field(default=0.0, ge=0.0, description="Breach initiation timestamp in seconds")
    breach_formation_duration_s: float = Field(default=3600.0, ge=0.0, le=864000.0, description="Duration of breach opening formation in seconds")

    # Hydrodynamic Roughness & Discretization
    manning_roughness: float = Field(default=0.035, gt=0.001, le=0.5, description="Manning bed friction coefficient n")
    simulation_duration_s: float = Field(default=3600.0, gt=0.0, le=864000.0, description="Total simulation duration in seconds")
    output_interval_s: float = Field(default=60.0, gt=0.0, le=36000.0, description="Output recording interval in seconds")
    target_mesh_resolution_m: float = Field(default=50.0, ge=1.0, le=1000.0, description="Target spatial grid / mesh resolution in meters")

    # Selected Engine & Execution Parameters
    selected_engine: SimulationEngine = Field(default=SimulationEngine.ANUGA, description="Primary simulation solver")
    engine_parameters: Dict[str, Any] = Field(default_factory=dict, description="Engine-specific parameter overrides (CFL, particle count, etc.)")

    # Provenance & Traceability
    provenance: Dict[str, Any] = Field(default_factory=dict, description="Traceability metadata, timestamps, author, origin")


class CanonicalScenarioCreateRequest(BaseModel):
    project_id: str
    scenario_name: str = Field(..., min_length=1, max_length=120)
    scenario_type: ScenarioType = Field(default=ScenarioType.DAM_BREAK)
    description: Optional[str] = Field(default=None, max_length=1000)
    dem_dataset_id: Optional[str] = None
    crs: str = "EPSG:4326"
    dam_crest_elevation_m: Optional[float] = None
    dam_location_lon_lat: Optional[Tuple[float, float]] = None
    initial_water_level_m: Optional[float] = None
    reservoir_volume_m3: Optional[float] = None
    is_intact_control: bool = False
    breach_width_m: float = Field(default=100.0, ge=0.0, le=5000.0)
    breach_depth_m: Optional[float] = None
    breach_start_time_s: float = 0.0
    breach_formation_duration_s: float = 3600.0
    manning_roughness: float = Field(default=0.035, gt=0.001, le=0.5)
    simulation_duration_s: float = Field(default=3600.0, gt=0.0, le=864000.0)
    output_interval_s: float = Field(default=60.0, gt=0.0, le=36000.0)
    target_mesh_resolution_m: float = Field(default=50.0, ge=1.0, le=1000.0)
    selected_engine: SimulationEngine = Field(default=SimulationEngine.ANUGA)
    engine_parameters: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class CanonicalScenarioUpdateRequest(BaseModel):
    scenario_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    scenario_type: Optional[ScenarioType] = None
    description: Optional[str] = None
    dem_dataset_id: Optional[str] = None
    crs: Optional[str] = None
    dam_crest_elevation_m: Optional[float] = None
    dam_location_lon_lat: Optional[Tuple[float, float]] = None
    initial_water_level_m: Optional[float] = None
    reservoir_volume_m3: Optional[float] = None
    is_intact_control: Optional[bool] = None
    breach_width_m: Optional[float] = Field(default=None, ge=0.0, le=5000.0)
    breach_depth_m: Optional[float] = None
    breach_start_time_s: Optional[float] = None
    breach_formation_duration_s: Optional[float] = None
    manning_roughness: Optional[float] = Field(default=None, gt=0.001, le=0.5)
    simulation_duration_s: Optional[float] = Field(default=None, gt=0.0, le=864000.0)
    output_interval_s: Optional[float] = Field(default=None, gt=0.0, le=36000.0)
    target_mesh_resolution_m: Optional[float] = Field(default=None, ge=1.0, le=1000.0)
    selected_engine: Optional[SimulationEngine] = None
    engine_parameters: Optional[Dict[str, Any]] = None
    provenance: Optional[Dict[str, Any]] = None


class CanonicalScenarioResponse(BaseModel):
    scenario: CanonicalScenario
    created_at: str
    updated_at: str
    supported_engines: List[str] = ["ANUGA", "PYSPH", "DELFT3D", "COUPLED_SPH_DELFT3D"]
    scientific_status: str = "canonical_unified_schema"
    message: str = "Canonical scenario ready for multi-engine dispatch"


class EngineTranslationResult(BaseModel):
    scenario_id: str
    target_engine: SimulationEngine
    translated_config: Dict[str, Any]
    provenance: Dict[str, Any]
    is_valid: bool = True
    validation_messages: List[str] = []


class CanonicalSimulationResult(BaseModel):
    """
    Canonical Multi-Engine Simulation Result Contract (Phase B3).
    Standardizes output payloads across PySPH, Delft3D FM, and ANUGA.
    Missing data is strictly preserved as null/None without fabrication.
    """
    run_id: str
    scenario_id: Optional[str] = None
    project_id: Optional[str] = None
    engine: str = Field(..., description="Simulation engine (e.g. 'pysph', 'delft3d_fm', 'anuga')")
    engine_version: Optional[str] = None
    execution_status: str = Field(default="completed", description="Execution lifecycle status")
    scientific_status: Optional[str] = Field(default=None, description="Scientific provenance status")
    created_at: str
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None

    # Temporal dimensions
    timestamps: List[float] = Field(default_factory=list, description="Array of simulation timesteps")
    time_units: str = "seconds"

    # Key Summary Metrics (None if not available/computed)
    maximum_depth_m: Optional[float] = None
    maximum_velocity_ms: Optional[float] = None
    flood_extent_km2: Optional[float] = None
    mean_depth_m: Optional[float] = None
    arrival_time_min_s: Optional[float] = None

    # Breach Hydrograph (if computed/forced)
    hydrograph: Optional[Dict[str, Any]] = None

    # Spatial & Raster metadata
    native_crs: Optional[str] = None
    spatial_bounds: Optional[List[float]] = None  # [xmin, ymin, xmax, ymax]
    raster_paths: Dict[str, str] = Field(default_factory=dict)  # {"maximum_depth": "/path/to/tif", ...}
    source_files: List[str] = Field(default_factory=list)
    layer_hashes: Dict[str, str] = Field(default_factory=dict)

    # Provenance & Metadata
    provenance: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CanonicalSimulationResultResponse(BaseModel):
    result: CanonicalSimulationResult
    retrieved_at: str
    is_comparable: bool = True
    message: str = "Canonical simulation result retrieved successfully"


class WorkflowEngineStatus(BaseModel):
    engine: str
    is_available: bool
    version: Optional[str] = None
    solver_status: str = "available"  # e.g. "available", "solver_unavailable"
    completed_runs_count: int = 0
    package_generation_ready: bool = True
    result_ingestion_ready: bool = True
    reason: Optional[str] = None


class WorkflowGISExportInfo(BaseModel):
    supported_formats: List[str] = ["geojson", "kml", "shp"]
    whitelisted_layers: List[str] = ["assets", "roads"]
    endpoints: Dict[str, str] = Field(default_factory=dict)


class WorkflowGEEValidationInfo(BaseModel):
    tasks_enabled: bool = False
    gated_reason: str = "Google Earth Engine connector is gated by server policy (ENABLE_GEE_TASKS=false)."
    whitelisted_datasets: List[str] = ["COPERNICUS/S1_GRD", "NASA/GPM_L3/IMERG_V07", "JRC/GSW1_4/GlobalSurfaceWater"]


class HidkalWorkflowSummaryResponse(BaseModel):
    project_id: str
    project_name: str
    project_status: str
    scenario: Optional[CanonicalScenario] = None
    available_engines: Dict[str, WorkflowEngineStatus]
    latest_canonical_results: Dict[str, Optional[CanonicalSimulationResult]] = Field(default_factory=dict)
    model_comparison_available: bool = False
    model_comparison_summary: Optional[Dict[str, Any]] = None
    exposure_summary: Optional[Dict[str, Any]] = None
    damage_summary: Optional[Dict[str, Any]] = None
    hadr_decision_support: Optional[Dict[str, Any]] = None
    gis_export: WorkflowGISExportInfo = Field(default_factory=WorkflowGISExportInfo)
    gee_validation: WorkflowGEEValidationInfo = Field(default_factory=WorkflowGEEValidationInfo)
    provenance_warnings: List[str] = Field(default_factory=list)
    generated_at: str




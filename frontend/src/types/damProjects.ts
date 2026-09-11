export interface RasterBounds {
  left: number
  bottom: number
  right: number
  top: number
}

export interface RasterResolution {
  x: number
  y: number
}

export interface RasterDerivedMetadata {
  width: number
  height: number
  band_count: number
  dtype: string
  crs: string
  bounds: RasterBounds
  resolution: RasterResolution
  nodata: number | null
  min_elevation: number | null
  max_elevation: number | null
  mean_elevation?: number | null
  valid_pixel_count?: number | null
  nodata_pixel_count?: number | null
  file_sha256?: string | null
  vertical_unit_in_header: string
  vertical_datum_in_header: string
}

export interface DamPointMetadata {
  dam_name: string
  latitude: number
  longitude: number
  crs_x?: number | null
  crs_y?: number | null
  geometry_crs?: string | null
  source: string
  elevation_at_point?: number | null
  sampled_from_dem: boolean
}

export interface EngineeringParameters {
  dam_height?: number | null
  crest_elevation?: number | null
  pool_elevation?: number | null
  manning_n?: number | null
  hydraulic_head?: number | null
  freeboard?: number | null
}

export interface UserProvidedMetadata {
  project_name: string
  dam_name?: string | null
  dam_point?: DamPointMetadata | null
  engineering_parameters?: EngineeringParameters | null
  vertical_unit?: string | null
  vertical_datum?: string | null
  reservoir_level?: number | null
  breach_width?: number | null
  breach_center?: [number, number] | null
  breach_formation_time_hr?: number | null
  manning_roughness?: number | null
  dam_crest_elevation?: number | null
  breach_invert_elevation?: number | null
  target_mesh_resolution_m?: number | null
  simulation_duration_s?: number | null
  output_interval_s?: number | null
  geometry_crs: string
}

export interface GeometryValidationMetadata {
  layer_name: string
  feature_count: number
  geometry_types: string[]
  is_valid: boolean
  intersects_dem_bounds: boolean
  fully_within_dem_bounds: boolean
  centroid_coords?: [number, number] | null
}

export interface NormalizedProjectMetadata {
  project_name: string
  dam_name?: string | null
  dam_point?: DamPointMetadata | null
  engineering_parameters?: EngineeringParameters | null
  raster_metadata?: RasterDerivedMetadata | null
  user_provided_metadata?: UserProvidedMetadata | null
  dam_axis_metadata?: GeometryValidationMetadata | null
  reservoir_metadata?: GeometryValidationMetadata | null
  model_domain_metadata?: GeometryValidationMetadata | null
  downstream_outlet_metadata?: GeometryValidationMetadata | null
  breach_on_dam_axis: boolean
  breach_distance_to_axis_m?: number | null
  distance_calculation_crs?: string | null
  scientific_status?: string
}

export interface DamProjectValidationResponse {
  valid: boolean
  project_name: string
  dam_name?: string | null
  scientific_status?: string
  errors: string[]
  warnings: string[]
  normalized_metadata?: NormalizedProjectMetadata | null
  assumptions_requiring_confirmation: string[]
  metadata_declared: boolean
  onboarding_validation_passed: boolean
  scientifically_verified: boolean
}

export interface DamProjectSummary {
  project_id: string
  project_name: string
  dam_name?: string | null
  status: string
  scientific_status?: string
  available: boolean
  integrity_status: string
  integrity_error?: string | null
  created_at: string
  crs: string
  bounds: RasterBounds
  resolution: RasterResolution
  dam_point?: DamPointMetadata | null
  has_reservoir_boundary: boolean
  has_model_domain?: boolean
  has_downstream_outlet?: boolean
  metadata_declared: boolean
  onboarding_validation_passed: boolean
  scientifically_verified: boolean
  manifest_sha256: string
  notes: string[]
}

export interface DamProjectDetailResponse {
  project_id: string
  project_name: string
  dam_name?: string | null
  status: string
  scientific_status?: string
  created_at: string
  dem_file: string
  dam_axis_file?: string | null
  reservoir_boundary_file?: string | null
  model_domain_file?: string | null
  downstream_outlet_file?: string | null
  raster_metadata: RasterDerivedMetadata
  user_provided_metadata: UserProvidedMetadata
  dam_point?: DamPointMetadata | null
  engineering_parameters?: EngineeringParameters | null
  dam_axis_metadata?: GeometryValidationMetadata | null
  reservoir_metadata?: GeometryValidationMetadata | null
  model_domain_metadata?: GeometryValidationMetadata | null
  downstream_outlet_metadata?: GeometryValidationMetadata | null
  breach_parameters: {
    reservoir_level?: number | null
    breach_width?: number | null
    breach_center?: [number, number] | null
    breach_formation_time_hr?: number | null
    manning_roughness?: number | null
    dam_crest_elevation?: number | null
    breach_invert_elevation?: number | null
    breach_on_dam_axis: boolean
    breach_distance_to_axis_m?: number | null
    distance_calculation_crs?: string | null
  }
  simulation_parameters?: {
    target_mesh_resolution_m?: number | null
    simulation_duration_s?: number | null
    output_interval_s?: number | null
    manning_roughness?: number | null
  }
  manifest: {
    manifest_version: string
    project_id: string
    project_name: string
    created_at: string
    status: string
    scientifically_verified: boolean
    files: Record<string, string>
  }
  assumptions_requiring_confirmation: string[]
  metadata_declared: boolean
  onboarding_validation_passed: boolean
  scientifically_verified: boolean
  anuga_package_built?: boolean
  anuga_package_sha256?: string | null
  warnings: string[]
}

export interface DamProjectReadinessResponse {
  project_id: string
  project_name: string
  dam_name?: string | null
  scientific_status: string
  scientifically_verified: boolean
  has_dem: boolean
  has_dam_point: boolean
  has_engineering_parameters: boolean
  has_dam_axis: boolean
  has_reservoir_boundary: boolean
  has_model_domain: boolean
  has_downstream_outlet: boolean
  ready_for_screening: boolean
  ready_for_anuga_simulation: boolean
  // Phase 19: 5-tier simulation readiness
  data_ready?: boolean
  geometry_ready?: boolean
  hydraulic_ready?: boolean
  solver_ready?: boolean
  simulation_ready?: boolean
  tier_breakdown?: Record<string, { ready: boolean; missing: string[]; details?: Record<string, any> }>
  missing_requirements?: string[]
  missing_for_anuga: string[]
  recommended_next_steps: string[]
  disclaimer: string
}

export interface DamProjectAnugaPreflightResponse {
  project_id: string
  project_name: string
  preflight_passed: boolean
  blockers: string[]
  warnings: string[]
  derived_checks: {
    model_domain_area_km2?: number | null
    estimated_mesh_triangles?: number | null
    water_head_above_invert_m?: number | null
    freeboard_m?: number | null
    output_steps_count?: number | null
    breach_distance_to_axis_m?: number | null
  }
  proposed_configuration: {
    target_mesh_resolution_m?: number | null
    max_triangle_area_m2?: number | null
    simulation_duration_s?: number | null
    output_interval_s?: number | null
    output_steps_count?: number | null
    manning_roughness?: number | null
    solver_type?: string
    breach_formulation?: string
    datum_declared?: string
  }
  scientific_status: string
}

export interface DamProjectAnugaPackageResponse {
  project_id: string
  project_name: string
  package_filename: string
  package_size_bytes: number
  package_sha256: string
  files_included: string[]
  scientific_status: string
  simulation_executed: boolean
  message: string
}

export interface DamProjectAnugaCapabilitiesResponse {
  execution_enabled: boolean
  anuga_installed: boolean
  anuga_environment_available?: boolean
  python_executable_path?: string | null
  anuga_import_success?: boolean
  anuga_version: string
  version_source?: 'importlib_metadata' | 'conda_meta' | 'fallback_runtime' | 'unavailable'
  raw_distribution_version?: string | null
  python_executable_configured: boolean
  reason?: string | null
  disclaimer: string
}

export interface HeuristicAssistRequest {
  search_radius_cells?: number
  downstream_length_m?: number
  corridor_width_m?: number
  dam_crest_length_m?: number
}

export interface HeuristicAssistResponse {
  project_id: string
  downstream_bearing_deg: number
  downstream_direction: string
  slope_gradient: number
  dam_point_elevation?: number | null
  estimated_crest_elevation?: number | null
  suggested_dam_axis: Record<string, any>
  suggested_breach_line: Record<string, any>
  suggested_model_domain: Record<string, any>
  suggested_outlet_boundary: Record<string, any>
  suggested_reservoir_boundary: Record<string, any>
  source: 'terrain_heuristic'
  scientifically_verified: boolean
  confidence: string
  caveats: string[]
}

export interface SimulationInputsUpdateRequest {
  reservoir_level?: number | null
  dam_crest_elevation?: number | null
  dam_height?: number | null
  breach_width?: number | null
  breach_invert_elevation?: number | null
  breach_formation_time_hr?: number | null
  manning_roughness?: number | null
  simulation_duration_s?: number | null
  output_interval_s?: number | null
  target_mesh_resolution_m?: number | null
  dam_axis_geometry?: Record<string, any> | null
  reservoir_geometry?: Record<string, any> | null
  model_domain_geometry?: Record<string, any> | null
  downstream_outlet_geometry?: Record<string, any> | null
  accept_heuristic_inputs?: boolean
  custom_notes?: string | null
}

export interface DamProjectAnugaRunRequest {
  acknowledge_hypothetical_unverified: boolean
  custom_notes?: string | null
  simulation_duration_s?: number | null
  output_interval_s?: number | null
  target_mesh_resolution_m?: number | null
}

export interface DamProjectAnugaRunResponse {
  run_id: string
  project_id: string
  project_name: string
  package_sha256: string
  status: 'queued' | 'preparing' | 'running' | 'postprocessing' | 'completed' | 'failed' | 'cancelled' | 'timed_out' | 'interrupted'
  created_at: string
  started_at?: string | null
  completed_at?: string | null
  exit_code?: number | null
  anuga_version?: string | null
  version_source?: 'importlib_metadata' | 'conda_meta' | 'fallback_runtime' | 'unavailable' | null
  raw_distribution_version?: string | null
  runtime_seconds?: number | null
  log_file?: string | null
  output_files: Record<string, string>
  parameters_snapshot?: Record<string, any>
  run_manifest_sha256?: string | null
  scientific_status: string
  simulation_executed: boolean
  has_results?: boolean
  message: string
}

export interface DamProjectAnugaOutputsResponse {
  project_id: string
  run_id: string
  status: string
  sww_file?: string | null
  sww_size_bytes?: number | null
  sww_sha256?: string | null
  output_files: Record<string, string>
  has_results: boolean
  available_layers: string[]
  layer_statistics: Record<string, any>
  runtime_seconds?: number | null
  scientific_status: string
  simulation_executed: boolean
  message: string
}

export interface DamProjectAnugaPostprocessRequest {
  dry_depth_threshold_m?: number
  arrival_depth_threshold_m?: number
  raster_resolution_m?: number | null
}

export interface DamProjectAnugaLayerStats {
  min?: number | null
  max?: number | null
  mean?: number | null
  valid_pixels: number
  nodata_pixels: number
  total_pixels: number
  unit: string
}

export interface DamProjectAnugaResultsResponse {
  project_id: string
  run_id: string
  processing_id?: string
  created_at: string
  sww_sha256: string
  package_sha256: string
  processing_identity_sha256: string
  available_layers: string[]
  layer_files: Record<string, string>
  layer_statistics: Record<string, DamProjectAnugaLayerStats>
  formulas: Record<string, string>
  thresholds: Record<string, number>
  actual_sww_timesteps: number[]
  interpolation_method: string
  mesh_mask_method: string
  raster_crs: string
  raster_resolution_m: number
  grid_dimensions: [number, number]
  anuga_version: string
  version_source: string
  raw_distribution_version?: string | null
  scientific_status: string
  simulation_executed: boolean
  mass_balance_status: string
  disclaimer: string
  message: string
}

export interface DamProjectAnugaPointValueResponse {
  project_id: string
  run_id: string
  processing_id?: string
  layer: string
  lon: number
  lat: number
  crs_x?: number | null
  crs_y?: number | null
  crs: string
  value?: number | null
  unit: string
  value_type: string
  description: string
  is_valid: boolean
  is_nodata: boolean
  disclaimer: string
}

export interface OnboardingFormValues {
  projectName: string
  damName: string
  latitude: string
  longitude: string
  damHeight: string
  crestElevation: string
  poolElevation: string
  manningN: string
  verticalUnit: string
  verticalDatum: string
  reservoirLevel: string
  breachWidth: string
  breachCenterX: string
  breachCenterY: string
  breachFormationTimeHr: string
  manningRoughness: string
  damCrestElevation: string
  breachInvertElevation: string
  targetMeshResolutionM: string
  simulationDurationS: string
  outputIntervalS: string
  geometryCrs: string
}

// Phase 20: Project-Scoped Earth Observation & Comparison Interfaces

export interface ProjectAOIResponse {
  project_id: string
  aoi_bounds: [number, number, number, number]
  aoi_geojson: any
  aoi_area_km2: number
  source: string
  buffer_applied_meters: number
}

export interface Sentinel1ProcessingParams {
  polarization?: 'VV' | 'VH' | 'both'
  change_threshold_db?: number
  post_event_water_threshold_db?: number
  threshold_source?: string
}

export interface EarthObservationRunRequest {
  datasets?: Array<'sentinel1' | 'jrc_water' | 'gpm_imerg'>
  event_date: string
  pre_event_window_days?: number
  post_event_window_days?: number
  rainfall_start_date?: string | null
  rainfall_end_date?: string | null
  aoi_buffer_meters?: number
  s1_params?: Sentinel1ProcessingParams
}

export interface RainfallTimeSeriesPoint {
  timestamp: string
  precipitation_mm_hr: number
  accumulated_precipitation_mm: number
}

export interface EarthObservationRunResponse {
  eo_run_id: string
  project_id: string
  status:
    | 'queued'
    | 'retrieving'
    | 'processing'
    | 'completed'
    | 'failed'
    | 'dry_run_unauthenticated'
    | 'gee_unavailable'
    | 'authentication_required'
    | 'project_not_configured'
    | 'no_imagery_available'
  created_at: string
  completed_at?: string | null
  aoi_bounds: [number, number, number, number]
  aoi_area_km2: number
  requested_datasets: string[]
  layers: Record<string, any>
  candidate_inundation_area_km2?: number | null
  permanent_water_area_km2?: number | null
  rainfall_accumulation_mm?: number | null
  rainfall_time_series: RainfallTimeSeriesPoint[]
  provenance: Record<string, any>
  scientific_disclaimer: string
  message: string
}

export interface ModelObservationComparisonRequest {
  anuga_run_id: string
  eo_run_id: string
  depth_threshold_m?: number
  jrc_permanent_threshold_pct?: number
  max_observation_time_delta_hours?: number
}

export interface TemporalValidityMetadata {
  comparison_valid: boolean
  event_reference_time: string
  satellite_acquisition_time: string
  absolute_delta_hours: number
  configured_tolerance_hours: number
  warning?: string | null
}

export interface ModelObservationComparisonResponse {
  comparison_id: string
  project_id: string
  anuga_run_id: string
  eo_run_id: string
  created_at: string
  model_inundated_area_km2: number
  satellite_candidate_area_km2: number
  overlap_area_km2: number
  model_only_area_km2: number
  satellite_only_area_km2: number
  union_area_km2: number
  spatial_agreement_iou: number
  precision?: number | null
  recall?: number | null
  temporal_validity: TemporalValidityMetadata
  label: string
  provenance: Record<string, any>
  scientific_caveats: string[]
}

export interface GEECapabilitiesResponse {
  gee_available: boolean
  authenticated: boolean
  project_id: string | null
  auth_mode: string
  tasks_enabled: boolean
  whitelisted_collections: string[]
  disclaimer: string
  guidance: string
  project_configured: boolean
  earthengine_import_success: boolean
  gee_project_id: string | null
  reason?: string | null
  supported_datasets: string[]
}

// ==========================================
// Phase 21: Multi-Engine Spatial Comparison
// ==========================================

export interface ModelComparisonEngineCapability {
  environment_available: boolean
  solver_available: boolean
  completed_run_count: number
  comparable_run_count: number
  available_for_comparison: boolean
  version?: string | null
  reason?: string | null
}

export interface ModelComparisonCapabilitiesResponse {
  project_id: string
  engines: Record<string, ModelComparisonEngineCapability>
  ready_for_comparison: boolean
  runs_available: Record<string, any[]>
  disclaimer: string
}

export interface ToleranceBandCoverage {
  tolerance_m: number
  pixel_count: number
  area_km2: number
  percentage_of_common_valid_area: number
}

export interface DepthDifferenceStats {
  common_valid_pixel_count: number
  common_analysis_area_km2: number
  mean_signed_difference_m: number
  median_signed_difference_m: number
  mae_m: number
  rmse_m: number
  max_positive_difference_m: number
  max_negative_difference_m: number
  tolerance_bands: ToleranceBandCoverage[]
}

export interface VelocityDifferenceStats {
  available: boolean
  reason?: string | null
  common_valid_pixel_count?: number | null
  common_analysis_area_km2?: number | null
  mean_signed_difference_m_s?: number | null
  mae_m_s?: number | null
  rmse_m_s?: number | null
  max_difference_m_s?: number | null
}

export interface InundationAgreementStats {
  label: string
  model_a_inundated_area_km2: number
  model_b_inundated_area_km2: number
  overlap_area_km2: number
  model_a_only_area_km2: number
  model_b_only_area_km2: number
  union_area_km2: number
  spatial_agreement_iou: number
}

export interface ArrivalTimeDifferenceStats {
  available: boolean
  comparison_valid: boolean
  reason?: string | null
  threshold_definition_a?: string | null
  threshold_definition_b?: string | null
  common_valid_pixel_count?: number | null
  common_analysis_area_km2?: number | null
  mean_signed_difference_s?: number | null
  mae_s?: number | null
  model_a_earlier_area_km2?: number | null
  model_b_earlier_area_km2?: number | null
}

export interface InterModelSpreadDiagnostic {
  computed: boolean
  label: string
  model_count: number
  pixel_count: number
  mean_spread_m: number
  max_spread_m: number
}

export interface ModelComparisonRunRequest {
  engine_a: string
  run_id_a: string
  engine_b: string
  run_id_b: string
  depth_inundation_threshold_m?: number
  tolerance_bands_m?: number[]
  synthetic_test_fixture?: boolean
}

export interface ModelComparisonRunResponse {
  comparison_id: string
  project_id: string
  engine_a: string
  run_id_a: string
  engine_b: string
  run_id_b: string
  status: string
  created_at: string
  completed_at?: string | null
  depth_difference: DepthDifferenceStats
  velocity_difference: VelocityDifferenceStats
  inundation_agreement: InundationAgreementStats
  arrival_time_difference: ArrivalTimeDifferenceStats
  ensemble_spread?: InterModelSpreadDiagnostic | null
  provenance: Record<string, any>
  scientific_disclaimer: string
}


// Phase 22: Exposure & Vulnerability Assessment Interfaces

export interface PopulationExposureSummary {
  available: boolean
  status: string
  reason_if_unavailable?: string | null
  population_source?: string | null
  population_unit?: string | null
  native_resolution?: number | null
  native_crs?: string | null
  analysis_crs?: string | null
  resampling_or_aggregation_method?: string | null
  count_conservation_method?: string | null
  total_population_in_aoi?: number | null
  population_in_inundation_extent?: number | null
  population_percentage_exposed?: number | null
  population_by_depth_band: Record<string, number>
  population_by_arrival_window: Record<string, number>
}

export interface BuildingExposureSummary {
  available: boolean
  status: string
  reason_if_unavailable?: string | null
  source_dataset?: string | null
  total_buildings: number
  buildings_exposed: number
  buildings_exposed_percentage: number
  building_footprint_area_exposed_m2: number
  building_footprint_area_exposed_km2: number
  buildings_by_depth_band: Record<string, number>
  buildings_by_usage: Record<string, number>
  sampling_method: string
}

export interface RoadExposureSummary {
  available: boolean
  status: string
  reason_if_unavailable?: string | null
  source_dataset?: string | null
  total_road_length_km: number
  affected_road_length_km: number
  affected_percentage: number
  max_depth_m?: number | null
  mean_depth_m?: number | null
  road_length_by_depth_band_km: Record<string, number>
  road_class_breakdown_km: Record<string, { total_km: number; affected_km: number }>
  road_passability_available: boolean
  passability_rule_note: string
}

export interface CriticalAssetItem {
  asset_id: string
  name?: string | null
  source_category: string
  normalized_category: string
  depth_m?: number | null
  velocity_mps?: number | null
  arrival_time_s?: number | null
  hazard_band?: string | null
  arrival_window?: string | null
  source_provenance: string
}

export interface CriticalInfrastructureSummary {
  available: boolean
  status: string
  reason_if_unavailable?: string | null
  source_dataset?: string | null
  total_critical_assets: number
  exposed_critical_assets: number
  exposed_by_category: Record<string, number>
  assets: CriticalAssetItem[]
}

export interface LULCClassExposure {
  class_id: number
  class_name: string
  flooded_area_m2: number
  flooded_area_km2: number
  flooded_percentage_of_class?: number | null
}

export interface LULCExposureSummary {
  available: boolean
  status: string
  reason_if_unavailable?: string | null
  source_dataset?: string | null
  total_flooded_area_km2: number
  classes: LULCClassExposure[]
  resampling_method: string
}

export interface DamageEstimationSummary {
  vulnerability_available: boolean
  monetary_damage_available: boolean
  reason_if_unavailable?: string | null
  relative_damage_index?: number | null
  monetary_damage?: number | null
  currency?: string | null
  valuation_year?: number | null
  value_source?: string | null
  methodology_note: string
}

export interface DecisionSupportHotspot {
  hotspot_id: string
  name: string
  latitude: number
  longitude: number
  priority_score: number
  reasons: string[]
  hazard_depth_m: number
  exposed_features: string[]
}

export interface DecisionSupportPrioritySummary {
  composite_index: number
  formula: string
  weights: Record<string, number>
  weights_label: string
  normalization_method: string
  hotspots: DecisionSupportHotspot[]
  caveat: string
}

export interface VulnerabilityCurveInfo {
  curve_id: string
  curve_source: string
  asset_class: string
  hazard_variable: string
  units: string
  curve_provenance: string
  region_applicability?: string
  curve_status?: string
  version_year?: number
}

export interface ExposureCapabilitiesResponse {
  project_id: string
  hazard_sources: Array<{
    engine: string
    run_id: string
    label: string
    completed_at?: string | null
    status: string
  }>
  available_exposure_datasets: Record<string, {
    available: boolean
    source?: string
    reason?: string
    unit?: string
    crs?: string
    resolution?: number
  }>
  supported_vulnerability_curves: VulnerabilityCurveInfo[]
  default_depth_bands: Array<{ name: string; min_depth: number; max_depth?: number | null }>
  default_arrival_windows: Array<{ name: string; min_s: number; max_s?: number | null }>
  default_priority_weights: Record<string, number>
}

export interface ExposureRunRequest {
  hazard_engine: string
  hazard_run_id?: string | null
  depth_threshold_m?: number
  depth_bands?: Array<{ name: string; min_depth: number; max_depth?: number | null }>
  arrival_windows?: Array<{ name: string; min_s: number; max_s?: number | null }>
  population_unit_override?: string | null
  priority_weights?: Record<string, number> | null
  passability_depth_threshold_m?: number | null
  target_analysis_crs?: string | null
  synthetic_test_fixture?: boolean
}

export interface ExposureRunSummary {
  run_id: string
  project_id: string
  hazard_engine: string
  hazard_run_id?: string | null
  status: string
  created_at: string
  depth_threshold_m: number
  population_exposed?: number | null
  buildings_exposed?: number | null
  affected_road_length_km?: number | null
  critical_assets_exposed?: number | null
  priority_score?: number | null
  scientific_status: string
}

export interface ExposureRunDetailResponse {
  run_id: string
  project_id: string
  status: string
  created_at: string
  hazard_contract: Record<string, any>
  depth_threshold_m: number
  depth_bands: Array<{ name: string; min_depth: number; max_depth?: number | null }>
  arrival_windows: Array<{ name: string; min_s: number; max_s?: number | null }>
  population: PopulationExposureSummary
  buildings: BuildingExposureSummary
  roads: RoadExposureSummary
  critical_infrastructure: CriticalInfrastructureSummary
  lulc: LULCExposureSummary
  vulnerability_and_damage: DamageEstimationSummary
  decision_support_priority: DecisionSupportPrioritySummary
  provenance: Record<string, any>
  scientific_caveats: string[]
  message: string
}

// Phase 23: System Capability & Health Interfaces
export interface SubsystemHealth {
  id: string
  name: string
  status: 'ready' | 'available_not_configured' | 'unavailable' | 'missing_data' | 'failed' | 'execution_disabled'
  status_label: string
  version?: string | null
  environment?: string | null
  details: string
  is_optional: boolean
  scientific_caveat?: string | null
}

export interface SystemHealthSummaryResponse {
  overall_status: string
  timestamp: string
  subsystems: SubsystemHealth[]
}




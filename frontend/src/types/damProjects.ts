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
  vertical_unit_in_header: string
  vertical_datum_in_header: string
}

export interface UserProvidedMetadata {
  project_name: string
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
  raster_metadata?: RasterDerivedMetadata | null
  user_provided_metadata?: UserProvidedMetadata | null
  dam_axis_metadata?: GeometryValidationMetadata | null
  reservoir_metadata?: GeometryValidationMetadata | null
  model_domain_metadata?: GeometryValidationMetadata | null
  downstream_outlet_metadata?: GeometryValidationMetadata | null
  breach_on_dam_axis: boolean
  breach_distance_to_axis_m?: number | null
  distance_calculation_crs?: string | null
}

export interface DamProjectValidationResponse {
  valid: boolean
  project_name: string
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
  status: string
  available: boolean
  integrity_status: string
  integrity_error?: string | null
  created_at: string
  crs: string
  bounds: RasterBounds
  resolution: RasterResolution
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
  status: string
  created_at: string
  dem_file: string
  dam_axis_file: string
  reservoir_boundary_file?: string | null
  model_domain_file?: string | null
  downstream_outlet_file?: string | null
  raster_metadata: RasterDerivedMetadata
  user_provided_metadata: UserProvidedMetadata
  dam_axis_metadata: GeometryValidationMetadata
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
  anuga_version: string
  version_source?: 'importlib_metadata' | 'conda_meta' | 'fallback_runtime' | 'unavailable'
  raw_distribution_version?: string | null
  python_executable_configured: boolean
  reason?: string | null
  disclaimer: string
}

export interface DamProjectAnugaRunRequest {
  acknowledge_hypothetical_unverified: boolean
  custom_notes?: string | null
}

export interface DamProjectAnugaRunResponse {
  run_id: string
  project_id: string
  project_name: string
  package_sha256: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'timed_out' | 'interrupted'
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
  scientific_status: string
  simulation_executed: boolean
  has_results?: boolean
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

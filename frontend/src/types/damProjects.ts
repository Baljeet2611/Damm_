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
  raster_metadata: RasterDerivedMetadata
  user_provided_metadata: UserProvidedMetadata
  dam_axis_metadata: GeometryValidationMetadata
  reservoir_metadata?: GeometryValidationMetadata | null
  breach_parameters: {
    reservoir_level?: number | null
    breach_width?: number | null
    breach_center?: [number, number] | null
    breach_formation_time_hr?: number | null
    manning_roughness?: number | null
    breach_on_dam_axis: boolean
    breach_distance_to_axis_m?: number | null
    distance_calculation_crs?: string | null
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
  warnings: string[]
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
  geometryCrs: string
}

import os
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Query, Response, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.schemas import (
    DatasetResponse,
    RasterMetadataResponse,
    RasterPointValueResponse,
    RasterLegendResponse,
    ExposureSummaryResponse,
    DamageConfigResponse,
    DamageScenarioRequest,
    DamageScenarioResponse,
    RouteScreeningRequest,
    RouteScreeningResponse,
    ExportRouteRequest,
    ExportRequest,
    ScenarioCreateRequest,
    ScenarioUpdateRequest,
    ScenarioResponse,
    SimulationCapabilitiesResponse,
    ModelPackageResponse,
    SimulationRunRequest,
    SimulationRunResponse,
    SimulationLogResponse,
    SPHCapabilitiesResponse,
    SPHPackageResponse,
    SPHRunRequest,
    SPHRunResponse,
    ComparisonReadinessResponse,
    ComparisonRequest,
    ComparisonResponse,
    MethodologyComparisonResponse,
    GEECapabilitiesResponse,
    GEEDatasetInfo,
    GEEExportPlanRequest,
    GEEExportPlanResponse,
    HazardSourcesResponse,
    ANUGARunSummary,
    ANUGARunDetailResponse,
    DamProjectValidationResponse,
    DamProjectSummary,
    DamProjectDetailResponse,
    DamProjectAnugaPreflightResponse,
    DamProjectAnugaPackageResponse,
    DamProjectAnugaCapabilitiesResponse,
    DamProjectAnugaRunRequest,
    DamProjectAnugaRunResponse,
)

from app.raster_service import (
    list_datasets,
    get_raster_metadata,
    get_raster_point_value,
    get_raster_tile,
    get_raster_legend,
)
from app.anuga_service import (
    get_hazard_sources,
    list_anuga_runs,
    get_anuga_run_detail,
    get_anuga_raster_metadata,
    get_anuga_raster_point_value,
    get_anuga_raster_tile,
    get_anuga_raster_legend,
)
from app.vector_service import (
    load_raw_assets,
    load_raw_roads,
    get_exposure_assets,
    get_exposure_roads,
    get_exposure_summary,
)
from app.damage_service import (
    get_default_damage_config,
    compute_damage_scenario,
)
from app.route_service import calculate_screening_route
from app.export_service import handle_export
from app.scenario_storage import (
    list_scenarios,
    get_scenario,
    create_scenario,
    update_scenario,
    clone_scenario,
    archive_scenario,
)
from app.simulation_service import (
    detect_capabilities,
    build_model_package,
    get_package_zip_path,
    execute_simulation_run,
    list_simulation_runs,
    get_simulation_run,
    get_simulation_logs,
)
from app.sph_service import (
    check_sph_capabilities,
    build_sph_package,
    get_sph_package_zip_path,
    execute_sph_run,
    list_sph_runs,
    get_sph_run,
    get_sph_logs,
)
from app.comparison_service import (
    check_comparison_readiness,
    compare_runs,
    get_methodology_comparison,
)
from app.gee_service import (
    check_gee_capabilities,
    list_whitelisted_datasets,
    get_dataset_info,
    create_export_plan,
)
from app.onboarding_service import (
    validate_dam_project_dataset,
    save_dam_project,
    list_dam_projects,
    get_dam_project,
    get_dam_project_dem_metadata,
    get_dam_project_dem_point_value,
    get_dam_project_dem_tile,
    get_dam_project_dam_axis_geometry,
    get_dam_project_reservoir_geometry,
    get_dam_project_breach_geometry,
    get_dam_project_model_domain_geometry,
    get_dam_project_outlet_geometry,
    assess_anuga_preflight,
    build_dam_project_anuga_package,
    get_dam_project_anuga_package_path,
    get_custom_anuga_capabilities,
    create_dam_project_anuga_run,
    list_dam_project_anuga_runs,
    get_dam_project_anuga_run,
    get_dam_project_anuga_run_logs,
    recover_interrupted_anuga_runs,
)

logger = logging.getLogger("app.main")

app = FastAPI(
    title="Dam Break Decision Support System API",
    description="Automated dam-break hydrodynamic inspection, vector overlays, preliminary exposure screening, illustrative damage estimation, scenario management, and Delft3D integration API",
    version="0.9.0",
)

@app.on_event("startup")
def on_startup():
    try:
        recover_interrupted_anuga_runs()
    except Exception as exc:
        logger.warning("Failed to recover interrupted ANUGA runs on startup: %s", exc)

cors_env = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [origin.strip() for origin in cors_env.split(",") if origin.strip()]
if not allowed_origins:
    allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled server error processing request %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred while processing the request."},
    )



@app.get("/api/health")
def health_check():
    return {"status": "ok"}


# Phase 16: Hazard Sources Catalog

@app.get("/api/hazard-sources", response_model=HazardSourcesResponse)
def get_hazard_sources_endpoint() -> HazardSourcesResponse:
    """
    Return catalog of available hazard sources (Sample vs ANUGA Pilot)
    with execution status, disclaimers, vertical unit descriptions, and availability.
    """
    return get_hazard_sources()


# Phase 16: ANUGA Pilot Hydrodynamic Results Endpoints

@app.get("/api/anuga/runs", response_model=List[ANUGARunSummary])
def get_anuga_runs() -> List[ANUGARunSummary]:
    """List registered ANUGA pilot simulation runs with availability and diagnostics."""
    return list_anuga_runs()


@app.get("/api/anuga/runs/{run_id}", response_model=ANUGARunDetailResponse)
def get_anuga_run(run_id: str) -> ANUGARunDetailResponse:
    """Retrieve detailed metadata, breach parameters, volume conservation, and manifest for an ANUGA run."""
    return get_anuga_run_detail(run_id=run_id)


@app.get("/api/anuga/rasters/{id}/metadata", response_model=RasterMetadataResponse)
def get_anuga_metadata(
    id: str,
    hazard_source: Optional[str] = Query(default=None, description="Hazard source: anuga_hidkal_pilot or anuga_hidkal_refined"),
) -> RasterMetadataResponse:
    """Return metadata for an ANUGA GeoTIFF raster layer (depth, velocity, arrival)."""
    return get_anuga_raster_metadata(layer_name=id, hazard_source=hazard_source)


@app.get("/api/anuga/rasters/{id}/value", response_model=RasterPointValueResponse)
def get_anuga_point_value(
    id: str,
    lon: float = Query(..., description="Query longitude coordinate in WGS84 (EPSG:4326)"),
    lat: float = Query(..., description="Query latitude coordinate in WGS84 (EPSG:4326)"),
    hazard_source: Optional[str] = Query(default=None, description="Hazard source: anuga_hidkal_pilot or anuga_hidkal_refined"),
) -> RasterPointValueResponse:
    """
    Point query for an ANUGA layer at WGS84 coordinates (lon, lat).
    Transforms coordinates into EPSG:32643 and samples the raster with arrival semantics.
    """
    return get_anuga_raster_point_value(layer_name=id, lon=lon, lat=lat, hazard_source=hazard_source)


@app.get("/api/anuga/rasters/{id}/tiles/{z}/{x}/{y}.png")
def get_anuga_tile(
    id: str,
    z: int,
    x: int,
    y: int,
    hazard_source: Optional[str] = Query(default=None, description="Hazard source: anuga_hidkal_pilot or anuga_hidkal_refined"),
) -> Response:
    """
    Web Mercator XYZ tile endpoint for ANUGA raster visualization.
    Returns 256x256 PNG with customized color ramp, bilinear/nearest rendering, and layer transparency.
    """
    tile_bytes = get_anuga_raster_tile(layer_name=id, z=z, x=x, y=y, hazard_source=hazard_source)
    return Response(
        content=tile_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/anuga/rasters/{id}/legend", response_model=RasterLegendResponse)
def get_anuga_legend(
    id: str,
    hazard_source: Optional[str] = Query(default=None, description="Hazard source: anuga_hidkal_pilot or anuga_hidkal_refined"),
) -> RasterLegendResponse:
    """Return colormap stops, discrete legend classifications, and value range for an ANUGA layer."""
    return get_anuga_raster_legend(layer_name=id, hazard_source=hazard_source)


# Sample Raster Inspection Endpoints

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


# Vector & Exposure Analysis Endpoints

@app.get("/api/assets")
def get_assets() -> Dict[str, Any]:
    """
    Return raw infrastructure assets GeoJSON FeatureCollection
    with OSM categorized classifications.
    Never accepts or exposes filesystem paths.
    """
    return load_raw_assets()


@app.get("/api/roads")
def get_roads() -> Dict[str, Any]:
    """
    Return road network converted from GraphML edges to GeoJSON FeatureCollection LineStrings.
    Uses stored geometry when available, otherwise node coordinates.
    Never accepts or exposes filesystem paths.
    """
    return load_raw_roads()


@app.get("/api/exposure/assets")
def get_exposure_assets_endpoint(
    hazard_source: Optional[str] = Query(default="sample_hidkal", description="Hazard source: sample_hidkal, anuga_hidkal_pilot, or anuga_hidkal_refined"),
    threshold: Optional[float] = Query(default=0.0, description="Minimum depth threshold for exposure screening"),
) -> Dict[str, Any]:
    """
    Return infrastructure assets GeoJSON FeatureCollection with preliminary
    raster exposure screening attributes attached (assessed, exposed, depth_value,
    velocity_value, arrival_value, is_initially_wet, sampling_method, category).
    """
    return get_exposure_assets(hazard_source=hazard_source or "sample_hidkal", threshold=threshold or 0.0)


@app.get("/api/exposure/roads")
def get_exposure_roads_endpoint(
    hazard_source: Optional[str] = Query(default="sample_hidkal", description="Hazard source: sample_hidkal, anuga_hidkal_pilot, or anuga_hidkal_refined"),
    threshold: Optional[float] = Query(default=0.0, description="Minimum depth threshold for exposure screening"),
) -> Dict[str, Any]:
    """
    Return road network GeoJSON FeatureCollection with preliminary
    raster exposure screening attributes attached (assessed, exposed, depth_value,
    velocity_value, arrival_value, is_initially_wet, sampling_method, category).
    """
    return get_exposure_roads(hazard_source=hazard_source or "sample_hidkal", threshold=threshold or 0.0)


@app.get("/api/exposure/summary", response_model=ExposureSummaryResponse)
def get_exposure_summary_endpoint(
    hazard_source: Optional[str] = Query(default="sample_hidkal", description="Hazard source: sample_hidkal, anuga_hidkal_pilot, or anuga_hidkal_refined"),
    threshold: Optional[float] = Query(default=0.0, description="Minimum depth threshold for exposure screening"),
) -> ExposureSummaryResponse:
    """
    Return preliminary flood-exposure summary containing total, assessed, exposed,
    not-exposed, and not-assessed counts, plus category breakdowns and reservoir partitioning.
    Includes scientific disclaimer on selected hazard source.
    """
    return get_exposure_summary(hazard_source=hazard_source or "sample_hidkal", threshold=threshold or 0.0)


# Phase 7: Illustrative Damage Scenario Endpoints

@app.get("/api/damage/config", response_model=DamageConfigResponse)
def get_damage_config() -> DamageConfigResponse:
    """
    Return default editable illustrative damage scenario configuration
    including assumed depth unit, currency label, replacement values per asset category,
    depth-damage piecewise curve, sensitivity percentage, and disclaimer.
    """
    return get_default_damage_config()


@app.post("/api/damage/estimate", response_model=DamageScenarioResponse)
def post_damage_estimate(request: DamageScenarioRequest) -> DamageScenarioResponse:
    """
    Calculate transparent illustrative damage scenario estimation based on
    preliminary asset screening depths and user-acknowledged input assumptions.
    Rejects calculation with 422 if acknowledge_unverified_inputs is False.
    """
    return compute_damage_scenario(request)


# Phase 8: Route Screening Endpoints

@app.post("/api/routes/screening", response_model=RouteScreeningResponse)
def post_route_screening(request: RouteScreeningRequest) -> RouteScreeningResponse:
    """
    Calculate preliminary route screening between start and destination coordinates.
    Snaps to nearest road network nodes, removes screening-positive segments by default,
    and returns Dijkstra shortest route geometry with segment count and diagnostic warnings.
    """
    return calculate_screening_route(request)


# Phase 9: Geospatial Export Endpoints

@app.get("/api/export/{layer}")
def get_export_layer(
    layer: str,
    format: str = "geojson",
    exposure_filter: str = "all",
    hazard_source: str = "sample_hidkal",
    threshold: float = 0.0,
) -> Response:
    """
    Export whitelisted spatial layer (assets, roads) as GeoJSON, KML, or ESRI Shapefile (ZIP).
    Route export is not supported via GET; use POST /api/export/route or POST /api/export.
    Applies exposure filtering (all, screening_positive, not_exposed, not_assessed).
    Never accepts or exposes arbitrary filesystem paths.
    """
    if layer.lower() == "route":
        raise HTTPException(
            status_code=422,
            detail="Route export is not supported via GET. Use POST /api/export/route or POST /api/export with RouteScreeningRequest parameters.",
        )
    return handle_export(
        layer=layer,
        format_type=format,
        exposure_filter=exposure_filter,
        hazard_source=hazard_source,
        threshold=threshold,
    )


@app.post("/api/export/route")
def post_export_route(request: ExportRouteRequest) -> Response:
    """
    Export screened route as GeoJSON, KML, or ESRI Shapefile (ZIP) by recomputing
    the shortest route from the validated RouteScreeningRequest parameters.
    """
    return handle_export(
        layer="route",
        format_type=request.format,
        exposure_filter="all",
        route_request=request.route_request,
        hazard_source=request.hazard_source or "sample_hidkal",
        threshold=request.screening_threshold or 0.0,
    )


@app.post("/api/export")
def post_export_custom(request: ExportRequest) -> Response:
    """
    Export spatial layer (assets, roads, route) as GeoJSON, KML, or ESRI Shapefile (ZIP).
    For route export, route_request parameters must be supplied to recompute route.
    """
    return handle_export(
        layer=request.layer,
        format_type=request.format,
        exposure_filter=request.exposure_filter or "all",
        route_request=request.route_request,
        hazard_source=request.hazard_source or "sample_hidkal",
        threshold=request.screening_threshold or 0.0,
    )


# Phase 10: Scenario Management Endpoints

@app.get("/api/scenarios", response_model=List[ScenarioResponse])
def get_scenarios(include_archived: bool = False) -> List[ScenarioResponse]:
    """List all stored scenarios with snapshot checksums and verification status."""
    return list_scenarios(include_archived=include_archived)


@app.post("/api/scenarios", response_model=ScenarioResponse)
def post_scenario(request: ScenarioCreateRequest) -> ScenarioResponse:
    """Create a new dam breach hydrodynamic scenario with UUID v4 and assumption tracking."""
    return create_scenario(request)


@app.get("/api/scenarios/{scenario_id}", response_model=ScenarioResponse)
def get_scenario_by_id(scenario_id: str) -> ScenarioResponse:
    """Retrieve details for a specific scenario by UUID."""
    return get_scenario(scenario_id)


@app.put("/api/scenarios/{scenario_id}", response_model=ScenarioResponse)
def put_scenario_by_id(scenario_id: str, request: ScenarioUpdateRequest) -> ScenarioResponse:
    """Update an existing scenario, auto-incrementing its revision number."""
    return update_scenario(scenario_id, request)


@app.post("/api/scenarios/{scenario_id}/clone", response_model=ScenarioResponse)
def post_clone_scenario(scenario_id: str) -> ScenarioResponse:
    """Clone an existing scenario with a new UUID v4 and revision 1."""
    return clone_scenario(scenario_id)


@app.post("/api/scenarios/{scenario_id}/archive", response_model=ScenarioResponse)
def post_archive_scenario(scenario_id: str) -> ScenarioResponse:
    """Mark a scenario as archived without deleting its data."""
    return archive_scenario(scenario_id, archive=True)


@app.post("/api/scenarios/{scenario_id}/unarchive", response_model=ScenarioResponse)
def post_unarchive_scenario(scenario_id: str) -> ScenarioResponse:
    """Restore an archived scenario to active status."""
    return archive_scenario(scenario_id, archive=False)


# Phase 11: Delft3D Capabilities & Simulation Endpoints

@app.get("/api/simulation/capabilities", response_model=SimulationCapabilitiesResponse)
def get_simulation_capabilities() -> SimulationCapabilitiesResponse:
    """
    Check local availability of HydroMT-Delft3D FM and D-Flow FM simulation engine.
    Returns honest availability badges, execution gating status, and setup instructions.
    """
    return detect_capabilities()


@app.post("/api/scenarios/{scenario_id}/build-package", response_model=ModelPackageResponse)
def post_build_model_package(scenario_id: str) -> ModelPackageResponse:
    """
    Generate downloadable Delft3D FM draft model package ZIP archive containing
    immutable manifest, SHA-256 checksums, config templates, and requirements documentation.
    """
    response, _ = build_model_package(scenario_id)
    return response


@app.get("/api/scenarios/{scenario_id}/download-package")
def get_download_model_package(scenario_id: str):
    """Download the built Delft3D FM draft model package ZIP archive."""
    zip_path = get_package_zip_path(scenario_id)
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=zip_path.name,
    )


@app.post("/api/scenarios/{scenario_id}/run", response_model=SimulationRunResponse)
def post_run_simulation(scenario_id: str, request: Optional[SimulationRunRequest] = None) -> SimulationRunResponse:
    """
    Execute D-Flow FM simulation strictly gated by server policy.
    Returns 409 Conflict if execution is disabled or solver binary is missing.
    Never fakes a simulation run or labels sample rasters as Delft3D output.
    """
    notes = request.custom_notes if request else ""
    return execute_simulation_run(scenario_id, custom_notes=notes or "")


@app.get("/api/runs", response_model=List[SimulationRunResponse])
def get_runs() -> List[SimulationRunResponse]:
    """List historical simulation runs from runtime storage."""
    return list_simulation_runs()


@app.get("/api/runs/{run_id}", response_model=SimulationRunResponse)
def get_run_by_id(run_id: str) -> SimulationRunResponse:
    """Retrieve status and metadata for a specific simulation run."""
    return get_simulation_run(run_id)


@app.get("/api/runs/{run_id}/logs", response_model=SimulationLogResponse)
def get_run_logs(run_id: str) -> SimulationLogResponse:
    """Retrieve captured stdout and stderr execution logs for a simulation run."""
    return get_simulation_logs(run_id)


# ==========================================
# Phase 12: SPH (PySPH) Solver Endpoints
# ==========================================

@app.get("/api/sph/capabilities", response_model=SPHCapabilitiesResponse)
def get_sph_capabilities() -> SPHCapabilitiesResponse:
    """Detect PySPH solver environment and execution policy."""
    return check_sph_capabilities()


@app.post("/api/scenarios/{scenario_id}/build-sph-package", response_model=SPHPackageResponse)
def post_build_sph_package(scenario_id: str) -> SPHPackageResponse:
    """Generate downloadable PySPH 2D benchmark model package ZIP archive."""
    response, _ = build_sph_package(scenario_id)
    return response


@app.get("/api/scenarios/{scenario_id}/download-sph-package")
def get_download_sph_package(scenario_id: str):
    """Download the built PySPH benchmark package ZIP archive."""
    zip_path = get_sph_package_zip_path(scenario_id)
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=zip_path.name,
    )


@app.post("/api/scenarios/{scenario_id}/run-sph", response_model=SPHRunResponse)
def post_run_sph(scenario_id: str, request: Optional[SPHRunRequest] = None) -> SPHRunResponse:
    """
    Execute PySPH simulation strictly gated by server policy.
    Returns 409 Conflict if execution is disabled or PySPH is missing.
    """
    return execute_sph_run(scenario_id, req=request)


@app.get("/api/sph-runs", response_model=List[SPHRunResponse])
def get_sph_runs_list() -> List[SPHRunResponse]:
    """List historical SPH simulation runs."""
    return list_sph_runs()


@app.get("/api/sph-runs/{run_id}", response_model=SPHRunResponse)
def get_sph_run_by_id(run_id: str) -> SPHRunResponse:
    """Retrieve status and metadata for a specific SPH run."""
    return get_sph_run(run_id)


@app.get("/api/sph-runs/{run_id}/logs", response_model=SimulationLogResponse)
def get_sph_run_logs(run_id: str) -> SimulationLogResponse:
    """Retrieve captured stdout and stderr execution logs for an SPH run."""
    return get_sph_logs(run_id)


# ==========================================
# Phase 12: Multi-Engine Comparison Endpoints
# ==========================================

@app.get("/api/comparison/readiness", response_model=ComparisonReadinessResponse)
def get_comparison_readiness() -> ComparisonReadinessResponse:
    """Check readiness of Delft3D FM and PySPH runs for physical hydrodynamic comparison."""
    return check_comparison_readiness()


@app.get("/api/comparison/methodology", response_model=MethodologyComparisonResponse)
def get_comparison_methodology() -> MethodologyComparisonResponse:
    """Retrieve structured architectural and physical methodology matrix."""
    return get_methodology_comparison()


@app.post("/api/comparison/compare", response_model=ComparisonResponse)
def post_compare_runs(request: ComparisonRequest) -> ComparisonResponse:
    """
    Execute quantitative spatial comparison between Delft3D and PySPH runs.
    Returns comparison_unavailable if runs are missing or units unverified.
    """
    return compare_runs(
        delft3d_run_id=request.delft3d_run_id,
        sph_run_id=request.sph_run_id,
        reproject_crs=request.reproject_crs or "EPSG:4326",
    )


# ==========================================
# Phase 12: Google Earth Engine Connector Endpoints
# ==========================================

@app.get("/api/gee/capabilities", response_model=GEECapabilitiesResponse)
def get_gee_capabilities() -> GEECapabilitiesResponse:
    """Detect Earth Engine connector capabilities and authentication status."""
    return check_gee_capabilities()


@app.get("/api/gee/datasets", response_model=List[GEEDatasetInfo])
def get_gee_datasets() -> List[GEEDatasetInfo]:
    """List approved whitelisted Earth Engine datasets."""
    return list_whitelisted_datasets()


@app.get("/api/gee/datasets/{dataset_id:path}", response_model=GEEDatasetInfo)
def get_gee_dataset(dataset_id: str) -> GEEDatasetInfo:
    """Retrieve metadata for a specific whitelisted Earth Engine dataset."""
    info = get_dataset_info(dataset_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found in approved Earth Engine whitelist.")
    return info


@app.post("/api/gee/export-plan", response_model=GEEExportPlanResponse)
def post_gee_export_plan(request: GEEExportPlanRequest) -> GEEExportPlanResponse:
    """
    Generate an Earth Engine export plan or candidate observation query.
    Returns dry-run plan if unauthenticated or task submission is disabled.
    """
    try:
        return create_export_plan(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==========================================
# Dam Project Onboarding & Dataset Validation (SIH PS 26161)
# ==========================================

@app.post("/api/dam-projects/validate", response_model=DamProjectValidationResponse)
async def post_validate_dam_project(
    dem_file: UploadFile = File(..., description="DEM GeoTIFF file (.tif or .tiff)"),
    dam_axis_file: UploadFile = File(..., description="Dam axis alignment GeoJSON file (.geojson or .json)"),
    reservoir_boundary_file: Optional[UploadFile] = File(default=None, description="Optional reservoir pool boundary GeoJSON (.geojson or .json)"),
    model_domain_file: Optional[UploadFile] = File(default=None, description="Optional model domain computational boundary GeoJSON (.geojson or .json)"),
    downstream_outlet_file: Optional[UploadFile] = File(default=None, description="Optional downstream outlet boundary GeoJSON (.geojson or .json)"),
    project_name: str = Form(default="New Dam Project"),
    vertical_unit: Optional[str] = Form(default=None, description="User-verified vertical elevation unit (e.g. meters)"),
    vertical_datum: Optional[str] = Form(default=None, description="User-verified vertical datum (e.g. MSL, EGM96)"),
    reservoir_level: Optional[float] = Form(default=None, description="Assumed reservoir level / FRL in elevation units"),
    breach_width: Optional[float] = Form(default=None, description="Hypothetical breach width in meters"),
    breach_center_x: Optional[float] = Form(default=None, description="Breach center longitude or X coordinate in geometry_crs"),
    breach_center_y: Optional[float] = Form(default=None, description="Breach center latitude or Y coordinate in geometry_crs"),
    breach_formation_time_hr: Optional[float] = Form(default=1.0, description="Breach formation time in hours"),
    manning_roughness: Optional[float] = Form(default=0.035, description="Channel Manning's roughness coefficient"),
    dam_crest_elevation: Optional[float] = Form(default=None, description="Dam crest elevation in vertical datum units"),
    breach_invert_elevation: Optional[float] = Form(default=None, description="Breach bottom / invert elevation in vertical datum units"),
    target_mesh_resolution_m: Optional[float] = Form(default=None, description="Target computational mesh resolution in meters"),
    simulation_duration_s: Optional[float] = Form(default=None, description="Total simulation duration in seconds"),
    output_interval_s: Optional[float] = Form(default=None, description="Simulation output timestep interval in seconds"),
    geometry_crs: Optional[str] = Form(default="EPSG:4326", description="Coordinate Reference System of input GeoJSON geometries and breach coordinates"),
) -> DamProjectValidationResponse:
    """
    Validate user-uploaded generalized dam/river dataset without running simulation.
    Performs spatial extent checking, CRS verification, geometry validation,
    and parameter safety checks using temporary in-memory storage.
    Breach center coordinates (breach_center_x, breach_center_y) are interpreted in geometry_crs.
    """
    dem_bytes = await dem_file.read()
    dam_axis_bytes = await dam_axis_file.read()
    res_bytes = await reservoir_boundary_file.read() if reservoir_boundary_file else None
    domain_bytes = await model_domain_file.read() if model_domain_file else None
    outlet_bytes = await downstream_outlet_file.read() if downstream_outlet_file else None

    return validate_dam_project_dataset(
        dem_bytes=dem_bytes,
        dem_filename=dem_file.filename or "dem.tif",
        dam_axis_bytes=dam_axis_bytes,
        dam_axis_filename=dam_axis_file.filename or "dam_axis.geojson",
        reservoir_bytes=res_bytes,
        reservoir_filename=reservoir_boundary_file.filename if reservoir_boundary_file else None,
        model_domain_bytes=domain_bytes,
        model_domain_filename=model_domain_file.filename if model_domain_file else None,
        downstream_outlet_bytes=outlet_bytes,
        downstream_outlet_filename=downstream_outlet_file.filename if downstream_outlet_file else None,
        project_name=project_name,
        vertical_unit=vertical_unit,
        vertical_datum=vertical_datum,
        reservoir_level=reservoir_level,
        breach_width=breach_width,
        breach_center_x=breach_center_x,
        breach_center_y=breach_center_y,
        breach_formation_time_hr=breach_formation_time_hr,
        manning_roughness=manning_roughness,
        dam_crest_elevation=dam_crest_elevation,
        breach_invert_elevation=breach_invert_elevation,
        target_mesh_resolution_m=target_mesh_resolution_m,
        simulation_duration_s=simulation_duration_s,
        output_interval_s=output_interval_s,
        geometry_crs=geometry_crs or "EPSG:4326",
    )


@app.post(
    "/api/dam-projects",
    response_model=DamProjectDetailResponse,
    summary="Register and persist custom dam project dataset",
    description="Validates and atomically persists an onboarding dam dataset under runtime storage.",
)
async def create_dam_project_endpoint(
    dem_file: UploadFile = File(..., description="DEM GeoTIFF raster (*.tif, *.tiff)"),
    dam_axis_file: UploadFile = File(..., description="Dam axis vector GeoJSON (*.geojson, *.json)"),
    reservoir_boundary_file: Optional[UploadFile] = File(default=None, description="Optional reservoir boundary GeoJSON"),
    model_domain_file: Optional[UploadFile] = File(default=None, description="Optional model domain computational boundary GeoJSON"),
    downstream_outlet_file: Optional[UploadFile] = File(default=None, description="Optional downstream outlet boundary GeoJSON"),
    project_name: str = Form(default="New Dam Project", description="Human-readable project title"),
    vertical_unit: Optional[str] = Form(default=None, description="User-verified vertical unit (e.g. meters, feet)"),
    vertical_datum: Optional[str] = Form(default=None, description="User-verified vertical datum (e.g. MSL, EGM96)"),
    reservoir_level: Optional[float] = Form(default=None, description="Assumed reservoir level / FRL in elevation units"),
    breach_width: Optional[float] = Form(default=None, description="Hypothetical breach width in meters"),
    breach_center_x: Optional[float] = Form(default=None, description="Breach center longitude or X coordinate in geometry_crs"),
    breach_center_y: Optional[float] = Form(default=None, description="Breach center latitude or Y coordinate in geometry_crs"),
    breach_formation_time_hr: Optional[float] = Form(default=1.0, description="Breach formation time in hours"),
    manning_roughness: Optional[float] = Form(default=0.035, description="Channel Manning's roughness coefficient"),
    dam_crest_elevation: Optional[float] = Form(default=None, description="Dam crest elevation in vertical datum units"),
    breach_invert_elevation: Optional[float] = Form(default=None, description="Breach bottom / invert elevation in vertical datum units"),
    target_mesh_resolution_m: Optional[float] = Form(default=None, description="Target computational mesh resolution in meters"),
    simulation_duration_s: Optional[float] = Form(default=None, description="Total simulation duration in seconds"),
    output_interval_s: Optional[float] = Form(default=None, description="Simulation output timestep interval in seconds"),
    geometry_crs: Optional[str] = Form(default="EPSG:4326", description="Coordinate Reference System of input GeoJSON geometries"),
    acknowledge_unverified_metadata: bool = Form(default=False, description="User acknowledgment that metadata is unverified"),
) -> DamProjectDetailResponse:
    """
    Persistently register a custom dam dataset after strict validation.
    Generates server-side UUID v4, stores dem.tif, dam_axis.geojson, project.json, and manifest.json.
    """
    dem_bytes = await dem_file.read()
    dam_axis_bytes = await dam_axis_file.read()
    res_bytes = await reservoir_boundary_file.read() if reservoir_boundary_file else None
    domain_bytes = await model_domain_file.read() if model_domain_file else None
    outlet_bytes = await downstream_outlet_file.read() if downstream_outlet_file else None

    return save_dam_project(
        dem_bytes=dem_bytes,
        dem_filename=dem_file.filename or "dem.tif",
        dam_axis_bytes=dam_axis_bytes,
        dam_axis_filename=dam_axis_file.filename or "dam_axis.geojson",
        reservoir_bytes=res_bytes,
        reservoir_filename=reservoir_boundary_file.filename if reservoir_boundary_file else None,
        model_domain_bytes=domain_bytes,
        model_domain_filename=model_domain_file.filename if model_domain_file else None,
        downstream_outlet_bytes=outlet_bytes,
        downstream_outlet_filename=downstream_outlet_file.filename if downstream_outlet_file else None,
        project_name=project_name,
        vertical_unit=vertical_unit,
        vertical_datum=vertical_datum,
        reservoir_level=reservoir_level,
        breach_width=breach_width,
        breach_center_x=breach_center_x,
        breach_center_y=breach_center_y,
        breach_formation_time_hr=breach_formation_time_hr,
        manning_roughness=manning_roughness,
        dam_crest_elevation=dam_crest_elevation,
        breach_invert_elevation=breach_invert_elevation,
        target_mesh_resolution_m=target_mesh_resolution_m,
        simulation_duration_s=simulation_duration_s,
        output_interval_s=output_interval_s,
        geometry_crs=geometry_crs or "EPSG:4326",
        acknowledge_unverified_metadata=acknowledge_unverified_metadata,
    )


@app.get(
    "/api/dam-projects",
    response_model=List[DamProjectSummary],
    summary="List registered custom dam projects",
    description="Returns metadata summaries of all persisted dam projects registered under runtime storage.",
)
def list_dam_projects_endpoint() -> List[DamProjectSummary]:
    return list_dam_projects()


@app.get(
    "/api/dam-projects/{project_id}",
    response_model=DamProjectDetailResponse,
    summary="Get registered dam project details",
    description="Returns complete metadata, file paths, validation results, and manifest for a registered project.",
)
def get_dam_project_endpoint(project_id: str) -> DamProjectDetailResponse:
    return get_dam_project(project_id)


@app.get(
    "/api/dam-projects/{project_id}/dem/metadata",
    response_model=RasterMetadataResponse,
    summary="Get custom project DEM raster metadata",
)
def get_dam_project_dem_metadata_endpoint(project_id: str) -> RasterMetadataResponse:
    return get_dam_project_dem_metadata(project_id)


@app.get(
    "/api/dam-projects/{project_id}/dem/value",
    response_model=RasterPointValueResponse,
    summary="Query point elevation value on custom project DEM",
)
def get_dam_project_dem_point_value_endpoint(
    project_id: str,
    lon: float = Query(..., description="Query longitude in WGS84 degrees"),
    lat: float = Query(..., description="Query latitude in WGS84 degrees"),
) -> RasterPointValueResponse:
    return get_dam_project_dem_point_value(project_id, lon=lon, lat=lat)


@app.get(
    "/api/dam-projects/{project_id}/dem/tiles/{z}/{x}/{y}.png",
    summary="Render custom project DEM Web Mercator map tile",
)
def get_dam_project_dem_tile_endpoint(
    project_id: str,
    z: int,
    x: int,
    y: int,
) -> Response:
    tile_bytes = get_dam_project_dem_tile(project_id, z=z, x=x, y=y)
    return Response(
        content=tile_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get(
    "/api/dam-projects/{project_id}/geometry/dam-axis",
    summary="Get reprojected dam axis vector geometry (EPSG:4326)",
    description="Returns EPSG:4326 GeoJSON FeatureCollection of the user-supplied dam axis.",
)
def get_dam_project_dam_axis_geometry_endpoint(project_id: str) -> Dict[str, Any]:
    return get_dam_project_dam_axis_geometry(project_id)


@app.get(
    "/api/dam-projects/{project_id}/geometry/reservoir",
    summary="Get reprojected reservoir boundary vector geometry (EPSG:4326)",
    description="Returns EPSG:4326 GeoJSON FeatureCollection of the user-supplied reservoir pool boundary.",
)
def get_dam_project_reservoir_geometry_endpoint(project_id: str) -> Dict[str, Any]:
    return get_dam_project_reservoir_geometry(project_id)


@app.get(
    "/api/dam-projects/{project_id}/geometry/breach",
    summary="Get hypothetical breach location Point geometry (EPSG:4326)",
    description="Returns EPSG:4326 GeoJSON FeatureCollection containing a single Point representing the hypothetical breach center.",
)
def get_dam_project_breach_geometry_endpoint(project_id: str) -> Dict[str, Any]:
    return get_dam_project_breach_geometry(project_id)


@app.get(
    "/api/dam-projects/{project_id}/geometry/model-domain",
    summary="Get reprojected model domain boundary vector geometry (EPSG:4326)",
    description="Returns EPSG:4326 GeoJSON FeatureCollection of the user-supplied computational model domain.",
)
def get_dam_project_model_domain_geometry_endpoint(project_id: str) -> Dict[str, Any]:
    return get_dam_project_model_domain_geometry(project_id)


@app.get(
    "/api/dam-projects/{project_id}/geometry/outlet",
    summary="Get reprojected downstream outlet boundary vector geometry (EPSG:4326)",
    description="Returns EPSG:4326 GeoJSON FeatureCollection of the user-supplied downstream outlet boundary.",
)
def get_dam_project_outlet_geometry_endpoint(project_id: str) -> Dict[str, Any]:
    return get_dam_project_outlet_geometry(project_id)


@app.post(
    "/api/dam-projects/{project_id}/anuga/preflight",
    response_model=DamProjectAnugaPreflightResponse,
    summary="Assess simulation-readiness for ANUGA model generation",
    description="Validates project manifest integrity, geometric boundaries, and physical elevations without executing simulations.",
)
def post_anuga_preflight_endpoint(project_id: str) -> DamProjectAnugaPreflightResponse:
    return assess_anuga_preflight(project_id)


@app.post(
    "/api/dam-projects/{project_id}/anuga/build-package",
    response_model=DamProjectAnugaPackageResponse,
    summary="Build reproducible ANUGA simulation package ZIP",
    description="Generates standalone ANUGA hydrodynamic simulation package with manifest, python run script, and validated inputs.",
)
def post_build_anuga_package_endpoint(project_id: str) -> DamProjectAnugaPackageResponse:
    return build_dam_project_anuga_package(project_id)


@app.get(
    "/api/dam-projects/{project_id}/anuga/package",
    summary="Download reproducible ANUGA simulation package ZIP",
    description="Downloads the generated immutable ANUGA package ZIP file containing validated inputs, config, and run script.",
)
def get_anuga_package_zip_endpoint(project_id: str) -> FileResponse:
    zip_path = get_dam_project_anuga_package_path(project_id)
    return FileResponse(
        path=str(zip_path),
        filename=f"dam_project_{project_id[:8]}_anuga_package.zip",
        media_type="application/zip",
    )


@app.get(
    "/api/dam-projects/{project_id}/anuga/capabilities",
    response_model=DamProjectAnugaCapabilitiesResponse,
    summary="Get custom ANUGA execution capability and environment status",
    description="Checks whether custom ANUGA hydrodynamic simulation execution is enabled and verifies the server-side Python environment.",
)
def get_dam_project_anuga_capabilities_endpoint(project_id: str) -> DamProjectAnugaCapabilitiesResponse:
    return get_custom_anuga_capabilities()


@app.post(
    "/api/dam-projects/{project_id}/anuga/runs",
    response_model=DamProjectAnugaRunResponse,
    summary="Execute custom ANUGA hydrodynamic simulation run",
    description="Queues a strictly-gated, isolated ANUGA simulation run for an onboarded dam project after validating user acknowledgments and package integrity.",
)
def post_dam_project_anuga_run_endpoint(
    project_id: str,
    request: DamProjectAnugaRunRequest,
) -> DamProjectAnugaRunResponse:
    return create_dam_project_anuga_run(project_id, request)


@app.get(
    "/api/dam-projects/{project_id}/anuga/runs",
    response_model=List[DamProjectAnugaRunResponse],
    summary="List execution runs for an onboarded dam project",
    description="Retrieves all historical ANUGA simulation execution runs for a custom dam project.",
)
def get_dam_project_anuga_runs_endpoint(project_id: str) -> List[DamProjectAnugaRunResponse]:
    return list_dam_project_anuga_runs(project_id)


@app.get(
    "/api/dam-projects/{project_id}/anuga/runs/{run_id}",
    response_model=DamProjectAnugaRunResponse,
    summary="Get specific ANUGA execution run status",
    description="Retrieves the detailed progress, timestamps, output file hashes, and exit status for a specific ANUGA execution run.",
)
def get_dam_project_anuga_run_by_id_endpoint(project_id: str, run_id: str) -> DamProjectAnugaRunResponse:
    return get_dam_project_anuga_run(project_id, run_id)


@app.get(
    "/api/dam-projects/{project_id}/anuga/runs/{run_id}/logs",
    response_class=PlainTextResponse,
    summary="Get sanitized execution logs for an ANUGA run",
    description="Retrieves the sanitized execution log stream from the isolated ANUGA run workspace.",
)
def get_dam_project_anuga_run_logs_endpoint(project_id: str, run_id: str) -> PlainTextResponse:
    logs = get_dam_project_anuga_run_logs(project_id, run_id)
    return PlainTextResponse(content=logs, media_type="text/plain")


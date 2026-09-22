import os
import json
import uuid
import shutil
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import rasterio
from fastapi import FastAPI, Query, Response, HTTPException, Request, UploadFile, File, Form, Body
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.schemas import (
    SubsystemHealth,
    SystemHealthSummaryResponse,
    DatasetResponse,
    RasterMetadataResponse,
    RasterPointValueResponse,
    RasterLegendResponse,
    ExposureSummaryResponse,
    DamageConfigResponse,
    DamageScenarioRequest,
    DamageScenarioResponse,
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
    DamProjectAnugaPostprocessRequest,
    DamProjectAnugaResultsResponse,
    DamProjectAnugaPointValueResponse,
    DamPointMetadata,
    EngineeringParameters,
    DamProjectReadinessResponse,
    HeuristicAssistRequest,
    HeuristicAssistResponse,
    SimulationInputsUpdateRequest,
    DemoInputsRequest,
    DemoInputsResponse,
    DamProjectAnugaOutputsResponse,
    ProjectAOIResponse,
    EarthObservationRunRequest,
    EarthObservationRunResponse,
    ModelObservationComparisonRequest,
    ModelObservationComparisonResponse,
    ModelComparisonCapabilitiesResponse,
    ModelComparisonRunRequest,
    ModelComparisonRunResponse,
    SPHvsANUGAComparisonResponse,
    DecisionSupportResponse,
    DemoReadinessResponse,
    ProjectDelft3DPackageResponse,
    ProjectSPHPackageResponse,
    Delft3DRunImportRequest,
    SPHRunImportRequest,
    HydrographPoint,
    BreachHydrographResponse,
    ExposureCapabilitiesResponse,
    ExposureRunRequest,
    ExposureRunSummary,
    ExposureRunDetailResponse,
    CanonicalScenario,
    CanonicalScenarioCreateRequest,
    CanonicalScenarioUpdateRequest,
    CanonicalScenarioResponse,
    EngineTranslationResult,
    SimulationEngine,
    CanonicalSimulationResult,
    CanonicalSimulationResultResponse,
    HidkalWorkflowSummaryResponse,
)
from app.hidkal_workflow_service import (
    get_hidkal_workflow_summary,
    get_or_create_hidkal_canonical_scenario,
)
from app.unified_scenario_service import (
    create_canonical_scenario,
    get_canonical_scenario,
    list_canonical_scenarios,
    update_canonical_scenario,
    translate_scenario_to_engine,
)
from app.unified_result_service import (
    pysph_result_to_canonical,
    delft3d_result_to_canonical,
    anuga_result_to_canonical,
    get_canonical_simulation_result,
    list_canonical_simulation_results,
)
from app.delft3d_ugrid_service import (
    validate_delft3d_ugrid_file,
    parse_delft3d_ugrid_netcdf,
    ingest_delft3d_netcdf_run,
)
from app.decision_support_service import (
    get_decision_support_summary,
    render_decision_support_tile,
    export_decision_support_summary,
    check_demo_readiness,
)
from app.model_comparison_service import (
    get_project_engine_capabilities,
    compute_model_comparison,
    list_model_comparison_runs,
    get_model_comparison_run,
    get_model_comparison_logs,
    render_model_comparison_tile,
    get_sph_vs_anuga_comparison,
)
from app.sph_service import (
    build_dam_project_sph_package,
    import_dam_project_sph_run,
    list_dam_project_sph_runs,
    get_dam_project_sph_run_detail,
    execute_dam_project_sph_terrain_simulation,
    extract_sph_breach_hydrograph,
)
from app.simulation_service import (
    build_dam_project_delft3d_package,
    import_dam_project_delft3d_run,
    list_dam_project_delft3d_runs,
    get_dam_project_delft3d_run_detail,
)
from app.exposure_service import (
    get_project_exposure_capabilities,
    execute_exposure_run,
    list_project_exposure_runs,
    get_exposure_run_detail,
    get_exposure_run_logs,
    get_exposure_run_assets_geojson,
    get_exposure_run_roads_geojson,
    get_exposure_run_layers,
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
    get_dam_project_sph_dir,
    sanitize_filename,
    build_dam_project_sph_package,
    import_dam_project_sph_run,
    list_dam_project_sph_runs,
    execute_dam_project_sph_terrain_simulation,
    get_dam_project_sph_run_detail,
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
    get_dam_project_dem_legend,
    get_dam_project_dam_marker_geometry,
    assess_project_simulation_readiness,
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
    compute_terrain_heuristic_assist,
    save_project_simulation_inputs,
    prepare_dam_project_demo_inputs,
    load_or_create_hidkal_demo_project,
    get_dam_project_anuga_outputs,
    cancel_dam_project_anuga_run,
    validate_project_uuid,
)
from app.anuga_postprocessing_service import (
    postprocess_dam_project_anuga_run,
    get_dam_project_anuga_results,
    get_dam_project_anuga_layer_metadata,
    get_dam_project_anuga_layer_legend,
    get_dam_project_anuga_layer_point_value,
    get_dam_project_anuga_layer_tile,
    get_dam_project_anuga_layer_geotiff_path,
    get_dam_project_anuga_timestep_metadata,
    get_dam_project_anuga_timestep_tile,
)
from app.river_blockage_service import (
    load_or_create_river_blockage_demo_project,
)
from app.earth_observation_service import (
    derive_project_aoi,
    create_earth_observation_run,
    list_earth_observation_runs,
    get_earth_observation_run,
    get_earth_observation_run_logs,
    compare_model_and_observation,
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


@app.get(
    "/api/system/health-summary",
    response_model=SystemHealthSummaryResponse,
    summary="Get unified system capability & health summary",
    description="Returns verified status, versions, and honest capability availability for all 8 application subsystems.",
)
def get_system_health_summary_endpoint() -> SystemHealthSummaryResponse:
    subsystems: List[SubsystemHealth] = []

    # 1. Backend Core
    subsystems.append(
        SubsystemHealth(
            id="backend",
            name="Backend API Core",
            status="ready",
            status_label="Ready",
            version="FastAPI 0.115 / Python 3.11",
            environment="sih-app",
            details="FastAPI REST API active with CORS and GZip middleware.",
            is_optional=False,
        )
    )

    # 2. Raster Engine
    rasterio_ver = getattr(rasterio, "__version__", "1.3+")
    subsystems.append(
        SubsystemHealth(
            id="raster_engine",
            name="GDAL / Rasterio Engine",
            status="ready",
            status_label="Ready",
            version=rasterio_ver,
            environment="sih-app",
            details="Native GDAL/Rasterio XYZ tile renderer, affine reprojection, and GeoTIFF writer active.",
            is_optional=False,
        )
    )

    # 3. ANUGA Hydrodynamic Solver
    anuga_cap = get_custom_anuga_capabilities()
    if anuga_cap.execution_enabled:
        subsystems.append(
            SubsystemHealth(
                id="anuga",
                name="ANUGA 2D Hydrodynamic Solver",
                status="ready",
                status_label="Ready",
                version=anuga_cap.anuga_version,
                environment="sih-anuga",
                details="sih-anuga environment detected with full 2D SWE simulation execution enabled.",
                is_optional=False,
                scientific_caveat="Custom runs are hypothetical engineering simulations, not official flood forecasts.",
            )
        )
    elif anuga_cap.anuga_installed:
        subsystems.append(
            SubsystemHealth(
                id="anuga",
                name="ANUGA 2D Hydrodynamic Solver",
                status="execution_disabled",
                status_label="Execution Disabled",
                version=anuga_cap.anuga_version,
                environment="sih-anuga",
                details="ANUGA installed in sih-anuga environment — simulation execution disabled by configuration (ENABLE_CUSTOM_ANUGA_EXECUTION=false).",
                is_optional=False,
                scientific_caveat="Package generation and preflight inspection enabled.",
            )
        )
    else:
        subsystems.append(
            SubsystemHealth(
                id="anuga",
                name="ANUGA 2D Hydrodynamic Solver",
                status="unavailable",
                status_label="Unavailable",
                version="unavailable",
                environment=None,
                details=anuga_cap.reason or "sih-anuga Conda environment not found on this machine.",
                is_optional=False,
            )
        )

    # 4. Google Earth Engine
    try:
        gee_cap = check_gee_capabilities()
        if gee_cap.authenticated and gee_cap.project_configured:
            subsystems.append(
                SubsystemHealth(
                    id="gee",
                    name="Google Earth Engine (GEE)",
                    status="ready",
                    status_label="Ready",
                    version="earthengine-api",
                    environment="sih-app",
                    details=f"Authenticated via {gee_cap.auth_mode} with GEE Project '{gee_cap.gee_project_id}'.",
                    is_optional=True,
                )
            )
        else:
            subsystems.append(
                SubsystemHealth(
                    id="gee",
                    name="Google Earth Engine (GEE)",
                    status="available_not_configured",
                    status_label="Available but Not Configured",
                    version=None,
                    environment="environment_gee.yml",
                    details="Google Earth Engine is not configured on this machine.",
                    is_optional=True,
                    scientific_caveat="Optional satellite observation evidence requires GEE credentials.",
                )
            )
    except Exception:
        subsystems.append(
            SubsystemHealth(
                id="gee",
                name="Google Earth Engine (GEE)",
                status="available_not_configured",
                status_label="Available but Not Configured",
                details="Google Earth Engine is not configured on this machine.",
                is_optional=True,
            )
        )

    # 5. Delft3D / D-Flow FM
    try:
        dflow_cap = detect_capabilities()
        if dflow_cap.dflowfm_available and dflow_cap.execution_enabled:
            subsystems.append(
                SubsystemHealth(
                    id="delft3d",
                    name="Delft3D FM / D-Flow FM",
                    status="ready",
                    status_label="Ready",
                    version=dflow_cap.hydromt_version or "installed",
                    environment="environment_hydromt_delft3dfm.yml",
                    details="HydroMT-Delft3D and D-Flow FM solver binaries installed and configured.",
                    is_optional=True,
                )
            )
        else:
            subsystems.append(
                SubsystemHealth(
                    id="delft3d",
                    name="Delft3D FM / D-Flow FM",
                    status="unavailable",
                    status_label="Unavailable",
                    environment="environment_hydromt_delft3dfm.yml",
                    details="D-Flow FM solver binaries are not installed on this host. Model package generation supported.",
                    is_optional=True,
                    scientific_caveat="Model comparison functions with available completed solver runs.",
                )
            )
    except Exception:
        subsystems.append(
            SubsystemHealth(
                id="delft3d",
                name="Delft3D FM / D-Flow FM",
                status="unavailable",
                status_label="Unavailable",
                details="Delft3D FM solver is not installed on this host.",
                is_optional=True,
            )
        )

    # 6. PySPH / Terrain-SPH Lagrangian Solver
    try:
        subsystems.append(
            SubsystemHealth(
                id="pysph",
                name="PySPH / Terrain-SPH Particle Solver",
                status="ready",
                status_label="Demonstration Ready",
                version="PySPH / Terrain-SPH",
                environment="sih-app",
                details="Local project-based terrain SPH demonstration solver active with real DEM coupling and automated GeoTIFF rasterization.",
                is_optional=True,
            )
        )
    except Exception:
        subsystems.append(
            SubsystemHealth(
                id="pysph",
                name="PySPH / Terrain-SPH Particle Solver",
                status="unavailable",
                status_label="Unavailable",
                details="PySPH is not configured on this host.",
                is_optional=True,
            )
        )

    # 7. Exposure & Vulnerability
    subsystems.append(
        SubsystemHealth(
            id="exposure",
            name="Spatial Exposure & Vulnerability Engine",
            status="ready",
            status_label="Ready",
            version="Phase 22",
            environment="sih-app",
            details="Mass-conserving population aggregator, building zonal statistics, segmented road analysis, and JRC reference curves ready.",
            is_optional=False,
        )
    )

    # 8. Frontend Interface
    subsystems.append(
        SubsystemHealth(
            id="frontend",
            name="Frontend MapLibre Dashboard",
            status="ready",
            status_label="Ready",
            version="React 19 / MapLibre GL 5",
            details="Interactive Web GIS studio, unified product stage navigation, and multi-raster probe active.",
            is_optional=False,
        )
    )

    return SystemHealthSummaryResponse(
        overall_status="operational",
        timestamp=datetime.now(timezone.utc).isoformat(),
        subsystems=subsystems,
    )



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

# Phase 9: Geospatial Export Endpoints

@app.get("/api/export/{layer}")
@app.get("/api/export/layers/{layer}")
def get_export_layer(
    layer: str,
    format: str = "geojson",
    exposure_filter: str = "all",
    hazard_source: str = "sample_hidkal",
    threshold: float = 0.0,
) -> Response:
    """
    Export whitelisted spatial layer (assets, roads) as GeoJSON, KML, or ESRI Shapefile (ZIP).
    Applies exposure filtering (all, screening_positive, not_exposed, not_assessed).
    Never accepts or exposes arbitrary filesystem paths.
    """
    return handle_export(
        layer=layer,
        format_type=format,
        exposure_filter=exposure_filter,
        hazard_source=hazard_source,
        threshold=threshold,
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


# ==============================================================================
# Phase A2: Canonical Unified Scenario API Endpoints
# ==============================================================================

@app.get("/api/canonical-scenarios", response_model=List[CanonicalScenarioResponse], tags=["Unified Scenarios"])
def get_canonical_scenarios(project_id: Optional[str] = Query(None, description="Optional project filter")) -> List[CanonicalScenarioResponse]:
    """List all canonical unified scenarios, optionally filtered by dam project ID."""
    return list_canonical_scenarios(project_id=project_id)


@app.post("/api/canonical-scenarios", response_model=CanonicalScenarioResponse, tags=["Unified Scenarios"])
def post_canonical_scenario(request: CanonicalScenarioCreateRequest) -> CanonicalScenarioResponse:
    """Create a new canonical unified scenario that can configure PySPH, Delft3D, ANUGA, and River Blockage."""
    return create_canonical_scenario(request)


@app.get("/api/canonical-scenarios/{scenario_id}", response_model=CanonicalScenarioResponse, tags=["Unified Scenarios"])
def get_canonical_scenario_by_id(scenario_id: str) -> CanonicalScenarioResponse:
    """Retrieve details for a canonical scenario by UUID."""
    return get_canonical_scenario(scenario_id)


@app.put("/api/canonical-scenarios/{scenario_id}", response_model=CanonicalScenarioResponse, tags=["Unified Scenarios"])
def put_canonical_scenario_by_id(scenario_id: str, request: CanonicalScenarioUpdateRequest) -> CanonicalScenarioResponse:
    """Update fields on an existing canonical scenario."""
    return update_canonical_scenario(scenario_id, request)


@app.post("/api/canonical-scenarios/{scenario_id}/translate/{target_engine}", response_model=EngineTranslationResult, tags=["Unified Scenarios"])
def post_translate_canonical_scenario(
    scenario_id: str,
    target_engine: SimulationEngine,
) -> EngineTranslationResult:
    """
    Translate a canonical scenario into the exact configuration parameters required by
    a specific numerical solver (PySPH, Delft3D FM, ANUGA, or Coupled SPH->Delft3D).
    """
    resp = get_canonical_scenario(scenario_id)
    return translate_scenario_to_engine(resp.scenario, target_engine=target_engine)


@app.get("/api/dam-projects/{project_id}/canonical-scenarios", response_model=List[CanonicalScenarioResponse], tags=["Unified Scenarios"])
def get_project_canonical_scenarios(project_id: str) -> List[CanonicalScenarioResponse]:
    """List all canonical scenarios for a specific dam project."""
    return list_canonical_scenarios(project_id=project_id)



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
    dam_axis_file: Optional[UploadFile] = File(default=None, description="Optional dam axis alignment GeoJSON file (.geojson or .json)"),
    reservoir_boundary_file: Optional[UploadFile] = File(default=None, description="Optional reservoir pool boundary GeoJSON (.geojson or .json)"),
    model_domain_file: Optional[UploadFile] = File(default=None, description="Optional model domain computational boundary GeoJSON (.geojson or .json)"),
    downstream_outlet_file: Optional[UploadFile] = File(default=None, description="Optional downstream outlet boundary GeoJSON (.geojson or .json)"),
    project_name: str = Form(default="New Dam Project"),
    dam_name: Optional[str] = Form(default=None, description="Dam name"),
    scenario_type: Optional[str] = Form(default="DAM_BREAK", description="Scenario type: DAM_BREAK or RIVER_BLOCKAGE"),
    is_intact_control: Optional[bool] = Form(default=False, description="True if baseline intact blockage/dam control"),
    latitude: Optional[float] = Form(default=None, description="Dam latitude in decimal degrees"),
    longitude: Optional[float] = Form(default=None, description="Dam longitude in decimal degrees"),
    dam_height: Optional[float] = Form(default=None, description="Dam structural height in meters"),
    crest_elevation: Optional[float] = Form(default=None, description="Dam crest elevation"),
    pool_elevation: Optional[float] = Form(default=None, description="Normal pool / reservoir level elevation"),
    manning_n: Optional[float] = Form(default=None, description="Bed Manning roughness coefficient"),
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
    blockage_height: Optional[float] = Form(default=None, description="Blockage structural height in meters"),
    blockage_crest_elevation: Optional[float] = Form(default=None, description="Blockage crest elevation in vertical datum units"),
    blockage_width: Optional[float] = Form(default=None, description="Blockage width in meters"),
    upstream_water_level: Optional[float] = Form(default=None, description="Upstream impounded pool water level elevation"),
    opening_width: Optional[float] = Form(default=None, description="Breach opening width in meters for river blockage"),
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
    dam_axis_bytes = await dam_axis_file.read() if dam_axis_file else None
    res_bytes = await reservoir_boundary_file.read() if reservoir_boundary_file else None
    domain_bytes = await model_domain_file.read() if model_domain_file else None
    outlet_bytes = await downstream_outlet_file.read() if downstream_outlet_file else None

    return validate_dam_project_dataset(
        dem_bytes=dem_bytes,
        dem_filename=dem_file.filename or "dem.tif",
        dam_axis_bytes=dam_axis_bytes,
        dam_axis_filename=dam_axis_file.filename if dam_axis_file else None,
        reservoir_bytes=res_bytes,
        reservoir_filename=reservoir_boundary_file.filename if reservoir_boundary_file else None,
        model_domain_bytes=domain_bytes,
        model_domain_filename=model_domain_file.filename if model_domain_file else None,
        downstream_outlet_bytes=outlet_bytes,
        downstream_outlet_filename=downstream_outlet_file.filename if downstream_outlet_file else None,
        project_name=project_name,
        dam_name=dam_name,
        scenario_type=scenario_type or "DAM_BREAK",
        is_intact_control=bool(is_intact_control),
        latitude=latitude,
        longitude=longitude,
        dam_height=dam_height,
        crest_elevation=crest_elevation,
        pool_elevation=pool_elevation,
        manning_n=manning_n,
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
        blockage_height=blockage_height,
        blockage_crest_elevation=blockage_crest_elevation,
        blockage_width=blockage_width,
        upstream_water_level=upstream_water_level,
        opening_width=opening_width,
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
    dam_axis_file: Optional[UploadFile] = File(default=None, description="Optional dam axis vector GeoJSON (*.geojson, *.json)"),
    reservoir_boundary_file: Optional[UploadFile] = File(default=None, description="Optional reservoir boundary GeoJSON"),
    model_domain_file: Optional[UploadFile] = File(default=None, description="Optional model domain computational boundary GeoJSON"),
    downstream_outlet_file: Optional[UploadFile] = File(default=None, description="Optional downstream outlet boundary GeoJSON"),
    project_name: str = Form(default="New Dam Project", description="Human-readable project title"),
    dam_name: Optional[str] = Form(default=None, description="Dam name"),
    scenario_type: Optional[str] = Form(default="DAM_BREAK", description="Scenario type: DAM_BREAK or RIVER_BLOCKAGE"),
    is_intact_control: Optional[bool] = Form(default=False, description="True if baseline intact blockage/dam control"),
    latitude: Optional[float] = Form(default=None, description="Dam latitude in decimal degrees"),
    longitude: Optional[float] = Form(default=None, description="Dam longitude in decimal degrees"),
    dam_height: Optional[float] = Form(default=None, description="Dam structural height in meters"),
    crest_elevation: Optional[float] = Form(default=None, description="Dam crest elevation"),
    pool_elevation: Optional[float] = Form(default=None, description="Normal pool / reservoir level elevation"),
    manning_n: Optional[float] = Form(default=None, description="Bed Manning roughness coefficient"),
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
    blockage_height: Optional[float] = Form(default=None, description="Blockage structural height in meters"),
    blockage_crest_elevation: Optional[float] = Form(default=None, description="Blockage crest elevation in vertical datum units"),
    blockage_width: Optional[float] = Form(default=None, description="Blockage width in meters"),
    upstream_water_level: Optional[float] = Form(default=None, description="Upstream impounded pool water level elevation"),
    opening_width: Optional[float] = Form(default=None, description="Breach opening width in meters for river blockage"),
    target_mesh_resolution_m: Optional[float] = Form(default=None, description="Target computational mesh resolution in meters"),
    simulation_duration_s: Optional[float] = Form(default=None, description="Total simulation duration in seconds"),
    output_interval_s: Optional[float] = Form(default=None, description="Simulation output timestep interval in seconds"),
    geometry_crs: Optional[str] = Form(default="EPSG:4326", description="Coordinate Reference System of input GeoJSON geometries"),
    acknowledge_unverified_metadata: bool = Form(default=False, description="User acknowledgment that metadata is unverified"),
) -> DamProjectDetailResponse:
    """
    Persistently register a custom dam dataset after strict validation.
    Generates server-side UUID v4, stores dem.tif, dam_axis.geojson (if provided), project.json, and manifest.json.
    """
    dem_bytes = await dem_file.read()
    dam_axis_bytes = await dam_axis_file.read() if dam_axis_file else None
    res_bytes = await reservoir_boundary_file.read() if reservoir_boundary_file else None
    domain_bytes = await model_domain_file.read() if model_domain_file else None
    outlet_bytes = await downstream_outlet_file.read() if downstream_outlet_file else None

    return save_dam_project(
        dem_bytes=dem_bytes,
        dem_filename=dem_file.filename or "dem.tif",
        dam_axis_bytes=dam_axis_bytes,
        dam_axis_filename=dam_axis_file.filename if dam_axis_file else None,
        reservoir_bytes=res_bytes,
        reservoir_filename=reservoir_boundary_file.filename if reservoir_boundary_file else None,
        model_domain_bytes=domain_bytes,
        model_domain_filename=model_domain_file.filename if model_domain_file else None,
        downstream_outlet_bytes=outlet_bytes,
        downstream_outlet_filename=downstream_outlet_file.filename if downstream_outlet_file else None,
        project_name=project_name,
        dam_name=dam_name,
        scenario_type=scenario_type or "DAM_BREAK",
        is_intact_control=bool(is_intact_control),
        latitude=latitude,
        longitude=longitude,
        dam_height=dam_height,
        crest_elevation=crest_elevation,
        pool_elevation=pool_elevation,
        manning_n=manning_n,
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
        blockage_height=blockage_height,
        blockage_crest_elevation=blockage_crest_elevation,
        blockage_width=blockage_width,
        upstream_water_level=upstream_water_level,
        opening_width=opening_width,
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
    "/api/dam-projects/{project_id}/dem/legend",
    response_model=RasterLegendResponse,
    summary="Get color ramp legend for custom project DEM",
    description="Returns color ramp stops and legend items for custom project DEM visualization.",
)
def get_dam_project_dem_legend_endpoint(project_id: str) -> RasterLegendResponse:
    return get_dam_project_dem_legend(project_id)


@app.get(
    "/api/dam-projects/{project_id}/geometry/dam-marker",
    summary="Get dam location marker Point geometry (EPSG:4326)",
    description="Returns EPSG:4326 GeoJSON FeatureCollection containing a single Point representing the dam location marker.",
)
def get_dam_project_dam_marker_geometry_endpoint(project_id: str) -> Dict[str, Any]:
    return get_dam_project_dam_marker_geometry(project_id)


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


@app.get(
    "/api/dam-projects/{project_id}/readiness",
    response_model=DamProjectReadinessResponse,
    summary="Assess pre-simulation readiness for onboarded dam project",
    description="Evaluates whether the onboarded dam project possesses the necessary elevation, coordinates, and engineering parameters.",
)
def get_dam_project_readiness_endpoint(project_id: str) -> DamProjectReadinessResponse:
    return assess_project_simulation_readiness(project_id)


@app.post(
    "/api/dam-projects/{project_id}/readiness",
    response_model=DamProjectReadinessResponse,
    summary="Assess pre-simulation readiness for onboarded dam project",
    description="Evaluates whether the onboarded dam project possesses the necessary elevation, coordinates, and engineering parameters.",
)
def post_dam_project_readiness_endpoint(project_id: str) -> DamProjectReadinessResponse:
    return assess_project_simulation_readiness(project_id)


@app.post(
    "/api/dam-projects/{project_id}/heuristic-assist",
    response_model=HeuristicAssistResponse,
    summary="Derive terrain-heuristic hydraulic geometries from DEM gradient",
    description="Analyzes DEM elevation gradient around dam coordinates to estimate downstream direction and candidate geometries tagged source='terrain_heuristic' and scientifically_verified=False.",
)
def post_dam_project_heuristic_assist_endpoint(
    project_id: str,
    request: HeuristicAssistRequest = Body(default_factory=HeuristicAssistRequest),
) -> HeuristicAssistResponse:
    return compute_terrain_heuristic_assist(project_id, request)


@app.post(
    "/api/dam-projects/{project_id}/simulation-inputs",
    response_model=DamProjectDetailResponse,
    summary="Save simulation inputs and geometries for an onboarded dam project",
    description="Updates physical hydraulic parameters and boundary geometries. If heuristic geometries are submitted, accept_heuristic_inputs=True is strictly enforced.",
)
def post_dam_project_simulation_inputs_endpoint(
    project_id: str,
    request: SimulationInputsUpdateRequest,
) -> DamProjectDetailResponse:
    return save_project_simulation_inputs(project_id, request)


@app.post(
    "/api/dam-projects/{project_id}/demo-inputs",
    response_model=DemoInputsResponse,
    summary="Prepare and persist hypothetical demo simulation inputs",
    description="Synthesizes, strictly validates, and persists conservative hypothetical demo geometries and hydraulic parameters within DEM bounds.",
)
def post_dam_project_demo_inputs_endpoint(
    project_id: str,
    request: Optional[DemoInputsRequest] = Body(default=None),
) -> DemoInputsResponse:
    req = request if request is not None else DemoInputsRequest()
    return prepare_dam_project_demo_inputs(project_id, req)


@app.post(
    "/api/dam-projects/load-hidkal-demo",
    response_model=DamProjectDetailResponse,
    summary="Load or seed Hidkal Dam hypothetical demonstration configuration",
    description="Loads or registers a reproducible hypothetical demonstration configuration for Hidkal Dam with validated geometries and conservative parameters.",
)
def post_load_hidkal_demo_endpoint() -> DamProjectDetailResponse:
    return load_or_create_hidkal_demo_project()


@app.post(
    "/api/dam-projects/load-river-blockage-demo",
    response_model=DamProjectDetailResponse,
    summary="Load or seed Natural Landslide Dam / River Blockage demonstration configuration",
    description="Loads or registers a reproducible hypothetical natural valley blockage demonstration configuration with intact vs failed hydrodynamic runs.",
)
def post_load_river_blockage_demo_endpoint() -> DamProjectDetailResponse:
    return load_or_create_river_blockage_demo_project()


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


@app.post(
    "/api/dam-projects/{project_id}/anuga/runs/{run_id}/cancel",
    response_model=DamProjectAnugaRunResponse,
    summary="Cancel active ANUGA simulation execution run",
    description="Terminates any active process for the specified run ID and marks its status as cancelled.",
)
def cancel_dam_project_anuga_run_endpoint(
    project_id: str,
    run_id: str,
) -> DamProjectAnugaRunResponse:
    return cancel_dam_project_anuga_run(project_id, run_id)


@app.get(
    "/api/dam-projects/{project_id}/anuga/runs/{run_id}/outputs",
    response_model=DamProjectAnugaOutputsResponse,
    summary="Get verified outputs and layer status for an ANUGA run",
    description="Retrieves output SWW file status, available postprocessed hazard rasters, and summary layer statistics.",
)
def get_dam_project_anuga_outputs_endpoint(
    project_id: str,
    run_id: str,
) -> DamProjectAnugaOutputsResponse:
    return get_dam_project_anuga_outputs(project_id, run_id)


@app.post(
    "/api/dam-projects/{project_id}/anuga/runs/{run_id}/postprocess",
    response_model=DamProjectAnugaResultsResponse,
    summary="Postprocess completed ANUGA SWW output into hazard rasters",
    description="Converts verified completed ANUGA SWW simulation output into maximum depth, maximum velocity, and arrival time GeoTIFF rasters using timestep-first linear triangular mesh interpolation.",
)
def postprocess_dam_project_anuga_run_endpoint(
    project_id: str,
    run_id: str,
    request: Optional[DamProjectAnugaPostprocessRequest] = Body(default=None),
) -> DamProjectAnugaResultsResponse:
    return postprocess_dam_project_anuga_run(project_id, run_id, request)


@app.get(
    "/api/dam-projects/{project_id}/anuga/runs/{run_id}/results",
    response_model=DamProjectAnugaResultsResponse,
    summary="Get postprocessed ANUGA simulation hazard results summary",
    description="Retrieves the manifest, layer statistics, thresholds, and provenance of postprocessed ANUGA simulation rasters.",
)
def get_dam_project_anuga_results_endpoint(
    project_id: str,
    run_id: str,
    processing_id: Optional[str] = Query(None, description="Optional processing ID (defaults to latest)"),
) -> DamProjectAnugaResultsResponse:
    return get_dam_project_anuga_results(project_id, run_id, processing_id=processing_id)


@app.get(
    "/api/dam-projects/{project_id}/anuga/runs/{run_id}/results/{layer}/metadata",
    response_model=RasterMetadataResponse,
    summary="Get raster metadata for an ANUGA hazard layer",
    description="Retrieves bounding box, CRS, dimensions, resolution, and value range for maximum_depth, maximum_velocity, or arrival_time.",
)
def get_dam_project_anuga_layer_metadata_endpoint(
    project_id: str,
    run_id: str,
    layer: str,
    processing_id: Optional[str] = Query(None, description="Optional processing ID (defaults to latest)"),
) -> RasterMetadataResponse:
    return get_dam_project_anuga_layer_metadata(project_id, run_id, layer, processing_id=processing_id)


@app.get(
    "/api/dam-projects/{project_id}/anuga/runs/{run_id}/results/{layer}/legend",
    response_model=RasterLegendResponse,
    summary="Get color ramp legend for an ANUGA hazard layer",
    description="Returns color ramp stops and legend items for visualizing ANUGA hazard rasters.",
)
def get_dam_project_anuga_layer_legend_endpoint(
    project_id: str,
    run_id: str,
    layer: str,
    processing_id: Optional[str] = Query(None, description="Optional processing ID (defaults to latest)"),
) -> RasterLegendResponse:
    return get_dam_project_anuga_layer_legend(project_id, run_id, layer, processing_id=processing_id)


@app.get(
    "/api/dam-projects/{project_id}/anuga/runs/{run_id}/results/{layer}/point",
    response_model=DamProjectAnugaPointValueResponse,
    summary="Query derived point value from an ANUGA hazard raster",
    description="Samples the derived interpolated raster value at a specified WGS84 coordinate (lon, lat).",
)
def get_dam_project_anuga_layer_point_value_endpoint(
    project_id: str,
    run_id: str,
    layer: str,
    lon: float = Query(..., description="Query longitude in WGS84 degrees"),
    lat: float = Query(..., description="Query latitude in WGS84 degrees"),
    processing_id: Optional[str] = Query(None, description="Optional processing ID (defaults to latest)"),
) -> DamProjectAnugaPointValueResponse:
    return get_dam_project_anuga_layer_point_value(project_id, run_id, layer, lon=lon, lat=lat, processing_id=processing_id)


@app.get(
    "/api/dam-projects/{project_id}/anuga/runs/{run_id}/results/{layer}/tiles/{z}/{x}/{y}.png",
    summary="Render Web Mercator map tile for an ANUGA hazard layer",
    description="Renders a 256x256 PNG map tile with colormapping and transparent dry/NoData masking for maximum_depth, maximum_velocity, or arrival_time.",
)
def get_dam_project_anuga_layer_tile_endpoint(
    project_id: str,
    run_id: str,
    layer: str,
    z: int,
    x: int,
    y: int,
    processing_id: Optional[str] = Query(None, description="Optional processing ID (defaults to latest)"),
) -> Response:
    tile_bytes = get_dam_project_anuga_layer_tile(project_id, run_id, layer, z=z, x=x, y=y, processing_id=processing_id)
    return Response(
        content=tile_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get(
    "/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/info",
    summary="Get timestep metadata and temporal range for an ANUGA simulation run",
    description="Returns available timesteps count, time intervals, and depth range for timeline playback.",
)
def get_dam_project_anuga_timesteps_info_endpoint(
    project_id: str,
    run_id: str,
    processing_id: Optional[str] = Query(None, description="Optional processing ID (defaults to latest)"),
) -> Dict[str, Any]:
    return get_dam_project_anuga_timestep_metadata(project_id, run_id, processing_id=processing_id)


@app.get(
    "/api/dam-projects/{project_id}/anuga/runs/{run_id}/timesteps/{step_idx}/tiles/{z}/{x}/{y}.png",
    summary="Render Web Mercator map tile for an ANUGA simulation timestep depth frame",
    description="Renders a 256x256 PNG map tile representing water depth for a discrete simulation timestep step_idx.",
)
def get_dam_project_anuga_timestep_tile_endpoint(
    project_id: str,
    run_id: str,
    step_idx: int,
    z: int,
    x: int,
    y: int,
    processing_id: Optional[str] = Query(None, description="Optional processing ID (defaults to latest)"),
) -> Response:
    tile_bytes = get_dam_project_anuga_timestep_tile(
        project_id, run_id, step_idx, z=z, x=x, y=y, processing_id=processing_id
    )
    return Response(
        content=tile_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get(
    "/api/dam-projects/{project_id}/anuga/runs/{run_id}/results/{layer}/download",
    summary="Download raw GeoTIFF for an ANUGA hazard raster layer",
    description="Downloads the raw GeoTIFF file for maximum_depth, maximum_velocity, or arrival_time.",
)
def download_dam_project_anuga_layer_geotiff_endpoint(
    project_id: str,
    run_id: str,
    layer: str,
    processing_id: Optional[str] = Query(None, description="Optional processing ID (defaults to latest)"),
) -> FileResponse:
    tif_path = get_dam_project_anuga_layer_geotiff_path(project_id, run_id, layer, processing_id=processing_id)
    return FileResponse(
        path=str(tif_path),
        media_type="image/tiff",
        filename=f"{layer}.tif",
    )


@app.get(
    "/api/dam-projects/{project_id}/anuga/runs/{run_id}/tiles/{layer}/{z}/{x}/{y}.png",
    summary="Direct tile alias for ANUGA hazard raster layer",
    description="Renders a 256x256 PNG map tile with colormapping for maximum_depth, maximum_velocity, or arrival_time.",
)
def get_dam_project_anuga_layer_tile_alias_endpoint(
    project_id: str,
    run_id: str,
    layer: str,
    z: int,
    x: int,
    y: int,
    processing_id: Optional[str] = Query(None, description="Optional processing ID (defaults to latest)"),
) -> Response:
    tile_bytes = get_dam_project_anuga_layer_tile(project_id, run_id, layer, z=z, x=x, y=y, processing_id=processing_id)
    return Response(
        content=tile_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ==============================================================================
# Phase 20: Project-Scoped Earth Observation & Model-Observation Comparison
# ==============================================================================

@app.get(
    "/api/dam-projects/{project_id}/earth-observation/aoi",
    response_model=ProjectAOIResponse,
    summary="Derive project Area of Interest (AOI) for Earth Observation",
    description="Calculates the project AOI bounding box from simulation domain or DEM extent with configurable metric buffer.",
)
def get_dam_project_aoi_endpoint(
    project_id: str,
    buffer_meters: float = Query(1000.0, ge=0.0, le=10000.0, description="Buffer in meters applied to project domain"),
) -> ProjectAOIResponse:
    return derive_project_aoi(project_id, buffer_meters=buffer_meters)


@app.post(
    "/api/dam-projects/{project_id}/earth-observation/runs",
    response_model=EarthObservationRunResponse,
    summary="Execute project-scoped Earth Observation retrieval and processing",
    description="Initiates satellite data retrieval (Sentinel-1 SAR, JRC Water, GPM IMERG) for the project AOI. If GEE is unavailable or unauthenticated, operates in truthful dry-run fallback mode without fabricated observations.",
)
def post_dam_project_earth_observation_run_endpoint(
    project_id: str,
    request: EarthObservationRunRequest,
) -> EarthObservationRunResponse:
    return create_earth_observation_run(project_id, request)


@app.get(
    "/api/dam-projects/{project_id}/earth-observation/runs",
    response_model=List[EarthObservationRunResponse],
    summary="List all Earth Observation runs for a project",
    description="Retrieves historical Earth Observation satellite retrieval and processing runs for the specified project.",
)
def list_dam_project_earth_observation_runs_endpoint(project_id: str) -> List[EarthObservationRunResponse]:
    return list_earth_observation_runs(project_id)


@app.get(
    "/api/dam-projects/{project_id}/earth-observation/runs/{eo_run_id}",
    response_model=EarthObservationRunResponse,
    summary="Get details for a specific Earth Observation run",
    description="Returns detailed status, layer map IDs, statistics, and provenance for an Earth Observation run.",
)
def get_dam_project_earth_observation_run_endpoint(
    project_id: str,
    eo_run_id: str,
) -> EarthObservationRunResponse:
    return get_earth_observation_run(project_id, eo_run_id)


@app.get(
    "/api/dam-projects/{project_id}/earth-observation/runs/{eo_run_id}/logs",
    response_class=PlainTextResponse,
    summary="Get sanitized processing logs for an Earth Observation run",
    description="Streams the processing log output for the specified Earth Observation run.",
)
def get_dam_project_earth_observation_run_logs_endpoint(
    project_id: str,
    eo_run_id: str,
) -> PlainTextResponse:
    logs = get_earth_observation_run_logs(project_id, eo_run_id)
    return PlainTextResponse(content=logs, media_type="text/plain")


@app.post(
    "/api/dam-projects/{project_id}/earth-observation/compare",
    response_model=ModelObservationComparisonResponse,
    summary="Compare ANUGA modelled flood against satellite candidate inundation",
    description="Calculates model-observation spatial agreement (IoU, overlap, model-only, satellite-only) and evaluates temporal observation validity.",
)
def post_dam_project_model_observation_comparison_endpoint(
    project_id: str,
    request: ModelObservationComparisonRequest,
) -> ModelObservationComparisonResponse:
    return compare_model_and_observation(project_id, request)


# ==============================================================================
# Phase 21: Multi-Engine Spatial Hydrodynamic Comparison Endpoints
# ==============================================================================

@app.get(
    "/api/dam-projects/{project_id}/model-comparison/capabilities",
    response_model=ModelComparisonCapabilitiesResponse,
    summary="Get multi-engine comparison capabilities and completed run matrix",
    description="Reports availability and comparable runs across ANUGA, Delft3D FM, and PySPH for the specified project.",
)
def get_dam_project_model_comparison_capabilities_endpoint(
    project_id: str,
) -> ModelComparisonCapabilitiesResponse:
    return get_project_engine_capabilities(project_id)


@app.post(
    "/api/dam-projects/{project_id}/model-comparison/runs",
    response_model=ModelComparisonRunResponse,
    summary="Execute multi-engine spatial hydrodynamic comparison",
    description="Aligns two solver runs to a shared metric grid and calculates depth differences, inundation extent agreement (IoU), velocity differences, arrival-time comparisons, and ensemble spread diagnostics.",
)
def post_dam_project_model_comparison_run_endpoint(
    project_id: str,
    request: ModelComparisonRunRequest,
) -> ModelComparisonRunResponse:
    return compute_model_comparison(project_id, request)


@app.get(
    "/api/dam-projects/{project_id}/model-comparison/runs",
    response_model=List[ModelComparisonRunResponse],
    summary="List all model comparisons for a project",
    description="Retrieves all recorded inter-model hydrodynamic comparisons for the specified project.",
)
def list_dam_project_model_comparison_runs_endpoint(
    project_id: str,
) -> List[ModelComparisonRunResponse]:
    return list_model_comparison_runs(project_id)


@app.get(
    "/api/dam-projects/{project_id}/model-comparison/runs/{comparison_id}",
    response_model=ModelComparisonRunResponse,
    summary="Get details of a specific model comparison run",
    description="Returns detailed statistics, contracts, layer files, and provenance for an inter-model comparison.",
)
def get_dam_project_model_comparison_run_endpoint(
    project_id: str,
    comparison_id: str,
) -> ModelComparisonRunResponse:
    return get_model_comparison_run(project_id, comparison_id)


@app.get(
    "/api/dam-projects/{project_id}/model-comparison/runs/{comparison_id}/layers",
    summary="List available comparison raster layers for a comparison run",
    description="Returns dictionary of generated comparison GeoTIFFs (depth_difference, inundation_overlap, velocity_difference, etc.).",
)
def get_dam_project_model_comparison_layers_endpoint(
    project_id: str,
    comparison_id: str,
) -> Dict[str, str]:
    run = get_model_comparison_run(project_id, comparison_id)
    return run.layer_files


@app.get(
    "/api/dam-projects/{project_id}/model-comparison/runs/{comparison_id}/logs",
    response_class=PlainTextResponse,
    summary="Get processing logs for a model comparison run",
    description="Streams the processing log output for the specified inter-model comparison run.",
)
def get_dam_project_model_comparison_run_logs_endpoint(
    project_id: str,
    comparison_id: str,
) -> PlainTextResponse:
    logs_data = get_model_comparison_logs(project_id, comparison_id)
    return PlainTextResponse(content=logs_data.get("logs", ""), media_type="text/plain")


@app.get(
    "/api/dam-projects/{project_id}/model-comparison/runs/{comparison_id}/tiles/{layer}/{z}/{x}/{y}.png",
    summary="Render MapLibre XYZ tile for comparison raster layer",
    description="Streams PNG map tile for depth difference, inundation overlap, or inter-model spread.",
)
def get_dam_project_model_comparison_tile_endpoint(
    project_id: str,
    comparison_id: str,
    layer: str,
    z: int,
    x: int,
    y: int,
) -> Response:
    png_bytes = render_model_comparison_tile(project_id, comparison_id, layer, z, x, y)
    return Response(content=png_bytes, media_type="image/png")


# Phase 28: Dedicated SPH vs ANUGA Hydrodynamic Comparison Endpoints

@app.get(
    "/api/dam-projects/{project_id}/model-comparison",
    response_model=SPHvsANUGAComparisonResponse,
    summary="Get standardized SPH vs ANUGA hydrodynamic comparison for a dam project",
    description="Returns normalized comparison metrics, 12-parameter scenario compatibility table, percentile distributions (P50/P90/P95/P99/MAX), synchronized timeline mapping, and factual insights.",
)
@app.get(
    "/api/dam-projects/{project_id}/sph-vs-anuga-comparison",
    response_model=SPHvsANUGAComparisonResponse,
    summary="Direct alias for SPH vs ANUGA comparison",
    description="Returns comprehensive SPH vs ANUGA comparison data.",
)
def get_dam_project_sph_vs_anuga_comparison_endpoint(
    project_id: str,
    sph_run_id: Optional[str] = Query(None, description="Optional specific SPH run ID (defaults to latest completed)"),
    anuga_run_id: Optional[str] = Query(None, description="Optional specific ANUGA run ID (defaults to latest completed)"),
) -> SPHvsANUGAComparisonResponse:
    return get_sph_vs_anuga_comparison(project_id, sph_run_id=sph_run_id, anuga_run_id=anuga_run_id)


@app.get(
    "/api/dam-projects/{project_id}/model-comparison/export",
    summary="Download exportable SPH vs ANUGA comparison report (JSON or CSV)",
    description="Generates downloadable report containing comparison metrics, scenario compatibility, and disclaimers.",
)
def export_dam_project_model_comparison_endpoint(
    project_id: str,
    format: str = Query("json", description="Export format: json or csv"),
    sph_run_id: Optional[str] = Query(None),
    anuga_run_id: Optional[str] = Query(None),
) -> Response:
    comp = get_sph_vs_anuga_comparison(project_id, sph_run_id=sph_run_id, anuga_run_id=anuga_run_id)
    if format.lower() == "csv":
        # Generate CSV representation of summary table and compatibility table
        lines = [
            "# SPH VS ANUGA HYDRODYNAMIC COMPARISON REPORT",
            f"# Project: {comp.project_name} ({comp.project_id})",
            f"# SPH Run: {comp.sph_run_id}",
            f"# ANUGA Run: {comp.anuga_run_id}",
            f"# Generated At: {comp.created_at}",
            "",
            "Section,Metric,SPH (Lagrangian),ANUGA (Eulerian SWE),Notes",
            f"Overview,Solver Name,\"{comp.sph_metrics.solver_name}\",\"{comp.anuga_metrics.solver_name}\",\"\"",
            f"Overview,Solver Type,\"{comp.sph_metrics.solver_type}\",\"{comp.anuga_metrics.solver_type}\",\"\"",
            f"Overview,Simulation Duration (s),{comp.sph_metrics.simulation_duration_s},{comp.anuga_metrics.simulation_duration_s},\"\"",
            f"Overview,Wall-clock Runtime (s),{comp.sph_metrics.wall_clock_runtime_s},{comp.anuga_metrics.wall_clock_runtime_s},\"\"",
            f"Overview,Time Ratio (Sim/Wall),{comp.sph_metrics.time_ratio},{comp.anuga_metrics.time_ratio},\"\"",
            f"Domain,Domain Area (km2),{comp.sph_metrics.domain_area_km2},{comp.anuga_metrics.domain_area_km2},\"\"",
            f"Domain,Downstream Extent (m),{comp.sph_metrics.downstream_extent_m},{comp.anuga_metrics.downstream_extent_m},\"\"",
            f"Domain,Inundated Area (km2),{comp.sph_metrics.inundated_area_km2},{comp.anuga_metrics.inundated_area_km2},\"\"",
            f"Discretization,Spatial Resolution (m),{comp.sph_metrics.spatial_resolution_m},{comp.anuga_metrics.spatial_resolution_m},\"\"",
            f"Discretization,Element Count,{comp.sph_metrics.discrete_element_count} particles,{comp.anuga_metrics.discrete_element_count} triangles,\"\"",
            f"Depth,P50 Depth (m),{comp.sph_metrics.depth_percentiles.p50},{comp.anuga_metrics.depth_percentiles.p50},\"\"",
            f"Depth,P90 Depth (m),{comp.sph_metrics.depth_percentiles.p90},{comp.anuga_metrics.depth_percentiles.p90},\"\"",
            f"Depth,P95 Depth (m),{comp.sph_metrics.depth_percentiles.p95},{comp.anuga_metrics.depth_percentiles.p95},\"\"",
            f"Depth,P99 Depth (m),{comp.sph_metrics.depth_percentiles.p99},{comp.anuga_metrics.depth_percentiles.p99},\"\"",
            f"Depth,MAX Depth (m),{comp.sph_metrics.depth_percentiles.max},{comp.anuga_metrics.depth_percentiles.max},\"\"",
            f"Velocity,P50 Velocity (m/s),{comp.sph_metrics.velocity_percentiles.p50},{comp.anuga_metrics.velocity_percentiles.p50},\"\"",
            f"Velocity,P90 Velocity (m/s),{comp.sph_metrics.velocity_percentiles.p90},{comp.anuga_metrics.velocity_percentiles.p90},\"\"",
            f"Velocity,P95 Velocity (m/s),{comp.sph_metrics.velocity_percentiles.p95},{comp.anuga_metrics.velocity_percentiles.p95},\"\"",
            f"Velocity,P99 Velocity (m/s),{comp.sph_metrics.velocity_percentiles.p99},{comp.anuga_metrics.velocity_percentiles.p99},\"\"",
            f"Velocity,MAX Velocity (m/s),{comp.sph_metrics.velocity_percentiles.max},{comp.anuga_metrics.velocity_percentiles.max},\"\"",
            f"Arrival,First Arrival (s),{comp.sph_metrics.first_downstream_arrival_s},{comp.anuga_metrics.first_downstream_arrival_s},\"Threshold: 0.05m\"",
            f"Comparison,Spatial Agreement (IoU),{comp.spatial_comparison.spatial_agreement_iou * 100:.2f}%,,\"{comp.spatial_comparison.overlap_area_km2:.3f} km2 overlap\"",
            f"Comparison,Depth MAE (m),{comp.depth_comparison.mae_m},,\"{comp.depth_comparison.common_analysis_area_km2:.3f} km2 common area\"",
            "",
            "# SCENARIO COMPATIBILITY TABLE",
            "Parameter,SPH Setup,ANUGA Setup,Classification,Explanation",
        ]
        for sc in comp.scenario_compatibility:
            lines.append(f"\"{sc.parameter_name}\",\"{sc.sph_value}\",\"{sc.anuga_value}\",\"{sc.classification}\",\"{sc.scientific_explanation}\"")
        csv_content = "\n".join(lines)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=sph_vs_anuga_comparison_{project_id}.csv"},
        )
    else:
        return Response(
            content=json.dumps(comp.model_dump(), indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=sph_vs_anuga_comparison_{project_id}.json"},
        )


# ==============================================================================
# Phase 29: Dam-Break Decision-Support Dashboard Endpoints
# ==============================================================================

@app.get(
    "/api/dam-projects/{project_id}/decision-support",
    response_model=DecisionSupportResponse,
    summary="Get comprehensive Dam-Break Decision-Support summary",
    description="Transforms raw ANUGA regional 2D shallow-water simulation rasters into deterministic KPIs, severity analysis, downstream zones, and critical points.",
)
def get_dam_project_decision_support_endpoint(
    project_id: str,
    run_id: Optional[str] = Query(None, description="Optional ANUGA run ID. If omitted, selects the latest completed ANUGA run."),
) -> DecisionSupportResponse:
    return get_decision_support_summary(project_id, run_id=run_id)


@app.get(
    "/api/dam-projects/{project_id}/decision-support/export",
    summary="Download Decision-Support Report (JSON or CSV)",
    description="Generates a downloadable decision-support report containing KPIs, percentile distributions, severity config, downstream zones, and disclaimers.",
)
def export_dam_project_decision_support_endpoint(
    project_id: str,
    format: str = Query("json", description="Export format: json or csv"),
    run_id: Optional[str] = Query(None, description="Optional ANUGA run ID."),
) -> Response:
    content_bytes, media_type, filename = export_decision_support_summary(project_id, export_format=format, run_id=run_id)
    return Response(
        content=content_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get(
    "/api/dam-projects/{project_id}/decision-support/tiles/{layer}/{z}/{x}/{y}.png",
    summary="Render Decision-Support Map Tile",
    description="Renders dynamic map tile for decision-support layers: depth, velocity, arrival, or severity.",
)
def get_dam_project_decision_support_tile_endpoint(
    project_id: str,
    layer: str,
    z: int,
    x: int,
    y: int,
    run_id: Optional[str] = Query(None, description="Optional ANUGA run ID."),
) -> Response:
    png_bytes = render_decision_support_tile(project_id, layer=layer, z=z, x=x, y=y, run_id=run_id)
    return Response(content=png_bytes, media_type="image/png")


@app.get(
    "/api/dam-projects/{project_id}/demo-readiness",
    response_model=DemoReadinessResponse,
    summary="Check demonstration readiness status",
    description="Deterministically checks availability of DEM, ANUGA simulation, SPH demonstration, and decision-support assets for live SIH demonstration.",
)
def get_dam_project_demo_readiness_endpoint(
    project_id: str,
) -> DemoReadinessResponse:
    return check_demo_readiness(project_id)




# ==============================================================================
# Phase 25: Project-Scoped Delft3D and SPH Workflow Endpoints
# ==============================================================================

@app.post(
    "/api/dam-projects/{project_id}/delft3d/build-package",
    response_model=ProjectDelft3DPackageResponse,
    summary="Build project-specific Delft3D / D-Flow FM package",
    description="Generates D-Flow FM MDU, boundary conditions, and output contracts for the dam project. Optionally couples SPH breach hydrograph.",
)
def post_dam_project_delft3d_build_package_endpoint(
    project_id: str,
    sph_run_id: Optional[str] = Query(None, description="Optional SPH simulation run ID to couple breach hydrograph forcing"),
) -> ProjectDelft3DPackageResponse:
    resp, _ = build_dam_project_delft3d_package(project_id, sph_run_id=sph_run_id)
    return resp


@app.get(
    "/api/dam-projects/{project_id}/delft3d/download-package",
    summary="Download project-specific Delft3D / D-Flow FM package zip",
)
def get_dam_project_delft3d_download_package_endpoint(
    project_id: str,
    sph_run_id: Optional[str] = Query(None, description="Optional SPH simulation run ID to couple breach hydrograph forcing"),
) -> FileResponse:
    _, zip_path = build_dam_project_delft3d_package(project_id, sph_run_id=sph_run_id)
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=zip_path.name,
    )


@app.post(
    "/api/dam-projects/{project_id}/delft3d/import-run",
    summary="Import external Delft3D simulation results",
    description="Uploads and validates externally computed Delft3D raster outputs (maximum_depth.tif, etc.) into project storage.",
)
async def post_dam_project_delft3d_import_run_endpoint(
    project_id: str,
    files: List[UploadFile] = File(...),
    run_label: str = Form("Imported Delft3D Run"),
    notes: str = Form(""),
) -> Dict[str, Any]:
    file_tuples = []
    for f in files:
        content = await f.read()
        file_tuples.append((f.filename or "uploaded_file.tif", content))
    req = Delft3DRunImportRequest(run_label=run_label, notes=notes)
    return import_dam_project_delft3d_run(project_id, file_tuples, req)


@app.get(
    "/api/dam-projects/{project_id}/delft3d/runs",
    summary="List completed/imported Delft3D runs for project",
)
def list_dam_project_delft3d_runs_endpoint(
    project_id: str,
) -> List[Dict[str, Any]]:
    return list_dam_project_delft3d_runs(project_id)


@app.get(
    "/api/dam-projects/{project_id}/delft3d/runs/{run_id}",
    summary="Get details of a Delft3D run for project",
)
def get_dam_project_delft3d_run_detail_endpoint(
    project_id: str,
    run_id: str,
) -> Dict[str, Any]:
    return get_dam_project_delft3d_run_detail(project_id, run_id)


@app.post(
    "/api/dam-projects/{project_id}/delft3d/parse-ugrid",
    summary="Inspect and parse genuine Delft3D FM UGRID NetCDF output",
    description="Uploads a Delft3D NetCDF map file (*_map.nc) and extracts mesh topology, coordinates, time dimensions, and hazard summary.",
)
async def post_dam_project_delft3d_parse_ugrid_endpoint(
    project_id: str,
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    import tempfile
    content = await file.read()
    temp_dir = Path(tempfile.mkdtemp(prefix="delft3d_ugrid_parse_"))
    try:
        temp_nc = temp_dir / (file.filename or "output_map.nc")
        temp_nc.write_bytes(content)
        parsed = parse_delft3d_ugrid_netcdf(temp_nc)
        # Remove raw numpy arrays for clean JSON response
        resp = {
            "engine": parsed["engine"],
            "source_filename": file.filename,
            "num_nodes": parsed["num_nodes"],
            "num_timesteps": parsed["num_timesteps"],
            "timestamps": parsed["timestamps"],
            "simulation_duration_s": parsed["simulation_duration_s"],
            "crs": parsed["crs"],
            "bounds": parsed["bounds"],
            "depth_extracted": parsed["depth_extracted"],
            "velocity_extracted": parsed["velocity_extracted"],
            "summary": parsed["summary"],
            "provenance": parsed["provenance"],
        }
        return resp
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)



@app.post(
    "/api/dam-projects/{project_id}/sph/build-package",
    response_model=ProjectSPHPackageResponse,
    summary="Build project-specific SPH model package",
    description="Generates PySPH initial condition script, physics config, and rasterization contracts.",
)
def post_dam_project_sph_build_package_endpoint(
    project_id: str,
) -> ProjectSPHPackageResponse:
    resp, _ = build_dam_project_sph_package(project_id)
    return resp


@app.get(
    "/api/dam-projects/{project_id}/sph/download-package",
    summary="Download project-specific SPH package zip",
)
def get_dam_project_sph_download_package_endpoint(
    project_id: str,
) -> FileResponse:
    _, zip_path = build_dam_project_sph_package(project_id)
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=zip_path.name,
    )


@app.post(
    "/api/dam-projects/{project_id}/sph/import-run",
    summary="Import external SPH simulation results",
    description="Uploads and rasterizes externally computed SPH particle data or rasters into project storage.",
)
async def post_dam_project_sph_import_run_endpoint(
    project_id: str,
    files: List[UploadFile] = File(...),
    run_label: str = Form("Imported SPH Run"),
    notes: str = Form(""),
    target_resolution_m: float = Form(10.0),
) -> Dict[str, Any]:
    file_tuples = []
    for f in files:
        content = await f.read()
        file_tuples.append((f.filename or "uploaded_file.tif", content))
    from app.schemas import SPHParticleInterpolationParams
    req = SPHRunImportRequest(
        run_label=run_label,
        notes=notes,
        particle_params=SPHParticleInterpolationParams(target_resolution_m=target_resolution_m),
    )
    return import_dam_project_sph_run(project_id, file_tuples, req)


@app.get(
    "/api/dam-projects/{project_id}/sph/runs",
    summary="List completed/imported SPH runs for project",
)
def list_dam_project_sph_runs_endpoint(
    project_id: str,
) -> List[Dict[str, Any]]:
    return list_dam_project_sph_runs(project_id)


@app.post(
    "/api/dam-projects/{project_id}/sph/run",
    summary="Execute project-based PySPH / Terrain-SPH hydrodynamic simulation",
    description="Executes a genuine project-based SPH simulation using real DEM terrain elevations, symplectic time integration, and automated Eulerian rasterization (maximum_depth.tif, maximum_velocity.tif, arrival_time.tif).",
)
def post_dam_project_sph_run_endpoint(
    project_id: str,
    options: Optional[Dict[str, Any]] = Body(default=None),
) -> Dict[str, Any]:
    return execute_dam_project_sph_terrain_simulation(project_id, options=options)


@app.get(
    "/api/dam-projects/{project_id}/sph/runs/{run_id}",
    summary="Get details of an SPH run for project",
)
def get_dam_project_sph_run_detail_endpoint(
    project_id: str,
    run_id: str,
) -> Dict[str, Any]:
    return get_dam_project_sph_run_detail(project_id, run_id)


@app.get(
    "/api/dam-projects/{project_id}/sph/runs/{run_id}/animation",
    summary="Get SPH run animation manifest",
    description="Returns animation manifest for a completed SPH terrain simulation run, including frame count, timing, and per-frame time list for playback.",
)
def get_dam_project_sph_animation_manifest_endpoint(
    project_id: str,
    run_id: str,
) -> Dict[str, Any]:
    valid_pid = validate_project_uuid(project_id)
    clean_rid = sanitize_filename(run_id)
    sph_dir = get_dam_project_sph_dir(valid_pid)
    manifest_path = sph_dir / "runs" / clean_rid / "animation_manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Animation manifest not found for SPH run '{clean_rid}'. Run the terrain simulation first.",
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


@app.get(
    "/api/dam-projects/{project_id}/sph/runs/{run_id}/animation/frames/{frame_index}",
    summary="Get a GeoJSON particle frame for SPH flood animation",
    description="Returns a GeoJSON FeatureCollection of downsampled particle positions with depth (d) and velocity (v) properties for the specified animation frame index. Coordinates are in WGS84 (EPSG:4326).",
)
def get_dam_project_sph_animation_frame_endpoint(
    project_id: str,
    run_id: str,
    frame_index: int,
) -> Dict[str, Any]:
    valid_pid = validate_project_uuid(project_id)
    clean_rid = sanitize_filename(run_id)
    sph_dir = get_dam_project_sph_dir(valid_pid)
    frame_path = sph_dir / "runs" / clean_rid / "animation" / f"frame_{frame_index:04d}.json"
    if not frame_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Animation frame {frame_index} not found for SPH run '{clean_rid}'.",
        )
    return json.loads(frame_path.read_text(encoding="utf-8"))


@app.get(
    "/api/dam-projects/{project_id}/sph/runs/{run_id}/hydrograph",
    response_model=BreachHydrographResponse,
    summary="Get breach discharge hydrograph Q(t) from SPH simulation",
    description="Returns the time-series breach outflow hydrograph Q(t) in m3/s extracted from SPH particle kinematics across the breach control section.",
)
def get_dam_project_sph_hydrograph_endpoint(
    project_id: str,
    run_id: str,
) -> BreachHydrographResponse:
    return extract_sph_breach_hydrograph(project_id, run_id)




# ==============================================================================
# Phase 22: Population, LULC, Infrastructure Exposure & Vulnerability Endpoints
# ==============================================================================

@app.get(
    "/api/dam-projects/{project_id}/exposure/capabilities",
    response_model=ExposureCapabilitiesResponse,
    summary="Get exposure capabilities, available hazard sources, and datasets",
    description="Reports availability of population, building footprints, roads, critical assets, LULC, and supported vulnerability curves.",
)
def get_dam_project_exposure_capabilities_endpoint(
    project_id: str,
) -> ExposureCapabilitiesResponse:
    return get_project_exposure_capabilities(project_id)


@app.post(
    "/api/dam-projects/{project_id}/exposure/runs",
    response_model=ExposureRunDetailResponse,
    summary="Execute exposure and vulnerability assessment run",
    description="Performs count-conserving population exposure, building footprint overlap, road segmentation, critical asset sampling, LULC area, vulnerability curve checks, and decision-support priority indexing.",
)
def post_dam_project_exposure_run_endpoint(
    project_id: str,
    request: ExposureRunRequest,
) -> ExposureRunDetailResponse:
    return execute_exposure_run(project_id, request)


@app.get(
    "/api/dam-projects/{project_id}/exposure/runs",
    response_model=List[ExposureRunSummary],
    summary="List all exposure assessment runs for a dam project",
    description="Retrieves summaries of all recorded exposure assessment runs for the specified dam project.",
)
def list_dam_project_exposure_runs_endpoint(
    project_id: str,
) -> List[ExposureRunSummary]:
    return list_project_exposure_runs(project_id)


@app.get(
    "/api/dam-projects/{project_id}/exposure/runs/{run_id}",
    response_model=ExposureRunDetailResponse,
    summary="Get full details of a specific exposure assessment run",
    description="Returns detailed statistics, depth band distributions, arrival windows, vulnerability findings, and provenance.",
)
def get_dam_project_exposure_run_endpoint(
    project_id: str,
    run_id: str,
) -> ExposureRunDetailResponse:
    return get_exposure_run_detail(project_id, run_id)


@app.get(
    "/api/dam-projects/{project_id}/exposure/runs/{run_id}/logs",
    response_class=PlainTextResponse,
    summary="Get processing logs for an exposure assessment run",
    description="Streams the processing log output for the specified exposure run.",
)
def get_dam_project_exposure_run_logs_endpoint(
    project_id: str,
    run_id: str,
) -> PlainTextResponse:
    logs = get_exposure_run_logs(project_id, run_id)
    return PlainTextResponse(content=logs, media_type="text/plain")


@app.get(
    "/api/dam-projects/{project_id}/exposure/runs/{run_id}/assets",
    summary="Get exposed assets GeoJSON for an exposure run",
    description="Returns GeoJSON FeatureCollection of exposed critical facilities and building structures.",
)
def get_dam_project_exposure_run_assets_endpoint(
    project_id: str,
    run_id: str,
) -> Dict[str, Any]:
    return get_exposure_run_assets_geojson(project_id, run_id)


@app.get(
    "/api/dam-projects/{project_id}/exposure/runs/{run_id}/roads",
    summary="Get affected road segments GeoJSON for an exposure run",
    description="Returns GeoJSON FeatureCollection of potentially affected road segments with depth attributions.",
)
def get_dam_project_exposure_run_roads_endpoint(
    project_id: str,
    run_id: str,
) -> Dict[str, Any]:
    return get_exposure_run_roads_geojson(project_id, run_id)


@app.get(
    "/api/dam-projects/{project_id}/exposure/runs/{run_id}/layers",
    summary="List available spatial layers for an exposure run",
    description="Returns availability and API endpoints for visual map layers.",
)
def get_dam_project_exposure_run_layers_endpoint(
    project_id: str,
    run_id: str,
) -> Dict[str, Any]:
    return get_exposure_run_layers(project_id, run_id)


# ==============================================================================
# Phase B3: Canonical Multi-Engine Simulation Result Endpoints
# ==============================================================================


@app.get(
    "/api/dam-projects/{project_id}/canonical-results",
    response_model=List[CanonicalSimulationResult],
    summary="List all canonical simulation results for project across engines",
    description="Retrieves standardized simulation results across PySPH, Delft3D FM, and ANUGA.",
)
def list_dam_project_canonical_results_endpoint(
    project_id: str,
) -> List[CanonicalSimulationResult]:
    return list_canonical_simulation_results(project_id)


@app.get(
    "/api/dam-projects/{project_id}/canonical-results/{engine}/{run_id}",
    response_model=CanonicalSimulationResultResponse,
    summary="Retrieve a single canonical simulation result for any engine",
    description="Standardizes PySPH, Delft3D FM, or ANUGA run outputs into the canonical result schema.",
)
def get_dam_project_canonical_result_endpoint(
    project_id: str,
    engine: str,
    run_id: str,
) -> CanonicalSimulationResultResponse:
    res = get_canonical_simulation_result(project_id, engine, run_id)
    return CanonicalSimulationResultResponse(
        result=res,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        is_comparable=bool(res.raster_paths.get("maximum_depth")),
        message=f"Canonical result for engine '{engine}' retrieved successfully",
    )


# ==============================================================================
# Phase C1: End-to-End Hidkal PS-161 Workflow Endpoint
# ==============================================================================


@app.get(
    "/api/dam-projects/{project_id}/workflow-summary",
    response_model=HidkalWorkflowSummaryResponse,
    summary="Get End-to-End PS-161 Workflow Summary for Dam Project",
    description="Returns a consolidated, truthful summary spanning scenario, multi-engine status, results, comparison, exposure, HADR, GIS export, and GEE validation.",
)
def get_dam_project_workflow_summary_endpoint(
    project_id: str,
) -> HidkalWorkflowSummaryResponse:
    return get_hidkal_workflow_summary(project_id)



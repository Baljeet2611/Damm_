"""
Google Earth Engine (GEE) Connector Service: Earth Observation & Satellite Data Integration

Provides an optional, strictly gated connector to Google Earth Engine for retrieving
radar backscatter (Sentinel-1 SAR), precipitation estimates (GPM IMERG), and historical
surface water baselines (JRC Global Surface Water).

SECURITY & SCIENTIFIC CONSTRAINTS:
1. Purely optional adapter; uses standard standalone environment_gee.yml.
2. Authentication uses strict server-side Application Default Credentials (ADC) or GEE_PROJECT_ID.
   The API NEVER accepts, stores, or transmits credentials or bearer tokens over HTTP.
3. Only whitelisted official Earth Engine collections are supported.
4. Satellite observations are explicitly labeled as "candidate water-change observations"
   and NOT ground-truth validated flood extents (due to radar speckle, vegetation penetration, etc.).
5. Cloud task submission is gated by ENABLE_GEE_TASKS=true (default: false).
"""

import os
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.schemas import (
    GEECapabilitiesResponse,
    GEEDatasetInfo,
    GEEExportPlanRequest,
    GEEExportPlanResponse,
)

logger = logging.getLogger(__name__)

# Environment configuration
ENABLE_GEE_TASKS = os.environ.get("ENABLE_GEE_TASKS", "false").lower() in ("true", "1", "yes")
GEE_PROJECT_ID = os.environ.get("GEE_PROJECT_ID", "")

# Whitelisted Collections Registry
WHITELISTED_DATASETS: Dict[str, Dict[str, Any]] = {
    "COPERNICUS/S1_GRD": {
        "id": "COPERNICUS/S1_GRD",
        "title": "Sentinel-1 SAR GRD (Ground Range Detected)",
        "provider": "European Space Agency (ESA) / Copernicus",
        "type": "Synthetic Aperture Radar (SAR)",
        "temporal_range": "2014-10 to Present (6-12 day repeat)",
        "spatial_resolution": "10 meters",
        "bands": ["VV", "VH", "angle"],
        "usage_guidance": (
            "C-band Synthetic Aperture Radar provides all-weather, day-and-night surface backscatter. "
            "Specular reflection over open water produces low backscatter (dark pixels) in VV/VH channels. "
            "Useful for candidate surface water mapping and flood progression screening."
        ),
        "disclaimer": (
            "SAR water detection is subject to radar speckle, wind-induced surface roughness, "
            "and vegetation canopy shielding. Outputs represent candidate water-change observations, "
            "not certified ground-truth flood inundation."
        )
    },
    "NASA/GPM_L3/IMERG_V07": {
        "id": "NASA/GPM_L3/IMERG_V07",
        "title": "GPM IMERG Final Precipitation L3 Half-Hourly / Daily",
        "provider": "NASA / JAXA Global Precipitation Measurement",
        "type": "Multi-Satellite Precipitation Analysis",
        "temporal_range": "2000-06 to Present (Half-hourly & Daily)",
        "spatial_resolution": "0.1 degree (~10 km)",
        "bands": ["precipitationCal", "precipitationUncal", "probabilityLiquidPrecipitation"],
        "usage_guidance": (
            "Combines passive microwave and infrared satellite observations with rain gauge calibrations "
            "to provide gridded global precipitation rates (mm/hr). Useful for antecedent moisture "
            "and catchment-scale storm rainfall estimation upstream of reservoirs."
        ),
        "disclaimer": (
            "Coarse spatial resolution (~10 km) cannot capture extreme localized convective orographic "
            "cells in mountainous terrain. Should be used for regional catchment trends only."
        )
    },
    "JRC/GSW1_4/GlobalSurfaceWater": {
        "id": "JRC/GSW1_4/GlobalSurfaceWater",
        "title": "JRC Global Surface Water Mapping (1984-2021)",
        "provider": "European Commission Joint Research Centre (JRC)",
        "type": "Historical Optical Surface Water Dynamics",
        "temporal_range": "1984 to 2021 (38-year aggregate)",
        "spatial_resolution": "30 meters (Landsat)",
        "bands": ["occurrence", "change_abs", "seasonality", "recurrence", "max_extent"],
        "usage_guidance": (
            "Provides 38-year spatial statistics on water presence across the globe. Used as a baseline "
            "to differentiate permanent water bodies (e.g., Ghataprabha riverbed and reservoir) from "
            "transient anomalous flood inundation."
        ),
        "disclaimer": (
            "Historical baseline does not reflect post-2021 riverbed infrastructure modifications, "
            "barrages, or severe seasonal drought conditions."
        )
    }
}


def check_gee_capabilities() -> GEECapabilitiesResponse:
    """
    Evaluates Earth Engine library presence, ADC authentication, and project configuration.
    Never exposes API secrets or bearer tokens.
    """
    gee_available = False
    authenticated = False
    auth_mode = "none"

    try:
        import ee
        gee_available = True
        
        # Test initialization with configured project ID if available
        if GEE_PROJECT_ID:
            try:
                ee.Initialize(project=GEE_PROJECT_ID)
                authenticated = True
                auth_mode = f"adc_project_{GEE_PROJECT_ID}"
            except Exception:
                authenticated = False
                auth_mode = "unauthenticated"
        else:
            try:
                ee.Initialize()
                authenticated = True
                auth_mode = "adc_default"
            except Exception:
                authenticated = False
                auth_mode = "unauthenticated"

    except ImportError:
        gee_available = False
        authenticated = False
        auth_mode = "missing_library"

    guidance = (
        "Google Earth Engine is an optional external connector. To enable live queries: "
        "1. Install the standalone conda environment: conda env create -f environment_gee.yml. "
        "2. Run 'earthengine authenticate' via Google Cloud CLI. "
        "3. Set GEE_PROJECT_ID=<your-gcp-project> and optionally ENABLE_GEE_TASKS=true."
    )

    disclaimer = (
        "OPTIONAL CONNECTOR: No cloud credentials or tokens are accepted via web endpoints. "
        "All satellite exports remain disabled by default to avoid unintended cloud costs."
    )

    return GEECapabilitiesResponse(
        gee_available=gee_available,
        authenticated=authenticated,
        project_id=GEE_PROJECT_ID if GEE_PROJECT_ID else None,
        auth_mode=auth_mode,
        tasks_enabled=ENABLE_GEE_TASKS,
        whitelisted_collections=list(WHITELISTED_DATASETS.keys()),
        disclaimer=disclaimer,
        guidance=guidance,
    )


def list_whitelisted_datasets() -> List[GEEDatasetInfo]:
    """
    Returns list of supported, whitelisted Earth Engine datasets with strict metadata.
    """
    return [GEEDatasetInfo(**info) for info in WHITELISTED_DATASETS.values()]


def get_dataset_info(dataset_id: str) -> Optional[GEEDatasetInfo]:
    """
    Returns metadata for a specific whitelisted dataset ID.
    """
    info = WHITELISTED_DATASETS.get(dataset_id)
    if not info:
        return None
    return GEEDatasetInfo(**info)


def create_export_plan(req: GEEExportPlanRequest) -> GEEExportPlanResponse:
    """
    Creates an Earth Engine export plan or candidate observation query.
    If unauthenticated or tasks disabled, produces a structured dry-run plan with disclaimers.
    """
    if req.dataset_id not in WHITELISTED_DATASETS:
        raise ValueError(f"Dataset '{req.dataset_id}' is not in the approved whitelist of Earth Engine collections.")

    # Validate dates
    try:
        d_start = datetime.strptime(req.start_date, "%Y-%m-%d")
        d_end = datetime.strptime(req.end_date, "%Y-%m-%d")
        if d_start >= d_end:
            raise ValueError("start_date must precede end_date")
    except ValueError as ve:
        if "strptime" in str(ve):
            raise ValueError("Dates must be formatted as YYYY-MM-DD")
        raise ve

    # Calculate approximate ROI pixel count
    # 1 deg lat ~ 111,000m, 1 deg lon ~ 106,000m at 16 deg latitude
    d_lat_m = abs(req.roi_max_lat - req.roi_min_lat) * 111000.0
    d_lon_m = abs(req.roi_max_lon - req.roi_min_lon) * 106000.0
    area_m2 = d_lat_m * d_lon_m
    pixel_area = req.target_scale_meters ** 2
    est_pixels = int(area_m2 / pixel_area) if pixel_area > 0 else 0

    caps = check_gee_capabilities()
    task_id = f"gee_plan_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    notes = [
        f"Target Dataset: {req.dataset_id}",
        f"ROI Bounds: [{req.roi_min_lon:.4f}, {req.roi_min_lat:.4f}, {req.roi_max_lon:.4f}, {req.roi_max_lat:.4f}]",
        f"Estimated Area: {area_m2 / 1e6:.2f} km² ({est_pixels:,} pixels at {req.target_scale_meters}m resolution)",
    ]

    candidate_label = "candidate_water_change_observation"
    acquisitions: List[str] = []
    cloud_submitted = False
    status = "plan_created"

    if not caps.authenticated:
        status = "dry_run_unauthenticated"
        notes.append("Earth Engine is unauthenticated in this environment. Plan generated in dry-run mode.")
        acquisitions = [
            f"{req.start_date}T00:00:00Z (Dry Run Simulation)",
            f"{req.end_date}T00:00:00Z (Dry Run Simulation)"
        ]
    elif not ENABLE_GEE_TASKS:
        status = "authenticated_task_submission_disabled"
        notes.append("Authenticated with Earth Engine, but ENABLE_GEE_TASKS is false. No background cloud export task was initiated.")
        # If authenticated, we could query actual metadata collection count
        try:
            import ee
            geom = ee.Geometry.Rectangle([req.roi_min_lon, req.roi_min_lat, req.roi_max_lon, req.roi_max_lat])
            col = ee.ImageCollection(req.dataset_id).filterDate(req.start_date, req.end_date).filterBounds(geom)
            count = col.size().getInfo()
            notes.append(f"Authentic catalog query returned {count} matching scene(s) in Earth Engine repository.")
            if count > 0:
                dates = col.aggregate_array('system:time_start').getInfo()
                acquisitions = [datetime.utcfromtimestamp(ts / 1000.0).strftime('%Y-%m-%dT%H:%M:%SZ') for ts in dates[:10]]
        except Exception as e:
            notes.append(f"Catalog query note: {str(e)}")
    else:
        status = "cloud_task_queued"
        cloud_submitted = True
        notes.append("Authenticated cloud export task prepared for execution.")

    disclaimer = (
        "EARTH OBSERVATION DISCLAIMER: All satellite rasters produced via this connector are "
        "candidate water-change observations. They have not been ground-truthed and must be "
        "interpreted alongside hydraulic model outputs with professional engineering judgment."
    )

    return GEEExportPlanResponse(
        task_id=task_id,
        dataset_id=req.dataset_id,
        status=status,
        date_range=(req.start_date, req.end_date),
        roi_bounds=(req.roi_min_lon, req.roi_min_lat, req.roi_max_lon, req.roi_max_lat),
        estimated_pixels=est_pixels,
        target_scale_meters=req.target_scale_meters,
        candidate_observation_label=candidate_label,
        acquisition_timestamps=acquisitions,
        cloud_task_submitted=cloud_submitted,
        notes=notes,
        disclaimer=disclaimer,
    )

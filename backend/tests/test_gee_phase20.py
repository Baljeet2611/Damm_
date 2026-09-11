"""
Automated unit and integration test suite for Phase 20:
Live Google Earth Engine / Remote-Sensing Integration & Model-Observation Comparison.

Covers:
1. GEE capability detection (unauthenticated fallback & mocked configuration).
2. Project-scoped AOI derivation from simulation domain vs DEM with metric buffering.
3. Strict zero-fabrication fallback when Earth Engine is unauthenticated/unavailable.
4. Sentinel-1 SAR heuristic thresholds persistence and candidate inundation labeling.
5. EO run lifecycle and persistent storage artifacts (request.json, provenance.json, etc.).
6. Model-observation spatial agreement calculation (IoU, overlap, model-only, satellite-only).
7. Configurable temporal validity checking and warnings.
8. Path traversal and UUID security on EO endpoints.
"""

import json
import uuid
import numpy as np
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi.testclient import TestClient
import rasterio
from rasterio.transform import from_origin

from app.main import app
from app.schemas import (
    EarthObservationRunRequest,
    ModelObservationComparisonRequest,
)
from app import onboarding_service
from app import earth_observation_service


client = TestClient(app)


def create_mock_dem_bytes(width: int = 40, height: int = 40, res: float = 0.001) -> bytes:
    """Creates an in-memory single-band Float32 GeoTIFF for testing."""
    import io
    transform = from_origin(74.60, 16.30, res, res)
    data = np.linspace(600.0, 650.0, width * height, dtype=np.float32).reshape((height, width))
    buf = io.BytesIO()
    with rasterio.open(
        buf,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)
    return buf.getvalue()


@pytest.fixture
def test_project(tmp_path, monkeypatch):
    """Creates an isolated dam project directory and registers it."""
    projects_dir = tmp_path / "dam_projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(onboarding_service, "get_dam_projects_dir", lambda: projects_dir)
    monkeypatch.setattr(earth_observation_service, "get_dam_projects_dir", lambda: projects_dir)

    p_id = str(uuid.uuid4())
    proj_dir = projects_dir / p_id
    proj_dir.mkdir(parents=True, exist_ok=True)

    # Write dem.tif
    dem_bytes = create_mock_dem_bytes()
    (proj_dir / "dem.tif").write_bytes(dem_bytes)

    # Write model_domain.geojson
    domain_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"layer_name": "model_domain"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [74.61, 16.25],
                        [74.63, 16.25],
                        [74.63, 16.28],
                        [74.61, 16.28],
                        [74.61, 16.25]
                    ]]
                }
            }
        ]
    }
    (proj_dir / "model_domain.geojson").write_text(json.dumps(domain_geojson), encoding="utf-8")

    # Write project.json
    now_iso = datetime.now(timezone.utc).isoformat()
    project_data = {
        "project_id": p_id,
        "project_name": "Test EO Project",
        "dam_name": "Test Dam",
        "created_at": now_iso,
        "dam_point": {
            "dam_name": "Test Dam",
            "latitude": 16.26,
            "longitude": 74.62,
            "elevation_sampled": 620.0,
            "elevation_source": "dem_point_interrogation",
        },
        "model_domain_file": "model_domain.geojson",
        "scientific_status": "hypothetical_unverified",
        "scientifically_verified": False,
        "onboarding_validation_passed": True,
    }
    (proj_dir / "project.json").write_text(json.dumps(project_data), encoding="utf-8")

    # Write manifest.json
    dem_h = onboarding_service.compute_file_sha256(proj_dir / "dem.tif")
    dom_h = onboarding_service.compute_file_sha256(proj_dir / "model_domain.geojson")
    manifest = {
        "manifest_version": "1.0.0",
        "project_id": p_id,
        "created_at": now_iso,
        "files": {
            "dem.tif": dem_h,
            "model_domain.geojson": dom_h,
        }
    }
    (proj_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    return p_id


class TestPhase20GEECapabilities:
    """Test GET /api/gee/capabilities detection and configuration reporting."""

    def test_capabilities_reports_unauthenticated_cleanly(self, monkeypatch):
        monkeypatch.delenv("GEE_PROJECT_ID", raising=False)
        monkeypatch.delenv("ENABLE_GEE_TASKS", raising=False)

        resp = client.get("/api/gee/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert "gee_available" in data
        assert "authenticated" in data
        assert "project_configured" in data
        assert "earthengine_import_success" in data
        assert "reason" in data
        assert "supported_datasets" in data
        assert len(data["supported_datasets"]) == 3
        assert data["project_configured"] is False

    def test_capabilities_configured_when_env_mocked(self, monkeypatch):
        monkeypatch.setenv("GEE_PROJECT_ID", "my-test-gee-project")
        monkeypatch.setenv("ENABLE_GEE_TASKS", "true")

        resp = client.get("/api/gee/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_configured"] is True
        assert data["gee_project_id"] == "my-test-gee-project"
        assert data["tasks_enabled"] is True


class TestPhase20AOIDerivation:
    """Test project-scoped AOI derivation."""

    def test_project_aoi_derivation_from_model_domain(self, test_project):
        resp = client.get(f"/api/dam-projects/{test_project}/earth-observation/aoi?buffer_meters=1000")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == test_project
        assert data["source"] == "simulation_domain"
        assert data["aoi_area_km2"] > 0
        min_lon, min_lat, max_lon, max_lat = data["aoi_bounds"]
        assert min_lon < max_lon
        assert min_lat < max_lat
        assert data["buffer_applied_meters"] == 1000.0

    def test_project_aoi_fallback_to_dem(self, test_project, monkeypatch):
        # Remove model_domain.geojson to trigger fallback
        p_dir = onboarding_service.get_dam_projects_dir() / test_project
        (p_dir / "model_domain.geojson").unlink(missing_ok=True)
        # Update manifest
        dem_h = onboarding_service.compute_file_sha256(p_dir / "dem.tif")
        (p_dir / "manifest.json").write_text(json.dumps({"files": {"dem.tif": dem_h}}), encoding="utf-8")

        resp = client.get(f"/api/dam-projects/{test_project}/earth-observation/aoi?buffer_meters=500")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "dem_extent"
        assert data["buffer_applied_meters"] == 500.0


class TestPhase20EORunLifecycleAndZeroFabrication:
    """Test EO run creation, zero-fabrication fallback, and persistence."""

    def test_eo_run_creation_zero_fabrication_when_unauthenticated(self, test_project, monkeypatch):
        monkeypatch.delenv("GEE_PROJECT_ID", raising=False)

        payload = {
            "datasets": ["sentinel1", "jrc_water", "gpm_imerg"],
            "event_date": "2024-07-15",
            "pre_event_window_days": 30,
            "post_event_window_days": 7,
            "aoi_buffer_meters": 1000.0,
            "s1_params": {
                "polarization": "VV",
                "change_threshold_db": -3.5,
                "post_event_water_threshold_db": -16.0,
            }
        }
        resp = client.post(f"/api/dam-projects/{test_project}/earth-observation/runs", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        # Zero-fabrication check: when unauthenticated, status MUST be truthful fallback
        assert data["status"] in ("gee_unavailable", "authentication_required", "project_not_configured")
        # No fabricated outputs
        assert data["candidate_inundation_area_km2"] is None
        assert data["rainfall_accumulation_mm"] is None
        assert "zero-fabrication" in data["message"].lower() or "not installed" in data["message"].lower() or "not configured" in data["message"].lower()

        # Check provenance has preserved configurable thresholds
        prov = data["provenance"]
        s1_p = prov["sentinel1_parameters"]
        assert s1_p["change_threshold_db"] == -3.5
        assert s1_p["post_event_water_threshold_db"] == -16.0
        assert s1_p["label"] == "candidate_inundation"
        assert s1_p["threshold_source"] == "configurable_heuristic"

    def test_eo_run_rejects_invalid_dates(self, test_project):
        # Invalid event date
        resp1 = client.post(
            f"/api/dam-projects/{test_project}/earth-observation/runs",
            json={"event_date": "not-a-date"}
        )
        assert resp1.status_code == 422

        # Invalid rainfall date range (start after end)
        resp2 = client.post(
            f"/api/dam-projects/{test_project}/earth-observation/runs",
            json={
                "event_date": "2024-07-15",
                "rainfall_start_date": "2024-07-20",
                "rainfall_end_date": "2024-07-10",
            }
        )
        assert resp2.status_code == 422
        assert "precede" in resp2.json()["detail"].lower()

    def test_synthetic_test_fixture_creates_completed_run_and_persists(self, test_project):
        """Verify that an explicit synthetic test fixture populates completed results for testing."""
        fixture = {
            "status": "completed",
            "candidate_inundation_area_km2": 8.45,
            "permanent_water_area_km2": 3.12,
            "rainfall_accumulation_mm": 62.4,
            "rainfall_time_series": [
                {"timestamp": "2024-07-14T00:00:00Z", "precipitation_mm_hr": 2.5, "accumulated_precipitation_mm": 2.5},
                {"timestamp": "2024-07-15T00:00:00Z", "precipitation_mm_hr": 5.0, "accumulated_precipitation_mm": 7.5},
            ]
        }
        req = EarthObservationRunRequest(event_date="2024-07-15")
        eo_resp = earth_observation_service.create_earth_observation_run(
            project_id=test_project,
            request=req,
            synthetic_test_fixture=fixture,
        )
        assert eo_resp.status_code if hasattr(eo_resp, "status_code") else True
        assert eo_resp.status == "completed"
        assert eo_resp.candidate_inundation_area_km2 == 8.45
        assert eo_resp.permanent_water_area_km2 == 3.12
        assert eo_resp.rainfall_accumulation_mm == 62.4
        assert len(eo_resp.rainfall_time_series) == 2

        # Verify persisted files
        eo_dir = onboarding_service.get_dam_projects_dir() / test_project / "earth_observation" / eo_resp.eo_run_id
        assert (eo_dir / "request.json").is_file()
        assert (eo_dir / "provenance.json").is_file()
        assert (eo_dir / "statistics.json").is_file()
        assert (eo_dir / "processing.log").is_file()

        # Test listing and getting via API
        list_resp = client.get(f"/api/dam-projects/{test_project}/earth-observation/runs")
        assert list_resp.status_code == 200
        runs = list_resp.json()
        assert len(runs) >= 1
        assert any(r["eo_run_id"] == eo_resp.eo_run_id for r in runs)

        get_resp = client.get(f"/api/dam-projects/{test_project}/earth-observation/runs/{eo_resp.eo_run_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["eo_run_id"] == eo_resp.eo_run_id

        log_resp = client.get(f"/api/dam-projects/{test_project}/earth-observation/runs/{eo_resp.eo_run_id}/logs")
        assert log_resp.status_code == 200
        assert "[TEST_FIXTURE]" in log_resp.text


class TestPhase20ModelObservationComparison:
    """Test ANUGA modelled vs satellite candidate inundation comparison."""

    @pytest.fixture
    def setup_comparison_data(self, test_project):
        """Sets up a mock ANUGA run and mock EO run in the project."""
        proj_dir = onboarding_service.get_dam_projects_dir() / test_project

        # 1. Setup mock ANUGA run
        anuga_id = str(uuid.uuid4())
        a_dir = proj_dir / "runs" / anuga_id
        a_dir.mkdir(parents=True, exist_ok=True)
        anuga_meta = {
            "run_id": anuga_id,
            "project_id": test_project,
            "status": "completed",
            "created_at": "2024-07-15T10:00:00Z",
            "completed_at": "2024-07-15T12:00:00Z",
            "simulation_executed": True,
        }
        (a_dir / "run.json").write_text(json.dumps(anuga_meta), encoding="utf-8")

        # 2. Setup mock completed EO run (aligned date: 2024-07-15)
        eo_id = str(uuid.uuid4())
        e_dir = proj_dir / "earth_observation" / eo_id
        e_dir.mkdir(parents=True, exist_ok=True)
        eo_meta = {
            "eo_run_id": eo_id,
            "project_id": test_project,
            "status": "completed",
            "created_at": "2024-07-15T14:00:00Z",
            "completed_at": "2024-07-15T14:05:00Z",
            "candidate_inundation_area_km2": 10.0,
            "provenance": {
                "event_date": "2024-07-15",
            },
        }
        (e_dir / "run.json").write_text(json.dumps(eo_meta), encoding="utf-8")

        # 3. Setup mock completed EO run with distant date (2024-08-01, ~17 days later)
        eo_distant_id = str(uuid.uuid4())
        ed_dir = proj_dir / "earth_observation" / eo_distant_id
        ed_dir.mkdir(parents=True, exist_ok=True)
        eo_dist_meta = {
            "eo_run_id": eo_distant_id,
            "project_id": test_project,
            "status": "completed",
            "created_at": "2024-08-01T14:00:00Z",
            "completed_at": "2024-08-01T14:05:00Z",
            "candidate_inundation_area_km2": 8.0,
            "provenance": {
                "event_date": "2024-08-01",
            },
        }
        (ed_dir / "run.json").write_text(json.dumps(eo_dist_meta), encoding="utf-8")

        return anuga_id, eo_id, eo_distant_id

    def test_model_observation_comparison_with_synthetic_masks(self, test_project, setup_comparison_data):
        anuga_id, eo_id, _ = setup_comparison_data

        # Create synthetic masks:
        # 100 pixels total, 60 model flooded, 40 satellite candidate, 30 overlap
        model_mask = np.zeros((10, 10), dtype=bool)
        model_mask[:6, :] = True  # 60 pixels

        sat_mask = np.zeros((10, 10), dtype=bool)
        sat_mask[3:7, :] = True  # 40 pixels (rows 3,4,5 overlap with model -> 30 overlap)

        pixel_area = 0.1  # 0.1 km² per pixel
        synthetic_masks = (model_mask, sat_mask, pixel_area)

        req = ModelObservationComparisonRequest(
            anuga_run_id=anuga_id,
            eo_run_id=eo_id,
            depth_threshold_m=0.10,
            max_observation_time_delta_hours=72.0,
        )

        comp_res = earth_observation_service.compare_model_and_observation(
            project_id=test_project,
            request=req,
            synthetic_masks_fixture=synthetic_masks,
        )

        assert comp_res.label == "model-observation spatial agreement"
        assert comp_res.overlap_area_km2 == round(30 * 0.1, 3)  # 3.0 km²
        assert comp_res.union_area_km2 == round(70 * 0.1, 3)    # 7.0 km²
        assert comp_res.model_only_area_km2 == round(30 * 0.1, 3)
        assert comp_res.satellite_only_area_km2 == round(10 * 0.1, 3)
        # IoU = 30 / 70 = 0.4286
        assert comp_res.spatial_agreement_iou == 0.4286
        # Temporal validity check (dates aligned on 2024-07-15)
        assert comp_res.temporal_validity.comparison_valid is True
        assert comp_res.temporal_validity.warning is None

    def test_temporal_validity_warns_when_distant(self, test_project, setup_comparison_data):
        anuga_id, _, eo_distant_id = setup_comparison_data

        payload = {
            "anuga_run_id": anuga_id,
            "eo_run_id": eo_distant_id,
            "depth_threshold_m": 0.10,
            "max_observation_time_delta_hours": 48.0,  # 48 hours tolerance
        }
        resp = client.post(f"/api/dam-projects/{test_project}/earth-observation/compare", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        temp_val = data["temporal_validity"]
        # Must be flagged invalid due to ~17 days gap exceeding 48 hours tolerance
        assert temp_val["comparison_valid"] is False
        assert temp_val["warning"] is not None
        assert "exceeding the configured tolerance" in temp_val["warning"]
        assert temp_val["absolute_delta_hours"] > 300.0

    def test_security_and_path_traversal_on_eo_endpoints(self, test_project):
        # Invalid UUIDs
        resp1 = client.get(f"/api/dam-projects/{test_project}/earth-observation/runs/not-a-uuid")
        assert resp1.status_code == 422

        resp2 = client.get(f"/api/dam-projects/{test_project}/earth-observation/runs/../../traversal")
        assert resp2.status_code in (404, 422)

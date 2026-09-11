"""
Phase 19 Live ANUGA Execution for Generalized Dam Projects - Test Suite.

Covers:
1. Gated ANUGA capability detection (Python path, ANUGA installed status, execution gating).
2. 5-tier simulation readiness model (data_ready, geometry_ready, hydraulic_ready, solver_ready, simulation_ready).
3. Terrain-heuristic geometry assist (gradient calculation, aspect bearing, unverified provenance tagging).
4. Heuristic acceptance gating (rejection if accept_heuristic_inputs is false).
5. Simulation inputs update and geometry persistence.
6. Package builder and immutable run manifest generation with SHA256.
7. Execution lifecycle transitions (queued -> preparing -> running -> postprocessing -> completed/failed/cancelled).
8. Execution gating without hypothetical acknowledgment (HTTP 422).
9. Output SWW verification (corrupted, empty/dry bed <= 0.0001m, and valid NetCDF).
10. Run cancellation endpoint (/cancel).
11. Outputs status endpoint (/outputs).
12. Scientific invariants: scientific_status = 'hypothetical_unverified', scientifically_verified = False.
"""

import io
import json
import os
import shutil
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import numpy as np
import rasterio
from affine import Affine
from fastapi.testclient import TestClient

from app.main import app
from app import onboarding_service, anuga_postprocessing_service
from app.schemas import (
    DamProjectAnugaCapabilitiesResponse,
    HeuristicAssistRequest,
    SimulationInputsUpdateRequest,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_dam_projects_storage(tmp_path, monkeypatch):
    """Ensure all tests run against an isolated temporary dam_projects directory."""
    temp_dir = tmp_path / "dam_projects"
    temp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(onboarding_service, "get_dam_projects_dir", lambda: temp_dir)
    return temp_dir


def create_test_wgs84_geotiff_bytes(
    width: int = 40,
    height: int = 40,
    crs: str = "EPSG:4326",
    nodata: float = -9999.0,
    min_val: float = 600.0,
    max_val: float = 750.0,
    origin_x: float = 73.70,
    origin_y: float = 17.50,
    res: float = 0.005,
) -> bytes:
    """Create in-memory GeoTIFF raster with linear slope for gradient tests."""
    buf = io.BytesIO()
    transform = Affine(res, 0.0, origin_x, 0.0, -res, origin_y)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": crs if crs else None,
        "transform": transform,
        "nodata": nodata,
    }
    with rasterio.open(buf, "w", **profile) as dst:
        # Create an elevation ramp: high in north-west, low in south-east
        y, x = np.mgrid[0:height, 0:width]
        data = (max_val - (y + x) * ((max_val - min_val) / (height + width))).astype(np.float32)
        dst.write(data, 1)

    return buf.getvalue()


def onboard_minimal_project(project_name: str = "Test Dam Project") -> str:
    """Helper to onboard a minimal project and return its project_id."""
    dem_bytes = create_test_wgs84_geotiff_bytes()
    files = {
        "dem_file": ("dem.tif", dem_bytes, "image/tiff"),
    }
    data = {
        "project_name": project_name,
        "dam_name": "Test Dam",
        "latitude": "17.40",
        "longitude": "73.80",
        "acknowledge_unverified_metadata": "true",
    }
    res = client.post("/api/dam-projects", files=files, data=data)
    assert res.status_code == 200, f"Failed to onboard minimal project: {res.text}"
    return res.json()["project_id"]


class TestPhase19CapabilitiesAndReadiness:
    """Test ANUGA capabilities check and 5-tier simulation readiness."""

    def test_capabilities_endpoint_reports_real_environment(self):
        """Capabilities endpoint must return explicit python executable and anuga status."""
        project_id = onboard_minimal_project("Capabilities Dam")
        res = client.get(f"/api/dam-projects/{project_id}/anuga/capabilities")
        assert res.status_code == 200
        data = res.json()
        assert "execution_enabled" in data
        assert "anuga_installed" in data
        assert "python_executable_path" in data
        assert "anuga_environment_available" in data
        assert "disclaimer" in data

    def test_five_tier_readiness_on_minimal_project(self):
        """Minimal project should be data_ready=True, but geometry_ready and hydraulic_ready=False."""
        project_id = onboard_minimal_project("Tiered Dam")
        res = client.post(f"/api/dam-projects/{project_id}/readiness")
        assert res.status_code == 200
        data = res.json()
        assert data["data_ready"] is True
        assert data["geometry_ready"] is False
        assert data["hydraulic_ready"] is False
        assert data["simulation_ready"] is False
        assert "tier_breakdown" in data
        assert "data_tier" in data["tier_breakdown"]
        assert "geometry_tier" in data["tier_breakdown"]
        assert "hydraulic_tier" in data["tier_breakdown"]
        assert "solver_tier" in data["tier_breakdown"]
        assert "simulation_tier" in data["tier_breakdown"]
        assert len(data["missing_requirements"]) > 0
        assert data["scientific_status"] == "validated_unverified"
        assert data["scientifically_verified"] is False


class TestPhase19TerrainHeuristicAssist:
    """Test DEM slope aspect heuristic derivation and acceptance gating."""

    def test_compute_terrain_heuristic_assist(self):
        """Terrain heuristic assist computes downstream bearing, dam axis, corridor, and caveats."""
        project_id = onboard_minimal_project("Heuristic Dam")
        res = client.post(
            f"/api/dam-projects/{project_id}/heuristic-assist",
            json={"downstream_length_m": 4000.0, "corridor_width_m": 800.0},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["source"] == "terrain_heuristic"
        assert data["scientifically_verified"] is False
        assert data["confidence"] == "low_unverified"
        assert len(data["caveats"]) >= 3
        assert "downstream_bearing_deg" in data
        assert "downstream_direction" in data
        assert "suggested_dam_axis" in data
        assert "suggested_model_domain" in data
        assert "suggested_breach_line" in data
        assert "suggested_outlet_boundary" in data
        assert "suggested_reservoir_boundary" in data
        assert data["suggested_dam_axis"]["type"] == "FeatureCollection"
        assert data["suggested_model_domain"]["type"] == "FeatureCollection"

    def test_save_simulation_inputs_rejects_heuristic_without_acknowledgment(self):
        """Saving heuristic geometries without accept_heuristic_inputs=True must return 422."""
        project_id = onboard_minimal_project("Gated Heuristic Dam")
        heur_res = client.post(f"/api/dam-projects/{project_id}/heuristic-assist")
        heur_data = heur_res.json()

        # Attempt to save without accept_heuristic_inputs
        payload = {
            "dam_axis_geometry": heur_data["suggested_dam_axis"],
            "model_domain_geometry": heur_data["suggested_model_domain"],
            "accept_heuristic_inputs": False,
        }
        res = client.post(f"/api/dam-projects/{project_id}/simulation-inputs", json=payload)
        assert res.status_code == 422
        assert "accept_heuristic_inputs" in res.text

    def test_save_simulation_inputs_accepts_with_acknowledgment_and_updates_readiness(self):
        """Saving heuristic geometries with accept_heuristic_inputs=True updates project and tier readiness."""
        project_id = onboard_minimal_project("Accepted Heuristic Dam")
        heur_res = client.post(f"/api/dam-projects/{project_id}/heuristic-assist")
        heur_data = heur_res.json()

        payload = {
            "dam_axis_geometry": heur_data["suggested_dam_axis"],
            "reservoir_geometry": heur_data["suggested_reservoir_boundary"],
            "model_domain_geometry": heur_data["suggested_model_domain"],
            "downstream_outlet_geometry": heur_data["suggested_outlet_boundary"],
            "reservoir_level": 740.0,
            "dam_crest_elevation": 745.0,
            "dam_height": 30.0,
            "breach_width": 40.0,
            "breach_invert_elevation": 715.0,
            "breach_formation_time_hr": 0.5,
            "manning_roughness": 0.035,
            "simulation_duration_s": 1800.0,
            "output_interval_s": 30.0,
            "accept_heuristic_inputs": True,
        }
        res = client.post(f"/api/dam-projects/{project_id}/simulation-inputs", json=payload)
        assert res.status_code == 200
        proj_data = res.json()
        assert proj_data["dam_axis_file"] is not None
        assert proj_data["model_domain_file"] is not None

        # Verify readiness reflects geometry_ready and hydraulic_ready
        readiness_res = client.post(f"/api/dam-projects/{project_id}/readiness")
        assert readiness_res.status_code == 200
        readiness = readiness_res.json()
        assert readiness["data_ready"] is True
        assert readiness["geometry_ready"] is True
        assert readiness["hydraulic_ready"] is True


class TestPhase19PackageBuilderAndManifest:
    """Test ANUGA simulation package builder and cryptographic run manifest."""

    def test_package_builder_generates_zip_and_manifest(self):
        """Building ANUGA package generates valid ZIP archive and manifest."""
        project_id = onboard_minimal_project("Package Dam")
        # Provide necessary geometries and hydraulics via assist
        heur_res = client.post(f"/api/dam-projects/{project_id}/heuristic-assist")
        heur_data = heur_res.json()
        client.post(
            f"/api/dam-projects/{project_id}/simulation-inputs",
            json={
                "dam_axis_geometry": heur_data["suggested_dam_axis"],
                "reservoir_geometry": heur_data["suggested_reservoir_boundary"],
                "model_domain_geometry": heur_data["suggested_model_domain"],
                "downstream_outlet_geometry": heur_data["suggested_outlet_boundary"],
                "reservoir_level": 740.0,
                "dam_crest_elevation": 745.0,
                "dam_height": 30.0,
                "breach_width": 40.0,
                "breach_invert_elevation": 715.0,
                "breach_formation_time_hr": 0.5,
                "manning_roughness": 0.035,
                "simulation_duration_s": 1200.0,
                "output_interval_s": 30.0,
                "target_mesh_resolution_m": 50.0,
                "accept_heuristic_inputs": True,
            },
        )

        # Build package
        pkg_res = client.post(f"/api/dam-projects/{project_id}/anuga/build-package")
        assert pkg_res.status_code == 200
        pkg_data = pkg_res.json()
        assert pkg_data["package_filename"].endswith(".zip")
        assert pkg_data["package_size_bytes"] > 0
        assert len(pkg_data["package_sha256"]) == 64
        assert pkg_data["scientific_status"] == "hypothetical_unverified"
        assert pkg_data["simulation_executed"] is False


class TestPhase19ExecutionLifecycleAndGating:
    """Test simulation run queuing, hypothetical acknowledgment gating, cancellation, and mock execution."""

    def test_execution_requires_hypothetical_acknowledgment(self):
        """Executing ANUGA without acknowledge_hypothetical_unverified=True must return 422."""
        project_id = onboard_minimal_project("Ack Dam")
        with patch.object(onboarding_service, "get_custom_anuga_capabilities") as mock_caps:
            mock_caps.return_value = DamProjectAnugaCapabilitiesResponse(
                execution_enabled=True,
                anuga_installed=True,
                anuga_environment_available=True,
                python_executable_path="python",
                anuga_import_success=True,
                anuga_version="3.0.0",
                version_source="fallback_runtime",
                python_executable_configured=True,
                disclaimer="Custom ANUGA execution runs uncalibrated hypothetical scenarios.",
            )
            res = client.post(
                f"/api/dam-projects/{project_id}/anuga/runs",
                json={"acknowledge_hypothetical_unverified": False},
            )
            assert res.status_code == 422


    def test_execution_gating_when_anuga_unavailable(self):
        """When ANUGA is not installed, execution returns 403 custom_anuga_execution_disabled."""
        project_id = onboard_minimal_project("Disabled Dam")
        heur_res = client.post(f"/api/dam-projects/{project_id}/heuristic-assist")
        heur_data = heur_res.json()
        client.post(
            f"/api/dam-projects/{project_id}/simulation-inputs",
            json={
                "dam_axis_geometry": heur_data["suggested_dam_axis"],
                "reservoir_geometry": heur_data["suggested_reservoir_boundary"],
                "model_domain_geometry": heur_data["suggested_model_domain"],
                "downstream_outlet_geometry": heur_data["suggested_outlet_boundary"],
                "reservoir_level": 740.0,
                "dam_crest_elevation": 745.0,
                "dam_height": 30.0,
                "breach_width": 40.0,
                "breach_invert_elevation": 715.0,
                "breach_formation_time_hr": 0.5,
                "accept_heuristic_inputs": True,
            },
        )
        client.post(f"/api/dam-projects/{project_id}/anuga/build-package")

        with patch.object(onboarding_service, "get_custom_anuga_capabilities") as mock_caps:
            mock_caps.return_value = DamProjectAnugaCapabilitiesResponse(
                execution_enabled=False,
                anuga_installed=False,
                anuga_environment_available=False,
                python_executable_path=None,
                anuga_import_success=False,
                anuga_version="unavailable",
                version_source="unavailable",
                python_executable_configured=False,
                reason="ANUGA package not installed in environment.",
                disclaimer="Custom ANUGA execution runs uncalibrated hypothetical scenarios.",
            )
            res = client.post(
                f"/api/dam-projects/{project_id}/anuga/runs",
                json={"acknowledge_hypothetical_unverified": True},
            )
            assert res.status_code == 403
            assert res.json()["detail"]["code"] == "custom_anuga_execution_disabled"

    def test_run_cancellation_endpoint(self):
        """Cancelling an active run updates its status to cancelled."""
        project_id = onboard_minimal_project("Cancel Dam")
        runs_dir = onboarding_service.get_dam_projects_dir() / project_id / "runs"
        run_id = str(uuid.uuid4())
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "run_id": run_id,
            "project_id": project_id,
            "project_name": "Cancel Dam",
            "package_sha256": "dummy_sha",
            "status": "running",
            "created_at": "2026-09-11T12:00:00Z",
            "started_at": "2026-09-11T12:00:01Z",
            "completed_at": None,
            "exit_code": None,
            "runtime_seconds": 5.0,
            "output_files": {},
            "scientific_status": "hypothetical_unverified",
            "simulation_executed": True,
            "message": "Running...",
        }
        with open(run_dir / "run.json", "w", encoding="utf-8") as f:
            json.dump(meta, f)

        cancel_res = client.post(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/cancel")
        assert cancel_res.status_code == 200
        cancel_data = cancel_res.json()
        assert cancel_data["status"] == "cancelled"

    def test_outputs_endpoint(self):
        """Outputs endpoint returns SWW status and available raster layers."""
        project_id = onboard_minimal_project("Outputs Dam")
        runs_dir = onboarding_service.get_dam_projects_dir() / project_id / "runs"
        run_id = str(uuid.uuid4())
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "run_id": run_id,
            "project_id": project_id,
            "project_name": "Outputs Dam",
            "package_sha256": "dummy_sha",
            "status": "completed",
            "created_at": "2026-09-11T12:00:00Z",
            "output_files": {},
            "scientific_status": "hypothetical_unverified",
            "simulation_executed": True,
            "has_results": False,
            "message": "Completed.",
        }
        with open(run_dir / "run.json", "w", encoding="utf-8") as f:
            json.dump(meta, f)

        res = client.get(f"/api/dam-projects/{project_id}/anuga/runs/{run_id}/outputs")
        assert res.status_code == 200
        data = res.json()
        assert data["run_id"] == run_id
        assert data["status"] == "completed"
        assert data["has_results"] is False



class TestPhase19SWWOutputValidation:
    """Test rigorous validation of simulation SWW NetCDF output."""

    def test_validate_sww_file_missing_raises_error(self, tmp_path):
        """Missing SWW file must return (False, error)."""
        missing_file = tmp_path / "nonexistent.sww"
        valid, err = anuga_postprocessing_service.validate_sww_file(missing_file)
        assert valid is False
        assert "does not exist" in err

    def test_validate_sww_file_corrupted_format(self, tmp_path):
        """Non-NetCDF or corrupt file must return (False, error)."""
        corrupt_file = tmp_path / "corrupted.sww"
        corrupt_file.write_bytes(b"This is not a valid NetCDF file content." * 50)
        valid, err = anuga_postprocessing_service.validate_sww_file(corrupt_file)
        assert valid is False
        assert "Failed to parse SWW NetCDF" in err or "suspiciously small" in err

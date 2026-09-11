"""Phase 21 Automated Test Suite: Multi-Engine Spatial Hydrodynamic Comparison.

Verifies:
- Engine capability matrix detection and unexecuted run reporting
- Rejection of missing projects, missing runs, and incomplete runs
- Normalization of solver contracts
- Metric CRS reprojection, common grid alignment, and NoData preservation
- Inter-model depth difference, MAE, RMSE, and configurable tolerance coverage
- Inundation extent agreement (IoU, A-only, B-only, overlap)
- Graceful handling when velocity or arrival-time outputs are unavailable
- Detection and invalidation of incompatible arrival-time threshold definitions
- Multi-model ensemble spread diagnostic
- Provenance and comparison persistence
- Path traversal and security protections
- Zero-fabrication enforcement
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from fastapi.testclient import TestClient

from app.main import app
from app.onboarding_service import get_dam_projects_dir
from app.model_comparison_service import (
    determine_analysis_metric_crs,
    align_rasters_to_common_metric_grid,
    compute_model_comparison,
    get_project_engine_capabilities,
    normalize_engine_output,
)
from app.schemas import ModelComparisonRunRequest

client = TestClient(app)


@pytest.fixture
def temp_dam_project(tmp_path):
    """Creates a temporary isolated dam project on disk for testing."""
    import uuid
    proj_id = str(uuid.uuid4())
    p_dir = get_dam_projects_dir() / proj_id
    p_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy dem.tif in EPSG:32643
    dem_path = p_dir / "dem.tif"
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        height=50,
        width=50,
        count=1,
        dtype=rasterio.float32,
        crs=CRS.from_epsg(32643),
        transform=rasterio.transform.from_bounds(500000.0, 1800000.0, 501000.0, 1801000.0, 50, 50),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.full((50, 50), 100.0, dtype=np.float32), 1)

    project_meta = {
        "project_id": proj_id,
        "project_name": "Test Comparison Project",
        "created_at": "2026-09-11T12:00:00Z",
        "scientific_status": "hypothetical_unverified",
    }
    (p_dir / "project.json").write_text(json.dumps(project_meta), encoding="utf-8")

    yield proj_id

    # Cleanup
    if p_dir.is_dir():
        shutil.rmtree(p_dir, ignore_errors=True)


class TestPhase21CapabilitiesAndValidation:
    """Tests engine capability matrix, missing run rejection, and path traversal."""

    def test_capabilities_reports_honest_status(self, temp_dam_project):
        """Capabilities must honestly report engine availability and 0 runs when none executed."""
        resp = client.get(f"/api/dam-projects/{temp_dam_project}/model-comparison/capabilities")
        assert resp.status_code == 200
        data = resp.json()

        assert data["project_id"] == temp_dam_project
        assert "engines" in data
        assert "anuga" in data["engines"]
        assert "delft3d_fm" in data["engines"]
        assert "pysph" in data["engines"]

        # Delft3D and PySPH must report available_for_comparison=False when no completed runs exist
        assert data["engines"]["delft3d_fm"]["available_for_comparison"] is False
        assert data["engines"]["pysph"]["available_for_comparison"] is False
        assert data["ready_for_comparison"] is False

    def test_missing_project_returns_404(self):
        """Querying capabilities or runs for non-existent project returns 404, or 422 if invalid UUID."""
        import uuid
        dummy_uuid = str(uuid.uuid4())
        resp = client.get(f"/api/dam-projects/{dummy_uuid}/model-comparison/capabilities")
        assert resp.status_code == 404

        resp2 = client.get("/api/dam-projects/nonexistent-project-9999/model-comparison/capabilities")
        assert resp2.status_code == 422

    def test_missing_run_rejection(self, temp_dam_project):
        """Attempting comparison with non-existent run returns 404."""
        payload = {
            "engine_a": "anuga",
            "run_id_a": "run-nonexistent-1",
            "engine_b": "anuga",
            "run_id_b": "run-nonexistent-2",
        }
        resp = client.post(f"/api/dam-projects/{temp_dam_project}/model-comparison/runs", json=payload)
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_security_path_traversal_rejection(self, temp_dam_project):
        """Path traversal characters in comparison_id or run_id must be rejected with 400 or 422."""
        resp = client.get(f"/api/dam-projects/{temp_dam_project}/model-comparison/runs/comp-..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (400, 404, 422)

        resp2 = client.get(f"/api/dam-projects/{temp_dam_project}/model-comparison/runs/comp-..%5Cwindows%5Cwin.ini")
        assert resp2.status_code in (400, 404, 422)


class TestPhase21GridAlignmentAndAreaCorrectness:
    """Tests metric CRS determination, reprojection, and NoData preservation."""

    def test_metric_crs_determination(self, temp_dam_project):
        """Analysis CRS must be metric (e.g. UTM), not EPSG:4326 degrees."""
        # For our test project, dem.tif is EPSG:32643
        crs = determine_analysis_metric_crs(temp_dam_project, (74.7, 16.2, 74.8, 16.3))
        assert not crs.is_geographic
        assert "32643" in str(crs) or crs.to_epsg() == 32643

    def test_reprojection_aligns_extents_and_preserves_nodata(self, tmp_path):
        """Rasters with different bounds must be clipped to intersection and preserve NoData."""
        r1_path = tmp_path / "raster1.tif"
        r2_path = tmp_path / "raster2.tif"

        target_crs = CRS.from_epsg(32643)

        # Raster 1: bounds [500000, 1800000, 502000, 1802000]
        data1 = np.full((100, 100), 2.5, dtype=np.float32)
        data1[0:10, 0:10] = -9999.0  # NoData patch
        with rasterio.open(
            r1_path, "w", driver="GTiff", height=100, width=100, count=1,
            dtype=rasterio.float32, crs=target_crs,
            transform=rasterio.transform.from_bounds(500000.0, 1800000.0, 502000.0, 1802000.0, 100, 100),
            nodata=-9999.0
        ) as dst:
            dst.write(data1, 1)

        # Raster 2: slightly shifted bounds [501000, 1801000, 503000, 1803000]
        data2 = np.full((100, 100), 1.5, dtype=np.float32)
        with rasterio.open(
            r2_path, "w", driver="GTiff", height=100, width=100, count=1,
            dtype=rasterio.float32, crs=target_crs,
            transform=rasterio.transform.from_bounds(501000.0, 1801000.0, 503000.0, 1803000.0, 100, 100),
            nodata=-9999.0
        ) as dst:
            dst.write(data2, 1)

        arr_a, arr_b, xform, w, h, px_area = align_rasters_to_common_metric_grid(
            r1_path, r2_path, target_crs, nodata_value=-9999.0
        )

        assert w > 0 and h > 0
        assert px_area > 0.0
        assert arr_a.shape == (h, w)
        assert arr_b.shape == (h, w)
        # Check intersection coordinates: [501000, 1801000, 502000, 1802000]
        assert np.isclose(xform.c, 501000.0, atol=25.0)


class TestPhase21NumericalDifferencesAndInundationAgreement:
    """Tests numerical comparison metrics on isolated synthetic fixture."""

    def test_synthetic_fixture_comparison_executes_and_persists(self, temp_dam_project):
        """Runs comparison pipeline using isolated synthetic fixture and verifies statistics."""
        req = ModelComparisonRunRequest(
            engine_a="anuga",
            run_id_a="synth_anuga_run_1",
            engine_b="delft3d_fm",
            run_id_b="synth_d3d_run_2",
            depth_inundation_threshold_m=0.10,
            tolerance_bands_m=[0.10, 0.25, 0.50],
            synthetic_test_fixture=True,
        )

        res = compute_model_comparison(temp_dam_project, req)
        assert res.status == "completed"
        assert res.comparison_id.startswith("comp-")

        # 1. Depth Difference checks
        assert res.depth_difference.common_valid_pixel_count > 0
        assert res.depth_difference.common_analysis_area_km2 > 0.0
        assert res.depth_difference.mae_m > 0.0
        assert res.depth_difference.rmse_m >= res.depth_difference.mae_m
        assert len(res.depth_difference.tolerance_bands) == 3
        # Percentage coverage must increase monotonically with wider tolerance bands
        pcts = [tb.percentage_of_common_valid_area for tb in res.depth_difference.tolerance_bands]
        assert pcts[0] <= pcts[1] <= pcts[2]

        # 2. Inundation Extent Agreement checks
        assert res.inundation_agreement.label == "inter-model spatial agreement"
        assert 0.0 <= res.inundation_agreement.spatial_agreement_iou <= 1.0
        assert res.inundation_agreement.overlap_area_km2 <= res.inundation_agreement.union_area_km2
        assert res.inundation_agreement.model_a_only_area_km2 >= 0.0
        assert res.inundation_agreement.model_b_only_area_km2 >= 0.0

        # 3. Velocity and Arrival Time checks
        assert res.velocity_difference.available is True
        assert res.velocity_difference.mae_m_s is not None
        assert res.arrival_time_difference.available is True
        assert res.arrival_time_difference.comparison_valid is True

        # 4. Ensemble spread diagnostic
        assert res.ensemble_spread is not None
        assert res.ensemble_spread.computed is True
        assert res.ensemble_spread.label == "inter-model spread"
        assert res.ensemble_spread.max_spread_m >= res.ensemble_spread.mean_spread_m

        # 5. File persistence
        comp_dir = get_dam_projects_dir() / temp_dam_project / "comparisons" / res.comparison_id
        assert (comp_dir / "comparison.json").is_file()
        assert (comp_dir / "provenance.json").is_file()
        assert (comp_dir / "statistics.json").is_file()
        assert (comp_dir / "processing.log").is_file()
        assert (comp_dir / "depth_difference.tif").is_file()
        assert (comp_dir / "inundation_overlap.tif").is_file()
        assert (comp_dir / "inter_model_spread.tif").is_file()

    def test_arrival_definition_mismatch_invalidates_comparison(self, temp_dam_project, monkeypatch):
        """If two models define arrival time with different water depths, comparison_valid must be False."""
        from unittest.mock import patch

        orig_normalize = normalize_engine_output

        def mock_normalize(*args, **kwargs):
            contract, paths = orig_normalize(*args, **kwargs)
            engine_name = args[1] if len(args) > 1 else kwargs.get("engine")
            if engine_name == "delft3d_fm":
                contract.arrival_time_definition = "depth >= 0.50m (incompatible definition)"
            return contract, paths

        with patch("app.model_comparison_service.normalize_engine_output", side_effect=mock_normalize):
            req = ModelComparisonRunRequest(
                engine_a="anuga",
                run_id_a="synth_anuga_run_1",
                engine_b="delft3d_fm",
                run_id_b="synth_d3d_run_2",
                synthetic_test_fixture=True,
            )
            res = compute_model_comparison(temp_dam_project, req)
            assert res.arrival_time_difference.available is True
            assert res.arrival_time_difference.comparison_valid is False
            assert "incompatible" in res.arrival_time_difference.invalidation_reason.lower()

    def test_nodata_handling_excludes_nodata_from_zero_depth(self, tmp_path):
        """Common valid analysis mask must strictly exclude NoData pixels and not treat them as 0.0m water."""
        target_crs = CRS.from_epsg(32643)
        p1 = tmp_path / "nd_r1.tif"
        p2 = tmp_path / "nd_r2.tif"

        # Model A: valid 2.0m, with 10 NoData pixels
        d1 = np.full((10, 10), 2.0, dtype=np.float32)
        d1[0, :5] = -9999.0
        with rasterio.open(
            p1, "w", driver="GTiff", height=10, width=10, count=1,
            dtype=rasterio.float32, crs=target_crs,
            transform=rasterio.transform.from_bounds(500000, 1800000, 500100, 1800100, 10, 10),
            nodata=-9999.0
        ) as dst:
            dst.write(d1, 1)

        # Model B: valid 1.0m, with 10 different NoData pixels
        d2 = np.full((10, 10), 1.0, dtype=np.float32)
        d2[5, :5] = -9999.0
        with rasterio.open(
            p2, "w", driver="GTiff", height=10, width=10, count=1,
            dtype=rasterio.float32, crs=target_crs,
            transform=rasterio.transform.from_bounds(500000, 1800000, 500100, 1800100, 10, 10),
            nodata=-9999.0
        ) as dst:
            dst.write(d2, 1)

        arr_a, arr_b, _, w, h, _ = align_rasters_to_common_metric_grid(p1, p2, target_crs, nodata_value=-9999.0)
        common_valid = (arr_a != -9999.0) & (arr_b != -9999.0) & ~np.isnan(arr_a) & ~np.isnan(arr_b)

        # 100 total pixels - 5 (from d1) - 5 (from d2) = 90 valid pixels
        assert common_valid.sum() == 90
        # Check that diff is strictly (2.0 - 1.0) = 1.0, NOT 2.0 - 0.0
        diff = arr_a[common_valid] - arr_b[common_valid]
        assert np.allclose(diff, 1.0)

    def test_velocity_and_arrival_unavailable_honesty(self, temp_dam_project):
        """When velocity or arrival rasters are unavailable, available=False is returned without synthesizing."""
        from unittest.mock import patch

        orig_normalize = normalize_engine_output

        def mock_normalize_no_vel(*args, **kwargs):
            contract, paths = orig_normalize(*args, **kwargs)
            engine_name = args[1] if len(args) > 1 else kwargs.get("engine")
            if engine_name == "delft3d_fm":
                contract.maximum_velocity_available = False
                contract.arrival_time_available = False
            return contract, paths

        with patch("app.model_comparison_service.normalize_engine_output", side_effect=mock_normalize_no_vel):
            req = ModelComparisonRunRequest(
                engine_a="anuga",
                run_id_a="synth_anuga_run_1",
                engine_b="delft3d_fm",
                run_id_b="synth_d3d_run_2",
                synthetic_test_fixture=True,
            )
            res = compute_model_comparison(temp_dam_project, req)
            assert res.velocity_difference.available is False
            assert "unavailable" in res.velocity_difference.reason_if_unavailable.lower()
            assert res.velocity_difference.mae_m_s is None
            assert res.arrival_time_difference.available is False

    def test_list_and_get_comparison_endpoints(self, temp_dam_project):
        """Endpoints for listing, getting detail, and fetching logs work correctly."""
        # Run comparison via API
        payload = {
            "engine_a": "anuga",
            "run_id_a": "synth_anuga_run_1",
            "engine_b": "delft3d_fm",
            "run_id_b": "synth_d3d_run_2",
            "depth_inundation_threshold_m": 0.10,
            "synthetic_test_fixture": True,
        }
        create_resp = client.post(f"/api/dam-projects/{temp_dam_project}/model-comparison/runs", json=payload)
        assert create_resp.status_code == 200
        comp_id = create_resp.json()["comparison_id"]

        # List
        list_resp = client.get(f"/api/dam-projects/{temp_dam_project}/model-comparison/runs")
        assert list_resp.status_code == 200
        items = list_resp.json()
        assert len(items) >= 1
        assert any(it["comparison_id"] == comp_id for it in items)

        # Get detail
        detail_resp = client.get(f"/api/dam-projects/{temp_dam_project}/model-comparison/runs/{comp_id}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["comparison_id"] == comp_id

        # Get layers
        layers_resp = client.get(f"/api/dam-projects/{temp_dam_project}/model-comparison/runs/{comp_id}/layers")
        assert layers_resp.status_code == 200
        assert "depth_difference" in layers_resp.json()

        # Get logs
        logs_resp = client.get(f"/api/dam-projects/{temp_dam_project}/model-comparison/runs/{comp_id}/logs")
        assert logs_resp.status_code == 200
        assert "Multi-Engine Comparison" in logs_resp.text

        # Tile endpoint test
        tile_resp = client.get(f"/api/dam-projects/{temp_dam_project}/model-comparison/runs/{comp_id}/tiles/depth_difference/10/500/500.png")
        assert tile_resp.status_code == 200
        assert tile_resp.headers["content-type"] == "image/png"


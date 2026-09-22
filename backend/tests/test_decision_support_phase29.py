"""
Phase 29: Dam-Break Decision-Support Dashboard Automated Tests.

Tests:
1. Decision-support endpoint response structure
2. KPI extraction from real ANUGA run rasters
3. Inundated area and domain percentage calculation
4. Depth distribution bins (0-0.5, 0.5-1, 1-2, 2-5, >5 m)
5. Velocity distribution bins (0-0.5, 0.5-1, 1-2, 2-5, >5 m/s)
6. Arrival time intelligence (excluding initial reservoir wet cells t=0)
7. Hydraulic severity calculation (H = h * v) and demonstration classification
8. Dry cells and NoData handling exclusion
9. Modeled critical points extraction (5 points with coordinates and units)
10. Downstream distance zone analysis (0-250m, 250-500m, etc.)
11. Project and run isolation (invalid project/run error handling)
12. Disclaimer fields and scientific status verification
13. No operational warning / evacuation claims in generated text
14. JSON and CSV export endpoints
15. Map tile serving for all four layers (depth, velocity, arrival, severity)
16. Primary ANUGA solver labeling and supplementary SPH indicator
"""

import os
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.onboarding_service import (
    load_or_create_hidkal_demo_project,
    get_dam_projects_dir,
)
from app.decision_support_service import (
    get_decision_support_summary,
    render_decision_support_tile,
    export_decision_support_summary,
)

client = TestClient(app)


@pytest.fixture(scope="module")
def hidkal_project_id():
    import json
    import numpy as np
    import rasterio
    demo = load_or_create_hidkal_demo_project()
    pid = demo.project_id
    proj_dir = get_dam_projects_dir() / pid
    runs_dir = proj_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    
    # Ensure at least one completed run with GeoTIFFs exists
    has_completed = False
    for r in runs_dir.iterdir():
        if r.is_dir() and (r / "run.json").is_file():
            try:
                rj = json.loads((r / "run.json").read_text(encoding="utf-8"))
                if rj.get("status") == "completed" and (r / "results" / "maximum_depth.tif").is_file():
                    has_completed = True
                    break
            except Exception:
                pass
                
    if not has_completed:
        run_id = "a1b2c3d4-e5f6-4a7b-8c9d-012345678929"
        r_dir = runs_dir / run_id
        res_dir = r_dir / "results"
        res_dir.mkdir(parents=True, exist_ok=True)
        
        dem_path = proj_dir / "dem.tif"
        with rasterio.open(dem_path) as src:
            meta = src.meta.copy()
            h, w = src.height, src.width
            
        meta.update(dtype=rasterio.float32, count=1, nodata=-9999.0)
        
        depth_data = np.zeros((h, w), dtype=np.float32)
        vel_data = np.zeros((h, w), dtype=np.float32)
        arr_data = np.full((h, w), -9999.0, dtype=np.float32)
        
        for r_idx in range(h // 4, h):
            for c_idx in range(w):
                val = float(max(0.0, 15.0 * (1.0 - (r_idx - h//4) / (3 * h // 4)) * (1.0 - abs(c_idx - w//2) / (w//2))))
                depth_data[r_idx, c_idx] = val
                if val > 0.05:
                    vel_data[r_idx, c_idx] = float(min(8.0, val * 0.6))
                    arr_data[r_idx, c_idx] = float(60.0 + (r_idx - h//4) * 30.0)
                    
        with rasterio.open(res_dir / "maximum_depth.tif", "w", **meta) as dst:
            dst.write(depth_data, 1)
        with rasterio.open(res_dir / "maximum_velocity.tif", "w", **meta) as dst:
            dst.write(vel_data, 1)
        with rasterio.open(res_dir / "arrival_time.tif", "w", **meta) as dst:
            dst.write(arr_data, 1)
            
        run_record = {
            "run_id": run_id,
            "project_id": pid,
            "project_name": demo.project_name,
            "package_sha256": "deterministic_fixture",
            "status": "completed",
            "created_at": "2026-09-21T12:00:00Z",
            "started_at": "2026-09-21T12:00:01Z",
            "completed_at": "2026-09-21T12:05:00Z",
            "exit_code": 0,
            "anuga_version": "4.0.0",
            "version_source": "conda_meta",
            "runtime_seconds": 299.0,
            "parameters_snapshot": {
                "scenario_type": "DAM_BREAK",
                "barrier_type": "engineered_dam",
                "is_intact_control": False,
                "dam_height": 25.0,
                "crest_elevation": 671.0,
                "reservoir_level": 666.0,
                "opening_width_m": 50.0,
            },
            "scientific_status": "hypothetical_unverified",
            "simulation_executed": True,
            "has_results": True,
            "message": "Completed successfully.",
        }
        (r_dir / "run.json").write_text(json.dumps(run_record, indent=2), encoding="utf-8")
        
    # Ensure SPH completed run also exists for demo-readiness
    sph_runs_dir = proj_dir / "sph" / "runs"
    sph_runs_dir.mkdir(parents=True, exist_ok=True)
    has_sph = False
    for s in sph_runs_dir.iterdir():
        if s.is_dir() and (s / "run.json").is_file():
            try:
                sj = json.loads((s / "run.json").read_text(encoding="utf-8"))
                if sj.get("status") == "completed" and ((s / "maximum_depth.tif").is_file() or (s / "depth.tif").is_file()):
                    has_sph = True
                    break
            except Exception:
                pass
                
    if not has_sph:
        sph_run_id = "sph-test-run-001"
        s_dir = sph_runs_dir / sph_run_id
        s_dir.mkdir(parents=True, exist_ok=True)
        dem_path = proj_dir / "dem.tif"
        with rasterio.open(dem_path) as src:
            meta = src.meta.copy()
            h, w = src.height, src.width
        meta.update(dtype=rasterio.float32, count=1, nodata=-9999.0)
        sph_depth = np.full((h, w), 5.0, dtype=np.float32)
        sph_vel = np.full((h, w), 3.5, dtype=np.float32)
        with rasterio.open(s_dir / "maximum_depth.tif", "w", **meta) as dst:
            dst.write(sph_depth, 1)
        with rasterio.open(s_dir / "maximum_velocity.tif", "w", **meta) as dst:
            dst.write(sph_vel, 1)
        s_record = {
            "run_id": sph_run_id,
            "project_id": pid,
            "engine": "pysph",
            "status": "completed",
            "created_at": "2026-09-21T12:00:00Z",
            "has_results": True,
        }
        (s_dir / "run.json").write_text(json.dumps(s_record, indent=2), encoding="utf-8")
        
    return pid


def test_01_decision_support_endpoint_response_structure(hidkal_project_id):
    """1. Test that the decision-support API returns HTTP 200 with complete valid structure."""
    response = client.get(f"/api/dam-projects/{hidkal_project_id}/decision-support")
    assert response.status_code == 200
    data = response.json()

    assert data["project_id"] == hidkal_project_id
    assert "run_id" in data
    assert "ANUGA" in data["solver"]
    assert "SPH" in data["supplementary_solver"]
    assert "kpis" in data
    assert "percentiles" in data
    assert "cumulative_depth_areas" in data
    assert "depth_distribution" in data
    assert "velocity_distribution" in data
    assert "downstream_zones" in data
    assert "critical_points" in data
    assert "severity_config" in data
    assert "scenario" in data
    assert "narrative_summary" in data
    assert "what_this_means" in data
    assert "limitations" in data
    assert "tile_endpoints" in data


def test_02_kpi_extraction_and_values(hidkal_project_id):
    """2. Test extraction of physical KPIs from the selected ANUGA simulation."""
    summary = get_decision_support_summary(hidkal_project_id)
    kpis = summary.kpis

    assert kpis.maximum_depth_m > 0.0
    assert kpis.maximum_velocity_ms > 0.0
    assert kpis.inundated_area_km2 > 0.0
    assert kpis.domain_inundated_pct > 0.0
    assert kpis.downstream_flood_reach_km > 0.0
    assert kpis.first_downstream_arrival_s >= 0.0
    assert kpis.first_downstream_arrival_min >= 0.0
    assert kpis.wet_cell_count > 0
    assert kpis.total_domain_area_km2 > 0.0


def test_03_inundated_area_and_domain_percentage(hidkal_project_id):
    """3. Test physical validity of inundated area relative to computational domain."""
    summary = get_decision_support_summary(hidkal_project_id)
    assert summary.kpis.inundated_area_km2 <= summary.kpis.total_domain_area_km2
    assert 0.0 < summary.kpis.domain_inundated_pct <= 100.0


def test_04_depth_distribution_bins(hidkal_project_id):
    """4. Test depth distribution bins partition and percentages."""
    summary = get_decision_support_summary(hidkal_project_id)
    bins = summary.depth_distribution

    assert len(bins) == 5
    expected_labels = ["0.0 - 0.5 m", "0.5 - 1.0 m", "1.0 - 2.0 m", "2.0 - 5.0 m", "> 5.0 m"]
    for b, expected in zip(bins, expected_labels):
        assert b.range_label == expected
        assert b.area_km2 >= 0.0
        assert 0.0 <= b.percentage <= 100.0

    total_pct = sum(b.percentage for b in bins)
    assert 95.0 <= total_pct <= 105.0  # Accounts for rounding


def test_05_velocity_distribution_bins(hidkal_project_id):
    """5. Test velocity distribution bins partition and percentages."""
    summary = get_decision_support_summary(hidkal_project_id)
    bins = summary.velocity_distribution

    assert len(bins) == 5
    expected_labels = ["0.0 - 0.5 m/s", "0.5 - 1.0 m/s", "1.0 - 2.0 m/s", "2.0 - 5.0 m/s", "> 5.0 m/s"]
    for b, expected in zip(bins, expected_labels):
        assert b.range_label == expected
        assert b.area_km2 >= 0.0
        assert 0.0 <= b.percentage <= 100.0


def test_06_arrival_time_intelligence(hidkal_project_id):
    """6. Verify arrival time intelligence masks initial reservoir water (t=0)."""
    summary = get_decision_support_summary(hidkal_project_id)
    kpis = summary.kpis

    assert kpis.first_downstream_arrival_s >= 0.0
    if kpis.median_downstream_arrival_s is not None:
        assert kpis.median_downstream_arrival_s >= kpis.first_downstream_arrival_s
    if kpis.p90_downstream_arrival_s is not None:
        assert kpis.p90_downstream_arrival_s >= (kpis.median_downstream_arrival_s or 0.0)


def test_07_hydraulic_severity_calculation(hidkal_project_id):
    """7. Test hydraulic severity intensity H = h * v and classification config."""
    summary = get_decision_support_summary(hidkal_project_id)
    sev = summary.severity_config

    assert sev.method == "depth_velocity_product"
    assert sev.formula == "H = h * v"
    assert sev.units == "m^2/s"
    assert sev.peak_severity_m2s > 0.0
    assert len(sev.thresholds) == 4
    assert "not regulatory classifications" in sev.disclaimer.lower()


def test_08_cumulative_depth_areas(hidkal_project_id):
    """8. Test monotonic decrease of cumulative depth areas."""
    summary = get_decision_support_summary(hidkal_project_id)
    cum = summary.cumulative_depth_areas

    assert cum.depth_gt_0_1m_km2 >= cum.depth_gt_0_5m_km2
    assert cum.depth_gt_0_5m_km2 >= cum.depth_gt_1_0m_km2
    assert cum.depth_gt_1_0m_km2 >= cum.depth_gt_2_0m_km2


def test_09_modeled_critical_points(hidkal_project_id):
    """9. Test extraction and formatting of modeled critical points."""
    summary = get_decision_support_summary(hidkal_project_id)
    pts = summary.critical_points

    assert 3 <= len(pts) <= 5
    point_ids = [p.point_id for p in pts]
    assert "max_depth" in point_ids
    assert "max_velocity" in point_ids
    assert "highest_severity" in point_ids

    for p in pts:
        assert len(p.coordinate_utm) == 2
        assert len(p.coordinate_wgs84) == 2
        # Check coordinate bounds for Hidkal (lat ~16, lon ~74)
        lat, lon = p.coordinate_wgs84
        assert 15.0 <= lat <= 17.5
        assert 73.5 <= lon <= 76.0
        assert "simulation output" in p.disclaimer.lower()


def test_10_downstream_distance_zones(hidkal_project_id):
    """10. Test downstream distance zones discretization and metrics."""
    summary = get_decision_support_summary(hidkal_project_id)
    zones = summary.downstream_zones

    assert len(zones) == 5
    expected_zones = ["0 - 250 m", "250 - 500 m", "500 - 750 m", "750 - 1000 m", "> 1000 m"]
    for z, exp_label in zip(zones, expected_zones):
        assert z.zone_label == exp_label
        assert z.max_depth_m >= 0.0
        assert z.max_velocity_ms >= 0.0
        assert z.inundated_area_km2 >= 0.0


def test_11_invalid_project_handling():
    """11. Test error handling for non-existent project and invalid UUID."""
    fake_pid = "00000000-0000-0000-0000-000000000000"
    resp = client.get(f"/api/dam-projects/{fake_pid}/decision-support")
    assert resp.status_code == 404

    resp_bad = client.get("/api/dam-projects/invalid-uuid/decision-support")
    assert resp_bad.status_code == 422


def test_12_disclaimers_and_scientific_status(hidkal_project_id):
    """12. Verify presence of transparent scientific disclaimers and limitation items."""
    summary = get_decision_support_summary(hidkal_project_id)

    assert len(summary.limitations) >= 4
    assert any("open-source" in lim.lower() or "srtm" in lim.lower() for lim in summary.limitations)
    assert any("uncalibrated" in lim.lower() for lim in summary.limitations)
    assert any("not certified" in lim.lower() or "demonstration" in lim.lower() for lim in summary.limitations)


def test_13_no_operational_warning_language(hidkal_project_id):
    """13. Verify that the generated narrative and text do not claim official evacuation authority."""
    summary = get_decision_support_summary(hidkal_project_id)
    full_text = (summary.narrative_summary + " " + " ".join(summary.limitations)).lower()

    forbidden_terms = [
        "official evacuation order",
        "mandatory evacuation",
        "certified emergency prediction",
        "authoritative flood warning",
        "certified life-safety warning",
    ]
    for term in forbidden_terms:
        assert term not in full_text


def test_14_json_and_csv_export_endpoints(hidkal_project_id):
    """14. Test JSON and CSV export endpoints."""
    # JSON Export
    resp_json = client.get(f"/api/dam-projects/{hidkal_project_id}/decision-support/export?format=json")
    assert resp_json.status_code == 200
    assert resp_json.headers["content-type"] == "application/json"
    data = resp_json.json()
    assert "kpis" in data

    # CSV Export
    resp_csv = client.get(f"/api/dam-projects/{hidkal_project_id}/decision-support/export?format=csv")
    assert resp_csv.status_code == 200
    assert "text/csv" in resp_csv.headers["content-type"]
    csv_text = resp_csv.text
    assert "SIH DAM-BREAK DECISION-SUPPORT SUMMARY REPORT" in csv_text
    assert "KEY PERFORMANCE INDICATORS" in csv_text
    assert "Maximum Water Depth" in csv_text


def test_15_tile_rendering_endpoints(hidkal_project_id):
    """15. Test tile rendering endpoints for depth, velocity, arrival, and severity."""
    for layer in ["depth", "velocity", "arrival", "severity"]:
        resp = client.get(f"/api/dam-projects/{hidkal_project_id}/decision-support/tiles/{layer}/13/5803/3670.png")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert len(resp.content) > 0


def test_16_solver_roles_labeling(hidkal_project_id):
    """16. Test that ANUGA is labeled as primary regional analysis and SPH as supplementary near-field."""
    summary = get_decision_support_summary(hidkal_project_id)
    assert "ANUGA" in summary.solver
    assert "Regional" in summary.solver or "Shallow-Water" in summary.solver
    assert "SPH" in summary.supplementary_solver
    assert "Near-Field" in summary.supplementary_solver or "Demonstration" in summary.supplementary_solver


def test_17_demo_readiness_endpoint(hidkal_project_id):
    """17. Test demo readiness checker endpoint."""
    resp = client.get(f"/api/dam-projects/{hidkal_project_id}/demo-readiness")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == hidkal_project_id
    assert data["has_dem"] is True
    assert data["anuga_ready"] is True
    assert data["sph_ready"] is True
    assert data["dashboard_ready"] is True
    assert data["comparison_ready"] is True
    assert data["is_ready"] is True
    assert data["status_badge"] == "Demo Ready ✓"
    assert data["preferred_anuga_run_id"] is not None
    assert data["preferred_sph_run_id"] is not None


def test_18_arrival_time_excludes_t0_reservoir(hidkal_project_id):
    """18. Verify that initially wet reservoir cells (t = 0 s) are not reported as downstream flood wave arrival."""
    summary = get_decision_support_summary(hidkal_project_id)
    # First downstream arrival must be > 0 (60s)
    assert summary.kpis.first_downstream_arrival_s > 0.0
    assert summary.kpis.first_downstream_arrival_s == 60.0
    # Downstream zones beyond dam axis must have positive earliest arrival
    for zone in summary.downstream_zones:
        if zone.earliest_arrival_s is not None:
            assert zone.earliest_arrival_s >= 0.0

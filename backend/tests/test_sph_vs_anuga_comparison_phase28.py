"""
Phase 28: SPH vs ANUGA Comparison Module Automated Tests.

Tests:
1. SPH run discovery
2. ANUGA run discovery
3. Same-project validation
4. Comparison payload generation
5. Missing SPH run error handling
6. Missing ANUGA run error handling
7. Incompatible run detection
8. Metric normalization (depth/velocity percentiles, area, arrival)
9. Correct solver labels ("Custom Terrain-SPH Near-Field Demonstration" & "ANUGA 2D Regional Shallow-Water Simulation")
10. No incorrect PySPH naming
11. No comparison across unrelated projects
12. API response structure (/api/dam-projects/{project_id}/model-comparison and /export)
"""

import os
import json
import uuid
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.onboarding_service import (
    load_or_create_hidkal_demo_project,
    get_dam_projects_dir,
)
from app.model_comparison_service import (
    get_project_engine_capabilities,
    get_sph_vs_anuga_comparison,
    compute_model_comparison,
)
from app.schemas import (
    ModelComparisonRunRequest,
    SPHvsANUGAComparisonResponse,
)

client = TestClient(app)


import shutil

@pytest.fixture(scope="module")
def hidkal_project_id():
    import numpy as np
    import rasterio
    demo = load_or_create_hidkal_demo_project()
    pid = demo.project_id
    p_dir = get_dam_projects_dir() / pid
    
    sph_runs_dir = p_dir / "sph" / "runs"
    anuga_runs_dir = p_dir / "runs"
    sph_runs_dir.mkdir(parents=True, exist_ok=True)
    anuga_runs_dir.mkdir(parents=True, exist_ok=True)
    
    def is_valid_sph(r_dir):
        if not r_dir.is_dir() or not (r_dir / "run.json").is_file():
            return False
        try:
            d = json.loads((r_dir / "run.json").read_text(encoding="utf-8"))
            return d.get("status") == "completed" and ((r_dir / "maximum_depth.tif").is_file() or (r_dir / "depth.tif").is_file())
        except Exception:
            return False

    def is_valid_anuga(r_dir):
        if not r_dir.is_dir() or not (r_dir / "run.json").is_file():
            return False
        try:
            d = json.loads((r_dir / "run.json").read_text(encoding="utf-8"))
            if d.get("status") != "completed":
                return False
            res = r_dir / "results"
            for dn in ["maximum_depth.tif", "depth_max.tif", "depth.tif", "max_depth.tif"]:
                if (r_dir / dn).is_file() or (res / dn).is_file():
                    return True
            if res.is_dir():
                for sub in res.glob("*/*.tif"):
                    if "depth" in sub.name.lower():
                        return True
            return False
        except Exception:
            return False

    has_sph = any(is_valid_sph(s) for s in sph_runs_dir.iterdir() if s.is_dir())
    has_anuga = any(is_valid_anuga(a) for c_dir in [anuga_runs_dir, p_dir / "anuga" / "runs"] if c_dir.is_dir() for a in c_dir.iterdir() if a.is_dir())

    dem_path = p_dir / "dem.tif"
    with rasterio.open(dem_path) as src:
        meta = src.meta.copy()
        h, w = src.height, src.width
    meta.update(dtype=rasterio.float32, count=1, nodata=-9999.0)

    if not has_sph:
        sph_run_id = "sph-test-run-001"
        s_dir = sph_runs_dir / sph_run_id
        s_dir.mkdir(parents=True, exist_ok=True)
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
            "discrete_element_count": 1017,
            "discrete_element_type": "particles",
            "first_downstream_arrival_s": 5.95,
            "arrival_threshold_m": 0.05,
            "simulation_duration_s": 24.0,
            "wall_clock_runtime_s": 3.55,
            "domain_area_km2": 521.903,
            "downstream_extent_m": 450.0,
            "inundated_area_km2": 521.903,
            "spatial_resolution_m": 10.0,
        }
        (s_dir / "run.json").write_text(json.dumps(s_record, indent=2), encoding="utf-8")

    if not has_anuga:
        anuga_run_id = "a1b2c3d4-e5f6-4a7b-8c9d-012345678929"
        r_dir = anuga_runs_dir / anuga_run_id
        res_dir = r_dir / "results"
        res_dir.mkdir(parents=True, exist_ok=True)
        depth_data = np.full((h, w), 6.0, dtype=np.float32)
        vel_data = np.full((h, w), 4.0, dtype=np.float32)
        arr_data = np.full((h, w), 60.0, dtype=np.float32)
        with rasterio.open(res_dir / "maximum_depth.tif", "w", **meta) as dst:
            dst.write(depth_data, 1)
        with rasterio.open(res_dir / "maximum_velocity.tif", "w", **meta) as dst:
            dst.write(vel_data, 1)
        with rasterio.open(res_dir / "arrival_time.tif", "w", **meta) as dst:
            dst.write(arr_data, 1)
        run_record = {
            "run_id": anuga_run_id,
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

    return pid
    return pid


def test_01_sph_run_discovery(hidkal_project_id):
    """1. Test discovery of completed SPH simulation runs."""
    caps = get_project_engine_capabilities(hidkal_project_id)
    assert "pysph" in caps.engines
    sph_cap = caps.engines["pysph"]
    assert sph_cap.completed_run_count >= 1
    assert sph_cap.comparable_run_count >= 1
    assert sph_cap.available_for_comparison is True


def test_02_anuga_run_discovery(hidkal_project_id):
    """2. Test discovery of completed ANUGA simulation runs."""
    caps = get_project_engine_capabilities(hidkal_project_id)
    assert "anuga" in caps.engines
    anuga_cap = caps.engines["anuga"]
    assert anuga_cap.completed_run_count >= 1
    assert anuga_cap.comparable_run_count >= 1
    assert anuga_cap.available_for_comparison is True


def test_03_same_project_validation(hidkal_project_id):
    """3. Test that comparison confirms both runs belong to the exact same project."""
    comp = get_sph_vs_anuga_comparison(hidkal_project_id)
    assert comp.same_project is True
    assert comp.project_id == hidkal_project_id
    assert comp.sph_run_id is not None
    assert comp.anuga_run_id is not None


def test_04_comparison_payload_generation(hidkal_project_id):
    """4. Test complete comparison payload generation including compatibility and disclaimers."""
    comp = get_sph_vs_anuga_comparison(hidkal_project_id)
    assert isinstance(comp, SPHvsANUGAComparisonResponse)
    assert len(comp.disclaimers) >= 3
    assert len(comp.scenario_compatibility) == 12
    assert len(comp.factual_insights) >= 3
    assert len(comp.time_sync_map) >= 10


def test_05_missing_sph_run_error_handling(hidkal_project_id):
    """5. Test error handling when an invalid/missing SPH run ID is requested."""
    with pytest.raises(Exception) as exc_info:
        get_sph_vs_anuga_comparison(hidkal_project_id, sph_run_id="nonexistent-sph-run-id")
    assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


def test_06_missing_anuga_run_error_handling(hidkal_project_id):
    """6. Test error handling when an invalid/missing ANUGA run ID is requested."""
    with pytest.raises(Exception) as exc_info:
        get_sph_vs_anuga_comparison(hidkal_project_id, anuga_run_id="nonexistent-anuga-run-id")
    assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


def test_07_incompatible_run_detection(hidkal_project_id):
    """7. Test scenario compatibility table parameter classification and explanations."""
    comp = get_sph_vs_anuga_comparison(hidkal_project_id)
    classifs = {item.parameter_name: item.classification for item in comp.scenario_compatibility}
    
    assert classifs["Terrain Dataset Source"] == "SAME"
    assert classifs["DEM Grid & CRS"] == "SAME"
    assert classifs["Dam Center Location"] == "SAME"
    assert classifs["Breach Location"] == "SAME"
    assert classifs["Breach Width"] == "SAME"
    assert classifs["Reservoir Pool Level"] == "SAME"
    assert classifs["Roughness / Manning's n"] == "SAME"
    assert classifs["Simulation Duration"] == "DIFFERENT"
    assert classifs["Downstream Modeled Extent"] == "DIFFERENT"
    assert classifs["Dam Crest Geometry"] in ["SIMILAR", "SAME"]
    assert classifs["Spatial Discretization"] in ["SIMILAR", "SAME"]


def test_08_metric_normalization(hidkal_project_id):
    """8. Test percentile metrics normalization for depth and velocity."""
    comp = get_sph_vs_anuga_comparison(hidkal_project_id)
    
    # SPH metrics
    assert comp.sph_metrics.depth_percentiles.max > 0
    assert comp.sph_metrics.depth_percentiles.p50 >= 0
    assert comp.sph_metrics.depth_percentiles.p90 <= comp.sph_metrics.depth_percentiles.max
    assert comp.sph_metrics.velocity_percentiles.max > 0
    assert comp.sph_metrics.discrete_element_type == "particles"
    assert comp.sph_metrics.discrete_element_count > 0
    
    # ANUGA metrics
    assert comp.anuga_metrics.depth_percentiles.max > 0
    assert comp.anuga_metrics.depth_percentiles.p50 >= 0
    assert comp.anuga_metrics.velocity_percentiles.max > 0
    assert comp.anuga_metrics.discrete_element_type == "mesh triangles"
    assert comp.anuga_metrics.discrete_element_count > 0

    # Overlap
    assert comp.spatial_comparison.spatial_agreement_iou > 0.5


def test_09_correct_solver_labels(hidkal_project_id):
    """9. Test correct naming and role profiling for both solvers."""
    comp = get_sph_vs_anuga_comparison(hidkal_project_id)
    assert comp.sph_metrics.solver_name == "Custom Terrain-SPH Near-Field Demonstration"
    assert comp.anuga_metrics.solver_name == "ANUGA 2D Regional Shallow-Water Simulation"
    assert "Lagrangian" in comp.sph_metrics.solver_type
    assert "SWE" in comp.anuga_metrics.solver_type or "Shallow-Water" in comp.anuga_metrics.solver_type


def test_10_no_incorrect_pysph_official_naming(hidkal_project_id):
    """10. Test that SPH is described as a custom prototype and not an official PySPH replacement for ANUGA."""
    comp = get_sph_vs_anuga_comparison(hidkal_project_id)
    role_sph = comp.solver_roles["sph"]
    assert "Near-Field" in role_sph.solver_name or "Custom Terrain-SPH" in role_sph.solver_name
    assert "Lagrangian" in role_sph.solver_type
    # Confirm ANUGA is not described as a particle simulator
    role_anuga = comp.solver_roles["anuga"]
    assert "Finite-Volume" in role_anuga.solver_type or "SWE" in role_anuga.solver_type


def test_11_no_comparison_across_unrelated_projects():
    """11. Test rejection when trying to compare against a nonexistent or unrelated project ID."""
    fake_id = str(uuid.uuid4())
    with pytest.raises(Exception) as exc_info:
        get_sph_vs_anuga_comparison(fake_id)
    assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


def test_12_api_response_structure_and_export(hidkal_project_id):
    """12. Test HTTP endpoints for model comparison and export."""
    # 1. Main comparison endpoint
    res = client.get(f"/api/dam-projects/{hidkal_project_id}/model-comparison")
    assert res.status_code == 200
    data = res.json()
    assert data["project_id"] == hidkal_project_id
    assert "sph_metrics" in data
    assert "anuga_metrics" in data
    assert "scenario_compatibility" in data
    assert "time_sync_map" in data

    # 2. JSON Export
    res_json = client.get(f"/api/dam-projects/{hidkal_project_id}/model-comparison/export?format=json")
    assert res_json.status_code == 200
    assert res_json.headers["content-type"] == "application/json"

    # 3. CSV Export
    res_csv = client.get(f"/api/dam-projects/{hidkal_project_id}/model-comparison/export?format=csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["content-type"]
    assert "SPH VS ANUGA HYDRODYNAMIC COMPARISON REPORT" in res_csv.text


def test_13_no_unsupported_3d_claims_and_conservative_language(hidkal_project_id):
    """13. Verify that SPH is described as a 2D depth-integrated prototype without unsupported 3D claims."""
    comp = get_sph_vs_anuga_comparison(hidkal_project_id)
    
    # Check solver roles and metric descriptions
    sph_role = comp.solver_roles["sph"]
    combined_text = (
        comp.sph_metrics.solver_type + " " +
        sph_role.numerical_formulation + " " +
        " ".join(sph_role.best_represented_for) + " " +
        " ".join(sph_role.limitations) + " " +
        comp.judge_30s_explanation + " " +
        " ".join(comp.factual_insights)
    ).lower()

    assert "3d-like" not in combined_text
    assert "3d free-surface jet" not in combined_text
    assert "3d surface column" not in combined_text
    assert "vertical acceleration" not in combined_text
    assert "vertical velocity profile" not in combined_text
    assert "3d kinetic energy" not in combined_text
    assert "2d depth-integrated" in sph_role.numerical_formulation.lower() or "2d particle" in comp.sph_metrics.solver_type.lower()


def test_14_no_certification_claims(hidkal_project_id):
    """14. Verify that the comparison does not use certification or authoritative claims."""
    comp = get_sph_vs_anuga_comparison(hidkal_project_id)
    all_text = json.dumps(comp.model_dump()).lower()
    
    forbidden_words = [
        "certified regional inundation",
        "hydraulic accuracy",
        "validated accuracy",
        "engineering-grade prediction",
        "precise prediction",
        "authoritative prediction",
    ]
    for word in forbidden_words:
        assert word not in all_text, f"Found forbidden overclaim '{word}' in comparison payload"


def test_15_arrival_time_from_metadata(hidkal_project_id):
    """15. Verify that SPH first arrival time reflects post-breach metadata and not t=0."""
    comp = get_sph_vs_anuga_comparison(hidkal_project_id)
    # SPH breach opens at t=5.0s, first arrival downstream is 5.95s (not 0.0s)
    assert comp.sph_metrics.first_downstream_arrival_s >= 5.0
    assert comp.anuga_metrics.first_downstream_arrival_s >= 0.0


def test_16_breach_parameters_and_insights_auditing(hidkal_project_id):
    """16. Verify breach parameters match metadata and factual insights distinguish observed outputs."""
    comp = get_sph_vs_anuga_comparison(hidkal_project_id)
    compat = {item.parameter_name: item for item in comp.scenario_compatibility}
    
    assert "50.0 m" in compat["Breach Width"].sph_value
    assert "50.0 m" in compat["Breach Width"].anuga_value
    assert compat["Breach Width"].classification == "SAME"
    
    assert compat["Breach Start Time"].classification == "DIFFERENT"
    assert "5.0 s" in compat["Breach Start Time"].sph_value
    assert "0.0 s" in compat["Breach Start Time"].anuga_value

    # Verify insights do not claim model superiority
    for insight in comp.factual_insights:
        assert "more accurate" not in insight.lower()
        assert "true flood extent" not in insight.lower()
        assert "superior" not in insight.lower()


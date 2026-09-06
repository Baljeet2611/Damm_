"""
Unit and integration tests for Phase 16 & 17 ANUGA Pilot & Refined Model API integration.
Tests hazard source registry, ANUGA run details (baseline vs refined adaptive),
raster metadata/tiles/values/legends, path traversal security, coordinate reprojection,
multi-source exposure screening, damage scenario propagation, route screening,
and cryptographic manifest provenance.
"""

import io
import json
from pathlib import Path
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app

client = TestClient(app)


def test_get_hazard_sources():
    """Verify GET /api/hazard-sources returns sample, baseline ANUGA pilot, and refined ANUGA model."""
    resp = client.get("/api/hazard-sources")
    assert resp.status_code == 200
    data = resp.json()

    assert data["default_source"] == "sample_hidkal"
    assert len(data["sources"]) == 3

    src_map = {s["id"]: s for s in data["sources"]}
    assert "sample_hidkal" in src_map
    assert "anuga_hidkal_pilot" in src_map
    assert "anuga_hidkal_refined" in src_map

    sample = src_map["sample_hidkal"]
    assert sample["status"] == "unverified_sample"
    assert sample["default_screening_threshold"] == 0.0

    pilot = src_map["anuga_hidkal_pilot"]
    assert pilot["status"] == "hypothetical_unverified"
    assert "hypothetical" in pilot["disclaimer"].lower()
    assert pilot["default_screening_threshold"] == 0.10
    assert "depth" in pilot["layers"]

    refined = src_map["anuga_hidkal_refined"]
    assert refined["status"] == "hypothetical_unverified"
    assert "hypothetical" in refined["disclaimer"].lower()
    assert refined["default_screening_threshold"] == 0.10
    assert refined["run_id"] == "anuga_hidkal_refined_hypothetical_v1"
    assert "depth" in refined["layers"]


def test_get_anuga_runs_list_and_detail():
    """Verify listing ANUGA runs (pilot and refined) and retrieving detailed run metadata with manifest."""
    resp = client.get("/api/anuga/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) >= 2

    run_map = {r["run_id"]: r for r in runs}
    assert "anuga_hidkal_pilot_hypothetical_v1" in run_map
    assert "anuga_hidkal_refined_hypothetical_v1" in run_map

    # Phase 15 Baseline Pilot
    run_pilot = run_map["anuga_hidkal_pilot_hypothetical_v1"]
    assert run_pilot["breach_width_m"] == 200.0
    assert run_pilot["mesh_triangles"] == 66000

    # Phase 17 Refined Model
    run_refined = run_map["anuga_hidkal_refined_hypothetical_v1"]
    assert run_refined["breach_width_m"] == 200.0
    assert run_refined["mesh_triangles"] == 131351
    assert run_refined["mesh_vertices"] == 65941

    # Get details for refined run
    detail_resp = client.get(f"/api/anuga/runs/{run_refined['run_id']}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["run_id"] == run_refined["run_id"]
    assert detail["breach_mechanics"]["effective_breach_width_m"] == 200.0
    err_val = detail["volume_conservation"].get("mass_balance_error_relative", detail["volume_conservation"].get("relative_volume_error", 0.0))
    assert err_val < 1e-10
    assert "manifest" in detail


def test_anuga_raster_metadata_and_legend():
    """Verify metadata and legend endpoints for ANUGA pilot and refined layers."""
    for hazard_source in ["anuga_hidkal_pilot", "anuga_hidkal_refined"]:
        for layer in ["depth", "velocity", "arrival"]:
            meta_resp = client.get(f"/api/anuga/rasters/{layer}/metadata?hazard_source={hazard_source}")
            assert meta_resp.status_code == 200
            meta = meta_resp.json()
            assert meta["crs"] == "EPSG:32643"
            assert meta["width"] > 0
            assert meta["height"] > 0

            legend_resp = client.get(f"/api/anuga/rasters/{layer}/legend?hazard_source={hazard_source}")
            assert legend_resp.status_code == 200
            legend = legend_resp.json()
            assert len(legend["items"]) > 0
            assert len(legend["color_ramp"]) > 0


def test_anuga_raster_tile_endpoint():
    """Verify XYZ tile rendering for ANUGA pilot and refined rasters with bilinear interpolation."""
    for hazard_source in ["anuga_hidkal_pilot", "anuga_hidkal_refined"]:
        resp = client.get(f"/api/anuga/rasters/depth/tiles/11/1448/930.png?hazard_source={hazard_source}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        img = Image.open(io.BytesIO(resp.content))
        assert img.size == (256, 256)
        assert img.mode == "RGBA"

    # Out of bounds tile
    oob_resp = client.get("/api/anuga/rasters/depth/tiles/10/10/10.png?hazard_source=anuga_hidkal_refined")
    assert oob_resp.status_code == 200
    assert oob_resp.headers["content-type"] == "image/png"


def test_anuga_raster_point_value_with_reprojection():
    """Verify point query with coordinate transformation from WGS84 to EPSG:32643 for refined run."""
    # Query point within reservoir area
    resp = client.get("/api/anuga/rasters/depth/value?lon=74.63&lat=16.20&hazard_source=anuga_hidkal_refined")
    assert resp.status_code == 200
    data = resp.json()
    assert data["row"] >= 0
    assert data["column"] >= 0
    assert "value" in data

    # Test arrival semantics
    arr_resp = client.get("/api/anuga/rasters/arrival/value?lon=74.63&lat=16.20&hazard_source=anuga_hidkal_refined")
    assert arr_resp.status_code == 200
    arr_data = arr_resp.json()
    if arr_data["value"] is not None:
        assert arr_data["value"] >= 0.0

    # Query out-of-bounds coordinates returns 422
    err_resp = client.get("/api/anuga/rasters/depth/value?lon=70.0&lat=10.0&hazard_source=anuga_hidkal_refined")
    assert err_resp.status_code == 422


def test_anuga_path_traversal_and_invalid_layer_security():
    """Verify path traversal attempts and invalid layer names return 404/422 without exposing paths."""
    bad_resp = client.get("/api/anuga/rasters/../../etc/passwd/metadata")
    assert bad_resp.status_code in (404, 422)
    assert "etc" not in bad_resp.text.lower()

    invalid_resp = client.get("/api/anuga/rasters/arbitrary_layer/metadata")
    assert invalid_resp.status_code == 404

    invalid_run = client.get("/api/anuga/runs/malicious_run_id")
    assert invalid_run.status_code == 404


def test_exposure_screening_with_anuga_pilot_source():
    """Verify exposure analysis with hazard_source='anuga_hidkal_pilot'."""
    resp = client.get("/api/exposure/summary?hazard_source=anuga_hidkal_pilot&threshold=0.10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hazard_source"] == "anuga_hidkal_pilot"
    assert data["screening_threshold"] == 0.10
    assert "hypothetical" in data["disclaimer"].lower()
    assert data["assets"]["total"] > 0
    assert data["roads"]["total"] > 0
    assert "initially_wet_reservoir_assets" in data

    assets_resp = client.get("/api/exposure/assets?hazard_source=anuga_hidkal_pilot&threshold=0.10")
    assert assets_resp.status_code == 200
    assets_fc = assets_resp.json()
    props0 = assets_fc["features"][0]["properties"]
    assert props0["hazard_source"] == "anuga_hidkal_pilot"
    assert props0["screening_threshold"] == 0.10


def test_exposure_screening_with_anuga_refined_source():
    """Verify exposure analysis with hazard_source='anuga_hidkal_refined'."""
    # 1. Summary
    resp = client.get("/api/exposure/summary?hazard_source=anuga_hidkal_refined&threshold=0.10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hazard_source"] == "anuga_hidkal_refined"
    assert data["screening_threshold"] == 0.10
    assert "hypothetical" in data["disclaimer"].lower()
    assert data["assets"]["total"] > 0
    assert data["roads"]["total"] > 0
    assert "initially_wet_reservoir_assets" in data

    # 2. Assets FeatureCollection
    assets_resp = client.get("/api/exposure/assets?hazard_source=anuga_hidkal_refined&threshold=0.10")
    assert assets_resp.status_code == 200
    assets_fc = assets_resp.json()
    props0 = assets_fc["features"][0]["properties"]
    assert props0["hazard_source"] == "anuga_hidkal_refined"
    assert props0["screening_threshold"] == 0.10


def test_damage_scenario_with_anuga_pilot_source():
    """Verify damage estimation propagates baseline pilot ANUGA source and run ID."""
    payload = {
        "hazard_source": "anuga_hidkal_pilot",
        "screening_threshold": 0.10,
        "assumed_depth_unit": "assumed metres based on source interpretation",
        "currency_label": "INR (₹)",
        "replacement_values": {
            "building": 2500000.0,
            "healthcare": 15000000.0,
            "education": 8000000.0,
            "emergency": 10000000.0,
            "settlement": 5000000.0,
            "transport": 3000000.0,
            "other": 1000000.0,
        },
        "depth_damage_curve": [
            {"depth": 0.0, "damage_ratio": 0.0},
            {"depth": 1.0, "damage_ratio": 0.3},
            {"depth": 5.0, "damage_ratio": 1.0},
        ],
        "sensitivity_percentage": 20.0,
        "acknowledge_unverified_inputs": True,
    }

    resp = client.post("/api/damage/estimate", json=payload)
    assert resp.status_code == 200
    res = resp.json()
    assert res["hazard_source"] == "anuga_hidkal_pilot"
    assert res["run_id"] == "anuga_hidkal_pilot_hypothetical_v1"
    assert res["screening_threshold"] == 0.10


def test_damage_scenario_with_anuga_refined_source():
    """Verify damage estimation propagates refined ANUGA source and run ID."""
    payload = {
        "hazard_source": "anuga_hidkal_refined",
        "screening_threshold": 0.10,
        "assumed_depth_unit": "assumed metres based on source interpretation",
        "currency_label": "INR (₹)",
        "replacement_values": {
            "building": 2500000.0,
            "healthcare": 15000000.0,
            "education": 8000000.0,
            "emergency": 10000000.0,
            "settlement": 5000000.0,
            "transport": 3000000.0,
            "other": 1000000.0,
        },
        "depth_damage_curve": [
            {"depth": 0.0, "damage_ratio": 0.0},
            {"depth": 1.0, "damage_ratio": 0.3},
            {"depth": 5.0, "damage_ratio": 1.0},
        ],
        "sensitivity_percentage": 20.0,
        "acknowledge_unverified_inputs": True,
    }

    resp = client.post("/api/damage/estimate", json=payload)
    assert resp.status_code == 200
    res = resp.json()
    assert res["hazard_source"] == "anuga_hidkal_refined"
    assert res["run_id"] == "anuga_hidkal_refined_hypothetical_v1"
    assert res["screening_threshold"] == 0.10
    assert "hypothetical" in res["disclaimer"].lower()


def test_route_screening_with_anuga_pilot_source():
    """Verify route screening with hazard_source='anuga_hidkal_pilot'."""
    payload = {
        "hazard_source": "anuga_hidkal_pilot",
        "screening_threshold": 0.10,
        "start_lon": 74.65,
        "start_lat": 16.25,
        "end_lon": 74.75,
        "end_lat": 16.28,
        "avoid_screening_positive": True,
        "max_snap_distance_meters": 5000.0,
    }

    resp = client.post("/api/routes/screening", json=payload)
    assert resp.status_code == 200
    res = resp.json()
    assert res["hazard_source"] == "anuga_hidkal_pilot"
    assert res["screening_threshold"] == 0.10


def test_route_screening_with_anuga_refined_source():
    """Verify route screening with hazard_source='anuga_hidkal_refined'."""
    payload = {
        "hazard_source": "anuga_hidkal_refined",
        "screening_threshold": 0.10,
        "start_lon": 74.65,
        "start_lat": 16.25,
        "end_lon": 74.75,
        "end_lat": 16.28,
        "avoid_screening_positive": True,
        "max_snap_distance_meters": 5000.0,
    }

    resp = client.post("/api/routes/screening", json=payload)
    assert resp.status_code == 200
    res = resp.json()
    assert res["hazard_source"] == "anuga_hidkal_refined"
    assert res["screening_threshold"] == 0.10


def test_export_with_anuga_pilot_source():
    """Verify export endpoints support hazard_source='anuga_hidkal_pilot'."""
    resp = client.get("/api/export/assets?hazard_source=anuga_hidkal_pilot&threshold=0.10&format=geojson")
    assert resp.status_code == 200
    fc = resp.json()
    assert fc["type"] == "FeatureCollection"
    if fc["features"]:
        assert fc["features"][0]["properties"]["hazard_source"] == "anuga_hidkal_pilot"


def test_export_with_anuga_refined_source():
    """Verify export endpoints support hazard_source='anuga_hidkal_refined'."""
    resp = client.get("/api/export/assets?hazard_source=anuga_hidkal_refined&threshold=0.10&format=geojson")
    assert resp.status_code == 200
    fc = resp.json()
    assert fc["type"] == "FeatureCollection"
    if fc["features"]:
        assert fc["features"][0]["properties"]["hazard_source"] == "anuga_hidkal_refined"

    post_resp = client.post(
        "/api/export",
        json={
            "layer": "assets",
            "format": "geojson",
            "hazard_source": "anuga_hidkal_refined",
            "screening_threshold": 0.10,
            "exposure_filter": "all",
        },
    )
    assert post_resp.status_code == 200


def test_png_tile_signature_and_alpha_transparency():
    """Verify PNG tiles have exact PNG signature and RGBA alpha channel."""
    # Active tile over inundation (zoom 11, x 1448, y 930)
    resp = client.get("/api/anuga/rasters/depth/tiles/11/1448/930.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")
    img = Image.open(io.BytesIO(resp.content))
    assert img.mode == "RGBA"
    assert img.size == (256, 256)
    # Check alpha channel exists
    alpha_extrema = img.getextrema()[3]
    assert alpha_extrema[0] >= 0  # min alpha
    assert alpha_extrema[1] > 0   # max alpha has non-zero opacity

    # Empty transparent tile for out of bounds
    oob_resp = client.get("/api/anuga/rasters/depth/tiles/1/0/0.png")
    assert oob_resp.status_code == 200
    assert oob_resp.content.startswith(b"\x89PNG\r\n\x1a\n")
    oob_img = Image.open(io.BytesIO(oob_resp.content))
    assert oob_img.mode == "RGBA"
    # All alpha is 0
    assert oob_img.getextrema()[3] == (0, 0)


def test_anuga_stored_volume_agreement_within_half_percent():
    """Verify baseline and refined runs have initial stored volumes matching within 0.5%."""
    pilot_resp = client.get("/api/anuga/runs/anuga_hidkal_pilot_hypothetical_v1")
    assert pilot_resp.status_code == 200
    pilot_vol = pilot_resp.json()["provenance_metrics"]["initial_volume_assumed_mcm"]

    refined_resp = client.get("/api/anuga/runs/anuga_hidkal_refined_hypothetical_v1")
    assert refined_resp.status_code == 200
    refined_vol = refined_resp.json()["provenance_metrics"]["initial_volume_assumed_mcm"]

    pct_diff = abs(refined_vol - pilot_vol) / pilot_vol * 100.0
    assert pct_diff < 0.5, f"Initial volume difference {pct_diff:.3f}% exceeds 0.5% limit"


def test_manifest_validation_for_both_runs(monkeypatch, tmp_path):
    """Verify SHA-256 hash manifest verification succeeds for both baseline and refined runs."""
    from app.anuga_service import validate_anuga_manifest, get_anuga_dir

    # Normal valid checks
    valid_pilot, errors_pilot = validate_anuga_manifest("anuga_hidkal_pilot_hypothetical_v1")
    assert valid_pilot is True
    assert len(errors_pilot) == 0

    valid_refined, errors_refined = validate_anuga_manifest("anuga_hidkal_refined_hypothetical_v1")
    assert valid_refined is True
    assert len(errors_refined) == 0

    # Tampered manifest simulation for refined run
    refined_dir = get_anuga_dir("anuga_hidkal_refined_hypothetical_v1")
    real_manifest = json.loads((refined_dir / "manifest.json").read_text())
    tampered_manifest = real_manifest.copy()
    tampered_manifest["files"]["pilot_summary.json"] = "0000000000000000000000000000000000000000000000000000000000000000"

    def mock_get_anuga_dir(run_id="anuga_hidkal_refined"):
        temp_refined = tmp_path / "refined"
        temp_refined.mkdir(exist_ok=True)
        (temp_refined / "manifest.json").write_text(json.dumps(tampered_manifest))
        (temp_refined / "pilot_summary.json").write_text((refined_dir / "pilot_summary.json").read_text())
        return temp_refined

    monkeypatch.setattr("app.anuga_service.get_anuga_dir", mock_get_anuga_dir)
    valid_tampered, errors_tampered = validate_anuga_manifest("anuga_hidkal_refined_hypothetical_v1")
    assert valid_tampered is False
    assert any("mismatch" in e for e in errors_tampered)

    # API endpoint returns 409
    resp = client.get("/api/anuga/runs/anuga_hidkal_refined_hypothetical_v1")
    assert resp.status_code == 409
    err_body = resp.json()
    assert err_body["detail"]["code"] == "provenance_integrity_failed"


def test_absent_anuga_outputs_handling(monkeypatch, tmp_path):
    """Verify system handles absent output files gracefully with 404 / availability=False and no path leakage."""
    from app.anuga_service import check_anuga_outputs_available, resolve_anuga_layer_file

    def mock_empty_dir(run_id="anuga_hidkal_refined"):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir(exist_ok=True)
        return empty_dir

    monkeypatch.setattr("app.anuga_service.get_anuga_dir", mock_empty_dir)
    avail, reason = check_anuga_outputs_available("anuga_hidkal_refined_hypothetical_v1")
    assert avail is False
    assert "not found" in reason

    with pytest.raises(HTTPException) as exc_info:
        resolve_anuga_layer_file("depth", hazard_source="anuga_hidkal_refined")
    assert exc_info.value.status_code == 404
    err_detail = str(exc_info.value.detail).lower()
    assert "c:\\" not in err_detail
    assert "c:/" not in err_detail
    assert "/users/" not in err_detail


def test_anuga_pilot_exposure_threshold_reconciliation():
    """Regression test reconciling Phase 16 (29 assets at threshold 0.0) vs Phase 17 (8 assets at threshold 0.10)."""
    # Query at threshold 0.00 (Phase 16 raw wet query)
    res_t0 = client.get("/api/exposure/assets?hazard_source=anuga_hidkal_pilot&threshold=0.0")
    assert res_t0.status_code == 200
    fc_t0 = res_t0.json()
    exposed_t0 = [f for f in fc_t0["features"] if f["properties"]["exposed"]]
    assert len(exposed_t0) == 29, f"Expected 29 exposed assets at threshold 0.0, got {len(exposed_t0)}"

    # Query at threshold 0.10 (Phase 17 standardized hydraulic screening threshold)
    res_t10 = client.get("/api/exposure/assets?hazard_source=anuga_hidkal_pilot&threshold=0.10")
    assert res_t10.status_code == 200
    fc_t10 = res_t10.json()
    exposed_t10 = [f for f in fc_t10["features"] if f["properties"]["exposed"]]
    assert len(exposed_t10) == 8, f"Expected 8 exposed assets at threshold 0.10, got {len(exposed_t10)}"

    # Identify the exact 21 assets with 0.0 < depth < 0.10m using feature index / property id
    ids_t0 = {f["properties"].get("id") or idx for idx, f in enumerate(fc_t0["features"]) if f["properties"]["exposed"]}
    ids_t10 = {f["properties"].get("id") or idx for idx, f in enumerate(fc_t10["features"]) if f["properties"]["exposed"]}
    sub_threshold_ids = ids_t0 - ids_t10
    assert len(sub_threshold_ids) == 21

    # Verify all 21 assets have depth in range (0.0, 0.10)
    for idx, f in enumerate(fc_t0["features"]):
        fid = f["properties"].get("id") or idx
        if fid in sub_threshold_ids:
            d = f["properties"]["depth_value"]
            assert 0.0 < d < 0.10, f"Asset {fid} depth {d} not in range (0.0, 0.10)"


def test_anuga_mesh_sensitivity_rasterio_alignment_and_metrics():
    """Verify rasterio.warp.reproject alignment metrics and transform-derived cell area."""
    from app.anuga_service import get_anuga_dir
    refined_dir = get_anuga_dir("anuga_hidkal_refined_hypothetical_v1")
    summary_path = refined_dir / "pilot_summary.json"
    assert summary_path.is_file()

    summary = json.loads(summary_path.read_text())
    sens = summary["mesh_sensitivity"]

    assert "rasterio.warp.reproject" in sens["alignment_method"]
    assert sens["sensitivity_type"] == "volume-matched mesh sensitivity"
    assert sens["cell_area_km2"] == pytest.approx(0.00992188, rel=1e-4)
    assert sens["inundation_extent_iou"] == pytest.approx(0.7842, abs=1e-3)
    assert sens["inundated_area_baseline_km2"] == pytest.approx(44.4699, abs=1e-3)
    assert sens["inundated_area_refined_km2"] == pytest.approx(54.8085, abs=1e-3)
    assert sens["depth_mean_absolute_error_assumed_m"] == pytest.approx(0.9146, abs=1e-3)
    assert sens["depth_rmse_assumed_m"] == pytest.approx(1.2766, abs=1e-3)
    assert sens["depth_mean_bias_assumed_m"] == pytest.approx(0.0820, abs=1e-3)
    assert sens["velocity_mean_absolute_error_assumed_mps"] == pytest.approx(0.6291, abs=1e-3)
    assert sens["velocity_rmse_assumed_mps"] == pytest.approx(0.8249, abs=1e-3)
    assert sens["velocity_mean_bias_assumed_mps"] == pytest.approx(0.1385, abs=1e-3)
    assert sens["exposure_count_differences"]["assets_exposed_baseline"] == 8
    assert sens["exposure_count_differences"]["assets_exposed_refined"] == 62
    assert sens["exposure_count_differences"]["roads_flooded_baseline"] == 108
    assert sens["exposure_count_differences"]["roads_flooded_refined"] == 128


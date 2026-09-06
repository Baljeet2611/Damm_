"""
Unit and integration tests for Phase 16 ANUGA Pilot API integration.
Tests hazard source registry, ANUGA run details, raster metadata/tiles/values/legends,
path traversal security, coordinate reprojection, multi-source exposure screening,
damage scenario propagation, and route screening.
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
    """Verify GET /api/hazard-sources returns both sample and ANUGA pilot hazard sources."""
    resp = client.get("/api/hazard-sources")
    assert resp.status_code == 200
    data = resp.json()

    assert data["default_source"] == "sample_hidkal"
    assert len(data["sources"]) == 2

    src_map = {s["id"]: s for s in data["sources"]}
    assert "sample_hidkal" in src_map
    assert "anuga_hidkal_pilot" in src_map

    sample = src_map["sample_hidkal"]
    assert sample["status"] == "unverified_sample"
    assert sample["default_screening_threshold"] == 0.0

    anuga = src_map["anuga_hidkal_pilot"]
    assert anuga["status"] == "hypothetical_unverified"
    assert "hypothetical" in anuga["disclaimer"].lower()
    assert anuga["default_screening_threshold"] == 0.10
    assert "depth" in anuga["layers"]
    assert "velocity" in anuga["layers"]
    assert "arrival" in anuga["layers"]


def test_get_anuga_runs_list_and_detail():
    """Verify listing ANUGA runs and retrieving detailed run metadata with manifest."""
    resp = client.get("/api/anuga/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) >= 1
    run0 = runs[0]
    assert run0["run_id"] == "anuga_hidkal_pilot_hypothetical_v1"
    assert run0["breach_width_m"] == 200.0
    assert run0["arrival_time_resolution_sec"] == 60.0

    # Get details
    detail_resp = client.get(f"/api/anuga/runs/{run0['run_id']}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["run_id"] == run0["run_id"]
    assert detail["breach_mechanics"]["effective_breach_width_m"] == 200.0
    assert detail["volume_conservation"]["relative_volume_error"] < 1e-10
    assert "manifest" in detail


def test_anuga_raster_metadata_and_legend():
    """Verify metadata and legend endpoints for ANUGA depth, velocity, and arrival layers."""
    for layer in ["depth", "velocity", "arrival"]:
        meta_resp = client.get(f"/api/anuga/rasters/{layer}/metadata")
        assert meta_resp.status_code == 200
        meta = meta_resp.json()
        assert meta["crs"] == "EPSG:32643"
        assert meta["width"] > 0
        assert meta["height"] > 0

        legend_resp = client.get(f"/api/anuga/rasters/{layer}/legend")
        assert legend_resp.status_code == 200
        legend = legend_resp.json()
        assert len(legend["items"]) > 0
        assert len(legend["color_ramp"]) > 0


def test_anuga_raster_tile_endpoint():
    """Verify XYZ tile rendering for ANUGA pilot raster."""
    # Test valid tile over Hidkal area
    resp = client.get("/api/anuga/rasters/depth/tiles/11/1448/930.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(resp.content))
    assert img.size == (256, 256)

    # Test out of bounds tile returns transparent 256x256 without 500 error
    oob_resp = client.get("/api/anuga/rasters/depth/tiles/10/10/10.png")
    assert oob_resp.status_code == 200
    assert oob_resp.headers["content-type"] == "image/png"


def test_anuga_raster_point_value_with_reprojection():
    """Verify point query with coordinate transformation from WGS84 to EPSG:32643."""
    # Query point within reservoir area
    resp = client.get("/api/anuga/rasters/depth/value?lon=74.63&lat=16.20")
    assert resp.status_code == 200
    data = resp.json()
    assert data["row"] >= 0
    assert data["column"] >= 0
    assert "value" in data

    # Test arrival semantics
    arr_resp = client.get("/api/anuga/rasters/arrival/value?lon=74.63&lat=16.20")
    assert arr_resp.status_code == 200
    arr_data = arr_resp.json()
    # Inside initial reservoir pool, arrival is 0.0
    if arr_data["value"] is not None:
        assert arr_data["value"] >= 0.0

    # Query out-of-bounds coordinates returns 422
    err_resp = client.get("/api/anuga/rasters/depth/value?lon=70.0&lat=10.0")
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


def test_exposure_screening_with_anuga_source():
    """Verify exposure analysis with hazard_source='anuga_hidkal_pilot'."""
    # 1. Summary
    resp = client.get("/api/exposure/summary?hazard_source=anuga_hidkal_pilot&threshold=0.10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hazard_source"] == "anuga_hidkal_pilot"
    assert data["screening_threshold"] == 0.10
    assert "hypothetical" in data["disclaimer"].lower()
    assert data["assets"]["total"] > 0
    assert data["roads"]["total"] > 0
    assert "initially_wet_reservoir_assets" in data

    # 2. Assets FeatureCollection
    assets_resp = client.get("/api/exposure/assets?hazard_source=anuga_hidkal_pilot&threshold=0.10")
    assert assets_resp.status_code == 200
    assets_fc = assets_resp.json()
    props0 = assets_fc["features"][0]["properties"]
    assert props0["hazard_source"] == "anuga_hidkal_pilot"
    assert props0["screening_threshold"] == 0.10


def test_damage_scenario_with_anuga_source():
    """Verify damage estimation propagates ANUGA source and run ID."""
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
    assert "hypothetical" in res["disclaimer"].lower()


def test_route_screening_with_anuga_source():
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


def test_export_with_anuga_source():
    """Verify export endpoints support hazard_source and screening_threshold."""
    # GET export
    resp = client.get("/api/export/assets?hazard_source=anuga_hidkal_pilot&threshold=0.10&format=geojson")
    assert resp.status_code == 200
    fc = resp.json()
    assert fc["type"] == "FeatureCollection"
    if fc["features"]:
        assert fc["features"][0]["properties"]["hazard_source"] == "anuga_hidkal_pilot"

    # POST export
    post_resp = client.post(
        "/api/export",
        json={
            "layer": "assets",
            "format": "geojson",
            "hazard_source": "anuga_hidkal_pilot",
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


def test_manifest_validation_and_tampered_hash_rejection(monkeypatch, tmp_path):
    """Verify SHA-256 hash manifest verification succeeds normally and rejects tampered files."""
    from app.anuga_service import validate_anuga_manifest, get_anuga_dir

    # Normal valid check
    valid, errors = validate_anuga_manifest("anuga_hidkal_pilot_hypothetical_v1")
    assert valid is True
    assert len(errors) == 0

    # Invalid run ID check
    valid_bad, errors_bad = validate_anuga_manifest("unknown_run")
    assert valid_bad is False
    assert "Unknown ANUGA run" in errors_bad[0]

    # Tampered manifest simulation
    pilot_dir = get_anuga_dir()
    real_manifest = json.loads((pilot_dir / "manifest.json").read_text())
    tampered_manifest = real_manifest.copy()
    tampered_manifest["files"]["pilot_summary.json"] = "0000000000000000000000000000000000000000000000000000000000000000"

    tampered_manifest_path = tmp_path / "manifest.json"
    tampered_manifest_path.write_text(json.dumps(tampered_manifest))

    # Monkeypatch pilot_dir to point to modified manifest
    def mock_get_anuga_dir():
        temp_pilot = tmp_path / "pilot"
        temp_pilot.mkdir(exist_ok=True)
        (temp_pilot / "manifest.json").write_text(json.dumps(tampered_manifest))
        (temp_pilot / "pilot_summary.json").write_text((pilot_dir / "pilot_summary.json").read_text())
        return temp_pilot

    monkeypatch.setattr("app.anuga_service.get_anuga_dir", mock_get_anuga_dir)
    valid_tampered, errors_tampered = validate_anuga_manifest("anuga_hidkal_pilot_hypothetical_v1")
    assert valid_tampered is False
    assert any("mismatch" in e for e in errors_tampered)

    # API endpoint check for HTTP 409 and code 'provenance_integrity_failed'
    resp = client.get("/api/anuga/runs/anuga_hidkal_pilot_hypothetical_v1")
    assert resp.status_code == 409
    err_body = resp.json()
    assert "detail" in err_body
    assert err_body["detail"]["code"] == "provenance_integrity_failed"
    assert "pilot_summary.json" in str(err_body["detail"]["errors"])

    # Information leakage check: no absolute paths or tracebacks
    resp_text = resp.text.lower()
    assert "traceback" not in resp_text
    assert "c:\\" not in resp_text
    assert "c:/" not in resp_text
    assert "/users/" not in resp_text


def test_absent_anuga_outputs_handling(monkeypatch, tmp_path):
    """Verify system handles absent output files gracefully with 404 / availability=False and no path leakage."""
    from app.anuga_service import check_anuga_outputs_available, resolve_anuga_layer_file

    def mock_empty_dir():
        empty_pilot = tmp_path / "empty_pilot"
        empty_pilot.mkdir(exist_ok=True)
        return empty_pilot

    monkeypatch.setattr("app.anuga_service.get_anuga_dir", mock_empty_dir)
    avail, reason = check_anuga_outputs_available("anuga_hidkal_pilot_hypothetical_v1")
    assert avail is False
    assert "not found" in reason

    with pytest.raises(HTTPException) as exc_info:
        resolve_anuga_layer_file("depth")
    assert exc_info.value.status_code == 404
    err_detail = str(exc_info.value.detail).lower()
    # Check that absolute paths are not exposed
    assert "c:\\" not in err_detail
    assert "c:/" not in err_detail
    assert "/users/" not in err_detail



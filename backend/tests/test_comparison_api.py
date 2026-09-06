import json
import numpy as np
from fastapi.testclient import TestClient

import rasterio
from rasterio.transform import from_origin

from app.main import app

client = TestClient(app)


def test_comparison_readiness_initial():
    response = client.get("/api/comparison/readiness")
    assert response.status_code == 200
    data = response.json()
    assert "delft3d_completed_runs" in data
    assert "sph_completed_runs" in data
    assert "comparison_ready" in data
    assert "methodology_summary" in data


def test_comparison_methodology():
    response = client.get("/api/comparison/methodology")
    assert response.status_code == 200
    data = response.json()
    assert "comparison_matrix" in data
    assert len(data["comparison_matrix"]) >= 4
    assert "scale_limitations" in data
    assert "disclaimer" in data
    assert "Navier-Stokes" in str(data["comparison_matrix"])
    assert "Shallow Water" in str(data["comparison_matrix"])


def test_comparison_unavailable_for_invalid_runs():
    payload = {
        "delft3d_run_id": "non_existent_delft3d",
        "sph_run_id": "non_existent_sph",
        "reproject_crs": "EPSG:4326"
    }
    response = client.post("/api/comparison/compare", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "comparison_unavailable"
    assert len(data["blockers"]) > 0
    assert data["valid_overlap_cells"] == 0


def test_comparison_with_synthesized_compatible_runs(tmp_path, monkeypatch):
    """
    Synthesize mock Delft3D and PySPH runs with real GeoTIFF rasters and verified unit manifests
    to test the full spatial reprojection, IoU, CSI, and MAE/RMSE calculations.
    """
    monkeypatch.setenv("SIH_RUNTIME_DIR", str(tmp_path))

    # Setup directories
    d_run_id = "test_delft_run_01"
    s_run_id = "test_sph_run_01"

    d_dir = tmp_path / "runs" / d_run_id
    s_dir = tmp_path / "sph_runs" / s_run_id
    d_dir.mkdir(parents=True, exist_ok=True)
    s_dir.mkdir(parents=True, exist_ok=True)

    # Manifests
    d_manifest = {
        "run_id": d_run_id,
        "scenario_id": "sc_test",
        "scenario_name": "Test Delft Scenario",
        "status": "completed",
        "units_verified": True,
        "units": {"depth": "meters", "velocity": "m/s"},
    }
    s_manifest = {
        "run_id": s_run_id,
        "scenario_id": "sc_test",
        "scenario_name": "Test SPH Scenario",
        "status": "completed",
        "units_verified": True,
        "units": {"depth": "meters", "velocity": "m/s"},
    }
    (d_dir / "run_manifest.json").write_text(json.dumps(d_manifest), encoding="utf-8")
    (s_dir / "run_manifest.json").write_text(json.dumps(s_manifest), encoding="utf-8")

    # Create synthetic GeoTIFFs (50x50 cells around 74.65 Lon, 16.20 Lat)
    transform = from_origin(74.65, 16.25, 0.001, 0.001)
    
    # Delft array: 50x50 with flood depth ~2.0m in center
    arr_d_depth = np.zeros((50, 50), dtype=np.float32)
    arr_d_depth[10:40, 10:40] = 2.0

    # SPH array: 50x50 with flood depth ~2.2m slightly shifted
    arr_s_depth = np.zeros((50, 50), dtype=np.float32)
    arr_s_depth[15:45, 10:40] = 2.2

    # Write GeoTIFFs
    meta = {
        "driver": "GTiff",
        "height": 50,
        "width": 50,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": transform,
    }

    with rasterio.open(d_dir / "depth.tif", "w", **meta) as dst:
        dst.write(arr_d_depth, 1)

    with rasterio.open(s_dir / "depth.tif", "w", **meta) as dst:
        dst.write(arr_s_depth, 1)

    payload = {
        "delft3d_run_id": d_run_id,
        "sph_run_id": s_run_id,
        "reproject_crs": "EPSG:4326"
    }
    res = client.post("/api/comparison/compare", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "completed"
    assert data["valid_overlap_cells"] > 0
    assert data["extent_iou"] > 0.0
    assert data["critical_success_index"] > 0.0
    assert data["depth_stats"] is not None
    assert data["depth_stats"]["mae"] > 0.0
    assert len(data["blockers"]) == 0


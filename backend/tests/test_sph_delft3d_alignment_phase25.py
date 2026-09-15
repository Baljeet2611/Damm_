import io
import json
import shutil
import tempfile
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from fastapi.testclient import TestClient

from app.main import app
from app.simulation_service import (
    detect_capabilities as detect_delft3d_capabilities,
    build_dam_project_delft3d_package,
    import_dam_project_delft3d_run,
    list_dam_project_delft3d_runs,
)
from app.sph_service import (
    detect_sph_capabilities,
    build_dam_project_sph_package,
    rasterize_sph_particles,
    import_dam_project_sph_run,
    list_dam_project_sph_runs,
)
from app.schemas import (
    SPHParticleInterpolationParams,
    SPHRunImportRequest,
    Delft3DRunImportRequest,
    ModelComparisonRunRequest,
)
from app.model_comparison_service import (
    get_project_engine_capabilities,
    compute_model_comparison,
    normalize_engine_output,
)
import uuid
from app.onboarding_service import get_dam_projects_dir


@pytest.fixture
def test_project_id():
    """Create isolated test dam project on disk for testing with valid UUID v4."""
    pid = str(uuid.uuid4())
    p_dir = get_dam_projects_dir() / pid
    p_dir.mkdir(parents=True, exist_ok=True)
    proj_json = p_dir / "project.json"
    proj_json.write_text(json.dumps({
        "id": pid,
        "name": "Phase 25 Test Dam",
        "dam_height_m": 60.0,
        "crest_length_m": 250.0,
        "normal_reservoir_level_m": 650.0,
        "tailwater_level_m": 600.0,
    }), encoding="utf-8")

    yield pid

    if p_dir.is_dir():
        shutil.rmtree(p_dir, ignore_errors=True)


def create_test_geotiff(
    path: Path,
    array: np.ndarray,
    bounds: tuple = (500000.0, 1800000.0, 501000.0, 1801000.0),
    crs_str: str = "EPSG:32643",
    nodata: float = -9999.0,
):
    """Helper to write a valid test GeoTIFF file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    height, width = array.shape
    transform = from_bounds(*bounds, width, height)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=rasterio.float32,
        crs=CRS.from_string(crs_str),
        transform=transform,
        nodata=nodata,
        compress="deflate",
    ) as dst:
        dst.write(array.astype(np.float32), 1)


# 1. Delft3D executable detection
def test_delft3d_capability_detection():
    caps = detect_delft3d_capabilities()
    assert hasattr(caps, "dflowfm_available")
    assert hasattr(caps, "hydromt_available")
    assert hasattr(caps, "execution_enabled")
    assert isinstance(caps.disclaimer, str)
    assert len(caps.disclaimer) > 0


# 2. Unavailable Delft3D returns truthful state
def test_unavailable_delft3d_truthfulness(monkeypatch):
    monkeypatch.delenv("DFLOWFM_EXECUTABLE", raising=False)
    monkeypatch.delenv("DIMR_EXECUTABLE", raising=False)
    monkeypatch.setattr(shutil, "which", lambda x: None)

    caps = detect_delft3d_capabilities()
    assert caps.dflowfm_available is False
    assert caps.engine_executable is None


# 3. Delft3D package building for dam project
def test_delft3d_package_building(test_project_id):
    resp, zip_path = build_dam_project_delft3d_package(test_project_id)
    assert resp.project_id == test_project_id
    assert zip_path.is_file()
    assert resp.package_size_bytes > 0
    assert "dflowfm_available" in resp.model_dump()


# 4. Delft3D external result import validation
def test_delft3d_import_valid_geotiff(test_project_id):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        depth_arr = np.array([[2.5, 3.0], [1.8, 0.0]], dtype=np.float32)
        vel_arr = np.array([[1.5, 2.0], [1.1, 0.0]], dtype=np.float32)
        arr_arr = np.array([[100.0, 150.0], [200.0, 300.0]], dtype=np.float32)

        create_test_geotiff(tmp_p / "maximum_depth.tif", depth_arr)
        create_test_geotiff(tmp_p / "maximum_velocity.tif", vel_arr)
        create_test_geotiff(tmp_p / "arrival_time.tif", arr_arr)

        files = [
            ("maximum_depth.tif", (tmp_p / "maximum_depth.tif").read_bytes()),
            ("maximum_velocity.tif", (tmp_p / "maximum_velocity.tif").read_bytes()),
            ("arrival_time.tif", (tmp_p / "arrival_time.tif").read_bytes()),
        ]

        req = Delft3DRunImportRequest(run_label="Valid External D3D Run")
        res = import_dam_project_delft3d_run(test_project_id, files, req)

        assert res["status"] == "completed"
        assert res["solver_execution_status"] == "imported"
        assert res["scientific_status"] == "imported_external_run"
        assert res["layers"]["has_maximum_depth"] is True
        assert res["layers"]["has_maximum_velocity"] is True
        assert res["layers"]["has_arrival_time"] is True
        assert "maximum_depth" in res["layer_hashes"]


# 5. Invalid Delft3D result rejected
def test_delft3d_import_invalid_result_rejected(test_project_id):
    invalid_files = [
        ("unrelated_notes.txt", b"just a text file"),
    ]
    req = Delft3DRunImportRequest(run_label="Invalid Run")
    with pytest.raises(Exception):
        import_dam_project_delft3d_run(test_project_id, invalid_files, req)


# 6. SPH capability detection
def test_sph_capability_detection():
    caps = detect_sph_capabilities()
    assert hasattr(caps, "pysph_available")
    assert hasattr(caps, "execution_enabled")
    assert isinstance(caps.disclaimer, str)


# 7. SPH package building for dam project
def test_sph_package_building(test_project_id):
    resp, zip_path = build_dam_project_sph_package(test_project_id)
    assert resp.project_id == test_project_id
    assert zip_path.is_file()
    assert resp.package_size_bytes > 0


# 8. SPH particle-to-raster postprocessing
def test_sph_particle_to_raster_postprocessing():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        # Synthetic particles around (500500, 1800500)
        np.random.seed(42)
        n_p = 50
        px = 500200.0 + np.random.rand(n_p) * 600.0
        py = 1800200.0 + np.random.rand(n_p) * 600.0
        p_depth = 1.0 + np.random.rand(n_p) * 3.0
        p_vel = 0.5 + np.random.rand(n_p) * 2.0
        p_arr = np.random.rand(n_p) * 500.0

        particles = {
            "x": px,
            "y": py,
            "depth": p_depth,
            "velocity": p_vel,
            "arrival_time": p_arr,
        }

        bounds = (500000.0, 1800000.0, 501000.0, 1801000.0)
        params = SPHParticleInterpolationParams(target_resolution_m=20.0)

        created = rasterize_sph_particles(
            particles=particles,
            bounds=bounds,
            resolution_m=20.0,
            crs_str="EPSG:32643",
            out_dir=tmp_dir,
            params=params,
        )

        assert "maximum_depth" in created
        assert "maximum_velocity" in created
        assert "arrival_time" in created

        with rasterio.open(created["maximum_depth"]) as src:
            assert src.crs == CRS.from_epsg(32643)
            data = src.read(1)
            assert np.any(data > 0)


# 9. SPH particle import validation (.npz)
def test_sph_import_valid_npz(test_project_id):
    with tempfile.TemporaryDirectory() as tmp:
        npz_file = Path(tmp) / "sph_particles.npz"
        np.savez(
            npz_file,
            x=np.array([500200.0, 500400.0, 500600.0]),
            y=np.array([1800200.0, 1800400.0, 1800600.0]),
            depth=np.array([2.0, 3.5, 1.2]),
            velocity=np.array([1.0, 2.5, 0.8]),
            arrival_time=np.array([60.0, 120.0, 180.0]),
        )

        files = [
            ("sph_particles.npz", npz_file.read_bytes()),
        ]

        req = SPHRunImportRequest(run_label="Valid External SPH Run")
        res = import_dam_project_sph_run(test_project_id, files, req)

        assert res["status"] == "completed"
        assert res["solver_execution_status"] == "imported"
        assert res["scientific_status"] == "imported_external_run"
        assert res["layers"]["has_maximum_depth"] is True
        assert res["layers"]["has_maximum_velocity"] is True
        assert res["layers"]["has_arrival_time"] is True


# 10. Path traversal rejection in imports
def test_import_path_traversal_rejection(test_project_id):
    files = [
        ("../../../evil.exe", b"malicious executable"),
    ]
    req = SPHRunImportRequest(run_label="Evil Run")
    with pytest.raises(Exception):
        import_dam_project_sph_run(test_project_id, files, req)


# 11. Multi-engine capabilities reporting
def test_project_capabilities_matrix(test_project_id):
    caps = get_project_engine_capabilities(test_project_id)
    assert caps.project_id == test_project_id
    assert "pysph" in caps.engines
    assert "delft3d_fm" in caps.engines
    assert "anuga" in caps.engines
    assert isinstance(caps.completed_runs_by_engine, dict)


# 12. Comparison on isolated synthetic test fixtures
def test_sph_vs_delft3d_synthetic_fixture_comparison(test_project_id):
    req = ModelComparisonRunRequest(
        engine_a="pysph",
        run_id_a="sph-fixture-1",
        engine_b="delft3d_fm",
        run_id_b="d3d-fixture-1",
        depth_inundation_threshold_m=0.10,
        tolerance_bands_m=[0.10, 0.25, 0.50],
        synthetic_test_fixture=True,
    )
    res = compute_model_comparison(test_project_id, req)

    assert res.status == "completed"
    assert res.engine_a == "pysph"
    assert res.engine_b == "delft3d_fm"
    assert res.depth_difference.mae_m >= 0.0
    assert res.depth_difference.rmse_m >= 0.0
    assert 0.0 <= res.inundation_agreement.spatial_agreement_iou <= 1.0
    assert res.velocity_difference.available is True
    assert res.arrival_time_difference.available is True


# 13. Comparison on real imported SPH vs Delft3D runs
def test_sph_vs_delft3d_real_imported_comparison(test_project_id):
    # 1. Import SPH run
    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        depth_arr_sph = np.array([[2.0, 3.0], [1.5, 0.0]], dtype=np.float32)
        vel_arr_sph = np.array([[1.0, 1.8], [0.8, 0.0]], dtype=np.float32)
        create_test_geotiff(tmp_p / "sph_depth.tif", depth_arr_sph)
        create_test_geotiff(tmp_p / "sph_vel.tif", vel_arr_sph)

        res_sph = import_dam_project_sph_run(
            test_project_id,
            [
                ("maximum_depth.tif", (tmp_p / "sph_depth.tif").read_bytes()),
                ("maximum_velocity.tif", (tmp_p / "sph_vel.tif").read_bytes()),
            ],
            SPHRunImportRequest(run_label="SPH Run for Comparison"),
        )
        sph_run_id = res_sph["run_id"]

        # 2. Import Delft3D run
        depth_arr_d3d = np.array([[2.2, 2.9], [1.4, 0.0]], dtype=np.float32)
        vel_arr_d3d = np.array([[1.1, 1.7], [0.9, 0.0]], dtype=np.float32)
        create_test_geotiff(tmp_p / "d3d_depth.tif", depth_arr_d3d)
        create_test_geotiff(tmp_p / "d3d_vel.tif", vel_arr_d3d)

        res_d3d = import_dam_project_delft3d_run(
            test_project_id,
            [
                ("maximum_depth.tif", (tmp_p / "d3d_depth.tif").read_bytes()),
                ("maximum_velocity.tif", (tmp_p / "d3d_vel.tif").read_bytes()),
            ],
            Delft3DRunImportRequest(run_label="Delft3D Run for Comparison"),
        )
        d3d_run_id = res_d3d["run_id"]

    # 3. Perform pairwise comparison SPH vs Delft3D
    req = ModelComparisonRunRequest(
        engine_a="pysph",
        run_id_a=sph_run_id,
        engine_b="delft3d_fm",
        run_id_b=d3d_run_id,
        depth_inundation_threshold_m=0.10,
        tolerance_bands_m=[0.10, 0.25, 0.50],
        synthetic_test_fixture=False,
    )
    res_comp = compute_model_comparison(test_project_id, req)

    assert res_comp.status == "completed"
    assert res_comp.engine_a == "pysph"
    assert res_comp.engine_b == "delft3d_fm"
    assert res_comp.contract_a.solver_execution_status == "imported"
    assert res_comp.contract_b.solver_execution_status == "imported"
    assert res_comp.depth_difference.common_valid_pixel_count > 0
    assert res_comp.inundation_agreement.spatial_agreement_iou > 0.0
    assert res_comp.velocity_difference.available is True


# 14. Missing velocity output handled honestly
def test_missing_velocity_handled_honestly(test_project_id):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        depth_arr = np.array([[2.0, 3.0], [1.5, 0.0]], dtype=np.float32)
        create_test_geotiff(tmp_p / "depth_only.tif", depth_arr)

        res_sph = import_dam_project_sph_run(
            test_project_id,
            [("maximum_depth.tif", (tmp_p / "depth_only.tif").read_bytes())],
            SPHRunImportRequest(run_label="Depth Only SPH"),
        )
        res_d3d = import_dam_project_delft3d_run(
            test_project_id,
            [("maximum_depth.tif", (tmp_p / "depth_only.tif").read_bytes())],
            Delft3DRunImportRequest(run_label="Depth Only D3D"),
        )

    req = ModelComparisonRunRequest(
        engine_a="pysph",
        run_id_a=res_sph["run_id"],
        engine_b="delft3d_fm",
        run_id_b=res_d3d["run_id"],
        synthetic_test_fixture=False,
    )
    res_comp = compute_model_comparison(test_project_id, req)
    assert res_comp.velocity_difference.available is False
    assert "Velocity comparison unavailable" in (res_comp.velocity_difference.reason_if_unavailable or "")


# 15. FastAPI endpoint integration
def test_fastapi_sph_and_delft3d_endpoints(test_project_id):
    client = TestClient(app)

    # 1. Capabilities
    r_cap = client.get(f"/api/dam-projects/{test_project_id}/model-comparison/capabilities")
    assert r_cap.status_code == 200
    assert "pysph" in r_cap.json()["engines"]

    # 2. Build SPH Package
    r_pkg = client.post(f"/api/dam-projects/{test_project_id}/sph/build-package")
    assert r_pkg.status_code == 200
    assert r_pkg.json()["package_filename"].endswith(".zip")

    # 3. Build Delft3D Package
    r_pkg_d3d = client.post(f"/api/dam-projects/{test_project_id}/delft3d/build-package")
    assert r_pkg_d3d.status_code == 200
    assert r_pkg_d3d.json()["package_filename"].endswith(".zip")

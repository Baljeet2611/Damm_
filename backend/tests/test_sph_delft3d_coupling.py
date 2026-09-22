"""
test_sph_delft3d_coupling.py - Comprehensive automated tests for PySPH to Delft3D-FM breach hydrograph coupling.

Validates Phase A1 Requirements:
1. Hydrograph extraction from real/valid SPH terrain simulation output.
2. Hydrograph validation: monotonic timestamps, finite discharge values, non-negative flow.
3. Accurate summary metrics: Q_peak, time_to_peak, trapezoidal integrated volume.
4. Robust rejection and error handling for invalid/missing SPH simulation runs.
5. Standardized Delft3D D-Flow FM boundary condition (.bc) generation with expected headers and units.
6. Number of entries and timing alignment in generated .bc file.
7. Uncoupled standalone Delft3D package generation backwards compatibility.
8. Coupled PySPH -> Delft3D package generation referencing breach_inflow.bc in boundary_conditions.ext.
9. Manifest coupling metadata and provenance recording.
10. FastAPI endpoints for hydrograph retrieval and coupled Delft3D package generation.
"""

import json
import uuid
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from fastapi.testclient import TestClient
from pathlib import Path

from app.main import app
from app.onboarding_service import get_dam_projects_dir, save_dam_project
from app.sph_service import (
    execute_dam_project_sph_terrain_simulation,
    extract_sph_breach_hydrograph,
    export_sph_breach_hydrograph_bc,
    get_dam_project_sph_dir,
)
from app.simulation_service import (
    build_dam_project_delft3d_package,
    get_dam_project_delft3d_dir,
)
from app.schemas import BreachHydrographResponse, HydrographPoint

client = TestClient(app)


@pytest.fixture
def sph_coupling_test_project():
    """Create a temporary test dam project with synthetic DEM and valid engineering parameters."""
    proj_id = str(uuid.uuid4())
    p_dir = get_dam_projects_dir() / proj_id
    p_dir.mkdir(parents=True, exist_ok=True)

    # 40 x 40 DEM grid
    elev_grid = np.zeros((40, 40), dtype=np.float32)
    for r in range(40):
        for c in range(40):
            elev_grid[r, c] = 600.0 + (abs(c - 20) * 2.0) + (40 - r) * 1.5

    dem_path = p_dir / "dem.tif"
    transform = from_origin(74.60, 16.20, 0.002, 0.002)
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        height=40,
        width=40,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(elev_grid, 1)

    project_meta = {
        "project_id": proj_id,
        "dam_name": "SPH-Delft3D Coupling Test Dam",
        "latitude": 16.14,
        "longitude": 74.64,
        "dam_height_m": 60.0,
        "crest_length_m": 250.0,
        "normal_reservoir_level_m": 650.0,
        "tailwater_level_m": 600.0,
        "dem_file": "dem.tif",
        "dem_crs": "EPSG:4326",
        "dem_resolution_m": 30.0,
        "created_at": "2026-09-16T00:00:00Z",
    }
    (p_dir / "project.json").write_text(json.dumps(project_meta, indent=2), encoding="utf-8")

    yield proj_id

    # Cleanup
    import shutil
    if p_dir.is_dir():
        shutil.rmtree(p_dir, ignore_errors=True)


def test_sph_hydrograph_extraction_and_metrics(sph_coupling_test_project):
    """Test executing a small SPH run and extracting a valid breach hydrograph."""
    proj_id = sph_coupling_test_project

    # Execute a small 20-step SPH terrain simulation
    run_result = execute_dam_project_sph_terrain_simulation(
        proj_id,
        options={
            "run_label": "Coupling Test SPH Run",
            "notes": "Testing hydrograph extraction",
            "num_particles": 60,
            "timesteps": 25,
            "dt": 0.4,
            "save_interval": 5,
        },
    )

    run_id = run_result["run_id"]
    assert run_result["status"] == "completed"
    assert "hydrograph_summary" in run_result

    # Extract hydrograph using service function
    hydrograph = extract_sph_breach_hydrograph(proj_id, run_id)
    assert isinstance(hydrograph, BreachHydrographResponse)
    assert hydrograph.source_engine == "pysph"
    assert hydrograph.run_id == run_id
    assert hydrograph.project_id == proj_id

    # 1. Monotonic timestamps check
    times = [pt.time_seconds for pt in hydrograph.points]
    assert len(times) >= 2
    assert np.all(np.diff(times) > 0), "Timestamps must be strictly monotonically increasing"
    assert times[0] == 0.0

    # 2. Finite non-negative discharge check
    q_vals = [pt.discharge_cms for pt in hydrograph.points]
    assert all(np.isfinite(q) for q in q_vals), "All discharge values must be finite numbers"
    assert all(q >= 0.0 for q in q_vals), "Discharge values must be non-negative"

    # 3. Peak discharge and time-to-peak validation
    expected_q_peak = float(max(q_vals))
    assert hydrograph.q_peak_cms == pytest.approx(expected_q_peak, rel=1e-5)
    expected_t_peak = times[q_vals.index(expected_q_peak)]
    assert hydrograph.time_to_peak_seconds == pytest.approx(expected_t_peak, rel=1e-5)

    # 4. Integrated volume calculation check (trapezoidal rule)
    from app.sph_service import _integrate_trapezoid
    expected_vol = _integrate_trapezoid(np.array(q_vals), np.array(times))
    assert hydrograph.total_released_volume_m3 == pytest.approx(expected_vol, rel=1e-4)
    assert hydrograph.duration_seconds == pytest.approx(times[-1] - times[0], rel=1e-5)

    # 5. Scientific terminology and mass balance check
    assert hydrograph.reservoir_release_fraction is not None
    assert 0.0 <= hydrograph.reservoir_release_fraction <= 1.0
    assert hydrograph.mass_balance_check in ["verified", "evaluated", "not_available"]


def test_export_sph_breach_hydrograph_bc(sph_coupling_test_project, tmp_path):
    """Test formatting and export of Delft3D .bc file."""
    points = [
        HydrographPoint(time_seconds=0.0, discharge_cms=0.0),
        HydrographPoint(time_seconds=60.0, discharge_cms=125.5),
        HydrographPoint(time_seconds=120.0, discharge_cms=350.0),
        HydrographPoint(time_seconds=180.0, discharge_cms=210.0),
        HydrographPoint(time_seconds=240.0, discharge_cms=45.0),
        HydrographPoint(time_seconds=300.0, discharge_cms=0.0),
    ]
    hydrograph = BreachHydrographResponse(
        source_engine="pysph",
        run_id="test_run_001",
        project_id=sph_coupling_test_project,
        created_at="2026-09-21T00:00:00Z",
        time_unit="s",
        discharge_unit="m3/s",
        points=points,
        q_peak_cms=350.0,
        time_to_peak_seconds=120.0,
        total_released_volume_m3=45000.0,
        duration_seconds=300.0,
        point_count=6,
    )

    bc_out_file = tmp_path / "breach_inflow.bc"
    exported_path = export_sph_breach_hydrograph_bc(hydrograph, bc_out_file)

    assert exported_path.is_file()
    content = exported_path.read_text(encoding="utf-8")

    # Verify Delft3D FM .bc format requirements
    assert "[forcing]" in content
    assert "Name                            = Inflow_Breach" in content
    assert "Function                        = time-series" in content
    assert "Time-interpolation              = linear" in content
    assert "Quantity                        = time" in content
    assert "Quantity                        = dischargebnd" in content
    assert "Unit                            = m3/s" in content

    # Verify time-series numbers
    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("[") and "=" not in line and not line.startswith("#")]
    assert len(lines) == 6
    # Check first line is 0.000  0.000
    first_parts = [float(x) for x in lines[0].split()]
    assert first_parts == [0.0, 0.0]
    # Check peak line is 120.000  350.000
    peak_parts = [float(x) for x in lines[2].split()]
    assert peak_parts == [120.0, 350.0]


def test_invalid_sph_run_rejection(sph_coupling_test_project):
    """Test that extract_sph_breach_hydrograph cleanly rejects invalid run IDs."""
    proj_id = sph_coupling_test_project
    with pytest.raises(Exception):
        extract_sph_breach_hydrograph(proj_id, "non_existent_run_99999")


def test_uncoupled_standalone_delft3d_package(sph_coupling_test_project):
    """Test that existing standalone Delft3D package generation functions without regression."""
    proj_id = sph_coupling_test_project
    resp, zip_path = build_dam_project_delft3d_package(proj_id)

    assert resp.project_id == proj_id
    assert resp.package_filename.endswith(".zip")
    assert zip_path.is_file()

    delft_dir = get_dam_project_delft3d_dir(proj_id)
    pkg_work_dir = delft_dir / "packages" / f"{proj_id}_delft3d_package"
    manifest = json.loads((pkg_work_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["coupling"] is None


def test_coupled_sph_delft3d_package_generation(sph_coupling_test_project):
    """Test coupled PySPH -> Delft3D package generation and boundary condition linkage."""
    proj_id = sph_coupling_test_project

    # 1. Run SPH
    sph_run = execute_dam_project_sph_terrain_simulation(
        proj_id,
        options={
            "num_particles": 50,
            "timesteps": 20,
            "dt": 0.5,
            "save_interval": 5,
        },
    )
    sph_run_id = sph_run["run_id"]

    # 2. Build coupled Delft3D package
    resp, zip_path = build_dam_project_delft3d_package(proj_id, sph_run_id=sph_run_id)

    assert resp.project_id == proj_id
    assert resp.package_filename.endswith(".zip")
    assert zip_path.is_file()

    delft_dir = get_dam_project_delft3d_dir(proj_id)
    pkg_work_dir = delft_dir / "packages" / f"{proj_id}_delft3d_sph_coupled_package"
    bc_file = pkg_work_dir / "boundaries" / "breach_inflow.bc"
    assert bc_file.is_file(), "breach_inflow.bc must be generated in boundaries dir"

    # Check boundary_conditions.ext references breach_inflow.bc
    ext_content = (pkg_work_dir / "boundaries" / "boundary_conditions.ext").read_text(encoding="utf-8")
    assert "QUANTITY=dischargebnd" in ext_content
    assert "FILENAME=breach_inflow.bc" in ext_content
    assert "FILETYPE=9" in ext_content

    # Check manifest.json records provenance
    manifest = json.loads((pkg_work_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["coupling"]["is_coupled"] is True
    assert manifest["coupling"]["source_sph_run_id"] == sph_run_id
    assert manifest["coupling"]["source_engine"] == "pysph"
    assert manifest["coupling"]["sph_q_peak_cms"] >= 0.0


def test_api_endpoints_sph_hydrograph_and_delft3d_coupling(sph_coupling_test_project):
    """Test FastAPI HTTP endpoints for SPH hydrograph retrieval and coupled package generation."""
    proj_id = sph_coupling_test_project

    # Run SPH via API
    run_resp = client.post(
        f"/api/dam-projects/{proj_id}/sph/run",
        json={"num_particles": 50, "timesteps": 20, "dt": 0.5, "save_interval": 5},
    )
    assert run_resp.status_code == 200
    run_id = run_resp.json()["run_id"]

    # Get hydrograph via API
    hydro_resp = client.get(f"/api/dam-projects/{proj_id}/sph/runs/{run_id}/hydrograph")
    assert hydro_resp.status_code == 200
    hydro_data = hydro_resp.json()
    assert hydro_data["source_engine"] == "pysph"
    assert hydro_data["run_id"] == run_id
    assert hydro_data["q_peak_cms"] >= 0.0
    assert len(hydro_data["points"]) > 0

    # Build coupled Delft3D package via API
    pkg_resp = client.post(
        f"/api/dam-projects/{proj_id}/delft3d/build-package?sph_run_id={run_id}"
    )
    assert pkg_resp.status_code == 200
    pkg_data = pkg_resp.json()
    assert pkg_data["project_id"] == proj_id
    assert pkg_data["package_filename"].endswith(".zip")
    assert pkg_data["package_size_bytes"] > 0

"""Phase B1: Delft3D Flexible Mesh UGRID NetCDF Output Ingestion Tests.

Verifies:
1. Valid UGRID NetCDF file validation & topology inspection
2. Mesh node coordinates (x, y) extraction
3. Timestamps and duration extraction
4. Direct depth extraction and computed water_level - bed_level extraction
5. Direct velocity magnitude and component vector magnitude extraction
6. Rasterization to standard North-up GeoTIFFs (maximum_depth.tif, maximum_velocity.tif)
7. Invalid/empty file rejection
8. Project-level ingestion with delft3d_fm provenance
9. REST API endpoints for parsing and importing NetCDF map files
"""

import io
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Generator

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from scipy.io import netcdf_file

from app.main import app
from app.delft3d_ugrid_service import (
    validate_delft3d_ugrid_file,
    parse_delft3d_ugrid_netcdf,
    rasterize_delft3d_ugrid_to_geotiff,
    ingest_delft3d_netcdf_run,
)
from app.onboarding_service import (
    get_dam_projects_dir,
)
from app.schemas import Delft3DRunImportRequest


@pytest.fixture
def test_client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def test_project_id() -> Generator[str, None, None]:
    """Create isolated test dam project on disk for testing with valid UUID v4."""
    pid = str(uuid.uuid4())
    p_dir = get_dam_projects_dir() / pid
    p_dir.mkdir(parents=True, exist_ok=True)
    proj_json = p_dir / "project.json"
    proj_json.write_text(json.dumps({
        "id": pid,
        "name": "Phase B1 Test Dam",
        "dam_height_m": 60.0,
        "crest_length_m": 250.0,
        "normal_reservoir_level_m": 650.0,
        "tailwater_level_m": 600.0,
    }), encoding="utf-8")

    yield pid

    if p_dir.is_dir():
        shutil.rmtree(p_dir, ignore_errors=True)


def create_mock_ugrid_netcdf(
    filepath: Path,
    n_nodes: int = 9,
    n_times: int = 4,
    use_vector_vel: bool = False,
    use_water_level_calc: bool = False,
) -> Path:
    """Helper to generate a deterministic Delft3D-FM UGRID NetCDF map fixture."""
    f = netcdf_file(str(filepath), "w")
    f.history = "Delft3D-FM D-Flow FM UGRID 2D Map Output"
    f.Conventions = "CF-1.8 UGRID-1.0"
    f.title = "Ghataprabha Regional Dam-Break Simulation"

    f.createDimension("mesh2d_nNodes", n_nodes)
    f.createDimension("time", n_times)

    # 3x3 grid coordinates in UTM 43N
    gx = np.array([500000.0, 501000.0, 502000.0, 500000.0, 501000.0, 502000.0, 500000.0, 501000.0, 502000.0])
    gy = np.array([1700000.0, 1700000.0, 1700000.0, 1701000.0, 1701000.0, 1701000.0, 1702000.0, 1702000.0, 1702000.0])

    vx = f.createVariable("mesh2d_node_x", "d", ("mesh2d_nNodes",))
    vx[:] = gx
    vy = f.createVariable("mesh2d_node_y", "d", ("mesh2d_nNodes",))
    vy[:] = gy

    # Timestamps in seconds (0s, 600s, 1200s, 1800s)
    times = np.array([0.0, 600.0, 1200.0, 1800.0])
    vt = f.createVariable("time", "d", ("time",))
    vt[:] = times

    if use_water_level_calc:
        # Water level and bed level
        vwl = f.createVariable("mesh2d_s1", "f", ("time", "mesh2d_nNodes"))
        vbl = f.createVariable("mesh2d_flowelem_bl", "f", ("mesh2d_nNodes",))
        vbl[:] = np.array([600.0, 601.0, 602.0, 600.5, 601.5, 602.5, 601.0, 602.0, 603.0])
        # Water level rises above bed level
        wl_matrix = np.zeros((n_times, n_nodes), dtype=np.float32)
        for t_idx in range(n_times):
            wl_matrix[t_idx, :] = vbl[:] + (t_idx * 1.2)
        vwl[:] = wl_matrix
    else:
        # Direct water depth
        vd = f.createVariable("mesh2d_waterdepth", "f", ("time", "mesh2d_nNodes"))
        depth_matrix = np.zeros((n_times, n_nodes), dtype=np.float32)
        depth_matrix[0, :] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        depth_matrix[1, :] = [1.2, 0.8, 0.0, 1.5, 0.9, 0.0, 0.5, 0.0, 0.0]
        depth_matrix[2, :] = [2.8, 2.1, 1.1, 3.4, 2.5, 1.0, 1.8, 0.9, 0.0]
        depth_matrix[3, :] = [3.5, 3.0, 1.8, 4.2, 3.6, 1.9, 2.5, 1.7, 0.8]
        vd[:] = depth_matrix

    if use_vector_vel:
        # Vector components ucx and ucy
        vux = f.createVariable("mesh2d_ucx", "f", ("time", "mesh2d_nNodes"))
        vuy = f.createVariable("mesh2d_ucy", "f", ("time", "mesh2d_nNodes"))
        ux_mat = np.ones((n_times, n_nodes), dtype=np.float32) * 1.5
        uy_mat = np.ones((n_times, n_nodes), dtype=np.float32) * 2.0
        vux[:] = ux_mat
        vuy[:] = uy_mat
    else:
        # Direct velocity magnitude
        vu = f.createVariable("mesh2d_ucmag", "f", ("time", "mesh2d_nNodes"))
        vel_matrix = np.zeros((n_times, n_nodes), dtype=np.float32)
        vel_matrix[0, :] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        vel_matrix[1, :] = [0.9, 0.6, 0.0, 1.1, 0.7, 0.0, 0.4, 0.0, 0.0]
        vel_matrix[2, :] = [1.8, 1.4, 0.7, 2.3, 1.6, 0.8, 1.2, 0.6, 0.0]
        vel_matrix[3, :] = [2.2, 1.9, 1.2, 2.9, 2.4, 1.3, 1.7, 1.1, 0.5]
        vu[:] = vel_matrix

    f.close()
    return filepath


def test_01_delft3d_ugrid_validation(tmp_path: Path):
    """Test validation of genuine vs corrupt vs empty NetCDF files."""
    valid_nc = create_mock_ugrid_netcdf(tmp_path / "valid_ugrid.nc")
    is_valid, msg, meta = validate_delft3d_ugrid_file(valid_nc)
    assert is_valid is True
    assert "mesh2d_node_x" in meta["x_variable"]
    assert "mesh2d_waterdepth" in meta["depth_variable"]
    assert meta["dimensions"]["mesh2d_nNodes"] == 9
    assert meta["dimensions"]["time"] == 4

    # Empty file
    empty_file = tmp_path / "empty.nc"
    empty_file.write_bytes(b"")
    is_v, msg_e, _ = validate_delft3d_ugrid_file(empty_file)
    assert is_v is False
    assert "empty" in msg_e.lower()

    # Corrupt file
    corrupt_file = tmp_path / "corrupt.nc"
    corrupt_file.write_bytes(b"NOT_A_NETCDF_HEADER_DATA")
    is_c, msg_c, _ = validate_delft3d_ugrid_file(corrupt_file)
    assert is_c is False


def test_02_parse_direct_depth_and_velocity(tmp_path: Path):
    """Test extraction of direct depth and velocity magnitude."""
    nc_path = create_mock_ugrid_netcdf(tmp_path / "direct_ugrid.nc")
    parsed = parse_delft3d_ugrid_netcdf(nc_path)

    assert parsed["engine"] == "delft3d_fm"
    assert parsed["num_nodes"] == 9
    assert parsed["num_timesteps"] == 4
    assert parsed["timestamps"] == [0.0, 600.0, 1200.0, 1800.0]
    assert parsed["simulation_duration_s"] == 1800.0
    assert parsed["depth_extracted"] is True
    assert parsed["velocity_extracted"] is True
    assert parsed["crs"] == "EPSG:32643"

    # Max depth across timesteps at node 3 is 4.2
    assert parsed["summary"]["max_depth_m"] == pytest.approx(4.2, 0.01)
    # Max velocity at node 3 is 2.9
    assert parsed["summary"]["max_velocity_ms"] == pytest.approx(2.9, 0.01)
    assert parsed["summary"]["flooded_points_count"] == 9
    assert parsed["provenance"]["source_engine"] == "delft3d_fm"


def test_03_parse_water_level_and_vector_velocity(tmp_path: Path):
    """Test computed depth (s1 - bed_level) and vector velocity (sqrt(ux^2 + uy^2))."""
    nc_path = create_mock_ugrid_netcdf(
        tmp_path / "vector_ugrid.nc",
        use_vector_vel=True,
        use_water_level_calc=True,
    )
    parsed = parse_delft3d_ugrid_netcdf(nc_path)

    assert parsed["depth_extracted"] is True
    assert parsed["velocity_extracted"] is True
    # At t=3 (index 3), water_level - bed_level = 3 * 1.2 = 3.6
    assert parsed["summary"]["max_depth_m"] == pytest.approx(3.6, 0.01)
    # Vector velocity: sqrt(1.5^2 + 2.0^2) = 2.5
    assert parsed["summary"]["max_velocity_ms"] == pytest.approx(2.5, 0.01)


def test_04_rasterize_delft3d_to_geotiff(tmp_path: Path):
    """Test conversion of parsed UGRID mesh to standard GeoTIFFs."""
    nc_path = create_mock_ugrid_netcdf(tmp_path / "raster_ugrid.nc")
    parsed = parse_delft3d_ugrid_netcdf(nc_path)

    out_dir = tmp_path / "geotiff_output"
    tifs = rasterize_delft3d_ugrid_to_geotiff(parsed, out_dir, resolution_m=50.0)

    assert "maximum_depth" in tifs
    assert "maximum_velocity" in tifs
    depth_tif = tifs["maximum_depth"]
    vel_tif = tifs["maximum_velocity"]

    assert depth_tif.is_file()
    assert vel_tif.is_file()

    with rasterio.open(depth_tif) as src:
        assert src.crs == rasterio.crs.CRS.from_string("EPSG:32643")
        assert src.nodata == -9999.0
        data = src.read(1)
        valid_data = data[data != src.nodata]
        assert len(valid_data) > 0
        assert np.nanmax(valid_data) > 0.0

    with rasterio.open(vel_tif) as src:
        assert src.crs == rasterio.crs.CRS.from_string("EPSG:32643")
        assert src.nodata == -9999.0
        data = src.read(1)
        valid_data = data[data != src.nodata]
        assert len(valid_data) > 0
        assert np.nanmax(valid_data) > 0.0


def test_05_ingest_delft3d_netcdf_run_service(test_project_id: str, tmp_path: Path):
    """Test full project ingestion service with raw NetCDF file."""
    pid = test_project_id
    nc_path = create_mock_ugrid_netcdf(tmp_path / "DFM_OUTPUT_ghataprabha_map.nc")
    import_req = Delft3DRunImportRequest(
        run_label="Canary Delft3D FM UGRID Ingest",
        notes="Testing genuine UGRID ingestion",
    )
    record = ingest_delft3d_netcdf_run(pid, nc_path, import_req)

    assert record["engine"] == "delft3d_fm"
    assert record["status"] == "completed"
    assert record["provenance"]["source_engine"] == "delft3d_fm"
    assert record["provenance"]["import_mode"] == "ugrid_netcdf"
    assert record["layers"]["has_maximum_depth"] is True
    assert record["layers"]["has_maximum_velocity"] is True
    assert "summary" in record
    assert record["summary"]["max_depth_m"] > 0.0

    # Check files on disk
    run_dir = get_dam_projects_dir() / pid / "delft3d" / "runs" / record["run_id"]
    assert (run_dir / "maximum_depth.tif").is_file()
    assert (run_dir / "maximum_velocity.tif").is_file()
    assert (run_dir / "DFM_OUTPUT_ghataprabha_map.nc").is_file()
    assert (run_dir / "run.json").is_file()


def test_06_rest_api_parse_ugrid_endpoint(test_client: TestClient, test_project_id: str, tmp_path: Path):
    """Test POST /api/dam-projects/{project_id}/delft3d/parse-ugrid endpoint."""
    pid = test_project_id
    nc_path = create_mock_ugrid_netcdf(tmp_path / "api_parse_test.nc")
    with open(nc_path, "rb") as f:
        nc_bytes = f.read()

    response = test_client.post(
        f"/api/dam-projects/{pid}/delft3d/parse-ugrid",
        files={"file": ("api_parse_test.nc", nc_bytes, "application/x-netcdf")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["engine"] == "delft3d_fm"
    assert data["num_nodes"] == 9
    assert data["num_timesteps"] == 4
    assert data["summary"]["max_depth_m"] > 0.0
    assert data["provenance"]["source_engine"] == "delft3d_fm"


def test_07_rest_api_import_netcdf_run(test_client: TestClient, test_project_id: str, tmp_path: Path):
    """Test POST /api/dam-projects/{project_id}/delft3d/import-run with NetCDF file."""
    pid = test_project_id
    nc_path = create_mock_ugrid_netcdf(tmp_path / "d3d_map.nc")
    with open(nc_path, "rb") as f:
        nc_bytes = f.read()

    response = test_client.post(
        f"/api/dam-projects/{pid}/delft3d/import-run",
        files=[("files", ("d3d_map.nc", nc_bytes, "application/x-netcdf"))],
        data={"run_label": "REST Ingested Delft3D Run", "notes": "Automated NetCDF ingestion test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["engine"] == "delft3d_fm"
    assert data["status"] == "completed"
    assert data["layers"]["has_maximum_depth"] is True
    assert data["layers"]["has_maximum_velocity"] is True
    assert data["provenance"]["import_mode"] == "ugrid_netcdf"

    # List runs
    list_resp = test_client.get(f"/api/dam-projects/{pid}/delft3d/runs")
    assert list_resp.status_code == 200
    runs = list_resp.json()
    assert len(runs) >= 1
    assert runs[0]["run_id"] == data["run_id"]

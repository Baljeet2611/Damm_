import os
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds
from fastapi.testclient import TestClient

from app.main import app
from app.raster_service import (
    set_registered_datasets,
    reset_registered_datasets,
    clear_cache,
    DEFAULT_REGISTERED_DATASETS,
)

client = TestClient(app)


def create_tiny_raster(file_path: Path, data: np.ndarray, nodata: float = -9999.0, crs: str = "EPSG:4326"):
    height, width = data.shape
    # Bounds: lon from 74.0 to 75.0, lat from 16.0 to 17.0
    transform = from_bounds(74.0, 16.0, 75.0, 17.0, width, height)
    with rasterio.open(
        file_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=data.dtype,
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)


@pytest.fixture
def mock_rasters(tmp_path: Path):
    """
    Creates tiny 4x4 test rasters and configures the registry so tests run
    completely independently of data/raw.
    """
    data_dir = tmp_path / "mock_data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # 1. DEM raster (values 600.0 to 650.0, nodata at [0,0])
    dem_arr = np.array(
        [
            [-9999.0, 610.0, 620.0, 630.0],
            [615.0, 625.0, 635.0, 640.0],
            [620.0, 630.0, 640.0, 645.0],
            [625.0, 635.0, 645.0, 650.0],
        ],
        dtype=np.float32,
    )
    dem_file = data_dir / "mock_dem.tif"
    create_tiny_raster(dem_file, dem_arr, nodata=-9999.0)

    # 2. Depth raster (values 0.0 to 10.0)
    depth_arr = np.array(
        [
            [0.0, 1.5, 2.5, 3.0],
            [0.0, 4.0, 5.0, 6.0],
            [0.0, 0.0, 7.5, 8.0],
            [0.0, 0.0, 9.0, 10.0],
        ],
        dtype=np.float32,
    )
    depth_file = data_dir / "mock_depth.tif"
    create_tiny_raster(depth_file, depth_arr, nodata=-9999.0)

    # 3. Velocity raster (values 0.0 to 5.0)
    velocity_arr = np.array(
        [
            [0.0, 0.5, 1.2, 2.0],
            [0.0, 1.0, 2.5, 3.2],
            [0.0, 0.0, 3.0, 4.1],
            [0.0, 0.0, 2.0, 5.0],
        ],
        dtype=np.float32,
    )
    velocity_file = data_dir / "mock_velocity.tif"
    create_tiny_raster(velocity_file, velocity_arr, nodata=-9999.0)

    # 4. Arrival raster: contains normal valid values, +9999.0, -9999.0, and NaN
    arrival_arr = np.array(
        [
            [12.5, 25.0, 9999.0, 9999.0],
            [14.0, 30.5, 9999.0, -9999.0],
            [18.0, 35.0, np.nan, 9999.0],
            [22.0, 40.0, 9999.0, 9999.0],
        ],
        dtype=np.float32,
    )
    arrival_file = data_dir / "mock_arrival.tif"
    create_tiny_raster(arrival_file, arrival_arr, nodata=-9999.0)

    # Configure registered datasets with relative paths from tmp_path
    os.environ["SIH_PROJECT_ROOT"] = str(tmp_path)
    test_datasets = {
        "dem": {
            "label": "Test DEM",
            "relative_path": "mock_data/mock_dem.tif",
            "data_type": "elevation",
            "unit_status": "unverified (elevation unit and vertical datum unverified)",
            "provenance_status": "mock raster for testing",
        },
        "depth": {
            "label": "Test Depth",
            "relative_path": "mock_data/mock_depth.tif",
            "data_type": "depth",
            "unit_status": "unverified",
            "provenance_status": "mock raster for testing",
        },
        "velocity": {
            "label": "Test Velocity",
            "relative_path": "mock_data/mock_velocity.tif",
            "data_type": "velocity",
            "unit_status": "unverified",
            "provenance_status": "mock raster for testing",
        },
        "arrival": {
            "label": "Test Arrival",
            "relative_path": "mock_data/mock_arrival.tif",
            "data_type": "arrival_time",
            "unit_status": "unknown (unit unknown, header NoData -9999 vs data +9999)",
            "provenance_status": "mock raster for testing",
        },
    }
    set_registered_datasets(test_datasets)

    yield test_datasets

    # Teardown
    reset_registered_datasets()
    if "SIH_PROJECT_ROOT" in os.environ:
        del os.environ["SIH_PROJECT_ROOT"]


def test_get_datasets(mock_rasters):
    """GET /api/datasets should return all 4 datasets without leaking absolute paths."""
    response = client.get("/api/datasets")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 4

    ids = {d["id"] for d in data}
    assert ids == {"dem", "depth", "velocity", "arrival"}

    for d in data:
        assert "id" in d
        assert "label" in d
        assert "availability" in d
        assert d["availability"] is True
        assert "data_type" in d
        assert "unit_status" in d
        assert "provenance_status" in d
        # Security requirement: Never expose absolute filesystem paths
        for k, v in d.items():
            if isinstance(v, str):
                assert ":\\" not in v
                assert "/mock_data" not in v


def test_get_metadata_dem(mock_rasters):
    """GET /api/rasters/dem/metadata returns valid metadata and cached min/max."""
    response = client.get("/api/rasters/dem/metadata")
    assert response.status_code == 200
    meta = response.json()

    assert meta["id"] == "dem"
    assert meta["width"] == 4
    assert meta["height"] == 4
    assert meta["dtype"] == "float32"
    assert "4326" in meta["crs"]
    assert meta["bounds"] == {"left": 74.0, "bottom": 16.0, "right": 75.0, "top": 17.0}
    assert meta["resolution"]["x"] == pytest.approx(0.25)
    assert meta["resolution"]["y"] == pytest.approx(0.25)
    assert meta["nodata"] == -9999.0
    # Min excluding nodata
    assert meta["valid_min"] == pytest.approx(610.0)
    assert meta["valid_max"] == pytest.approx(650.0)


def test_get_metadata_arrival_treats_both_9999_as_nodata(mock_rasters):
    """
    Arrival metadata valid_min and valid_max must treat both +9999 and -9999 as nodata.
    """
    response = client.get("/api/rasters/arrival/metadata")
    assert response.status_code == 200
    meta = response.json()

    assert meta["valid_min"] == pytest.approx(12.5)
    assert meta["valid_max"] == pytest.approx(40.0)


def test_point_query_valid_cell(mock_rasters):
    """GET /api/rasters/{id}/value returns row, col, value, is_nodata for valid cell."""
    # Pixel center for col=1, row=0 (x=74.375, y=16.875)
    response = client.get("/api/rasters/dem/value?lon=74.375&lat=16.875")
    assert response.status_code == 200
    res = response.json()
    assert res["id"] == "dem"
    assert res["row"] == 0
    assert res["column"] == 1
    assert res["value"] == pytest.approx(610.0)
    assert res["is_nodata"] is False


def test_point_query_header_nodata(mock_rasters):
    """GET /api/rasters/dem/value at [0,0] (-9999) returns value=null, is_nodata=true."""
    # Pixel center for col=0, row=0 (x=74.125, y=16.875)
    response = client.get("/api/rasters/dem/value?lon=74.125&lat=16.875")
    assert response.status_code == 200
    res = response.json()
    assert res["row"] == 0
    assert res["column"] == 0
    assert res["value"] is None
    assert res["is_nodata"] is True


def test_arrival_point_query_plus_9999_as_nodata(mock_rasters):
    """
    Arrival raster must treat +9999 as NoData and return value: null without modifying file.
    """
    # col=2, row=0 has +9999.0 (x=74.625, y=16.875)
    response = client.get("/api/rasters/arrival/value?lon=74.625&lat=16.875")
    assert response.status_code == 200
    res = response.json()
    assert res["row"] == 0
    assert res["column"] == 2
    assert res["value"] is None
    assert res["is_nodata"] is True


def test_arrival_point_query_minus_9999_as_nodata(mock_rasters):
    """
    Arrival raster must treat -9999 as NoData and return value: null.
    """
    # col=3, row=1 has -9999.0 (x=74.875, y=16.625)
    response = client.get("/api/rasters/arrival/value?lon=74.875&lat=16.625")
    assert response.status_code == 200
    res = response.json()
    assert res["row"] == 1
    assert res["column"] == 3
    assert res["value"] is None
    assert res["is_nodata"] is True


def test_arrival_point_query_nan_as_nodata(mock_rasters):
    """
    Arrival raster with NaN must return value: null and is_nodata: true.
    """
    # col=2, row=2 has NaN (x=74.625, y=16.375)
    response = client.get("/api/rasters/arrival/value?lon=74.625&lat=16.375")
    assert response.status_code == 200
    res = response.json()
    assert res["row"] == 2
    assert res["column"] == 2
    assert res["value"] is None
    assert res["is_nodata"] is True


def test_point_query_outside_bounds_returns_422(mock_rasters):
    """Querying coordinates outside bounds returns 422 Unprocessable Entity."""
    response = client.get("/api/rasters/dem/value?lon=80.0&lat=20.0")
    assert response.status_code == 422
    assert "outside raster bounds" in response.json()["detail"]


def test_point_query_invalid_params_returns_422():
    """Missing or non-numeric lon/lat returns 422."""
    response = client.get("/api/rasters/dem/value?lon=invalid&lat=16.5")
    assert response.status_code == 422


def test_unknown_dataset_id_returns_404():
    """Requesting an unknown dataset returns 404."""
    response = client.get("/api/rasters/unknown_layer/metadata")
    assert response.status_code == 404

    val_resp = client.get("/api/rasters/unknown_layer/value?lon=74.5&lat=16.5")
    assert val_resp.status_code == 404


def test_path_traversal_attempts_return_404():
    """Path traversal strings in dataset ID must return 404 and never access filesystem."""
    traversal_ids = [
        "../../etc/passwd",
        "..\\..\\windows\\system32",
        "data/raw/data_hidkal/hidkal_dem.tif",
        "dem.tif",
    ]
    for tid in traversal_ids:
        res_meta = client.get(f"/api/rasters/{tid}/metadata")
        assert res_meta.status_code == 404

        res_val = client.get(f"/api/rasters/{tid}/value?lon=74.5&lat=16.5")
        assert res_val.status_code == 404

        res_tile = client.get(f"/api/rasters/{tid}/tiles/10/500/500.png")
        assert res_tile.status_code == 404

        res_legend = client.get(f"/api/rasters/{tid}/legend")
        assert res_legend.status_code == 404


def test_get_legend(mock_rasters):
    """GET /api/rasters/{id}/legend returns legend items and color ramp stops."""
    for layer_id in ["dem", "depth", "velocity", "arrival"]:
        response = client.get(f"/api/rasters/{layer_id}/legend")
        assert response.status_code == 200
        legend = response.json()
        assert legend["id"] == layer_id
        assert "label" in legend
        assert "unit_status" in legend
        assert "provenance_status" in legend
        assert legend["min_value"] is not None
        assert legend["max_value"] is not None
        assert len(legend["color_ramp"]) >= 3
        assert len(legend["items"]) >= 3

        for stop in legend["color_ramp"]:
            assert "offset" in stop
            assert 0.0 <= stop["offset"] <= 1.0
            assert "color" in stop
            assert stop["color"].startswith("#")

        for item in legend["items"]:
            assert "value" in item
            assert "color" in item
            assert "label" in item


def test_get_tiles_dem(mock_rasters):
    """GET /api/rasters/dem/tiles/{z}/{x}/{y}.png returns a valid 256x256 PNG."""
    import io
    from PIL import Image

    # Mock bounds are [74.0, 16.0, 75.0, 17.0]. Slippy tile for z=8 at (74.5, 16.5) is x=180, y=116
    response = client.get("/api/rasters/dem/tiles/8/180/116.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"

    img = Image.open(io.BytesIO(response.content))
    assert img.size == (256, 256)
    assert img.mode == "RGBA"


def test_get_tiles_outside_bounds_returns_transparent_png(mock_rasters):
    """Tiles far outside raster bounds return 200 transparent 256x256 PNG without 500 error."""
    import io
    from PIL import Image

    # Tile at zoom 10, x=0, y=0 (Greenland/Arctic) is far outside
    response = client.get("/api/rasters/dem/tiles/10/0/0.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"

    img = Image.open(io.BytesIO(response.content))
    assert img.size == (256, 256)
    arr = np.array(img)
    # Alpha channel must be all 0 (fully transparent)
    assert np.all(arr[:, :, 3] == 0)


def test_depth_tiles_zero_transparent(mock_rasters):
    """Depth tile renders zero-depth pixels as fully transparent (alpha = 0)."""
    import io
    from PIL import Image

    # Tile covering mock depth raster
    response = client.get("/api/rasters/depth/tiles/8/180/116.png")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    arr = np.array(img)

    # Some pixels are depth > 0 (alpha > 0), and some are depth = 0 / outside (alpha == 0)
    has_transparent = np.any(arr[:, :, 3] == 0)
    has_colored = np.any(arr[:, :, 3] > 0)
    assert has_transparent
    assert has_colored


def test_velocity_tiles_zero_transparent(mock_rasters):
    """Velocity tile renders zero-velocity pixels as fully transparent (alpha = 0)."""
    import io
    from PIL import Image

    response = client.get("/api/rasters/velocity/tiles/8/180/116.png")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    arr = np.array(img)

    has_transparent = np.any(arr[:, :, 3] == 0)
    has_colored = np.any(arr[:, :, 3] > 0)
    assert has_transparent
    assert has_colored


def test_arrival_tiles_9999_transparent(mock_rasters):
    """Arrival tile renders +9999 and -9999 pixels as transparent (alpha = 0)."""
    import io
    from PIL import Image

    response = client.get("/api/rasters/arrival/tiles/8/180/116.png")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    arr = np.array(img)

    # Valid arrival pixels exist and +9999 / nodata pixels are transparent
    has_transparent = np.any(arr[:, :, 3] == 0)
    has_colored = np.any(arr[:, :, 3] > 0)
    assert has_transparent
    assert has_colored



# Integration test with real Hidkal data (skipped if data/raw absent)
HIDKAL_DEM_PATH = Path(__file__).resolve().parents[2] / "data" / "raw" / "data_hidkal" / "hidkal_dem.tif"


@pytest.mark.skipif(not HIDKAL_DEM_PATH.exists(), reason="Local Hidkal dataset is not present in data/raw")
def test_local_hidkal_integration():
    """
    Integration test using real Hidkal GeoTIFFs when present locally.
    Validates Hidkal DEM bounds, metadata, arrival NoData filtering, tiles, and legends.
    """
    import io
    from PIL import Image

    # Ensure default datasets are active
    reset_registered_datasets()

    # 1. Dataset listing
    res = client.get("/api/datasets")
    assert res.status_code == 200
    datasets = {d["id"]: d for d in res.json()}
    assert datasets["dem"]["available"] is True
    assert datasets["arrival"]["available"] is True

    # 2. Real DEM metadata
    dem_meta_res = client.get("/api/rasters/dem/metadata")
    assert dem_meta_res.status_code == 200
    dem_meta = dem_meta_res.json()
    assert dem_meta["width"] == 700
    assert dem_meta["height"] == 600
    assert dem_meta["crs"] == "EPSG:4326"
    assert dem_meta["bounds"]["left"] == pytest.approx(74.6)
    assert dem_meta["bounds"]["right"] == pytest.approx(74.88)
    assert dem_meta["valid_min"] == pytest.approx(600.0001, rel=1e-3)
    assert dem_meta["valid_max"] == pytest.approx(682.5, rel=1e-3)

    # 3. Real Arrival metadata: checks +9999 filtering (valid max is 66.5, not 9999.0)
    arr_meta_res = client.get("/api/rasters/arrival/metadata")
    assert arr_meta_res.status_code == 200
    arr_meta = arr_meta_res.json()
    assert arr_meta["valid_min"] == pytest.approx(7.0, rel=1e-3)
    assert arr_meta["valid_max"] == pytest.approx(66.5, rel=1e-3)

    # 4. Query arrival raster at unflooded point (+9999.0)
    # Bounds: 74.6 to 74.88, 16.12 to 16.32. Top-left corner (74.61, 16.31) is unflooded
    arr_val_res = client.get("/api/rasters/arrival/value?lon=74.61&lat=16.31")
    assert arr_val_res.status_code == 200
    arr_val = arr_val_res.json()
    assert arr_val["is_nodata"] is True
    assert arr_val["value"] is None

    # 5. Outside bounds returns 422
    out_res = client.get("/api/rasters/dem/value?lon=70.0&lat=10.0")
    assert out_res.status_code == 422

    # 6. Real Hidkal Tiles at zoom 11 (x=1449, y=930 covers Hidkal)
    for lid in ["dem", "depth", "velocity", "arrival"]:
        tile_res = client.get(f"/api/rasters/{lid}/tiles/11/1449/930.png")
        assert tile_res.status_code == 200
        assert tile_res.headers["content-type"] == "image/png"
        img = Image.open(io.BytesIO(tile_res.content))
        assert img.size == (256, 256)

        legend_res = client.get(f"/api/rasters/{lid}/legend")
        assert legend_res.status_code == 200
        legend_data = legend_res.json()
        assert legend_data["id"] == lid
        assert len(legend_data["color_ramp"]) > 0


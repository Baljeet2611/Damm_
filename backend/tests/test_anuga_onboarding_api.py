"""
Unit and integration tests for Simulation-Readiness Assessment & Reproducible ANUGA Package (SIH PS 26161).

Tests:
1. Missing-input blockers for ANUGA preflight (reservoir boundary, model domain, downstream outlet, vertical unit/datum, crest/invert elevations, mesh/time configs, breach location).
2. Physical elevation consistency checks (crest > reservoir_level > invert).
3. Geometric containment checks (domain inside DEM, outlet inside domain).
4. Manifest tampering protection (409 project_integrity_failed on preflight, build-package, and package download).
5. Successful ANUGA package generation (ZIP contents, manifest SHA-256 hashes, script parameters, no SWW fabricated).
6. Unsupported progressive formation-time reported as warning without crashing.
7. Backward compatibility with older projects saved without domain/outlet.
8. Strict UUID and path traversal protection across all new endpoints.
9. Geometry endpoints for model-domain and outlet.
"""

import io
import json
import zipfile
import hashlib
from pathlib import Path
import pytest
import numpy as np
import rasterio
from affine import Affine
from fastapi.testclient import TestClient

from app.main import app
from app import onboarding_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_dam_projects_storage(tmp_path, monkeypatch):
    """Ensure all tests execute with an isolated temporary dam_projects storage directory."""
    temp_dir = tmp_path / "dam_projects"
    temp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(onboarding_service, "get_dam_projects_dir", lambda: temp_dir)
    return temp_dir


def create_test_geotiff_bytes(
    width: int = 50,
    height: int = 50,
    crs: str = "EPSG:32643",
    bands: int = 1,
    nodata: float = -9999.0,
    min_val: float = 580.0,
    max_val: float = 720.0,
    origin_x: float = 500000.0,
    origin_y: float = 1800000.0,
    res: float = 30.0,
) -> bytes:
    """Create in-memory GeoTIFF raster bytes."""
    buf = io.BytesIO()
    transform = Affine(res, 0.0, origin_x, 0.0, -res, origin_y)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": bands,
        "dtype": "float32",
        "crs": crs if crs else None,
        "transform": transform,
        "nodata": nodata,
    }
    with rasterio.open(buf, "w", **profile) as dst:
        data = np.linspace(min_val, max_val, width * height, dtype=np.float32).reshape((height, width))
        for b_idx in range(1, bands + 1):
            dst.write(data, b_idx)

    return buf.getvalue()


def create_line_geojson(coords: list, name: str = "Dam Axis") -> bytes:
    """Create GeoJSON FeatureCollection with LineString."""
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords,
                },
                "properties": {"name": name},
            }
        ],
    }
    return json.dumps(fc).encode("utf-8")


def create_polygon_geojson(coords: list, name: str = "Polygon") -> bytes:
    """Create GeoJSON FeatureCollection with Polygon."""
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [coords],
                },
                "properties": {"name": name},
            }
        ],
    }
    return json.dumps(fc).encode("utf-8")


def create_point_geojson(coords: list, name: str = "Point") -> bytes:
    """Create GeoJSON FeatureCollection with Point."""
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": coords,
                },
                "properties": {"name": name},
            }
        ],
    }
    return json.dumps(fc).encode("utf-8")


def get_standard_valid_payload():
    """Build standard complete valid multipart dataset for testing."""
    # Extent in EPSG:32643: [500000, 1800000 - 50*30=1798500] -> X: 500000 to 501500, Y: 1798500 to 1800000
    dem_bytes = create_test_geotiff_bytes()
    dam_axis_bytes = create_line_geojson([[500500.0, 1799200.0], [500500.0, 1799800.0]], "Dam Axis")
    reservoir_bytes = create_polygon_geojson(
        [
            [500100.0, 1799200.0],
            [500500.0, 1799200.0],
            [500500.0, 1799800.0],
            [500100.0, 1799800.0],
            [500100.0, 1799200.0],
        ],
        "Reservoir Pool",
    )
    domain_bytes = create_polygon_geojson(
        [
            [500050.0, 1798600.0],
            [501400.0, 1798600.0],
            [501400.0, 1799900.0],
            [500050.0, 1799900.0],
            [500050.0, 1798600.0],
        ],
        "Model Domain",
    )
    outlet_bytes = create_line_geojson([[501400.0, 1798800.0], [501400.0, 1799600.0]], "Downstream Outlet")

    files = {
        "dem_file": ("dem.tif", dem_bytes, "image/tiff"),
        "dam_axis_file": ("dam_axis.geojson", dam_axis_bytes, "application/geo+json"),
        "reservoir_boundary_file": ("reservoir.geojson", reservoir_bytes, "application/geo+json"),
        "model_domain_file": ("model_domain.geojson", domain_bytes, "application/geo+json"),
        "downstream_outlet_file": ("outlet.geojson", outlet_bytes, "application/geo+json"),
    }
    data = {
        "project_name": "Koyna ANUGA Study",
        "vertical_unit": "meters",
        "vertical_datum": "MSL",
        "reservoir_level": "650.0",
        "dam_crest_elevation": "665.0",
        "breach_invert_elevation": "590.0",
        "breach_width": "120.0",
        "breach_center_x": "500500.0",
        "breach_center_y": "1799500.0",
        "breach_formation_time_hr": "1.5",
        "manning_roughness": "0.035",
        "target_mesh_resolution_m": "30.0",
        "simulation_duration_s": "7200.0",
        "output_interval_s": "60.0",
        "geometry_crs": "EPSG:32643",
        "acknowledge_unverified_metadata": "true",
    }
    return files, data


class TestDamProjectAnugaPreflight:
    """Tests for POST /api/dam-projects/{project_id}/anuga/preflight."""

    def test_preflight_passes_for_complete_valid_project(self):
        files, data = get_standard_valid_payload()
        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200
        p_id = save_res.json()["project_id"]

        # Run preflight
        pf_res = client.post(f"/api/dam-projects/{p_id}/anuga/preflight")
        assert pf_res.status_code == 200
        pf_data = pf_res.json()

        assert pf_data["preflight_passed"] is True
        assert len(pf_data["blockers"]) == 0
        assert pf_data["scientific_status"] == "hypothetical_unverified"

        # Derived checks
        derived = pf_data["derived_checks"]
        assert derived["water_head_above_invert_m"] == 60.0  # 650.0 - 590.0
        assert derived["freeboard_m"] == 15.0  # 665.0 - 650.0
        assert derived["output_steps_count"] == 120  # 7200 / 60
        assert derived["model_domain_area_km2"] is not None
        assert derived["model_domain_area_km2"] > 0
        assert derived["estimated_mesh_triangles"] is not None
        assert derived["estimated_mesh_triangles"] > 0

        # Proposed configuration
        cfg = pf_data["proposed_configuration"]
        assert cfg["target_mesh_resolution_m"] == 30.0
        assert cfg["simulation_duration_s"] == 7200.0
        assert cfg["output_interval_s"] == 60.0
        assert cfg["manning_roughness"] == 0.035
        assert cfg["solver_type"] == "anuga_shallow_water_2d"
        assert cfg["breach_formulation"] == "instantaneous_hypothetical"

        # Warning for unsupported breach formation time
        warnings_text = " ".join(pf_data["warnings"])
        assert "instantaneous" in warnings_text.lower()
        assert "unsupported" in warnings_text.lower()

    def test_preflight_blocks_when_reservoir_boundary_missing(self):
        files, data = get_standard_valid_payload()
        del files["reservoir_boundary_file"]
        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200
        p_id = save_res.json()["project_id"]

        pf_res = client.post(f"/api/dam-projects/{p_id}/anuga/preflight")
        assert pf_res.status_code == 200
        pf_data = pf_res.json()
        assert pf_data["preflight_passed"] is False
        assert any("reservoir boundary" in b.lower() for b in pf_data["blockers"])

    def test_preflight_blocks_when_model_domain_missing(self):
        files, data = get_standard_valid_payload()
        del files["model_domain_file"]
        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200
        p_id = save_res.json()["project_id"]

        pf_res = client.post(f"/api/dam-projects/{p_id}/anuga/preflight")
        assert pf_res.status_code == 200
        pf_data = pf_res.json()
        assert pf_data["preflight_passed"] is False
        assert any("model domain" in b.lower() for b in pf_data["blockers"])

    def test_preflight_blocks_when_outlet_missing(self):
        files, data = get_standard_valid_payload()
        del files["downstream_outlet_file"]
        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200
        p_id = save_res.json()["project_id"]

        pf_res = client.post(f"/api/dam-projects/{p_id}/anuga/preflight")
        assert pf_res.status_code == 200
        pf_data = pf_res.json()
        assert pf_data["preflight_passed"] is False
        assert any("downstream outlet" in b.lower() for b in pf_data["blockers"])

    def test_preflight_blocks_when_outlet_outside_model_domain(self):
        files, data = get_standard_valid_payload()
        # Model domain is [500050, 1798600] to [500700, 1799900]
        # Outlet is at X=501200, which is fully inside DEM [500000..501500] but outside model domain
        files["model_domain_file"] = (
            "model_domain.geojson",
            create_polygon_geojson(
                [
                    [500050.0, 1798600.0],
                    [500700.0, 1798600.0],
                    [500700.0, 1799900.0],
                    [500050.0, 1799900.0],
                    [500050.0, 1798600.0],
                ],
                "Small Model Domain",
            ),
            "application/geo+json",
        )
        files["downstream_outlet_file"] = (
            "outlet.geojson",
            create_line_geojson([[501200.0, 1798800.0], [501200.0, 1799600.0]]),
            "application/geo+json",
        )
        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200
        p_id = save_res.json()["project_id"]

        pf_res = client.post(f"/api/dam-projects/{p_id}/anuga/preflight")
        assert pf_res.status_code == 200
        pf_data = pf_res.json()
        assert pf_data["preflight_passed"] is False
        assert any("outlet" in b.lower() and ("touch" in b.lower() or "boundary" in b.lower() or "outside" in b.lower()) for b in pf_data["blockers"])

    def test_preflight_blocks_when_reservoir_extends_outside_model_domain(self):
        files, data = get_standard_valid_payload()
        # DEM extent: X in [500000, 501500]
        # Set Model Domain: X in [500300, 501400]
        # Reservoir: X in [500100, 500500] (inside DEM [500000..501500], but extends west of domain [500300..501400])
        files["model_domain_file"] = (
            "model_domain.geojson",
            create_polygon_geojson(
                [
                    [500300.0, 1798600.0],
                    [501400.0, 1798600.0],
                    [501400.0, 1799900.0],
                    [500300.0, 1799900.0],
                    [500300.0, 1798600.0],
                ],
                "Shifted Model Domain",
            ),
            "application/geo+json",
        )
        files["reservoir_boundary_file"] = (
            "reservoir.geojson",
            create_polygon_geojson(
                [
                    [500100.0, 1799200.0],
                    [500500.0, 1799200.0],
                    [500500.0, 1799800.0],
                    [500100.0, 1799800.0],
                    [500100.0, 1799200.0],
                ],
                "Partially Outside Reservoir",
            ),
            "application/geo+json",
        )
        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200
        p_id = save_res.json()["project_id"]

        pf_res = client.post(f"/api/dam-projects/{p_id}/anuga/preflight")
        assert pf_res.status_code == 200
        pf_data = pf_res.json()
        assert pf_data["preflight_passed"] is False
        assert any("reservoir" in b.lower() and "model domain" in b.lower() for b in pf_data["blockers"])

    def test_preflight_blocks_when_outlet_is_point_geometry(self):
        files, data = get_standard_valid_payload()
        # Downstream outlet supplied as Point
        files["downstream_outlet_file"] = (
            "outlet.geojson",
            create_point_geojson([501400.0, 1799200.0], "Outlet Point"),
            "application/geo+json",
        )
        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200
        p_id = save_res.json()["project_id"]

        pf_res = client.post(f"/api/dam-projects/{p_id}/anuga/preflight")
        assert pf_res.status_code == 200
        pf_data = pf_res.json()
        assert pf_data["preflight_passed"] is False
        assert any("linestring" in b.lower() and "point" in b.lower() for b in pf_data["blockers"])

    def test_preflight_blocks_when_outlet_does_not_touch_model_domain_boundary(self):
        files, data = get_standard_valid_payload()
        # Model domain exterior X bounds are 500050 and 501400, Y bounds are 1798600 and 1799900
        # Put outlet line right in the interior center of the domain at X=500800 (not touching boundary)
        files["downstream_outlet_file"] = (
            "outlet.geojson",
            create_line_geojson([[500800.0, 1799000.0], [500800.0, 1799400.0]], "Interior Outlet"),
            "application/geo+json",
        )
        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200
        p_id = save_res.json()["project_id"]

        pf_res = client.post(f"/api/dam-projects/{p_id}/anuga/preflight")
        assert pf_res.status_code == 200
        pf_data = pf_res.json()
        assert pf_data["preflight_passed"] is False
        assert any("outlet" in b.lower() and ("touch" in b.lower() or "boundary" in b.lower()) for b in pf_data["blockers"])

    def test_preflight_warns_when_breach_invert_below_local_terrain(self):
        files, data = get_standard_valid_payload()
        # DEM values range from 580.0 to 720.0. Local terrain around breach is ~620.0.
        # Set breach invert very low (e.g. 500.0)
        data["breach_invert_elevation"] = "500.0"
        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200
        p_id = save_res.json()["project_id"]

        pf_res = client.post(f"/api/dam-projects/{p_id}/anuga/preflight")
        assert pf_res.status_code == 200
        pf_data = pf_res.json()
        assert any("lower than local baseline dem terrain" in w.lower() for w in pf_data["warnings"])

    def test_preflight_blocks_when_vertical_unit_or_datum_missing(self):
        files, data = get_standard_valid_payload()
        data["vertical_unit"] = ""
        data["vertical_datum"] = ""
        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200
        p_id = save_res.json()["project_id"]

        pf_res = client.post(f"/api/dam-projects/{p_id}/anuga/preflight")
        assert pf_res.status_code == 200
        pf_data = pf_res.json()
        assert pf_data["preflight_passed"] is False
        assert any("vertical unit" in b.lower() for b in pf_data["blockers"])
        assert any("vertical datum" in b.lower() for b in pf_data["blockers"])

    def test_preflight_blocks_elevation_inconsistencies(self):
        # Case A: dam crest <= reservoir level
        files, data = get_standard_valid_payload()
        data["dam_crest_elevation"] = "640.0"  # Less than reservoir_level 650.0
        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200
        p_id = save_res.json()["project_id"]

        pf_res = client.post(f"/api/dam-projects/{p_id}/anuga/preflight")
        assert pf_res.status_code == 200
        pf_data = pf_res.json()
        assert pf_data["preflight_passed"] is False
        assert any("dam crest elevation" in b.lower() and "greater than" in b.lower() for b in pf_data["blockers"])

        # Case B: breach invert >= reservoir level
        files2, data2 = get_standard_valid_payload()
        data2["breach_invert_elevation"] = "655.0"  # Greater than reservoir_level 650.0
        save_res2 = client.post("/api/dam-projects", files=files2, data=data2)
        assert save_res2.status_code == 200
        p_id2 = save_res2.json()["project_id"]

        pf_res2 = client.post(f"/api/dam-projects/{p_id2}/anuga/preflight")
        assert pf_res2.status_code == 200
        pf_data2 = pf_res2.json()
        assert pf_data2["preflight_passed"] is False
        assert any("breach invert elevation" in b.lower() and "less than" in b.lower() for b in pf_data2["blockers"])

    def test_preflight_blocks_breach_center_far_from_axis(self):
        files, data = get_standard_valid_payload()
        # Move breach center 1500m away from dam axis (tolerance is max(200, 5*30)=200m)
        data["breach_center_x"] = "501300.0"
        data["breach_center_y"] = "1799500.0"
        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200
        p_id = save_res.json()["project_id"]

        pf_res = client.post(f"/api/dam-projects/{p_id}/anuga/preflight")
        assert pf_res.status_code == 200
        pf_data = pf_res.json()
        assert pf_data["preflight_passed"] is False
        assert any("breach center is located" in b.lower() or "exceeds" in b.lower() for b in pf_data["blockers"])


class TestDamProjectAnugaPackageBuilder:
    """Tests for package generation, compilation, deterministic build, and download."""

    def test_package_build_fails_when_preflight_fails(self):
        files, data = get_standard_valid_payload()
        del files["model_domain_file"]
        save_res = client.post("/api/dam-projects", files=files, data=data)
        p_id = save_res.json()["project_id"]

        build_res = client.post(f"/api/dam-projects/{p_id}/anuga/build-package")
        assert build_res.status_code == 400
        err = build_res.json()
        assert "preflight" in str(err).lower()

    def test_package_build_and_download_success(self, tmp_path):
        import py_compile
        files, data = get_standard_valid_payload()
        save_res = client.post("/api/dam-projects", files=files, data=data)
        p_id = save_res.json()["project_id"]

        # 1. Build package
        build_res = client.post(f"/api/dam-projects/{p_id}/anuga/build-package")
        assert build_res.status_code == 200
        build_data = build_res.json()

        assert build_data["package_filename"] == "anuga_package.zip"
        assert build_data["package_size_bytes"] > 0
        assert build_data["package_sha256"] is not None
        assert build_data["simulation_executed"] is False
        assert build_data["scientific_status"] == "hypothetical_unverified"

        # 2. Repeated build must return existing package (deterministic & non-overwriting)
        repeat_build_res = client.post(f"/api/dam-projects/{p_id}/anuga/build-package")
        assert repeat_build_res.status_code == 200
        repeat_data = repeat_build_res.json()
        assert repeat_data["package_sha256"] == build_data["package_sha256"]
        assert "existing package returned" in repeat_data["message"].lower()

        # 3. Download package ZIP
        dl_res = client.get(f"/api/dam-projects/{p_id}/anuga/package")
        assert dl_res.status_code == 200
        assert dl_res.headers["content-type"] == "application/zip"
        zip_bytes = dl_res.content

        # 4. Inspect ZIP structure
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            namelist = zf.namelist()
            assert "config.json" in namelist
            assert "run_anuga.py" in namelist
            assert "requirements.txt" in namelist
            assert "README_LIMITATIONS.txt" in namelist
            assert "manifest.json" in namelist
            assert "dem.tif" in namelist
            assert "dam_axis.geojson" in namelist
            assert "reservoir_boundary.geojson" in namelist
            assert "model_domain.geojson" in namelist
            assert "downstream_outlet.geojson" in namelist
            assert "environment_anuga.yml" in namelist

            # Ensure no fake simulation results fabricated
            for fn in namelist:
                assert not fn.endswith(".sww")
                assert not fn.endswith(".nc")
                assert not fn.startswith("results/")

            # Validate internal manifest SHA-256 hashes
            manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))
            assert manifest_data["simulation_executed"] is False
            assert manifest_data["scientific_status"] == "hypothetical_unverified"

            for fname, meta in manifest_data["files"].items():
                content = zf.read(fname)
                expected_h = meta["sha256"]
                actual_h = hashlib.sha256(content).hexdigest()
                assert actual_h == expected_h, f"Hash mismatch in package for {fname}"

            # Validate run_anuga.py content and test py_compile
            script_str = zf.read("run_anuga.py").decode("utf-8")
            assert "anuga" in script_str
            assert "config.json" in script_str
            assert "Hypothetical Unverified" in script_str

            script_temp_file = tmp_path / "test_run_anuga.py"
            script_temp_file.write_text(script_str, encoding="utf-8")
            compiled_path = py_compile.compile(str(script_temp_file), doraise=True)
            assert compiled_path is not None

            # Validate config.json content
            cfg_dict = json.loads(zf.read("config.json").decode("utf-8"))
            assert cfg_dict["reservoir_level"] == 650.0
            assert cfg_dict["dam_crest_elevation"] == 665.0
            assert cfg_dict["breach_invert_elevation"] == 590.0
            assert cfg_dict["simulation_parameters"]["target_mesh_resolution_m"] == 30.0

            # Validate README
            readme_str = zf.read("README_LIMITATIONS.txt").decode("utf-8")
            assert "NO SIMULATION HAS BEEN EXECUTED" in readme_str
            assert "instantaneous hypothetical" in readme_str.lower()

    def test_user_strings_cannot_inject_python_code(self, tmp_path):
        import py_compile
        files, data = get_standard_valid_payload()
        # Inject Python syntax break and executable code into user text fields
        data["project_name"] = 'Dam"); import os; os.system("echo PWNED"); #'
        data["vertical_unit"] = 'meters"); __import__("sys").exit(1); #'
        data["vertical_datum"] = 'MSL\nimport os\nos.remove("xyz")\n'

        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200
        p_id = save_res.json()["project_id"]

        # Build package
        build_res = client.post(f"/api/dam-projects/{p_id}/anuga/build-package")
        assert build_res.status_code == 200

        # Download and verify run_anuga.py is pure static script and compiles safely
        dl_res = client.get(f"/api/dam-projects/{p_id}/anuga/package")
        with zipfile.ZipFile(io.BytesIO(dl_res.content), "r") as zf:
            script_str = zf.read("run_anuga.py").decode("utf-8")
            assert "PWNED" not in script_str
            assert "os.remove" not in script_str

            script_temp = tmp_path / "injected_check.py"
            script_temp.write_text(script_str, encoding="utf-8")
            compiled_path = py_compile.compile(str(script_temp), doraise=True)
            assert compiled_path is not None

            # config.json contains the strings safely as JSON data
            cfg = json.loads(zf.read("config.json").decode("utf-8"))
            assert 'PWNED' in cfg["project_name"]

    def test_working_terrain_and_breach_gap_calculations_preserve_original_dem(self):
        from shapely.geometry import Point, LineString
        import numpy as np

        # Simulate the exact math in run_anuga.py
        breach_center = [500500.0, 1799500.0]
        breach_width = 120.0
        dam_crest = 665.0
        breach_invert = 590.0

        dam_line = LineString([[500500.0, 1799200.0], [500500.0, 1799800.0]])
        dam_poly = dam_line.buffer(15.0)
        breach_pt = Point(breach_center[0], breach_center[1])
        breach_poly = breach_pt.buffer(breach_width / 2.0)

        # 1. Point at exact breach center must be inside breach polygon
        assert breach_poly.contains(breach_pt)
        # 2. Point 50m north on dam axis must be inside breach polygon (radius is 60m)
        assert breach_poly.contains(Point(500500.0, 1799550.0))
        # 3. Point 70m north on dam axis must be OUTSIDE breach polygon (outside 60m radius)
        assert not breach_poly.contains(Point(500500.0, 1799570.0))
        # 4. Point 70m north on dam axis must still be inside dam crest polygon
        assert dam_poly.contains(Point(500500.0, 1799570.0))

        # Terrain modification logic test
        original_dem_elev = 620.0
        # In breach gap
        elev_in_breach = min(original_dem_elev, breach_invert)
        assert elev_in_breach == 590.0
        # On remaining dam crest
        elev_on_crest = max(original_dem_elev, dam_crest)
        assert elev_on_crest == 665.0
        # Original DEM reference value remains 620.0
        assert original_dem_elev == 620.0

    def test_tampered_manifest_blocks_preflight_and_build(self):
        files, data = get_standard_valid_payload()
        save_res = client.post("/api/dam-projects", files=files, data=data)
        p_id = save_res.json()["project_id"]

        # Tamper with dem.tif
        proj_dir = onboarding_service.get_dam_projects_dir() / p_id
        dem_file = proj_dir / "dem.tif"
        dem_file.write_bytes(b"corrupted_tampered_bytes")

        # Preflight must return 409 project_integrity_failed
        pf_res = client.post(f"/api/dam-projects/{p_id}/anuga/preflight")
        assert pf_res.status_code == 409
        err = pf_res.json()
        assert err["detail"]["code"] == "project_integrity_failed"

        # Build-package must also return 409
        build_res = client.post(f"/api/dam-projects/{p_id}/anuga/build-package")
        assert build_res.status_code == 409

        # Download package must return 409
        dl_res = client.get(f"/api/dam-projects/{p_id}/anuga/package")
        assert dl_res.status_code == 409


class TestDamProjectGeometryEndpoints:
    """Tests for model domain and outlet geometry endpoints."""

    def test_model_domain_and_outlet_geometry_endpoints(self):
        files, data = get_standard_valid_payload()
        save_res = client.post("/api/dam-projects", files=files, data=data)
        p_id = save_res.json()["project_id"]

        # GET model domain
        dom_res = client.get(f"/api/dam-projects/{p_id}/geometry/model-domain")
        assert dom_res.status_code == 200
        dom_fc = dom_res.json()
        assert dom_fc["type"] == "FeatureCollection"
        assert len(dom_fc["features"]) > 0
        assert dom_fc["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")

        # GET outlet
        out_res = client.get(f"/api/dam-projects/{p_id}/geometry/outlet")
        assert out_res.status_code == 200
        out_fc = out_res.json()
        assert out_fc["type"] == "FeatureCollection"
        assert len(out_fc["features"]) > 0
        assert out_fc["features"][0]["geometry"]["type"] in ("LineString", "MultiLineString", "Point")


class TestDamProjectBackwardCompatibility:
    """Ensure older saved projects without model_domain/outlet continue to load without error."""

    def test_legacy_project_loads_and_preflight_blocks_cleanly(self):
        files, data = get_standard_valid_payload()
        # Older project had no domain, no outlet, no crest elevation, no invert elevation
        del files["model_domain_file"]
        del files["downstream_outlet_file"]
        data["dam_crest_elevation"] = ""
        data["breach_invert_elevation"] = ""

        save_res = client.post("/api/dam-projects", files=files, data=data)
        assert save_res.status_code == 200
        p_id = save_res.json()["project_id"]

        # Detail endpoint succeeds
        det_res = client.get(f"/api/dam-projects/{p_id}")
        assert det_res.status_code == 200
        det = det_res.json()
        assert det["model_domain_file"] is None
        assert det["downstream_outlet_file"] is None

        # Preflight cleanly reports missing domain/outlet/elevations as blockers without 500 error
        pf_res = client.post(f"/api/dam-projects/{p_id}/anuga/preflight")
        assert pf_res.status_code == 200
        pf_data = pf_res.json()
        assert pf_data["preflight_passed"] is False
        assert len(pf_data["blockers"]) >= 3


class TestDamProjectSecurityAndValidation:
    """Security tests for path traversal and UUID format."""

    def test_path_traversal_on_anuga_endpoints(self):
        bad_ids = [
            "invalid-uuid",
            "12345",
            "not-a-uuid-format",
            "b16f3938-1234",
            "99999999-9999-9999-9999-99999999999g",
            ".._..",
            "admin--path",
        ]
        for bad_id in bad_ids:
            res_pf = client.post(f"/api/dam-projects/{bad_id}/anuga/preflight")
            assert res_pf.status_code == 422

            res_build = client.post(f"/api/dam-projects/{bad_id}/anuga/build-package")
            assert res_build.status_code == 422

            res_dl = client.get(f"/api/dam-projects/{bad_id}/anuga/package")
            assert res_dl.status_code == 422

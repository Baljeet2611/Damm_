"""
Unit tests for Phase 15 ANUGA Hidkal Regional Pilot.
Validates manifest checksums, scenario configuration honesty tags,
breach mechanics barrier and flux audit, numerical diagnostics,
reprojection mask isolation, area partitioning, and output provenance.
"""

import os
import sys
import json
import numpy as np
import yaml
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.anuga_hidkal_pilot.preprocess_dem import compute_sha256


@pytest.fixture
def pilot_dir() -> Path:
    """Path to ANUGA Hidkal pilot validation directory."""
    return REPO_ROOT / "validation" / "anuga_hidkal_pilot"


def test_pilot_manifest_integrity(pilot_dir: Path):
    """Verify that manifest.json exists and all SHA-256 hashes match files on disk."""
    manifest_file = pilot_dir / "manifest.json"
    assert manifest_file.is_file(), "manifest.json must exist in anuga_hidkal_pilot"

    with open(manifest_file, "r") as f:
        manifest = json.load(f)

    assert manifest.get("scenario_id") == "anuga_hidkal_pilot_hypothetical_v1"
    files = manifest.get("files", {})
    assert len(files) >= 6, "Manifest must track config, 3 scripts, breach diagnostics, and summary JSON"

    for rel_path, expected_hash in files.items():
        target_file = pilot_dir / rel_path
        assert target_file.is_file(), f"Tracked file {rel_path} must exist"
        actual_hash = compute_sha256(target_file)
        assert actual_hash == expected_hash, f"SHA-256 mismatch for {rel_path}: expected {expected_hash}, got {actual_hash}"


def test_scenario_config_truth_labels(pilot_dir: Path):
    """Verify that scenario_config.yml contains explicit hypothetical unverified status tags and barrier settings."""
    config_file = pilot_dir / "scenario_config.yml"
    assert config_file.is_file(), "scenario_config.yml must exist"

    with open(config_file, "r") as f:
        config = yaml.safe_load(f)

    # Check status tags
    meta = config.get("scenario_metadata", {})
    assert meta.get("scenario_status") == "hypothetical_unverified"
    assert "hypothetical" in meta.get("disclaimer", "").lower()

    # Check input source hash & assumed unit description
    raw_dem = config.get("source_inputs", {}).get("dem", {})
    assert raw_dem.get("raw_sha256") == "ed4c97474857ef24845f0954baa36b8de2555ccc2a0d468cfa99fdd39fab5baf"
    assert "assumed_metres" in raw_dem.get("elevation_unit_assumption", "")

    # Check barrier & breach settings
    breach_cfg = config.get("hypothetical_breach_and_reservoir", {})
    assert breach_cfg.get("dam_axis_x_utm_m") == 462600.0
    assert breach_cfg.get("dam_crest_elevation_assumed_m") == 675.0
    assert breach_cfg.get("assumed_breach_width_m") == 200.0


def test_breach_mechanics_and_impermeable_barrier(pilot_dir: Path):
    """Verify physical barrier presence, effective opening width, and flux containment."""
    breach_file = pilot_dir / "breach_diagnostics.json"
    assert breach_file.is_file(), "breach_diagnostics.json must exist"

    with open(breach_file, "r") as f:
        diag = json.load(f)

    assert diag.get("effective_breach_width_m") == 200.0
    assert diag.get("dam_crest_elevation_assumed_m") == 675.0
    assert diag.get("assumed_reservoir_stage_m") == 660.0

    coords = diag.get("breach_coordinates_utm43n", {})
    assert coords.get("dam_axis_x_m") == 462600.0
    assert coords.get("breach_center_y_m") == 1792000.0
    assert coords.get("breach_y_max_m") - coords.get("breach_y_min_m") == 200.0

    flux = diag.get("hydraulic_flux_summary", {})
    assert flux.get("peak_breach_discharge_m3ps", 0.0) > 1000.0
    assert flux.get("cumulative_breach_released_volume_assumed_mcm", 0.0) > 5.0
    assert flux.get("leakage_percentage", 100.0) < 0.1, "Non-breach leakage must be numerically negligible (<0.1%)"
    assert flux.get("numerical_containment_status") == "VERIFIED_NEGLIGIBLE_LEAKAGE"


def test_pilot_summary_diagnostics_and_partitioning(pilot_dir: Path):
    """Verify simulation summary results, area partitioning, boundary isolation, and mass balance."""
    summary_file = pilot_dir / "pilot_summary.json"
    assert summary_file.is_file(), "pilot_summary.json must exist"

    with open(summary_file, "r") as f:
        summary = json.load(f)

    assert summary.get("scenario_status") == "hypothetical_unverified"
    assert summary.get("verdict", {}).get("status") == "PILOT_SIMULATION_SUCCESSFUL"

    # Check spatial parameters & reprojection mask isolation
    spatial = summary.get("spatial_parameters", {})
    assert spatial.get("projected_crs") == "EPSG:32643"
    assert spatial.get("domain_extent_km2") > 500.0
    assert spatial.get("reprojection_filled_cells_excluded") is True
    assert spatial.get("reprojection_filled_cells_wetted_count") == 0

    # Check boundary isolation statement
    bnd = summary.get("boundary_analysis", {})
    assert bnd.get("boundary_interaction_occurred") is False
    assert bnd.get("boundary_isolation_verified") is True
    assert "no >=0.1 assumed-metre wetting detected within" in bnd.get("boundary_interaction_statement", "")

    # Check area partitioning
    areas = summary.get("area_partitioning_km2", {})
    init_area = areas.get("initial_reservoir_wet_area_km2", 0.0)
    total_area = areas.get("max_total_inundated_area_km2", 0.0)
    new_area = areas.get("newly_inundated_area_km2", 0.0)

    assert 15.0 <= init_area <= 45.0
    assert 25.0 <= total_area <= 80.0
    assert 5.0 <= new_area <= 30.0
    assert abs((init_area + new_area) - total_area) < 1.0, "Total area must equal initial + newly inundated area"

    # Check volume conservation within numerical precision
    vol = summary.get("volume_conservation", {})
    assert vol.get("relative_volume_error", 1.0) < 1e-10
    assert "within numerical precision" in vol.get("conservation_statement", "").lower()

    # Check inundation results
    results = summary.get("inundation_results", {})
    assert 5.0 <= results.get("max_water_depth_assumed_m", 0.0) <= 50.0
    assert 1.0 <= results.get("max_flow_velocity_mps", 0.0) <= 35.0
    assert "model-derived first detected arrival" in results.get("arrival_time_description", "")
    arr_range = results.get("newly_wetted_arrival_time_range_sec", [])
    assert len(arr_range) == 2
    assert arr_range[0] >= 0.0
    assert arr_range[1] <= 1800.0

    # Numerical integrity
    num = summary.get("numerical_integrity", {})
    assert num.get("is_finite") is True
    assert num.get("non_negative_depth") is True
    assert num.get("spatial_coverage_non_empty") is True
    assert num.get("reprojection_filled_cells_isolated") is True


def test_generated_geotiff_metadata_and_arrival_encoding(pilot_dir: Path):
    """Verify exported GeoTIFF metadata and distinct arrival encoding for initial reservoir."""
    output_dir = pilot_dir / "output"
    depth_tif = output_dir / "anuga_hidkal_pilot_depth.tif"
    vel_tif = output_dir / "anuga_hidkal_pilot_velocity.tif"
    arr_tif = output_dir / "anuga_hidkal_pilot_arrival.tif"

    import rasterio

    if depth_tif.is_file():
        with rasterio.open(depth_tif) as src:
            assert str(src.crs) == "EPSG:32643"
            arr = src.read(1)
            assert arr.max() > 5.0
            assert arr.min() >= -9999.0

    if vel_tif.is_file():
        with rasterio.open(vel_tif) as src:
            assert str(src.crs) == "EPSG:32643"
            arr = src.read(1)
            assert arr.max() > 1.0

    if arr_tif.is_file():
        with rasterio.open(arr_tif) as src:
            assert str(src.crs) == "EPSG:32643"
            arr = src.read(1)
            assert float(src.nodata) == 9999.0
            # 0.0 represents initial reservoir, > 0 represents newly wetted arrival
            assert np.any(arr == 0.0)
            assert np.any((arr > 0.0) & (arr <= 1800.0))

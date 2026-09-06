"""
Tests for Phase 14 ANUGA 2D Dam-Break Benchmark.
Validates the benchmark manifest checksums, result summary parser, centerline CSV data,
and Ritter analytical solution verification.
"""

import sys
import json
from pathlib import Path
import numpy as np
import pytest

# Ensure repository root is on sys.path regardless of pytest working directory
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.anuga_dam_break.run_benchmark import (
    compute_sha256,
    ritter_analytical_solution,
)


@pytest.fixture
def benchmark_dir() -> Path:
    """Path to ANUGA dam-break benchmark directory."""
    return REPO_ROOT / "validation" / "anuga_dam_break"


def test_manifest_integrity(benchmark_dir: Path):
    """Verify that manifest.json exists and all SHA-256 hashes match files on disk."""
    manifest_file = benchmark_dir / "manifest.json"
    assert manifest_file.is_file(), "manifest.json must exist"

    with open(manifest_file, "r") as f:
        manifest = json.load(f)

    assert manifest.get("benchmark_id") == "anuga_2d_dam_break_ritter_t40s"
    files = manifest.get("files", {})
    assert len(files) >= 3, "Manifest must track script, CSV and summary JSON"

    for rel_path, expected_hash in files.items():
        target_file = benchmark_dir / rel_path
        assert target_file.is_file(), f"Tracked file {rel_path} must exist"
        actual_hash = compute_sha256(target_file)
        assert actual_hash == expected_hash, f"SHA-256 mismatch for {rel_path}: expected {expected_hash}, got {actual_hash}"


def test_benchmark_summary_diagnostics(benchmark_dir: Path):
    """Verify benchmark summary structure, physical conservation, and error bounds."""
    summary_file = benchmark_dir / "benchmark_summary.json"
    assert summary_file.is_file(), "benchmark_summary.json must exist"

    with open(summary_file, "r") as f:
        summary = json.load(f)

    # Check solver metadata
    solver = summary.get("solver", {})
    assert "ANUGA" in solver.get("name", "")
    assert solver.get("governing_equations") == "2D Non-linear Shallow Water Equations (SWE)"

    # Check domain parameters
    domain = summary.get("domain_parameters", {})
    assert domain.get("length_m") == 2000.0
    assert domain.get("width_m") == 50.0
    assert domain.get("initial_upstream_depth_h0_m") == 10.0
    assert domain.get("gravity_mps2") == 9.81
    assert domain.get("duration_sec") == 40.0

    # Check diagnostics
    diagnostics = summary.get("diagnostics", {})
    assert diagnostics.get("is_finite_numerics") is True
    assert diagnostics.get("relative_mass_balance_error") < 1e-4, "Mass balance error must be negligible"

    # Analytical comparison at t=40s
    comp = diagnostics.get("analytical_comparison_t40s", {})
    assert comp.get("sample_points") > 100
    assert comp.get("depth_rmse_m") < 0.15, "Depth RMSE vs Ritter solution must be < 0.15 m"
    assert comp.get("depth_mae_m") < 0.10, "Depth MAE vs Ritter solution must be < 0.10 m"

    # Verdict
    assert summary.get("verdict", {}).get("status") == "PASSED_VERIFIED"


def test_centerline_csv_format(benchmark_dir: Path):
    """Verify centerline CSV format and physical values."""
    csv_file = benchmark_dir / "centerline_t40s.csv"
    assert csv_file.is_file(), "centerline_t40s.csv must exist"

    data = np.genfromtxt(csv_file, delimiter=",", names=True)
    assert len(data) > 0, "Centerline data must not be empty"

    # Check columns
    assert "x_m" in data.dtype.names
    assert "depth_anuga_m" in data.dtype.names
    assert "depth_ritter_m" in data.dtype.names
    assert "u_anuga_mps" in data.dtype.names

    # Check monotonicity / coordinates
    assert np.all(np.diff(data["x_m"]) >= 0), "x coordinates must be sorted"
    assert np.min(data["x_m"]) >= 0.0
    assert np.max(data["x_m"]) <= 2000.0

    # Check non-negative depths
    assert np.all(data["depth_anuga_m"] >= -1e-6)
    assert np.all(data["depth_ritter_m"] >= 0.0)


def test_ritter_analytical_function():
    """Verify analytical Ritter solution calculation against theoretical limits."""
    h0 = 10.0
    g = 9.81
    c0 = np.sqrt(g * h0)
    x_dam = 1000.0
    t = 40.0

    # Far upstream: undisturbed reservoir depth h0
    x_upstream = np.array([100.0, 500.0])
    h_up, u_up = ritter_analytical_solution(x_upstream, t=t, x_dam=x_dam, h0=h0, g=g)
    assert np.allclose(h_up, h0)
    assert np.allclose(u_up, 0.0)

    # Far downstream: dry bed depth 0
    x_downstream = np.array([1850.0, 1950.0])
    h_down, u_down = ritter_analytical_solution(x_downstream, t=t, x_dam=x_dam, h0=h0, g=g)
    assert np.allclose(h_down, 0.0)
    assert np.allclose(u_down, 0.0)

    # At dam axis (x = x_dam): depth is exactly (4/9) * h0 = 4.444 m, velocity is (2/3) * c0
    x_dam_arr = np.array([x_dam])
    h_dam, u_dam = ritter_analytical_solution(x_dam_arr, t=t, x_dam=x_dam, h0=h0, g=g)
    assert np.isclose(h_dam[0], (4.0 / 9.0) * h0, atol=1e-3)
    assert np.isclose(u_dam[0], (2.0 / 3.0) * c0, atol=1e-3)

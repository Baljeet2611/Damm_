# PySPH $\to$ Delft3D-FM Breach Hydrograph Coupling Bridge

**Module Version**: 1.1.0 (Phase A1 Gate Verified)  
**Authors**: Antigravity AI Pair Programming System  
**Status**: Scientifically Validated, Unit-Tested, & Provenance-Verified  

---

## 1. Overview and Scientific Motivation

Near-field dam breach hydrodynamics involve 3D free-surface deformations, violent wave-breaking, and steep vertical accelerations where hydrostatic shallow-water assumptions break down. Smoothed Particle Hydrodynamics (SPH / WCSPH) captures these non-hydrostatic phenomena near the breach structure. However, simulating regional downstream flood routing (10–100 km) with SPH is computationally prohibitive due to particle count scaling.

Conversely, 2D Shallow Water Equation solvers like **Deltares Delft3D Flexible Mesh (D-Flow FM)** efficiently model regional floodplain routing over large unstructured meshes, but require an accurate upstream boundary inflow hydrograph $Q(t)$.

This coupling bridge establishes a bidirectional numerical link:
$$\text{PySPH / WCSPH Near-Field Simulation} \longrightarrow Q(t)\ [m^3/s] \longrightarrow \text{Delft3D-FM Boundary Forcing } (\texttt{breach\_inflow.bc}) \longrightarrow \text{Regional D-Flow FM Model Package}$$

---

## 2. Discharge Calculation & Time Semantics

The instantaneous volumetric breach outflow discharge $Q(t)$ ($m^3/s$) is scientifically computed across the breach control section during the SPH simulation:

$$Q(t) = \sum_{i \in \text{Breach Window}} \max\left(0,\, \vec{v}_i \cdot \hat{n}_{\text{breach}}\right) \cdot h_i(t) \cdot \Delta x$$

Where:
- $\vec{v}_i = (u_i, v_i)$ is the velocity vector of particle $i$.
- $\hat{n}_{\text{breach}} = (n_x, n_y)$ is the unit normal vector pointing downstream perpendicular to the dam axis.
- $h_i(t)$ is the local depth represented by particle $i$ ($m$).
- $\Delta x$ is the initial inter-particle spacing ($m$).
- The $\max(0, \cdot)$ operator ensures only positive downstream flux contributes to breach outflow.

### Timing Semantics ($Q(t=0)$ vs Delayed Breach)
- **Instantaneous Breach ($t_{\text{breach}} = 0.0\,\text{s}$)**: The breach control section is opened at $t=0$. Reservoir water column immediately accelerates through the opening due to hydrostatic pressure gradient, resulting in $Q(0) \ge 0$ as physically expected for sudden instantaneous failure.
- **Delayed Breach ($t_{\text{breach}} > 0.0\,\text{s}$)**: The impermeable dam barrier reflects all particles upstream until $t = t_{\text{breach}}$. For all $t < t_{\text{breach}}$, $Q(t) \equiv 0.0\,\text{m}^3/\text{s}$.

### Numerical Integrity & Volume Metrics
1. **Strict Monotonicity**: Timestamps $t_0 < t_1 < \dots < t_N$ are strictly increasing.
2. **Positivity**: $Q(t) \ge 0.0$ for all $t$.
3. **Finite Numerics**: Zero `NaN`, `Inf`, or uninitialized values.
4. **Released Volume**:
   $$V_{\text{released}} = \int_0^T Q(t)\, dt \approx \sum_{k=0}^{N-1} \frac{Q(t_k) + Q(t_{k+1})}{2} (t_{k+1} - t_k)$$
5. **Reservoir Release Fraction**:
   $$\text{reservoir\_release\_fraction} = \frac{V_{\text{released}}}{V_{\text{reservoir, initial}}}$$
6. **Global Mass Balance Check**:
   $$\text{mass\_balance\_error\_pct} = 100 \times \frac{|V_{\text{initial}} - V_{\text{final, domain}} - V_{\text{released}}|}{V_{\text{initial}}}$$
   Status is reported as `"verified"` if closed-domain error $< 15\%$, `"evaluated"` if open boundary losses occur, or `"not_available"` if historical metadata lacks spatial field depths.

---

## 3. Data Contracts & Schemas

### Internal Schema (`backend/app/schemas.py`)
```python
class HydrographPoint(BaseModel):
    time_seconds: float = Field(..., description="Timestamp in seconds from simulation start")
    discharge_cms: float = Field(..., ge=0.0, description="Instantaneous outflow discharge in m^3/s")

class BreachHydrographResponse(BaseModel):
    source_engine: str = "pysph"
    target_engine: Optional[str] = "delft3d_fm"
    run_id: str
    project_id: Optional[str] = None
    created_at: str
    time_unit: str = "s"
    discharge_unit: str = "m3/s"
    point_count: int
    duration_seconds: float
    q_peak_cms: float
    time_to_peak_seconds: float
    total_released_volume_m3: float
    initial_reservoir_volume_m3: Optional[float] = None
    reservoir_release_fraction: Optional[float] = None
    mass_balance_check: str = "not_available"
    mass_balance_error_pct: Optional[float] = None
    points: List[HydrographPoint]
    metadata: Dict[str, Any] = {}
```

---

## 4. Standardized Deltares D-Flow FM `.bc` Format & Temporal Consistency

The exported boundary condition file follows the official Deltares Delft3D Flexible Mesh specification:

```ini
# ==============================================================================
# Delft3D Flexible Mesh (D-Flow FM) Boundary Condition File
# Source Engine: pysph (Lagrangian Smoothed Particle Hydrodynamics)
# SPH Run ID:    sph-real-20260921_174139_a2df6b15
# Generated At:  2026-09-21T17:41:44.022361+00:00
# Peak Outflow:  12059.074 m3/s at t=6.00 s
# Total Volume:  49940.8 m3
# ==============================================================================

[forcing]
Name                            = Inflow_Breach
Function                        = time-series
Time-interpolation              = linear
Quantity                        = time
Unit                            = seconds since 2026-09-01 00:00:00
Quantity                        = dischargebnd
Unit                            = m3/s
0.000                           146.0836
0.200                           730.3997
0.450                           1460.6946
...
6.000                           12059.0735
...
23.950                          0.0000
```

### Temporal Alignment with `dflowfm.mdu`
- **Time Base**: `Tunit = S` (seconds), `RefDate = 20260901`.
- **Simulation Duration**: `TStart = 0.0`, `TStop = 86400.0` (24-hour regional routing window).
- **Interpolation & Tail Extrapolation**: D-Flow FM performs linear time interpolation between $Q(t)$ samples. At $t > T_{\text{sph}}$, the boundary forcing holds $Q(t) = 0.0\,\text{m}^3/\text{s}$ as guaranteed by the final hydrograph sample point, preventing artificial truncation or spurious inflows.

---

## 5. Package Provenance & Transparency

All generated packages record strict execution provenance in `manifest.json`:
```json
{
  "manifest_version": "1.0.0",
  "project_id": "23caf134-dc88-4ccc-9cdd-6baacf61b17f",
  "package_type": "project_delft3d_package",
  "solver_framework": "Delft3D Flexible Mesh (D-Flow FM)",
  "solver_execution_status": "package_generated_unexecuted",
  "coupling": {
    "is_coupled": true,
    "source_engine": "pysph",
    "target_engine": "delft3d_fm",
    "source_sph_run_id": "sph-real-20260921_174139_a2df6b15",
    "derived_from_sph": true,
    "solver_status": "package_generated_unexecuted",
    "sph_q_peak_cms": 12059.0735,
    "sph_time_to_peak_s": 6.0,
    "sph_total_released_volume_m3": 49940.84,
    "sph_reservoir_release_fraction": 0.0041,
    "sph_mass_balance_check": "evaluated"
  }
}
```
This guarantees that package generation is never misrepresented as completed Delft3D hydrodynamic simulation execution.

---

## 6. Verification & Automated Test Coverage

The test suite in `backend/tests/test_sph_delft3d_coupling.py` validates:
- [x] SPH hydrograph extraction from authentic terrain runs
- [x] Monotonic timestamps and non-negative discharge values
- [x] Accurate calculation of $Q_{\text{peak}}$, $t_{\text{peak}}$, and $\int Q(t) dt$
- [x] Correct evaluation of `reservoir_release_fraction` and `mass_balance_check`
- [x] Rejection and 404 handling of non-existent/corrupted runs
- [x] Standalone uncoupled package backwards compatibility
- [x] Coupled package creation with `breach_inflow.bc`, `.ext` reference, and manifest provenance
- [x] Complete REST API endpoint contract validation

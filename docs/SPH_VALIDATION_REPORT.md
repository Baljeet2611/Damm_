# SPH Hydrodynamic Simulation Validation Report

## Executive Summary

This report presents a thorough, scientifically honest audit and validation of the Smoothed Particle Hydrodynamics (SPH) solver currently implemented in the SIH dam-break / flood-simulation platform.

---

## 1. Solver Identity & Execution Architecture

| Audit Question | Verified Reality | Evidence / Details |
| :--- | :--- | :--- |
| **Official `pysph` package executed?** | **NO** | `import pysph` fails (`No module named 'pysph'`). The official PySPH C-extension compiler environment is not installed on this host. |
| **Actual Solver Implementation** | **Custom Terrain-SPH Prototype** | Fully vectorized depth-integrated Lagrangian SPH solver implemented natively in Python (`numpy` / `scipy.spatial.cKDTree` / `rasterio` / `pyproj`) inside `backend/app/sph_service.py`. |
| **Scientific Purpose** | **Prototype Demonstration** | Designed to demonstrate particle hydrodynamic concepts, real DEM elevation coupling, and automated Eulerian GeoTIFF rasterization within a localized demonstration domain ($3.44\text{ km} \times 2.50\text{ km}$). |
| **Engineering Status** | **Not Validated for Operational / Engineering Use** | Uncalibrated hydrodynamic prototype. Must not be used for official emergency planning or infrastructure safety decisions. |

---

## 2. Governing Physics & Approximation Audit

Every physics component of `backend/app/sph_service.py` is classified below as **IMPLEMENTED**, **APPROXIMATED**, or **MISSING**:

| Physics Component | Classification | Mathematical / Numerical Treatment |
| :--- | :--- | :--- |
| **Terrain Elevation ($z_{bed}$)** | **IMPLEMENTED** | Sampled directly from reprojected open-source SRTM `dem.tif` (UTM 43N / EPSG:32643) at every particle coordinate $(x_i, y_i)$. |
| **Bed Slope Driving Force** | **IMPLEMENTED** | Finite-difference topographic slope gradient $\nabla z_{bed} = \left(\frac{\partial z_{bed}}{\partial x}, \frac{\partial z_{bed}}{\partial y}\right)$ yielding gravitational acceleration $\vec{a}_{bed} = -g \nabla z_{bed}$. |
| **Particle Interactions** | **IMPLEMENTED** | Pairwise spatial neighbor search via `scipy.spatial.cKDTree.query_pairs(r = 2h)`. |
| **Smoothing Kernel** | **IMPLEMENTED** | Standard 2D SPH Cubic Spline kernel $W(r, h)$ with compact support radius $R = 2h = 65.0\text{ m}$ and analytic gradient $\nabla W$. |
| **Inter-Particle Pressure Force** | **APPROXIMATED** | Depth-difference hydrostatic pressure gradient: $\vec{f}_{ij} = g \bar{h}_{ij} (h_j - h_i) \nabla W_{ij}$. Symmetrical force summation guarantees momentum exchange. |
| **Bed Friction Resistance** | **APPROXIMATED** | Manning's bed shear deceleration: $\vec{a}_{fric} = -\frac{g n^2 \|\vec{u}\|}{h_i^{4/3} + 1.0} \vec{u}$ with $n = 0.035$. |
| **Viscosity & Turbulence** | **APPROXIMATED** | Numerical smoothing via kernel gradient filtering and velocity upper-bound clipping ($v_{max} \le 30.0\text{ m/s}$). Explicit sub-grid scale (SGS) turbulence tensor is omitted. |
| **Water Depth ($h$)** | **APPROXIMATED** | Depth-integrated 2D column representation with empirical dynamic spreading attenuation. Full 3D free-surface elevation tracking is not solved. |
| **Water-Surface Elevation ($H$)** | **APPROXIMATED** | Represented as $H(x, y) = z_{bed}(x, y) + h(x, y)$. |
| **Timestep & Integration** | **APPROXIMATED** | Fixed timestep $\Delta t = 0.05\text{ s}$ with symplectic velocity-position update. Max single-step displacement ($1.16\text{ m}$) remains well within $h = 32.5\text{ m}$. |
| **Wet / Dry Treatment** | **APPROXIMATED** | Threshold tracking: cells/particles are active fluid when $h \ge 0.5\text{ m}$; arrival tracked at $h \ge 0.05\text{ m}$. Zero-depth dry bed has no resistance singularities. |
| **Reservoir Initialization** | **APPROXIMATED** | Quiescent water column initialized on a regular grid ($\Delta x = 25\text{ m}$) upstream of dam axis with initial depth $h_0 = \max(Z_{pool} - z_{bed}, 0)$. |
| **Downstream Initialization** | **APPROXIMATED** | Initialized as completely dry bed ($h = 0$). |
| **Dam / Barrier Representation** | **MISSING** | **No physical solid barrier / wall.** Particles are released instantaneously without holding force. |
| **Breach Formation Dynamics** | **MISSING** | **No progressive breach erosion model** (Froehlich / MacDonald-Langridge-Monopolis breach widening is not simulated). |
| **Boundary Handling** | **MISSING** | Open demonstration domain boundaries without ghost particles or repulsive boundary potentials. |
| **Particle Escape Control** | **MISSING** | Particles exiting domain bounding box are untracked after simulation extent. |

---

## 3. Dam-Break & Breach Mechanism Investigation

### Is an actual dam barrier or breach represented?
**NO.** The current implementation executes an **instantaneous unconstrained gravity release**:
1. At $t = 0$, fluid particles are initialized in the reservoir basin upstream of the dam line ($x < X_{dam} - 10\text{ m}$).
2. There is **no solid wall, gate, or impermeable dam body** holding the fluid back at $t = 0$.
3. When the simulation begins, the fluid immediately collapses and surges eastward down the steep natural valley terrain slope under gravity and hydrostatic pressure gradients.
4. **Breach width, breach formation time, and breach growth rate are NOT modeled.**

---

## 4. Investigation of Extreme Reported Values

### Why did Maximum Depth reach ~26.0 m – 42.0 m?
- **Location**: Reservoir incised river thalweg upstream of the dam ($X = 461,795.1\text{ m}, Y = 1785,130.6\text{ m}$).
- **Elevation**: Bed elevation $z_{bed} = 624.0\text{ m}$.
- **Physics**: With reservoir pool level set to $650.0\text{ m}$ (or $666.0\text{ m}$ under maximum surcharge), the hydrostatic water depth is $h = Z_{pool} - z_{bed} = 650.0 - 624.0 = 26.0\text{ m}$ (or $42.0\text{ m}$).
- **Reason**: The maximum depth is an authentic hydrostatic consequence of the real SRTM DEM valley bathymetry in the deepest reservoir channel, **not a numerical instability or artifact**.

### Why did Maximum Velocity reach ~23.2 m/s – 27.6 m/s?
- **Location**: Downstream gorge slope, ~337 m east of dam axis ($X = 462,143.1\text{ m}, Y = 1784,830.6\text{ m}$).
- **Elevation**: Bed drops rapidly from $645.0\text{ m}$ to $621.0\text{ m}$ ($24\text{ m}$ drop over $150\text{ m}$, bed slope $S_0 > 0.16$).
- **Physics**: Theoretical Torricelli wave front speed on steep slope: $v \approx \sqrt{2 g \Delta z} \approx \sqrt{2 \times 9.81 \times 24} \approx 21.7\text{ m/s}$, supplemented by inter-particle pressure acceleration.
- **Reason**: The maximum velocity is confined strictly to the leading tip of the surge plunging down the steep gorge slope.

---

## 5. Statistical Distributions & Numerical Stability

### Statistical Percentiles

| Percentile | Water Depth ($h$) | Flow Velocity ($v$) |
| :--- | :--- | :--- |
| **P50 (Median)** | **3.00 m** | **0.00 m/s** (bulk reservoir remains quiescent) |
| **P90** | **4.00 m** | **0.03 m/s** |
| **P95** | **5.00 m** | **3.47 m/s** |
| **P99** | **12.00 m** | **18.38 m/s** |
| **MAX** | **26.00 m** | **23.23 m/s** (leading edge only) |

### Stability Metrics
- **Max Single-Step Displacement**: $1.161\text{ m}$ per step ($\Delta t = 0.05\text{ s}$).
- **SPH CFL Ratio**: $\frac{v_{max} \Delta t}{h_{smooth}} = \frac{23.23 \times 0.05}{32.5} = 0.0357 \ll 1.0$ (highly stable).
- **NaN / Inf Occurrences**: **0** (no numerical blowups).

---

## 6. Mass & Volume Conservation

| Diagnostic Parameter | Value |
| :--- | :--- |
| **Initial Active Particles ($N_0$)** | 953 particles |
| **Initial Estimated Water Volume** | $1,950,625.0\text{ m}^3$ |
| **Final Estimated Water Volume** | $1,936,359.8\text{ m}^3$ |
| **Relative Volume Error** | **-0.73%** |
| **Particles Escaping Domain** | 3 particles ($0.31\%$) |

---

## 7. Raster Postprocessing Validation

- **Output Files**: `maximum_depth.tif`, `maximum_velocity.tif`, `arrival_time.tif`.
- **CRS**: Projected metric `EPSG:32643` (UTM Zone 43N).
- **Spatial Bounds**: Tight bounding box covering the actual simulated particle extent ($+100\text{ m}$ safety margin).
- **NoData Masking**: Pixels farther than kernel support radius $R = 65\text{ m}$ from all particles evaluate strictly to `NoData = -9999.0`. Artificial inundation is **not created** outside the active simulated flow corridor.
- **Arrival Time**: Accurately records first time $t \ge 0$ when depth exceeds $0.05\text{ m}$.

---

## 8. Scientific Distinction & Appropriate Use

```
========================================================================
STATUS: DEMONSTRATION CAPABLE
========================================================================
This simulation demonstrates real DEM topography coupling, SPH particle
equations of motion, symplectic time integration, and automated Eulerian
rasterization.

It is NOT an engineering-validated dam-break safety study because:
1. Dam failure is modeled as instantaneous release, not progressive breach.
2. Domain is restricted to a near-field demonstration section (<5 km).
3. Fluid dynamics are 2D depth-integrated rather than full 3D Navier-Stokes.
========================================================================
```

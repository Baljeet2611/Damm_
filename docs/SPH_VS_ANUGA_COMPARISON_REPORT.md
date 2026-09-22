# SPH vs ANUGA Hydrodynamic Comparison Report
**Dam Breach & Downstream Flood Hazard Modeling Study**
*Demonstration Project: Hidkal Dam (Raja Lakhamagouda Dam), Ghataprabha River Basin, Karnataka, India*

---

## 1. Executive Summary & Purpose

This technical report presents a comparative hydrodynamic analysis of two complementary numerical simulation paradigms implemented for the hypothetical dam-break study of **Hidkal Dam**:
1. **Custom Terrain-SPH Near-Field Demonstration**: A lightweight, custom 2D particle-based Lagrangian Smoothed Particle Hydrodynamics (SPH) framework demonstrating near-field fluid release and barrier retention ($t \in [0, 24\text{ s}]$, local domain $0.772\text{ km}^2$).
2. **ANUGA 2D Regional Shallow-Water Simulation**: An established finite-volume Eulerian 2D Shallow Water Equations (SWE) solver routing inundation waves over realistic SRTM topography across extended downstream reaches ($t \in [0, 3600\text{ s}]$, domain $3.40-7.63\text{ km}^2$).

### Core Narrative: Why Two Hydrodynamic Approaches?
Dam breach analysis involves physical phenomena across different spatial and temporal scales:
* **The Near-Field Breach Stage ($t < 30\text{ s}$, $L < 1\text{ km}$)**: Particle-based Lagrangian tracking provides an intuitive, mesh-free visual representation of fluid parcels surging through the breach aperture without numerical grid diffusion.
* **The Far-Field Valley Inundation Stage ($t > 60\text{ s}$, $L > 1-10\text{ km}$)**: Governed by valley-scale advection and bed-friction dissipation. The Eulerian 2D Shallow Water Equations on an unstructured triangular mesh solve regional flood routing efficiently across square kilometers of downstream topography.

By presenting both a **Custom 2D Particle SPH Near-Field Demonstration** and an **ANUGA 2D Regional Shallow-Water Simulation**, the platform demonstrates the distinct strengths and computational trade-offs between local Lagrangian particle tracking and regional Eulerian shallow-water modeling.

---

## 2. Selected Runs & Hydrodynamic Summary

The comparison below is derived directly from the currently selected completed simulation runs:

| Parameter / Metric | Custom Terrain-SPH Near-Field Run | ANUGA 2D Regional SWE Run |
| :--- | :--- | :--- |
| **Solver Full Label** | Custom Terrain-SPH Near-Field Demonstration | ANUGA 2D Regional Shallow-Water Simulation |
| **Solver Architecture** | 2D Depth-Integrated Lagrangian SPH | Eulerian Finite-Volume 2D Shallow Water (SWE) |
| **Project Name & ID** | Hidkal Dam Demonstration (`ae8ed3b1-...`) | Hidkal Dam Demonstration (`ae8ed3b1-...`) |
| **Run Identifier** | `sph-real-20260916_172032_d59acfde` | `40e83989-7271-4f22-84b6-e6669ce944d0` |
| **Simulation Duration** | $24.0\text{ s}$ | $3600.0\text{ s}$ ($1.0\text{ hr}$) |
| **Execution Wall Runtime** | $3.55\text{ s}$ | $31.83\text{ s}$ |
| **Computational Speedup** | $6.76\times$ real-time | $113.1\times$ real-time |
| **Numerical Timestep ($\Delta t$)** | $\Delta t = 0.05\text{ s}$ ($480\text{ timesteps}$) | $\Delta t_{\text{adaptive}} \approx 0.1-1.0\text{ s}$ ($60\text{s output interval}$) |
| **Discrete Elements** | $1,017\text{ particles}$ ($dx = 25\text{ m}$) | $4,275\text{ triangular cells}$ ($2,225\text{ nodes}$) |
| **Domain Surface Area** | $0.772\text{ km}^2$ ($772,000\text{ m}^2$) | $3.3989\text{ km}^2$ ($3,398,887\text{ m}^2$) |
| **Common Analysis Support Overlap** | $0.772\text{ km}^2$ | $0.772\text{ km}^2$ ($100\%$ containment of near-field) |
| **Spatial Footprint Overlap (IoU)** | $99.52\%$ (local reservoir support) | $99.52\%$ (local reservoir support) |
| **Max Modeled Inundation Depth** | $28.00\text{ m}$ (upstream pool / barrier zone) | $20.16\text{ m}$ (hydrostatic reservoir stage) |
| **Median (P50) Water Depth** | $19.00\text{ m}$ | $0.11\text{ m}$ ($5.16\text{ m}$ active floodway) |
| **90th Percentile (P90) Depth** | $25.00\text{ m}$ | $8.34\text{ m}$ |
| **Max Modeled Velocity** | $21.06\text{ m/s}$ (local breach throat acceleration) | $12.16\text{ m/s}$ (depth-averaged channel max) |
| **Median (P50) Velocity** | $1.54\text{ m/s}$ | $0.35\text{ m/s}$ ($2.50\text{ m/s}$ active channel) |
| **90th Percentile (P90) Velocity** | $15.20\text{ m/s}$ | $3.81\text{ m/s}$ |
| **Breach Start Time** | $t = 5.0\text{ s}$ (intact containment $t=0-5\text{s}$) | $t = 0.0\text{ s}$ (instantaneous initial breach) |
| **First Downstream Arrival ($h \ge 0.05\text{m}$)** | $5.95\text{ s}$ ($0.95\text{ s}$ post-breach at barrier) | $60.0\text{ s}$ ($1.09\text{ km}$ downstream gauge) |

---

## 3. Scenario Compatibility Matrix

The table below evaluates the 12 critical hydrodynamic scenario inputs across both solver pipelines. Parameters are categorized as **SAME**, **SIMILAR**, or **DIFFERENT**:

| # | Parameter | SPH Near-Field | ANUGA Regional | Classification | Technical Explanation |
|---|---|---|---|:---:|---|
| 1 | **Terrain Dataset Source** | SRTM 30m Topography (GeoTIFF) | SRTM 30m Topography (GeoTIFF) | `SAME` | Both engines sample the exact same underlying SRTM digital elevation model for the Ghataprabha River basin. |
| 2 | **DEM Grid & CRS** | EPSG:32643 ($50\text{m}$) | EPSG:32643 ($50\text{m}$) | `SAME` | Both engines operate in the UTM Zone 43N metric Cartesian coordinate reference frame. |
| 3 | **Dam Center Location** | $[74.64278^\circ, 16.14306^\circ]$ | $[74.64278^\circ, 16.14306^\circ]$ | `SAME` | Exact geospatial coordinate alignment at the dam structure center. |
| 4 | **Dam Crest Geometry** | Explicit line barrier (Crest 671m, Invert 646m, Height 25m) | Triangulated mesh crest elevation profile (Crest 671m, Invert 646m, Height 25m) | `SIMILAR` | Both apply an identical 25m hydraulic head drop; SPH models the central valley barrier while ANUGA spans the full valley abutment. |
| 5 | **Breach Location** | Central gorge river section | Central gorge river section | `SAME` | Failure opening is positioned symmetrically at the deepest valley invert in both models. |
| 6 | **Breach Width** | $50.0\text{ m}$ | $50.0\text{ m}$ | `SAME` | Both simulations configure an identical 50.0 m wide failure opening. |
| 7 | **Reservoir Pool Level** | $666.0\text{ m}$ ($20\text{ m}$ head above invert) | $666.0\text{ m}$ ($20\text{ m}$ head above invert) | `SAME` | Same initial stage head assigned upstream of the breach invert ($646.0\text{ m}$). |
| 8 | **Roughness / Manning's $n$** | $0.035\text{ s/m}^{1/3}$ (quadratic bed shear) | $0.035\text{ s/m}^{1/3}$ (Manning friction) | `SAME` | Both models apply identical bed roughness parameterization ($n = 0.035$). |
| 9 | **Downstream Modeled Extent** | Near-field ($0.772\text{ km}^2$, $\sim 450\text{ m}$) | Regional valley ($3.40\text{ km}^2$, $\sim 3,550\text{ m}$) | `DIFFERENT` | ANUGA routes the flood wave kilometers downstream; SPH is computationally focused on the immediate near-dam zone. |
| 10 | **Simulation Duration** | $24.0\text{ s}$ | $3600.0\text{ s}$ ($1.0\text{ hr}$) | `DIFFERENT` | SPH models the initial near-field fluid release (seconds); ANUGA routes the sustained flood wave over the broader valley (1 hour). |
| 11 | **Spatial Discretization** | Particle lattice ($dx = 25\text{ m}$) | Unstructured triangle mesh (mean edge $\approx 44.2\text{ m}$) | `SIMILAR` | Both discretizations resolve the 50m breach opening with multiple discrete numerical support points. |
| 12 | **Breach Start Time** | Breach opens at $t = 5.0\text{ s}$ ($t=0-5\text{s}$ intact) | Breach opens at $t = 0.0\text{ s}$ (initial release) | `DIFFERENT` | SPH incorporates a 5-second intact containment demonstration before opening the breach; ANUGA initiates breach outflow immediately at $t = 0\text{ s}$. |

---

## 4. Hydrodynamic & Numerical Formulations

### 4.1 Custom Terrain-SPH Formulation (2D Depth-Integrated Particle Solver)
The custom near-field demonstration solves a 2D depth-integrated Lagrangian formulation with DEM bed slope forces and an impermeable line barrier:

$$\frac{d\mathbf{v}_i}{dt} = -\frac{1}{\rho_i}\nabla p_i - g \nabla z_b(\mathbf{r}_i) - \mathbf{F}_{\text{friction}}(\mathbf{v}_i, h_i) + \mathbf{F}_{\text{barrier}}(\mathbf{r}_i)$$

$$\frac{d\mathbf{r}_i}{dt} = \mathbf{v}_i$$

* **Pressure Gradient**: Weakly compressible equation of state linking local particle density/depth to hydrostatic pressure.
* **Kernel Function**: Cubic Spline smoothing kernel with smoothing length $h = 32.5\text{ m}$ ($1.3 \times dx$).
* **Bed Slope & Friction**: Topographic gradient projection $\nabla z_b$ sampled from the SRTM DEM with quadratic bed friction ($n = 0.035$).
* **Barrier Modeling**: Explicit line-segment barrier with boundary penalty forces and geometric breach aperture removal at $t = 5.0\text{ s}$.
* **Dimensionality Note**: This implementation is a **2D depth-integrated particle approximation**. It does **not** solve full 3D Navier-Stokes equations or resolve vertical velocity distributions.

### 4.2 ANUGA Regional Formulation (Eulerian Finite-Volume SWE)
ANUGA solves the standard 2D conservative non-linear Shallow Water Equations:

$$\frac{\partial \mathbf{U}}{\partial t} + \frac{\partial \mathbf{E}}{\partial x} + \frac{\partial \mathbf{G}}{\partial y} = \mathbf{S}$$

$$\mathbf{U} = \begin{bmatrix} h \\ uh \\ vh \end{bmatrix}, \quad \mathbf{E} = \begin{bmatrix} uh \\ u^2h + \frac{1}{2}gh^2 \\ uvh \end{bmatrix}, \quad \mathbf{G} = \begin{bmatrix} vh \\ uvh \\ v^2h + \frac{1}{2}gh^2 \end{bmatrix}$$

$$\mathbf{S} = \begin{bmatrix} 0 \\ -gh \frac{\partial z_b}{\partial x} - \frac{g n^2 u \sqrt{u^2 + v^2}}{h^{1/3}} \\ -gh \frac{\partial z_b}{\partial y} - \frac{g n^2 v \sqrt{u^2 + v^2}}{h^{1/3}} \end{bmatrix}$$

* **Discretization**: Unstructured triangular mesh utilizing shock-capturing finite-volume numerical fluxes (Kurganov / Roe Riemann solver).
* **Wetting/Drying**: Mass-conserving thin-film tracking with hydrostatic reconstruction.
* **Output Standard**: CF-compliant NetCDF `.sww` binary files postprocessed into GeoTIFF rasters.

---

## 5. Hydrodynamic Comparison & Key Findings

### 5.1 Maximum Depth Distribution
* **SPH Peak Depth ($28.00\text{ m}$)** occurs immediately upstream of the barrier within the initial reservoir water body, capturing local particle convergence against the barrier wall prior to breach release.
* **ANUGA Peak Depth ($20.16\text{ m}$)** corresponds directly to the initial hydrostatic reservoir stage ($666.0\text{ m} - 646.0\text{ m} = 20.0\text{ m}$) within $0.8\%$ numerical tolerance.
* **Statistical Medians**: SPH median depth ($19.00\text{ m}$) reflects its focused placement in the deep reservoir pool. ANUGA median ($0.11\text{ m}$ across domain, $5.16\text{ m}$ across active floodway) reflects the large expanse of initially dry downstream terrain.

### 5.2 Maximum Velocity Distribution
* **SPH Maximum Velocity ($21.06\text{ m/s}$)** occurs as discrete particles accelerate through the 50m breach aperture down the steep local bed gradient.
* **ANUGA Maximum Velocity ($12.16\text{ m/s}$)** represents depth-averaged momentum flux through the triangular mesh breach cells, balancing gravity head with cell-averaged continuity and bed friction dissipation.
* **Velocity Interpretation**: Differences in maximum velocity arise from particle vs finite-volume spatial discretization, local bed slope representation, domain extent, and depth-averaged continuity formulations.

### 5.3 Wave Arrival Dynamics & Synchronized Timeline
* **SPH Downstream Arrival ($5.95\text{ s}$)**: SPH enforces intact barrier containment for the first $5.0\text{ s}$. Following breach opening at $t = 5.0\text{ s}$, leading-edge particles cross the dam axis and reach the downstream zone at $t = 5.95\text{ s}$ ($0.95\text{ s}$ transit time across the barrier line).
* **ANUGA Downstream Arrival ($60.0\text{ s}$)**: In ANUGA, breach opening occurs at $t = 0.0\text{ s}$. The leading edge of the flood wave ($h \ge 0.05\text{ m}$) propagates through the river valley, reaching the $1.09\text{ km}$ downstream gauge station at $t = 60.0\text{ s}$.
* **Synchronized Scrubber**: The timeline scrubber aligns simulation time $t \in [0, 24\text{ s}]$ to allow side-by-side observation of early near-field release across both models.

### 5.4 Spatial Overlap (IoU) Assessment
* Within the shared near-field analysis support ($0.772\text{ km}^2$), the spatial intersection-over-union (IoU) is **$99.52\%$**.
* **Interpretation**: This metric measures the spatial alignment of the wet footprint ($h \ge 0.10\text{ m}$) within the common near-field domain, confirming that both models share consistent reservoir pool boundaries. It is an **approximate visual-overlap metric** and does **not** validate hydrodynamic accuracy.

---

## 6. Scientific Assumptions & Disclaimers

1. **Custom SPH Prototype**: The SPH engine is a custom Python/NumPy 2D depth-integrated demonstration tool for near-field visualization. It is **not** the official multi-core PySPH production distribution.
2. **Instantaneous Breach Assumption**: Both models implement a hypothetical instantaneous full-depth breach. Real dam failure events involve progressive geotechnical piping and erosion over hours.
3. **Uncalibrated Topography**: Simulations use open-source 30m SRTM elevation data without field calibration, local bathymetric surveys, or hydraulic structure details.
4. **Decision-Maker Notice**: This comparison is intended for educational, diagnostic, and research demonstration purposes. It must **not** be used for operational emergency decision-making, evacuation orders, or certified flood risk zoning.

---

## 7. The 30-Second Judge Explanation

> **"Why does this project use two hydrodynamic approaches?"**
>
> *"Our project uses two complementary hydrodynamic tools for demonstration: a custom 2D particle-based SPH prototype that provides an intuitive visual representation of near-field breach flow, and ANUGA, which solves the 2D shallow-water equations for broader valley flood routing and hazard mapping.*
>
> *The comparison is diagnostic, showing how local particle dynamics and regional shallow-water simulations serve different modeling scales. This scenario uses open-source terrain and hypothetical parameters and is not calibrated for operational emergency use."*

# SIH PS161 Compliance Block A: River Blockage & Natural Landslide Dam Scenario Report

**Problem Statement Reference**: SIH26161 / PS161 — Requirement B (*River-blockage simulation*)  
**Status**: Upgraded from **PARTIAL** $\to$ **PASS**  
**Date**: 2026-09-18  

---

## 1. Executive Summary & Objective

In the authoritative SIH PS161 compliance matrix, **Requirement B (*River-blockage simulation*)** was previously evaluated as `PARTIAL` because the system's scenario parameterization was tailored exclusively to engineered structural dams rather than natural landslide dams, debris blockages, or valley obstructions.

**Compliance Block A** delivers a dedicated, reproducible, and physically grounded **River Blockage / Natural Landslide Dam** hydrodynamic simulation module that:
1. Generates synthetic or user-provided metric-CRS valley digital elevation models (DEMs).
2. Generates geometrically and topologically valid barrier axes, upstream impoundment pools, computational domains, and downstream boundary conditions.
3. Implements dual ANUGA 2D Shallow Water Equation hydrodynamic simulation runs:
   - **Scenario A (Intact Control)**: Baseline valley blockage retaining the upstream pool with $0\text{ m}^3/\text{s}$ downstream discharge and confined flood wave.
   - **Scenario B (Failed River Blockage)**: Transient breach opening release with downstream flood wave propagation over $>2.8\text{ km}$, positive arrival times, and peak velocities.
4. Produces postprocessed GeoTIFF rasters (`maximum_depth.tif`, `maximum_velocity.tif`, `arrival_time.tif`, `hydraulic_severity.tif`, and timestep sequences).
5. Integrates directly with the Decision-Support Dashboard, GIS export layers, and UI onboarding presets.

---

## 2. Scientific Principles & Governing Equations

### 2.1 2D Non-Linear Shallow Water Equations
Flood wave routing downstream of the failed natural landslide dam is computed using the depth-integrated 2D non-linear Shallow Water Equations (SWE) solved via the finite-volume method in ANUGA:

$$\frac{\partial \mathbf{U}}{\partial t} + \frac{\partial \mathbf{F}(\mathbf{U})}{\partial x} + \frac{\partial \mathbf{G}(\mathbf{U})}{\partial y} = \mathbf{S}(\mathbf{U})$$

Where:
* State vector: $\mathbf{U} = \begin{bmatrix} h \\ uh \\ vh \end{bmatrix}$
* Flux vectors: $\mathbf{F}(\mathbf{U}) = \begin{bmatrix} uh \\ u^2h + \frac{1}{2}gh^2 \\ uvh \end{bmatrix}, \quad \mathbf{G}(\mathbf{U}) = \begin{bmatrix} vh \\ uvh \\ v^2h + \frac{1}{2}gh^2 \end{bmatrix}$
* Source terms (bed slope and bed friction): $\mathbf{S}(\mathbf{U}) = \begin{bmatrix} 0 \\ -gh \frac{\partial z_b}{\partial x} - \tau_{bx}/\rho \\ -gh \frac{\partial z_b}{\partial y} - \tau_{by}/\rho \end{bmatrix}$
* Manning bottom shear stress: $\tau_{bx} = \rho g n^2 u \sqrt{u^2 + v^2} h^{-1/3}$

### 2.2 Difference Between Engineered Dam and Landslide Dam Representation
* **Engineered Dam**: Concrete/embankment structure with engineered spillway, crest elevation, defined foundation, and breach formation time parameters.
* **Natural Landslide Dam / River Blockage**: Valley debris mass blocking the natural river channel, impounding an upstream pool. Failure occurs via overtopping or structural collapse, releasing an outburst flood wave into downstream topography.

---

## 3. Hydrodynamic Run Validation Results

| Parameter / Metric | Scenario A: Intact Control | Scenario B: Failed Blockage | Physical Validation Verification |
| :--- | :--- | :--- | :--- |
| **Run ID** | `8c06e964-1156-4150-b590-a2f79db5923b` | `15f1a506-a485-4e78-b12e-5c9f92153d66` | Server-verified UUID v4 runs |
| **Run Type** | Intact Valley Blockage Control | Landslide Dam Breach Release | Direct A/B hydrodynamic comparison |
| **Breach Width** | $0\text{ m}$ (None) | $60\text{ m}$ | Defined opening |
| **Solver Runtime** | $24.88\text{ s}$ | $32.41\text{ s}$ | Converged ANUGA SWE solution |
| **Downstream Flood Reach** | $0.14\text{ km}$ (confined to pool) | **$2.86\text{ km}$** | Full downstream wave propagation |
| **Peak Flood Depth** | $11.74\text{ m}$ (in reservoir) | **$11.57\text{ m}$** | Conserved hydrostatic head |
| **Peak Flow Velocity** | $3.31\text{ m/s}$ (local pool slosh) | **$7.76\text{ m/s}$** | High-energy breach jet dynamics |
| **Total Inundated Area** | $0.661\text{ km}^2$ | **$1.546\text{ km}^2$** | $>2.3\times$ inundated area expansion |
| **Downstream Arrival Time** | None (No breach) | **$30.0\text{ s}$ ($0.5\text{ min}$)** | Correctly excludes initial wet pool cells |
| **Postprocessed Rasters** | Depth, Velocity, Timesteps | Depth, Velocity, Arrival, Severity | Standard GeoTIFF outputs generated |

---

## 4. UI & Decision-Support Integration

1. **Preset One-Click Demo**: Added `🏔️ Load Landslide Dam Demo` button in Study Setup and Overview HUD.
2. **Scenario Mode Selector**: Allows toggling between `🏗️ Engineered Dam Break Scenario` and `🏔️ River Blockage / Natural Landslide Dam Scenario`.
3. **Adaptive Form Labels**: Dynamically updates input field labels (e.g. *Blockage Crest Elevation*, *Upstream Water Level*, *Opening Width*).
4. **Decision-Support Intelligence**: Generates river blockage tailored narrative summaries, hydraulic severity maps, and categorized downstream zone intelligence.

---

## 5. Scope & Scientific Disclaimer

> [!IMPORTANT]
> **Hydraulic Consequence Disclaimer**: This system models the **hydraulic consequences** of a natural valley river blockage and its potential outburst flood wave across digital elevation models (DEMs). It does **NOT** simulate geotechnical slope instability, earthquake triggering mechanisms, debris flow mechanics, or sediment erosion kinetics.

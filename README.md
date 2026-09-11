# Dam Break Decision Support System (SIH 26161)

Automated multi-engine hydrodynamic simulation, satellite cross-validation, and decision-support framework for dam-break inundation screening.

---

## Quick Start (Automated Safe Startup)

To check prerequisites, inspect network ports, and safely launch both the FastAPI backend and Vite frontend dev server:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-dev.ps1
```

- **Frontend Application**: `http://127.0.0.1:5173`
- **Backend API Documentation**: `http://127.0.0.1:8000/docs`
- **System Health Status HUD**: `http://127.0.0.1:8000/api/system/health-summary`

---

## Environment Setup & Prerequisites

### Prerequisites
- **Node.js**: v20+ and npm
- **Conda**: Miniforge or Anaconda on Windows

### 1. Main Application Environment (`sih-app`)
Contains FastAPI, GDAL, Rasterio, Shapely, PyProj, GeoPandas, and Pytest.
```powershell
conda env create -f environment.yml
conda activate sih-app
```

### 2. Optional ANUGA Solver Environment (`sih-anuga`)
Required only for executing live 2D hydrodynamic finite-volume SWE simulations locally.
```powershell
conda env create -f environment-anuga.yml
```

> [!NOTE]
> **Separation of Discovery & Execution Permission (Phase 23)**:
> The system automatically discovers installed ANUGA interpreters across standard Conda paths. However, solver execution permission remains **strictly disabled by default** (`ENABLE_CUSTOM_ANUGA_EXECUTION=false`) to prevent accidental solver execution.
> To enable execution during demonstration or development:
> ```powershell
> $env:ENABLE_CUSTOM_ANUGA_EXECUTION="true"
> ```

### 3. Optional Google Earth Engine (GEE)
The core application runs 100% offline without GEE. When `earthengine-api` or credentials are not configured, the System Health HUD truthfully reports `Available but not configured`, allowing simulation, exposure, and comparison tools to operate without disruption.

---

## System Verification & Smoke Testing

To execute a complete audit of all environments, static analysis, full test suite, and production build:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify-system.ps1
```

To run the dedicated ANUGA real solver engineering smoke test (evolving an ANUGA domain, producing SWW, and validating GeoTIFF postprocessing):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run-smoke-tests.ps1
```

---

## Product Workflow Stages

The application organizes dam safety workflows into 8 logical, user-facing stages:

1. **🌐 Overview**: System Health HUD chips and inventory of registered dam studies.
2. **🏗️ Study Setup**: Ingest custom terrain DEM GeoTIFFs, define dam location coordinates, and parameterize structural characteristics.
3. **⚡ Simulation**: Pre-simulation 5-tier readiness assessment, mesh generation parameters, gated ANUGA runner with live execution logs, and hazard rasters (depth, velocity, arrival time).
4. **🛰️ Satellite Evidence**: Sentinel-1 SAR acquisition timeline, backscatter thresholding, and model vs. observation flood extent comparison.
5. **⚖️ Model Comparison**: Multi-engine spatial comparison (ANUGA vs. Delft3D FM vs. PySPH) with difference maps, inter-model spread, and metric tables.
6. **👥 Exposure & Impact**: Mass-conserving population exposure, building footprint intersections, segmented road network disruption, critical facilities screening, and LULC cross-tabulation.
7. **🎯 Decision Support**: Evacuation corridor accessibility, warning lead-time timelines, impact severity matrix, and executive briefing downloads.
8. **📜 Technical / Provenance**: Cryptographic manifest SHA-256 validation, vulnerability curve provenance (Huizinga et al., 2017 EUR 28552 EN; `unverified_reference`), and scientific governing assumptions.

---

## API Reference Summary

- System Health Summary: `GET http://localhost:8000/api/system/health-summary`
- Datasets Catalog: `GET http://localhost:8000/api/datasets`
- Dam Projects Management: `GET / POST http://localhost:8000/api/dam-projects`
- Project Simulation Readiness: `GET http://localhost:8000/api/dam-projects/{id}/readiness`
- ANUGA Capabilities & Runs: `GET / POST http://localhost:8000/api/dam-projects/{id}/anuga/capabilities`, `runs`
- Earth Observation Studio: `GET / POST http://localhost:8000/api/dam-projects/{id}/earth-observation/runs`
- Model Comparison Studio: `GET / POST http://localhost:8000/api/dam-projects/{id}/model-comparison/runs`
- Exposure & Vulnerability: `GET / POST http://localhost:8000/api/dam-projects/{id}/exposure/runs`


### Registered Dataset IDs
- `dem` -> `data/raw/data_hidkal/hidkal_dem.tif` (Float32 DEM)
- `depth` -> `data/raw/data_hidkal/hidkal_depth.tif` (Float32 Inundation Depth; zero is transparent)
- `velocity` -> `data/raw/data_hidkal/hidkal_velocity.tif` (Float32 Velocity; zero is transparent)
- `arrival` -> `data/raw/data_hidkal/hidkal_arrival.tif` (Float32 Arrival Time; `+9999` and `-9999` treated as NoData & transparent)
- `assets` -> `data/raw/data_hidkal/hidkal_assets.geojson` (513 OSM infrastructure assets)
- `roads` -> `data/raw/data_hidkal/hidkal_roads.graphml` (3,084 nodes, 8,047 road edges)

### Scenario Management & Snapshot Module (Phase 10)
- Persistent local scenario storage under runtime directory (`SIH_RUNTIME_DIR`), secured against filesystem traversal via UUID v4 validation and atomic JSON replacement.
- Parametric modeling fields: breach geometry (width, formation time), reservoir pool level, boundary descriptors, Manning friction $n$, flexible mesh cell size, run duration, and computational timestep.

### Hydrodynamic Solver Validation (Phase 14)
- Genuine numerical shallow-water solver execution via **ANUGA** finite-volume framework in isolated conda environment `sih-anuga`.
- Idealized 2D dry-bed rectangular channel dam-break benchmark (`validation/anuga_dam_break/`).
- Validated against the **Ritter (1892)** analytical exact solution:
  - Centerline Depth RMSE: **0.0480 m** (MAE: **0.0308 m**).
  - Relative Volume Conservation Error: **0.00e+00** (exact mass conservation).
  - Execution Time: **6.65 s** for $T=40\text{ s}$ dynamic integration.
  - Reproducible runner (`run_benchmark.py`), summary (`benchmark_summary.json`), and cryptographic checksum manifest (`manifest.json`).

### ANUGA Regional Hydrodynamic Pilot & Refined Model (Phase 15, 16 & 17)
- **Scientific Status**: *Hypothetical refined ANUGA pilot — not a forecast or validated Hidkal prediction.* Vertical datum and DEM elevation units remain assumed based on source interpretation.
- **Resolution Levels Rigorously Distinguished**:
  1. *Numerical Mesh Resolution*: Unstructured adaptive mesh ($\le 50\text{ m}$ breach/channel zone, $\le 100\text{ m}$ corridor, $\le 200\text{ m}$ outer domain, $131,351$ triangles, $65,941$ vertices; 11 crossing edges / 10 discrete intervals across 200 m breach opening; measured edge lengths: min $28.91\text{ m}$, median $43.36\text{ m}$, $p_{95}$ $60.99\text{ m}$, max $93.75\text{ m}$).
  2. *Exported Visualization Grid*: $50\text{ m}$ regular GeoTIFF rasters ($442 \times 600$, $265,200$ cells) in EPSG:32643 UTM Zone 43N. Outer domain areas are supported by $100\text{--}200\text{ m}$ mesh elements and contain nearest/linear interpolation.
  3. *Interpolated Display Rendering*: Smooth bilinear resampling for continuous depth and velocity with crisp transparent dry/NoData masks; nearest-neighbour for arrival time. High visual quality does **not** increase underlying physical accuracy.
- **Baseline (Phase 15) vs Refined (Phase 17) Volume-Matched Mesh Sensitivity**:
  - Initial Stored Volume Match: Baseline = **317.161860 MCM** ($317,161,860.23\text{ m}^3$) vs Refined = **317.161857 MCM** ($317,161,857.32\text{ m}^3$), agreeing within **0.0000009%** via documented $-0.356572\text{ m}$ numerical stage adjustment ($659.643428\text{ m}$).
  - Inundated Extent IoU ($h \ge 0.10\text{ m}$): **0.7842** (Refined Area: **54.81 km²** vs Baseline: **44.47 km²**; $\Delta = +10.34\text{ km}^2$ via `rasterio.warp.reproject` with transform-derived $0.009922\text{ km}^2$ cell area).
  - Depth Errors on Common Inundated Area: MAE = **0.9146 assumed m**, RMSE = **1.2766 assumed m**, Mean Bias = **+0.0820 assumed m**.
  - Velocity Errors on Common Inundated Area: MAE = **0.6291 assumed m/s**, RMSE = **0.8249 assumed m/s**, Mean Bias = **+0.1385 assumed m/s**.
  - Peak Extrema: Depth = **25.633 assumed m** (Refined) vs **25.898 assumed m** (Baseline); Velocity = **15.772 assumed m/s** (Refined) vs **11.638 assumed m/s** (Baseline).
  - Peak Breach Discharge: Baseline $\approx 9,794.37\text{ assumed m}^3/\text{s}$ vs Refined $\approx 21,953.43\text{ assumed m}^3/\text{s}$ at $t = 300\text{ s}$ (approximate, not directly comparable due to 1-cell [one $200\text{ m}$ structured cross-mesh cell represented by four triangles and five vertices] vs 10-interval spatial discretization; numerical convergence is not demonstrated).
  - Non-Breach Embankment Leakage: Instantaneous rate = **0.0 assumed m³/s**; Cumulative leakage = **0.0 assumed m³** (time-integrated rate over $1,800\text{ s}$ via trapezoidal rule across the $675.0\text{ m}$ impermeable crest).
  - Exposure Screening Differences ($h \ge 0.10\text{ m}$): Assets exposed = **8** (Baseline) vs **62** (Refined), $\Delta = +54$; Screening-positive road segments (depth $\ge 0.10$ assumed metres) = **108** (Baseline) vs **128** (Refined), $\Delta = +20$. (At unthresholded $h > 0.00\text{ m}$, baseline exposes 29 assets due to 21 sub-threshold shallow assets with $0.02\text{--}0.09\text{ m}$ depth).
  - Full reproducible toolchain (`validation/anuga_hidkal_refined/run_anuga_refined.py`, `postprocess_refined.py`), summary (`pilot_summary.json`), GeoTIFF exports, and cryptographic manifest (`manifest.json`).
- **Hazard Source Switcher**: Frontend UI and all backend APIs seamlessly switch between `sample_hidkal`, `anuga_hidkal_pilot`, and `anuga_hidkal_refined` with complete state purging and provenance inspection.

### Generalized Dam / River Ingestion (Phase 18)
- **Minimal Generalized Onboarding**:
  - Ingestion of arbitrary dams using only `project_name`, `dam_name`, `latitude`, `longitude` (WGS84 decimal degrees), and a DEM GeoTIFF (`dem_file`).
  - Strict decoupling from vector requirements: Dam axis boundary polyline is now optional. When omitted, the system generates a synthesized dam point marker and allows regional terrain screening.
  - Optional Engineering Parameters: Accepts `dam_height`, `crest_elevation`, `pool_elevation`, and `manning_n`, automatically validating physical feasibility (`crest_elevation > pool_elevation`) and computing `freeboard`.
  - Automatic Point Sampling: Interrogates DEM elevation at the dam coordinates upon upload and records sampled elevation.
  - Pre-Simulation Readiness Assessment: Detailed checklist endpoint (`GET /api/dam-projects/{id}/readiness`) clearly delineates whether a project is ready for basic terrain/hazard screening vs. what components are required before ANUGA hydrodynamic simulation can run (e.g., dam axis geometry, reservoir stage-storage, simulation boundary, downstream Manning's n).
  - Dynamic DEM Legend & Value Probe: Interactive elevation color ramp endpoint (`GET /api/dam-projects/{id}/dem/legend`), dam marker GeoJSON endpoint (`GET /api/dam-projects/{id}/geometry/dam-marker`), and point sampling endpoint (`GET /api/dam-projects/{id}/dem/value`).
  - Strict Scientific Integrity: All newly ingested projects enforce `scientific_status = "validated_unverified"` and `scientifically_verified = false`.
  - Frontend Onboarding Studio: Guided tabbed wizard with interactive map preview, dam marker pin, readiness status badges, and project inspection list.

### Live ANUGA Execution for Generalized Dam Projects (Phase 19)
- **Multi-Environment Capability Discovery**:
  - Gated discovery endpoint (`GET /api/dam-projects/anuga/capabilities`) detecting active Python executable, ANUGA importability, version provenance, and execution enable/disable state (`ENABLE_CUSTOM_ANUGA_EXECUTION`).
  - Strict absence of single-developer hardcoded paths; cleanly probes host environments without crashes.
- **5-Tier Progressive Simulation Readiness Model**:
  - `GET /api/dam-projects/{id}/readiness` provides full `tier_breakdown`:
    1. **Data Tier** (`data_ready`): DEM raster valid, single-band, valid coordinate bounds, dam point location.
    2. **Geometry Tier** (`geometry_ready`): Dam axis line, downstream corridor / domain boundary, downstream outlet point.
    3. **Hydraulic Tier** (`hydraulic_ready`): Upstream reservoir boundary, initial stage pool elevation, breach location & dimensions, downstream Manning's n.
    4. **Solver Tier** (`solver_ready`): Target mesh resolution, duration, timestep, solver numerical stability parameters.
    5. **Simulation Tier** (`simulation_ready`): Composite verification requiring Tiers 1-4 + active ANUGA engine availability.
- **Terrain-Heuristic Hydraulic Assist & Scientific Integrity**:
  - DEM slope gradient aspect derivation at dam marker location computes candidate dam axis, breach cut, downstream corridor, outlet point, and upstream reservoir boundary (`POST /api/dam-projects/{id}/heuristic-assist`).
  - Topological safety guarantee: reservoir boundary is strictly contained within the model domain polygon and touches the dam axis.
  - Strict scientific tagging: All inferred parameters are tagged `source="terrain_heuristic"`, `scientifically_verified=false`, and `confidence="low_unverified"`.
  - Safeguarded saving: `POST /api/dam-projects/{id}/simulation-inputs` enforces `accept_heuristic_inputs=True` and updates `project.json` and cryptographic `manifest.json`.
- **Reproducible ANUGA Package Generator**:
  - Generates downloadable ZIP archive (`GET /api/dam-projects/{id}/anuga/download-package`) containing `run_anuga_project.py`, `postprocess_project.py`, cryptographic parameter snapshot `run_manifest.json`, standalone `environment.yml`, input geometries, and scientific caveats in `README_REQUIREMENTS.txt`.
- **7-State Execution Lifecycle & Solver Gating**:
  - Full execution state machine: `queued`, `preparing`, `running`, `postprocessing`, `completed`, `failed`, `cancelled`, `timed_out`, `interrupted`.
  - Gated execution: Requires user acknowledgment (`acknowledge_hypothetical_simulation=True`). Returns HTTP 403 `custom_anuga_execution_disabled` when host environment lacks ANUGA, preventing fabricated outputs.
  - Live log streaming (`GET /api/dam-projects/{id}/anuga/runs/{run_id}/logs`) and run cancellation (`POST /api/dam-projects/{id}/anuga/runs/{run_id}/cancel`).
- **Rigorous Output Validation**:
  - `validate_sww_file` verifies NetCDF structure, minimum 2 timesteps, finite values, and non-zero hydrodynamic depth (`max(stage - elevation) > 0.0001 m`).
  - Generates verified peak depth, velocity, and arrival GeoTIFFs, with outputs inspection via `GET /api/dam-projects/{id}/anuga/runs/{run_id}/outputs`.
- **Frontend Decision-Support UI**:
  - `DamProjectAnugaReadiness.tsx` integration with 5-Tier Readiness badges HUD, Terrain-Heuristic Assist accordion, runtime parameter controls, cancellation controls, and hazard layer viewer.

### Live Google Earth Engine & Remote-Sensing Integration (Phase 20)
- **Zero-Fabrication Fallback & Capability Detection**:
  - Dynamic discovery via `GET /api/gee/capabilities` inspecting ADC credentials and `GEE_PROJECT_ID`.
  - Truthful degradation when unauthenticated or GEE is missing: returns status `gee_unavailable`, `authentication_required`, or `project_not_configured` without fabricating fake SAR scenes, fake permanent water masks, or fake rainfall accumulation.
- **Project-Scoped AOI Derivation**:
  - `GET /api/dam-projects/{id}/earth-observation/aoi?buffer_meters=` extracts AOI bounds and polygon from model domain or DEM extent with configurable UTM metric buffer.
- **Sentinel-1 SAR Flood Inundation & Configurable Heuristics**:
  - Configurable heuristics for thresholding: `change_threshold_db` (-3.0 dB default) and `post_event_water_threshold_db` (-15.0 dB default).
  - Provenance strictly tagged with `threshold_source="configurable_heuristic"`, orbit metadata, and temporal windows.
  - Pixels explicitly labeled `candidate_inundation` (never confirmed flood).
- **JRC Global Surface Water & GPM IMERG Rainfall**:
  - Differentiates permanent water bodies from flood candidate pixels using JRC occurrence masks.
  - Ingests NASA GPM IMERG rainfall accumulation and time series for hydrological context.
- **Observed vs. Modelled Comparison Engine**:
  - Evaluates spatial overlap, union, model-only, and satellite-only areas between ANUGA 2D hydrodynamic simulation rasters (`maximum_depth.tif`) and candidate inundation masks.
  - Calculates Intersection over Union ($IoU$ / Jaccard Index), strictly labeled `"model-observation spatial agreement"` (explicitly NOT labeled "simulation accuracy").
  - Configurable `max_observation_time_delta_hours` with temporal validity metadata and warning logs.
- **Frontend Earth Observation Studio**:
  - Interactive `EarthObservationPanel.tsx` embedded in project cards with live GEE status HUD, AOI buffer controls, query builder, run history with log console, and comparison KPI card with scientific uncertainty caveats.

### Multi-Engine Spatial Hydrodynamic Comparison (Phase 21)
- **Normalized Output Contract**: Standardizes solver outputs across ANUGA, Delft3D FM, and PySPH, preserving native/analysis CRS, layer hashes, and scientific status.
- **Projected Metric Grid Analysis**: Area calculations computed exclusively on projected metric grids (e.g. UTM) with common valid analysis masks.
- **Spatial Agreement & Spread Diagnostic**: Evaluates pairwise $IoU$, depth MAE/RMSE, velocity deltas, arrival deltas, and multi-model spread.
- **Frontend Studio**: `ModelComparisonPanel.tsx` embedded in project cards with capability discovery HUD and diverging difference tile overlays.

### Population, Infrastructure Exposure & Vulnerability Assessment (Phase 22)
- **Hazard vs. Exposure vs. Vulnerability**: Strictly maintains scientific distinction (`exposed population != casualties`; `inundated building != destroyed`; `flooded road != impassable`).
- **Population Raster Semantics & Mass Conservation**: Supports `persons_per_cell` (mass conserved without bilinear distortion) and `persons_per_sq_km` (area integrated); categorized into configurable depth bands.
- **Building Exposure**: True polygon raster zonal overlay deriving max/mean depth, max velocity, earliest arrival, and flooded footprint area; interior point sampling fallback.
- **Road Exposure**: Metric length calculation via spatial segmentation; labeled `"potentially affected road segment"` (`road_passability_available = false` unless documented threshold exists).
- **Critical Infrastructure**: Normalized mapping based strictly on confirmed OSM tags; ambiguous features strictly marked `normalized_category = "unknown"`.
- **Categorical LULC**: Nearest-neighbour resampling; preserves unmapped classes as `unknown / class_<value>`.
- **Vulnerability Curves & Zero Monetary Fabrication**: Evaluates relative damage ratios (0.0 to 1.0) using documented JRC flood curves; returns `monetary_damage = null` without local valuation data.
- **Decision-Support Priority Index & Hotspots**: Multi-criteria priority score with visible heuristic weights; transparent hotspot flagging (`high_depth_settlement`, `critical_asset_flooded`, etc.).
- **Frontend Studio**: `ExposureVulnerabilityPanel.tsx` with honest dataset capability matrix, KPI metrics, depth band breakdown, and MapLibre layer toggles.

### Delft3D FM Integration & Gated Execution Boundary (Phase 11)
- Capability discovery: Detects local HydroMT-Delft3D FM and D-Flow FM solver binary availability.
- Clean environment recipe: Standalone `environment_hydromt_delft3dfm.yml` specification for isolated HydroMT model setup without modifying the core app environment.
- Draft model package generator: Generates downloadable ZIP bundle containing immutable `manifest.json`, dataset SHA-256 hashes, draft HydroMT/D-Flow FM configuration templates (`.ini`, `.yaml`), folder hierarchy, and `README_REQUIREMENTS.txt` detailing missing real-world inputs.
- Gated simulation runner: Execution is strictly disabled by default (`ENABLE_DFLOWFM_EXECUTION=false`) and requires server-configured binary paths. Rejects unconfigured runs with HTTP 409 Conflict (`engine_unavailable`). Never fabricates simulation results.

### SPH Solver, Comparison Boundary & GEE Connector (Phase 12)
- **PySPH Lagrangian Particle Solver**: Dedicated `environment_pysph.yml` specification; capability discovery; downloadable 2D column collapse benchmark package (`dam_break_2d_pysph.py`, SHA-256 manifest, requirements); strictly gated subprocess execution (`ENABLE_PYSPH_EXECUTION=false`).
- **Multi-Engine Hydrodynamic Comparison**: Dynamic common grid alignment in temporary memory; quantitative spatial metrics ($IoU$, $CSI$, Area $\Delta \text{km}^2$) and error statistics ($MAE$, $RMSE$, Mean Bias); structured 5-dimension methodology comparison matrix (Eulerian SWE vs Lagrangian Navier-Stokes).
- **Google Earth Engine (GEE) Connector**: Dedicated `environment_gee.yml`; server-side ADC authentication (`GEE_PROJECT_ID`); whitelisted datasets (`Sentinel-1 SAR GRD`, `GPM IMERG`, `JRC Global Surface Water`); candidate water-change observation plan generator with cloud task gating (`ENABLE_GEE_TASKS=false`).

### Automated Verification & Presentation Preparation (Phase 13)
- **One-Command Verification**: `powershell .\scripts\verify.ps1` executes all 79 Pytest tests and frontend production build.
- **Safe Live Demo Launcher**: `powershell .\scripts\demo.ps1` checks prerequisites, reuses healthy ports safely, starts backend/frontend services, and opens the interactive dashboard at `http://localhost:5173`.
- **Comprehensive Documentation Suite (`docs/`)**:
  - [ARCHITECTURE.md](file:///docs/ARCHITECTURE.md): System components & Mermaid data flow.
  - [VALIDATION_REPORT.md](file:///docs/VALIDATION_REPORT.md): Audit records & test breakdown.
  - [LIMITATIONS.md](file:///docs/LIMITATIONS.md): Scientific caveats, datum uncertainties, and operational constraints.
  - [DEMO_SCRIPT.md](file:///docs/DEMO_SCRIPT.md): Truthful 5-minute SIH live demonstration script.
  - [PRESENTATION_OUTLINE.md](file:///docs/PRESENTATION_OUTLINE.md): 10-slide competition pitch deck.
  - [JUDGE_QA.md](file:///docs/JUDGE_QA.md): Technical defense questions and answers.
  - [DEPLOYMENT.md](file:///docs/DEPLOYMENT.md): Local and production NGINX / systemd setup.
  - [FINAL_STATUS.md](file:///docs/FINAL_STATUS.md): Categorized feature completion & readiness matrix.

### 3. Frontend Application (React + Vite + TypeScript)
```powershell
cd frontend
npm install
npm run build
npm run dev
```
- Web Application: `http://localhost:5173`

### 4. Convenience & Verification Scripts
```powershell
# Run full automated test suite and production build
.\scripts\verify.ps1

# Launch one-command live demo session
.\scripts\demo.ps1

# Standard development launcher
.\scripts\dev.ps1
```

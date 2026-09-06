# Dam Break Decision Support System (SIH26161)

## Local Run Instructions

### Prerequisites
- Conda (Miniforge / Anaconda)
- Node.js (v20+) and npm

### 1. Conda Environment Setup
```powershell
conda env create -f environment.yml
conda activate sih-app
```

### 2. Backend Service (FastAPI)
```powershell
cd backend
pytest -v
uvicorn app.main:app --reload --port 8000
```
- Health Check: `http://localhost:8000/api/health`
- Datasets Catalog: `http://localhost:8000/api/datasets`
- Raster Metadata: `http://localhost:8000/api/rasters/{id}/metadata`
- Raster Point Value: `http://localhost:8000/api/rasters/{id}/value?lon={lon}&lat={lat}`
- Raster XYZ Tiles: `http://localhost:8000/api/rasters/{id}/tiles/{z}/{x}/{y}.png`
- Raster Legend & Color Ramp: `http://localhost:8000/api/rasters/{id}/legend`
- Interactive API Docs: `http://localhost:8000/docs`
- Vector Assets GeoJSON: `http://localhost:8000/api/assets`
- Vector Roads GeoJSON: `http://localhost:8000/api/roads`
- Assets Preliminary Exposure: `http://localhost:8000/api/exposure/assets`
- Roads Preliminary Exposure: `http://localhost:8000/api/exposure/roads`
- Exposure Screening Summary: `http://localhost:8000/api/exposure/summary`
- Damage Scenario Default Config: `http://localhost:8000/api/damage/config`
- Damage Scenario Estimation: `POST http://localhost:8000/api/damage/estimate`
- Route Screening: `POST http://localhost:8000/api/routes/screening`
- Geospatial Layer Export: `GET http://localhost:8000/api/export/{layer}?format={format}&exposure_filter={filter}` (`assets`, `roads`)
- Screened Route Export: `POST http://localhost:8000/api/export/route` (or `POST http://localhost:8000/api/export`)
- Scenarios Management: `GET / POST http://localhost:8000/api/scenarios` (Clone, Archive, Update)
- Simulation Capabilities: `GET http://localhost:8000/api/simulation/capabilities`
- Delft3D Draft Package Build: `POST http://localhost:8000/api/scenarios/{id}/build-package`
- Delft3D Draft Package Download: `GET http://localhost:8000/api/scenarios/{id}/download-package`
- Simulation Execution: `POST http://localhost:8000/api/scenarios/{id}/run` (Gated; requires engine)
- Simulation Runs History & Logs: `GET http://localhost:8000/api/runs`, `GET http://localhost:8000/api/runs/{run_id}/logs`
- PySPH Capabilities: `GET http://localhost:8000/api/sph/capabilities`
- PySPH Package Build & Download: `POST /api/scenarios/{id}/build-sph-package`, `GET /api/scenarios/{id}/download-sph-package`
- PySPH Simulation Run & Logs: `POST /api/scenarios/{id}/run-sph` (Gated), `GET /api/sph-runs`, `GET /api/sph-runs/{run_id}/logs`
- Multi-Engine Comparison: `GET /api/comparison/readiness`, `GET /api/comparison/methodology`, `POST /api/comparison/compare`
- Google Earth Engine Connector: `GET /api/gee/capabilities`, `GET /api/gee/datasets`, `POST /api/gee/export-plan`

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

### ANUGA Regional Hydrodynamic Pilot (Phase 15)
- Genuine 2D finite-volume Shallow Water Equation regional simulation over Ghataprabha basin topography (`validation/anuga_hidkal_pilot/`).
- Reprojected Hidkal DEM to **EPSG:32643** (UTM Zone 43N) spanning $30.0\text{ km} \times 22.1\text{ km}$ ($663.0\text{ km}^2$, $21,120$ triangular elements).
- Hypothetical unverified pilot scenario ($200\text{ m}$ breach, assumed pool stage $660.0\text{ m}$, composite roughness $n = 0.035$, $T=1800\text{ s}$ duration).
- Complete diagnostic verification:
  - Peak Inundation Depth: **24.83 m**, Peak Flow Velocity: **12.84 m/s**, Inundated Area: **197.62 km²**.
  - Volume Conservation: Exact ($9.20 \times 10^{-15}$ relative mass difference from $356.48\text{ MCM}$).
  - Full reproducible toolchain (`preprocess_dem.py`, `run_anuga_pilot.py`, `postprocess_outputs.py`), summary (`pilot_summary.json`), GeoTIFF exports, and cryptographic manifest (`manifest.json`).
- Distinct scientific validation: Separates schema validity from verified physics; unverified inputs remain flagged as `input_review_required`.
- Immutable snapshots: Computes deterministic SHA-256 digests over configuration parameters and referenced input datasets.
- Revision history and non-destructive archiving.

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

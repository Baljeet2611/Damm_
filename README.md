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
- Distinct scientific validation: Separates schema validity from verified physics; unverified inputs remain flagged as `input_review_required`.
- Immutable snapshots: Computes deterministic SHA-256 digests over configuration parameters and referenced input datasets.
- Revision history and non-destructive archiving.

### Delft3D FM Integration & Gated Execution Boundary (Phase 11)
- Capability discovery: Detects local HydroMT-Delft3D FM and D-Flow FM solver binary availability.
- Clean environment recipe: Standalone `environment_hydromt_delft3dfm.yml` specification for isolated HydroMT model setup without modifying the core app environment.
- Draft model package generator: Generates downloadable ZIP bundle containing immutable `manifest.json`, dataset SHA-256 hashes, draft HydroMT/D-Flow FM configuration templates (`.ini`, `.yaml`), folder hierarchy, and `README_REQUIREMENTS.txt` detailing missing real-world inputs.
- Gated simulation runner: Execution is strictly disabled by default (`ENABLE_DFLOWFM_EXECUTION=false`) and requires server-configured binary paths. Rejects unconfigured runs with HTTP 409 Conflict (`engine_unavailable`). Never fabricates simulation results.


### 3. Frontend Application (React + Vite + TypeScript)
```powershell
cd frontend
npm install
npm run build
npm run dev
```
- Web Application: `http://localhost:5173`

### 4. Optional Convenience Script
```powershell
.\scripts\dev.ps1
```


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

### Registered Dataset IDs
- `dem` -> `data/raw/data_hidkal/hidkal_dem.tif` (Float32 DEM)
- `depth` -> `data/raw/data_hidkal/hidkal_depth.tif` (Float32 Inundation Depth; zero is transparent)
- `velocity` -> `data/raw/data_hidkal/hidkal_velocity.tif` (Float32 Velocity; zero is transparent)
- `arrival` -> `data/raw/data_hidkal/hidkal_arrival.tif` (Float32 Arrival Time; `+9999` and `-9999` treated as NoData & transparent)
- `assets` -> `data/raw/data_hidkal/hidkal_assets.geojson` (513 OSM infrastructure assets)
- `roads` -> `data/raw/data_hidkal/hidkal_roads.graphml` (3,084 nodes, 8,047 road edges)

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


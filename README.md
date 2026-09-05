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

### Registered Dataset IDs
- `dem` -> `data/raw/data_hidkal/hidkal_dem.tif` (Float32 DEM)
- `depth` -> `data/raw/data_hidkal/hidkal_depth.tif` (Float32 Inundation Depth; zero is transparent)
- `velocity` -> `data/raw/data_hidkal/hidkal_velocity.tif` (Float32 Velocity; zero is transparent)
- `arrival` -> `data/raw/data_hidkal/hidkal_arrival.tif` (Float32 Arrival Time; `+9999` and `-9999` treated as NoData & transparent)
- `assets` -> `data/raw/data_hidkal/hidkal_assets.geojson` (513 OSM infrastructure assets)
- `roads` -> `data/raw/data_hidkal/hidkal_roads.graphml` (3,084 nodes, 8,047 road edges)

### Road Network Route Screening Module (Phase 8)
- Dijkstra shortest path routing over directed MultiDiGraph topology weighted by geodesic edge length in meters.
- Snapping to nearest road network nodes via spherical Haversine distance with configurable threshold (`max_snap_distance_meters`, default 5000 m). Rejects points beyond threshold with HTTP 422.
- Automatically excludes screening-positive road segments (`exposed == true`) when `avoid_screening_positive` is enabled.
- Reconstructs continuous LineString route geometries in exact sequence and direction of travel.
- Prominently labeled with mandatory screening disclaimer ("Screening route only — road closures, bridges, carrying capacity, and live accessibility are not validated").

### Geospatial Multi-Format Exports Module (Phase 9)
- Multi-format support: **GeoJSON** (`.geojson`), **Google Earth KML** (`.kml`), and **ESRI Shapefile ZIP** (`.zip`).
- Strict layer and format whitelisting (`assets`, `roads`, `route`).
- Exposure status filtering: `all`, `screening_positive`, `not_exposed`, `not_assessed`.
- Automatic partitioning of mixed geometry types into separated `_points.shp`, `_lines.shp`, and `_polygons.shp` shapefile bundles.
- Includes complete shapefile component sets (`.shp`, `.shx`, `.dbf`, `.prj`, `.cpg`) and `README_METADATA.txt` detailing column mappings, `EPSG:4326` CRS, and scientific disclaimers.
- In-memory ZIP buffer creation prevents premature file deletion and race conditions during streaming responses.


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


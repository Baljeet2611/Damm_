# Phased Implementation Tasks: SIH26161

Automated dam-break framework comparing SPH and Delft3D, with inundation, damage analysis, GUI, SHP/KML export, and GEE flood analysis.

---

## Phase 1: Ingestion, Safe Inspection & Quality Assessment [CURRENT - COMPLETED]
- [x] Preserve raw archives (`data_hidkal.zip`, `tifToTerrain.zip`) unmodified in workspace root.
- [x] Extract archives into `data/raw/` (`data/raw/data_hidkal/` and `data/raw/tifToTerrain/`).
- [x] Inspect all raster layers safely (dimensions, CRS, bounds, pixel sizes, NoData values, value ranges).
- [x] Detect and record `hidkal_arrival.tif` NoData mismatch (`GDAL_NODATA = -9999` in header vs `+9999.0` in raster data).
- [x] Inspect vector layers (`hidkal_assets.geojson` geometries/properties and `hidkal_roads.graphml` nodes/edges).
- [x] Detect and segregate `default.tif` (confirmed located in Morbi, Gujarat, outside Hidkal domain) and inspect `new.html` Three.js viewer.
- [x] Document that current flood rasters are unverified sample rasters of unknown provenance and must not be presented as validated simulations.
- [x] Establish project governance documentation:
  - [x] `PROJECT_CONTEXT.md`
  - [x] `TASKS.md`
  - [x] `DATA_SOURCES.md`
  - [x] `.gitignore`

## Phase 2: Minimal Reproducible Application Scaffold [COMPLETED]
- [x] Create `environment.yml`: `sih-app` conda environment (conda-forge, Python 3.11, FastAPI, uvicorn, rasterio, geopandas, shapely, networkx, numpy, pydantic, pytest, httpx).
- [x] Create `backend/app/` Python package with minimal FastAPI app, `GET /api/health`, and CORS configured for `http://localhost:5173`.
- [x] Create pytest health-endpoint unit test (`backend/tests/test_health.py`).
- [x] Create `frontend/` using Vite, React, and TypeScript.
- [x] Install `maplibre-gl` in `frontend/`.
- [x] Create minimal UI page displaying "Dam Break Decision Support System" and backend health status.
- [x] Add `frontend/.env.example` with `VITE_API_BASE_URL=http://localhost:8000` (and `frontend/.env`).
- [x] Add concise local run instructions (`README.md`) and launch script (`scripts/dev.ps1`).
- [x] Validate conda environment creation, npm dependency installation, pytest execution, and `npm run build`.

---

## Phase 3: Safe Raster Metadata & Point-Query API [COMPLETED]
- [x] Register fixed dataset catalog with strict ID whitelisting (`dem`, `depth`, `velocity`, `arrival`).
- [x] Implement `GET /api/datasets` returning ID, label, availability, data type, unit status, and provenance status without exposing absolute filesystem paths.
- [x] Implement `GET /api/rasters/{id}/metadata` returning width, height, dtype, CRS, bounds, resolution, metadata NoData, and valid min/max.
- [x] Implement metadata in-memory caching keyed by ID and file modification time (never returns full raster arrays).
- [x] Implement `GET /api/rasters/{id}/value?lon=&lat=` with coordinate validation, returning row, column, value, and `is_nodata` (404 for unknown ID, 422 outside bounds).
- [x] Treat both `+9999` and `-9999` as NoData for `arrival` returning `value: null` without modifying the original raw file.
- [x] Prevent arbitrary file-path inputs and path traversal vulnerabilities.
- [x] Build comprehensive unit tests using temporary tiny rasters in `tmp_path` (runs without `data/raw`).
- [x] Add local integration test that validates real Hidkal rasters when present (skips gracefully when absent).


---

## Phase 4: Raster Tile Rendering, Legends & Interactive GIS Map Viewer [COMPLETED]
- [x] Integrate `rio-tiler` for XYZ slippy tile serving on registered rasters (`dem`, `depth`, `velocity`, `arrival`).
- [x] Implement `GET /api/rasters/{id}/tiles/{z}/{x}/{y}.png` returning 256x256 PNGs with caching headers and strict dataset ID whitelisting.
- [x] Handle outside-extent and out-of-bounds tiles gracefully by returning transparent PNGs without 500 server errors.
- [x] Implement display transparency rules:
  - Depth: zero depth (0.0 / dry cells) is transparent.
  - Velocity: zero velocity (0.0 m/s) is transparent.
  - Arrival: unflooded cells (+9999.0 and -9999.0) are transparent.
  - DEM: NoData cells (-9999.0 and NaN) are transparent.
- [x] Implement `GET /api/rasters/{id}/legend` returning color ramp stops, discrete classification items, and value ranges.
- [x] Build frontend MapLibre interactive map canvas with OpenStreetMap basemap and attribution.
- [x] Fit map initial view to Hidkal Dam bounds (`[74.60, 16.12, 74.88, 16.32]`) with quick "Fit Hidkal" button.
- [x] Add Layer Selector (DEM, Depth, Velocity, Arrival) and Opacity Slider (0% - 100%).
- [x] Add Dynamic Legend HUD displaying color ramp gradient bar, discrete stop chips, and transparency notices.
- [x] Add Multi-Raster Point Query Probe on map click querying all four rasters simultaneously and displaying probed values.
- [x] Prominently display mandatory disclaimer banner: "Unverified sample outputs — not a validated prediction."
- [x] Add connection status indicator, loading states, error handling, and responsive GIS styling.
- [x] Build and pass 20 backend pytest unit/integration tests and validate frontend production build (`npm run build`).

---

## Phase 5–6: Vector Overlays & Preliminary Flood-Exposure Screening [COMPLETED]
- [x] Implement fixed read-only endpoints:
  - [x] `GET /api/assets`: Raw OSM infrastructure assets (513 features) with standardized categorization (`building`, `healthcare`, `education`, `emergency`, `settlement`, `transport`, `other`).
  - [x] `GET /api/roads`: OSMnx GraphML road network (3,084 nodes, 8,047 edges) converted to GeoJSON LineStrings with stored geometry fallback.
  - [x] `GET /api/exposure/assets`: Preliminary exposure screening per asset with attached attributes (`assessed`, `exposed` where valid depth > 0, `depth_value`, `velocity_value`, `arrival_value`, `sampling_method`).
  - [x] `GET /api/exposure/roads`: Preliminary exposure screening per road segment.
  - [x] `GET /api/exposure/summary`: Full exposure summary with total, assessed, exposed, not-exposed, not-assessed counts, and category breakdowns.
- [x] Implemented geometric screening methods:
  - Direct point sampling for Points (`point_direct`).
  - Interior representative point sampling for Polygons (`polygon_representative_point`).
  - Segment midpoint sampling for LineStrings (`line_midpoint`).
- [x] In-memory caching for parsed vector data and raster screening results keyed by file modification timestamps.
- [x] Path safety: all endpoints accept only whitelisted IDs and never accept or expose filesystem paths.
- [x] Frontend vector visualization in MapLibre:
  - Independent toggle switches for Infrastructure Assets and Road Network overlays without breaking raster selection.
  - Distinct styling for exposed (vivid crimson red) vs non-exposed/dry (emerald green / slate).
  - Interactive click popups displaying feature title, category, exposed/safe badge, raster values marked "unit unverified", and methodology notes.
  - Dynamic Exposure Summary panel with KPI cards (135/513 assets, 2,060/8,047 road segments exposed) and category breakdown tables.
  - Prominently labeled with mandatory preliminary exposure screening disclaimer.
- [x] Passed 29 backend pytest tests (isolated mocks + real Hidkal integration) and verified frontend production build (`npm run build`).

---

## Phase 7: Transparent Illustrative Damage-Scenario Estimation [COMPLETED]
- [x] Backend Endpoints:
  - [x] `GET /api/damage/config`: Returns default configuration, assumed depth unit, currency label, replacement values per category, depth-damage curve points, sensitivity percentage, and methodology assumptions.
  - [x] `POST /api/damage/estimate`: Computes category and total illustrative loss with low/base/high sensitivity estimates based on piecewise linear interpolation of sampled depth on screening-positive assets.
- [x] Strict Validation & Safeguards:
  - [x] Reject calculation with HTTP 422 if `acknowledge_unverified_inputs` is not `True`.
  - [x] Validate replacement values are non-negative.
  - [x] Validate depth-damage curve is monotonic and strictly ascending in depth with ratios between 0.0 and 1.0 ($\ge 2$ points).
  - [x] Validate sensitivity percentage is between 0% and 100%.
  - [x] Exclude road network and human populations/casualties strictly from monetary valuation.
- [x] Frontend Damage Scenario Panel:
  - [x] Dedicated "Illustrative Damage Scenario" tab in HUD alongside Layers and Exposure Screening.
  - [x] Prominent disclaimer banner: *"Illustrative scenario only — not an official loss estimate or emergency decision."*
  - [x] Calculation disabled until explicit acknowledgement checkbox is checked by user.
  - [x] Full interactive editing: currency label, assumed depth unit, sensitivity %, replacement value per category, dynamic depth-damage curve table (add/remove points).
  - [x] Results display: Low / Base / High KPI cards with sensitivity bounds, category loss breakdown table, screening asset counts, and transparent methodology explanation.
- [x] Complete test suite: 35 backend pytest tests (6 dedicated damage scenario tests) and verified frontend build.

---

## Phase 8: GIS & Multi-Format Export Pipeline
- [ ] Automated spatial layer exporter:
  * [ ] Export hazard zones and peak depths to ESRI Shapefile (`.shp`, `.shx`, `.dbf`, `.prj`).
  * [ ] Export styled 3D hazard polygons and time-stamped wavefronts to Google Earth KML/KMZ (`.kml`, `.kmz`).
  * [ ] Export vector layers to open OGC GeoPackage (`.gpkg`).
  * [ ] Export Cloud-Optimized GeoTIFFs (COG) with pyramids for rapid web mapping.
- [ ] Automated PDF / Markdown summary report generator (flood extent, affected population, disrupted roads, damage tally).

---

## Phase 9: Earth Observation & GEE Flood Validation Module
- [ ] Google Earth Engine (GEE) integration:
  * [ ] Authenticate and query Sentinel-1 SAR GRD collections (C-band VV/VH polarizations) for pre-flood and post-flood dates.
  * [ ] Apply speckle filtering (Lee/Refined Lee) and radiometric terrain correction.
  * [ ] Execute adaptive thresholding (Otsu method / bimodal distribution split) to delineate actual observed surface water.
- [ ] Calibration and validation analytics:
  * [ ] Overlay satellite-derived flood extent against model-simulated flood footprints.
  * [ ] Compute classification confusion matrix: True Positive (Hit), False Positive (Overprediction), False Negative (Underprediction).
  * [ ] Calculate critical success index ($CSI$), intersection over union ($IoU$), and Cohen's Kappa ($\kappa$).

---

## Phase 10: 3D Terrain & Decision Support Dashboard
- [ ] Interactive 2D Map View:
  * [ ] Temporal playback scrubber showing flood wave propagation over time.
- [ ] 3D WebGL Terrain Viewer:
  * [ ] Adapt and integrate Three.js terrain rendering from `new.html` to load real Hidkal DEM and flood depth surfaces.
  * [ ] Dynamic color ramp shading, water surface animation, and interactive orbit controls.
- [ ] Scenario Configuration & Decision Dashboard:
  * [ ] Dam breach parameter configuration panel (breach width, failure duration, initial reservoir level).
  * [ ] One-click export button for SHP, KML, and executive briefing reports.

---

## Phase 11: Benchmarking, Validation & Final Packaging
- [ ] End-to-end integration testing on Hidkal case study.
- [ ] Comprehensive documentation, API guides, and demonstration video / walkthrough.

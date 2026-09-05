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

## Phase 8: Preliminary Road Network Route Screening [COMPLETED]
- [x] Backend Routing Engine (`backend/app/route_service.py`):
  - [x] Load road network from OSMnx GraphML (`hidkal_roads.graphml`) and synchronize with exposure screening results from `vector_service.get_exposure_roads()`.
  - [x] Graph topology: Respect directed `MultiDiGraph` and extract edge geometries in travel direction order.
  - [x] Stable edge key matching: Match exposure screening results using `(u, v, key)` tuples, never list indices.
  - [x] Spatial node lookup: Nearest node snapping using great-circle Haversine spherical distance calculation.
  - [x] Validation: Coordinate bounds validation ([-180, 180], [-90, 90]) and configurable `max_snap_distance_meters` (default 5000m) with 422 rejection when points exceed threshold.
  - [x] Filtered Dijkstra shortest-path routing avoiding edges marked `exposed == True` when `avoid_screening_positive` is enabled.
  - [x] Fallback handling: Returns `route_found: False` with diagnostic warnings if no traversable path exists without routing over screening-positive (depth > 0 at sample) edges.
  - [x] Metric calculations: Geodesic route distance (meters and km), segment count, snap distances, and excluded screening-positive (depth > 0 at sample) edge counts.
  - [x] Disclaimers & metadata: Includes scientific screening disclaimer ("Screening route only — road closures, bridges, carrying capacity, and live accessibility are not validated").
- [x] Frontend Route Screening Panel (`frontend/src/App.tsx`, `App.css`):
  - [x] Dedicated "🛣️ Route" tab in HUD panel.
  - [x] Coordinate input fields with interactive map picking ("📍 Set on Map" for Start and Destination).
  - [x] Map click interception: Picking mode banner appears, map click sets waypoint and dismisses banner without triggering point probe or vector popups.
  - [x] Start Pin (Green) and Destination Pin (Purple) markers rendered on MapLibre map.
  - [x] Glowing cyan route LineString layer with dark blue casing rendered above base map.
  - [x] Route result card with status badge, distance KPIs, segment count, snap distances, and warnings list.
- [x] Test suite: Comprehensive unit and integration tests (`backend/tests/test_route_api.py`) covering snapping, edge exclusion, fallback diagnostics, and real Hidkal road routing.

---

## Phase 9: Geospatial Multi-Format Exports Pipeline [COMPLETED]
- [x] Backend Export Engine (`backend/app/export_service.py`, `app/main.py`):
  - [x] Endpoints:
    - `GET /api/export/{layer}` (whitelisted: `assets`, `roads`; applies `exposure_filter`: `all`, `screening_positive`, `not_exposed`, `not_assessed`).
    - `POST /api/export/route` and `POST /api/export` (recomputes screened route from validated `RouteScreeningRequest`).
  - [x] GeoJSON Exporter: Formatted GeoJSON FeatureCollection stream with content disposition attachment headers.
  - [x] Google Earth KML Exporter: Well-formed XML-escaped Placemarks with extended attribute data tables, custom styling, and disclaimer headers.
  - [x] ESRI Shapefile Zipped Archive Exporter:
    - GeoPandas GeoDataFrame export into in-memory ZIP buffer before temporary directory cleanup to avoid streaming race conditions.
    - Mixed geometry partitioning: Automatically splits assets into `_points.shp`, `_lines.shp`, and `_polygons.shp`.
    - Complete shapefile sidecars: `.shp`, `.shx`, `.dbf`, `.prj` (`EPSG:4326`), `.cpg` (`UTF-8`).
    - Attribute sanitization: Deterministic column name shortening ($\le 10$ chars), safe serialization of nested dicts/lists to JSON strings, and string truncation to 254 chars.
    - Detailed `README_METADATA.txt` packaged inside every ZIP with attribute field mappings, CRS specification, and unverified data disclaimers.
  - [x] Security & Safeguards: Strict layer whitelisting, format validation, and explicit 422 rejection of GET route requests.
- [x] Frontend Geospatial Export Panel:
  - [x] Dedicated "💾 Export" tab in HUD panel.
  - [x] Layer selector (Infrastructure Assets, Road Network, Screened Route with prerequisite validation).
  - [x] Exposure status filter selector (All, Screening-positive, Not Exposed at Sample, Not Assessed).
  - [x] Format selector (GeoJSON, KML, Shapefile ZIP).
  - [x] Browser blob download trigger with loading spinner, success confirmation badge, and error notifications.
- [x] Test suite: Comprehensive unit and integration tests (`backend/tests/test_export_api.py`) validating GeoJSON, KML XML structure, Shapefile ZIP internal files, and metadata generation.

---

## Phase 10: Persistent Scenario Management & Immutable Snapshots [COMPLETED]
- [x] Backend Scenario Storage Engine (`backend/app/scenario_storage.py`):
  - [x] Persistent JSON storage in dedicated runtime directory (`SIH_RUNTIME_DIR`), secured via UUID v4 validation and atomic tempfile replacement.
  - [x] Parametric fields: name, description, site, DEM dataset ID, CRS, breach width (m), breach formation time (hr), pool level (m), boundary descriptors, Manning's $n$, mesh cell size (m), duration (hr), timestep (s).
  - [x] Assumption verification tracking: Explicit unit tags and status indicators (`unverified_illustrative`, `unverified_datum`, `estimated`, `verified`).
  - [x] Scientific validation separation: Distinguishes schema validity from verified physics; unverified inputs remain flagged as `input_review_required`.
  - [x] Immutable snapshots: Computes deterministic SHA-256 digests over configuration and referenced input datasets (`hidkal_dem.tif`).
  - [x] Lifecycle endpoints: Create, list, get, update (auto-increments revision), clone, archive, and unarchive (non-destructive).
- [x] Frontend Scenario Manager (`frontend/src/App.tsx`, `App.css`):
  - [x] Dedicated "🌊 Scenarios" tab in HUD panel.
  - [x] Scenario creation and editing form with assumption status tags and unit hints.
  - [x] Scenario cards with revision badges, quick metrics, SHA-256 fingerprint, and action buttons (Edit, Clone, Archive, Build Package, Run).
  - [x] Scientific validation checklist card highlighting missing prerequisites.
- [x] Test suite: Comprehensive unit tests (`backend/tests/test_scenario_api.py`) covering CRUD, atomic persistence, revision increments, traversal rejection, and clone/archive workflows.

---

## Phase 11: Honest Delft3D FM Integration & Gated Execution Boundary [COMPLETED]
- [x] Backend Simulation & Capabilities Service (`backend/app/simulation_service.py`, `app/main.py`):
  - [x] Capability discovery: `GET /api/simulation/capabilities` detects local HydroMT-Delft3D FM module and D-Flow FM/DIMR solver binary.
  - [x] Clean environment isolation: Documented `environment_hydromt_delft3dfm.yml` for optional standalone HydroMT model builder environment without modifying `sih-app`.
  - [x] Draft model package builder: `POST /api/scenarios/{id}/build-package` generates downloadable ZIP package containing immutable `manifest.json`, dataset SHA-256 hashes, draft HydroMT/D-Flow FM configuration templates (`.ini`, `.yaml`), folder hierarchy, and honest `README_REQUIREMENTS.txt`.
  - [x] Package download endpoint: `GET /api/scenarios/{id}/download-package`.
  - [x] Gated simulation runner: `POST /api/scenarios/{id}/run` is strictly disabled by default (`ENABLE_DFLOWFM_EXECUTION=false`). Rejects unconfigured executions with HTTP 409 Conflict (`engine_unavailable`). Never fabricates simulation results.
  - [x] Safe subprocess execution: Argument list invocation (`shell=False`), fixed working directory, timeout handling, and stdout/stderr log capture.
  - [x] Historical run tracking: `GET /api/runs`, `GET /api/runs/{run_id}`, and `GET /api/runs/{run_id}/logs`.
- [x] Frontend Capabilities & Simulation Panel:
  - [x] Live capability status badges for HydroMT Builder and D-Flow FM Engine.
  - [x] Collapsible setup and environment configuration guide.
  - [x] "📦 Build Package" action generating draft package ZIP with manifest checksum notification.
  - [x] Gated "🚀 Run D-Flow FM" button with explanatory disabled state and error messaging.
  - [x] Simulation execution history table with log viewer modal (stdout/stderr inspection).
- [x] Test suite: Comprehensive unit and mock integration tests (`backend/tests/test_simulation_api.py`) verifying capabilities, package contents, 409 gating, mock subprocess success/failure/timeout, and log retrieval.

---

## Phase 12: SPH Integration, Multi-Engine Comparison & Earth Engine Connector [COMPLETED]
- [x] PySPH Solver Adapter & Package Builder (`backend/app/sph_service.py`, `environment_pysph.yml`):
  - [x] Isolated PySPH environment specification (`environment_pysph.yml`) without polluting base `sih-app`.
  - [x] Capability detection: `GET /api/sph/capabilities` detects PySPH module and executable status.
  - [x] Draft benchmark package generator: `POST /api/scenarios/{id}/build-sph-package` generates ZIP with 2D column collapse benchmark script (`dam_break_2d_pysph.py`), config JSON, SHA-256 manifest, and `README_SPH_REQUIREMENTS.txt`.
  - [x] Download endpoint: `GET /api/scenarios/{id}/download-sph-package`.
  - [x] Gated simulation execution: `POST /api/scenarios/{id}/run-sph` (gated behind `ENABLE_PYSPH_EXECUTION=false`, returns 409 Conflict if disabled).
  - [x] PySPH historical run tracking & log viewer: `GET /api/sph-runs`, `GET /api/sph-runs/{run_id}`, `GET /api/sph-runs/{run_id}/logs`.
  - [x] Explicit laboratory benchmark vs. regional 3D river scale separation disclaimers.
- [x] Multi-Engine Benchmark & Hydrodynamic Comparison Boundary (`backend/app/comparison_service.py`):
  - [x] Readiness evaluation: `GET /api/comparison/readiness` verifies presence of completed Delft3D and PySPH runs with verified physical unit manifests.
  - [x] Dynamic spatial alignment: `POST /api/comparison/compare` reprojects raster outputs onto common evaluation grid in temporary memory.
  - [x] Quantitative metrics: Computes Extent IoU (Jaccard), Critical Success Index (CSI / Threat Score), Area Difference ($\text{km}^2$), Depth / Velocity MAE, RMSE, Mean Bias.
  - [x] Honest failure states: Returns status `comparison_unavailable` with explicit blocker lists when runs are missing or unverified.
  - [x] Architectural methodology matrix: `GET /api/comparison/methodology` detailing physical equations (SWE vs Navier-Stokes), discretization, wave breaking, and compute scale limitations.
- [x] Google Earth Engine (GEE) Connector Service (`backend/app/gee_service.py`, `environment_gee.yml`):
  - [x] Isolated Earth Engine environment specification (`environment_gee.yml`).
  - [x] Capabilities & strict ADC authentication: `GET /api/gee/capabilities` checking GCP Application Default Credentials and `GEE_PROJECT_ID`. Never accepts tokens over HTTP.
  - [x] Whitelisted collections: `COPERNICUS/S1_GRD` (Sentinel-1 SAR), `NASA/GPM_L3/IMERG_V07` (GPM IMERG), `JRC/GSW1_4/GlobalSurfaceWater` (JRC Surface Water).
  - [x] Dataset catalog endpoint: `GET /api/gee/datasets` and `GET /api/gee/datasets/{dataset_id}`.
  - [x] Observation export plan generator: `POST /api/gee/export-plan` creating dry-run candidate observation plans with speckle and resolution disclaimers, gated behind `ENABLE_GEE_TASKS=false`.
- [x] Frontend Multi-Engine & Satellite Dashboard (`frontend/src/App.tsx`, `App.css`):
  - [x] Responsive 4-way sub-navigation bar inside "🌊 Scenarios & Simulation" tab:
    - [x] `Delft3D FM (SWE)`: HydroMT builder, scenario parameter editor, package download, gated simulation runner, run history.
    - [x] `PySPH Solver`: Benchmark parameter controls (particle spacing, time step), package generator, gated execution, SPH run logs.
    - [x] `Comparison`: Run pairing selector, spatial overlap KPIs, depth/velocity error metrics, and physical methodology comparison matrix.
    - [x] `Earth Engine`: Approved satellite collection selector, ROI & date range configuration, candidate water-change observation plan generator.
- [x] Test suite: Comprehensive pytest suites (`test_sph_api.py`, `test_comparison_api.py`, `test_gee_api.py`) with 79 passing tests verifying zero-trust gating, mocked subprocess execution, spatial alignment, and GEE dry-run plans.

---

## Phase 13: 3D Terrain & Decision Support Dashboard [NEXT]
- [ ] Interactive 2D Map View:
  * [ ] Temporal playback scrubber showing flood wave propagation over time.
- [ ] 3D WebGL Terrain Viewer:
  * [ ] Adapt and integrate Three.js terrain rendering from `new.html` to load real Hidkal DEM and flood depth surfaces.
  * [ ] Dynamic color ramp shading, water surface animation, and interactive orbit controls.
- [ ] Scenario Configuration & Decision Dashboard:
  * [ ] Dam breach parameter configuration panel (breach width, failure duration, initial reservoir level).
  * [ ] One-click export button for SHP, KML, and executive briefing reports.




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

## Phase 13: Final Validation, Demo Readiness, Deployment Packaging & SIH Presentation [COMPLETED]
- [x] Final Technical Audit & Robustness:
  - [x] GZip compression middleware (`GZipMiddleware`, `minimum_size=1000`) and dynamic `CORS_ORIGINS` environment configuration with safe localhost defaults.
  - [x] Safe HTTP Cache-Control headers (`public, max-age=3600` on tiles/legends).
  - [x] Centralized global exception handler shielding internal file paths, credentials, and stack traces.
  - [x] Path traversal immunity, coordinate bounding-box rejection (HTTP 422), and UUID validation across all endpoints.
- [x] Demo Reliability & Basemap Offline Resilience:
  - [x] MapLibre fallback dark background canvas with non-blocking offline basemap warning banner.
  - [x] Container-aware responsive 2-column grid HUD sub-navigation (`minmax(0, 1fr)`, `min-width: 0`) preventing label clipping.
  - [x] Strict disabled states and handler guards on multi-engine comparison and GEE cloud task buttons.
- [x] Automated Verification & One-Command Demo Scripts:
  - [x] `scripts/verify.ps1`: Automated PowerShell script executing all 79 Pytest tests and Vite/TypeScript production build with clean exit code output.
  - [x] `scripts/demo.ps1`: Automated launcher checking local Hidkal datasets, Python/Node prerequisites, safe port reuse, health verification, and browser dashboard startup.
- [x] Production Deployment Templates:
  - [x] `.env.example`: Comprehensive environment configuration template for CORS, runtime store, D-Flow FM, PySPH, and GEE feature gates.
  - [x] `Dockerfile` & `docker-compose.yml`: Unverified multi-stage container templates with read-only data mounts and isolated persistent runtime storage.
- [x] Comprehensive SIH Documentation Suite (`docs/`):
  - [x] `docs/ARCHITECTURE.md`: Detailed component specifications and Mermaid data-flow diagram.
  - [x] `docs/VALIDATION_REPORT.md`: Complete audit records, 79/79 test breakdown, build times, and smoke test results.
  - [x] `docs/LIMITATIONS.md`: Scientific caveats on unverified sample rasters, representative-point screening, illustrative valuations, route limitations, and engine gating.
  - [x] `docs/DEMO_SCRIPT.md`: Truthful, click-by-click 5-minute SIH live demonstration walkthrough.
  - [x] `docs/PRESENTATION_OUTLINE.md`: 10-slide competition pitch deck.
  - [x] `docs/JUDGE_QA.md`: Technical defense questions and concise, truthful answers.
  - [x] `docs/DEPLOYMENT.md`: Step-by-step local and production deployment guide with NGINX reverse-proxy configuration.
  - [x] `docs/FINAL_STATUS.md`: Feature completion, integration-ready frameworks, and externally blocked prerequisites matrix.

---

## Phase 14: Hydrodynamic Solver Execution & Dam-Break Validation Benchmark [COMPLETED]
- [x] Isolated Solver Environment (`environment_anuga.yml`):
  - [x] Created isolated `sih-anuga` conda environment using conda-forge (`anuga=4.0.0`, `python=3.10`, `numpy`, `scipy`, `matplotlib`, `netcdf4`).
  - [x] Preserved existing `sih-app` environment and existing Delft3D / PySPH integration boundaries intact.
- [x] Reproducible 2D Dam-Break Benchmark (`validation/anuga_dam_break/`):
  - [x] Standard 2D rectangular flume: $L = 2000\text{ m}, W = 50\text{ m}, \Delta x = 10\text{ m}, \Delta y = 10\text{ m}$ ($4,000$ triangular elements).
  - [x] Physical parameters: Flat bed ($z_b = 0$), upstream depth $h_0 = 10.0\text{ m}$ ($x \le 1000\text{ m}$), downstream dry bed ($x > 1000\text{ m}$), frictionless ($n = 0.0$), gravity $g = 9.81\text{ m/s}^2$.
  - [x] Boundary conditions: Reflective on left, top, bottom; Transmissive on right.
  - [x] Solver execution: Executed genuine ANUGA finite-volume Shallow Water Equation solver for $T_{end} = 40.0\text{ s}$ ($\Delta t_{yield} = 1.0\text{ s}$, runtime $6.65\text{ s}$).
- [x] Quantitative Analytical Validation & Diagnostics:
  - [x] Comparison with **Ritter (1892)** analytical exact solution:
    - Centerline depth RMSE: **0.0480 m** (MAE: **0.0308 m**, Max Error: **0.1932 m**).
    - Relative volume / mass conservation error: **0.00e+00** (exact mass conservation from $501,666.67\text{ m}^3$).
    - Finite numerics check: All depth and velocity arrays strictly finite.
- [x] Cryptographic Manifest & Automated Test Suite:
  - [x] Generated `validation/anuga_dam_break/manifest.json` tracking SHA-256 hashes of `run_benchmark.py`, `centerline_t40s.csv`, and `benchmark_summary.json`.
  - [x] Excluded heavy binary SWW simulation files from git tracking via `.gitignore`.
  - [x] Added `backend/tests/test_anuga_benchmark.py` (4 automated tests) verifying manifest checksums, diagnostic bounds, centerline CSV integrity, and Ritter analytical limits. All 83 backend pytest tests passing.

---

## Phase 16: Safe Hydrodynamic Integration & Provenance Integrity [COMPLETED]
- [x] Result Registry & Provenance Verification:
  - [x] Registered `anuga_hidkal_pilot_hypothetical_v1` with whitelisted layer resolution (`depth`, `velocity`, `arrival`).
  - [x] Validated SHA-256 provenance manifest returning HTTP 409 `provenance_integrity_failed` on checksum mismatches without leaking file paths.
- [x] Vector & Scenario Cross-Service Propagation:
  - [x] Integrated `hazard_source=anuga_hidkal_pilot` across exposure screening, illustrative damage estimation, Dijkstra route screening, and GeoJSON/KML/Shapefile export.
  - [x] Maintained $0.10\text{ m}$ threshold consistency and strict assumption disclaimers.
- [x] Frontend Multi-Source UI Integration:
  - [x] Built hazard source switcher in dashboard HUD, dynamic provenance statistics card, and state reset on source toggle.

---

## Phase 17: Refined ANUGA Map Quality & Final Scientific Audit [COMPLETED]
- [x] Preserved Phase 15 baseline pilot outputs unmodified under `validation/anuga_hidkal_pilot/`.
- [x] Built and genuinely executed adaptive ANUGA simulation (`validation/anuga_hidkal_refined/`):
  - [x] Breach/channel zone: $\le 50\text{ m}$ ($1,250\text{ m}^2$).
  - [x] Downstream flood corridor: $\le 100\text{ m}$ ($5,000\text{ m}^2$).
  - [x] Outer domain: $\le 200\text{ m}$ ($20,000\text{ m}^2$).
  - [x] Measured breach discretization: 11 crossing edges (10 discrete intervals; edge lengths min 28.91 m, median 43.36 m, p95 60.99 m, max 93.75 m) across 200 m breach opening.
  - [x] Impermeable dam barrier preserved along non-breach axis (0.0 m³/s leakage verified via transect flux integration).
  - [x] Genuine execution in ~10.5 min for 131,351 triangles and 65,941 vertices.
- [x] Multi-Resolution Rigor & Scientific Clarity:
  - [x] Clearly distinguished numerical mesh resolution (≤ 50 m adaptive), exported visualization grid resolution (50 m GeoTIFF; outer domain supported by 100–200 m elements with interpolation), and display rendering (bilinear for continuous depth/velocity, nearest-neighbour for arrival).
  - [x] Exported GeoTIFFs with EPSG:32643 CRS, NoData masking, and "assumed" units.
  - [x] Generated SHA-256 manifest and `pilot_summary.json`.
- [x] Quantitative Volume-Matched Mesh Sensitivity Audit:
  - [x] Stored Volume Match: Baseline = 317.161860 MCM, Refined = 317.161857 MCM (within 0.0000009% via documented -0.356572 m numerical stage adjustment to 659.643428 m).
  - [x] Inundated Area ($h \ge 0.10\text{ m}$): Baseline = 44.47 km², Refined = 54.81 km² (Δ = +10.34 km² via `rasterio.warp.reproject` with transform cell area 0.009922 km²).
  - [x] Extent IoU: 0.7842.
  - [x] Volume-matched mesh sensitivity explicitly stated; numerical convergence not demonstrated.
  - [x] Aligned Depth Error: MAE = 0.9146 assumed m, RMSE = 1.2766 assumed m, Mean Bias = +0.0820 assumed m.
  - [x] Aligned Velocity Error: MAE = 0.6291 assumed m/s, RMSE = 0.8249 assumed m/s, Mean Bias = +0.1385 assumed m/s.
  - [x] Peak Extrema: Depth = 25.633 assumed m (Refined) vs 25.898 assumed m (Baseline); Velocity = 15.772 assumed m/s (Refined) vs 11.638 assumed m/s (Baseline).
  - [x] Peak Breach Discharge: Baseline ≈ 9,794.37 assumed m³/s vs Refined ≈ 21,953.43 assumed m³/s (approximate, not directly comparable due to 1-cell [one 200 m structured cross-mesh cell represented by four triangles and five vertices] vs 10-interval discretization).
  - [x] Embankment Non-Breach Leakage: Instantaneous rate = 0.0 assumed m³/s; Cumulative leakage = 0.0 assumed m³ (trapezoidal time-integration over 1,800 s).
  - [x] Exposure Screening Differences ($h \ge 0.10\text{ m}$): Assets exposed = 8 (Baseline) vs 62 (Refined), Δ = +54; Screening-positive road segments (depth ≥ 0.10 assumed metres) = 108 (Baseline) vs 128 (Refined), Δ = +20. (At threshold 0.0m, baseline exposes 29 assets due to 21 sub-threshold shallow assets).
- [x] API & Frontend Integration:
  - [x] Registered `anuga_hidkal_refined` in hazard source catalog, metadata, XYZ tiles (bilinear/nearest), point queries, exposure, damage, route, and export services.
  - [x] 3-option UI hazard selector with dynamic provenance HUD card.
- [x] Automated Tests & Verification:
  - [x] 106/106 pytest test suite passing (all 101 prior tests preserved + 5 refined model tests).
  - [x] Frontend production build passing (`npm run build`).
  - [x] Mandatory statement included: "Hypothetical refined ANUGA pilot — not a forecast or validated Hidkal prediction."

---

## Phase 18: Generalized Dam / River Ingestion [COMPLETED]
- [x] Backend Schema Enhancements (`backend/app/schemas.py`):
  - [x] Added `DamPointMetadata` with `dam_name`, `latitude`, `longitude`, `elevation_sampled`, `elevation_source`.
  - [x] Added `EngineeringParameters` with `dam_height`, `crest_elevation`, `pool_elevation`, `freeboard`, `manning_n`.
  - [x] Added `DamProjectReadinessResponse` with `ready_for_screening`, `ready_for_simulation`, `missing_for_simulation`, `checklist`, and `recommended_actions`.
  - [x] Extended `RasterDerivedMetadata` with `mean_elevation`, `valid_pixel_count`, `nodata_pixel_count`, `file_sha256`.
  - [x] Extended `DamProjectSummary`, `DamProjectDetailResponse`, `DamProjectValidationResponse`, `NormalizedProjectMetadata`, and `UserProvidedMetadata` with Phase 18 fields.
- [x] Onboarding Service Generalization (`backend/app/onboarding_service.py`):
  - [x] Generalized `validate_dam_project_dataset` & `save_dam_project`: made `dam_axis_bytes` optional; accepts `dam_name`, `latitude`, `longitude`, `dam_height`, `crest_elevation`, `pool_elevation`, `manning_n`.
  - [x] Implemented DEM point elevation sampling for the dam point.
  - [x] Implemented physical validation: `crest_elevation > pool_elevation` and computed `freeboard`.
  - [x] Decoupled project structure: saves minimal project with `dem.tif`, `project.json`, and SHA-256 `manifest.json`.
  - [x] Maintained scientific invariants: `scientific_status = "validated_unverified"` and `scientifically_verified = False`.
  - [x] Added `get_dam_project_dem_legend` returning elevation color ramp stops and range for custom DEMs.
  - [x] Added `get_dam_project_dam_marker_geometry` returning EPSG:4326 GeoJSON Point FeatureCollection with dam attributes.
  - [x] Added `assess_project_simulation_readiness` returning screening vs. ANUGA simulation readiness checklist.
  - [x] Preserved legacy vector onboarding backwards compatibility (full compatibility with 2-file DEM + vector workflows).
- [x] API Router Endpoints (`backend/app/main.py`):
  - [x] Updated `POST /api/dam-projects/validate` and `POST /api/dam-projects` with optional `dam_axis_file` and Phase 18 parameters.
  - [x] Added `GET /api/dam-projects/{id}/dem/legend`.
  - [x] Added `GET /api/dam-projects/{id}/geometry/dam-marker`.
  - [x] Added `GET /api/dam-projects/{id}/readiness`.
  - [x] Added `GET /api/dam-projects/{id}/dem/value?lon=&lat=`.
- [x] Frontend Implementation (`frontend/src/`):
  - [x] Synchronized TypeScript definitions in `types/damProjects.ts`.
  - [x] Exported Phase 18 API helper functions in `api/damProjects.ts`.
  - [x] Added dam marker pin layer and smart coordinate bounds centering in `components/onboarding/useDamProjectMap.ts`.
  - [x] Built modern guided onboarding wizard in `components/onboarding/DamOnboardingPanel.tsx` and `DamOnboardingPanel.css`.
  - [x] Enhanced `components/onboarding/DamProjectMapLegend.tsx` with dam metadata and unverified status badge.
  - [x] Updated `App.tsx` point probe to sample custom project DEM elevation and synced effect dependencies.
- [x] Automated Testing & Quality Assurance:
  - [x] Created `backend/tests/test_generalized_onboarding_phase18.py` (12/12 tests passing).
  - [x] Verified all 51 onboarding tests in repository pass 100%.
  - [x] Verified `npm run lint` passes with 0 errors and 0 warnings.
  - [x] Verified `npm run build` generates production bundle cleanly.

---

## Phase 19: Live ANUGA Execution for Generalized Dam Projects [COMPLETED]
- [x] Capability Detection & Multi-Environment Gating:
  - [x] Built dynamic discovery function `get_custom_anuga_capabilities` inspecting active Python executable, ANUGA package importability, version provenance, and execution enable/disable state (`ENABLE_CUSTOM_ANUGA_EXECUTION`).
  - [x] Eliminated single-developer hardcoded path dependencies; safely probes host environments without raising unhandled exceptions.
  - [x] Added `DamProjectAnugaCapabilitiesResponse` schema and endpoint `GET /api/dam-projects/anuga/capabilities`.
- [x] 5-Tier Progressive Simulation Readiness Model:
  - [x] Implemented structured 5-tier assessment:
    - Tier 1: `data_ready` (DEM valid, single-band, valid coordinate bounds, dam point location).
    - Tier 2: `geometry_ready` (dam axis line, downstream corridor / domain boundary, downstream outlet point).
    - Tier 3: `hydraulic_ready` (reservoir boundary / initial stage pool, stage-storage representation, breach location & dimensions, downstream Manning's n).
    - Tier 4: `solver_ready` (target mesh resolution, duration, timestep, solver stability parameters).
    - Tier 5: `simulation_ready` (composite flag requiring all 4 tiers + host capability gating check).
  - [x] Returns detailed `tier_breakdown` (`data_tier`, `geometry_tier`, `hydraulic_tier`, `solver_tier`, `simulation_tier`) via `GET /api/dam-projects/{id}/readiness`.
- [x] Terrain-Heuristic Hydraulic Assist & Strict Scientific Caveat:
  - [x] Implemented `compute_terrain_heuristic_assist` calculating DEM slope gradient aspect at dam marker point to derive candidate dam axis, breach cut, downstream corridor, outlet point, and upstream reservoir boundary.
  - [x] Strictly tagged all generated geometries with `source="terrain_heuristic"`, `scientifically_verified=false`, and `confidence="low_unverified"`.
  - [x] Geometry containment guaranteed: reservoir boundary strictly contained within model domain polygon and touches the dam axis.
  - [x] Implemented `POST /api/dam-projects/{id}/heuristic-assist` for pre-calculation inspection.
  - [x] Built `save_project_simulation_inputs` with strict safeguard: rejects terrain-heuristic inputs with HTTP 422 if `accept_heuristic_inputs` is not explicitly set to `True`.
  - [x] Implemented `POST /api/dam-projects/{id}/simulation-inputs` writing GeoJSON boundaries with valid metadata, updating `project.json` and cryptographic `manifest.json`.
- [x] Reproducible ANUGA Package Builder & Run Manifest:
  - [x] Built standalone package generator producing an immutable ZIP bundle containing:
    - `run_anuga_project.py` (self-contained simulation runner).
    - `postprocess_project.py` (SWW to GeoTIFF / NetCDF conversion pipeline).
    - `run_manifest.json` with cryptographic parameter snapshot (SHA-256 of all inputs).
    - Standalone `environment.yml` for isolated reproduction.
    - `dem.tif` and all input vector boundary GeoJSON files.
    - `README_REQUIREMENTS.txt` documenting scientific caveats and execution instructions.
  - [x] Available via `GET /api/dam-projects/{id}/anuga/download-package`.
- [x] 7-State Execution Lifecycle & Gated Subprocess Management:
  - [x] Implemented robust execution lifecycle (`queued`, `preparing`, `running`, `postprocessing`, `completed`, `failed`, `cancelled`, `timed_out`, `interrupted`).
  - [x] Enforced mandatory user acknowledgment (`acknowledge_hypothetical_simulation=True`) to launch simulations (`POST /api/dam-projects/{id}/anuga/run`).
  - [x] Strictly gated against missing ANUGA solver: returns HTTP 403 `custom_anuga_execution_disabled` when host environment lacks ANUGA, preventing fabricated outputs.
  - [x] Implemented asynchronous task cancellation (`POST /api/dam-projects/{id}/anuga/runs/{run_id}/cancel`) with PID termination and state cleanup.
  - [x] Implemented execution progress polling and live log streaming (`GET /api/dam-projects/{id}/anuga/runs/{run_id}/logs`).
- [x] Rigorous Output Validation & Hazard Serving:
  - [x] Enhanced `validate_sww_file` in `anuga_postprocessing_service.py` to enforce non-zero hydrodynamic depth (`max(stage - elevation) > 0.0001 m`), valid NetCDF readability, and minimum timestep threshold ($\ge 2$ timesteps).
  - [x] Added `GET /api/dam-projects/{id}/anuga/runs/{run_id}/outputs` reporting validation status, generated rasters, peak depth/velocity, and file hashes.
  - [x] Registered custom run hazard layers for raster tiling, point queries, and GIS overlays.
- [x] Frontend Decision-Support UI (`DamProjectAnugaReadiness.tsx`):
  - [x] 5-Tier Readiness badges HUD with real-time status indicators.
  - [x] Interactive Terrain-Heuristic Assist accordion with prominent warning banner, generated parameter summary, and explicit acknowledgment checkbox.
  - [x] Simulation parameter controls (run duration, output interval, target mesh resolution).
  - [x] Simulation launcher with mandatory hypothetical simulation acknowledgment modal/checkbox.
  - [x] Active run monitoring with progress bar, live log console, and cancellation button.
  - [x] Post-run hazard layer viewer and package download button.
- [x] Automated Testing & Quality Assurance:
  - [x] Created `backend/tests/test_generalized_anuga_phase19.py` (12/12 tests passing).
  - [x] All 63 onboarding and generalized test cases passing 100%.
  - [x] Frontend `npm run lint` passing with 0 errors / 0 warnings.
  - [x] Frontend `npm run build` compiling production bundle cleanly.

---

## Phase 20: Live Google Earth Engine / Remote-Sensing Integration [COMPLETED]
- [x] Dynamic GEE Capability Detection (`backend/app/gee_service.py`):
  - [x] Enhanced `check_gee_capabilities` to inspect `earthengine-api` availability, Application Default Credentials (`ADC`), and dynamic `GEE_PROJECT_ID` configuration.
  - [x] Returns expanded `GEECapabilitiesResponse` reporting `gee_available`, `authenticated`, `project_configured`, `earthengine_import_success`, `gee_project_id`, `reason`, and `supported_datasets`.
  - [x] Exposes endpoint `GET /api/gee/capabilities`.
- [x] Project-Scoped Area of Interest (AOI) Derivation (`backend/app/earth_observation_service.py`):
  - [x] Implemented `derive_project_aoi` deriving bounding box and polygon from `model_domain.geojson`, `suggested_model_domain`, or `dem.tif` extent.
  - [x] Applies configurable metric buffer (default 2,000 m) with UTM planar projection and calculates precise AOI area ($\text{km}^2$).
  - [x] Exposes endpoint `GET /api/dam-projects/{id}/earth-observation/aoi?buffer_meters=`.
- [x] Zero-Fabrication Fallback & Earth Observation Run Lifecycle:
  - [x] Strict scientific zero-fabrication enforcement: when Earth Engine is unauthenticated, missing, or lacks a configured project, the pipeline NEVER fabricates fake Sentinel-1 scenes, fake JRC water, or fake IMERG rainfall.
  - [x] Fallback mode validates query, derives AOI, documents intended GEE parameters, and returns truthful status (`gee_unavailable`, `authentication_required`, `project_not_configured`, `no_imagery_available`).
  - [x] Synthetic observations are strictly isolated to explicit offline unit test fixtures (`synthetic_test_fixture=True`).
  - [x] Implemented run persistence under `runtime/dam_projects/{id}/earth_observation/{eo_run_id}/` storing `request.json`, `provenance.json`, `statistics.json`, `processing.log`, and `run.json`.
  - [x] Exposes endpoints:
    - `POST /api/dam-projects/{id}/earth-observation/runs`
    - `GET /api/dam-projects/{id}/earth-observation/runs`
    - `GET /api/dam-projects/{id}/earth-observation/runs/{eo_run_id}`
    - `GET /api/dam-projects/{id}/earth-observation/runs/{eo_run_id}/logs`
- [x] Sentinel-1 SAR Flood Mapping & Configurable Heuristics:
  - [x] Thresholds are configurable initial defaults (change threshold: -3.0 dB, post-event water threshold: -15.0 dB, polarization: VV/VH/both).
  - [x] Provenance records `threshold_source = "configurable_heuristic"`, orbit metadata, and temporal windows.
  - [x] Resulting pixels labeled strictly as `candidate_inundation` (never confirmed flood).
- [x] JRC Water & GPM IMERG Rainfall Integration:
  - [x] JRC Global Surface Water occurrence mask to differentiate permanent water from transient flood inundation.
  - [x] NASA GPM / IMERG precipitation accumulation and time series tracking.
- [x] Observed vs Modelled Comparison Engine:
  - [x] Evaluates spatial agreement between ANUGA 2D hydrodynamic simulation rasters (`maximum_depth.tif`) and satellite observation masks.
  - [x] Computes overlap ($\text{km}^2$), union ($\text{km}^2$), model-only ($\text{km}^2$), satellite-only ($\text{km}^2$), and Intersection over Union ($IoU$ / Jaccard Index).
  - [x] Strictly labeled `"model-observation spatial agreement"` (explicitly NOT labeled "simulation accuracy").
  - [x] Configurable `max_observation_time_delta_hours` (default 72h) with temporal validity tracking and mismatch warnings.
  - [x] Exposes endpoint `POST /api/dam-projects/{id}/earth-observation/compare`.
- [x] Frontend Decision-Support Studio (`EarthObservationPanel.tsx` & `.css`):
  - [x] Embedded Earth Observation studio accessible from project card in `DamOnboardingPanel.tsx`.
  - [x] Live GEE capability HUD with offline/zero-fabrication fallback badge.
  - [x] Interactive AOI viewer with buffer expansion slider.
  - [x] Query builder for Sentinel-1 heuristics, JRC water, and IMERG rainfall.
  - [x] Earth observation runs history list with metrics grid and live log viewer.
  - [x] Model vs. observation comparison runner with IoU agreement KPI banner, temporal validity alert, and scientific uncertainty caveats.
- [x] Automated Testing & Quality Assurance:
  - [x] Created `backend/tests/test_gee_phase20.py` (10/10 tests passing).
  - [x] Ran complete backend test suite: 188 passed, 6 skipped, 0 regressions.
  - [x] Frontend `npm run lint` passing with 0 errors and 0 warnings.
  - [x] Frontend `npm run build` compiling production bundle cleanly.

---

## Phase 21: Multi-Engine Spatial Hydrodynamic Comparison [CURRENT - COMPLETED]
- [x] Normalized Solver Output Contract (`backend/app/schemas.py`, `backend/app/model_comparison_service.py`):
  - [x] Implemented `HydrodynamicOutputContract` normalizing solver outputs across ANUGA, Delft3D FM, and PySPH.
  - [x] Independent availability flags: `maximum_depth_available`, `maximum_velocity_available`, `arrival_time_available`, `inundation_extent_available`.
  - [x] Preserves native CRS, native resolution, analysis CRS, analysis resolution, bounds, file hashes, run timestamps, solver versions, and `scientific_status`.
- [x] Projected Metric Grid Analysis & Common Valid Mask (Mandatory Corrections 1, 2, 3):
  - [x] All area statistics (inundated area, overlap, model-only areas, union, spread) computed on a projected metric grid (e.g. local UTM zone) derived via `determine_analysis_metric_crs`.
  - [x] Excludes degree-based EPSG:4326 pixel area distortion.
  - [x] Strict common valid analysis mask: evaluates pairwise statistics exclusively on pixels where both compared models contain valid data; tracks `common_valid_pixel_count` and `common_analysis_area_km2`.
  - [x] Never treats NoData as zero-depth water.
  - [x] Resampling: bilinear continuous interpolation for depth/velocity/arrival-time rasters; nearest-neighbour for categorical masks; full provenance logged.
- [x] Real Engine Outputs & Honest Capability Matrix (Mandatory Corrections 4, 11):
  - [x] Discovers real runs for ANUGA, Delft3D/D-Flow FM, and PySPH without fabricating missing rasters.
  - [x] Distinguishes `environment_available`, `solver_available`, `completed_run_count`, `comparable_run_count`, and `available_for_comparison`.
  - [x] Exposes endpoint `GET /api/dam-projects/{id}/model-comparison/capabilities`.
- [x] Inter-Model Depth Difference & Configurable Tolerances (Mandatory Correction 6):
  - [x] Computes signed difference ($A - B$), mean signed difference, median signed difference, MAE, RMSE, max positive difference, max negative difference.
  - [x] Configurable tolerance bands ($\pm 0.10$ m, $\pm 0.25$ m, $\pm 0.50$ m) with percentage coverage of common analysis area.
  - [x] Labeled strictly as `"inter-model depth difference"` (never model error).
- [x] Velocity & Arrival-Time Inter-Model Comparison (Mandatory Corrections 7, 9):
  - [x] Velocity comparison computed only when both real runs contain valid velocity products; otherwise marked `available=False` with explicit reason (never synthesized).
  - [x] Arrival-time comparison validates threshold definition compatibility (`threshold_definition_a`, `threshold_definition_b`). If incompatible, marks `comparison_valid=False` and suppresses misleading metrics.
- [x] Inundation Extent Agreement & Inter-Model Spread Diagnostic (Mandatory Corrections 8, 10):
  - [x] Derives inundation footprints using configurable depth threshold (default 0.10 m); calculates overlap ($\text{km}^2$), union ($\text{km}^2$), A-only ($\text{km}^2$), B-only ($\text{km}^2$), and Intersection over Union ($IoU$).
  - [x] Labeled strictly as `"inter-model spatial agreement"` (never accuracy, validation, or truth).
  - [x] Computes ensemble spread diagnostic ($max - min$ depth, mean spread, max spread) labeled `"inter-model spread"` (never uncertainty quantification or confidence interval).
- [x] Persistence & Tile Serving (Mandatory Corrections 12, 13):
  - [x] Persists comparisons under `runtime/dam_projects/{id}/comparisons/{comparison_id}/` (`comparison.json`, `statistics.json`, `provenance.json`, `processing.log`, `depth_difference.tif`, `inundation_overlap.tif`, `inter_model_spread.tif`).
  - [x] Secure tile access via `GET /api/dam-projects/{id}/model-comparison/runs/{comparison_id}/tiles/{layer}/{z}/{x}/{y}.png`.
  - [x] Diverging color ramp semantics: Cyan = Engine A lower than Engine B; Gray = Similar; Red = Engine A higher than Engine B.
- [x] Frontend Decision Studio (`ModelComparisonPanel.tsx` & `.css`, `DamOnboardingPanel.tsx`):
  - [x] Engine capability cards with honest availability states for ANUGA, Delft3D FM, and PySPH.
  - [x] Pairwise solver and run selection pickers.
  - [x] Results KPI HUD (Spatial Agreement IoU, Overlap, Model-only areas, Depth MAE/RMSE, Velocity delta, Arrival-time delta, Inter-model spread diagnostic).
  - [x] Prominent scientific disclaimer banner.
- [x] Quantitative Volume-Matched Mesh Sensitivity Audit:
  - [x] Stored Volume Match: Baseline = 317.161860 MCM, Refined = 317.161857 MCM (within 0.0000009% via documented -0.356572 m numerical stage adjustment to 659.643428 m).
  - [x] Inundated Area ($h \ge 0.10\text{ m}$): Baseline = 44.47 km², Refined = 54.81 km² (Δ = +10.34 km² via `rasterio.warp.reproject` with transform cell area 0.009922 km²).
  - [x] Extent IoU: 0.7842.
  - [x] Volume-matched mesh sensitivity explicitly stated; numerical convergence not demonstrated.
  - [x] Aligned Depth Error: MAE = 0.9146 assumed m, RMSE = 1.2766 assumed m, Mean Bias = +0.0820 assumed m.
  - [x] Aligned Velocity Error: MAE = 0.6291 assumed m/s, RMSE = 0.8249 assumed m/s, Mean Bias = +0.1385 assumed m/s.
  - [x] Peak Extrema: Depth = 25.633 assumed m (Refined) vs 25.898 assumed m (Baseline); Velocity = 15.772 assumed m/s (Refined) vs 11.638 assumed m/s (Baseline).
  - [x] Peak Breach Discharge: Baseline ≈ 9,794.37 assumed m³/s vs Refined ≈ 21,953.43 assumed m³/s (approximate, not directly comparable due to 1-cell [one 200 m structured cross-mesh cell represented by four triangles and five vertices] vs 10-interval discretization).
  - [x] Embankment Non-Breach Leakage: Instantaneous rate = 0.0 assumed m³/s; Cumulative leakage = 0.0 assumed m³ (trapezoidal time-integration over 1,800 s).
  - [x] Exposure Screening Differences ($h \ge 0.10\text{ m}$): Assets exposed = 8 (Baseline) vs 62 (Refined), Δ = +54; Screening-positive road segments (depth ≥ 0.10 assumed metres) = 108 (Baseline) vs 128 (Refined), Δ = +20. (At threshold 0.0m, baseline exposes 29 assets due to 21 sub-threshold shallow assets).
- [x] API & Frontend Integration:
  - [x] Registered `anuga_hidkal_refined` in hazard source catalog, metadata, XYZ tiles (bilinear/nearest), point queries, exposure, damage, route, and export services.
  - [x] 3-option UI hazard selector with dynamic provenance HUD card.
- [x] Automated Tests & Verification:
  - [x] 106/106 pytest test suite passing (all 101 prior tests preserved + 5 refined model tests).
  - [x] Frontend production build passing (`npm run build`).
  - [x] Mandatory statement included: "Hypothetical refined ANUGA pilot — not a forecast or validated Hidkal prediction."

---

## Phase 18: Generalized Dam / River Ingestion [COMPLETED]
- [x] Backend Schema Enhancements (`backend/app/schemas.py`):
  - [x] Added `DamPointMetadata` with `dam_name`, `latitude`, `longitude`, `elevation_sampled`, `elevation_source`.
  - [x] Added `EngineeringParameters` with `dam_height`, `crest_elevation`, `pool_elevation`, `freeboard`, `manning_n`.
  - [x] Added `DamProjectReadinessResponse` with `ready_for_screening`, `ready_for_simulation`, `missing_for_simulation`, `checklist`, and `recommended_actions`.
  - [x] Extended `RasterDerivedMetadata` with `mean_elevation`, `valid_pixel_count`, `nodata_pixel_count`, `file_sha256`.
  - [x] Extended `DamProjectSummary`, `DamProjectDetailResponse`, `DamProjectValidationResponse`, `NormalizedProjectMetadata`, and `UserProvidedMetadata` with Phase 18 fields.
- [x] Onboarding Service Generalization (`backend/app/onboarding_service.py`):
  - [x] Generalized `validate_dam_project_dataset` & `save_dam_project`: made `dam_axis_bytes` optional; accepts `dam_name`, `latitude`, `longitude`, `dam_height`, `crest_elevation`, `pool_elevation`, `manning_n`.
  - [x] Implemented DEM point elevation sampling for the dam point.
  - [x] Implemented physical validation: `crest_elevation > pool_elevation` and computed `freeboard`.
  - [x] Decoupled project structure: saves minimal project with `dem.tif`, `project.json`, and SHA-256 `manifest.json`.
  - [x] Maintained scientific invariants: `scientific_status = "validated_unverified"` and `scientifically_verified = False`.
  - [x] Added `get_dam_project_dem_legend` returning elevation color ramp stops and range for custom DEMs.
  - [x] Added `get_dam_project_dam_marker_geometry` returning EPSG:4326 GeoJSON Point FeatureCollection with dam attributes.
  - [x] Added `assess_project_simulation_readiness` returning screening vs. ANUGA simulation readiness checklist.
  - [x] Preserved legacy vector onboarding backwards compatibility (full compatibility with 2-file DEM + vector workflows).
- [x] API Router Endpoints (`backend/app/main.py`):
  - [x] Updated `POST /api/dam-projects/validate` and `POST /api/dam-projects` with optional `dam_axis_file` and Phase 18 parameters.
  - [x] Added `GET /api/dam-projects/{id}/dem/legend`.
  - [x] Added `GET /api/dam-projects/{id}/geometry/dam-marker`.
  - [x] Added `GET /api/dam-projects/{id}/readiness`.
  - [x] Added `GET /api/dam-projects/{id}/dem/value?lon=&lat=`.
- [x] Frontend Implementation (`frontend/src/`):
  - [x] Synchronized TypeScript definitions in `types/damProjects.ts`.
  - [x] Exported Phase 18 API helper functions in `api/damProjects.ts`.
  - [x] Added dam marker pin layer and smart coordinate bounds centering in `components/onboarding/useDamProjectMap.ts`.
  - [x] Built modern guided onboarding wizard in `components/onboarding/DamOnboardingPanel.tsx` and `DamOnboardingPanel.css`.
  - [x] Enhanced `components/onboarding/DamProjectMapLegend.tsx` with dam metadata and unverified status badge.
  - [x] Updated `App.tsx` point probe to sample custom project DEM elevation and synced effect dependencies.
- [x] Automated Testing & Quality Assurance:
  - [x] Created `backend/tests/test_generalized_onboarding_phase18.py` (12/12 tests passing).
  - [x] Verified all 51 onboarding tests in repository pass 100%.
  - [x] Verified `npm run lint` passes with 0 errors and 0 warnings.
  - [x] Verified `npm run build` generates production bundle cleanly.

---

## Phase 19: Live ANUGA Execution for Generalized Dam Projects [COMPLETED]
- [x] Capability Detection & Multi-Environment Gating:
  - [x] Built dynamic discovery function `get_custom_anuga_capabilities` inspecting active Python executable, ANUGA package importability, version provenance, and execution enable/disable state (`ENABLE_CUSTOM_ANUGA_EXECUTION`).
  - [x] Eliminated single-developer hardcoded path dependencies; safely probes host environments without raising unhandled exceptions.
  - [x] Added `DamProjectAnugaCapabilitiesResponse` schema and endpoint `GET /api/dam-projects/anuga/capabilities`.
- [x] 5-Tier Progressive Simulation Readiness Model:
  - [x] Implemented structured 5-tier assessment:
    - Tier 1: `data_ready` (DEM valid, single-band, valid coordinate bounds, dam point location).
    - Tier 2: `geometry_ready` (dam axis line, downstream corridor / domain boundary, downstream outlet point).
    - Tier 3: `hydraulic_ready` (reservoir boundary / initial stage pool, stage-storage representation, breach location & dimensions, downstream Manning's n).
    - Tier 4: `solver_ready` (target mesh resolution, duration, timestep, solver stability parameters).
    - Tier 5: `simulation_ready` (composite flag requiring all 4 tiers + host capability gating check).
  - [x] Returns detailed `tier_breakdown` (`data_tier`, `geometry_tier`, `hydraulic_tier`, `solver_tier`, `simulation_tier`) via `GET /api/dam-projects/{id}/readiness`.
- [x] Terrain-Heuristic Hydraulic Assist & Strict Scientific Caveat:
  - [x] Implemented `compute_terrain_heuristic_assist` calculating DEM slope gradient aspect at dam marker point to derive candidate dam axis, breach cut, downstream corridor, outlet point, and upstream reservoir boundary.
  - [x] Strictly tagged all generated geometries with `source="terrain_heuristic"`, `scientifically_verified=false`, and `confidence="low_unverified"`.
  - [x] Geometry containment guaranteed: reservoir boundary strictly contained within model domain polygon and touches the dam axis.
  - [x] Implemented `POST /api/dam-projects/{id}/heuristic-assist` for pre-calculation inspection.
  - [x] Built `save_project_simulation_inputs` with strict safeguard: rejects terrain-heuristic inputs with HTTP 422 if `accept_heuristic_inputs` is not explicitly set to `True`.
  - [x] Implemented `POST /api/dam-projects/{id}/simulation-inputs` writing GeoJSON boundaries with valid metadata, updating `project.json` and cryptographic `manifest.json`.
- [x] Reproducible ANUGA Package Builder & Run Manifest:
  - [x] Built standalone package generator producing an immutable ZIP bundle containing:
    - `run_anuga_project.py` (self-contained simulation runner).
    - `postprocess_project.py` (SWW to GeoTIFF / NetCDF conversion pipeline).
    - `run_manifest.json` with cryptographic parameter snapshot (SHA-256 of all inputs).
    - Standalone `environment.yml` for isolated reproduction.
    - `dem.tif` and all input vector boundary GeoJSON files.
    - `README_REQUIREMENTS.txt` documenting scientific caveats and execution instructions.
  - [x] Available via `GET /api/dam-projects/{id}/anuga/download-package`.
- [x] 7-State Execution Lifecycle & Gated Subprocess Management:
  - [x] Implemented robust execution lifecycle (`queued`, `preparing`, `running`, `postprocessing`, `completed`, `failed`, `cancelled`, `timed_out`, `interrupted`).
  - [x] Enforced mandatory user acknowledgment (`acknowledge_hypothetical_simulation=True`) to launch simulations (`POST /api/dam-projects/{id}/anuga/run`).
  - [x] Strictly gated against missing ANUGA solver: returns HTTP 403 `custom_anuga_execution_disabled` when host environment lacks ANUGA, preventing fabricated outputs.
  - [x] Implemented asynchronous task cancellation (`POST /api/dam-projects/{id}/anuga/runs/{run_id}/cancel`) with PID termination and state cleanup.
  - [x] Implemented execution progress polling and live log streaming (`GET /api/dam-projects/{id}/anuga/runs/{run_id}/logs`).
- [x] Rigorous Output Validation & Hazard Serving:
  - [x] Enhanced `validate_sww_file` in `anuga_postprocessing_service.py` to enforce non-zero hydrodynamic depth (`max(stage - elevation) > 0.0001 m`), valid NetCDF readability, and minimum timestep threshold ($\ge 2$ timesteps).
  - [x] Added `GET /api/dam-projects/{id}/anuga/runs/{run_id}/outputs` reporting validation status, generated rasters, peak depth/velocity, and file hashes.
  - [x] Registered custom run hazard layers for raster tiling, point queries, and GIS overlays.
- [x] Frontend Decision-Support UI (`DamProjectAnugaReadiness.tsx`):
  - [x] 5-Tier Readiness badges HUD with real-time status indicators.
  - [x] Interactive Terrain-Heuristic Assist accordion with prominent warning banner, generated parameter summary, and explicit acknowledgment checkbox.
  - [x] Simulation parameter controls (run duration, output interval, target mesh resolution).
  - [x] Simulation launcher with mandatory hypothetical simulation acknowledgment modal/checkbox.
  - [x] Active run monitoring with progress bar, live log console, and cancellation button.
  - [x] Post-run hazard layer viewer and package download button.
- [x] Automated Testing & Quality Assurance:
  - [x] Created `backend/tests/test_generalized_anuga_phase19.py` (12/12 tests passing).
  - [x] All 63 onboarding and generalized test cases passing 100%.
  - [x] Frontend `npm run lint` passing with 0 errors / 0 warnings.
  - [x] Frontend `npm run build` compiling production bundle cleanly.

---

## Phase 20: Live Google Earth Engine / Remote-Sensing Integration [COMPLETED]
- [x] Dynamic GEE Capability Detection (`backend/app/gee_service.py`):
  - [x] Enhanced `check_gee_capabilities` to inspect `earthengine-api` availability, Application Default Credentials (`ADC`), and dynamic `GEE_PROJECT_ID` configuration.
  - [x] Returns expanded `GEECapabilitiesResponse` reporting `gee_available`, `authenticated`, `project_configured`, `earthengine_import_success`, `gee_project_id`, `reason`, and `supported_datasets`.
  - [x] Exposes endpoint `GET /api/gee/capabilities`.
- [x] Project-Scoped Area of Interest (AOI) Derivation (`backend/app/earth_observation_service.py`):
  - [x] Implemented `derive_project_aoi` deriving bounding box and polygon from `model_domain.geojson`, `suggested_model_domain`, or `dem.tif` extent.
  - [x] Applies configurable metric buffer (default 2,000 m) with UTM planar projection and calculates precise AOI area ($\text{km}^2$).
  - [x] Exposes endpoint `GET /api/dam-projects/{id}/earth-observation/aoi?buffer_meters=`.
- [x] Zero-Fabrication Fallback & Earth Observation Run Lifecycle:
  - [x] Strict scientific zero-fabrication enforcement: when Earth Engine is unauthenticated, missing, or lacks a configured project, the pipeline NEVER fabricates fake Sentinel-1 scenes, fake JRC water, or fake IMERG rainfall.
  - [x] Fallback mode validates query, derives AOI, documents intended GEE parameters, and returns truthful status (`gee_unavailable`, `authentication_required`, `project_not_configured`, `no_imagery_available`).
  - [x] Synthetic observations are strictly isolated to explicit offline unit test fixtures (`synthetic_test_fixture=True`).
  - [x] Implemented run persistence under `runtime/dam_projects/{id}/earth_observation/{eo_run_id}/` storing `request.json`, `provenance.json`, `statistics.json`, `processing.log`, and `run.json`.
  - [x] Exposes endpoints:
    - `POST /api/dam-projects/{id}/earth-observation/runs`
    - `GET /api/dam-projects/{id}/earth-observation/runs`
    - `GET /api/dam-projects/{id}/earth-observation/runs/{eo_run_id}`
    - `GET /api/dam-projects/{id}/earth-observation/runs/{eo_run_id}/logs`
- [x] Sentinel-1 SAR Flood Mapping & Configurable Heuristics:
  - [x] Thresholds are configurable initial defaults (change threshold: -3.0 dB, post-event water threshold: -15.0 dB, polarization: VV/VH/both).
  - [x] Provenance records `threshold_source = "configurable_heuristic"`, orbit metadata, and temporal windows.
  - [x] Resulting pixels labeled strictly as `candidate_inundation` (never confirmed flood).
- [x] JRC Water & GPM IMERG Rainfall Integration:
  - [x] JRC Global Surface Water occurrence mask to differentiate permanent water from transient flood inundation.
  - [x] NASA GPM / IMERG precipitation accumulation and time series tracking.
- [x] Observed vs Modelled Comparison Engine:
  - [x] Evaluates spatial agreement between ANUGA 2D hydrodynamic simulation rasters (`maximum_depth.tif`) and satellite observation masks.
  - [x] Computes overlap ($\text{km}^2$), union ($\text{km}^2$), model-only ($\text{km}^2$), satellite-only ($\text{km}^2$), and Intersection over Union ($IoU$ / Jaccard Index).
  - [x] Strictly labeled `"model-observation spatial agreement"` (explicitly NOT labeled "simulation accuracy").
  - [x] Configurable `max_observation_time_delta_hours` (default 72h) with temporal validity tracking and mismatch warnings.
  - [x] Exposes endpoint `POST /api/dam-projects/{id}/earth-observation/compare`.
- [x] Frontend Decision-Support Studio (`EarthObservationPanel.tsx` & `.css`):
  - [x] Embedded Earth Observation studio accessible from project card in `DamOnboardingPanel.tsx`.
  - [x] Live GEE capability HUD with offline/zero-fabrication fallback badge.
  - [x] Interactive AOI viewer with buffer expansion slider.
  - [x] Query builder for Sentinel-1 heuristics, JRC water, and IMERG rainfall.
  - [x] Earth observation runs history list with metrics grid and live log viewer.
  - [x] Model vs. observation comparison runner with IoU agreement KPI banner, temporal validity alert, and scientific uncertainty caveats.
- [x] Automated Testing & Quality Assurance:
  - [x] Created `backend/tests/test_gee_phase20.py` (10/10 tests passing).
  - [x] Ran complete backend test suite: 188 passed, 6 skipped, 0 regressions.
  - [x] Frontend `npm run lint` passing with 0 errors and 0 warnings.
  - [x] Frontend `npm run build` compiling production bundle cleanly.

---

## Phase 21: Multi-Engine Spatial Hydrodynamic Comparison [CURRENT - COMPLETED]
- [x] Normalized Solver Output Contract (`backend/app/schemas.py`, `backend/app/model_comparison_service.py`):
  - [x] Implemented `HydrodynamicOutputContract` normalizing solver outputs across ANUGA, Delft3D FM, and PySPH.
  - [x] Independent availability flags: `maximum_depth_available`, `maximum_velocity_available`, `arrival_time_available`, `inundation_extent_available`.
  - [x] Preserves native CRS, native resolution, analysis CRS, analysis resolution, bounds, file hashes, run timestamps, solver versions, and `scientific_status`.
- [x] Projected Metric Grid Analysis & Common Valid Mask (Mandatory Corrections 1, 2, 3):
  - [x] All area statistics (inundated area, overlap, model-only areas, union, spread) computed on a projected metric grid (e.g. local UTM zone) derived via `determine_analysis_metric_crs`.
  - [x] Excludes degree-based EPSG:4326 pixel area distortion.
  - [x] Strict common valid analysis mask: evaluates pairwise statistics exclusively on pixels where both compared models contain valid data; tracks `common_valid_pixel_count` and `common_analysis_area_km2`.
  - [x] Never treats NoData as zero-depth water.
  - [x] Resampling: bilinear continuous interpolation for depth/velocity/arrival-time rasters; nearest-neighbour for categorical masks; full provenance logged.
- [x] Real Engine Outputs & Honest Capability Matrix (Mandatory Corrections 4, 11):
  - [x] Discovers real runs for ANUGA, Delft3D/D-Flow FM, and PySPH without fabricating missing rasters.
  - [x] Distinguishes `environment_available`, `solver_available`, `completed_run_count`, `comparable_run_count`, and `available_for_comparison`.
  - [x] Exposes endpoint `GET /api/dam-projects/{id}/model-comparison/capabilities`.
- [x] Inter-Model Depth Difference & Configurable Tolerances (Mandatory Correction 6):
  - [x] Computes signed difference ($A - B$), mean signed difference, median signed difference, MAE, RMSE, max positive difference, max negative difference.
  - [x] Configurable tolerance bands ($\pm 0.10$ m, $\pm 0.25$ m, $\pm 0.50$ m) with percentage coverage of common analysis area.
  - [x] Labeled strictly as `"inter-model depth difference"` (never model error).
- [x] Velocity & Arrival-Time Inter-Model Comparison (Mandatory Corrections 7, 9):
  - [x] Velocity comparison computed only when both real runs contain valid velocity products; otherwise marked `available=False` with explicit reason (never synthesized).
  - [x] Arrival-time comparison validates threshold definition compatibility (`threshold_definition_a`, `threshold_definition_b`). If incompatible, marks `comparison_valid=False` and suppresses misleading metrics.
- [x] Inundation Extent Agreement & Inter-Model Spread Diagnostic (Mandatory Corrections 8, 10):
  - [x] Derives inundation footprints using configurable depth threshold (default 0.10 m); calculates overlap ($\text{km}^2$), union ($\text{km}^2$), A-only ($\text{km}^2$), B-only ($\text{km}^2$), and Intersection over Union ($IoU$).
  - [x] Labeled strictly as `"inter-model spatial agreement"` (never accuracy, validation, or truth).
  - [x] Computes ensemble spread diagnostic ($max - min$ depth, mean spread, max spread) labeled `"inter-model spread"` (never uncertainty quantification or confidence interval).
- [x] Persistence & Tile Serving (Mandatory Corrections 12, 13):
  - [x] Persists comparisons under `runtime/dam_projects/{id}/comparisons/{comparison_id}/` (`comparison.json`, `statistics.json`, `provenance.json`, `processing.log`, `depth_difference.tif`, `inundation_overlap.tif`, `inter_model_spread.tif`).
  - [x] Secure tile access via `GET /api/dam-projects/{id}/model-comparison/runs/{comparison_id}/tiles/{layer}/{z}/{x}/{y}.png`.
  - [x] Diverging color ramp semantics: Cyan = Engine A lower than Engine B; Gray = Similar; Red = Engine A higher than Engine B.
- [x] Frontend Decision Studio (`ModelComparisonPanel.tsx` & `.css`, `DamOnboardingPanel.tsx`):
  - [x] Engine capability cards with honest availability states for ANUGA, Delft3D FM, and PySPH.
  - [x] Pairwise solver and run selection pickers.
  - [x] Results KPI HUD (Spatial Agreement IoU, Overlap, Model-only areas, Depth MAE/RMSE, Velocity delta, Arrival-time delta, Inter-model spread diagnostic).
  - [x] Prominent scientific disclaimer banner.
  - [x] Map layer toggles with diverging legend.
- [x] Automated Testing & Quality Assurance (Mandatory Corrections 16, 17):
  - [x] Created `backend/tests/test_model_comparison_phase21.py` (11/11 tests passing).
  - [x] 0 regressions across Phase 18, 19, and 20 suites (34/34 passing).
  - [x] Frontend `npm run lint` passing with 0 warnings and 0 errors.
  - [x] Frontend `npm run build` compiling cleanly with exit code 0.

---

## Phase 22: Population, LULC, Infrastructure Exposure & Vulnerability Assessment [COMPLETED]
- [x] Standardized Hazard Source Contract (`backend/app/schemas.py`, `backend/app/exposure_service.py`):
  - [x] Validates completed custom hydrodynamic runs (`status == "completed"`, `maximum_depth.tif` exists and passes raster integrity checks).
  - [x] Optional layers (`maximum_velocity.tif`, `arrival_time.tif`) explicitly checked with `available=False` fallback when missing; no synthesis.
  - [x] Persists engine, run_id, engine_version, SHA-256 layer hashes, native CRS, analysis CRS, depth threshold, timestamp, and scientific status.
- [x] Population Semantics & Mass Conservation (Mandatory Correction 1, 8):
  - [x] Discovers and supports explicit semantics: `persons_per_cell` (absolute count) vs `persons_per_sq_km` (density).
  - [x] Resampling preserves mass: count rasters resampled using mass-conservation scaling factor; density rasters aggregated via pixel area integration. Bilinear interpolation strictly avoided for counts.
  - [x] Configurable depth bands (default: 0.0-0.10m, 0.10-0.50m, 0.50-1.00m, 1.00-2.00m, 2.00-3.00m, >3.00m).
  - [x] Outputs: `total_population_in_aoi`, `population_in_inundation_extent`, `population_by_depth_band`, `population_percentage_exposed`.
  - [x] Strict naming invariant: labeled `"population exposed"` (never "casualties", "fatalities", or "people killed").
- [x] Building Exposure with True Polygon Overlay (Mandatory Correction 2, 9):
  - [x] Prefer true polygon/raster overlap / zonal statistics (deriving max depth, mean depth, max velocity, earliest arrival, flooded footprint area).
  - [x] Representative point sampling preserved as documented fallback with sampling method recorded in provenance.
  - [x] Only classifies building usage when source attributes support it; no inference from geometry alone.
- [x] Segmented Road Exposure & Metric Lengths (Mandatory Correction 3, 10):
  - [x] Evaluates road exposure by spatial segmentation / intersection against inundation extent (not single-point classification).
  - [x] Computes metric lengths in projected CRS (`total_road_length_km`, `affected_road_length_km`, `affected_percentage`, `road_length_by_depth_band`, `road_class_breakdown`).
  - [x] Labeled `"potentially affected road segment"` (passability set to `road_passability_available = false` unless authoritative threshold is documented).
- [x] Critical Infrastructure Classification & Provenance (Mandatory Correction 4, 11):
  - [x] Maps source attributes to normalized categories only when supported by actual OSM tags (`hospital`, `school`, `bridge`, `substation`, etc.).
  - [x] Ambiguous or unlabeled features remain strictly `normalized_category = "unknown"` (never guessed).
  - [x] Preserves `original_source_category`, `source_dataset`, and `source_feature_id`.
- [x] Categorical LULC Flood Area (Mandatory Correction 12):
  - [x] Nearest-neighbour resampling only; persists class mapping.
  - [x] Unmapped integer classes preserved as `unknown` / `class_<value>`.
- [x] Separation of Vulnerability & Monetary Damage (Mandatory Correction 13, 14):
  - [x] Evaluates relative damage ratios using documented JRC vulnerability curves only when asset class, hazard variable, and units match.
  - [x] Monetary damage requires authoritative asset valuation datasets; without local valuation, returns `monetary_damage_available = false` and `monetary_damage = null` (zero fabricated rupee values).
- [x] Modelled Arrival-Time Windows (Mandatory Correction 15):
  - [x] Categorizes into windows (<15m, 15-30m, 30-60m, 1-2h, >2h) when arrival raster is available.
  - [x] Strictly labeled `"modelled arrival-time window"` (never "guaranteed warning time").
- [x] Decision-Support Priority Index & Hotspots (Mandatory Correction 16, 17):
  - [x] Weighted priority index labeled `"decision-support priority index"` (never "true risk" or "fatality risk") with exposed heuristic weights.
  - [x] Hotspots flagged with transparent reason codes (`high_depth_settlement`, `critical_asset_flooded`, `major_road_cutoff`, `fast_arrival_builtup`); never called "disaster zones".
- [x] Dataset Availability & Project-Scoped Persistence (Mandatory Correction 18, 19):
  - [x] Honest per-domain availability matrix (`available`, `source`, `reason_if_unavailable`); partial run completion supported.
  - [x] Persistent storage under `runtime/dam_projects/{project_id}/exposure_runs/{exposure_run_id}/` (`request.json`, `statistics.json`, `provenance.json`, `processing.log`, `assets_exposed.geojson`, `roads_exposed.geojson`).
- [x] Full REST API (Mandatory Correction 20):
  - [x] `GET /api/dam-projects/{id}/exposure/capabilities`
  - [x] `POST /api/dam-projects/{id}/exposure/runs`
  - [x] `GET /api/dam-projects/{id}/exposure/runs`
  - [x] `GET /api/dam-projects/{id}/exposure/runs/{run_id}`
  - [x] `GET /api/dam-projects/{id}/exposure/runs/{run_id}/logs`
  - [x] `GET /api/dam-projects/{id}/exposure/runs/{run_id}/assets`
  - [x] `GET /api/dam-projects/{id}/exposure/runs/{run_id}/roads`
  - [x] `GET /api/dam-projects/{id}/exposure/runs/{run_id}/layers`
- [x] Frontend Decision Studio (`ExposureVulnerabilityPanel.tsx` & `.css`, `DamOnboardingPanel.tsx`):
  - [x] Capability matrix HUD displaying honest dataset status (e.g. `Not provided` instead of `0`).
  - [x] Run configuration modal with depth band and priority weight inspector.
  - [x] Interactive results tabs: Overview, Population, Buildings, Roads, Critical Assets, LULC, Vulnerability & Damage, Priority & Hotspots.
  - [x] Interactive map layer toggles with scientific disclaimer badges.
- [x] Automated Testing & Quality Assurance (Mandatory Correction 23, 24):
  - [x] Created `backend/tests/test_exposure_vulnerability_phase22.py` (14/14 tests passing).
  - [x] 0 regressions across Phase 18, 19, 20, and 21 suites (59/59 passing).
  - [x] Frontend `npm run lint` passing with 0 warnings and 0 errors.
  - [x] Frontend `npm run build` compiling cleanly with exit code 0.

---

## Phase 23: Final SIH Integration, End-to-End Hardening & Demo Readiness [FINAL - COMPLETED]
- [x] Complete System Audit & Classification (backend, frontend, scripts, configs, documentation).
- [x] Decoupled ANUGA Capability Discovery & Execution Permission:
  - [x] 4-tier discovery (`ANUGA_PYTHON_EXECUTABLE`, active interpreter, Conda paths, Conda metadata).
  - [x] `ENABLE_CUSTOM_ANUGA_EXECUTION=false` by default; execution permission strictly decoupled from discovery.
  - [x] Resilient version handling for local `0.0.0+unknown` via import verification and solver execution proof.
  - [x] Developer path sanitization (`.../sih-anuga/python.exe` in frontend responses; no private local directory leakage).
- [x] Real ANUGA Engineering Solver Smoke Test (`backend/tests/test_anuga_real_smoke_phase23.py`):
  - [x] Real deterministic ANUGA Domain evolved in `sih-anuga` (2-triangle column collapse).
  - [x] Genuine NetCDF SWW file generation and Phase 19 `validate_sww_file` check.
  - [x] Linear triangular mesh interpolation postprocessing into `maximum_depth.tif`, `maximum_velocity.tif`, and `arrival_time.tif`.
  - [x] Automated temporary directory cleanup (zero runtime outputs left in source tree).
  - [x] Labeled `engineering_smoke_test = true`, `scientifically_verified = false`.
- [x] System Health Monitoring & Subsystem Gating:
  - [x] Backend endpoint `GET /api/system/health-summary` covering all 8 subsystems.
  - [x] Truthful statuses: `Ready`, `Available but not configured`, `Unavailable`, `Missing data`, `Failed`, `Execution disabled`.
  - [x] Reusable Frontend `SystemHealthPanel` (compact HUD chips + expandable diagnostics drawer).
- [x] Final User-Facing Product Stage Navigation (`DamOnboardingPanel.tsx` & `.css`, `App.tsx`):
  - [x] Replaced internal Phase terminology with 8 user-facing stages:
    1. Overview (Health HUD + active studies list)
    2. Study Setup (DEM & parameter onboarding form)
    3. Simulation (Readiness checklist + ANUGA builder & runner)
    4. Satellite Evidence (EarthObservationPanel)
    5. Model Comparison (ModelComparisonPanel)
    6. Exposure & Impact (ExposureVulnerabilityPanel)
    7. Decision Support (Priority indicators & export)
    8. Technical / Provenance (Manifests & scientific limitations)
  - [x] Active study selector across stages.
  - [x] Complete error states: loading, empty, error, unavailable across all workflows.
- [x] Vulnerability Curve Provenance Audit:
  - [x] Added `curve_provenance`, `region_applicability`, `curve_status = "unverified_reference"`, and `version_year = 2017`.
  - [x] Fully attributed to Joint Research Centre EUR 28552 EN (Huizinga et al., 2017).
- [x] Legacy Hidkal Tests Audit (`backend/tests/test_anuga_api.py`):
  - [x] Isolated 16 missing static raster tests with centralized `skipif(check_hidkal_anuga_assets_present)` decorator.
  - [x] Preserved full assertions when rasters are present.
  - [x] Result: 0 unexplained failures in pytest suite (215 passed, 22 skipped, 0 failed).
- [x] Frontend Static Analysis & Build Verification:
  - [x] Configured meaningful `oxlint -D correctness -D suspicious -A react/react-in-jsx-scope` (146 rules across 13 files).
  - [x] Fixed all genuine correctness and unused variable issues.
  - [x] `npm run lint`: 0 warnings, 0 errors in 715ms.
  - [x] `npm run build`: cleanly compiles production bundle into `dist/` in 1.07s.
- [x] Startup Scripts & Demonstration Runbook:
  - [x] `scripts/start-dev.ps1`: Safe multi-service launcher checking Node, npm, Python, port conflicts (8000, 5173).
  - [x] `scripts/verify-system.ps1`: Full audit script checking environments, static analysis, pytest, and build.
  - [x] `scripts/run-smoke-tests.ps1`: Dedicated ANUGA engineering smoke test runner.
  - [x] `DEMO_CHECKLIST.md`: 5-to-8 minute judge flow with contingency fallbacks.
- [x] Comprehensive Test Suite Execution:
  - [x] Full pytest suite: 215 passed, 22 skipped, 0 failed.

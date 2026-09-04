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

---

## Phase 2: Data Preprocessing, Normalization & Sanitization
- [ ] Implement robust raster sanitizer:
  - [ ] Remap `hidkal_arrival.tif` unflooded value `9999.0` to standard IEEE `NaN` / masked NoData.
  - [ ] Normalize dry cell representation across `depth`, `velocity`, and `arrival` layers.
  - [ ] Reproject Hidkal rasters from geographic EPSG:4326 to metric planar CRS (UTM Zone 43N / EPSG:32643) with bilinear/cubic resampling.
- [ ] DEM conditioning and hydro-enforcement:
  - [ ] Fill spurious depression sinks and burn main river channel centerlines.
  - [ ] Compute slope, aspect, and flow accumulation grids.
- [ ] Vector data preparation:
  - [ ] Clean and categorize `hidkal_assets.geojson` into physical vulnerability classes (residential, commercial, educational, medical, critical utilities).
  - [ ] Convert `hidkal_roads.graphml` into a spatial NetworkX graph with metric edge lengths, bridge tags, and speed limits.
- [ ] Build automated unit and regression tests for data sanitization pipelines.

---

## Phase 3: Hydrodynamic Simulation & Solver Comparison Engine
- [ ] Near-field SPH modeling interface:
  - [ ] Define dam breach geometry (trapezoidal / instantaneous / partial collapse parameters).
  * [ ] Interface with DualSPHysics / SPH solver to simulate 3D free-surface near-field dam-break surge.
  * [ ] Interpolate particle fields to Eulerian water depth and velocity grids.
- [ ] Far-field Delft3D-FM (2D SWE) modeling interface:
  * [ ] Generate flexible computational mesh (unstructured triangular/quadrilateral) for Ghataprabha valley.
  * [ ] Assign spatially distributed Manning's $n$ bed roughness based on LULC.
  * [ ] Apply breach inflow hydrograph (from SPH near-field or empirical Froehlich/MacDonald equations).
  * [ ] Execute 2D hydrodynamic simulation and extract time-series water surface elevation and flow velocities.
- [ ] Solver Intercomparison & Verification Module:
  * [ ] Compare peak water depths ($h_{max}$), peak velocities ($v_{max}$), arrival times ($t_{arr}$), and wave front speeds.
  * [ ] Compute spatial difference maps ($\Delta h = h_{SPH} - h_{Delft3D}$) and mass conservation metrics.
  * [ ] Quantify computational trade-offs (GPU runtime vs CPU mesh scalability).

---

## Phase 4: Exposure, Vulnerability & Damage Assessment Engine
- [ ] Multi-sector asset exposure analysis:
  * [ ] Intersect maximum flood extent with building footprints, schools, hospitals, and utilities.
  * [ ] Classify flood hazard levels based on USBR / DEFRA hazard rating ($H = d \times (v + 0.5) + DF$).
- [ ] Depth-damage curve modeling:
  * [ ] Integrate structural and contents depth-damage functions for Indian rural and peri-urban buildings.
  * [ ] Estimate economic losses (direct structural loss, inventory loss, agricultural crop loss).
- [ ] Critical road network & evacuation accessibility:
  * [ ] Identify submerged road segments and cut-off bridge crossings dynamically over simulation time steps.
  * [ ] Compute shortest safe evacuation routes from vulnerable settlements to designated relief centers.
  * [ ] Detect isolated clusters and estimate critical evacuation time windows before wave arrival.

---

## Phase 5: GIS & Multi-Format Export Pipeline
- [ ] Automated spatial layer exporter:
  * [ ] Export hazard zones and peak depths to ESRI Shapefile (`.shp`, `.shx`, `.dbf`, `.prj`).
  * [ ] Export styled 3D hazard polygons and time-stamped wavefronts to Google Earth KML/KMZ (`.kml`, `.kmz`).
  * [ ] Export vector layers to open OGC GeoPackage (`.gpkg`).
  * [ ] Export Cloud-Optimized GeoTIFFs (COG) with pyramids for rapid web mapping.
- [ ] Automated PDF / Markdown summary report generator (flood extent, affected population, disrupted roads, damage tally).

---

## Phase 6: Earth Observation & GEE Flood Validation Module
- [ ] Google Earth Engine (GEE) integration:
  * [ ] Authenticate and query Sentinel-1 SAR GRD collections (C-band VV/VH polarizations) for pre-flood and post-flood dates.
  * [ ] Apply speckle filtering (Lee/Refined Lee) and radiometric terrain correction.
  * [ ] Execute adaptive thresholding (Otsu method / bimodal distribution split) to delineate actual observed surface water.
- [ ] Calibration and validation analytics:
  * [ ] Overlay satellite-derived flood extent against model-simulated flood footprints.
  * [ ] Compute classification confusion matrix: True Positive (Hit), False Positive (Overprediction), False Negative (Underprediction).
  * [ ] Calculate critical success index ($CSI$), intersection over union ($IoU$), and Cohen's Kappa ($\kappa$).

---

## Phase 7: Interactive GUI, 3D Terrain & Decision Support Dashboard
- [ ] Interactive 2D Map View:
  * [ ] MapLibre GL / Leaflet map canvas with multi-layer overlays (DEM, depth, velocity, arrival, OSM assets, road status).
  * [ ] Temporal playback scrubber showing flood wave propagation over time.
- [ ] 3D WebGL Terrain Viewer:
  * [ ] Adapt and integrate Three.js terrain rendering from `new.html` to load real Hidkal DEM and flood depth surfaces.
  * [ ] Dynamic color ramp shading, water surface animation, and interactive orbit controls.
- [ ] Scenario Configuration & Decision Dashboard:
  * [ ] Dam breach parameter configuration panel (breach width, failure duration, initial reservoir level).
  * [ ] Real-time KPIs: inundated area ($\text{km}^2$), vulnerable population count, severed road length ($\text{km}$), estimated economic loss.
  * [ ] One-click export button for SHP, KML, and executive briefing reports.

---

## Phase 8: Benchmarking, Validation & Final Packaging
- [ ] End-to-end integration testing on Hidkal case study.
- [ ] Comprehensive documentation, API guides, and demonstration video / walkthrough.

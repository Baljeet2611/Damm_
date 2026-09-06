# SIH 2026 Presentation Outline: 10-Slide Deck

**Project Title**: Automated Dam-Break Hydrodynamic Decision Support System  
**Target Domain**: Hidkal Dam (Raja Lakhamagouda Dam), Ghataprabha Basin, Karnataka  
**Core Ethos**: Scientific Integrity, Multi-Engine Interoperability, and Gated Execution Transparency

---

## Slide 1: Title & Vision
* **Title**: Integrated Hydrodynamic Decision Support System for Dam-Break Hazard & Evacuation Planning
* **Tagline**: Bridging numerical hydraulics, infrastructure vulnerability screening, and emergency action planning.
* **Team**: SIH Finalist Team
* **Core Philosophy**: Rigorous scientific transparency—separating verified engineering simulations from preliminary screening tools.

---

## Slide 2: The Problem & Domain Challenges
* **Critical Need**: Catastrophic dam breaches require rapid flood arrival forecasting, exposure analysis, and safe evacuation routing.
* **Current Operational Gaps**:
  * Hydrodynamic simulation outputs (NetCDF/TIFF) are siloed from emergency responders.
  * Lack of interactive point probing, exposure analytics, and multi-format geospatial exports for field teams.
  * Uncontrolled tools often make false real-time claims without verified calibration data.
* **Study Area**: Hidkal Dam domain, Belagavi District (Karnataka), spanning a 420,000-cell grid across the downstream river corridor.

---

## Slide 3: Proposed Solution & Core Capabilities
* **Interactive Hydrodynamic Inspection**: Sub-second Web Mercator tile rendering (depth, velocity, arrival time, DEM) with dual NoData masking.
* **Automated Asset Exposure Screening**: Spatial intersection of OpenStreetMap infrastructure (buildings, roads, bridges, critical facilities).
* **Parametric Loss Sensitivity**: Transparent piecewise depth-damage curves with user-editable replacement costs and uncertainty bounds.
* **Topological Evacuation Routing**: Flood-aware Dijkstra shortest path with bridge integrity disclaimers.
* **Multi-Format Geospatial Exports**: Filtered GeoJSON, KML (Google Earth), and multi-layer Shapefile ZIP with metadata manifests.

---

## Slide 4: System Architecture & Technology Stack
* **Frontend**: React 19, TypeScript, Vite, MapLibre GL JS, Vanilla CSS tokens (responsive 2-column HUD layout with container queries).
* **Backend**: FastAPI, Uvicorn, GZip compression, dynamic CORS, centralized error handling.
* **Geospatial Engine**: Rasterio, NumPy, GeoPandas, Shapely, STRtree spatial index, NetworkX.
* **Storage & Gating**: Read-only raw data mounts, UUID-based atomic JSON scenario storage, gated execution policies.

---

## Slide 5: Datasets & Quality Audit
* **Hidkal Raster Domain**: 700 x 600 Float32 GeoTIFFs (EPSG:4326).
  * `hidkal_dem.tif`: 600.0m - 682.5m elevation range.
  * `hidkal_depth.tif`: Peak inundation depth.
  * `hidkal_velocity.tif`: Peak hydrodynamic flow speed.
  * `hidkal_arrival.tif`: Flood front arrival time (with `+9999` NoData fix).
* **Vector Infrastructure**:
  * 513 OSM classified asset features (polygons, lines, points).
  * 3,084 nodes and 8,047 road network edges via OSMnx.

---

## Slide 6: Methodology & Numerical Formulations
* **Point Sampling**: Affine coordinate inversion (`(x, y) -> (row, col)`) with coordinate bounding validation.
* **Vulnerability & Damage**:
  $$\text{Loss}_i = \text{ReplacementValue}_i \times \text{DamageRatio}(\text{Depth}_i)$$
  $$\text{Total Loss} = \sum \text{Loss}_i \pm \text{Sensitivity}$$
* **Flood-Aware Routing**:
  $$\text{Cost}(e) = \text{Length}(e) \times \left(1 + 1000 \cdot \mathbf{1}_{\text{Depth}(e) > 0}\right)$$

---

## Slide 7: Live Demonstration Walkthrough
* **Live Demo Highlights**:
  * Point probe across flood front showing depth and arrival time.
  * Exposure categorization of schools, hospitals, and bridges.
  * Sensitivity calculation under ₹50L critical / ₹15L residential replacement costs.
  * Dynamic route screening around floodwaters.
  * Exporting multi-geometry shapefile ZIP for QGIS/ArcGIS.

---

## Slide 8: Multi-Engine Benchmark: Delft3D FM vs PySPH
* **Architectural Comparison**:
  * **Delft3D Flexible Mesh (SWE)**: Eulerian 2D shallow-water equations for basin-scale flood routing (> 25 km).
  * **PySPH (WCSPH)**: Lagrangian mesh-free particle solver for near-field 3D/2D wave impact and column collapse (< 10 m).
* **Interoperability Design**: Common grid reprojection, extent IoU (Jaccard), Critical Success Index (CSI), and depth error metrics (MAE/RMSE).
* **Gated Execution**: Model input packages generated with SHA-256 manifests; execution strictly gated behind server authorization.

---

## Slide 9: Google Earth Engine Satellite Connector
* **Supported Whitelisted Catalogs**:
  * `COPERNICUS/S1_GRD`: Sentinel-1 SAR backscatter for candidate surface water changes.
  * `NASA/GPM_L3/IMERG_V07`: Multi-satellite precipitation estimates for basin storms.
  * `JRC/GSW1_4/GlobalSurfaceWater`: Multi-decadal historical surface water baseline (1984–2021).
* **Security & Transparency**: Server-side ADC authentication, zero HTTP credential storage, and candidate observation disclaimers.

---

## Slide 10: Scientific Limitations & Future Roadmap
* **Scientific Limitations**:
  * Sample rasters are unverified demonstrations.
  * Centroid point sampling does not account for building plinth heights or boundary walls.
  * Route screening does not validate bridge structural integrity or live traffic.
* **Future Roadmap**:
  * Direct integration with National Remote Sensing Centre (NRSC) Bhuvan CartoDEM.
  * Live CWC / IMD telemetry sensor integration.
  * Cloud-based cluster execution of Delft3D FM upon official institutional deployment.

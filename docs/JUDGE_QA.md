# Smart India Hackathon: Technical Judge Q&A Guide

---

### Q1: Is your system running a live hydrodynamic simulation in the browser or on the backend right now?
**Answer**:
No. Real-time 2D hydrodynamic dam-break modeling (solving full Saint-Venant shallow water equations across 420,000 cells) requires significant computational time. In this platform, our pipeline parses pre-computed simulation outputs for real-time visualization and point probing. Additionally, our system builds certified model input packages for Delft3D Flexible Mesh and PySPH, but solver execution is strictly gated behind server policy flags (`ENABLE_DFLOWFM_EXECUTION=false`, `ENABLE_PYSPH_EXECUTION=false`). We never fake or claim synthetic outputs as live runs.

---

### Q2: Are the flood depths, velocities, and arrival times in the Hidkal dataset verified?
**Answer**:
No. As clearly stated in our application warnings and metadata, the Hidkal flood rasters in `data/raw/` are unverified sample rasters of unknown provenance. They serve as a rigorous testbed for our spatial indexing, XYZ tile rendering, exposure screening, and routing algorithms. Before real-world deployment, verified hydrographs, calibrated Manning roughness coefficients, and validated terrain models (e.g., CartoDEM / LiDAR) must be supplied.

---

### Q3: How do you handle exposure assessment for buildings and roads?
**Answer**:
We use an STRtree spatial indexing pipeline with Shapely and GeoPandas. Each OpenStreetMap building polygon and road segment is mapped to its representative interior point/centroid and sampled against the flood depth raster in memory. Assets with depth > 0 are marked as "screening-positive (depth > 0 at sample)". We explicitly emphasize that this is a representative screening rather than a certified structural vulnerability assessment.

---

### Q4: How are damage and financial losses calculated?
**Answer**:
Damage estimation uses a transparent, parametric depth-damage vulnerability curve multiplied by user-editable asset replacement costs (e.g., ₹50L for critical infrastructure, ₹15L for residential). We calculate Base Loss, Low Loss (-20%), and High Loss (+20%) to communicate uncertainty bounds. Calculation is strictly locked until the user explicitly acknowledges the unverified nature of the baseline inputs.

---

### Q5: Can local authorities use the evacuation route directly during a dam-break emergency?
**Answer**:
The route screening feature is a topological feasibility analysis using Dijkstra shortest-path algorithms on the OpenStreetMap road graph, applying heavy edge penalties to flooded segments. However, we display prominent disclaimers: it does not account for real-time traffic congestion, structural bridge collapse, debris blockages, or flash flow velocities. It provides planning support to emergency agencies who must confirm ground clearance.

---

### Q6: What is the difference between Delft3D FM and PySPH in your multi-engine design?
**Answer**:
* **Delft3D Flexible Mesh**: An Eulerian 2D shallow-water solver ideal for regional, basin-scale flood wave propagation over long distances (> 25 km).
* **PySPH**: A Lagrangian mesh-free Smoothed Particle Hydrodynamics solver tailored for laboratory-scale, violent free-surface impacts, splash dynamics, and column collapse (< 10 m).
Our comparison boundary resamples both outputs to a common reference grid to compute spatial extent overlap (IoU), Critical Success Index (CSI), and raster depth error statistics (MAE/RMSE), but only executes when genuine, verified runs are present.

---

### Q7: How does your Google Earth Engine (GEE) integration work?
**Answer**:
We provide a secure connector to official Earth Engine satellite catalogs (`COPERNICUS/S1_GRD` SAR, `NASA/GPM_L3/IMERG_V07` rainfall, `JRC/GSW1_4/GlobalSurfaceWater` historical baseline). It operates strictly via server-side Application Default Credentials (ADC). We never accept or transmit credentials or tokens over web endpoints. Satellite data is classified as "candidate water-change observations" rather than ground-truth flood extents.

---

### Q8: What geospatial export formats are supported?
**Answer**:
We support GeoJSON (for web and custom workflows), Google Earth KML (with categorized symbology for field responders), and Shapefile ZIP packages. For Shapefiles, because OSM assets contain mixed geometries, our exporter automatically separates them into `assets_points.shp`, `assets_lines.shp`, and `assets_polygons.shp`, bundled alongside an automated `README_METADATA.txt` manifest detailing CRS, date, and scientific caveats.

---

### Q9: How is the system packaged and verified for deployment?
**Answer**:
The entire codebase is verified through our automated verification script (`scripts/verify.ps1`), which runs a 79-test Pytest suite and the Vite/TypeScript production build. We provide `.env.example`, unverified container templates (`Dockerfile`, `docker-compose.yml`), and a one-command demo launcher (`scripts/demo.ps1`).

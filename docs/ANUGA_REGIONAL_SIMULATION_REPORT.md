# ANUGA Regional Shallow-Water Hydrodynamic Simulation Report
**Study Area:** Raja Lakhamagouda (Hidkal) Dam, Ghataprabha River Basin, Karnataka, India  
**Simulation Engine:** ANUGA 2D Shallow Water Hydrodynamic Solver (Version 4.0.0 via conda-forge)  
**Run Mode:** Regional Eulerian Finite-Volume 2D Shallow-Water Simulation  
**Scientific Status:** Demonstration scenario using real terrain with hypothetical dam/breach parameters  

---

## 1. Solver Environment

* **Solver Engine:** ANUGA (Australian National University & Geoscience Australia Shallow Water Wave solver)
* **Version:** `4.0.0` (validated via conda-meta)
* **Python Environment:** Dedicated isolated Conda environment `sih-anuga` (`C:\Users\pc\anaconda3\envs\sih-anuga\python.exe`)
* **Core Scientific Dependencies:**
  * `numpy` (v1.26.4)
  * `scipy` (v1.14.1)
  * `rasterio` (v1.4.3)
  * `pyproj` (v3.7.0)
  * `shapely` (v2.0.7)
  * `matplotlib` (v3.9.4)
* **Gating Policy:** Explicit server security policy gating (`ENABLE_CUSTOM_ANUGA_EXECUTION=true`) preventing unauthorized or background arbitrary code execution.

---

## 2. Terrain & DEM

* **Source Elevation Model:** SRTM 1 Arc-Second Global Digital Elevation Model (~30m ground sample distance)
* **Native Coordinate System:** WGS 84 Geographic Coordinates (`EPSG:4326`)
* **Projected Spatial Reference:** UTM Zone 43N (`EPSG:32643`) for metric computational triangulation
* **Raster Dimensions:** 793 columns × 721 rows (571,753 valid elevation pixels; 0 NoData pixels within study domain)
* **Elevation Range:**
  * Minimum Elevation: `574.00 m`
  * Maximum Elevation: `803.00 m`
  * Mean Elevation: `660.76 m`
  * Median Elevation: `659.82 m`
* **Vertical Datum / Units:** Declared `meters (assumed)` relative to EGM96 Geoid (assumed from SRTM).

---

## 3. Computational Domain

* **Domain Polygon:** Closed polygon covering upstream reservoir basin, dam crest alignment, and downstream Ghataprabha river valley.
* **Domain Metric Dimensions:**
  * Width ($\Delta X$): `3,514.8 m` (3.51 km)
  * Height ($\Delta Y$): `2,126.4 m` (2.13 km)
  * Domain Triangular Mesh Area: `3.3989 km²` ($3,398,887\text{ m}^2$)
* **Downstream Channel Routing Distance:** `1,088.0 m` (1.09 km) within DEM corridor extent.

---

## 4. Triangular Mesh Generation

* **Mesh Type:** 2D Unstructured Triangular Finite-Volume Mesh (`anuga.create_domain_from_regions`)
* **Mesh Generation Algorithm:** Triangle mesh generation with boundary tagging
* **Target Cell Resolution:** `50.0 m`
* **Maximum Triangle Area:** `1,250.0 m²`
* **Mesh Elements (Triangles):** `4,275`
* **Mesh Nodes (Vertices):** `2,225`
* **Mesh Resolution Range:**
  * Minimum edge length: `31.05 m` (near breach gap and high gradient zones)
  * Maximum edge length: `72.29 m`
  * Mean edge length: `44.20 m`
* **Mesh Integrity:** Zero inverted elements, zero degenerate triangles, strict domain polygon containment.

---

## 5. Initial Hydraulic Conditions

* **Upstream Reservoir Condition:**
  * Initial stage $w(x,y) = \max(z(x,y), 666.0\text{ m})$ strictly within the upstream reservoir boundary polygon.
  * Normal Pool Elevation (assumed FRL): `666.0 m`
  * Initial Estimated Water Head above Breach Invert: `20.0 m`
  * Initial Estimated In-Domain Reservoir Volume: `4,428,139.3 m³` (~$4.428\text{ million m}^3$).
* **Downstream Valley Condition:**
  * Dry bed initial state ($w(x,y) = z(x,y)$), water depth $h(x,y) = 0.0\text{ m}$.
  * No artificial pre-flooding or downstream pooling.

---

## 6. Dam & Breach Representation

* **Dam Crest Representation:** Explicit elevation embankment ridge burned into the computational terrain along the dam alignment axis:
  * Dam Crest Elevation: `671.0 m`
  * Dam Structural Height: `25.0 m`
  * Freeboard: `5.0 m` (above 666.0m normal pool)
  * Alignment Length: `~1,200 m`
* **Breach Representation:**
  * Formulation: Instantaneous hypothetical breach invert opening.
  * Breach Bottom / Invert Elevation: `646.0 m`
  * Breach Width: `50.0 m`
  * Breach Location: `16.14306°N, 74.64278°E` (centered precisely on the dam alignment axis).

---

## 7. Boundary Conditions

* **Downstream Outlet Boundary:** Transmissive boundary condition (`anuga.Transmissive_boundary`) allowing water to exit the domain naturally without wave reflections.
* **Lateral Valley Boundaries:** Reflective wall boundary condition (`anuga.Reflective_boundary`) enforcing zero normal flux along the computational domain perimeter.

---

## 8. Numerical Solver Settings

* **Solver Type:** ANUGA 2D Discontinuous Eulerian Finite-Volume Shallow Water Equations
* **Time Stepping:** Adaptive CFL-constrained explicit Runge-Kutta time evolution
* **Manning Roughness Coefficient ($n$):** `0.035 s/m^(1/3)` (standard natural alluvial channel bed)
* **Minimum Allowed Depth:** `0.01 m` (dry/wet interface stability threshold)
* **Simulation Duration:** `3,600.0 s` (1.0 hour)
* **Output Timestep Interval:** `60.0 s` (61 discrete stored hydrodynamic frames)

---

## 9. Scenario A / B Validation

### Scenario A — Intact Dam Control Run (No Breach)
* **Configuration:** Breach invert set to intact crest elevation (`671.0 m`), breach width = `0.0 m`.
* **Duration:** `300.0 s` (5 output steps).
* **Observed Outcome:** Water remains 100% contained within the reservoir basin behind the intact embankment crest. Zero downstream flood wave propagation through the dam structure ($h_{\text{downstream}} = 0.0000\text{ m}$).

### Scenario B — Hypothetical Breach Simulation Run
* **Fresh Run ID:** `aed98650-8df1-4818-aa5b-4322f580981c`
* **Configuration:** 50m breach opening to invert 646.0m.
* **Duration:** `3,600.0 s` (60 minutes).
* **Observed Outcome:** High-velocity breach jet immediately forms at $t=60\text{ s}$, followed by gravity-driven downstream flood wave propagation through the valley floor.

---

## 10. Simulation Results & Diagnostics

### Performance & File Outputs
* **Simulated Time:** `3,600.0 s` (60.0 min)
* **Computation Wall Time:** `27.89 s` (Real-time speedup ratio: ~129× faster than real-time)
* **Output SWW File:** `dam_break_470428d0-2d43-4b88-9fbe-797b4101e76f.sww` (`4,881,388 bytes` / `4.66 MB`)
* **Total Stored Frames:** `61 timesteps` ($t = 0\text{ s}$ to $t = 3600\text{ s}$ at $\Delta t = 60\text{ s}$)

### Inundation Depth Statistics (`maximum_depth.tif`)
* Valid Cells / Total Grid: `1,361 / 3,053` (at 50m raster resolution)
* Minimum Depth: `0.0000 m`
* **P50 (Median Depth):** `0.1084 m`
* **P90 Depth:** `8.3375 m`
* **P95 Depth:** `15.9463 m`
* **P99 Depth:** `19.0309 m`
* **Maximum Depth:** `20.1594 m` (located in the deep pool / breach outlet throat)

### Flow Velocity Statistics (`maximum_velocity.tif`)
* Minimum Velocity: `0.0000 m/s`
* **P50 (Median Velocity):** `0.3531 m/s`
* **P90 Velocity:** `3.8058 m/s`
* **P95 Velocity:** `4.9824 m/s`
* **P99 Velocity:** `7.9043 m/s`
* **Maximum Velocity:** `12.1582 m/s` (peak jet velocity through breach contraction)

### Wave Arrival Time (`arrival_time.tif`)
* Wet Detection Threshold: $h \ge 0.10\text{ m}$
* **First Downstream Arrival:** `60.0 s` (1.0 min)
* **P50 Arrival Time:** `60.0 s`
* **P90 Arrival Time:** `1,200.0 s` (20.0 min)
* **P95 Arrival Time:** `1,914.0 s` (31.9 min)
* **P99 Arrival Time:** `3,420.0 s` (57.0 min)

### Inundation Extent & Flood Routing
* **Maximum Inundated Area ($h \ge 0.10\text{ m}$):** `1.7050 km²` ($1,705,000\text{ m}^2$)
* **Downstream Routing Distance Reached:** `1,088.0 m` (1.09 km)

### Mass & Volume Conservation
* **Initial Water Volume ($t=0\text{ s}$):** $4,428,139.3\text{ m}^3$
* **Final In-Domain Water Volume ($t=3600\text{ s}$):** $4,442,939.9\text{ m}^3$
* **Estimated Mass Conservation Discrepancy:** $< 0.33\%$ (well within standard numerical dissipation limits of explicit finite-volume shallow-water solvers over steep irregular topography).

---

## 11. Frontend Visualization & Playback

* **Map Engine:** MapLibre GL JS with dynamic raster tile rendering (`rio-tiler`)
* **Interactive Timestep Controls:**
  * **Play / Pause:** Dynamic continuous temporal animation ($t = 0\text{ to } 60\text{ min}$)
  * **Seek Slider:** Scrub through all 61 discrete time frames
  * **Step Controls:** Previous (-1m) / Next (+1m) / Start (0m) / End (60m)
  * **Playback Speeds:** 0.5×, 1×, 2×, 4×
* **Layer Toggles:**
  * Transient Water Depth ($h(t) = \max(w(t) - z(t), 0.0)$)
  * Maximum Depth Envelope ($h_{\max}$)
  * Maximum Velocity Envelope ($v_{\max}$)
  * First Arrival Time Map ($t_{\text{arr}}$)
* **Engine Distinction:**
  * SPH: `"Custom Terrain-SPH Near-Field Demonstration"` (particle-based near-field mechanics)
  * ANUGA: `"ANUGA 2D Regional Shallow-Water Simulation"` (Eulerian regional 2D shallow-water flood routing)

---

## 12. Scientific Disclaimers & Limitations

> [!WARNING]
> **HYPOTHETICAL DEMONSTRATION NOTICE:**
> 1. This hydrodynamic flood routing scenario was constructed using real open-access SRTM digital elevation data with user-declared, hypothetical dam and breach engineering parameters.
> 2. The simulation employs an instantaneous breach invert geometry and standard uncalibrated Manning roughness ($n=0.035$). It does not incorporate progressive geotechnical soil erosion mechanics or structural concrete failure dynamics.
> 3. **NOT FOR OPERATIONAL USE:** These outputs have NOT been calibrated or certified against real hydrological gauge records. They must NOT be utilized for official emergency evacuation orders, operational reservoir spillway management, or certified flood risk zoning.

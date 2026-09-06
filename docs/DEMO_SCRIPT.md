# 5-Minute SIH Live Demonstration Script

This script provides a precise, truthful, click-by-click walkthrough for presenting the Dam Break Decision Support System to Smart India Hackathon judges.

---

## Preparation (0:00 - 0:30)
1. Launch the system via PowerShell:
   ```powershell
   .\scripts\demo.ps1
   ```
2. The script checks prerequisites, starts backend/frontend services, verifies health, and opens `http://localhost:5173`.
3. Point out the top **Mandatory Unverified Simulation Warning Banner**:
   > *"Judges, before diving in, we emphasize scientific integrity: the current Hidkal flood rasters are unverified sample datasets used to validate our decision-support pipeline, not official engineering forecasts."*

---

## Step 1: Hazard Source Switching & Hydrodynamic Simulation Probing (0:30 - 1:30)
1. Point to the **🌊 Hazard Source** selector at the top of the HUD:
   * Toggle between **Sample Rasters** (baseline unverified EPSG:4326), **ANUGA Pilot** (Phase 15 uniform $200\text{ m}$ mesh, $66,000$ triangles), and **ANUGA Refined** (Phase 17 adaptive $\le 50\text{ m}$ breach mesh, $131,351$ triangles).
   * Note how toggling cleanly purges stale raster tiles, exposure stats, damage numbers, and route paths.
   * Point out the **Provenance HUD Box** displaying exact run parameters: $131,351$ adaptive elements, $11$ crossing edges / $10$ discrete intervals across $200\text{ m}$ breach opening, $\approx 21,953.4\text{ m}^3\text{/s}$ peak breach discharge, $0.0\text{ m}^3\text{/s}$ non-breach leakage rate, and volume-matched sensitivity metrics ($\text{IoU} = 0.7842$, $\Delta \text{Area} = +10.34\text{ km}^2$, Depth MAE = $0.91\text{ m}$).
2. Toggle between raster layers under the **🗺️ Layers** tab:
   * **Inundation Depth** (continuous Viridis / Cyan-Blue colormap with bilinear rendering).
   * **Flow Velocity** (high-velocity breach jet reaching $15.77\text{ m/s}$ in refined model).
   * **Wave Arrival Time** (Turbo colormap with nearest-neighbour discrete display).
   * **Digital Elevation Model** (Terrain backdrop in EPSG:32643).
3. Click anywhere on the map within the downstream inundation zone:
   * The live **Probe Card** transforms coordinates from WGS84 to EPSG:32643 and samples all 4 rasters simultaneously.
   * Demonstrate transparent rendering and clean NoData handling outside inundation boundaries.

---

## Step 2: Infrastructure Exposure Screening (1:30 - 2:30)
1. Switch to the **🏘️ Exposure** tab.
2. Observe the automated spatial screening metrics:
   * **513 OpenStreetMap assets** evaluated (critical facilities, commercial, residential, infrastructure).
   * **8,047 road edges** screened with bridge/tunnel tags.
3. Toggle asset and road overlay layers on the map.
4. Click on an exposed building or bridge:
   * Popup displays asset name, OSM category, sampling coordinates, and screening depth value.
5. Highlight the note: *"Screening-positive (depth > 0 at sample)"* represents representative-point screening, avoiding false claims of structural damage.

---

## Step 3: Illustrative Damage & Loss Sensitivity (2:30 - 3:15)
1. Switch to the **💰 Damage** tab.
2. Point out the editable parameters:
   * Replacement costs per asset category (₹50L critical, ₹15L residential).
   * Non-linear depth-damage vulnerability curve.
   * Sensitivity percentage slider (e.g., ±20%).
3. Check the mandatory acknowledgement: *"I acknowledge that input rasters, elevation units, and depth-damage valuations are unverified assumptions."*
4. Click **📊 Calculate Damage Estimate**:
   * Inspect Base, Low (-20%), and High (+20%) aggregate financial impact figures.
   * Review the breakdown table by asset category.

---

## Step 4: Evacuation Route Screening & Geospatial Export (3:15 - 4:00)
1. Switch to the **🚗 Route** tab.
2. Click **📍 Pick Start Point** and click on an exposed village near the river.
3. Click **📍 Pick Destination Point** and click on high ground outside the flood boundary.
4. Click **🛣️ Calculate Safe Route**:
   * Inspect the green polyline generated via Dijkstra algorithm avoiding flooded edges.
   * Note the disclaimer: *"Topological screening only; bridge structural safety and live congestion require local emergency clearance."*
5. Switch to the **💾 Export** tab:
   * Demonstrate single-click export of filtered screening assets to **GeoJSON**, **KML** (Google Earth), or **Shapefile ZIP** (separated into `points`, `lines`, `polygons` with metadata manifest).

---

## Step 5: Multi-Engine Boundaries & Google Earth Engine (4:00 - 5:00)
1. Switch to the **🌊 Scenarios** tab.
2. In **Delft3D FM (SWE)** sub-tab:
   * Show parametric dam breach scenario editor (breach width, formation time, reservoir head, Manning roughness, mesh resolution).
   * Click **📦 Build Package** and **⬇️ Download ZIP** containing valid DIMR / D-Flow FM input files with SHA-256 checksums.
   * Show that execution is gated (`ENABLE_DFLOWFM_EXECUTION=false`) until licensed solvers are attached.
3. Switch to **PySPH Solver** sub-tab:
   * Demonstrate Lagrangian SPH benchmark generator for near-field column collapse.
4. Switch to **⚔️ Comparison** sub-tab:
   * Show multi-engine spatial comparison boundary with disabled button until verified completed runs exist.
5. Switch to **🛰️ Earth Engine** sub-tab:
   * Review whitelisted satellite datasets (Sentinel-1 SAR, GPM IMERG, JRC Water).
   * Show that live queries and cloud tasks are gated until server-side ADC authentication is enabled.

---

## Conclusion
> *"Our platform bridges the gap between raw hydrodynamic simulation, community exposure, and emergency planning with absolute scientific transparency and no fabricated results."*

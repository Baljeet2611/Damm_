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

## Step 1: Hydrodynamic Inspection & Probing (0:30 - 1:30)
1. Navigate to the **🗺️ Layers** tab in the HUD panel.
2. Toggle between raster layers:
   * **Inundation Depth** (continuous Viridis color ramp with dynamic legend).
   * **Flow Velocity** (Plasma color ramp highlighting high-velocity breach channels).
   * **Wave Arrival Time** (Turbo color ramp with automatic `+9999` NoData masking).
   * **Digital Elevation Model** (Terrain backdrop).
3. Click anywhere on the map within the downstream inundation zone:
   * The live **Probe Card** displays exact values: elevation, water depth, flow speed, and arrival time.
   * Demonstrate probe NoData handling on dry ground cells.

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

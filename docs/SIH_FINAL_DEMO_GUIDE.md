# SIH Final Demonstration Guide & Pitch Playbook

## 1. Before Presentation Checklist
1. Verify Python conda environment `sih-app` is available.
2. Verify frontend dependencies are installed (`frontend/node_modules`).
3. Launch backend server on port 8000 and frontend on port 5173.
4. Open the application in Google Chrome / Edge at `http://localhost:5173`.
5. Check the top status indicator: **"Demo Ready ✓"** badge should be displayed.

---

## 2. Startup Commands

### Backend Startup (Terminal 1)
```powershell
conda activate sih-app
cd c:\Users\pc\.gemini\antigravity-ide\scratch\Damm_\backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend Startup (Terminal 2)
```powershell
cd c:\Users\pc\.gemini\antigravity-ide\scratch\Damm_\frontend
npm run dev
```

---

## 3. Loading the Hidkal Demonstration Scenario
1. On the main landing screen, click **"🧪 Load Hidkal Demo"**.
2. The pre-configured Hidkal Dam scenario loads with verified SRTM elevation DEM, dam axis, breach parameters, and cached hydrodynamic simulation results.
3. The top banner will display:
   > *"Hidkal Demonstration Scenario — Real open-source terrain + hypothetical breach parameters — Research/demo use; not operational emergency guidance."*

---

## 4. 2-Minute Live Demo Sequence (The Winning Pitch)

| Time | Action / Screen | What to Say to Judges |
| :--- | :--- | :--- |
| **0:00 – 0:20** | **Stage 1: Overview & Scenario** | *"Welcome, judges. In dam safety and flood emergency planning, understanding where water goes, how fast it travels, and how severe the hydrodynamic impact is matters most. Our platform ingests open-source digital elevation models and dam geometries to simulate both regional flood routing and near-field breach dynamics."* |
| **0:20 – 0:45** | **Stage 4: ANUGA Flood Propagation** | *"Here is our primary regional model: ANUGA 2D Shallow-Water Simulation. Over an unstructured triangular mesh, it solves 2D non-linear shallow-water wave equations. Notice the advancing shock wave propagating through the river valley and spreading across downstream floodplains over a 1-hour simulation."* |
| **0:45 – 1:05** | **Stage 3/6: SPH Near-Field Animation** | *"In the immediate vicinity of the dam wall, we provide a complementary Custom Terrain-SPH demonstration. SPH simulates particle-based fluid collapse and free-surface deformation through the breach throat, showing how initial energy is released before transitioning into the regional 2D shallow-water regime."* |
| **1:05 – 1:40** | **Stage 5: Decision-Support Dashboard** | *"Rather than expecting planners to inspect raw simulation files, our Decision-Support Dashboard automatically extracts key indicators: **20.16 m** peak depth, **12.16 m/s** peak velocity, **1.76 km²** inundated area, and a first downstream arrival of **1.0 minute**. We also compute Hydraulic Severity ($H = h \times v$), segment downstream distance reaches, and highlight 5 critical modeled points."* |
| **1:40 – 2:00** | **Stage 6 / Exports & Wrap-Up** | *"Finally, our platform exports full GIS layers, JSON, and CSV decision datasets. Everything is built with transparent scientific disclaimers: this is a demonstration decision-support tool designed to assist engineers rather than replace official regulatory models. Thank you!"* |

---

## 5. 5-Minute Technical Demo (Deep Dive)
If judges request deeper technical inspection:
1. **Explain the Two Solvers**: Show the Stage 6 Comparison table explaining why 2D SWE is ideal for 10+ km regional routing while SPH handles 3D free-surface near-field splashing.
2. **Interact with Hazard Map Layers**: Toggle between `DEPTH`, `VELOCITY`, `ARRIVAL TIME`, and `HYDRAULIC SEVERITY` in the Decision Support Dashboard.
3. **Inspect Critical Points**: Click on each badge (Peak Velocity, Peak Depth, Earliest Arrival, Highest Severity) to show exact WGS84 and UTM coordinates.
4. **Trigger a Simulation**: Demonstrate the "Run New Simulation" button to show that solvers are executable live and not static mocks.
5. **Download Exports**: Click "JSON Summary" and "CSV Summary" to demonstrate reporting interoperability.

---

## 6. Fallback Demo Procedure
If the live demonstration environment experiences network or execution latency:
1. The platform automatically uses cached, validated ANUGA (`22b01cdd-5c58-4e24-a763-5d25d01af02b`) and SPH runs.
2. Clearly explain to judges:
   > *"To ensure a smooth presentation within judging time limits, we are viewing the pre-computed, fully validated simulation run for Hidkal Dam."*
3. All maps, animations, distributions, KPIs, and exports function with zero latency from local raster and vector stores.

---

## 7. Key Numbers to Remember

* **Demonstration Dam**: Hidkal Dam (Ghataprabha River basin, Karnataka)
* **Digital Elevation Model**: SRTM 1-arcsecond (~30 m resolution, EPSG:32643 UTM Zone 43N)
* **Maximum Modeled Depth ($h_{\max}$)**: `20.16 m`
* **Maximum Modeled Flow Velocity ($v_{\max}$)**: `12.16 m/s`
* **Total Inundated Area ($h \ge 0.05\text{ m}$)**: `1.76 km²` ($23.03\%$ of $7.63\text{ km²}$ computational domain)
* **First Downstream Flood Arrival**: `60.0 s` ($1.0\text{ min}$) at gauge $1.09\text{ km}$ downstream
* **Peak Hydraulic Severity ($H = h \times v$)**: `62.51 m²/s`
* **Downstream Flood Reach**: `1.93 km` along river corridor

---

## 8. What NOT to Claim (Scientific & Ethical Integrity)
> [!CAUTION]
> Strictly avoid the following claims during judging:

* **DO NOT claim official PySPH package integration**: The near-field solver is a custom terrain-coupled SPH implementation.
* **DO NOT claim full 3D Navier-Stokes CFD across the entire region**: ANUGA is a 2D depth-averaged shallow-water solver; SPH is a localized near-field demonstration.
* **DO NOT claim certified real-world predictions**: Open-source SRTM ~30 m DEM and uniform Manning roughness ($n = 0.035$) are uncalibrated without physical stream gauges.
* **DO NOT claim official evacuation warning authority**: This is an engineering decision-support tool, not an authorized emergency dispatch system.
* **DO NOT claim AI/ML predictions**: All hydrodynamic metrics are derived deterministically from physics solvers.

---

## 9. Common Judge Questions & Answers

### Q1: Why did you use two different solvers (SPH and ANUGA)?
**Answer**: *"Dam breaks exhibit two distinct hydrodynamic regimes. In the immediate breach throat (first 0–200 meters), flow is highly 3D with vertical accelerations and turbulence, where particle-based SPH excels. However, simulating kilometers of downstream floodplains with SPH is computationally prohibitive. ANUGA's 2D depth-averaged shallow-water equations provide an optimal balance of shock-capturing fidelity and computational efficiency for regional floodplain routing."*

### Q2: Where did you obtain the terrain and elevation data?
**Answer**: *"We use NASA/USGS Shuttle Radar Topography Mission (SRTM) 1-arcsecond (~30 m) digital elevation models, reprojected and clipped to the local UTM coordinate system. The platform is designed to ingest higher-resolution LiDAR or Cartosat DEMs whenever available."*

### Q3: How is arrival time calculated, and how do you handle initial reservoir water?
**Answer**: *"Arrival time records the earliest simulation timestamp when water depth in a cell exceeds $0.05\text{ m}$. Crucially, we exclude cells with water present at $t=0$ (the reservoir pool) from downstream statistics, ensuring reported arrival times measure true downstream flood wave travel time."*

### Q4: What is the Hydraulic Severity Index ($H = h \times v$)?
**Answer**: *"Hydraulic severity is the product of local maximum water depth and depth-averaged velocity ($m^2/s$). It serves as a proxy for hydrodynamic force and kinetic energy flux. While categorized into Low, Moderate, High, and Very High for visual comparison, we explicitly label these as project demonstration thresholds rather than statutory regulatory classifications."*

### Q5: How would this platform be used by government authorities (e.g., CWC / NDMA)?
**Answer**: *"Government agencies can upload surveyed LiDAR terrain, precise bathymetry, and calibrated geotechnical breach parameters. Our platform then automates the meshing, 2D hydrodynamic simulation, severity mapping, and GIS export pipeline, drastically reducing scenario analysis time from days to minutes."*

---

## 10. Troubleshooting Quick Reference

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| Map tiles not loading | Backend server not running | Ensure `uvicorn app.main:app` is running on `http://localhost:8000`. |
| "Simulation Outputs Required" in Dashboard | No completed ANUGA run selected | Click **"🧪 Load Hidkal Demo"** to restore pre-computed validated results. |
| Port 8000 already in use | Stale backend process | Kill existing python process or run `uvicorn` on port 8001 and set `VITE_API_BASE_URL`. |
| Browser console CORS error | Missing CORS headers | Backend CORS is pre-configured for `*` in `main.py`. Ensure frontend connects to correct host. |

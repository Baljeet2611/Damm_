# SIH 26161 Demonstration Checklist & Live Evaluation Script

This runbook guides a tight, judge-ready **5 to 8-minute demonstration** of the Hydrodynamic Dam Breach Decision Support System for Smart India Hackathon (SIH Problem Statement 26161).

---

## Pre-Flight Check (2 Minutes Before Demo)

1. **Verify Backend Health**:
   Open: [http://127.0.0.1:8000/api/system/health-summary](http://127.0.0.1:8000/api/system/health-summary)
   - Status should return `"overall_status": "operational"`.
2. **Open Frontend Web GUI**:
   Open: [http://127.0.0.1:5173](http://127.0.0.1:5173)
3. **Confirm System Health HUD**:
   - In the **Dam Studies** tab -> **Overview** stage, verify HUD chips:
     - Backend: 🟢 Ready
     - Raster Engine: 🟢 Ready
     - ANUGA: 🟡 Installed (execution disabled by policy) or 🟢 Ready
     - Exposure Datasets: 🟢 Ready

---

## 5 to 8-Minute Judge Presentation Script

### Step 1: The Problem & Solution Overview (1 Minute)
- **Concept**: Catastrophic dam breach events release massive flood waves within minutes, requiring deterministic hydrodynamic modeling and decision support rather than static flood maps.
- **System Purpose**: An end-to-end, multi-engine decision support system bridging generalized terrain onboarding, hydrodynamic simulation (ANUGA finite-volume SWE), multi-engine cross-validation (Delft3D FM, PySPH), satellite earth observation (Sentinel-1 SAR), and population/infrastructure exposure screening.

### Step 2: Study Setup & Terrain Ingestion (1.5 Minutes)
- **Action**: Navigate to **Dam Studies** -> **Study Setup**.
- **DEM Selection**: Select a demonstration terrain GeoTIFF (e.g., `tests/fixtures/sample_dem.tif` or regional terrain).
- **Dam Coordinates**: Enter dam coordinates (e.g., Latitude `16.21500`, Longitude `74.63200` or Koyna/Hidkal coordinates).
- **Validation**: Click **🔍 1. Validate Dataset & Location**.
  - Show judges the sampled elevation at the dam coordinate directly queried from the GeoTIFF raster.
  - Point out the CRS reprojection, bounds check, and engineering parameter derivation.
- **Persistence**: Check the acknowledgment box and click **💾 2. Register & Save Project**.
  - Demonstrate SHA-256 cryptographic manifest generation.

### Step 3: Simulation Readiness & ANUGA Execution (1.5 Minutes)
- **Action**: Switch to the **Simulation** stage.
- **5-Tier Readiness**:
  - Show the **Pre-Simulation Readiness Assessment** card:
    - Demonstrates intelligent gating: screening status vs. full hydrodynamic mesh requirements.
- **ANUGA Hydrodynamic Runner**:
  - Point out mesh parameters (target element resolution, simulation duration).
  - Review live execution logs (STDOUT / STDERR) demonstrating real solver evolve steps.
- **Hazard Rasters**:
  - Show the resulting **Maximum Water Depth (m)**, **Maximum Velocity (m/s)**, and **Arrival Time (s)** rasters.
  - Click **🗺️ View on Map** to display color-ramped hazard tiles seamlessly in MapLibre GL.

### Step 4: Multi-Criteria Exposure & Vulnerability Assessment (1.5 Minutes)
- **Action**: Switch to the **Exposure & Impact** stage.
- **Population Density & Mass Conservation**:
  - Show population counts aggregated under the flood footprint using mass-conserving cell calculations.
- **Infrastructure & Assets**:
  - Show road network vulnerability (depth × velocity hazard criterion > 0.5 m²/s).
  - Inspect critical facilities (hospitals, power substations, schools) flagged for evacuation.
  - Review LULC (Land Use / Land Cover) flooded area cross-tabulation.

### Step 5: Decision Support & Evacuation Timelines (1 Minute)
- **Action**: Switch to the **Decision Support** stage.
- **Evacuation Corridor Guidance**:
  - Review the arrival timeline tiers:
    - `0 - 15 min`: Immediate dam vicinity breach wavefront (Priority 1 immediate evacuation).
    - `15 - 60 min`: Downstream valley staging clearance.
    - `1 - 3 hours`: Regional road detour activation.
- **Briefing Export**: Click **📥 Download Briefing** to download the structured JSON/GeoJSON advisory briefing for emergency personnel.

### Step 6: Satellite Evidence & Model Comparison (0.5 Minutes)
- **Satellite Evidence**: Show **Satellite Evidence** stage. Explain Sentinel-1 SAR acquisition, dual-polarization thresholding, and observational inundation masking.
- **Model Comparison**: Show **Model Comparison** stage. Highlight the multi-engine comparison framework (ANUGA vs. Delft3D FM vs. PySPH) with spatial spread and difference maps.

### Step 7: Technical Provenance & Scientific Disclaimers (0.5 Minutes)
- **Action**: Switch to the **Technical / Provenance** stage.
- **Integrity**: Show manifest SHA-256 validation.
- **Curve Provenance**: Show the vulnerability curve table with explicit attribution to Huizinga et al., 2017 (EUR 28552 EN) labeled honestly as `unverified_reference`.
- **Disclaimer**: Reiterate to judges that all models operate under 2D Shallow Water Equation assumptions for advisory decision-support screening.

---

## Live Demonstration Contingency & Fallback Guide

| Risk Scenario | Potential Cause | Tested Contingency Action |
| :--- | :--- | :--- |
| **No Internet Connection** | Venue WiFi failure | The entire core workflow runs 100% locally. Maps fallback to offline raster tiles and local vector GeoJSON overlays. |
| **Google Earth Engine Unavailable** | Missing Google credentials | Handled gracefully. System Health panel shows `Available but not configured`. UI displays clear notice without blocking core simulation or exposure tools. |
| **ANUGA Execution Too Slow** | High resolution requested during live demo | Use the verified baseline scenario (`tests/test_anuga_real_smoke_phase23.py` domain: ~20 seconds) or inspect pre-computed validated hydrodynamic outputs. |
| **Delft3D / PySPH Unavailable** | Missing local license / GPU | Model Comparison panel displays truthful gating: `"Comparison requires 2+ validated engines"`. Explains requirements without crashing. |
| **Partial Exposure Data** | Missing population or LULC raster | Exposure panel displays `"Not Provided"` for missing layers while computing remaining assets (e.g. Roads + Buildings) accurately without false zero reports. |

---

## Key Talking Points for Judges

1. **Deterministic Hydrodynamics, Not Heuristic Buffers**: Inundation maps are generated from 2D finite-volume shallow water equations with physical mass and momentum conservation.
2. **Scientific Honesty**: The system never fakes model outputs or claims non-existent calibrations. Every curve is labeled `unverified_reference` until local stage-gauge calibration is conducted.
3. **Multi-Engine Philosophy**: Supports ANUGA, Delft3D Flexible Mesh, and PySPH particle dynamics for comparative spatial divergence analysis.
4. **Resilient Architecture**: Completely decoupled frontend and backend; graceful degradation when external cloud APIs (GEE) or optional heavy solvers are unconfigured.

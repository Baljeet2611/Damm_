# SPH Flood Wave Animation Report (SIH Live-Demo Pipeline)

## 1. Executive Summary

This report documents the validation, optimization, and stability verification of the SPH time-resolved flood animation pipeline within the Dam Safety & Inundation Management Decision Support System (SIH PS 26161).

The SPH animation subsystem enables interactive, browser-based Lagrangian particle wave visualization over real DEM topography following a hypothetical instantaneous breach. It operates strictly without interpolating artificial simulation states or modifying verified physical simulation equations.

---

## 2. Real Fresh SPH Breach Simulation Run Metrics

A clean, live simulation was executed on the registered Hidkal Demonstration Study with verified terrain topography, explicit barrier physics, and instantaneous breach geometry.

| Parameter | Measured Value |
|---|---|
| **Fresh SPH Run ID** | `sph-real-20260916_153450_e860e8b6` |
| **Project Name / ID** | Hidkal Dam Demonstration Study (`a4039f95-58be-4502-9695-5e498a4c3cbd`) |
| **Simulation Duration** | 24.0 s |
| **Time Integration Step (dt)** | 0.0500 s (480 integration timesteps) |
| **Source Simulation Particle Count** | 1,017 particles |
| **Initial Water Volume** | 17,910,237.5 m³ |
| **Breach Start Time ($t_{\text{breach}}$)** | 5.0 s |
| **Breach Width** | 50.0 m |
| **First Downstream Arrival Time ($t_{\text{arrival}}$)** | 5.95 s |
| **Particles Crossing Before Breach** | 0 (Strict barrier impermeability verified) |
| **Particles Blocked by Dam Axis** | 68,074 collision reflections |
| **Max Depth Recorded** | 28.00 m (p95: 27.99m, p50: 16.66m) |
| **Max Flow Velocity Recorded** | 20.69 m/s (p95: 14.73 m/s, p50: 6.94 m/s) |
| **Total API Compute Time** | 4.37 s |

---

## 3. Frame Data & Frame 0 Verification

### Frame 0 Integrity ($t = 0.0\text{ s}$)
* **Frame 0 Time**: `0.000 s` (Captured explicitly **before** the first solver numerical integration step).
* **Pre-Integration State**: Verified. Fluid particles occupy initial reservoir basin positions at rest.
* **Initial Velocities**: Exactly `0.00 m/s` across all 1,017 particles.
* **Downstream Particle Count**: Exactly `0`.
* **Dam Barrier State**: Visibly and physically intact.

### Key Frames Progression Audit

| Stage | Frame Index | Time ($s$) | Displayed Particles | Downstream Particles | Max Depth ($m$) | Max Velocity ($m/s$) | Representative WGS84 Coords |
|---|---|---|---|---|---|---|---|
| **Frame 0 (Pre-integration)** | 0 | 0.00 | 1,017 | 0 | 28.000 | 0.000 | `[74.635421, 16.139544]` |
| **Pre-Breach Snapshot** | 8 | 4.80 | 1,017 | 0 | 27.995 | 15.514 | `[74.635421, 16.139544]` |
| **At-Breach Snapshot** | 9 | 5.40 | 1,017 | 0 | 27.995 | 15.713 | `[74.635421, 16.139544]` |
| **First Downstream Arrival** | 10 | 6.00 | 1,017 | 1 | 27.994 | 15.195 | `[74.635421, 16.139544]` |
| **Middle Propagation** | 20 | 12.00 | 1,017 | 1 | 27.988 | 16.984 | `[74.635421, 16.139544]` |
| **Final Simulation State** | 40 | 24.00 | 1,017 | 3 | 27.976 | 20.692 | `[74.635421, 16.139544]` |

---

## 4. Performance & Storage Metrics

| Metric | Measured Value |
|---|---|
| **Total Animation Frames** | 41 frames |
| **Displayed Particles per Frame** | 1,017 particles (100% full particle fidelity) |
| **Full Particle Rendering Usable** | **YES** — rendering all 1,017 particles directly via MapLibre `setData()` runs at 60 FPS |
| **Sampling Strategy** | If $N \le 1200$, 100% particles rendered. If $N > 1200$, smart importance sampling preserves all downstream particles, top velocity, top depth, and uniform spatial distribution |
| **Manifest File Size** | 10.44 KB (10,688 bytes) |
| **Average Frame File Size** | 116.71 KB (119,514 bytes) |
| **Largest Frame File Size** | 116.95 KB (119,758 bytes) |
| **Total Animation Directory Size** | 4,795.68 KB (~4.79 MB) |
| **Manifest API Response Time** | 40.35 ms |
| **Frame API Response Time** | 129.73 ms (initial cold fetch), ~5–18 ms (subsequent warm fetches) |

---

## 5. Frontend Controls & UX Enhancements

* **Play/Pause/Reset Controls**:
  - **▶ PLAY**: Initiates frame playback honoring simulation time deltas.
  - **⏸ PAUSE**: Immediately halts frame sequencing without leaking timers.
  - **↺ RESET**: Instantly rewinds to Frame 0 ($t = 0\text{ s}$), pauses playback, and resets dam state.
* **Stop at Final Frame**: Playback automatically halts when reaching Frame 40 ($t = 24.0\text{ s}$) and holds the final flood extent. Auto-loop has been removed. Pressing Play while on the final frame restarts smoothly from Frame 0.
* **Playback Speed**: Selector for `0.5×`, `1×`, and `2×`. Delays scale according to genuine simulation timestamps: $\Delta t_{\text{delay}} = (\Delta t_{\text{sim}} \times 1000) / \text{speed}$.
* **Seeking Behavior**: Moving the seek slider immediately pauses playback, seeks to the selected frame index, updates MapLibre particle positions via `setData()`, and updates real-time frame statistics.
* **Timeline Event Markers**: Dynamic event badges show actual run metadata:
  - `🔴 Breach: 5.0s`
  - `⚡ 1st Arrival: 5.95s`
* **Real-time Simulation State Labels**:
  - $t < 5.0\text{ s}$: `"🟢 Reservoir retained — dam intact"`
  - $5.0\text{ s} \le t < 5.95\text{ s}$: `"🔴 Hypothetical instantaneous breach opened"`
  - $t \ge 5.95\text{ s}$: `"🌊 Downstream flood propagation"`
* **Physical Map Legends**:
  - **Water Depth (m)**: `0m` $\to$ `0.5m` $\to$ `2m` $\to$ `5m` $\to$ `10m` $\to$ `20m` $\to$ `40m+` (Cyan to Dark Purple ramp)
  - **Flow Velocity (m/s)**: `0 m/s` $\to$ `1 m/s` $\to$ `3 m/s` $\to$ `6 m/s` $\to$ `10 m/s` $\to$ `20 m/s+` (Yellow to Crimson ramp)
* **Real-Time Frame Statistics Cards**: Backend pre-calculated metrics displayed in real-time:
  - `WET PARTICLES`
  - `DOWNSTREAM PARTICLES`
  - `MAX DEPTH (m)`
  - `MAX VELOCITY (m/s)`
* **Permanent Prototype Disclaimer**:
  - `"Custom Terrain-SPH Demonstration Prototype"`
  - `"Hypothetical breach parameters — not engineering validated or intended for emergency decision-making."`

---

## 6. SIH 60-Second Demo Procedure

Follow this exact sequence during the live SIH jury demonstration:

1. **Navigate to Model Comparison**:
   - Open the web application.
   - Click on the **"Dam Onboarding & Studies"** tab in the sidebar.
   - Select the **"Hidkal Dam Demonstration Study"** project.
   - Click **"Stage 5: Multi-Model SWE & SPH Comparison"**.

2. **Trigger SPH Demonstration Run** *(or view existing completed run)*:
   - In the **Custom Terrain-SPH Demonstration** card, observe breach parameters (Mode: *Instantaneous*, Width: *50m*, Breach Start: *5s*).
   - Click **"▶ Run Terrain-SPH Simulation"**.
   - Wait ~4 seconds for the NumPy/SciPy Lagrangian solver to complete.

3. **Demonstrate Frame 0 Pre-Breach State**:
   - Notice the **Particle Animation** widget auto-loads and displays Frame 1 of 41 ($t = 0.0\text{ s}$).
   - Point to the state badge: `"🟢 Reservoir retained — dam intact"`.
   - Point to the statistics card: `Downstream: 0`, `Max Velocity: 0.00 m/s`, `Max Depth: 28.00 m`.
   - Point to the dam axis on the map: Solid red intact barrier line.

4. **Play Animation & Speed Selection**:
   - Click **"▶" (Play)**.
   - Watch the playback reach $t = 5.0\text{ s}$: state flips to `"🔴 Hypothetical instantaneous breach opened"`, dam axis line shifts to breach open state.
   - Watch the wave pass the breach at $t = 5.95\text{ s}$: state flips to `"🌊 Downstream flood propagation"`, downstream particles count increments to `1`, `2`, `3`.
   - Switch speed to **"2×"** to show fast-forward, then **"0.5×"** to inspect leading flood wave.

5. **Color Mode & Legends**:
   - Click **"💨 Flow Velocity"**: particles instantly re-color from depth blue to high-velocity orange/red.
   - Point out the scientific physical legend: `0 to 20+ m/s`.
   - Click **"💧 Water Depth"**: particles return to water depth color ramp.

6. **Interactive Seek & Reset**:
   - Drag the seek slider to $t = 12.0\text{ s}$ (Frame 21). Note that seeking automatically pauses playback.
   - Click **"↺ Reset"**: immediately snaps back to Frame 0 ($t = 0.0\text{ s}$) with dam intact.

---

## 7. Model Limitations & Scope Boundaries

* **Demonstration Prototype**: The depth-integrated SPH Lagrangian formulation is designed for near-field hydrodynamic wave visualization (<5 km from dam axis).
* **Instantaneous Breach Model**: The current solver simulates an instantaneous structural breach opening; progressive geotechnical erosion and sediment transport are not resolved.
* **Regional Downstream Inundation**: For long-range regional 2D shallow water routing and infrastructure exposure assessments, the system utilizes the ANUGA Finite Volume reference engine and Delft3D-FM packages.

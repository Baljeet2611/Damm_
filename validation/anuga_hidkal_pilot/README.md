# ANUGA Regional Hydrodynamic Pilot Simulation (Phase 15)

## 1. Scientific Status & Critical Warnings
> [!WARNING]
> **HYPOTHETICAL UNVERIFIED RESEARCH PILOT ONLY**
> 
> This simulation is an idealized numerical pilot designed exclusively for computational framework validation.
> - The DEM vertical datum and elevation units are **unverified** (reported as *assumed metres based on source interpretation*).
> - The dam breach location ($x = 462,600.0\text{ m}$ in UTM 43N), physical embankment barrier ($Z_{\text{crest}} = 675.0\text{ assumed m}$), breach geometry ($200\text{ m}$ instantaneous opening at $y \in [1791900, 1792100]$), initial reservoir pool level ($660.0$ assumed metres), and composite Manning roughness ($n = 0.035$) are **hypothetical assumptions**.
> - This simulation must **NEVER** be used for emergency evacuation decisions, official flood hazard mapping, or real-world disaster management.

---

## 2. Input Datasets & Topographic Preflight

- **Source Topography**: `data/raw/data_hidkal/hidkal_dem.tif`
  - SHA-256: `ed4c97474857ef24845f0954baa36b8de2555ccc2a0d468cfa99fdd39fab5baf`
  - Dimensions: $600\text{ rows} \times 700\text{ cols}$ ($420,000\text{ cells}$, $0$ NoData cells)
  - Elevation Range: $600.0001$ to $682.5000$ assumed metres based on source interpretation
- **Reprojection to EPSG:32643 (UTM Zone 43N)**:
  - Reprojected Grid: $443\text{ rows} \times 601\text{ cols}$ ($266,243\text{ cells}$ at $50\text{ m}$ resolution)
  - Valid Geographic Footprint: $264,832\text{ cells}$ ($662.08\text{ km}^2$, $99.47\%$)
  - Reprojection Corner NaNs: $1,411\text{ cells}$ ($3.53\text{ km}^2$, $0.53\%$) filled via nearest-neighbor distance transform exclusively for mesh boundary smoothness.
  - **Reprojection-filled Cell Isolation**: Excluded from flood metrics and verified to have 0 wetted cells and zero flow paths.
- **Domain Extent**:
  - Longitudinal ($X$): $457,200.0\text{ m}$ to $487,200.0\text{ m}$ ($30.0\text{ km}$)
  - Latitudinal ($Y$): $1,782,250.0\text{ m}$ to $1,804,350.0\text{ m}$ ($22.1\text{ km}$)
  - Total Domain Area: $663.0\text{ km}^2$

---

## 3. Physical Barrier & Breach Mechanics

### Dam Embankment Barrier & Breach Representation
- **Dam Embankment Axis**: Located at $X = 462,600.0\text{ m}$ spanning $Y \in [1,788,000.0\text{ m}, 1,796,000.0\text{ m}]$.
- **Impermeable Raised Crest**: Everywhere outside the breach along the dam axis, the elevation is raised to $Z_{\text{crest}} = 675.0\text{ assumed m}$ ($15.0\text{ m}$ above initial pool stage $660.0\text{ assumed m}$).
- **Breach Opening**: $200.0\text{ m}$ width spanning $Y \in [1,791,900.0\text{ m}, 1,792,100.0\text{ m}]$ at $X = 462,600.0\text{ m}$ where elevation is the natural riverbed invert ($Z \approx 634.5\text{ assumed m}$).
- **Perimeter Containment Walls**: North ($Y = 1,796,000\text{ m}$) and South ($Y = 1,788,000\text{ m}$) reservoir boundaries are raised to $Z_{\text{crest}} = 675.0\text{ assumed m}$.
- **West Reservoir Boundary**: Enclosed by reflective domain boundary wall ($X = 457,200\text{ m}$).

### Hydraulic Flux & Containment Audit
- **Peak Breach Discharge**: $9,794.37\text{ m}^3/\text{s}$
- **Cumulative Released Volume through Breach**: $14.349\text{ assumed MCM}$ ($14,348,619.30\text{ assumed m}^3$)
- **Non-Breach Leakage Volume**: $9,218.5\text{ assumed m}^3$ (leakage percentage = $0.064\% < 0.1\%$, verified numerically negligible)
- **North & South Perimeter Leakage**: $0.00\text{ assumed m}^3$
- **West Impermeable Boundary Leakage**: $0.00\text{ assumed m}^3$

---

## 4. Numerical Model Setup & SI Parameters

| Parameter | Assumed Value | Units | Description |
| :--- | :--- | :--- | :--- |
| Model Grid | $150 \times 110$ | cells | $66,000$ triangular finite-volume elements |
| Mesh Resolution ($\Delta x, \Delta y$) | $200.0 \times 200.0$ | m | Aligned mesh resolving the 200m breach opening |
| Dam Axis ($X_{dam}$) | $462,600.0$ | m | Physical embankment axis in UTM 43N |
| Dam Crest Elevation | $675.0$ | assumed m | Raised impermeable barrier |
| Breach Width | $200.0$ | m | Instantaneous release opening |
| Assumed Reservoir Extent | $X \in [457200, 462600], Y \in [1788000, 1796000]$ | m | Upstream reservoir storage box |
| Assumed Pool Stage ($w_0$) | $660.0$ | assumed m | Assumed water surface elevation |
| Downstream Initial Condition | $h = 0.0$ (Dry bed) | assumed m | Initially dry river bed |
| Manning Roughness ($n$) | $0.035$ | $\text{s/m}^{1/3}$ | Assumed composite riverbed roughness |
| Simulation Duration | $1800.0$ ($30\text{ min}$) | s | Dynamic Shallow Water time integration |
| Saved Yield Frames | $31$ | frames | Frame recording interval $\Delta t_{yield} = 60.0\text{ s}$ |
| Arrival Threshold | $0.10$ | assumed m | Minimum depth threshold for arrival timing |

### Boundary Conditions & Wave Isolation
- **Left / Top / Bottom**: Reflective (solid boundary walls / watershed ridgelines).
- **Right (East)**: Transmissive (downstream open discharge boundary for Ghataprabha river valley).
- **Boundary Interaction**: **no $\ge 0.1$ assumed-metre wetting detected within $1.54\text{ km}$ of the boundary** (minimum buffer to boundary is $5.43\text{ km}$).

---

## 5. Simulation Execution & Results

- **Solver**: ANUGA 2D Finite-Volume Shallow Water Solver (C-accelerated core, target CFL = 1.0)
- **Solver Runtime**: **$11.30\text{ s}$** wall time on Windows x64
- **Mass Balance Conservation**:
  - Initial Reservoir Stored Volume: **$317,161,860.23\text{ assumed m}^3$** ($317.16\text{ assumed MCM}$)
  - Final Computed Volume: **$317,161,860.23\text{ assumed m}^3$**
  - Relative Volume Difference: **$3.95 \times 10^{-15}$** (conserved within numerical precision)
- **Inundation Area Partitioning**:
  - Initial Reservoir Wet Area ($t = 0$): **$29.50\text{ km}^2$** (raster grid) / **$28.19\text{ km}^2$** (mesh)
  - Max Total Inundated Area: **$44.82\text{ km}^2$** (raster grid) / **$43.23\text{ km}^2$** (mesh)
  - **Newly Inundated Area**: **$15.32\text{ km}^2$** (raster grid) / **$13.88\text{ km}^2$** (mesh)
- **Hydraulic Results**:
  - Peak Inundation Water Depth: **$25.90\text{ assumed m}$** (Mean in wet zone: $6.87\text{ assumed m}$)
  - Peak Flow Velocity: **$11.64\text{ m/s}$** (Mean in wet zone: $4.42\text{ m/s}$)
  - Newly Wetted Arrival Range: **$60.0\text{ s}$ to $1,800.0\text{ s}$** (model-derived first detected arrival at 60 s output resolution; initial reservoir encoded as $0.0$, unflooded as $9999.0$ NoData)

---

## 6. File Structure & Manifest

```
validation/anuga_hidkal_pilot/
├── scenario_config.yml       # Explicit YAML configuration with assumption tags & barrier params
├── preprocess_dem.py         # Reprojects raw DEM to EPSG:32643 and preserves valid footprint mask
├── run_anuga_pilot.py        # Embankment barrier, 200m breach, flux tracking, ANUGA simulation
├── postprocess_outputs.py    # Excludes filled cells, extracts depth/velocity/arrival, exports GeoTIFFs
├── breach_diagnostics.json   # Effective width, coordinates, peak Q, volumes, leakage audit
├── pilot_summary.json        # Structured numerical summary report
├── manifest.json             # SHA-256 cryptographic hashes of all scripts and configs
├── README.md                 # Complete documentation and scientific disclosures
└── output/                   # Ignored directory for generated SWW, GeoTIFFs, and caches
```

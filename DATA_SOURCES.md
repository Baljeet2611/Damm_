# Data Sources Specification & Inventory

## 1. Inventory of Existing Local Datasets

The raw data has been extracted into `data/raw/` preserving the original archive files (`data_hidkal.zip` and `tifToTerrain.zip`) untouched in the workspace root.

### 1.1 Hidkal Dam Domain (`data/raw/data_hidkal/`)

Geographic Region: Downstream reach of Raja Lakhamagouda Dam (Hidkal Dam) on the Ghataprabha River, Hukkeri/Gokak Taluks, Belagavi District, Karnataka, India.

| File Name | Format | Dimensions | CRS | Spatial Bounds (WGS84) | Pixel Size (deg / approx m) | NoData Tag | Detected Range / Stats | Status / Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `hidkal_dem.tif` | GeoTIFF (Float32, uncompressed) | 700 x 600 (420,000 cells) | EPSG:4326 (WGS 84) | MinX: 74.600000° E<br>MinY: 16.120000° N<br>MaxX: 74.880000° E<br>MaxY: 16.320000° N | dx: 0.00040000° (~44.4 m)<br>dy: 0.00033333° (~36.9 m) | `-9999` (0 occurrences in raster) | Min: 600.0001<br>Max: 682.5<br>Mean: 630.8929 | Numeric range 600.0001–682.5; elevation unit and vertical datum unverified; continuous coverage, 100% valid cells. |
| `hidkal_depth.tif` | GeoTIFF (Float32, uncompressed) | 700 x 600 (420,000 cells) | EPSG:4326 (WGS 84) | MinX: 74.600000° E<br>MinY: 16.120000° N<br>MaxX: 74.880000° E<br>MaxY: 16.320000° N | dx: 0.00040000°<br>dy: 0.00033333° | `-9999` (0 occurrences in raster) | Zero cells: 284,904<br>Positive cells: 135,096<br>Max: 13.3386 | **Unverified sample raster of unknown provenance**. Zero values used for dry/unflooded cells; `-9999` metadata tag is absent in data. |
| `hidkal_velocity.tif` | GeoTIFF (Float32, uncompressed) | 700 x 600 (420,000 cells) | EPSG:4326 (WGS 84) | MinX: 74.600000° E<br>MinY: 16.120000° N<br>MaxX: 74.880000° E<br>MaxY: 16.320000° N | dx: 0.00040000°<br>dy: 0.00033333° | `-9999` (0 occurrences in raster) | Zero cells: 294,000<br>Positive cells: 126,000<br>Max: 21.5660 | **Unverified sample raster of unknown provenance**. Zero values used for dry cells; `-9999` metadata tag absent in data. |
| `hidkal_arrival.tif` | GeoTIFF (Float32, uncompressed) | 700 x 600 (420,000 cells) | EPSG:4326 (WGS 84) | MinX: 74.600000° E<br>MinY: 16.120000° N<br>MaxX: 74.880000° E<br>MaxY: 16.320000° N | dx: 0.00040000°<br>dy: 0.00033333° | Header tag: `-9999`<br>**Actual: `+9999.0`** | Total pixels: 420,000<br>`+9999`: 294,000<br>Valid: 126,000<br>`-9999`: 0<br>Valid range: 7.0–66.5 | **CRITICAL MISMATCH & Unverified Sample**. Unverified sample raster of unknown provenance. Unflooded cells encoded as `+9999.0`, conflicting with `-9999` metadata NoData. Unit unknown. |
| `hidkal_assets.geojson` | GeoJSON (FeatureCollection) | 513 features | EPSG:4326 (urn:ogc:def:crs:OGC:1.3:CRS84) | MinX: 74.602977° E<br>MinY: 16.121080° N<br>MaxX: 74.873340° E<br>MaxY: 16.315434° N | Vector geometries | N/A | 333 Polygons (buildings)<br>102 LineStrings (bridges, highways, railways)<br>78 Points (places/settlements, amenities) | Extracted from OpenStreetMap for Hidkal inundation corridor. Spatially contained within raster bounds. |
| `hidkal_roads.graphml` | GraphML (OSM XML network) | 3,084 nodes<br>8,047 edges | EPSG:4326 (node lat/lon `d4`/`d5`) | MinX: 74.600006° E<br>MinY: 16.121360° N<br>MaxX: 74.879961° E<br>MaxY: 16.319962° N | Directed network graph | N/A | Node keys: x, y, street_count, highway, railway<br>Edge keys: highway, oneway, length, lanes, bridge, tunnel, geometry | Generated via OSMnx 2.1.1 (2026-09-02). Spatial extents match the raster bounds. |

---

### 1.2 Standalone Terrain Demo Dataset (`data/raw/tifToTerrain/`)

| File Name | Format | Dimensions | CRS | Spatial Bounds | Pixel Size | NoData | Characteristics & Disconnection from Hidkal |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `default.tif` | GeoTIFF (Int16, LZW tiled 256x256) | 219 x 346 | EPSG:4326 | MinX: 70.808889° E<br>MinY: 22.759167° N<br>MaxX: 70.869722° E<br>MaxY: 22.855278° N | 0.00027778° x 0.00027778° (~30m SRTM) | None | **Completely outside Hidkal domain**. Located in Morbi district, Gujarat (~760 km NW of Hidkal Dam). Accompanied by `new.html` browser test prototype. |
| `new.html` | HTML5 / JavaScript | 238 lines | N/A | N/A | N/A | N/A | Standalone Three.js client-side 3D terrain visualizer using `geotiff.js` (reads `default.tif`, applies a 5x5 window smoothing filter, and generates 3D heightfield mesh). |

---

## 2. Key Geometric & Scientific Caveats of Current Rasters

1. **Unverified Simulation Warning**:
   The flood rasters (`hidkal_depth.tif`, `hidkal_velocity.tif`, `hidkal_arrival.tif`) are **unverified sample rasters of unknown provenance**. They must **never** be presented as validated hydrodynamic simulations or official engineering dam-break hazard maps. Calibrated breach hydrographs, hydraulic structures, roughness coefficients, and conservation verification are required before real-world operational use.
2. **Arrival NoData Mismatch**:
   In `hidkal_arrival.tif`, the TIFF metadata header lists `GDAL_NODATA = "-9999"`, but the actual unflooded array contains `+9999.0` for 294,000 cells (out of 420,000 total pixels, with 126,000 valid cells and 0 cells with value `-9999`). Default GIS pipelines that filter by header NoData will treat 9999 as a valid arrival time, producing wildly inaccurate flood propagation stats. A reclassification / masking step is mandatory. Valid arrival times range between 7.0 and 66.5, with units unknown.
3. **Dry Cell Encoding Discrepancy**:
   `hidkal_depth.tif` and `hidkal_velocity.tif` mark unflooded cells as `0.0` (depth zero: 284,904; velocity zero: 294,000), while keeping `GDAL_NODATA = "-9999"` in the header. Downstream damage analysis must distinguish between explicitly wet cells (depth > threshold, positive count: 135,096) and dry background cells.
4. **Elevation Units & Vertical Datum**:
   In `hidkal_dem.tif`, the values span the numeric range 600.0001–682.5; elevation unit and vertical datum are unverified.
5. **Non-Square Pixel Aspect Ratio**:
   The grid spacing in EPSG:4326 is `0.00040000°` longitude (~44.4 m) by `0.00033333°` latitude (~36.9 m). Numerical calculations involving gradient, slope, hydraulic radius, cell area, or velocity fluxes must project into metric planar CRS (e.g., UTM Zone 43N / EPSG:32643) to avoid anisotropic spatial distortion.

---

## 3. Planned External Data Sources

To construct a rigorous, operational dam-break modeling and impact analysis pipeline, the following external datasets are planned for integration:

### 3.1 Topography & Elevation
* **Bhuvan / CartoDEM**:
  * *Provider*: Indian Space Research Organisation (ISRO) / NRSC.
  * *Resolution*: 30 m (national) / 10 m (Cartosat-1/2 stereo pairs where available).
  * *Application*: Primary high-precision terrain model for Indian river basins, capturing local riverbed morphology and embankment levels better than global datasets.
* **SRTM / Copernicus DEM (GLO-30)**:
  * *Provider*: ESA / Copernicus / NASA.
  * *Resolution*: 30 m global elevation data.
  * *Application*: Baseline terrain backup and gap-filling for hydrologic conditioning.

### 3.2 Hydrological & Dam Parameters
* **India-WRIS (Water Resources Information System)**:
  * *Provider*: Ministry of Jal Shakti, Central Water Commission (CWC).
  * *Data*: Dam structural specifications (dam height, crest length, gross storage capacity, spillway type and capacity), historical gauge discharges, reservoir stage-storage-area curves.
  * *Application*: Parametrizing Froehlich / MacDonald-Langridge-Monopolis breach equations and initial reservoir head conditions.
* **NWDP (National Water Development Agency)** / Dam Safety Authority:
  * *Provider*: NWDA / CWC Dam Safety Organisation.
  * *Data*: Emergency Action Plans (EAP), Rule Curves, downstream cross-sections, and design flood estimates (PMF / SPF).
  * *Application*: Inflow boundary conditions, extreme scenario formulation, and downstream benchmark cross-sections.
* **HydroSHEDS & HydroRIVERS**:
  * *Provider*: WWF / USGS.
  * *Data*: Conditioned drainage networks, flow direction (D8), flow accumulation, river channel width and gradient estimates.
  * *Application*: Channel delineation, 1D/2D hydraulic model domain truncation, downstream boundary location selection.

### 3.3 Exposure, Infrastructure & Vulnerability
* **OpenStreetMap (OSM)**:
  * *Provider*: OpenStreetMap Foundation / Overpass API / Geofabrik India extracts.
  * *Data*: Road networks, railways, bridges, culverts, building footprints, critical facilities (hospitals, police stations, power sub-stations, schools).
  * *Application*: Exposure assessment, evacuation route graph construction, and physical asset inundation depth-damage curves.
* **WorldPop / LandScan Global Population Database**:
  * *Provider*: WorldPop Project (University of Southampton) / Oak Ridge National Laboratory.
  * *Resolution*: 100 m (1 km for LandScan).
  * *Application*: Population exposure estimation, vulnerable demographic density mapping, and life-safety risk assessment.

### 3.4 Satellite Earth Observation & Flood Validation
* **Google Earth Engine (GEE) / Copernicus Sentinel-1 SAR**:
  * *Provider*: ESA Copernicus via Google Earth Engine API.
  * *Data*: Sentinel-1 C-band Synthetic Aperture Radar (SAR) Ground Range Detected (GRD), Dual-polarization (VV + VH), 10 m spatial resolution, 6-12 day revisit.
  * *Application*: Historic flood surface delineation via SAR backscatter thresholding (Otsu / adaptive bimodal thresholding), cloud-penetrating inundation monitoring, and empirical ground-truth validation for hydraulic simulation footprints.
* **Sentinel-2 Multi-Spectral Instrument (MSI)**:
  * *Provider*: ESA Copernicus via GEE.
  * *Data*: 10 m optical bands (B2, B3, B4, B8) for NDWI (Normalized Difference Water Index) and MNDWI when cloud-free imagery is available during post-flood recession.

# System Architecture & Technical Specifications

```mermaid
graph TD
    subgraph Client ["Frontend Client (Vite + React + MapLibre GL)"]
        UI[Interactive Decision Support HUD]
        Map[MapLibre WebGL Canvas & Vector Overlays]
        Tabs[Layers | Exposure | Damage | Route | Export | Scenarios]
        SubTabs[Delft3D FM | PySPH SPH | Comparison | Earth Engine]
    end

    subgraph API ["Backend API (FastAPI)"]
        Router[API Router & Path-Safe Middleware]
        GZip[GZip Compression & Cache Middleware]
        Security[Coordinate & Bounds Validation Guard]
    end

    subgraph CoreServices ["Core Services"]
        RasterSvc[Raster Service: XYZ Tiles & Point Probing]
        VectorSvc[Vector Service: OSM Asset & Road Spatial Screening]
        DamageSvc[Damage Service: Parametric Vulnerability & Loss Curves]
        RouteSvc[Route Screening: NetworkX Topological Dijkstra]
        ExportSvc[Export Service: GeoJSON, KML, Multi-layer Shapefile ZIP]
        ScenarioSvc[Scenario & Storage Service: UUID JSON Store]
    end

    subgraph SimulationBoundaries ["Simulation & External Integration Boundaries"]
        HydroMTSvc[Delft3D-FM / HydroMT Model Package Builder]
        SPHSvc[PySPH Lagrangian Benchmark Adapter]
        CompSvc[Multi-Engine Spatial Comparison Engine]
        GEESvc[Google Earth Engine Catalog Connector]
    end

    subgraph Storage ["Storage & File System"]
        RawData[(Read-Only Raw Rasters & OSM Geometries)]
        RuntimeDir[(Isolated Local Runtime JSON & Log Store)]
    end

    UI --> Router
    Map --> Router
    Router --> GZip --> Security
    Security --> RasterSvc & VectorSvc & DamageSvc & RouteSvc & ExportSvc & ScenarioSvc
    Security --> HydroMTSvc & SPHSvc & CompSvc & GEESvc

    RasterSvc --> RawData
    VectorSvc --> RawData
    ScenarioSvc --> RuntimeDir
    HydroMTSvc --> RuntimeDir
    SPHSvc --> RuntimeDir
    CompSvc --> RuntimeDir
```

## 1. System Layers

### 1.1 Frontend Web Client
* **Framework**: React 19 + TypeScript + Vite.
* **Geospatial Renderer**: MapLibre GL JS (WebGL accelerated).
* **Styling**: Responsive Vanilla CSS tokens with high-contrast HUD cards, mobile/narrow panel support, container-aware grid layouts, and neutral dark canvas offline fallback.
* **State Management**: Pure React hooks with asynchronous debounced data fetchers and strict gating states.

### 1.2 Backend API Gateway
* **Framework**: FastAPI + Starlette + Uvicorn.
* **Performance & Network**: GZip response compression (`minimum_size=1000`), configurable `CORS_ORIGINS` with secure localhost defaults, and HTTP cache headers (`max-age=3600` on tiles/legends).
* **Security & Path Traversal Guards**: Strict UUID parameter validation, dataset ID whitelisting, coordinate bounding-box rejection (HTTP 422), and centralized exception handling shielding internal paths and stack traces.

### 1.3 Analytical & Spatial Services
* **Raster Service**: Point probing with NoData masking (`+9999.0` and `-9999`), on-the-fly 256x256 Web Mercator PNG tile generation with custom continuous color ramps.
* **Vector Exposure Service**: Spatial indexing (STRtree / R-tree), representative-point raster sampling, category classification (critical, commercial, residential, infrastructure).
* **Damage Estimator**: Piecewise depth-damage vulnerability interpolation, editable replacement valuations, sensitivity bounding (`±%`), and mandatory unverified-input acknowledgement.
* **Route Screening**: Local NetworkX directed road graph screening, topological flood avoidance, haversine edge weighting, and bridge/tunnel integrity disclaimers.
* **Multi-Format Exporter**: Filtered GeoJSON, Google Earth KML with custom styling, and Shapefile ZIP packaging separated by geometry type (`assets_points.shp`, `assets_lines.shp`, `assets_polygons.shp`) with accompanying metadata manifest.

### 1.4 Hydrodynamic & Benchmark Integration Boundaries
* **HydroMT-Delft3D FM Boundary**: Parametric dam breach configuration, atomic scenario revisions, automated `.ext`, `.mdu`, and `.dimr` input package generation with SHA-256 checksums, and gated solver execution (`ENABLE_DFLOWFM_EXECUTION=false`).
* **PySPH Lagrangian SPH Adapter**: 2D WCSPH dam-break benchmark generator, particle discretization (`dx`, `dt`), standalone script packaging, and gated solver execution (`ENABLE_PYSPH_EXECUTION=false`).
* **Multi-Engine Comparison Boundary**: Dynamic grid resampling, spatial extent Intersection over Union (IoU), Critical Success Index (CSI), and raster depth error statistics (`MAE`, `RMSE`, `Mean Bias`) requiring genuine verified runs.
* **Google Earth Engine Connector**: Whitelisted collection queries (`COPERNICUS/S1_GRD`, `NASA/GPM_L3/IMERG_V07`, `JRC/GSW1_4/GlobalSurfaceWater`), acquisition timestamp extraction, and gated background cloud task exports (`ENABLE_GEE_TASKS=false`).

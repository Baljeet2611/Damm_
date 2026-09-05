import { useEffect, useRef, useState, useCallback } from 'react'
import maplibregl, { Map as MapLibreMap, Marker, Popup } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import './App.css'

type LayerId = 'dem' | 'depth' | 'velocity' | 'arrival'

interface DatasetInfo {
  id: string
  label: string
  availability: boolean
  available?: boolean
  data_type: string
  unit_status: string
  provenance_status: string
}

interface ColorRampStop {
  offset: number
  color: string
  value: number
}

interface LegendItem {
  value: number
  color: string
  label: string
}

interface RasterLegend {
  id: string
  label: string
  unit_status: string
  provenance_status: string
  min_value: number | null
  max_value: number | null
  color_ramp: ColorRampStop[]
  items: LegendItem[]
}

interface PointValueResult {
  id: string
  row: number
  column: number
  value: number | null
  is_nodata: boolean
}

interface ProbeData {
  lon: number
  lat: number
  loading: boolean
  error: string | null
  values: Record<LayerId, PointValueResult | null>
}

interface CategoryCount {
  total: number
  assessed: number
  exposed: number
  not_exposed: number
  not_assessed: number
}

interface ExposureDatasetSummary {
  total: number
  assessed: number
  exposed: number
  not_exposed: number
  not_assessed: number
  by_category: Record<string, CategoryCount>
}

interface ExposureSummary {
  disclaimer: string
  methodology_note: string
  assets: ExposureDatasetSummary
  roads: ExposureDatasetSummary
}

// Phase 7: Damage Scenario Interfaces
interface DamageCurvePoint {
  depth: number
  damage_ratio: number
}

interface DamageConfig {
  assumed_depth_unit: string
  currency_label: string
  replacement_values: Record<string, number>
  depth_damage_curve: DamageCurvePoint[]
  sensitivity_percentage: number
  disclaimer: string
  methodology: string
}

interface TotalEstimates {
  base_loss: number
  low_loss: number
  high_loss: number
}

interface AssetCountSummary {
  total_assets: number
  assessed_assets: number
  screening_positive_assets: number
  not_exposed_assets: number
  not_assessed_assets: number
}

interface CategoryDamageResult {
  total_count: number
  screening_positive_count: number
  not_exposed_count: number
  not_assessed_count: number
  unit_replacement_value: number
  base_loss: number
  low_loss: number
  high_loss: number
}

interface DamageScenarioResult {
  disclaimer: string
  methodology: string
  currency_label: string
  assumed_depth_unit: string
  sensitivity_percentage: number
  total_estimates: TotalEstimates
  asset_counts: AssetCountSummary
  by_category: Record<string, CategoryDamageResult>
  warnings: string[]
}

// Phase 8: Route Screening Interface
interface RouteScreeningResult {
  route_found: boolean
  geojson: any | null
  total_distance_meters: number | null
  total_distance_km: number | null
  segment_count: number | null
  start_coords: [number, number]
  end_coords: [number, number]
  snapped_start_coords: [number, number] | null
  snapped_end_coords: [number, number] | null
  start_snap_distance_meters: number | null
  end_snap_distance_meters: number | null
  excluded_edges_count: number
  avoid_screening_positive: boolean
  disclaimer: string
  methodology: string
  warnings: string[]
}

// Phase 10 & 11: Scenario Management & Simulation Interfaces
interface ScenarioAssumption {
  parameter: string
  value: any
  unit: string
  status: string
  note: string
}

interface ScenarioItem {
  id: string
  name: string
  description: string
  site: string
  dem_dataset_id: string
  crs: string
  breach_width_m: number
  breach_formation_time_hr: number
  assumed_reservoir_level_m: number
  upstream_boundary_desc: string
  downstream_boundary_desc: string
  manning_roughness: number
  mesh_resolution_m: number
  simulation_duration_hr: number
  timestep_sec: number
  assumptions: ScenarioAssumption[]
  created_at: string
  updated_at: string
  revision: number
  archived: boolean
  status: string
  validation_notes: string[]
  snapshot_checksum?: string
}

interface SimulationCapabilities {
  hydromt_available: boolean
  hydromt_version: string | null
  hydromt_path: string | null
  dflowfm_available: boolean
  execution_enabled: boolean
  engine_executable: string | null
  disclaimer: string
  guidance: string
}

interface SimulationRunItem {
  run_id: string
  scenario_id: string
  scenario_name: string
  revision: number
  status: string
  started_at: string
  completed_at?: string
  duration_seconds?: number
  exit_code?: number
  log_url: string
  notes: string[]
}

interface SimulationLogs {
  run_id: string
  scenario_id: string
  status: string
  stdout: string
  stderr: string
}

// Hidkal Dam bounding box [minLon, minLat, maxLon, maxLat]
const HIDKAL_BOUNDS: [number, number, number, number] = [74.60, 16.12, 74.88, 16.32]

const LAYER_LABELS: Record<LayerId, { title: string; subtitle: string; icon: string }> = {
  dem: { title: 'Digital Elevation Model', subtitle: 'Topography & Terrain', icon: '⛰️' },
  depth: { title: 'Inundation Depth', subtitle: 'Peak Flood Water Depth', icon: '🌊' },
  velocity: { title: 'Flow Velocity', subtitle: 'Peak Hydrodynamic Speed', icon: '⚡' },
  arrival: { title: 'Wave Arrival Time', subtitle: 'Flood Front Arrival Time', icon: '⏱️' },
}

function App() {
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const markerRef = useRef<Marker | null>(null)
  const popupRef = useRef<Popup | null>(null)

  // Start / Destination Markers
  const startMarkerRef = useRef<Marker | null>(null)
  const endMarkerRef = useRef<Marker | null>(null)

  const [backendOnline, setBackendOnline] = useState<boolean | null>(null)
  const [datasets, setDatasets] = useState<DatasetInfo[]>([])
  const [selectedLayer, setSelectedLayer] = useState<LayerId>('depth')
  const [opacity, setOpacity] = useState<number>(0.85)
  const [legend, setLegend] = useState<RasterLegend | null>(null)
  const [legendLoading, setLegendLoading] = useState<boolean>(false)
  const [mapLoaded, setMapLoaded] = useState<boolean>(false)
  const [probe, setProbe] = useState<ProbeData | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true)

  // Vector Layer Toggles & Exposure Summary
  const [showAssets, setShowAssets] = useState<boolean>(true)
  const [showRoads, setShowRoads] = useState<boolean>(true)
  const [exposureSummary, setExposureSummary] = useState<ExposureSummary | null>(null)
  const [summaryLoading, setSummaryLoading] = useState<boolean>(false)
  const [activeTab, setActiveTab] = useState<'layers' | 'exposure' | 'damage' | 'route' | 'export' | 'scenarios'>('layers')

  // Phase 10 & 11: Scenario Management & Simulation State
  const [capabilities, setCapabilities] = useState<SimulationCapabilities | null>(null)
  const [scenarios, setScenarios] = useState<ScenarioItem[]>([])
  const [scenariosLoading, setScenariosLoading] = useState<boolean>(false)
  const [scenarioError, setScenarioError] = useState<string | null>(null)
  const [includeArchived, setIncludeArchived] = useState<boolean>(false)
  const [selectedScenarioId, setSelectedScenarioId] = useState<string | null>(null)
  const [isEditingScenario, setIsEditingScenario] = useState<boolean>(false)
  const [isCreatingScenario, setIsCreatingScenario] = useState<boolean>(false)
  const [packageBuilding, setPackageBuilding] = useState<boolean>(false)
  const [packageSuccessMsg, setPackageSuccessMsg] = useState<string | null>(null)
  const [runs, setRuns] = useState<SimulationRunItem[]>([])
  const [runsLoading, setRunsLoading] = useState<boolean>(false)
  const [runLogsModal, setRunLogsModal] = useState<SimulationLogs | null>(null)
  const [runExecuting, setRunExecuting] = useState<boolean>(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [showSetupGuide, setShowSetupGuide] = useState<boolean>(false)

  const [scenarioForm, setScenarioForm] = useState({
    name: '',
    description: '',
    site: 'Hidkal Dam, Belagavi, Karnataka',
    dem_dataset_id: 'dem',
    crs: 'EPSG:4326',
    breach_width_m: 100.0,
    breach_formation_time_hr: 2.0,
    assumed_reservoir_level_m: 660.0,
    upstream_boundary_desc: 'Dam breach failure hydrograph (illustrative)',
    downstream_boundary_desc: 'Free water-level slope outflow',
    manning_roughness: 0.035,
    mesh_resolution_m: 50.0,
    simulation_duration_hr: 24.0,
    timestep_sec: 1.0,
  })

  // Phase 7: Damage Scenario State
  const [damageConfig, setDamageConfig] = useState<DamageConfig | null>(null)
  const [currencyLabel, setCurrencyLabel] = useState<string>('INR (₹)')
  const [assumedDepthUnit, setAssumedDepthUnit] = useState<string>('assumed meters (unverified)')
  const [replacementValues, setReplacementValues] = useState<Record<string, number>>({})
  const [depthCurve, setDepthCurve] = useState<DamageCurvePoint[]>([])
  const [sensitivityPercent, setSensitivityPercent] = useState<number>(20.0)
  const [acknowledgeAssumptions, setAcknowledgeAssumptions] = useState<boolean>(false)
  const [damageResult, setDamageResult] = useState<DamageScenarioResult | null>(null)
  const [damageLoading, setDamageLoading] = useState<boolean>(false)
  const [damageError, setDamageError] = useState<string | null>(null)

  // Phase 8: Route Screening State
  const [startLon, setStartLon] = useState<number>(74.7085)
  const [startLat, setStartLat] = useState<number>(16.2052)
  const [endLon, setEndLon] = useState<number>(74.7289)
  const [endLat, setEndLat] = useState<number>(16.2415)
  const [avoidScreeningPositive, setAvoidScreeningPositive] = useState<boolean>(true)
  const [maxSnapDistance, setMaxSnapDistance] = useState<number>(5000)
  const [routePickMode, setRoutePickMode] = useState<'start' | 'dest' | null>(null)
  const [routeResult, setRouteResult] = useState<RouteScreeningResult | null>(null)
  const [routeLoading, setRouteLoading] = useState<boolean>(false)
  const [routeError, setRouteError] = useState<string | null>(null)

  // Ref to track routePickMode inside map click callbacks
  const routePickModeRef = useRef<'start' | 'dest' | null>(null)
  useEffect(() => {
    routePickModeRef.current = routePickMode
  }, [routePickMode])

  // Phase 9: Geospatial Export State
  const [exportLayer, setExportLayer] = useState<'assets' | 'roads' | 'route'>('assets')
  const [exportFilter, setExportFilter] = useState<'all' | 'screening_positive' | 'not_exposed' | 'not_assessed'>('all')
  const [exportFormat, setExportFormat] = useState<'geojson' | 'kml' | 'shp'>('geojson')
  const [exportLoading, setExportLoading] = useState<boolean>(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [exportSuccessMsg, setExportSuccessMsg] = useState<string | null>(null)

  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

  // Health check and dataset list
  useEffect(() => {
    fetch(`${apiBaseUrl}/api/health`)
      .then((res) => {
        if (!res.ok) throw new Error('Health check failed')
        return res.json()
      })
      .then(() => setBackendOnline(true))
      .catch(() => setBackendOnline(false))

    fetch(`${apiBaseUrl}/api/datasets`)
      .then((res) => res.json())
      .then((data: DatasetInfo[]) => setDatasets(data))
      .catch(() => {})
  }, [apiBaseUrl])

  // Fetch Exposure Summary
  useEffect(() => {
    setSummaryLoading(true)
    fetch(`${apiBaseUrl}/api/exposure/summary`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json() as Promise<ExposureSummary>
      })
      .then((data) => {
        setExposureSummary(data)
        setSummaryLoading(false)
      })
      .catch(() => {
        setSummaryLoading(false)
      })
  }, [apiBaseUrl])

  // Fetch Damage Scenario Defaults
  useEffect(() => {
    fetch(`${apiBaseUrl}/api/damage/config`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json() as Promise<DamageConfig>
      })
      .then((data) => {
        setDamageConfig(data)
        setCurrencyLabel(data.currency_label)
        setAssumedDepthUnit(data.assumed_depth_unit)
        setReplacementValues(data.replacement_values)
        setDepthCurve(data.depth_damage_curve)
        setSensitivityPercent(data.sensitivity_percentage)
      })
      .catch(() => {})
  }, [apiBaseUrl])

  // Fetch legend when active layer changes
  useEffect(() => {
    let isMounted = true
    setLegendLoading(true)

    fetch(`${apiBaseUrl}/api/rasters/${selectedLayer}/legend`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json() as Promise<RasterLegend>
      })
      .then((data) => {
        if (isMounted) {
          setLegend(data)
          setLegendLoading(false)
        }
      })
      .catch(() => {
        if (isMounted) {
          setLegend(null)
          setLegendLoading(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [apiBaseUrl, selectedLayer])

  // Initialize MapLibre map
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution:
              '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
          },
        },
        layers: [
          {
            id: 'osm-tiles',
            type: 'raster',
            source: 'osm',
            minzoom: 0,
            maxzoom: 19,
          },
        ],
      },
      bounds: [
        [HIDKAL_BOUNDS[0], HIDKAL_BOUNDS[1]],
        [HIDKAL_BOUNDS[2], HIDKAL_BOUNDS[3]],
      ],
      fitBoundsOptions: { padding: 40 },
    })

    map.addControl(new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }), 'top-right')

    map.on('load', () => {
      setMapLoaded(true)
    })

    mapRef.current = map

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  // Update Raster Layer on Map
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return

    const sourceId = 'raster-tiles-source'
    const layerId = 'raster-tiles-layer'
    const tileUrl = `${apiBaseUrl}/api/rasters/${selectedLayer}/tiles/{z}/{x}/{y}.png`

    if (map.getLayer(layerId)) {
      map.removeLayer(layerId)
    }
    if (map.getSource(sourceId)) {
      map.removeSource(sourceId)
    }

    map.addSource(sourceId, {
      type: 'raster',
      tiles: [tileUrl],
      tileSize: 256,
      bounds: HIDKAL_BOUNDS,
    })

    // Add raster layer beneath vector layers if they exist
    const firstVectorLayer = map.getLayer('roads-line') ? 'roads-line' : undefined

    map.addLayer(
      {
        id: layerId,
        type: 'raster',
        source: sourceId,
        paint: {
          'raster-opacity': opacity,
          'raster-fade-duration': 150,
        },
      },
      firstVectorLayer
    )
  }, [apiBaseUrl, selectedLayer, mapLoaded])

  // Update raster opacity dynamically
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return
    const layerId = 'raster-tiles-layer'
    if (map.getLayer(layerId)) {
      map.setPaintProperty(layerId, 'raster-opacity', opacity)
    }
  }, [opacity, mapLoaded])

  // Helper for vector click popup creation
  const handleVectorFeatureClick = useCallback((e: maplibregl.MapMouseEvent & { features?: any[] }) => {
    if (routePickModeRef.current) return // Requirement 8: Skip popup if in route pick mode
    if (!e.features || e.features.length === 0 || !mapRef.current) return

    const feat = e.features[0]
    const props = feat.properties || {}
    const isExposed = props.exposed === true || props.exposed === 'true'
    const isAssessed = props.assessed === true || props.assessed === 'true'
    const depthVal = props.depth_value != null && props.depth_value !== '' ? Number(props.depth_value) : null
    const velVal = props.velocity_value != null && props.velocity_value !== '' ? Number(props.velocity_value) : null
    const arrVal = props.arrival_value != null && props.arrival_value !== '' ? Number(props.arrival_value) : null

    const title = props.name || props.ref || props.osmid || (props.category ? `Asset: ${props.category}` : 'Feature')
    const category = props.category || 'other'
    const method = props.sampling_method || 'direct'

    if (popupRef.current) {
      popupRef.current.remove()
    }

    const badgeLabel = isExposed
      ? 'Screening-positive (depth > 0 at sample)'
      : isAssessed
      ? 'Not exposed at sample'
      : 'Not assessed'

    const badgeClass = isExposed
      ? 'badge-exposed'
      : isAssessed
      ? 'badge-safe'
      : 'badge-unassessed'

    const depthDisplay = depthVal !== null
      ? (depthVal > 0 ? `${depthVal.toFixed(2)} (unit unverified)` : '0.00 (not exposed at sample)')
      : 'Not assessed'

    const htmlContent = `
      <div class="vector-popup-card">
        <div class="vector-popup-header">
          <span class="vector-popup-icon">${isExposed ? '⚠️' : '🛡️'}</span>
          <div class="vector-popup-title-box">
            <h4 class="vector-popup-title">${title}</h4>
            <span class="vector-popup-badge ${badgeClass}">
              ${badgeLabel}
            </span>
          </div>
        </div>
        <div class="vector-popup-body">
          <div class="popup-row"><span class="popup-label">Category:</span> <strong class="popup-val">${category.toUpperCase()}</strong></div>
          <div class="popup-row"><span class="popup-label">Flood Depth:</span> <strong class="popup-val ${isExposed ? 'text-danger' : ''}">${depthDisplay}</strong></div>
          <div class="popup-row"><span class="popup-label">Velocity:</span> <strong class="popup-val">${velVal !== null ? `${velVal.toFixed(2)} (unit unverified)` : 'N/A'}</strong></div>
          <div class="popup-row"><span class="popup-label">Arrival Time:</span> <strong class="popup-val">${arrVal !== null ? `${arrVal.toFixed(2)} (unit unverified)` : 'N/A'}</strong></div>
          <div class="popup-row"><span class="popup-label">Sampling Method:</span> <span class="popup-method">${method}</span></div>
        </div>
        <div class="vector-popup-footer">
          <span>ℹ️ Preliminary exposure screening based on unverified sample rasters. Not a validated risk or damage assessment.</span>
        </div>
      </div>
    `

    popupRef.current = new maplibregl.Popup({ closeButton: true, closeOnClick: true, maxWidth: '320px' })
      .setLngLat(e.lngLat)
      .setHTML(htmlContent)
      .addTo(mapRef.current)
  }, [])

  // Manage Vector Road Network Layer
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return

    const sourceId = 'exposure-roads-source'
    const layerId = 'roads-line'

    if (!showRoads) {
      if (map.getLayer(layerId)) map.removeLayer(layerId)
      if (map.getSource(sourceId)) map.removeSource(sourceId)
      return
    }

    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, {
        type: 'geojson',
        data: `${apiBaseUrl}/api/exposure/roads`,
      })
    }

    if (!map.getLayer(layerId)) {
      map.addLayer({
        id: layerId,
        type: 'line',
        source: sourceId,
        paint: {
          'line-color': [
            'case',
            ['==', ['get', 'exposed'], true],
            '#e11d48', // Exposed = Crimson
            '#64748b', // Not exposed at sample = Slate
          ],
          'line-width': [
            'case',
            ['==', ['get', 'exposed'], true],
            3.2,
            1.6,
          ],
          'line-opacity': 0.88,
        },
      })

      map.on('click', layerId, handleVectorFeatureClick)
      map.on('mouseenter', layerId, () => {
        if (!routePickModeRef.current) map.getCanvas().style.cursor = 'pointer'
      })
      map.on('mouseleave', layerId, () => {
        if (!routePickModeRef.current) map.getCanvas().style.cursor = ''
      })
    }
  }, [apiBaseUrl, showRoads, mapLoaded, handleVectorFeatureClick])

  // Manage Vector Assets Layer (Polygons, Lines, Points)
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return

    const sourceId = 'exposure-assets-source'
    const fillLayerId = 'assets-polygons-fill'
    const lineLayerId = 'assets-polygons-line'
    const linesLayerId = 'assets-lines'
    const pointLayerId = 'assets-points'

    const layerIds = [fillLayerId, lineLayerId, linesLayerId, pointLayerId]

    if (!showAssets) {
      layerIds.forEach((id) => {
        if (map.getLayer(id)) map.removeLayer(id)
      })
      if (map.getSource(sourceId)) map.removeSource(sourceId)
      return
    }

    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, {
        type: 'geojson',
        data: `${apiBaseUrl}/api/exposure/assets`,
      })
    }

    // 1. Asset Polygons (Buildings/Facilities)
    if (!map.getLayer(fillLayerId)) {
      map.addLayer({
        id: fillLayerId,
        type: 'fill',
        source: sourceId,
        filter: ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]],
        paint: {
          'fill-color': [
            'case',
            ['==', ['get', 'exposed'], true],
            '#ef4444', // Screening-positive = Red
            '#10b981', // Not exposed at sample = Emerald
          ],
          'fill-opacity': [
            'case',
            ['==', ['get', 'exposed'], true],
            0.65,
            0.35,
          ],
        },
      })

      map.addLayer({
        id: lineLayerId,
        type: 'line',
        source: sourceId,
        filter: ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]],
        paint: {
          'line-color': [
            'case',
            ['==', ['get', 'exposed'], true],
            '#b91c1c',
            '#047857',
          ],
          'line-width': 1.5,
        },
      })
    }

    // 2. Asset Lines (Bridges / Rails / Transport links)
    if (!map.getLayer(linesLayerId)) {
      map.addLayer({
        id: linesLayerId,
        type: 'line',
        source: sourceId,
        filter: ['in', ['geometry-type'], ['literal', ['LineString', 'MultiLineString']]],
        paint: {
          'line-color': [
            'case',
            ['==', ['get', 'exposed'], true],
            '#dc2626',
            '#0284c7',
          ],
          'line-width': [
            'case',
            ['==', ['get', 'exposed'], true],
            3.5,
            2.0,
          ],
        },
      })
    }

    // 3. Asset Points (Settlements / Amenities / Hospitals / Schools)
    if (!map.getLayer(pointLayerId)) {
      map.addLayer({
        id: pointLayerId,
        type: 'circle',
        source: sourceId,
        filter: ['==', ['geometry-type'], 'Point'],
        paint: {
          'circle-color': [
            'case',
            ['==', ['get', 'exposed'], true],
            '#ef4444',
            '#10b981',
          ],
          'circle-radius': [
            'case',
            ['==', ['get', 'exposed'], true],
            7.0,
            5.0,
          ],
          'circle-stroke-width': 2,
          'circle-stroke-color': '#ffffff',
        },
      })
    }

    // Attach click and hover handlers
    layerIds.forEach((id) => {
      map.on('click', id, handleVectorFeatureClick)
      map.on('mouseenter', id, () => {
        if (!routePickModeRef.current) map.getCanvas().style.cursor = 'pointer'
      })
      map.on('mouseleave', id, () => {
        if (!routePickModeRef.current) map.getCanvas().style.cursor = ''
      })
    })
  }, [apiBaseUrl, showAssets, mapLoaded, handleVectorFeatureClick])

  // Update Start & Destination Markers on Map
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return

    // Start Marker
    if (!startMarkerRef.current) {
      const el = document.createElement('div')
      el.className = 'route-pin-marker pin-start'
      el.innerHTML = '<span class="pin-icon">📍</span><span class="pin-badge">Start</span>'
      startMarkerRef.current = new maplibregl.Marker({ element: el })
        .setLngLat([startLon, startLat])
        .addTo(map)
    } else {
      startMarkerRef.current.setLngLat([startLon, startLat])
    }

    // Destination Marker
    if (!endMarkerRef.current) {
      const el = document.createElement('div')
      el.className = 'route-pin-marker pin-dest'
      el.innerHTML = '<span class="pin-icon">🎯</span><span class="pin-badge">Dest</span>'
      endMarkerRef.current = new maplibregl.Marker({ element: el })
        .setLngLat([endLon, endLat])
        .addTo(map)
    } else {
      endMarkerRef.current.setLngLat([endLon, endLat])
    }
  }, [startLon, startLat, endLon, endLat, mapLoaded])

  // Render Screened Route Line on Map
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return

    const sourceId = 'screened-route-source'
    const casingLayerId = 'screened-route-casing'
    const lineLayerId = 'screened-route-line'

    if (!routeResult || !routeResult.route_found || !routeResult.geojson) {
      if (map.getLayer(lineLayerId)) map.removeLayer(lineLayerId)
      if (map.getLayer(casingLayerId)) map.removeLayer(casingLayerId)
      if (map.getSource(sourceId)) map.removeSource(sourceId)
      return
    }

    const geojsonData = {
      type: 'FeatureCollection',
      features: [routeResult.geojson],
    }

    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, {
        type: 'geojson',
        data: geojsonData,
      })
    } else {
      const src = map.getSource(sourceId) as maplibregl.GeoJSONSource
      src.setData(geojsonData as any)
    }

    if (!map.getLayer(casingLayerId)) {
      map.addLayer({
        id: casingLayerId,
        type: 'line',
        source: sourceId,
        paint: {
          'line-color': '#0284c7',
          'line-width': 7,
          'line-opacity': 0.85,
        },
      })
    }

    if (!map.getLayer(lineLayerId)) {
      map.addLayer({
        id: lineLayerId,
        type: 'line',
        source: sourceId,
        paint: {
          'line-color': '#00f0ff',
          'line-width': 3.8,
          'line-opacity': 1.0,
        },
      })
    }
  }, [routeResult, mapLoaded])

  // Fit map to Hidkal bounds
  const fitToHidkal = useCallback(() => {
    if (!mapRef.current) return
    mapRef.current.fitBounds(
      [
        [HIDKAL_BOUNDS[0], HIDKAL_BOUNDS[1]],
        [HIDKAL_BOUNDS[2], HIDKAL_BOUNDS[3]],
      ],
      { padding: 50, duration: 1000 }
    )
  }, [])

  // Handle Map Click - Point Inspection Probe & Route Point Picking (Requirement 8)
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const handleMapClick = (e: maplibregl.MapMouseEvent) => {
      const { lng, lat } = e.lngLat
      const queryLon = Number(lng.toFixed(5))
      const queryLat = Number(lat.toFixed(5))

      // Requirement 8: If picking route start or destination, set coords and do not trigger probe/popup
      if (routePickModeRef.current === 'start') {
        setStartLon(queryLon)
        setStartLat(queryLat)
        setRoutePickMode(null)
        return
      }
      if (routePickModeRef.current === 'dest') {
        setEndLon(queryLon)
        setEndLat(queryLat)
        setRoutePickMode(null)
        return
      }

      // If a vector feature was clicked, don't overwrite with blank probe
      const vectorFeatures = map.queryRenderedFeatures(e.point, {
        layers: ['assets-polygons-fill', 'assets-lines', 'assets-points', 'roads-line'].filter((id) => map.getLayer(id)),
      })

      if (vectorFeatures.length > 0) {
        return
      }

      // Update or create probe marker
      if (!markerRef.current) {
        const el = document.createElement('div')
        el.className = 'custom-map-marker'
        el.innerHTML = '📍'
        markerRef.current = new maplibregl.Marker({ element: el }).setLngLat([lng, lat]).addTo(map)
      } else {
        markerRef.current.setLngLat([lng, lat])
      }

      setProbe({
        lon: queryLon,
        lat: queryLat,
        loading: true,
        error: null,
        values: { dem: null, depth: null, velocity: null, arrival: null },
      })

      // Query all 4 rasters simultaneously
      const layerIds: LayerId[] = ['dem', 'depth', 'velocity', 'arrival']
      const promises = layerIds.map((id) =>
        fetch(`${apiBaseUrl}/api/rasters/${id}/value?lon=${queryLon}&lat=${queryLat}`)
          .then((res) => {
            if (res.status === 422) {
              return { id, row: 0, column: 0, value: null, is_nodata: true, outside: true }
            }
            if (!res.ok) throw new Error(`HTTP ${res.status}`)
            return res.json() as Promise<PointValueResult>
          })
          .catch(() => null)
      )

      Promise.all(promises).then((results) => {
        const newValues: Record<LayerId, PointValueResult | null> = {
          dem: null,
          depth: null,
          velocity: null,
          arrival: null,
        }
        let allOutside = true
        results.forEach((res, index) => {
          const lid = layerIds[index]
          if (res) {
            newValues[lid] = res
            if (!('outside' in res)) {
              allOutside = false
            }
          }
        })

        setProbe({
          lon: queryLon,
          lat: queryLat,
          loading: false,
          error: allOutside ? 'Location is outside Hidkal domain extent.' : null,
          values: newValues,
        })
      })
    }

    map.on('click', handleMapClick)
    return () => {
      map.off('click', handleMapClick)
    }
  }, [apiBaseUrl])

  // Execute Damage Estimation
  const handleCalculateDamage = () => {
    if (!acknowledgeAssumptions) return

    setDamageLoading(true)
    setDamageError(null)

    const payload = {
      assumed_depth_unit: assumedDepthUnit,
      currency_label: currencyLabel,
      replacement_values: replacementValues,
      depth_damage_curve: depthCurve,
      sensitivity_percentage: sensitivityPercent,
      acknowledge_unverified_inputs: acknowledgeAssumptions,
    }

    fetch(`${apiBaseUrl}/api/damage/estimate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(async (res) => {
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}))
          throw new Error(errData.detail || `Server error (HTTP ${res.status})`)
        }
        return res.json() as Promise<DamageScenarioResult>
      })
      .then((data) => {
        setDamageResult(data)
        setDamageLoading(false)
      })
      .catch((err) => {
        setDamageError(err.message || 'Damage calculation failed.')
        setDamageLoading(false)
      })
  }

  const handleResetDamageDefaults = () => {
    if (!damageConfig) return
    setCurrencyLabel(damageConfig.currency_label)
    setAssumedDepthUnit(damageConfig.assumed_depth_unit)
    setReplacementValues(damageConfig.replacement_values)
    setDepthCurve(damageConfig.depth_damage_curve)
    setSensitivityPercent(damageConfig.sensitivity_percentage)
    setDamageResult(null)
    setDamageError(null)
  }

  const handleCurveChange = (index: number, field: 'depth' | 'damage_ratio', val: number) => {
    const updated = [...depthCurve]
    updated[index] = { ...updated[index], [field]: val }
    setDepthCurve(updated)
  }

  const handleAddCurvePoint = () => {
    const lastPt = depthCurve[depthCurve.length - 1] || { depth: 0, damage_ratio: 0 }
    setDepthCurve([...depthCurve, { depth: Number((lastPt.depth + 1.0).toFixed(1)), damage_ratio: Math.min(1.0, Number((lastPt.damage_ratio + 0.1).toFixed(2))) }])
  }

  const handleRemoveCurvePoint = (index: number) => {
    if (depthCurve.length <= 2) return
    setDepthCurve(depthCurve.filter((_, i) => i !== index))
  }

  // Execute Route Screening Calculation
  const handleCalculateRoute = () => {
    setRouteLoading(true)
    setRouteError(null)

    const payload = {
      start_lon: startLon,
      start_lat: startLat,
      end_lon: endLon,
      end_lat: endLat,
      avoid_screening_positive: avoidScreeningPositive,
      max_snap_distance_meters: maxSnapDistance,
    }

    fetch(`${apiBaseUrl}/api/routes/screening`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(async (res) => {
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}))
          throw new Error(errData.detail || `Routing error (HTTP ${res.status})`)
        }
        return res.json() as Promise<RouteScreeningResult>
      })
      .then((data) => {
        setRouteResult(data)
        setRouteLoading(false)
      })
      .catch((err) => {
        setRouteError(err.message || 'Route screening failed.')
        setRouteLoading(false)
      })
  }

  const handleClearRoute = () => {
    setRouteResult(null)
    setRouteError(null)
  }

  // Execute Geospatial Export Download
  const handleDownloadExport = async () => {
    setExportLoading(true)
    setExportError(null)
    setExportSuccessMsg(null)

    try {
      let url = ''
      let options: RequestInit = {}

      if (exportLayer === 'route') {
        if (!routeResult || !routeResult.route_found) {
          throw new Error('Please calculate a valid screening route in the Route tab first.')
        }
        url = `${apiBaseUrl}/api/export/route`
        options = {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            format: exportFormat,
            route_request: {
              start_lon: startLon,
              start_lat: startLat,
              end_lon: endLon,
              end_lat: endLat,
              avoid_screening_positive: avoidScreeningPositive,
              max_snap_distance_meters: maxSnapDistance,
            },
          }),
        }
      } else {
        url = `${apiBaseUrl}/api/export/${exportLayer}?format=${exportFormat}&exposure_filter=${exportFilter}`
        options = { method: 'GET' }
      }

      const res = await fetch(url, options)
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || `Export failed with HTTP ${res.status}`)
      }

      // Read filename from Content-Disposition header
      const disp = res.headers.get('Content-Disposition')
      let filename = `dam_break_${exportLayer}_${exportFilter}.${exportFormat === 'shp' ? 'zip' : exportFormat}`
      if (disp && disp.includes('filename=')) {
        const match = disp.match(/filename="?([^";]+)"?/)
        if (match && match[1]) filename = match[1]
      }

      const blob = await res.blob()
      const blobUrl = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(blobUrl)

      setExportSuccessMsg(`Successfully downloaded ${filename}`)
    } catch (err: any) {
      setExportError(err.message || 'Export generation failed')
    } finally {
      setExportLoading(false)
    }
  }

  const formatCurrency = (val: number) => {
    return val.toLocaleString('en-IN', { maximumFractionDigits: 0 })
  }

  // Phase 10 & 11 Action Handlers
  const fetchCapabilities = () => {
    fetch(`${apiBaseUrl}/api/simulation/capabilities`)
      .then((res) => res.json())
      .then((data: SimulationCapabilities) => setCapabilities(data))
      .catch(() => {})
  }

  const fetchScenarios = (archived = includeArchived) => {
    setScenariosLoading(true)
    fetch(`${apiBaseUrl}/api/scenarios?include_archived=${archived}`)
      .then((res) => res.json())
      .then((data: ScenarioItem[]) => {
        setScenarios(data)
        setScenariosLoading(false)
        if (data.length > 0 && !selectedScenarioId) {
          setSelectedScenarioId(data[0].id)
        }
      })
      .catch((err) => {
        setScenarioError(err.message || 'Failed to load scenarios')
        setScenariosLoading(false)
      })
  }

  const fetchRuns = () => {
    setRunsLoading(true)
    fetch(`${apiBaseUrl}/api/runs`)
      .then((res) => res.json())
      .then((data: SimulationRunItem[]) => {
        setRuns(data)
        setRunsLoading(false)
      })
      .catch(() => setRunsLoading(false))
  }

  useEffect(() => {
    fetchCapabilities()
    fetchScenarios(false)
    fetchRuns()
  }, [apiBaseUrl])

  useEffect(() => {
    if (activeTab === 'scenarios') {
      fetchCapabilities()
      fetchScenarios(includeArchived)
      fetchRuns()
    }
  }, [activeTab, includeArchived])

  const selectedScenario = scenarios.find((s) => s.id === selectedScenarioId) || null

  const handleStartCreateScenario = () => {
    setIsCreatingScenario(true)
    setIsEditingScenario(false)
    setScenarioForm({
      name: `Hidkal Dam Breach Scenario ${scenarios.length + 1}`,
      description: 'Parametric breach scenario for far-field inundation screening.',
      site: 'Hidkal Dam, Belagavi, Karnataka',
      dem_dataset_id: 'dem',
      crs: 'EPSG:4326',
      breach_width_m: 120.0,
      breach_formation_time_hr: 2.0,
      assumed_reservoir_level_m: 660.0,
      upstream_boundary_desc: 'Dam breach failure hydrograph (illustrative)',
      downstream_boundary_desc: 'Free water-level slope outflow',
      manning_roughness: 0.035,
      mesh_resolution_m: 50.0,
      simulation_duration_hr: 24.0,
      timestep_sec: 1.0,
    })
  }

  const handleStartEditScenario = (sc: ScenarioItem) => {
    setIsCreatingScenario(false)
    setIsEditingScenario(true)
    setSelectedScenarioId(sc.id)
    setScenarioForm({
      name: sc.name,
      description: sc.description,
      site: sc.site,
      dem_dataset_id: sc.dem_dataset_id,
      crs: sc.crs,
      breach_width_m: sc.breach_width_m,
      breach_formation_time_hr: sc.breach_formation_time_hr,
      assumed_reservoir_level_m: sc.assumed_reservoir_level_m,
      upstream_boundary_desc: sc.upstream_boundary_desc,
      downstream_boundary_desc: sc.downstream_boundary_desc,
      manning_roughness: sc.manning_roughness,
      mesh_resolution_m: sc.mesh_resolution_m,
      simulation_duration_hr: sc.simulation_duration_hr,
      timestep_sec: sc.timestep_sec,
    })
  }

  const handleSaveScenario = async () => {
    setScenarioError(null)
    try {
      if (isCreatingScenario) {
        const res = await fetch(`${apiBaseUrl}/api/scenarios`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(scenarioForm),
        })
        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          throw new Error(err.detail || `Failed to create scenario (HTTP ${res.status})`)
        }
        const created: ScenarioItem = await res.json()
        setIsCreatingScenario(false)
        fetchScenarios(includeArchived)
        setSelectedScenarioId(created.id)
      } else if (isEditingScenario && selectedScenarioId) {
        const res = await fetch(`${apiBaseUrl}/api/scenarios/${selectedScenarioId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(scenarioForm),
        })
        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          throw new Error(err.detail || `Failed to update scenario (HTTP ${res.status})`)
        }
        setIsEditingScenario(false)
        fetchScenarios(includeArchived)
      }
    } catch (err: any) {
      setScenarioError(err.message || 'Scenario save failed')
    }
  }

  const handleCloneScenario = async (scId: string) => {
    setScenarioError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/scenarios/${scId}/clone`, { method: 'POST' })
      if (!res.ok) throw new Error(`Clone failed with HTTP ${res.status}`)
      const cloned: ScenarioItem = await res.json()
      fetchScenarios(includeArchived)
      setSelectedScenarioId(cloned.id)
    } catch (err: any) {
      setScenarioError(err.message || 'Failed to clone scenario')
    }
  }

  const handleArchiveScenario = async (scId: string, archive: boolean) => {
    setScenarioError(null)
    try {
      const endpoint = archive ? 'archive' : 'unarchive'
      const res = await fetch(`${apiBaseUrl}/api/scenarios/${scId}/${endpoint}`, { method: 'POST' })
      if (!res.ok) throw new Error(`Archive operation failed with HTTP ${res.status}`)
      fetchScenarios(includeArchived)
    } catch (err: any) {
      setScenarioError(err.message || 'Failed to archive scenario')
    }
  }

  const handleBuildPackage = async (scId: string) => {
    setPackageBuilding(true)
    setPackageSuccessMsg(null)
    setScenarioError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/scenarios/${scId}/build-package`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `Package build failed with HTTP ${res.status}`)
      }
      const data = await res.json()
      setPackageSuccessMsg(`Package built (${(data.package_size_bytes / 1024).toFixed(1)} KB) with SHA-256 manifest.`)
      fetchScenarios(includeArchived)
    } catch (err: any) {
      setScenarioError(err.message || 'Package build failed')
    } finally {
      setPackageBuilding(false)
    }
  }

  const handleDownloadPackage = (scId: string) => {
    window.open(`${apiBaseUrl}/api/scenarios/${scId}/download-package`, '_blank')
  }

  const handleRunSimulation = async (scId: string) => {
    setRunExecuting(true)
    setRunError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/scenarios/${scId}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ custom_notes: 'Triggered from web GUI' }),
      })
      if (res.status === 409) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'D-Flow FM engine execution is disabled by server policy. Never faking a model run.')
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `Run failed with HTTP ${res.status}`)
      }
      fetchRuns()
    } catch (err: any) {
      setRunError(err.message || 'Simulation execution failed.')
    } finally {
      setRunExecuting(false)
    }
  }

  const handleViewLogs = async (runId: string) => {
    try {
      const res = await fetch(`${apiBaseUrl}/api/runs/${runId}/logs`)
      if (!res.ok) throw new Error('Failed to fetch run logs')
      const data: SimulationLogs = await res.json()
      setRunLogsModal(data)
    } catch (err) {
      alert('Could not retrieve execution logs for this run.')
    }
  }

  return (
    <div className="app-layout">
      {/* Top Navigation & Warning Banner */}
      <header className="app-header">
        <div className="header-brand">
          <div className="brand-logo">🌊</div>
          <div>
            <h1 className="brand-title">Dam Break Decision Support System</h1>
            <p className="brand-subtitle">SIH26161 • Hydrodynamic Inundation & Hazard Analytics</p>
          </div>
        </div>

        {/* Mandatory Scientific Disclaimer Banner */}
        <div className="warning-banner" role="alert">
          <span className="warning-icon">⚠️</span>
          <span className="warning-text">Unverified sample outputs — not a validated prediction.</span>
        </div>

        <div className="header-actions">
          <div className={`status-indicator ${backendOnline ? 'online' : backendOnline === false ? 'offline' : 'checking'}`}>
            <span className="status-dot"></span>
            <span>{backendOnline ? 'API Connected' : backendOnline === false ? 'API Offline' : 'Connecting...'}</span>
          </div>
          <button
            className="hud-toggle-btn"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            title="Toggle Controls Panel"
          >
            {sidebarOpen ? 'Hide Panel' : 'Show Panel'}
          </button>
        </div>
      </header>

      {/* Main Workspace with Map & Floating Panels */}
      <main className="map-workspace">
        <div ref={mapContainerRef} className="map-canvas" id="map-container" />

        {/* Route Picking Mode Indicator Banner */}
        {routePickMode && (
          <div className="pick-mode-banner">
            <span className="pick-mode-icon">📍</span>
            <span>
              Click on the map to place <strong>{routePickMode === 'start' ? 'Start Point (Green)' : 'Destination Point (Purple)'}</strong>
            </span>
            <button className="btn-cancel-pick" onClick={() => setRoutePickMode(null)}>✕ Cancel</button>
          </div>
        )}

        {/* Floating Sidebar / Control HUD */}
        {sidebarOpen && (
          <aside className="hud-panel">
            {/* Panel Tab Navigation (5 Tabs) */}
            <div className="hud-tabs">
              <button
                className={`hud-tab-btn ${activeTab === 'layers' ? 'active' : ''}`}
                onClick={() => setActiveTab('layers')}
              >
                🗺️ Layers
              </button>
              <button
                className={`hud-tab-btn ${activeTab === 'exposure' ? 'active' : ''}`}
                onClick={() => setActiveTab('exposure')}
              >
                📊 Exposure
              </button>
              <button
                className={`hud-tab-btn ${activeTab === 'damage' ? 'active' : ''}`}
                onClick={() => setActiveTab('damage')}
              >
                💰 Damage
              </button>
              <button
                className={`hud-tab-btn ${activeTab === 'route' ? 'active' : ''}`}
                onClick={() => setActiveTab('route')}
              >
                🛣️ Route
              </button>
              <button
                className={`hud-tab-btn ${activeTab === 'export' ? 'active' : ''}`}
                onClick={() => setActiveTab('export')}
              >
                💾 Export
              </button>
              <button
                className={`hud-tab-btn ${activeTab === 'scenarios' ? 'active' : ''}`}
                onClick={() => setActiveTab('scenarios')}
              >
                🌊 Scenarios
              </button>
            </div>

            {/* TAB 1: Hydrodynamic & Vector Layers */}
            {activeTab === 'layers' && (
              <>
                {/* Vector Overlays Toggle Card */}
                <div className="hud-card vector-controls-card">
                  <div className="hud-card-header">
                    <h3>Vector Overlays & Exposure</h3>
                    <button className="btn-fit" onClick={fitToHidkal} title="Fit map to Hidkal bounds">
                      🎯 Fit Hidkal
                    </button>
                  </div>

                  <div className="vector-toggles">
                    <label className="toggle-checkbox-row">
                      <input
                        type="checkbox"
                        checked={showAssets}
                        onChange={(e) => setShowAssets(e.target.checked)}
                      />
                      <div className="toggle-label-content">
                        <span className="toggle-title">🏛️ Infrastructure Assets (513)</span>
                        <span className="toggle-desc">Buildings, Healthcare, Settlements, Bridges</span>
                      </div>
                    </label>

                    <label className="toggle-checkbox-row">
                      <input
                        type="checkbox"
                        checked={showRoads}
                        onChange={(e) => setShowRoads(e.target.checked)}
                      />
                      <div className="toggle-label-content">
                        <span className="toggle-title">🛣️ Road Network Graph (8,047)</span>
                        <span className="toggle-desc">Primary, Secondary, Tertiary & Residential roads</span>
                      </div>
                    </label>
                  </div>

                  {/* Vector Styling Key */}
                  <div className="vector-style-key">
                    <div className="style-key-item">
                      <span className="style-chip chip-exposed" />
                      <span>Screening-positive (depth &gt; 0 at sample)</span>
                    </div>
                    <div className="style-key-item">
                      <span className="style-chip chip-safe" />
                      <span>Not exposed at sample</span>
                    </div>
                    <div className="style-key-item">
                      <span className="style-chip chip-unassessed" />
                      <span>Not assessed</span>
                    </div>
                  </div>
                </div>

                {/* Layer Selector Card */}
                <div className="hud-card">
                  <div className="hud-card-header">
                    <h3>Hydrodynamic Raster Layers</h3>
                    <span className="legend-tag">{selectedLayer.toUpperCase()}</span>
                  </div>

                  <div className="layer-options">
                    {(['dem', 'depth', 'velocity', 'arrival'] as LayerId[]).map((layerId) => {
                      const meta = LAYER_LABELS[layerId]
                      const isSelected = selectedLayer === layerId
                      const ds = datasets.find((d) => d.id === layerId)
                      const isAvailable = ds?.available ?? ds?.availability ?? true

                      return (
                        <button
                          key={layerId}
                          className={`layer-option-btn ${isSelected ? 'active' : ''}`}
                          onClick={() => setSelectedLayer(layerId)}
                        >
                          <span className="layer-btn-icon">{meta.icon}</span>
                          <div className="layer-btn-text">
                            <span className="layer-btn-title">{meta.title}</span>
                            <span className="layer-btn-sub">{meta.subtitle}</span>
                          </div>
                          <div className="layer-badges">
                            {!isAvailable && <span className="layer-unavailable-badge">Offline</span>}
                            {isSelected && <span className="layer-active-badge">Active</span>}
                          </div>
                        </button>
                      )
                    })}
                  </div>

                  {/* Opacity Control */}
                  <div className="opacity-control">
                    <div className="opacity-header">
                      <label htmlFor="opacity-slider">Raster Opacity</label>
                      <span className="opacity-val">{Math.round(opacity * 100)}%</span>
                    </div>
                    <input
                      id="opacity-slider"
                      type="range"
                      min="0"
                      max="1"
                      step="0.05"
                      value={opacity}
                      onChange={(e) => setOpacity(parseFloat(e.target.value))}
                      className="opacity-slider"
                    />
                  </div>
                </div>

                {/* Dynamic Legend Card */}
                <div className="hud-card legend-card">
                  <div className="hud-card-header">
                    <h3>Legend & Classification</h3>
                  </div>

                  {legendLoading ? (
                    <div className="legend-loading">Loading color ramp...</div>
                  ) : legend ? (
                    <div className="legend-content">
                      <p className="legend-layer-title">{legend.label}</p>
                      <div className="legend-meta-note">
                        <span className="meta-key">Status:</span> {legend.unit_status}
                      </div>

                      {/* Gradient Bar */}
                      <div
                        className="legend-gradient-bar"
                        style={{
                          background: `linear-gradient(to right, ${legend.color_ramp
                            .map((stop) => `${stop.color} ${stop.offset * 100}%`)
                            .join(', ')})`,
                        }}
                      />

                      {/* Discrete Class Items */}
                      <div className="legend-stops-list">
                        {legend.items.map((item, idx) => (
                          <div key={idx} className="legend-stop-item">
                            <span className="stop-color-chip" style={{ backgroundColor: item.color }} />
                            <span className="stop-label">{item.label}</span>
                          </div>
                        ))}
                      </div>

                      {/* Transparency note */}
                      <div className="transparency-note">
                        {selectedLayer === 'depth' && 'ℹ️ Zero depth cells (not exposed at sample) are rendered transparent.'}
                        {selectedLayer === 'velocity' && 'ℹ️ Zero velocity cells are rendered transparent.'}
                        {selectedLayer === 'arrival' && 'ℹ️ NoData arrival cells (+9999 / -9999) are rendered transparent.'}
                        {selectedLayer === 'dem' && 'ℹ️ NoData / outside domain cells are rendered transparent.'}
                      </div>
                    </div>
                  ) : (
                    <div className="legend-error">Legend data currently unavailable.</div>
                  )}
                </div>

                {/* Point Inspection Probe Card */}
                <div className="hud-card probe-card">
                  <div className="hud-card-header">
                    <h3>Point Query Probe</h3>
                    <span className="probe-hint">Click map to inspect</span>
                  </div>

                  {probe ? (
                    <div className="probe-content">
                      <div className="probe-coords">
                        <span>Lon: {probe.lon.toFixed(5)}°E</span>
                        <span>Lat: {probe.lat.toFixed(5)}°N</span>
                      </div>

                      {probe.loading ? (
                        <div className="probe-loading">
                          <span className="spinner"></span> Querying all 4 rasters...
                        </div>
                      ) : probe.error ? (
                        <div className="probe-error-msg">{probe.error}</div>
                      ) : (
                        <div className="probe-grid">
                          <div className="probe-item">
                            <div className="probe-item-header">
                              <span className="probe-item-icon">⛰️</span>
                              <span className="probe-item-label">DEM Elevation</span>
                            </div>
                            <div className="probe-item-val">
                              {probe.values.dem?.value != null
                                ? `${probe.values.dem.value.toFixed(2)} (unit unverified)`
                                : probe.values.dem?.is_nodata
                                ? 'NoData'
                                : 'N/A'}
                            </div>
                          </div>

                          <div className="probe-item">
                            <div className="probe-item-header">
                              <span className="probe-item-icon">🌊</span>
                              <span className="probe-item-label">Flood Depth</span>
                            </div>
                            <div className="probe-item-val highlight-depth">
                              {probe.values.depth?.value != null
                                ? probe.values.depth.value > 0
                                  ? `${probe.values.depth.value.toFixed(2)} (unit unverified)`
                                  : '0.00 (not exposed)'
                                : probe.values.depth?.is_nodata
                                ? 'NoData'
                                : 'N/A'}
                            </div>
                          </div>

                          <div className="probe-item">
                            <div className="probe-item-header">
                              <span className="probe-item-icon">⚡</span>
                              <span className="probe-item-label">Velocity</span>
                            </div>
                            <div className="probe-item-val highlight-velocity">
                              {probe.values.velocity?.value != null
                                ? probe.values.velocity.value > 0
                                  ? `${probe.values.velocity.value.toFixed(2)} (unit unverified)`
                                  : '0.00 (unit unverified)'
                                : probe.values.velocity?.is_nodata
                                ? 'NoData'
                                : 'N/A'}
                            </div>
                          </div>

                          <div className="probe-item">
                            <div className="probe-item-header">
                              <span className="probe-item-icon">⏱️</span>
                              <span className="probe-item-label">Arrival Time</span>
                            </div>
                            <div className="probe-item-val highlight-arrival">
                              {probe.values.arrival?.value != null
                                ? `${probe.values.arrival.value.toFixed(2)} (unit unverified)`
                                : probe.values.arrival?.is_nodata
                                ? 'Not assessed'
                                : 'N/A'}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="probe-placeholder">
                      <p>📍 Click anywhere on the map to probe raster values, or click on an asset/road for exposure screening details.</p>
                    </div>
                  )}
                </div>
              </>
            )}

            {/* TAB 2: Exposure Summary */}
            {activeTab === 'exposure' && (
              <div className="hud-card exposure-summary-card">
                <div className="hud-card-header">
                  <h3>Preliminary Exposure Screening Summary</h3>
                  <button className="btn-fit" onClick={fitToHidkal}>🎯 Fit Hidkal</button>
                </div>

                {summaryLoading ? (
                  <div className="probe-loading">
                    <span className="spinner"></span> Loading exposure screening summary...
                  </div>
                ) : exposureSummary ? (
                  <div className="exposure-summary-body">
                    {/* Preliminary Disclaimer Note */}
                    <div className="preliminary-disclaimer-box">
                      <span className="disclaimer-icon">⚠️</span>
                      <p className="disclaimer-text">
                        <strong>Preliminary exposure screening based on unverified sample rasters.</strong> Not a validated hydrodynamic risk assessment, damage calculation, or safety conclusion.
                      </p>
                    </div>

                    {/* KPI Stat Cards */}
                    <div className="kpi-grid">
                      <div className="kpi-card">
                        <span className="kpi-title">Screening-positive Assets</span>
                        <div className="kpi-value-row">
                          <span className="kpi-num text-danger">{exposureSummary.assets.exposed}</span>
                          <span className="kpi-total">/ {exposureSummary.assets.total}</span>
                        </div>
                        <span className="kpi-sub">
                          {((exposureSummary.assets.exposed / (exposureSummary.assets.total || 1)) * 100).toFixed(1)}% screened positive
                        </span>
                      </div>

                      <div className="kpi-card">
                        <span className="kpi-title">Screening-positive Road Segments</span>
                        <div className="kpi-value-row">
                          <span className="kpi-num text-danger">{exposureSummary.roads.exposed.toLocaleString()}</span>
                          <span className="kpi-total">/ {exposureSummary.roads.total.toLocaleString()}</span>
                        </div>
                        <span className="kpi-sub">
                          {((exposureSummary.roads.exposed / (exposureSummary.roads.total || 1)) * 100).toFixed(1)}% screened positive
                        </span>
                      </div>
                    </div>

                    {/* Asset Breakdown Table */}
                    <div className="breakdown-section">
                      <h4 className="breakdown-title">Asset Category Breakdown</h4>
                      <table className="breakdown-table">
                        <thead>
                          <tr>
                            <th>Category</th>
                            <th className="text-right">Total</th>
                            <th className="text-right">Screening-positive</th>
                            <th className="text-right">Not exposed at sample</th>
                            <th className="text-right">Not assessed</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(exposureSummary.assets.by_category).map(([cat, c]) => (
                            <tr key={cat}>
                              <td className="cat-name-cell">
                                <span className="cat-dot" />
                                <span>{cat.charAt(0).toUpperCase() + cat.slice(1)}</span>
                              </td>
                              <td className="text-right font-mono">{c.total}</td>
                              <td className={`text-right font-mono ${c.exposed > 0 ? 'text-danger font-bold' : ''}`}>{c.exposed}</td>
                              <td className="text-right font-mono text-muted">{c.not_exposed}</td>
                              <td className="text-right font-mono text-muted">{c.not_assessed}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    {/* Road Network Breakdown Table */}
                    <div className="breakdown-section">
                      <h4 className="breakdown-title">Road Network Breakdown</h4>
                      <table className="breakdown-table">
                        <thead>
                          <tr>
                            <th>Highway Type</th>
                            <th className="text-right">Segments</th>
                            <th className="text-right">Screening-positive</th>
                            <th className="text-right">Not exposed at sample</th>
                            <th className="text-right">Not assessed</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(exposureSummary.roads.by_category)
                            .sort((a, b) => b[1].total - a[1].total)
                            .map(([cat, c]) => (
                              <tr key={cat}>
                                <td className="cat-name-cell">
                                  <span className="cat-dot dot-road" />
                                  <span>{cat.charAt(0).toUpperCase() + cat.slice(1)}</span>
                                </td>
                                <td className="text-right font-mono">{c.total.toLocaleString()}</td>
                                <td className={`text-right font-mono ${c.exposed > 0 ? 'text-danger font-bold' : ''}`}>{c.exposed.toLocaleString()}</td>
                                <td className="text-right font-mono text-muted">{c.not_exposed.toLocaleString()}</td>
                                <td className="text-right font-mono text-muted">{c.not_assessed.toLocaleString()}</td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : (
                  <div className="legend-error">Exposure summary unavailable.</div>
                )}
              </div>
            )}

            {/* TAB 3: Damage Scenario Estimation */}
            {activeTab === 'damage' && (
              <div className="hud-card damage-card">
                <div className="hud-card-header">
                  <h3>Illustrative Damage Scenario</h3>
                  <button className="btn-fit" onClick={handleResetDamageDefaults} title="Reset to default assumptions">
                    ↺ Reset
                  </button>
                </div>

                <div className="damage-body">
                  {/* Prominent Mandatory Disclaimer Banner */}
                  <div className="damage-disclaimer-banner">
                    <span className="disclaimer-icon">⚠️</span>
                    <p className="disclaimer-text">
                      <strong>Illustrative scenario only — not an official loss estimate or emergency decision.</strong>
                      <br />
                      Calculations use unverified sample depths and user-configured replacement assumptions. Road network and casualties are excluded.
                    </p>
                  </div>

                  {/* User Acknowledgement Box */}
                  <div className="acknowledgement-box">
                    <label className="ack-label">
                      <input
                        type="checkbox"
                        checked={acknowledgeAssumptions}
                        onChange={(e) => setAcknowledgeAssumptions(e.target.checked)}
                        className="ack-checkbox"
                      />
                      <span className="ack-text">
                        I acknowledge that the rasters, units, replacement values, and damage curves are <strong>unverified illustrative assumptions</strong>. I agree these results cannot be used as official risk predictions.
                      </span>
                    </label>
                  </div>

                  {/* Editable Configuration Controls */}
                  <div className="damage-config-section">
                    <h4 className="config-section-title">⚙️ Scenario Parameters</h4>

                    <div className="config-row-grid">
                      <div className="config-field">
                        <label>Currency Label</label>
                        <input
                          type="text"
                          value={currencyLabel}
                          onChange={(e) => setCurrencyLabel(e.target.value)}
                          className="config-input"
                        />
                      </div>
                      <div className="config-field">
                        <label>Assumed Depth Unit</label>
                        <input
                          type="text"
                          value={assumedDepthUnit}
                          onChange={(e) => setAssumedDepthUnit(e.target.value)}
                          className="config-input"
                        />
                      </div>
                      <div className="config-field config-field-full">
                        <label>Sensitivity (±%)</label>
                        <input
                          type="number"
                          min="0"
                          max="100"
                          step="5"
                          value={sensitivityPercent}
                          onChange={(e) => setSensitivityPercent(Math.max(0, Math.min(100, parseFloat(e.target.value) || 0)))}
                          className="config-input font-mono"
                        />
                      </div>
                    </div>

                    {/* Replacement Values per Category */}
                    <div className="config-sub-section">
                      <h5 className="sub-title">Unit Replacement Value per Asset</h5>
                      <div className="replacement-grid">
                        {Object.entries(replacementValues).map(([cat, val]) => (
                          <div key={cat} className="replacement-item">
                            <span className="rep-cat-name">{cat.charAt(0).toUpperCase() + cat.slice(1)}</span>
                            <div className="rep-input-wrap">
                              <span className="rep-currency-prefix">{currencyLabel.split(' ')[0]}</span>
                              <input
                                type="number"
                                min="0"
                                step="100000"
                                value={val}
                                onChange={(e) => {
                                  const num = Math.max(0, parseFloat(e.target.value) || 0)
                                  setReplacementValues({ ...replacementValues, [cat]: num })
                                }}
                                className="config-input font-mono rep-input"
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Piecewise Depth-Damage Curve Table */}
                    <div className="config-sub-section">
                      <div className="curve-header-row">
                        <h5 className="sub-title">Depth–Damage Curve (Piecewise Monotonic)</h5>
                        <button className="btn-add-pt" onClick={handleAddCurvePoint}>+ Add Point</button>
                      </div>
                      <table className="curve-table">
                        <thead>
                          <tr>
                            <th>Depth ({assumedDepthUnit.split(' ')[0]})</th>
                            <th>Damage Ratio (0.0 - 1.0)</th>
                            <th className="text-right">Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {depthCurve.map((pt, idx) => (
                            <tr key={idx}>
                              <td>
                                <input
                                  type="number"
                                  min="0"
                                  step="0.5"
                                  value={pt.depth}
                                  onChange={(e) => handleCurveChange(idx, 'depth', parseFloat(e.target.value) || 0)}
                                  className="curve-input font-mono"
                                />
                              </td>
                              <td>
                                <input
                                  type="number"
                                  min="0"
                                  max="1"
                                  step="0.05"
                                  value={pt.damage_ratio}
                                  onChange={(e) => handleCurveChange(idx, 'damage_ratio', Math.max(0, Math.min(1, parseFloat(e.target.value) || 0)))}
                                  className="curve-input font-mono"
                                />
                              </td>
                              <td className="text-right">
                                {depthCurve.length > 2 && (
                                  <button className="btn-remove-pt" onClick={() => handleRemoveCurvePoint(idx)}>✕</button>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    {/* Calculate Button */}
                    <div className="calculate-action-row">
                      <button
                        className={`btn-calculate ${!acknowledgeAssumptions ? 'disabled' : ''}`}
                        disabled={!acknowledgeAssumptions || damageLoading}
                        onClick={handleCalculateDamage}
                      >
                        {damageLoading ? (
                          <>
                            <span className="spinner"></span> Calculating Scenario...
                          </>
                        ) : (
                          '⚡ Calculate Illustrative Loss'
                        )}
                      </button>
                      {!acknowledgeAssumptions && (
                        <span className="ack-required-hint">⚠️ Check acknowledgement above to enable calculation.</span>
                      )}
                    </div>

                    {damageError && <div className="damage-error-box">{damageError}</div>}
                  </div>

                  {/* Results Section */}
                  {damageResult && (
                    <div className="damage-results-section">
                      <h4 className="results-title">📊 Scenario Estimation Results</h4>

                      {/* Low / Base / High KPI Grid */}
                      <div className="damage-kpi-grid">
                        <div className="damage-kpi-card kpi-low">
                          <span className="damage-kpi-label">Low Estimate (-{damageResult.sensitivity_percentage}%)</span>
                          <span className="damage-kpi-val font-mono">{currencyLabel.split(' ')[0]} {formatCurrency(damageResult.total_estimates.low_loss)}</span>
                        </div>

                        <div className="damage-kpi-card kpi-base">
                          <span className="damage-kpi-label">Base Scenario Estimate</span>
                          <span className="damage-kpi-val font-mono text-danger">{currencyLabel.split(' ')[0]} {formatCurrency(damageResult.total_estimates.base_loss)}</span>
                          <span className="damage-kpi-sub">from {damageResult.asset_counts.screening_positive_assets} positive assets</span>
                        </div>

                        <div className="damage-kpi-card kpi-high">
                          <span className="damage-kpi-label">High Estimate (+{damageResult.sensitivity_percentage}%)</span>
                          <span className="damage-kpi-val font-mono">{currencyLabel.split(' ')[0]} {formatCurrency(damageResult.total_estimates.high_loss)}</span>
                        </div>
                      </div>

                      {/* Category Breakdown Table */}
                      <div className="breakdown-section">
                        <h5 className="sub-title">Category Loss Breakdown</h5>
                        <table className="breakdown-table damage-table">
                          <thead>
                            <tr>
                              <th>Category</th>
                              <th className="text-right">Positive</th>
                              <th className="text-right">Unit Value</th>
                              <th className="text-right">Base Loss</th>
                              <th className="text-right">Range (±{damageResult.sensitivity_percentage}%)</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(damageResult.by_category).map(([cat, res]) => (
                              <tr key={cat}>
                                <td className="cat-name-cell">
                                  <span className="cat-dot" />
                                  <span>{cat.charAt(0).toUpperCase() + cat.slice(1)}</span>
                                </td>
                                <td className="text-right font-mono">{res.screening_positive_count} / {res.total_count}</td>
                                <td className="text-right font-mono text-muted">{formatCurrency(res.unit_replacement_value)}</td>
                                <td className={`text-right font-mono ${res.base_loss > 0 ? 'text-danger font-bold' : ''}`}>
                                  {formatCurrency(res.base_loss)}
                                </td>
                                <td className="text-right font-mono text-dim">
                                  {formatCurrency(res.low_loss)} – {formatCurrency(res.high_loss)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>

                      {/* Methodology and Warnings */}
                      <div className="damage-notes-card">
                        <span className="note-title">ℹ️ Assumptions & Scope</span>
                        <p className="note-text">{damageResult.methodology}</p>
                        <ul className="warnings-list">
                          {damageResult.warnings.map((w, i) => (
                            <li key={i}>{w}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* TAB 4: Route Screening (Phase 8) */}
            {activeTab === 'route' && (
              <div className="hud-card route-card">
                <div className="hud-card-header">
                  <h3>Road Network Route Screening</h3>
                  <button className="btn-fit" onClick={handleClearRoute} title="Clear calculated route">
                    ✕ Clear
                  </button>
                </div>

                <div className="route-body">
                  {/* Prominent Mandatory Disclaimer Banner */}
                  <div className="route-disclaimer-banner">
                    <span className="disclaimer-icon">⚠️</span>
                    <p className="disclaimer-text">
                      <strong>Preliminary screening route only.</strong> Road closures, structural bridge integrity, carrying capacity, and live traffic are not validated. Not an official emergency evacuation route.
                    </p>
                  </div>

                  {/* Waypoint Coordinates Card */}
                  <div className="route-waypoints-section">
                    <h4 className="config-section-title">📍 Origin & Destination Points</h4>

                    {/* Start Waypoint */}
                    <div className="waypoint-box waypoint-start">
                      <div className="waypoint-header">
                        <span className="waypoint-badge badge-start">📍 Start Point</span>
                        <button
                          className={`btn-pick-map ${routePickMode === 'start' ? 'active-pick' : ''}`}
                          onClick={() => setRoutePickMode(routePickMode === 'start' ? null : 'start')}
                        >
                          {routePickMode === 'start' ? '🎯 Click Map...' : '📍 Set on Map'}
                        </button>
                      </div>
                      <div className="coord-inputs-grid">
                        <div className="coord-field">
                          <label>Longitude (°E)</label>
                          <input
                            type="number"
                            step="0.0001"
                            value={startLon}
                            onChange={(e) => setStartLon(parseFloat(e.target.value) || 0)}
                            className="config-input font-mono"
                          />
                        </div>
                        <div className="coord-field">
                          <label>Latitude (°N)</label>
                          <input
                            type="number"
                            step="0.0001"
                            value={startLat}
                            onChange={(e) => setStartLat(parseFloat(e.target.value) || 0)}
                            className="config-input font-mono"
                          />
                        </div>
                      </div>
                    </div>

                    {/* Destination Waypoint */}
                    <div className="waypoint-box waypoint-dest">
                      <div className="waypoint-header">
                        <span className="waypoint-badge badge-dest">🎯 Destination Point</span>
                        <button
                          className={`btn-pick-map ${routePickMode === 'dest' ? 'active-pick' : ''}`}
                          onClick={() => setRoutePickMode(routePickMode === 'dest' ? null : 'dest')}
                        >
                          {routePickMode === 'dest' ? '🎯 Click Map...' : '📍 Set on Map'}
                        </button>
                      </div>
                      <div className="coord-inputs-grid">
                        <div className="coord-field">
                          <label>Longitude (°E)</label>
                          <input
                            type="number"
                            step="0.0001"
                            value={endLon}
                            onChange={(e) => setEndLon(parseFloat(e.target.value) || 0)}
                            className="config-input font-mono"
                          />
                        </div>
                        <div className="coord-field">
                          <label>Latitude (°N)</label>
                          <input
                            type="number"
                            step="0.0001"
                            value={endLat}
                            onChange={(e) => setEndLat(parseFloat(e.target.value) || 0)}
                            className="config-input font-mono"
                          />
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Routing Options */}
                  <div className="route-options-section">
                    <label className="toggle-checkbox-row route-option-checkbox">
                      <input
                        type="checkbox"
                        checked={avoidScreeningPositive}
                        onChange={(e) => setAvoidScreeningPositive(e.target.checked)}
                      />
                      <div className="toggle-label-content">
                        <span className="toggle-title">🚫 Avoid screening-positive (depth &gt; 0 at sample) roads</span>
                        <span className="toggle-desc">Excludes road edges with depth &gt; 0 in sample raster</span>
                      </div>
                    </label>

                    <div className="config-field">
                      <label>Max Snap Distance to Road Network (meters)</label>
                      <input
                        type="number"
                        min="100"
                        max="20000"
                        step="500"
                        value={maxSnapDistance}
                        onChange={(e) => setMaxSnapDistance(Math.max(100, parseFloat(e.target.value) || 5000))}
                        className="config-input font-mono"
                      />
                    </div>
                  </div>

                  {/* Calculate Action Button */}
                  <div className="calculate-action-row">
                    <button
                      className="btn-calculate"
                      disabled={routeLoading}
                      onClick={handleCalculateRoute}
                    >
                      {routeLoading ? (
                        <>
                          <span className="spinner"></span> Computing Screening Route...
                        </>
                      ) : (
                        '🛣️ Screen Shortest Traversable Route'
                      )}
                    </button>
                  </div>

                  {routeError && <div className="damage-error-box">{routeError}</div>}

                  {/* Route Screening Results Summary */}
                  {routeResult && (
                    <div className="route-results-section">
                      <div className="hud-card-header">
                        <h4 className="results-title">
                          {routeResult.route_found ? '✅ Route Screened Successfully' : '⚠️ No Traversable Route Found'}
                        </h4>
                        <span className={`status-badge ${routeResult.route_found ? 'status-ok' : 'status-fail'}`}>
                          {routeResult.route_found ? 'Traversable' : 'Blocked'}
                        </span>
                      </div>

                      {routeResult.route_found ? (
                        <>
                          {/* Route KPI Stat Cards */}
                          <div className="route-kpi-grid">
                            <div className="route-kpi-card">
                              <span className="kpi-title">Total Distance</span>
                              <div className="kpi-value-row">
                                <span className="kpi-num text-cyan">{routeResult.total_distance_km}</span>
                                <span className="kpi-total">km</span>
                              </div>
                              <span className="kpi-sub">
                                ({routeResult.total_distance_meters?.toLocaleString()} m)
                              </span>
                            </div>

                            <div className="route-kpi-card">
                              <span className="kpi-title">Road Segments</span>
                              <div className="kpi-value-row">
                                <span className="kpi-num">{routeResult.segment_count}</span>
                                <span className="kpi-total">edges</span>
                              </div>
                              <span className="kpi-sub">
                                {routeResult.excluded_edges_count} screening-positive (depth &gt; 0 at sample) excluded
                              </span>
                            </div>
                          </div>

                          {/* Node Snapping Breakdown */}
                          <div className="breakdown-section">
                            <h5 className="sub-title">Node Snapping Diagnostics</h5>
                            <div className="snap-diagnostics-box">
                              <div className="snap-row">
                                <span className="snap-label">Start Point Snap:</span>
                                <span className="snap-val font-mono">{routeResult.start_snap_distance_meters} m</span>
                              </div>
                              <div className="snap-row">
                                <span className="snap-label">Destination Snap:</span>
                                <span className="snap-val font-mono">{routeResult.end_snap_distance_meters} m</span>
                              </div>
                              <div className="snap-row">
                                <span className="snap-label">Excluded Edges (depth &gt; 0 at sample):</span>
                                <span className="snap-val font-mono text-danger">{routeResult.excluded_edges_count} segments</span>
                              </div>
                            </div>
                          </div>
                        </>
                      ) : (
                        <div className="route-not-found-box">
                          <p>
                            No clear road path could connect the snapped start and destination nodes without traversing screening-positive (depth &gt; 0 at sample) road segments. Try unchecking <em>"Avoid screening-positive roads"</em> to inspect shortest geometric connection.
                          </p>
                        </div>
                      )}

                      {/* Warnings and Methodology */}
                      {routeResult.warnings && routeResult.warnings.length > 0 && (
                        <div className="damage-notes-card">
                          <span className="note-title">⚠️ Route Warnings & Notes</span>
                          <ul className="warnings-list">
                            {routeResult.warnings.map((w, idx) => (
                              <li key={idx}>{w}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* TAB 5: Geospatial Exports (Phase 9) */}
            {activeTab === 'export' && (
              <div className="hud-card export-card">
                <div className="hud-card-header">
                  <h3>Geospatial Data Exports</h3>
                  <span className="legend-tag">MULTI-FORMAT</span>
                </div>

                <div className="export-body">
                  {/* Export Layer Selector */}
                  <div className="export-section">
                    <label className="export-field-label">1. Select Target Layer</label>
                    <div className="export-options-grid">
                      <button
                        className={`export-select-btn ${exportLayer === 'assets' ? 'active' : ''}`}
                        onClick={() => setExportLayer('assets')}
                      >
                        <span className="export-btn-icon">🏛️</span>
                        <div className="export-btn-text">
                          <span className="export-btn-title">Infrastructure Assets</span>
                          <span className="export-btn-sub">Buildings, Hospitals, Settlements (513)</span>
                        </div>
                      </button>

                      <button
                        className={`export-select-btn ${exportLayer === 'roads' ? 'active' : ''}`}
                        onClick={() => setExportLayer('roads')}
                      >
                        <span className="export-btn-icon">🛣️</span>
                        <div className="export-btn-text">
                          <span className="export-btn-title">Road Network Graph</span>
                          <span className="export-btn-sub">8,047 road network segments</span>
                        </div>
                      </button>

                      <button
                        className={`export-select-btn ${exportLayer === 'route' ? 'active' : ''}`}
                        onClick={() => setExportLayer('route')}
                      >
                        <span className="export-btn-icon">🚗</span>
                        <div className="export-btn-text">
                          <span className="export-btn-title">Screened Route</span>
                          <span className="export-btn-sub">
                            {routeResult?.route_found ? `${routeResult.total_distance_km} km calculated route` : 'Requires calculated route'}
                          </span>
                        </div>
                      </button>
                    </div>
                  </div>

                  {/* Route Status Callout if Route Layer Selected */}
                  {exportLayer === 'route' && (!routeResult || !routeResult.route_found) && (
                    <div className="export-route-warning">
                      <span>⚠️ No calculated route found. Please calculate a route in the <strong>Route</strong> tab before exporting.</span>
                    </div>
                  )}

                  {/* Exposure Status Filter (only for assets and roads) */}
                  {exportLayer !== 'route' && (
                    <div className="export-section">
                      <label className="export-field-label">2. Exposure Status Filter</label>
                      <div className="filter-options-grid">
                        {[
                          { id: 'all', label: 'All Features', desc: 'Complete dataset' },
                          { id: 'screening_positive', label: 'Screening-positive Only', desc: 'Depth > 0 in sample raster' },
                          { id: 'not_exposed', label: 'Not Exposed at Sample Only', desc: 'Assessed with zero depth' },
                          { id: 'not_assessed', label: 'Not Assessed Only', desc: 'Outside domain extent' },
                        ].map((item) => (
                          <button
                            key={item.id}
                            className={`filter-select-btn ${exportFilter === item.id ? 'active' : ''}`}
                            onClick={() => setExportFilter(item.id as any)}
                          >
                            <span className="filter-btn-title">{item.label}</span>
                            <span className="filter-btn-sub">{item.desc}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Format Selector */}
                  <div className="export-section">
                    <label className="export-field-label">
                      {exportLayer === 'route' ? '2. Select Export Format' : '3. Select Export Format'}
                    </label>
                    <div className="format-options-grid">
                      <button
                        className={`format-select-btn ${exportFormat === 'geojson' ? 'active' : ''}`}
                        onClick={() => setExportFormat('geojson')}
                      >
                        <span className="format-title">GeoJSON</span>
                        <span className="format-ext">.geojson</span>
                        <span className="format-desc">Standard web GIS GeoJSON FeatureCollection</span>
                      </button>

                      <button
                        className={`format-select-btn ${exportFormat === 'kml' ? 'active' : ''}`}
                        onClick={() => setExportFormat('kml')}
                      >
                        <span className="format-title">Google Earth KML</span>
                        <span className="format-ext">.kml</span>
                        <span className="format-desc">Styled placemarks with attribute metadata</span>
                      </button>

                      <button
                        className={`format-select-btn ${exportFormat === 'shp' ? 'active' : ''}`}
                        onClick={() => setExportFormat('shp')}
                      >
                        <span className="format-title">ESRI Shapefile ZIP</span>
                        <span className="format-ext">.zip</span>
                        <span className="format-desc">Multi-geometry partition + README_METADATA.txt</span>
                      </button>
                    </div>
                  </div>

                  {/* Download Trigger Button */}
                  <div className="calculate-action-row">
                    <button
                      className={`btn-calculate ${(exportLayer === 'route' && (!routeResult || !routeResult.route_found)) ? 'disabled' : ''}`}
                      disabled={exportLoading || (exportLayer === 'route' && (!routeResult || !routeResult.route_found))}
                      onClick={handleDownloadExport}
                    >
                      {exportLoading ? (
                        <>
                          <span className="spinner"></span> Generating Package...
                        </>
                      ) : (
                        `💾 Download ${exportLayer.toUpperCase()} (${exportFormat.toUpperCase()})`
                      )}
                    </button>
                  </div>

                  {exportSuccessMsg && <div className="export-success-box">✅ {exportSuccessMsg}</div>}
                  {exportError && <div className="damage-error-box">{exportError}</div>}

                  {/* Package Metadata Summary */}
                  <div className="export-info-card">
                    <span className="note-title">ℹ️ Export Specifications</span>
                    <ul className="export-specs-list">
                      <li><strong>CRS:</strong> WGS84 Longitude/Latitude (<code>EPSG:4326</code>)</li>
                      <li><strong>Shapefile Bundles:</strong> Zipped archive includes complete <code>.shp</code>, <code>.shx</code>, <code>.dbf</code>, <code>.prj</code>, <code>.cpg</code> sets.</li>
                      <li><strong>Mixed Geometries:</strong> Automatically split into separated <code>_points.shp</code>, <code>_lines.shp</code>, and <code>_polygons.shp</code>.</li>
                      <li><strong>Audit Metadata:</strong> Every ZIP package includes a <code>README_METADATA.txt</code> containing column mappings and scientific screening disclaimers.</li>
                    </ul>
                  </div>
                </div>
              </div>
            )}

            {/* TAB 6: Scenario Management & Honest Delft3D FM Integration */}
            {activeTab === 'scenarios' && (
              <div className="hud-content">
                <div className="hud-card">
                  {/* Capabilities & Scientific Boundary Card */}
                  <div className="hud-card-header">
                    <h3 className="card-title">🌊 Hydrodynamic Scenario & Delft3D Boundary</h3>
                  </div>

                  <div className="capabilities-grid">
                    <div className={`capability-card ${capabilities?.hydromt_available ? 'cap-available' : 'cap-missing'}`}>
                      <div className="cap-header">
                        <span className="cap-icon">⚙️</span>
                        <span className="cap-title">HydroMT Builder</span>
                      </div>
                      <span className="cap-badge">
                        {capabilities?.hydromt_available
                          ? `Installed (${capabilities.hydromt_version || 'Ready'})`
                          : 'Not Installed (Template Mode)'}
                      </span>
                      <p className="cap-desc">Builds & formats 2D mesh, topography, and boundary config templates.</p>
                    </div>

                    <div className={`capability-card ${capabilities?.execution_enabled && capabilities?.dflowfm_available ? 'cap-available' : 'cap-disabled'}`}>
                      <div className="cap-header">
                        <span className="cap-icon">🚀</span>
                        <span className="cap-title">D-Flow FM Engine</span>
                      </div>
                      <span className="cap-badge">
                        {capabilities?.execution_enabled && capabilities?.dflowfm_available
                          ? 'Engine Ready'
                          : 'Execution Disabled / Unavailable'}
                      </span>
                      <p className="cap-desc">Numerical SWE solver. Execution is strictly gated behind server configuration.</p>
                    </div>
                  </div>

                  {/* Setup & Boundary Guidance Accordion */}
                  <div className="guide-accordion-box">
                    <button
                      className="btn-toggle-guide"
                      onClick={() => setShowSetupGuide(!showSetupGuide)}
                    >
                      {showSetupGuide ? '▾ Hide Delft3D & HydroMT Setup Instructions' : '▸ Show Delft3D & HydroMT Setup Instructions'}
                    </button>
                    {showSetupGuide && (
                      <div className="guide-content font-mono">
                        <p><strong>1. Isolated HydroMT Conda Environment:</strong></p>
                        <pre className="code-snippet">
conda env create -f environment_hydromt_delft3dfm.yml{'\n'}
conda activate hydromt-delft3dfm
                        </pre>
                        <p><strong>2. Server Simulation Gating (Disabled by Default):</strong></p>
                        <pre className="code-snippet">
ENABLE_DFLOWFM_EXECUTION=true{'\n'}
DFLOWFM_EXECUTABLE=C:\Deltares\dflowfm\bin\dflowfm.exe
                        </pre>
                        <p><strong>3. Scientific Transparency:</strong></p>
                        <p className="guide-note">
                          Existing sample rasters (depth, velocity, arrival) in this workspace are unverified and of unknown provenance. They are NEVER attributed to Delft3D outputs or attached to simulation runs.
                        </p>
                      </div>
                    )}
                  </div>

                  {/* Scenario Error or Success Banners */}
                  {scenarioError && <div className="damage-error-box">{scenarioError}</div>}
                  {packageSuccessMsg && <div className="export-success-box">📦 {packageSuccessMsg}</div>}
                  {runError && <div className="damage-error-box">{runError}</div>}

                  {/* Scenarios Header & Create Action */}
                  <div className="scenarios-action-bar">
                    <div className="scenarios-title-row">
                      <h4 className="sub-title">Scenarios ({scenarios.length})</h4>
                      <label className="toggle-archived-label">
                        <input
                          type="checkbox"
                          checked={includeArchived}
                          onChange={(e) => setIncludeArchived(e.target.checked)}
                        />
                        <span>Show Archived</span>
                      </label>
                    </div>
                    {!isCreatingScenario && !isEditingScenario && (
                      <button className="btn-secondary-action" onClick={handleStartCreateScenario}>
                        ➕ New Scenario
                      </button>
                    )}
                  </div>

                  {/* Scenario Creator / Editor Form */}
                  {(isCreatingScenario || isEditingScenario) && (
                    <div className="scenario-form-card">
                      <h4 className="results-title">
                        {isCreatingScenario ? '➕ Create Hydrodynamic Scenario' : '✏️ Edit Scenario Parameters'}
                      </h4>

                      <div className="form-group">
                        <label>Scenario Title</label>
                        <input
                          type="text"
                          value={scenarioForm.name}
                          onChange={(e) => setScenarioForm({ ...scenarioForm, name: e.target.value })}
                          className="config-input"
                          placeholder="e.g. Hidkal Sunny Day Breach - High Sensitivity"
                        />
                      </div>

                      <div className="form-group">
                        <label>Description & Notes</label>
                        <textarea
                          value={scenarioForm.description}
                          onChange={(e) => setScenarioForm({ ...scenarioForm, description: e.target.value })}
                          className="config-input font-sans textarea-field"
                          placeholder="Operational notes, modeling intent, and boundary assumptions..."
                          rows={2}
                        />
                      </div>

                      <div className="scenario-params-grid">
                        <div className="config-field">
                          <label>Breach Width (m)</label>
                          <input
                            type="number"
                            min="5"
                            max="3000"
                            step="10"
                            value={scenarioForm.breach_width_m}
                            onChange={(e) => setScenarioForm({ ...scenarioForm, breach_width_m: parseFloat(e.target.value) || 100 })}
                            className="config-input font-mono"
                          />
                          <span className="field-unit-tag">Assumed meters (unverified)</span>
                        </div>

                        <div className="config-field">
                          <label>Breach Time (hours)</label>
                          <input
                            type="number"
                            min="0.1"
                            max="72"
                            step="0.5"
                            value={scenarioForm.breach_formation_time_hr}
                            onChange={(e) => setScenarioForm({ ...scenarioForm, breach_formation_time_hr: parseFloat(e.target.value) || 2 })}
                            className="config-input font-mono"
                          />
                          <span className="field-unit-tag">Formation duration</span>
                        </div>

                        <div className="config-field">
                          <label>Reservoir Level (m)</label>
                          <input
                            type="number"
                            min="100"
                            max="2000"
                            step="1"
                            value={scenarioForm.assumed_reservoir_level_m}
                            onChange={(e) => setScenarioForm({ ...scenarioForm, assumed_reservoir_level_m: parseFloat(e.target.value) || 660 })}
                            className="config-input font-mono"
                          />
                          <span className="field-unit-tag">Vertical datum unverified</span>
                        </div>

                        <div className="config-field">
                          <label>Manning Roughness n</label>
                          <input
                            type="number"
                            min="0.01"
                            max="0.2"
                            step="0.005"
                            value={scenarioForm.manning_roughness}
                            onChange={(e) => setScenarioForm({ ...scenarioForm, manning_roughness: parseFloat(e.target.value) || 0.035 })}
                            className="config-input font-mono"
                          />
                          <span className="field-unit-tag">Uniform s/m^(1/3)</span>
                        </div>

                        <div className="config-field">
                          <label>Flexible Mesh Target (m)</label>
                          <input
                            type="number"
                            min="10"
                            max="500"
                            step="10"
                            value={scenarioForm.mesh_resolution_m}
                            onChange={(e) => setScenarioForm({ ...scenarioForm, mesh_resolution_m: parseFloat(e.target.value) || 50 })}
                            className="config-input font-mono"
                          />
                          <span className="field-unit-tag">Target grid cell size</span>
                        </div>

                        <div className="config-field">
                          <label>Simulation Duration (hr)</label>
                          <input
                            type="number"
                            min="1"
                            max="168"
                            step="6"
                            value={scenarioForm.simulation_duration_hr}
                            onChange={(e) => setScenarioForm({ ...scenarioForm, simulation_duration_hr: parseFloat(e.target.value) || 24 })}
                            className="config-input font-mono"
                          />
                          <span className="field-unit-tag">Total run window</span>
                        </div>
                      </div>

                      <div className="form-action-row">
                        <button className="btn-calculate" onClick={handleSaveScenario}>
                          💾 {isCreatingScenario ? 'Save Scenario' : 'Update Scenario'}
                        </button>
                        <button
                          className="btn-secondary-action"
                          onClick={() => {
                            setIsCreatingScenario(false)
                            setIsEditingScenario(false)
                          }}
                        >
                          ✕ Cancel
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Scenarios List */}
                  {scenariosLoading ? (
                    <div className="loading-box"><span className="spinner"></span> Loading scenarios...</div>
                  ) : scenarios.length === 0 ? (
                    <div className="empty-state-box">
                      <p>No scenarios found. Click <strong>➕ New Scenario</strong> to create your first dam breach modeling scenario.</p>
                    </div>
                  ) : (
                    <div className="scenarios-list">
                      {scenarios.map((sc) => {
                        const isSelected = selectedScenarioId === sc.id
                        return (
                          <div
                            key={sc.id}
                            className={`scenario-card ${isSelected ? 'selected' : ''} ${sc.archived ? 'archived' : ''}`}
                            onClick={() => setSelectedScenarioId(sc.id)}
                          >
                            <div className="scenario-card-header">
                              <div>
                                <h5 className="scenario-title">{sc.name}</h5>
                                <span className="scenario-id-text font-mono">ID: {sc.id.slice(0, 8)}... (Rev {sc.revision})</span>
                              </div>
                              <div className="scenario-badges">
                                <span className={`status-badge status-${sc.status === 'package_built' ? 'ok' : 'pending'}`}>
                                  {sc.status.replace(/_/g, ' ')}
                                </span>
                                {sc.archived && <span className="badge-archived">Archived</span>}
                              </div>
                            </div>

                            {sc.description && <p className="scenario-desc">{sc.description}</p>}

                            {/* Quick Metrics */}
                            <div className="scenario-quick-metrics">
                              <span>📐 Breach: {sc.breach_width_m} m</span>
                              <span>⏱️ Formation: {sc.breach_formation_time_hr} h</span>
                              <span>🌊 Stage: {sc.assumed_reservoir_level_m} m</span>
                              <span>⚡ Manning: {sc.manning_roughness}</span>
                              <span>🕸️ Mesh: {sc.mesh_resolution_m} m</span>
                            </div>

                            {/* Snapshot Checksum */}
                            {sc.snapshot_checksum && (
                              <div className="checksum-row font-mono">
                                <span>SHA-256: {sc.snapshot_checksum.slice(0, 16)}...</span>
                              </div>
                            )}

                            {/* Action Buttons */}
                            <div className="scenario-actions" onClick={(e) => e.stopPropagation()}>
                              <button
                                className="btn-card-action"
                                onClick={() => handleStartEditScenario(sc)}
                                title="Edit scenario parameters"
                              >
                                ✏️ Edit
                              </button>
                              <button
                                className="btn-card-action"
                                onClick={() => handleCloneScenario(sc.id)}
                                title="Clone scenario copy"
                              >
                                📋 Clone
                              </button>
                              <button
                                className="btn-card-action"
                                onClick={() => handleBuildPackage(sc.id)}
                                disabled={packageBuilding}
                                title="Build Delft3D FM configuration package"
                              >
                                📦 Build Package
                              </button>
                              <button
                                className="btn-card-action"
                                onClick={() => handleDownloadPackage(sc.id)}
                                title="Download draft package ZIP"
                              >
                                ⬇️ Download ZIP
                              </button>
                              <button
                                className="btn-card-action"
                                onClick={() => handleArchiveScenario(sc.id, !sc.archived)}
                                title={sc.archived ? 'Restore scenario' : 'Archive scenario'}
                              >
                                {sc.archived ? '📂 Unarchive' : '📁 Archive'}
                              </button>
                              <button
                                className={`btn-card-action btn-run-action ${(!capabilities?.execution_enabled || !capabilities?.dflowfm_available) ? 'disabled' : ''}`}
                                disabled={!capabilities?.execution_enabled || !capabilities?.dflowfm_available || runExecuting}
                                onClick={() => handleRunSimulation(sc.id)}
                                title={
                                  capabilities?.execution_enabled && capabilities?.dflowfm_available
                                    ? 'Execute D-Flow FM simulation'
                                    : 'D-Flow FM solver execution is disabled or binary missing on server'
                                }
                              >
                                {runExecuting ? '⏳ Running...' : '🚀 Run D-Flow FM'}
                              </button>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}

                  {/* Selected Scenario Scientific Validation Notes */}
                  {selectedScenario && (
                    <div className="scenario-validation-card">
                      <div className="hud-card-header">
                        <h4 className="results-title">🔬 Scientific Validation & Input Review</h4>
                        <span className="status-badge status-warn">Review Required</span>
                      </div>
                      <p className="validation-intro">
                        Schema validation has passed, but the following critical scientific inputs are required before running a certified hydrodynamic simulation:
                      </p>
                      <ul className="validation-notes-list">
                        {selectedScenario.validation_notes.map((note, idx) => (
                          <li key={idx}>⚠️ {note}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Historical Simulation Runs */}
                  <div className="runs-history-card">
                    <div className="hud-card-header">
                      <h4 className="results-title">📋 Simulation Execution History</h4>
                      <button className="btn-text-action" onClick={fetchRuns}>🔄 Refresh</button>
                    </div>

                    {runsLoading ? (
                      <div className="loading-box"><span className="spinner"></span> Loading runs...</div>
                    ) : runs.length === 0 ? (
                      <p className="no-runs-text">No simulation runs executed yet. Gated execution is enforced.</p>
                    ) : (
                      <div className="runs-table-wrapper">
                        <table className="breakdown-table runs-table">
                          <thead>
                            <tr>
                              <th>Run ID</th>
                              <th>Scenario</th>
                              <th>Status</th>
                              <th>Started At</th>
                              <th>Duration</th>
                              <th className="text-right">Logs</th>
                            </tr>
                          </thead>
                          <tbody>
                            {runs.map((r) => (
                              <tr key={r.run_id}>
                                <td className="font-mono">{r.run_id.slice(0, 8)}...</td>
                                <td>{r.scenario_name} (r{r.revision})</td>
                                <td>
                                  <span className={`status-badge ${r.status === 'completed' ? 'status-ok' : r.status === 'failed' ? 'status-fail' : 'status-pending'}`}>
                                    {r.status}
                                  </span>
                                </td>
                                <td className="font-mono text-muted">{new Date(r.started_at).toLocaleTimeString()}</td>
                                <td className="font-mono">{r.duration_seconds != null ? `${r.duration_seconds}s` : 'N/A'}</td>
                                <td className="text-right">
                                  <button className="btn-mini-log" onClick={() => handleViewLogs(r.run_id)}>
                                    📄 Logs
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </aside>
        )}
      </main>

      {/* Log Viewer Modal */}
      {runLogsModal && (
        <div className="modal-backdrop" onClick={() => setRunLogsModal(null)}>
          <div className="log-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h4 className="modal-title">📄 Simulation Logs: {runLogsModal.run_id.slice(0, 8)}...</h4>
              <button className="btn-close-modal" onClick={() => setRunLogsModal(null)}>✕</button>
            </div>
            <div className="modal-body font-mono">
              <h5 className="log-section-title">STDOUT:</h5>
              <pre className="log-pre">{runLogsModal.stdout || '(No stdout captured)'}</pre>
              <h5 className="log-section-title">STDERR:</h5>
              <pre className="log-pre text-danger">{runLogsModal.stderr || '(No stderr captured)'}</pre>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary-action" onClick={() => setRunLogsModal(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App


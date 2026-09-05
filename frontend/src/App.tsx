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
  const [activeTab, setActiveTab] = useState<'layers' | 'exposure' | 'damage'>('layers')

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
      ? 'Screening-positive (depth > 0)'
      : isAssessed
      ? 'Not exposed at sample'
      : 'Not assessed'

    const badgeClass = isExposed
      ? 'badge-exposed'
      : isAssessed
      ? 'badge-safe'
      : 'badge-unassessed'

    const depthDisplay = depthVal !== null
      ? (depthVal > 0 ? `${depthVal.toFixed(2)} (unit unverified)` : '0.00 (unit unverified)')
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
          <div class="popup-row"><span class="popup-label">Arrival Time:</span> <strong class="popup-val">${arrVal !== null ? `${arrVal.toFixed(2)} (unit unverified)` : 'N/A (unit unverified)'}</strong></div>
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
            '#64748b', // Not exposed = Slate
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
        map.getCanvas().style.cursor = 'pointer'
      })
      map.on('mouseleave', layerId, () => {
        map.getCanvas().style.cursor = ''
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
        map.getCanvas().style.cursor = 'pointer'
      })
      map.on('mouseleave', id, () => {
        map.getCanvas().style.cursor = ''
      })
    })
  }, [apiBaseUrl, showAssets, mapLoaded, handleVectorFeatureClick])

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

  // Handle Map Click - Point Inspection Probe (when clicking non-feature canvas)
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const handleMapClick = (e: maplibregl.MapMouseEvent) => {
      // If a vector feature was clicked, don't overwrite with blank probe
      const vectorFeatures = map.queryRenderedFeatures(e.point, {
        layers: ['assets-polygons-fill', 'assets-lines', 'assets-points', 'roads-line'].filter((id) => map.getLayer(id)),
      })

      if (vectorFeatures.length > 0) {
        return
      }

      const { lng, lat } = e.lngLat
      const queryLon = Number(lng.toFixed(6))
      const queryLat = Number(lat.toFixed(6))

      // Update or create marker
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

  const formatCurrency = (val: number) => {
    return val.toLocaleString('en-IN', { maximumFractionDigits: 0 })
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

        {/* Floating Sidebar / Control HUD */}
        {sidebarOpen && (
          <aside className="hud-panel">
            {/* Panel Tab Navigation */}
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
                💰 Damage Scenario
              </button>
            </div>

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
                      <span>Screening-positive (depth &gt; 0)</span>
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
                        {selectedLayer === 'depth' && 'ℹ️ Dry cells (depth = 0, unit unverified) are rendered transparent.'}
                        {selectedLayer === 'velocity' && 'ℹ️ Zero velocity cells (0, unit unverified) are rendered transparent.'}
                        {selectedLayer === 'arrival' && 'ℹ️ Unflooded cells (+9999 / -9999, unit unverified) are rendered transparent.'}
                        {selectedLayer === 'dem' && 'ℹ️ NoData / outside cells are rendered transparent.'}
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
                                  : '0.00 (unit unverified)'
                                : probe.values.depth?.is_nodata
                                ? 'NoData / Dry'
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
                                ? 'Unflooded'
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

            {activeTab === 'exposure' && (
              /* Exposure Summary Card */
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

            {activeTab === 'damage' && (
              /* Phase 7: Illustrative Damage Scenario Panel */
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
          </aside>
        )}
      </main>
    </div>
  )
}

export default App

import { useEffect, useRef, useState, useCallback } from 'react'
import maplibregl, { Map as MapLibreMap, Marker } from 'maplibre-gl'
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
  offset: float
  color: string
  value: float
}

type float = number

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

  const [backendOnline, setBackendOnline] = useState<boolean | null>(null)
  const [datasets, setDatasets] = useState<DatasetInfo[]>([])
  const [selectedLayer, setSelectedLayer] = useState<LayerId>('depth')
  const [opacity, setOpacity] = useState<number>(0.85)
  const [legend, setLegend] = useState<RasterLegend | null>(null)
  const [legendLoading, setLegendLoading] = useState<boolean>(false)
  const [mapLoaded, setMapLoaded] = useState<boolean>(false)
  const [probe, setProbe] = useState<ProbeData | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true)

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

    map.addLayer({
      id: layerId,
      type: 'raster',
      source: sourceId,
      paint: {
        'raster-opacity': opacity,
        'raster-fade-duration': 150,
      },
    })
  }, [apiBaseUrl, selectedLayer, mapLoaded])

  // Update opacity dynamically
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return
    const layerId = 'raster-tiles-layer'
    if (map.getLayer(layerId)) {
      map.setPaintProperty(layerId, 'raster-opacity', opacity)
    }
  }, [opacity, mapLoaded])

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

  // Handle Map Click - Point Inspection Probe
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const handleMapClick = (e: maplibregl.MapMouseEvent) => {
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
            {/* Layer Selector */}
            <div className="hud-card">
              <div className="hud-card-header">
                <h3>Hydrodynamic Raster Layers</h3>
                <button className="btn-fit" onClick={fitToHidkal} title="Fit map to Hidkal bounds">
                  🎯 Fit Hidkal
                </button>
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
                  <label htmlFor="opacity-slider">Layer Opacity</label>
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
                <span className="legend-tag">{selectedLayer.toUpperCase()}</span>
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
                              : '0.00 (Dry, unit unverified)'
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
                  <p>📍 Click anywhere inside the Hidkal boundary to probe elevation, depth, velocity, and arrival values.</p>
                </div>
              )}
            </div>
          </aside>
        )}
      </main>
    </div>
  )
}

export default App


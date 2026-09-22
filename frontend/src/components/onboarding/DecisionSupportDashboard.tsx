// DecisionSupportDashboard.tsx - Phase 29 Dam-Break Decision-Support Dashboard
import React, { useState, useEffect, useCallback } from 'react'
import type {
  DecisionSupportResponse,
  ModeledCriticalPoint,
} from '../../types/damProjects'
import {
  fetchDecisionSupportSummary,
  getDecisionSupportExportUrl,
} from '../../api/damProjects'
import './DecisionSupportDashboard.css'

interface DecisionSupportDashboardProps {
  projectId: string
  onSelectLayer?: (tileUrl: string, layerName: string) => void
  onSelectCriticalPoint?: (point: ModeledCriticalPoint) => void
  onOpenComparison?: () => void
}

type MapMode = 'depth' | 'velocity' | 'arrival' | 'severity'

export const DecisionSupportDashboard: React.FC<DecisionSupportDashboardProps> = ({
  projectId,
  onSelectLayer,
  onSelectCriticalPoint,
  onOpenComparison,
}) => {
  const [data, setData] = useState<DecisionSupportResponse | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [activeMapMode, setActiveMapMode] = useState<MapMode>('severity')
  const [selectedPointId, setSelectedPointId] = useState<string | null>(null)

  const loadData = useCallback(() => {
    if (!projectId) return
    setLoading(true)
    setError(null)
    fetchDecisionSupportSummary(projectId)
      .then((resp) => {
        setData(resp)
        setLoading(false)
      })
      .catch((err: any) => {
        setError(err.message || 'Failed to load decision-support data')
        setLoading(false)
      })
  }, [projectId])

  useEffect(() => {
    let active = true
    if (!projectId) return

    fetchDecisionSupportSummary(projectId)
      .then((resp) => {
        if (active) {
          setData(resp)
          setLoading(false)
        }
      })
      .catch((err: any) => {
        if (active) {
          setError(err.message || 'Failed to load decision-support data')
          setLoading(false)
        }
      })

    return () => {
      active = false
    }
  }, [projectId])

  const handleModeChange = (mode: MapMode) => {
    setActiveMapMode(mode)
    if (!data || !onSelectLayer) return
    const endpoint = data.tile_endpoints[mode]
    const labelMap: Record<MapMode, string> = {
      depth: 'Maximum Water Depth (m)',
      velocity: 'Maximum Flow Velocity (m/s)',
      arrival: 'Downstream Arrival Time (s)',
      severity: 'Hydraulic Severity (H = h × v)',
    }
    onSelectLayer(endpoint, labelMap[mode])
  }

  const handlePointClick = (point: ModeledCriticalPoint) => {
    setSelectedPointId(point.point_id)
    if (onSelectCriticalPoint) {
      onSelectCriticalPoint(point)
    }
  }

  if (loading) {
    return (
      <div className="decision-support-container">
        <div style={{ padding: '3rem', textAlign: 'center', color: '#94a3b8' }}>
          <span className="spinner" style={{ marginRight: '0.5rem' }} />
          Loading Hydrodynamic Decision-Support Metrics...
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="decision-support-container">
        <div style={{ padding: '2rem', textAlign: 'center', color: '#f87171' }}>
          <div style={{ fontSize: '1.5rem', marginBottom: '0.5rem' }}>⚠️ Simulation Outputs Required</div>
          <p style={{ fontSize: '0.85rem', color: '#cbd5e1', maxWidth: '480px', margin: '0 auto 1rem' }}>
            {error || 'No completed ANUGA simulation runs were found for this project.'}
          </p>
          <button className="btn-ds-shortcut" onClick={loadData} style={{ margin: '0 auto' }}>
            ↺ Retry
          </button>
        </div>
      </div>
    )
  }

  const { kpis, severity_config, scenario, critical_points, depth_distribution, velocity_distribution, downstream_zones } = data

  return (
    <div className="decision-support-container">
      {/* Header & Meta Bar */}
      <div className="ds-header">
        <div className="ds-title-group">
          <h3>📊 Dam-Break Decision-Support Dashboard</h3>
          <div className="ds-solver-badges">
            <span className="ds-badge-primary" title="Primary 2D hydrodynamic solver for regional routing">
              PRIMARY REGIONAL ANALYSIS: ANUGA 2D Shallow-Water Simulation
            </span>
            <span className="ds-badge-supp" title="Supplementary near-field Lagrangian particle model">
              SUPPLEMENTARY NEAR-FIELD: Custom Terrain-SPH Demonstration
            </span>
            <span className="ds-badge-demo" title="Academic research demonstration only">
              DEMONSTRATION PROTOTYPE — NOT FOR OPERATIONAL EVACUATION
            </span>
          </div>
        </div>

        <div className="ds-actions">
          <a
            href={getDecisionSupportExportUrl(projectId, 'json')}
            download={`decision_support_${projectId.slice(0, 8)}.json`}
            className="btn-ds-export"
          >
            📥 JSON Export
          </a>
          <a
            href={getDecisionSupportExportUrl(projectId, 'csv')}
            download={`decision_support_${projectId.slice(0, 8)}.csv`}
            className="btn-ds-export"
          >
            📊 CSV Summary
          </a>
          {onOpenComparison && (
            <button className="btn-ds-shortcut" onClick={onOpenComparison}>
              ⚖️ View SPH vs ANUGA Comparison
            </button>
          )}
        </div>
      </div>

      {/* Row 1: Top-Level KPI Cards */}
      <div className="ds-kpi-grid">
        <div className="ds-kpi-card">
          <div className="ds-kpi-icon">🌊</div>
          <div className="ds-kpi-title">Maximum Water Depth</div>
          <div className="ds-kpi-value-row">
            <span className="ds-kpi-value">{kpis.maximum_depth_m.toFixed(2)}</span>
            <span className="ds-kpi-unit">m</span>
          </div>
          <div className="ds-kpi-subtext">Peak modeled water-column submergence in deep pool / breach outlet.</div>
        </div>

        <div className="ds-kpi-card">
          <div className="ds-kpi-icon">⚡</div>
          <div className="ds-kpi-title">Maximum Flow Velocity</div>
          <div className="ds-kpi-value-row">
            <span className="ds-kpi-value">{kpis.maximum_velocity_ms.toFixed(2)}</span>
            <span className="ds-kpi-unit">m/s</span>
          </div>
          <div className="ds-kpi-subtext">Peak modeled depth-averaged speed through breach constriction.</div>
        </div>

        <div className="ds-kpi-card">
          <div className="ds-kpi-icon">🗺️</div>
          <div className="ds-kpi-title">Maximum Inundated Area</div>
          <div className="ds-kpi-value-row">
            <span className="ds-kpi-value">{kpis.inundated_area_km2.toFixed(2)}</span>
            <span className="ds-kpi-unit">km²</span>
          </div>
          <div className="ds-kpi-subtext">
            {kpis.domain_inundated_pct.toFixed(1)}% of total modeled computational domain ({kpis.total_domain_area_km2.toFixed(2)} km²).
          </div>
        </div>

        <div className="ds-kpi-card">
          <div className="ds-kpi-icon">⏱️</div>
          <div className="ds-kpi-title">First Downstream Arrival</div>
          <div className="ds-kpi-value-row">
            <span className="ds-kpi-value">{kpis.first_downstream_arrival_min.toFixed(1)}</span>
            <span className="ds-kpi-unit">min</span>
          </div>
          <div className="ds-kpi-subtext">
            {kpis.first_downstream_arrival_s.toFixed(0)} s to first downstream station outside reservoir pool.
          </div>
        </div>

        <div className="ds-kpi-card">
          <div className="ds-kpi-icon">📍</div>
          <div className="ds-kpi-title">Downstream Flood Reach</div>
          <div className="ds-kpi-value-row">
            <span className="ds-kpi-value">{kpis.downstream_flood_reach_km.toFixed(2)}</span>
            <span className="ds-kpi-unit">km</span>
          </div>
          <div className="ds-kpi-subtext">Maximum distance along river corridor reached by modeled surge.</div>
        </div>
      </div>

      {/* Row 2: Map Controls & Modeled Critical Points */}
      <div className="ds-map-section">
        <div className="ds-map-header">
          <div className="ds-map-title">
            <span>🗺️</span> Active Analysis Layer Selector
          </div>
          <div className="ds-mode-selector">
            <button
              className={`ds-mode-btn ${activeMapMode === 'depth' ? 'active' : ''}`}
              onClick={() => handleModeChange('depth')}
            >
              🌊 Water Depth
            </button>
            <button
              className={`ds-mode-btn ${activeMapMode === 'velocity' ? 'active' : ''}`}
              onClick={() => handleModeChange('velocity')}
            >
              💨 Flow Velocity
            </button>
            <button
              className={`ds-mode-btn ${activeMapMode === 'arrival' ? 'active' : ''}`}
              onClick={() => handleModeChange('arrival')}
            >
              ⏱️ Arrival Time
            </button>
            <button
              className={`ds-mode-btn ${activeMapMode === 'severity' ? 'active' : ''}`}
              onClick={() => handleModeChange('severity')}
            >
              🔥 Hydraulic Severity
            </button>
          </div>
        </div>

        {/* Modeled Critical Points */}
        <div className="ds-critical-points-bar">
          <span className="ds-cp-label">📍 Modeled Critical Points:</span>
          {critical_points.map((pt) => (
            <button
              key={pt.point_id}
              className={`ds-cp-badge ${selectedPointId === pt.point_id ? 'active' : ''}`}
              onClick={() => handlePointClick(pt)}
              title={`${pt.description} | WGS84 Lat: ${pt.coordinate_wgs84[0]}° N, Lon: ${pt.coordinate_wgs84[1]}° E | UTM: ${pt.coordinate_utm[0]} m, ${pt.coordinate_utm[1]} m`}
            >
              <strong>{pt.title}:</strong> {pt.value} {pt.unit}
            </button>
          ))}
        </div>

        {/* Selected Critical Point Detail Panel */}
        {selectedPointId && (() => {
          const pt = critical_points.find(p => p.point_id === selectedPointId)
          if (!pt) return null
          return (
            <div style={{
              margin: '0.4rem 0.75rem',
              padding: '0.5rem 0.75rem',
              background: '#0f172a',
              border: '1px solid #38bdf8',
              borderRadius: '6px',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.25rem',
              fontSize: '0.75rem',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 700, color: '#38bdf8' }}>📍 {pt.title}: {pt.value} {pt.unit}</span>
                <span style={{ fontSize: '0.68rem', color: '#94a3b8', fontStyle: 'italic' }}>{pt.disclaimer}</span>
              </div>
              <div style={{ color: '#cbd5e1' }}>{pt.description}</div>
              <div style={{ display: 'flex', gap: '1rem', color: '#94a3b8', fontFamily: 'monospace', fontSize: '0.7rem' }}>
                <span>🌐 WGS84: Lat {pt.coordinate_wgs84[0]}° N, Lon {pt.coordinate_wgs84[1]}° E</span>
                <span>📐 UTM: Easting {pt.coordinate_utm[0]} m, Northing {pt.coordinate_utm[1]} m</span>
              </div>
            </div>
          )
        })()}


        {/* Active Legend Strip */}
        <div className="ds-legend-strip">
          {activeMapMode === 'severity' && (
            <>
              <span style={{ fontWeight: 600, color: '#38bdf8' }}>Hydraulic Severity (H = h × v):</span>
              {severity_config.thresholds.map((b) => (
                <div key={b.band} className="ds-legend-band">
                  <span className="ds-legend-color" style={{ background: b.color }} />
                  <span>{b.band} ({b.min_val}{b.max_val ? ` - ${b.max_val}` : '+'} m²/s)</span>
                </div>
              ))}
              <span style={{ fontSize: '0.68rem', color: '#94a3b8', marginLeft: 'auto' }}>
                *Project demonstration thresholds — not regulatory classifications
              </span>
            </>
          )}

          {activeMapMode === 'depth' && (
            <>
              <span style={{ fontWeight: 600, color: '#38bdf8' }}>Water Depth:</span>
              <div className="ds-legend-band"><span className="ds-legend-color" style={{ background: '#38bdf8' }} /> Shallow (0.05 - 1.0 m)</div>
              <div className="ds-legend-band"><span className="ds-legend-color" style={{ background: '#0284c7' }} /> Moderate (1.0 - 5.0 m)</div>
              <div className="ds-legend-band"><span className="ds-legend-color" style={{ background: '#1e3a8a' }} /> Deep (&gt; 5.0 m)</div>
            </>
          )}

          {activeMapMode === 'velocity' && (
            <>
              <span style={{ fontWeight: 600, color: '#38bdf8' }}>Flow Velocity:</span>
              <div className="ds-legend-band"><span className="ds-legend-color" style={{ background: '#22c55e' }} /> Low (0 - 1.0 m/s)</div>
              <div className="ds-legend-band"><span className="ds-legend-color" style={{ background: '#eab308' }} /> Moderate (1.0 - 3.0 m/s)</div>
              <div className="ds-legend-band"><span className="ds-legend-color" style={{ background: '#ef4444' }} /> High (&gt; 3.0 m/s)</div>
            </>
          )}

          {activeMapMode === 'arrival' && (
            <>
              <span style={{ fontWeight: 600, color: '#38bdf8' }}>Downstream Arrival:</span>
              <div className="ds-legend-band"><span className="ds-legend-color" style={{ background: '#ef4444' }} /> Immediate (&lt; 5 min)</div>
              <div className="ds-legend-band"><span className="ds-legend-color" style={{ background: '#f59e0b' }} /> Short (5 - 20 min)</div>
              <div className="ds-legend-band"><span className="ds-legend-color" style={{ background: '#a855f7' }} /> Extended (&gt; 20 min)</div>
            </>
          )}
        </div>
      </div>

      {/* Row 3: Decision Summary Narrative & "What This Means" */}
      <div className="ds-narrative-card">
        <div className="ds-narrative-header">
          <span>📝</span> Automated Decision Summary
        </div>
        <p style={{ margin: 0 }}>{data.narrative_summary}</p>
      </div>

      <div className="ds-education-grid">
        <div className="ds-education-card">
          <strong>🌊 Water Depth (h)</strong>
          {data.what_this_means.depth}
        </div>
        <div className="ds-education-card">
          <strong>⚡ Flow Velocity (v)</strong>
          {data.what_this_means.velocity}
        </div>
        <div className="ds-education-card">
          <strong>⏱️ Arrival Time (t_arr)</strong>
          {data.what_this_means.arrival_time}
        </div>
        <div className="ds-education-card">
          <strong>🔥 Hydraulic Severity (H)</strong>
          {data.what_this_means.hydraulic_severity}
        </div>
      </div>

      {/* Row 4: Depth & Velocity Distribution Visualizations */}
      <div className="ds-charts-grid">
        <div className="ds-chart-card">
          <div className="ds-chart-title">
            <span>🌊</span> Modeled Water-Depth Distribution
          </div>
          <div className="ds-chart-bars">
            {depth_distribution.map((bin) => (
              <div key={bin.range_label} className="ds-bar-row">
                <div className="ds-bar-label-row">
                  <span>{bin.range_label}</span>
                  <span style={{ fontWeight: 600 }}>{bin.area_km2.toFixed(3)} km² ({bin.percentage.toFixed(1)}%)</span>
                </div>
                <div className="ds-bar-track">
                  <div className="ds-bar-fill" style={{ width: `${Math.min(bin.percentage, 100)}%`, background: '#38bdf8' }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="ds-chart-card">
          <div className="ds-chart-title">
            <span>⚡</span> Modeled Flow-Velocity Distribution
          </div>
          <div className="ds-chart-bars">
            {velocity_distribution.map((bin) => (
              <div key={bin.range_label} className="ds-bar-row">
                <div className="ds-bar-label-row">
                  <span>{bin.range_label}</span>
                  <span style={{ fontWeight: 600 }}>{bin.area_km2.toFixed(3)} km² ({bin.percentage.toFixed(1)}%)</span>
                </div>
                <div className="ds-bar-track">
                  <div className="ds-bar-fill" style={{ width: `${Math.min(bin.percentage, 100)}%`, background: '#f59e0b' }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Row 5: Downstream Zone Distance Analysis */}
      <div className="ds-table-card">
        <div className="ds-chart-title">
          <span>📏</span> Downstream Distance Zone Analysis (From Dam Axis)
        </div>
        <table className="ds-table">
          <thead>
            <tr>
              <th>Distance Zone</th>
              <th>Max Depth</th>
              <th>Max Velocity</th>
              <th>Earliest Arrival</th>
              <th>Inundated Area</th>
              <th>Mean Severity (h × v)</th>
            </tr>
          </thead>
          <tbody>
            {downstream_zones.map((z) => (
              <tr key={z.zone_label}>
                <td style={{ fontWeight: 600, color: '#38bdf8' }}>{z.zone_label}</td>
                <td>{z.max_depth_m > 0 ? `${z.max_depth_m.toFixed(2)} m` : 'Dry'}</td>
                <td>{z.max_velocity_ms > 0 ? `${z.max_velocity_ms.toFixed(2)} m/s` : '0 m/s'}</td>
                <td>{z.earliest_arrival_s !== null ? `${z.earliest_arrival_min?.toFixed(1)} min (${z.earliest_arrival_s} s)` : '—'}</td>
                <td>{z.inundated_area_km2.toFixed(3)} km²</td>
                <td>{z.mean_severity_m2s.toFixed(2)} m²/s</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Row 6: Scenario Parameters & Model Limitations */}
      <div className="ds-table-card">
        <div className="ds-chart-title">
          <span>⚙️</span> Simulation Scenario Configuration
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.75rem', fontSize: '0.75rem' }}>
          <div><span style={{ color: '#94a3b8' }}>Dam / Project:</span> <strong>{scenario.dam_name}</strong></div>
          <div><span style={{ color: '#94a3b8' }}>Terrain Dataset:</span> <strong>{scenario.terrain_source}</strong></div>
          <div><span style={{ color: '#94a3b8' }}>Initial Reservoir Level:</span> <strong>{scenario.reservoir_level_m} m</strong></div>
          <div><span style={{ color: '#94a3b8' }}>Modeled Breach Width:</span> <strong>{scenario.breach_width_m} m</strong></div>
          <div><span style={{ color: '#94a3b8' }}>Failure Mode:</span> <strong>{scenario.breach_type}</strong></div>
          <div><span style={{ color: '#94a3b8' }}>Manning Roughness (n):</span> <strong>{scenario.manning_roughness}</strong></div>
          <div><span style={{ color: '#94a3b8' }}>Simulation Duration:</span> <strong>{scenario.simulation_duration_s} s (1.0 hr)</strong></div>
          <div><span style={{ color: '#94a3b8' }}>Computational Mesh:</span> <strong>{scenario.mesh_cells} triangular cells</strong></div>
        </div>
      </div>

      {/* Scientific Limitations Panel */}
      <div className="ds-limitations-card">
        <div className="ds-limitations-title">
          <span>⚠️</span> Model Limitations & Demonstration Notice
        </div>
        <ul className="ds-limitations-list">
          {data.limitations.map((lim, idx) => (
            <li key={idx}>{lim}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export default DecisionSupportDashboard

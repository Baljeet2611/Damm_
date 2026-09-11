// ModelComparisonPanel.tsx - Phase 21 Multi-Engine Spatial Hydrodynamic Comparison
import React, { useEffect, useState, useCallback } from 'react'
import type {
  ModelComparisonCapabilitiesResponse,
  ModelComparisonRunResponse,
} from '../../types/damProjects'
import {
  fetchModelComparisonCapabilities,
  createModelComparisonRun,
  fetchModelComparisonRuns,
  fetchModelComparisonLogs,
  getModelComparisonTileUrl,
} from '../../api/damProjects'
import './ModelComparisonPanel.css'

interface ModelComparisonPanelProps {
  projectId: string
  onSelectComparisonLayer?: (tileUrl: string | null, layerName: string | null) => void
  onClose?: () => void
}

export const ModelComparisonPanel: React.FC<ModelComparisonPanelProps> = ({
  projectId,
  onSelectComparisonLayer,
  onClose,
}) => {
  const [capabilities, setCapabilities] = useState<ModelComparisonCapabilitiesResponse | null>(null)
  const [loadingCaps, setLoadingCaps] = useState<boolean>(true)
  const [runs, setRuns] = useState<ModelComparisonRunResponse[]>([])
  const [selectedRun, setSelectedRun] = useState<ModelComparisonRunResponse | null>(null)
  const [executing, setExecuting] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  // Form parameters
  const [engineA, setEngineA] = useState<string>('anuga')
  const [runIdA, setRunIdA] = useState<string>('')
  const [engineB, setEngineB] = useState<string>('delft3d_fm')
  const [runIdB, setRunIdB] = useState<string>('')
  const [depthThreshold, setDepthThreshold] = useState<number>(0.10)
  const [allowSynthetic, setAllowSynthetic] = useState<boolean>(false)

  // Active layer & logs
  const [activeLayer, setActiveLayer] = useState<string | null>(null)
  const [showingLogs, setShowingLogs] = useState<boolean>(false)
  const [logsContent, setLogsContent] = useState<string | null>(null)
  const [loadingLogs, setLoadingLogs] = useState<boolean>(false)

  useEffect(() => {
    let mounted = true
    const init = async () => {
      try {
        setLoadingCaps(true)
        setError(null)
        const [caps, runList] = await Promise.all([
          fetchModelComparisonCapabilities(projectId),
          fetchModelComparisonRuns(projectId).catch(() => []),
        ])
        if (!mounted) return
        setCapabilities(caps)
        setRuns(runList)
        if (runList.length > 0) {
          setSelectedRun(runList[0])
        }

        const anugaRuns = caps.runs_available?.anuga || []
        const d3dRuns = caps.runs_available?.delft3d_fm || []
        const sphRuns = caps.runs_available?.pysph || []

        if (anugaRuns.length > 0) {
          setRunIdA(anugaRuns[0].run_id)
        }
        if (d3dRuns.length > 0) {
          setEngineB('delft3d_fm')
          setRunIdB(d3dRuns[0].run_id)
        } else if (sphRuns.length > 0) {
          setEngineB('pysph')
          setRunIdB(sphRuns[0].run_id)
        } else if (anugaRuns.length > 1) {
          setEngineB('anuga')
          setRunIdB(anugaRuns[1].run_id)
        }
      } catch (err: any) {
        if (mounted) setError(err.message || 'Failed to query engine capabilities')
      } finally {
        if (mounted) setLoadingCaps(false)
      }
    }
    init()
    return () => {
      mounted = false
    }
  }, [projectId])

  const refreshRuns = useCallback(async () => {
    try {
      const runList = await fetchModelComparisonRuns(projectId)
      setRuns(runList)
    } catch {
      // Non-fatal
    }
  }, [projectId])

  const handleExecuteComparison = async () => {
    try {
      setExecuting(true)
      setError(null)

      const payload = {
        engine_a: engineA,
        run_id_a: runIdA || 'default_run',
        engine_b: engineB,
        run_id_b: runIdB || 'default_run',
        depth_inundation_threshold_m: depthThreshold,
        tolerance_bands_m: [0.10, 0.25, 0.50],
        synthetic_test_fixture: allowSynthetic,
      }

      const res = await createModelComparisonRun(projectId, payload)
      setSelectedRun(res)
      await refreshRuns()
    } catch (err: any) {
      setError(err.message || 'Execution of model comparison failed')
    } finally {
      setExecuting(false)
    }
  }

  const handleToggleLayer = (layerName: string) => {
    if (!selectedRun) return

    if (activeLayer === layerName) {
      setActiveLayer(null)
      onSelectComparisonLayer?.(null, null)
    } else {
      setActiveLayer(layerName)
      const tileUrl = getModelComparisonTileUrl(projectId, selectedRun.comparison_id, layerName)
      onSelectComparisonLayer?.(tileUrl, `Comparison: ${layerName}`)
    }
  }

  const handleViewLogs = async (comparisonId: string) => {
    try {
      setLoadingLogs(true)
      setShowingLogs(true)
      const res = await fetchModelComparisonLogs(projectId, comparisonId)
      setLogsContent(res.logs)
    } catch (err: any) {
      setLogsContent(`Failed to fetch logs: ${err.message}`)
    } finally {
      setLoadingLogs(false)
    }
  }

  return (
    <div className="model-comp-container">
      {/* Header */}
      <div className="comp-header">
        <h3 className="comp-title">
          <span>⚖️</span> Multi-Engine Spatial Hydrodynamic Comparison
        </h3>
        {onClose && (
          <button
            type="button"
            className="comp-select"
            style={{ padding: '0.2rem 0.5rem', cursor: 'pointer' }}
            onClick={onClose}
          >
            ✕ Close
          </button>
        )}
      </div>

      {/* Scientific Disclaimer */}
      <div className="comp-disclaimer-box">
        <strong>Scientific Disclaimer: </strong>
        Model disagreement reflects differences in numerical schemes, mesh resolution, wetting/drying treatment,
        friction, breach representation, terrain processing, boundaries and other modelling assumptions.
        Neither model is treated as ground truth. All spatial agreement and difference statistics are strictly inter-model comparisons.
      </div>

      {/* Engine Capability Matrix */}
      <div className="comp-section">
        <div className="comp-section-title">
          <span>1. Hydrodynamic Solver Availability Matrix</span>
          {loadingCaps && <span style={{ fontSize: '0.7rem', color: '#94a3b8' }}>Detecting engines...</span>}
        </div>

        <div className="engine-matrix-grid">
          {/* ANUGA */}
          {(() => {
            const anuga = capabilities?.engines?.anuga
            const isReady = anuga?.available_for_comparison
            return (
              <div className={`engine-cap-card ${isReady ? 'ready' : 'unsupported'}`}>
                <div className="engine-card-header">
                  <span className="engine-name">ANUGA</span>
                  <span className={`engine-pill ${isReady ? 'pill-ready' : anuga?.environment_available ? 'pill-untested' : 'pill-unavailable'}`}>
                    {isReady ? 'Comparable' : anuga?.environment_available ? 'No Runs' : 'Unavailable'}
                  </span>
                </div>
                <div className="engine-detail-row">
                  <span>Version:</span>
                  <span className="engine-detail-val">{anuga?.version || 'undetected'}</span>
                </div>
                <div className="engine-detail-row">
                  <span>Environment:</span>
                  <span className="engine-detail-val">{anuga?.environment_available ? 'Installed' : 'Missing'}</span>
                </div>
                <div className="engine-detail-row">
                  <span>Completed Runs:</span>
                  <span className="engine-detail-val">{anuga?.completed_run_count ?? 0}</span>
                </div>
                {anuga?.reason && <div className="engine-reason">{anuga.reason}</div>}
              </div>
            )
          })()}

          {/* Delft3D FM */}
          {(() => {
            const d3d = capabilities?.engines?.delft3d_fm
            const isReady = d3d?.available_for_comparison
            return (
              <div className={`engine-cap-card ${isReady ? 'ready' : 'unsupported'}`}>
                <div className="engine-card-header">
                  <span className="engine-name">Delft3D / D-Flow FM</span>
                  <span className={`engine-pill ${isReady ? 'pill-ready' : d3d?.environment_available ? 'pill-untested' : 'pill-unavailable'}`}>
                    {isReady ? 'Comparable' : d3d?.environment_available ? 'No Runs' : 'Unavailable'}
                  </span>
                </div>
                <div className="engine-detail-row">
                  <span>Version:</span>
                  <span className="engine-detail-val">{d3d?.version || 'undetected'}</span>
                </div>
                <div className="engine-detail-row">
                  <span>Environment:</span>
                  <span className="engine-detail-val">{d3d?.environment_available ? 'HydroMT Ready' : 'Missing'}</span>
                </div>
                <div className="engine-detail-row">
                  <span>Completed Runs:</span>
                  <span className="engine-detail-val">{d3d?.completed_run_count ?? 0}</span>
                </div>
                {d3d?.reason && <div className="engine-reason">{d3d.reason}</div>}
              </div>
            )
          })()}

          {/* PySPH */}
          {(() => {
            const sph = capabilities?.engines?.pysph
            const isReady = sph?.available_for_comparison
            return (
              <div className={`engine-cap-card ${isReady ? 'ready' : 'unsupported'}`}>
                <div className="engine-card-header">
                  <span className="engine-name">PySPH (Lagrangian)</span>
                  <span className={`engine-pill ${isReady ? 'pill-ready' : sph?.environment_available ? 'pill-untested' : 'pill-unavailable'}`}>
                    {isReady ? 'Comparable' : sph?.environment_available ? 'No Raster' : 'Unavailable'}
                  </span>
                </div>
                <div className="engine-detail-row">
                  <span>Version:</span>
                  <span className="engine-detail-val">{sph?.version || 'undetected'}</span>
                </div>
                <div className="engine-detail-row">
                  <span>Environment:</span>
                  <span className="engine-detail-val">{sph?.environment_available ? 'PySPH Ready' : 'Missing'}</span>
                </div>
                <div className="engine-detail-row">
                  <span>Completed Runs:</span>
                  <span className="engine-detail-val">{sph?.completed_run_count ?? 0}</span>
                </div>
                {sph?.reason && <div className="engine-reason">{sph.reason}</div>}
              </div>
            )
          })()}
        </div>
      </div>

      {/* Setup / Run Picker */}
      <div className="comp-section">
        <div className="comp-section-title">2. Configure Pairwise Comparison</div>

        <div className="comp-form-row">
          {/* Model A */}
          <div className="comp-field">
            <label htmlFor="comp-engine-a">Engine A (Reference Solver)</label>
            <select
              id="comp-engine-a"
              className="comp-select"
              value={engineA}
              onChange={(e) => {
                setEngineA(e.target.value)
                const list = capabilities?.runs_available?.[e.target.value] || []
                if (list.length > 0) setRunIdA(list[0].run_id)
              }}
            >
              <option value="anuga">ANUGA Shallow Water</option>
              <option value="delft3d_fm">Delft3D / D-Flow FM</option>
              <option value="pysph">PySPH SPH</option>
            </select>

            <label htmlFor="comp-run-a" style={{ marginTop: '0.3rem' }}>Select Run A</label>
            <select
              id="comp-run-a"
              className="comp-select"
              value={runIdA}
              onChange={(e) => setRunIdA(e.target.value)}
            >
              {(capabilities?.runs_available?.[engineA] || []).length === 0 && (
                <option value="">(No completed runs on disk)</option>
              )}
              {(capabilities?.runs_available?.[engineA] || []).map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id.substring(0, 16)}... ({r.status})
                </option>
              ))}
            </select>
          </div>

          {/* Model B */}
          <div className="comp-field">
            <label htmlFor="comp-engine-b">Engine B (Comparison Solver)</label>
            <select
              id="comp-engine-b"
              className="comp-select"
              value={engineB}
              onChange={(e) => {
                setEngineB(e.target.value)
                const list = capabilities?.runs_available?.[e.target.value] || []
                if (list.length > 0) setRunIdB(list[0].run_id)
              }}
            >
              <option value="delft3d_fm">Delft3D / D-Flow FM</option>
              <option value="anuga">ANUGA Shallow Water</option>
              <option value="pysph">PySPH SPH</option>
            </select>

            <label htmlFor="comp-run-b" style={{ marginTop: '0.3rem' }}>Select Run B</label>
            <select
              id="comp-run-b"
              className="comp-select"
              value={runIdB}
              onChange={(e) => setRunIdB(e.target.value)}
            >
              {(capabilities?.runs_available?.[engineB] || []).length === 0 && (
                <option value="">(No completed runs on disk)</option>
              )}
              {(capabilities?.runs_available?.[engineB] || []).map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id.substring(0, 16)}... ({r.status})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Depth threshold and test fixture option */}
        <div className="comp-form-row" style={{ marginTop: '0.4rem', alignItems: 'center' }}>
          <div className="comp-field">
            <label htmlFor="comp-threshold">Inundation Threshold (m)</label>
            <input
              id="comp-threshold"
              type="number"
              className="comp-input"
              value={depthThreshold}
              min={0.01}
              max={2.0}
              step={0.01}
              onChange={(e) => setDepthThreshold(parseFloat(e.target.value) || 0.10)}
            />
          </div>

          <div className="comp-field" style={{ justifyContent: 'center' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={allowSynthetic}
                onChange={(e) => setAllowSynthetic(e.target.checked)}
              />
              <span>Test synthetic fixture (for validation without runs)</span>
            </label>
          </div>
        </div>

        {/* Action Button */}
        <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.4rem' }}>
          <button
            type="button"
            className="comp-btn-primary"
            style={{ flex: 1 }}
            disabled={executing || (!capabilities?.ready_for_comparison && !allowSynthetic)}
            onClick={handleExecuteComparison}
          >
            {executing ? 'Computing Spatial Comparison...' : 'Compute Inter-Model Spatial Comparison'}
          </button>
        </div>

        {error && <div className="engine-reason" style={{ marginTop: '0.5rem' }}>{error}</div>}
      </div>

      {/* Previous Comparison Runs */}
      {runs.length > 0 && (
        <div className="comp-section">
          <div className="comp-section-title">
            <span>Historical Comparisons ({runs.length})</span>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', overflowX: 'auto', paddingBottom: '0.2rem' }}>
            {runs.map((r) => (
              <button
                key={r.comparison_id}
                type="button"
                className="comp-select"
                style={{
                  cursor: 'pointer',
                  borderColor: selectedRun?.comparison_id === r.comparison_id ? '#38bdf8' : 'rgba(255,255,255,0.15)',
                  background: selectedRun?.comparison_id === r.comparison_id ? 'rgba(56, 189, 248, 0.15)' : 'rgba(15, 23, 42, 0.8)',
                }}
                onClick={() => setSelectedRun(r)}
              >
                {r.comparison_id.substring(0, 16)}... ({r.engine_a} vs {r.engine_b})
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Comparison Results KPI HUD */}
      {selectedRun && (
        <div className="comp-section">
          <div className="comp-section-title">
            <span>Comparison Results: {selectedRun.engine_a.toUpperCase()} vs {selectedRun.engine_b.toUpperCase()}</span>
            <span className="status-badge status-completed">{selectedRun.status}</span>
          </div>

          {/* Spatial Inundation Agreement KPI */}
          <div style={{ marginBottom: '0.6rem' }}>
            <span style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>
              Spatial Extent Agreement (Threshold &ge; {depthThreshold.toFixed(2)}m)
            </span>
            <div className="comp-kpi-grid" style={{ marginTop: '0.3rem' }}>
              <div className="comp-kpi-card">
                <span className="comp-kpi-label">Spatial Agreement (IoU)</span>
                <span className="comp-kpi-value" style={{ color: '#4ade80' }}>
                  {(selectedRun.inundation_agreement.spatial_agreement_iou * 100).toFixed(1)}%
                </span>
                <span className="comp-kpi-sub">Jaccard index</span>
              </div>

              <div className="comp-kpi-card">
                <span className="comp-kpi-label">Overlap Area</span>
                <span className="comp-kpi-value">
                  {selectedRun.inundation_agreement.overlap_area_km2.toFixed(3)} km²
                </span>
                <span className="comp-kpi-sub">Both flooded</span>
              </div>

              <div className="comp-kpi-card">
                <span className="comp-kpi-label">{selectedRun.engine_a.toUpperCase()} Only</span>
                <span className="comp-kpi-value" style={{ color: '#38bdf8' }}>
                  {selectedRun.inundation_agreement.model_a_only_area_km2.toFixed(3)} km²
                </span>
                <span className="comp-kpi-sub">Disagreement</span>
              </div>

              <div className="comp-kpi-card">
                <span className="comp-kpi-label">{selectedRun.engine_b.toUpperCase()} Only</span>
                <span className="comp-kpi-value" style={{ color: '#fb923c' }}>
                  {selectedRun.inundation_agreement.model_b_only_area_km2.toFixed(3)} km²
                </span>
                <span className="comp-kpi-sub">Disagreement</span>
              </div>
            </div>
          </div>

          {/* Depth Difference KPI */}
          <div style={{ marginBottom: '0.6rem' }}>
            <span style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>
              Inter-Model Depth Difference (Common Valid Analysis Grid)
            </span>
            <div className="comp-kpi-grid" style={{ marginTop: '0.3rem' }}>
              <div className="comp-kpi-card">
                <span className="comp-kpi-label">Depth MAE</span>
                <span className="comp-kpi-value">
                  {selectedRun.depth_difference.mae_m.toFixed(2)} m
                </span>
                <span className="comp-kpi-sub">Mean absolute diff</span>
              </div>

              <div className="comp-kpi-card">
                <span className="comp-kpi-label">Depth RMSE</span>
                <span className="comp-kpi-value">
                  {selectedRun.depth_difference.rmse_m.toFixed(2)} m
                </span>
                <span className="comp-kpi-sub">Root mean square diff</span>
              </div>

              <div className="comp-kpi-card">
                <span className="comp-kpi-label">Mean Signed Diff</span>
                <span className="comp-kpi-value">
                  {selectedRun.depth_difference.mean_signed_difference_m >= 0 ? '+' : ''}
                  {selectedRun.depth_difference.mean_signed_difference_m.toFixed(2)} m
                </span>
                <span className="comp-kpi-sub">A - B bias</span>
              </div>

              <div className="comp-kpi-card">
                <span className="comp-kpi-label">Common Area</span>
                <span className="comp-kpi-value">
                  {selectedRun.depth_difference.common_analysis_area_km2.toFixed(2)} km²
                </span>
                <span className="comp-kpi-sub">{selectedRun.depth_difference.common_valid_pixel_count.toLocaleString()} pixels</span>
              </div>
            </div>

            {/* Tolerance Coverage Table */}
            {selectedRun.depth_difference.tolerance_bands?.length > 0 && (
              <table className="tolerance-table">
                <thead>
                  <tr>
                    <th>Tolerance Band</th>
                    <th>Area Coverage</th>
                    <th>% of Common Analysis Area</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedRun.depth_difference.tolerance_bands.map((tb) => (
                    <tr key={tb.tolerance_m}>
                      <td>&plusmn;{tb.tolerance_m.toFixed(2)} m</td>
                      <td>{tb.area_km2.toFixed(3)} km²</td>
                      <td>
                        <strong>{tb.percentage_of_common_valid_area.toFixed(1)}%</strong>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Velocity & Arrival Time row */}
          <div className="comp-form-row" style={{ marginBottom: '0.6rem' }}>
            {/* Velocity */}
            <div className="comp-field">
              <span style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>
                Velocity Comparison
              </span>
              {selectedRun.velocity_difference.available ? (
                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.2rem' }}>
                  <div className="comp-kpi-card" style={{ flex: 1 }}>
                    <span className="comp-kpi-label">Velocity MAE</span>
                    <span className="comp-kpi-value">
                      {selectedRun.velocity_difference.mae_m_s?.toFixed(2)} m/s
                    </span>
                  </div>
                  <div className="comp-kpi-card" style={{ flex: 1 }}>
                    <span className="comp-kpi-label">Velocity RMSE</span>
                    <span className="comp-kpi-value">
                      {selectedRun.velocity_difference.rmse_m_s?.toFixed(2)} m/s
                    </span>
                  </div>
                </div>
              ) : (
                <div className="engine-reason" style={{ color: '#94a3b8', background: 'rgba(255,255,255,0.05)' }}>
                  Velocity comparison unavailable: {selectedRun.velocity_difference.reason || 'Missing velocity outputs in one or both solvers.'}
                </div>
              )}
            </div>

            {/* Arrival Time */}
            <div className="comp-field">
              <span style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>
                Arrival Time Comparison
              </span>
              {selectedRun.arrival_time_difference.available && selectedRun.arrival_time_difference.comparison_valid ? (
                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.2rem' }}>
                  <div className="comp-kpi-card" style={{ flex: 1 }}>
                    <span className="comp-kpi-label">Arrival MAE</span>
                    <span className="comp-kpi-value">
                      {selectedRun.arrival_time_difference.mae_s ? `${(selectedRun.arrival_time_difference.mae_s / 60).toFixed(1)} min` : 'N/A'}
                    </span>
                  </div>
                  <div className="comp-kpi-card" style={{ flex: 1 }}>
                    <span className="comp-kpi-label">Arrival Bias</span>
                    <span className="comp-kpi-value">
                      {selectedRun.arrival_time_difference.mean_signed_difference_s ? `${(selectedRun.arrival_time_difference.mean_signed_difference_s / 60).toFixed(1)} min` : 'N/A'}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="engine-reason" style={{ color: '#fbbf24', background: 'rgba(245, 158, 11, 0.08)' }}>
                  {selectedRun.arrival_time_difference.reason || 'Arrival time definitions are incompatible or outputs are unavailable.'}
                </div>
              )}
            </div>
          </div>

          {/* Inter-Model Spread */}
          {selectedRun.ensemble_spread?.computed && (
            <div style={{ marginBottom: '0.6rem' }}>
              <span style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>
                Inter-Model Spread Diagnostic (max - min depth)
              </span>
              <div className="comp-kpi-grid" style={{ marginTop: '0.3rem' }}>
                <div className="comp-kpi-card">
                  <span className="comp-kpi-label">Mean Spread</span>
                  <span className="comp-kpi-value">{selectedRun.ensemble_spread.mean_spread_m.toFixed(2)} m</span>
                </div>
                <div className="comp-kpi-card">
                  <span className="comp-kpi-label">Max Spread</span>
                  <span className="comp-kpi-value">{selectedRun.ensemble_spread.max_spread_m.toFixed(2)} m</span>
                </div>
                <div className="comp-kpi-card">
                  <span className="comp-kpi-label">Spread Pixels</span>
                  <span className="comp-kpi-value">{selectedRun.ensemble_spread.pixel_count.toLocaleString()}</span>
                </div>
                <div className="comp-kpi-card">
                  <span className="comp-kpi-label">Diagnostic Label</span>
                  <span className="comp-kpi-value" style={{ fontSize: '0.85rem' }}>{selectedRun.ensemble_spread.label}</span>
                </div>
              </div>
            </div>
          )}

          {/* Diverging Color Ramp Legend */}
          <div style={{ margin: '0.5rem 0' }}>
            <span style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>
              Diverging Map Difference Legend (A - B)
            </span>
            <div className="diverging-legend-bar">
              <div className="legend-seg-cyan" />
              <div className="legend-seg-gray" />
              <div className="legend-seg-red" />
            </div>
            <div className="legend-labels">
              <span>Cyan: {selectedRun.engine_a.toUpperCase()} Lower than {selectedRun.engine_b.toUpperCase()} (&lt; -0.25m)</span>
              <span>Gray: Similar (&plusmn;0.10m)</span>
              <span>Red: {selectedRun.engine_a.toUpperCase()} Higher than {selectedRun.engine_b.toUpperCase()} (&gt; +0.25m)</span>
            </div>
          </div>

          {/* Map Layer Toggles */}
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.6rem', flexWrap: 'wrap' }}>
            <button
              type="button"
              className="comp-select"
              style={{
                cursor: 'pointer',
                background: activeLayer === 'depth_difference' ? '#0284c7' : 'rgba(15, 23, 42, 0.8)',
                color: activeLayer === 'depth_difference' ? 'white' : '#f1f5f9',
              }}
              onClick={() => handleToggleLayer('depth_difference')}
            >
              {activeLayer === 'depth_difference' ? 'Hide Depth Difference' : '🗺️ View Depth Difference (A - B)'}
            </button>

            <button
              type="button"
              className="comp-select"
              style={{
                cursor: 'pointer',
                background: activeLayer === 'inundation_overlap' ? '#0284c7' : 'rgba(15, 23, 42, 0.8)',
                color: activeLayer === 'inundation_overlap' ? 'white' : '#f1f5f9',
              }}
              onClick={() => handleToggleLayer('inundation_overlap')}
            >
              {activeLayer === 'inundation_overlap' ? 'Hide Inundation Overlap' : '🗺️ View Inundation Overlap'}
            </button>

            <button
              type="button"
              className="comp-select"
              style={{
                cursor: 'pointer',
                background: activeLayer === 'inter_model_spread' ? '#0284c7' : 'rgba(15, 23, 42, 0.8)',
                color: activeLayer === 'inter_model_spread' ? 'white' : '#f1f5f9',
              }}
              onClick={() => handleToggleLayer('inter_model_spread')}
            >
              {activeLayer === 'inter_model_spread' ? 'Hide Inter-Model Spread' : '🗺️ View Inter-Model Spread'}
            </button>

            <button
              type="button"
              className="comp-select"
              style={{ cursor: 'pointer' }}
              onClick={() => handleViewLogs(selectedRun.comparison_id)}
            >
              📋 View Execution Log
            </button>
          </div>

          {/* Logs Modal */}
          {showingLogs && (
            <div style={{ marginTop: '0.6rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.3rem' }}>
                <span style={{ fontSize: '0.72rem', color: '#94a3b8', fontWeight: 600 }}>Execution Logs</span>
                <button
                  type="button"
                  style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}
                  onClick={() => setShowingLogs(false)}
                >
                  ✕ Close
                </button>
              </div>
              <div className="logs-modal">
                {loadingLogs ? 'Loading logs...' : logsContent || 'No logs available.'}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
export default ModelComparisonPanel

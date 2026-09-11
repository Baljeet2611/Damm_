import React, { useState, useEffect, useRef } from 'react'
import type {
  DamProjectAnugaPreflightResponse,
  DamProjectAnugaPackageResponse,
  DamProjectAnugaCapabilitiesResponse,
  DamProjectAnugaRunResponse,
  DamProjectAnugaResultsResponse,
  DamProjectAnugaPointValueResponse,
  DamProjectSummary,
  DamProjectDetailResponse,
  DamProjectReadinessResponse,
  HeuristicAssistResponse,
} from '../../types/damProjects'
import {
  runAnugaPreflight,
  buildAnugaPackage,
  getAnugaPackageDownloadUrl,
  fetchDamProjectAnugaCapabilities,
  executeDamProjectAnugaRun,
  fetchDamProjectAnugaRuns,
  fetchDamProjectAnugaRunLogs,
  postprocessDamProjectAnugaRun,
  fetchDamProjectAnugaResults,
  fetchDamProjectAnugaLayerLegend,
  fetchDamProjectAnugaLayerPointValue,
  fetchDamProjectReadiness,
  fetchTerrainHeuristicAssist,
  saveProjectSimulationInputs,
  cancelDamProjectAnugaRun,
} from '../../api/damProjects'

interface DamProjectAnugaReadinessProps {
  project: DamProjectSummary | DamProjectDetailResponse
  onPackageBuilt?: () => void
  onDisplayHazardLayer?: (projectId: string, runId: string, layer: string, processingId?: string) => void
}

export const DamProjectAnugaReadiness: React.FC<DamProjectAnugaReadinessProps> = ({
  project,
  onPackageBuilt,
  onDisplayHazardLayer,
}) => {
  const [runningPreflight, setRunningPreflight] = useState<boolean>(false)
  const [preflightResult, setPreflightResult] = useState<DamProjectAnugaPreflightResponse | null>(null)
  const [preflightError, setPreflightError] = useState<string | null>(null)

  const [buildingPackage, setBuildingPackage] = useState<boolean>(false)
  const [packageResult, setPackageResult] = useState<DamProjectAnugaPackageResponse | null>(null)
  const [packageError, setPackageError] = useState<string | null>(null)

  // Phase 19: 5-Tier Readiness State
  const [readiness, setReadiness] = useState<DamProjectReadinessResponse | null>(null)
  const [loadingReadiness, setLoadingReadiness] = useState<boolean>(false)

  // Phase 19: Heuristic Assist State
  const [showHeuristics, setShowHeuristics] = useState<boolean>(false)
  const [computingHeuristic, setComputingHeuristic] = useState<boolean>(false)
  const [heuristicResult, setHeuristicResult] = useState<HeuristicAssistResponse | null>(null)
  const [heuristicError, setHeuristicError] = useState<string | null>(null)
  const [ackHeuristic, setAckHeuristic] = useState<boolean>(false)
  const [applyingHeuristic, setApplyingHeuristic] = useState<boolean>(false)
  const [heuristicSuccess, setHeuristicSuccess] = useState<string | null>(null)

  // Phase 19: Simulation Configuration Inputs
  const [simDuration, setSimDuration] = useState<string>('3600')
  const [simInterval, setSimInterval] = useState<string>('60')
  const [simResolution, setSimResolution] = useState<string>('')
  const [cancellingRun, setCancellingRun] = useState<boolean>(false)

  // Execution state (Stage 3)
  const [capabilities, setCapabilities] = useState<DamProjectAnugaCapabilitiesResponse | null>(null)
  const [ackHypothetical, setAckHypothetical] = useState<boolean>(false)
  const [executingRun, setExecutingRun] = useState<boolean>(false)
  const [activeRun, setActiveRun] = useState<DamProjectAnugaRunResponse | null>(null)
  const [executionError, setExecutionError] = useState<string | null>(null)
  const [runLogs, setRunLogs] = useState<string | null>(null)
  const [showLogs, setShowLogs] = useState<boolean>(false)
  const pollingTimerRef = useRef<number | null>(null)

  // Postprocessing & Results state (Stage 4)
  const [dryDepthThreshold, setDryDepthThreshold] = useState<number>(0.005)
  const [arrivalDepthThreshold, setArrivalDepthThreshold] = useState<number>(0.05)
  const [postprocessing, setPostprocessing] = useState<boolean>(false)
  const [postprocessError, setPostprocessError] = useState<string | null>(null)
  const [results, setResults] = useState<DamProjectAnugaResultsResponse | null>(null)
  const [selectedLayer, setSelectedLayer] = useState<'maximum_depth' | 'maximum_velocity' | 'arrival_time'>('maximum_depth')
  const [legend, setLegend] = useState<any | null>(null)
  const [pointLon, setPointLon] = useState<string>('')
  const [pointLat, setPointLat] = useState<string>('')
  const [pointResult, setPointResult] = useState<DamProjectAnugaPointValueResponse | null>(null)
  const [queryingPoint, setQueryingPoint] = useState<boolean>(false)
  const [pointError, setPointError] = useState<string | null>(null)
  const [showManifestDetails, setShowManifestDetails] = useState<boolean>(false)

  const refreshReadiness = async () => {
    setLoadingReadiness(true)
    try {
      const res = await fetchDamProjectReadiness(project.project_id)
      setReadiness(res)
    } catch {
      // ignore
    } finally {
      setLoadingReadiness(false)
    }
  }

  useEffect(() => {
    fetchDamProjectAnugaCapabilities(project.project_id)
      .then(caps => setCapabilities(caps))
      .catch(() => setCapabilities(null))

    fetchDamProjectReadiness(project.project_id)
      .then(r => setReadiness(r))
      .catch(() => setReadiness(null))

    fetchDamProjectAnugaRuns(project.project_id)
      .then(runs => {
        if (runs && runs.length > 0) {
          setActiveRun(runs[0])
          if (runs[0].has_results) {
            fetchDamProjectAnugaResults(project.project_id, runs[0].run_id)
              .then(res => setResults(res))
              .catch(() => {})
          }
        }
      })
      .catch(() => {})

    return () => {
      if (pollingTimerRef.current) {
        clearInterval(pollingTimerRef.current)
      }
    }
  }, [project.project_id])

  useEffect(() => {
    const isRunning = activeRun && (
      activeRun.status === 'queued' ||
      activeRun.status === 'preparing' ||
      activeRun.status === 'running' ||
      activeRun.status === 'postprocessing'
    )
    if (isRunning) {
      if (!pollingTimerRef.current) {
        pollingTimerRef.current = window.setInterval(async () => {
          try {
            const updated = await fetchDamProjectAnugaRuns(project.project_id)
            if (updated && updated.length > 0) {
              setActiveRun(updated[0])
              const stillRunning = (
                updated[0].status === 'queued' ||
                updated[0].status === 'preparing' ||
                updated[0].status === 'running' ||
                updated[0].status === 'postprocessing'
              )
              if (!stillRunning) {
                if (pollingTimerRef.current) {
                  clearInterval(pollingTimerRef.current)
                  pollingTimerRef.current = null
                }
                if (updated[0].has_results) {
                  fetchDamProjectAnugaResults(project.project_id, updated[0].run_id)
                    .then(res => setResults(res))
                    .catch(() => {})
                }
              }
            }
          } catch {
            // silent polling catch
          }
        }, 3000)
      }
    } else {
      if (pollingTimerRef.current) {
        clearInterval(pollingTimerRef.current)
        pollingTimerRef.current = null
      }
    }
  }, [activeRun, project.project_id])

  useEffect(() => {
    if (activeRun && results) {
      fetchDamProjectAnugaLayerLegend(project.project_id, activeRun.run_id, selectedLayer)
        .then(leg => setLegend(leg))
        .catch(() => setLegend(null))
    }
  }, [activeRun, results, selectedLayer, project.project_id])

  const handleRunPreflight = async () => {
    setRunningPreflight(true)
    setPreflightError(null)
    setPreflightResult(null)
    setPackageError(null)
    try {
      const res = await runAnugaPreflight(project.project_id)
      setPreflightResult(res)
    } catch (err: any) {
      setPreflightError(err.message || 'Preflight assessment failed.')
    } finally {
      setRunningPreflight(false)
    }
  }

  const handleBuildPackage = async () => {
    if (!preflightResult || !preflightResult.preflight_passed) return
    setBuildingPackage(true)
    setPackageError(null)
    setPackageResult(null)
    try {
      const res = await buildAnugaPackage(project.project_id)
      setPackageResult(res)
      if (onPackageBuilt) {
        onPackageBuilt()
      }
    } catch (err: any) {
      setPackageError(err.message || 'Failed to generate ANUGA package.')
    } finally {
      setBuildingPackage(false)
    }
  }

  const handleComputeHeuristic = async () => {
    setComputingHeuristic(true)
    setHeuristicError(null)
    setHeuristicResult(null)
    setHeuristicSuccess(null)
    try {
      const res = await fetchTerrainHeuristicAssist(project.project_id)
      setHeuristicResult(res)
    } catch (err: any) {
      setHeuristicError(err.message || 'Heuristic assist calculation failed.')
    } finally {
      setComputingHeuristic(false)
    }
  }

  const handleApplyHeuristic = async () => {
    if (!heuristicResult || !ackHeuristic) return
    setApplyingHeuristic(true)
    setHeuristicError(null)
    try {
      await saveProjectSimulationInputs(project.project_id, {
        dam_axis_geometry: heuristicResult.suggested_dam_axis,
        reservoir_geometry: heuristicResult.suggested_reservoir_boundary,
        model_domain_geometry: heuristicResult.suggested_model_domain,
        downstream_outlet_geometry: heuristicResult.suggested_outlet_boundary,
        dam_crest_elevation: heuristicResult.estimated_crest_elevation,
        accept_heuristic_inputs: true,
      })
      setHeuristicSuccess('✅ Heuristic geometries applied to project inputs. Readiness re-evaluated.')
      await refreshReadiness()
    } catch (err: any) {
      setHeuristicError(err.message || 'Failed to apply heuristic inputs.')
    } finally {
      setApplyingHeuristic(false)
    }
  }

  const handleCancelRun = async () => {
    if (!activeRun) return
    setCancellingRun(true)
    try {
      const res = await cancelDamProjectAnugaRun(project.project_id, activeRun.run_id)
      setActiveRun(res)
    } catch (err: any) {
      setExecutionError(err.message || 'Failed to cancel simulation run.')
    } finally {
      setCancellingRun(false)
    }
  }

  const handleExecuteRun = async () => {
    if (!ackHypothetical) return
    setExecutingRun(true)
    setExecutionError(null)
    try {
      const res = await executeDamProjectAnugaRun(project.project_id, {
        acknowledge_hypothetical_unverified: true,
        simulation_duration_s: simDuration ? parseFloat(simDuration) : undefined,
        output_interval_s: simInterval ? parseFloat(simInterval) : undefined,
        target_mesh_resolution_m: simResolution ? parseFloat(simResolution) : undefined,
      })
      setActiveRun(res)
    } catch (err: any) {
      setExecutionError(err.message || 'Simulation run failed to start.')
    } finally {
      setExecutingRun(false)
    }
  }

  const handleToggleLogs = async () => {
    if (!showLogs && activeRun) {
      try {
        const text = await fetchDamProjectAnugaRunLogs(project.project_id, activeRun.run_id)
        setRunLogs(text)
      } catch (err: any) {
        setRunLogs(err.message || 'Failed to load logs.')
      }
    }
    setShowLogs(!showLogs)
  }

  const handlePostprocess = async () => {
    if (!activeRun || activeRun.status !== 'completed') return
    setPostprocessing(true)
    setPostprocessError(null)
    try {
      const res = await postprocessDamProjectAnugaRun(project.project_id, activeRun.run_id, {
        dry_depth_threshold_m: dryDepthThreshold,
        arrival_depth_threshold_m: arrivalDepthThreshold,
      })
      setResults(res)
    } catch (err: any) {
      setPostprocessError(err.message || 'Postprocessing failed.')
    } finally {
      setPostprocessing(false)
    }
  }

  const handleQueryPoint = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!activeRun || !results) return
    const lonNum = parseFloat(pointLon)
    const latNum = parseFloat(pointLat)
    if (isNaN(lonNum) || isNaN(latNum)) {
      setPointError('Please enter valid numeric longitude and latitude coordinates.')
      return
    }
    setQueryingPoint(true)
    setPointError(null)
    setPointResult(null)
    try {
      const res = await fetchDamProjectAnugaLayerPointValue(
        project.project_id,
        activeRun.run_id,
        selectedLayer,
        lonNum,
        latNum,
      )
      setPointResult(res)
    } catch (err: any) {
      setPointError(err.message || 'Point query failed.')
    } finally {
      setQueryingPoint(false)
    }
  }

  const isCorrupted =
    ('available' in project && !project.available) ||
    ('integrity_status' in project && project.integrity_status === 'integrity_failed') ||
    project.status === 'integrity_failed'

  const hasBuiltPackage = Boolean(
    packageResult ||
    ('anuga_package_built' in project && project.anuga_package_built)
  )

  return (
    <div className="simulation-readiness-container">
      <div className="readiness-header">
        <h5>⚡ ANUGA Simulation Readiness & Package</h5>
        <span className="legend-tag">HYPOTHETICAL UNVERIFIED</span>
      </div>

      <p className="readiness-intro">
        Assess spatial boundaries, physical water heads, and numerical mesh readiness before generating a reproducible ANUGA package.
      </p>

      {/* 5-Tier Simulation Readiness Badges */}
      <div className="preflight-report-card" style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
          <strong style={{ fontSize: '0.85rem' }}>📊 5-Tier Simulation Readiness</strong>
          <button
            type="button"
            onClick={refreshReadiness}
            disabled={loadingReadiness}
            style={{ background: 'none', border: 'none', color: '#38bdf8', fontSize: '0.72rem', cursor: 'pointer' }}
          >
            {loadingReadiness ? 'Refreshing...' : '🔄 Refresh Readiness'}
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '0.4rem', fontSize: '0.72rem' }}>
          <div style={{ background: '#0f172a', padding: '0.4rem', borderRadius: '4px', borderLeft: `3px solid ${readiness?.data_ready ? '#10b981' : '#f59e0b'}` }}>
            <div style={{ color: '#94a3b8' }}>Tier 1: Data</div>
            <div style={{ fontWeight: 600, color: readiness?.data_ready ? '#10b981' : '#f59e0b' }}>
              {readiness?.data_ready ? '✅ Complete' : '⚠️ Missing'}
            </div>
          </div>
          <div style={{ background: '#0f172a', padding: '0.4rem', borderRadius: '4px', borderLeft: `3px solid ${readiness?.geometry_ready ? '#10b981' : '#f59e0b'}` }}>
            <div style={{ color: '#94a3b8' }}>Tier 2: Geometry</div>
            <div style={{ fontWeight: 600, color: readiness?.geometry_ready ? '#10b981' : '#f59e0b' }}>
              {readiness?.geometry_ready ? '✅ Defined' : '⚠️ Incomplete'}
            </div>
          </div>
          <div style={{ background: '#0f172a', padding: '0.4rem', borderRadius: '4px', borderLeft: `3px solid ${readiness?.hydraulic_ready ? '#10b981' : '#f59e0b'}` }}>
            <div style={{ color: '#94a3b8' }}>Tier 3: Hydraulic</div>
            <div style={{ fontWeight: 600, color: readiness?.hydraulic_ready ? '#10b981' : '#f59e0b' }}>
              {readiness?.hydraulic_ready ? '✅ Parameters Set' : '⚠️ Missing'}
            </div>
          </div>
          <div style={{ background: '#0f172a', padding: '0.4rem', borderRadius: '4px', borderLeft: `3px solid ${readiness?.solver_ready ? '#10b981' : '#ef4444'}` }}>
            <div style={{ color: '#94a3b8' }}>Tier 4: Solver</div>
            <div style={{ fontWeight: 600, color: readiness?.solver_ready ? '#10b981' : '#ef4444' }}>
              {readiness?.solver_ready ? '✅ Installed' : '❌ Unavailable'}
            </div>
          </div>
          <div style={{ background: '#0f172a', padding: '0.4rem', borderRadius: '4px', borderLeft: `3px solid ${readiness?.simulation_ready ? '#10b981' : '#64748b'}` }}>
            <div style={{ color: '#94a3b8' }}>Tier 5: Simulation</div>
            <div style={{ fontWeight: 600, color: readiness?.simulation_ready ? '#10b981' : '#94a3b8' }}>
              {readiness?.simulation_ready ? '🚀 Ready' : '⏳ Gated'}
            </div>
          </div>
        </div>

        {readiness && readiness.missing_requirements && readiness.missing_requirements.length > 0 && (
          <div style={{ marginTop: '0.5rem', fontSize: '0.72rem', color: '#f59e0b' }}>
            <span>Pending Requirements: </span>
            <span className="font-mono">{readiness.missing_requirements.join(', ')}</span>
          </div>
        )}
      </div>

      {/* Terrain Heuristic Assist Panel */}
      <div className="preflight-report-card" style={{ marginBottom: '1rem', background: '#1e293b' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <strong style={{ fontSize: '0.85rem' }}>🧭 Terrain-Heuristic Hydraulic Assist</strong>
            <span className="legend-tag status-tag-unverified" style={{ marginLeft: '0.5rem' }}>HEURISTIC UNVERIFIED</span>
          </div>
          <button
            type="button"
            onClick={() => setShowHeuristics(!showHeuristics)}
            style={{ background: 'none', border: 'none', color: '#38bdf8', fontSize: '0.72rem', cursor: 'pointer' }}
          >
            {showHeuristics ? 'Collapse' : 'Expand Assist'}
          </button>
        </div>

        {showHeuristics && (
          <div style={{ marginTop: '0.6rem' }}>
            <p style={{ fontSize: '0.74rem', color: '#94a3b8', margin: '0 0 0.5rem 0' }}>
              Synthesizes candidate dam axis, breach alignment, downstream model domain corridor, and reservoir polygon from DEM slope aspect analysis.
            </p>

            <button
              type="button"
              className="btn-preflight"
              onClick={handleComputeHeuristic}
              disabled={computingHeuristic}
              style={{ padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}
            >
              {computingHeuristic ? 'Analyzing DEM Slope Gradient...' : '🔍 Analyze DEM & Derive Candidate Geometries'}
            </button>

            {heuristicError && (
              <div className="damage-error-box font-mono" style={{ marginTop: '0.4rem' }}>
                ⛔ {heuristicError}
              </div>
            )}

            {heuristicSuccess && (
              <div className="val-status-banner success" style={{ marginTop: '0.4rem', fontSize: '0.75rem' }}>
                {heuristicSuccess}
              </div>
            )}

            {heuristicResult && (
              <div style={{ marginTop: '0.6rem', background: '#0f172a', padding: '0.6rem', borderRadius: '4px' }}>
                <div className="val-disclaimer-box font-mono" style={{ fontSize: '0.7rem', margin: '0 0 0.5rem 0', borderColor: '#f59e0b', color: '#fbbf24' }}>
                  ⚠️ <strong>SCIENTIFIC CAVEAT:</strong> {heuristicResult.caveats.join(' ')}
                </div>

                <div className="val-metadata-grid font-mono" style={{ fontSize: '0.72rem' }}>
                  <div className="val-meta-item">
                    <span className="val-meta-label">Downstream Bearing</span>
                    <span className="val-meta-value">{heuristicResult.downstream_bearing_deg}° ({heuristicResult.downstream_direction})</span>
                  </div>
                  <div className="val-meta-item">
                    <span className="val-meta-label">Slope Gradient</span>
                    <span className="val-meta-value">{(heuristicResult.slope_gradient * 100).toFixed(2)}%</span>
                  </div>
                  <div className="val-meta-item">
                    <span className="val-meta-label">Dam Point Elevation</span>
                    <span className="val-meta-value">{heuristicResult.dam_point_elevation != null ? `${heuristicResult.dam_point_elevation.toFixed(1)} m` : 'N/A'}</span>
                  </div>
                  <div className="val-meta-item">
                    <span className="val-meta-label">Estimated Crest</span>
                    <span className="val-meta-value">{heuristicResult.estimated_crest_elevation != null ? `${heuristicResult.estimated_crest_elevation.toFixed(1)} m` : 'N/A'}</span>
                  </div>
                </div>

                <div style={{ marginTop: '0.6rem' }}>
                  <label style={{ display: 'flex', alignItems: 'flex-start', gap: '0.4rem', fontSize: '0.75rem', cursor: 'pointer', color: '#fbbf24' }}>
                    <input
                      type="checkbox"
                      checked={ackHeuristic}
                      onChange={e => setAckHeuristic(e.target.checked)}
                      style={{ marginTop: '2px' }}
                    />
                    <span>
                      I confirm and accept using these terrain-derived heuristic inputs for simulation setup (scientifically unverified).
                    </span>
                  </label>
                </div>

                <div style={{ marginTop: '0.5rem' }}>
                  <button
                    type="button"
                    className="btn-build-package"
                    onClick={handleApplyHeuristic}
                    disabled={!ackHeuristic || applyingHeuristic}
                    style={{
                      padding: '0.3rem 0.7rem',
                      fontSize: '0.75rem',
                      backgroundColor: ackHeuristic ? '#0284c7' : '#475569',
                    }}
                  >
                    {applyingHeuristic ? 'Applying Geometries...' : '💾 Apply Heuristics to Project Inputs'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="readiness-actions-row">
        <button
          className="btn-preflight"
          onClick={handleRunPreflight}
          disabled={runningPreflight || isCorrupted}
        >
          {runningPreflight ? (
            <>
              <span className="spinner" /> Assessing Readiness...
            </>
          ) : (
            '🔍 Assess Simulation Readiness (Preflight)'
          )}
        </button>
      </div>

      {preflightError && (
        <div className="damage-error-box font-mono" style={{ marginTop: '0.5rem' }}>
          ⛔ {preflightError}
        </div>
      )}

      {preflightResult && (
        <div className="preflight-report-card">
          <div className={`val-status-banner ${preflightResult.preflight_passed ? 'success' : 'failure'}`}>
            <span>
              {preflightResult.preflight_passed
                ? '✅ Simulation Preflight Passed — Ready for Package Generation'
                : '❌ Simulation Blocked — Missing / Inconsistent Hydraulic Inputs'}
            </span>
            <span className="legend-tag">{preflightResult.scientific_status}</span>
          </div>

          {/* Blockers */}
          {preflightResult.blockers.length > 0 && (
            <div className="preflight-blockers-box">
              <span className="note-title text-danger">⚠️ Blockers (Must resolve before package build):</span>
              <ul className="val-errors-list font-mono">
                {preflightResult.blockers.map((b, idx) => (
                  <li key={idx}>{b}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Warnings */}
          {preflightResult.warnings.length > 0 && (
            <div className="preflight-warnings-box">
              <span className="note-title text-warning">Warnings & Limitations:</span>
              <ul className="val-warnings-list font-mono">
                {preflightResult.warnings.map((w, idx) => (
                  <li key={idx}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Proposed Configuration & Derived Checks */}
          <div className="val-metadata-grid" style={{ marginTop: '0.5rem' }}>
            <div className="val-meta-item">
              <span className="val-meta-label">Target Mesh Resolution</span>
              <span className="val-meta-value">
                {preflightResult.proposed_configuration.target_mesh_resolution_m != null
                  ? `${preflightResult.proposed_configuration.target_mesh_resolution_m} m`
                  : 'Not specified'}
              </span>
            </div>
            <div className="val-meta-item">
              <span className="val-meta-label">Simulation Time</span>
              <span className="val-meta-value">
                {preflightResult.proposed_configuration.simulation_duration_s != null
                  ? `${preflightResult.proposed_configuration.simulation_duration_s} s (step: ${preflightResult.proposed_configuration.output_interval_s} s)`
                  : 'Not specified'}
              </span>
            </div>
            <div className="val-meta-item">
              <span className="val-meta-label">Estimated Elements</span>
              <span className="val-meta-value">
                {preflightResult.derived_checks.estimated_mesh_triangles != null
                  ? `~${preflightResult.derived_checks.estimated_mesh_triangles.toLocaleString()} triangles`
                  : 'N/A'}
              </span>
            </div>
            <div className="val-meta-item">
              <span className="val-meta-label">Domain Area</span>
              <span className="val-meta-value">
                {preflightResult.derived_checks.model_domain_area_km2 != null
                  ? `${preflightResult.derived_checks.model_domain_area_km2.toFixed(2)} km²`
                  : 'N/A'}
              </span>
            </div>
            <div className="val-meta-item">
              <span className="val-meta-label">Hydraulic Head above Invert</span>
              <span className="val-meta-value">
                {preflightResult.derived_checks.water_head_above_invert_m != null
                  ? `${preflightResult.derived_checks.water_head_above_invert_m.toFixed(2)} m`
                  : 'N/A'}
              </span>
            </div>
            <div className="val-meta-item">
              <span className="val-meta-label">Crest Freeboard</span>
              <span className="val-meta-value">
                {preflightResult.derived_checks.freeboard_m != null
                  ? `${preflightResult.derived_checks.freeboard_m.toFixed(2)} m`
                  : 'N/A'}
              </span>
            </div>
          </div>

          {/* Build Package Button */}
          <div style={{ marginTop: '0.8rem', display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <button
              className="btn-build-package"
              onClick={handleBuildPackage}
              disabled={buildingPackage || !preflightResult.preflight_passed}
              title={
                !preflightResult.preflight_passed
                  ? 'Resolve all preflight blockers before generating package'
                  : 'Build standalone reproducible ANUGA package ZIP'
              }
            >
              {buildingPackage ? (
                <>
                  <span className="spinner" /> Bundling ANUGA Package...
                </>
              ) : (
                '📦 Build ANUGA Package'
              )}
            </button>
            {!preflightResult.preflight_passed && (
              <span className="package-blocked-hint font-mono">
                🔒 Package generation locked until preflight passes.
              </span>
            )}
          </div>
        </div>
      )}

      {packageError && (
        <div className="damage-error-box font-mono" style={{ marginTop: '0.5rem' }}>
          ⛔ {packageError}
        </div>
      )}

      {packageResult && (
        <div className="package-success-card">
          <div className="package-banner-success">
            <span>✅ Package generated; simulation has not been executed.</span>
          </div>

          <div className="val-disclaimer-box" style={{ margin: '0.4rem 0' }}>
            <strong>DISCLAIMER:</strong> This package contains runnable model definitions for an instantaneous hypothetical dam-break. Results from running this script represent uncalibrated simulations and are never labeled as forecasts or certified predictions.
          </div>

          <div className="val-metadata-grid font-mono" style={{ fontSize: '0.72rem' }}>
            <div className="val-meta-item">
              <span className="val-meta-label">ZIP Archive</span>
              <span className="val-meta-value">{packageResult.package_filename} ({(packageResult.package_size_bytes / 1024).toFixed(1)} KB)</span>
            </div>
            <div className="val-meta-item">
              <span className="val-meta-label">SHA-256</span>
              <span className="val-meta-value">{packageResult.package_sha256 ? `${packageResult.package_sha256.slice(0, 16)}...` : 'N/A'}</span>
            </div>
            <div className="val-meta-item" style={{ gridColumn: 'span 2' }}>
              <span className="val-meta-label">Files Bundled</span>
              <span className="val-meta-value">{packageResult.files_included.join(', ')}</span>
            </div>
          </div>

          <div style={{ marginTop: '0.6rem' }}>
            <a
              href={getAnugaPackageDownloadUrl(project.project_id)}
              download={`dam_project_${project.project_id.slice(0, 8)}_anuga_package.zip`}
              className="btn-download-package"
            >
              ⬇️ Download ANUGA Package (.zip)
            </a>
          </div>
        </div>
      )}

      {/* Gated ANUGA Execution Section (Stage 3) */}
      <div className="anuga-execution-section" style={{ marginTop: '1.2rem', borderTop: '1px solid #334155', paddingTop: '0.8rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
          <h6 style={{ margin: 0, fontSize: '0.88rem', fontWeight: 600 }}>🚀 Server Simulation Execution</h6>
          {capabilities && (
            <span
              className={`legend-tag ${capabilities.execution_enabled ? 'status-tag-valid' : 'status-tag-unverified'}`}
              style={{ fontSize: '0.68rem' }}
            >
              {capabilities.execution_enabled ? 'EXECUTION ENABLED' : 'EXECUTION GATED'}
            </span>
          )}
        </div>

        <div className="val-disclaimer-box font-mono" style={{ fontSize: '0.72rem', margin: '0.4rem 0' }}>
          ⚠️ <strong>HYPOTHETICAL UNVERIFIED SIMULATION:</strong> Running this simulation computes numerical hydrodynamic dam-break scenarios based on user-declared parameters. It has not been field-calibrated or scientifically certified.
        </div>

        {capabilities && !capabilities.execution_enabled && (
          <div className="preflight-blockers-box font-mono" style={{ fontSize: '0.75rem', margin: '0.4rem 0' }}>
            🔒 <strong>Execution Disabled:</strong> {capabilities.reason || 'Server execution policy disabled.'}
          </div>
        )}

        <div style={{ marginTop: '0.6rem' }}>
          <label style={{ display: 'flex', alignItems: 'flex-start', gap: '0.4rem', fontSize: '0.78rem', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={ackHypothetical}
              onChange={e => setAckHypothetical(e.target.checked)}
              disabled={isCorrupted || !capabilities?.execution_enabled}
              style={{ marginTop: '2px' }}
            />
            <span>I acknowledge this is an uncalibrated hypothetical scenario and agree to proceed.</span>
          </label>
        </div>

        {/* Phase 19: Runtime Parameters */}
        <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap', margin: '0.5rem 0' }}>
          <label style={{ fontSize: '0.72rem', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
            Duration (s):
            <input
              type="number"
              value={simDuration}
              onChange={e => setSimDuration(e.target.value)}
              className="point-probe-input"
              style={{ width: '70px' }}
            />
          </label>
          <label style={{ fontSize: '0.72rem', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
            Interval (s):
            <input
              type="number"
              value={simInterval}
              onChange={e => setSimInterval(e.target.value)}
              className="point-probe-input"
              style={{ width: '60px' }}
            />
          </label>
          <label style={{ fontSize: '0.72rem', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
            Target Res (m):
            <input
              type="number"
              value={simResolution}
              placeholder="auto"
              onChange={e => setSimResolution(e.target.value)}
              className="point-probe-input"
              style={{ width: '60px' }}
            />
          </label>
        </div>

        <div style={{ marginTop: '0.6rem', display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <button
            className="btn-build-package"
            onClick={handleExecuteRun}
            disabled={
              executingRun ||
              !ackHypothetical ||
              !hasBuiltPackage ||
              !capabilities?.execution_enabled ||
              (activeRun != null && (activeRun.status === 'queued' || activeRun.status === 'running'))
            }
            style={{
              backgroundColor:
                !ackHypothetical || !hasBuiltPackage || !capabilities?.execution_enabled
                  ? '#475569'
                  : '#2563eb',
            }}
          >
            {executingRun || (activeRun && (activeRun.status === 'queued' || activeRun.status === 'running')) ? (
              <>
                <span className="spinner" /> Running ANUGA ({activeRun?.status || 'executing'})...
              </>
            ) : (
              '▶️ Run ANUGA Simulation'
            )}
          </button>

          {!hasBuiltPackage && (
            <span className="package-blocked-hint font-mono" style={{ fontSize: '0.72rem' }}>
              Build package first before running.
            </span>
          )}
        </div>

        {executionError && (
          <div className="damage-error-box font-mono" style={{ marginTop: '0.5rem' }}>
            ⛔ {executionError}
          </div>
        )}

        {/* Active / Latest Run Status */}
        {activeRun && (
          <div className="preflight-report-card" style={{ marginTop: '0.8rem' }}>
            <div className={`val-status-banner ${activeRun.status === 'completed' ? 'success' : activeRun.status === 'failed' || activeRun.status === 'timed_out' || activeRun.status === 'interrupted' || activeRun.status === 'cancelled' ? 'failure' : 'running'}`}>
              <span>
                {activeRun.status === 'completed' && '✅ Simulation Completed Successfully'}
                {activeRun.status === 'failed' && '❌ Simulation Failed'}
                {activeRun.status === 'cancelled' && '🛑 Simulation Cancelled by User'}
                {activeRun.status === 'timed_out' && '⏱️ Simulation Timed Out'}
                {activeRun.status === 'interrupted' && '⚠️ Simulation Interrupted (Server restart / terminated)'}
                {activeRun.status === 'running' && '⏳ Simulation Running in Background...'}
                {activeRun.status === 'preparing' && '⚙️ Preparing Simulation Runtime Workspace...'}
                {activeRun.status === 'postprocessing' && '⚡ Automatic Postprocessing in Progress...'}
                {activeRun.status === 'queued' && '🕒 Simulation Queued in Worker...'}
              </span>
              <span className="legend-tag">{activeRun.status.toUpperCase()}</span>
            </div>

            <div className="val-metadata-grid font-mono" style={{ fontSize: '0.72rem', marginTop: '0.4rem' }}>
              <div className="val-meta-item">
                <span className="val-meta-label">Run ID</span>
                <span className="val-meta-value">{activeRun.run_id.slice(0, 8)}...</span>
              </div>
              <div className="val-meta-item">
                <span className="val-meta-label">Exit Code</span>
                <span className="val-meta-value">{activeRun.exit_code != null ? activeRun.exit_code : 'Running'}</span>
              </div>
              <div className="val-meta-item">
                <span className="val-meta-label">Runtime</span>
                <span className="val-meta-value">{activeRun.runtime_seconds != null ? `${activeRun.runtime_seconds} s` : 'In progress'}</span>
              </div>
              <div className="val-meta-item">
                <span className="val-meta-label">ANUGA Version</span>
                <span className="val-meta-value">{activeRun.anuga_version || 'N/A'}</span>
              </div>
              <div className="val-meta-item" style={{ gridColumn: 'span 2' }}>
                <span className="val-meta-label">Status Message</span>
                <span className="val-meta-value">{activeRun.message}</span>
              </div>
            </div>

            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <button
                type="button"
                className="btn-preflight"
                onClick={handleToggleLogs}
                style={{ padding: '0.25rem 0.5rem', fontSize: '0.72rem' }}
              >
                {showLogs ? 'Hide Logs' : '📄 View Sanitized Execution Logs'}
              </button>

              {activeRun && (activeRun.status === 'queued' || activeRun.status === 'preparing' || activeRun.status === 'running' || activeRun.status === 'postprocessing') && (
                <button
                  type="button"
                  className="btn-preflight"
                  onClick={handleCancelRun}
                  disabled={cancellingRun}
                  style={{ padding: '0.25rem 0.5rem', fontSize: '0.72rem', color: '#ef4444', borderColor: '#ef4444' }}
                >
                  {cancellingRun ? 'Cancelling...' : '🛑 Cancel Simulation Run'}
                </button>
              )}
            </div>

            {showLogs && (
              <pre className="font-mono" style={{ maxHeight: '180px', overflowY: 'auto', background: '#0f172a', padding: '0.5rem', borderRadius: '4px', fontSize: '0.7rem', color: '#94a3b8', marginTop: '0.4rem', whiteSpace: 'pre-wrap' }}>
                {runLogs || 'Loading logs...'}
              </pre>
            )}

            {/* Stage 4: Postprocessing & Results */}
            {activeRun.status === 'completed' && (
              <div style={{ marginTop: '0.8rem', borderTop: '1px dashed #334155', paddingTop: '0.6rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#38bdf8' }}>
                    ⚡ SWW Hydrodynamic Postprocessing
                  </span>
                </div>

                <div style={{ display: 'flex', gap: '0.8rem', alignItems: 'center', marginTop: '0.4rem', flexWrap: 'wrap' }}>
                  <label style={{ fontSize: '0.72rem', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                    Dry Depth (m):
                    <input
                      type="number"
                      step="0.001"
                      min="0.001"
                      value={dryDepthThreshold}
                      onChange={e => setDryDepthThreshold(parseFloat(e.target.value) || 0.005)}
                      className="point-probe-input"
                      style={{ width: '65px' }}
                    />
                  </label>

                  <label style={{ fontSize: '0.72rem', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                    Arrival Depth (m):
                    <input
                      type="number"
                      step="0.01"
                      min="0.001"
                      value={arrivalDepthThreshold}
                      onChange={e => setArrivalDepthThreshold(parseFloat(e.target.value) || 0.05)}
                      className="point-probe-input"
                      style={{ width: '65px' }}
                    />
                  </label>

                  <button
                    type="button"
                    className="btn-postprocess-trigger"
                    onClick={handlePostprocess}
                    disabled={postprocessing}
                  >
                    {postprocessing ? (
                      <>
                        <span className="spinner" /> Postprocessing Mesh & Timesteps...
                      </>
                    ) : (
                      '⚡ Generate Hazard Rasters (GeoTIFFs)'
                    )}
                  </button>
                </div>

                {postprocessError && (
                  <div className="damage-error-box font-mono" style={{ marginTop: '0.4rem' }}>
                    ⛔ {postprocessError}
                  </div>
                )}

                {/* Results Section */}
                {results && (
                  <div className="results-card">
                    <div className="results-header">
                      <h6>🗺️ Hydrodynamic Hazard Maps (GeoTIFFs)</h6>
                      <span className="legend-tag status-tag-unverified">HYPOTHETICAL UNVERIFIED</span>
                    </div>

                    <div className="val-disclaimer-box font-mono" style={{ fontSize: '0.68rem', margin: '0.2rem 0' }}>
                      ⚠️ <strong>SCIENTIFIC DISCLAIMER:</strong> These hazard rasters were generated by postprocessing an uncalibrated 2D shallow water equation model with zero-extrapolation mesh masking. They represent hypothetical scenarios and are not certified predictions.
                    </div>

                    {/* Layer Switcher */}
                    <div className="layer-switcher-row" style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', alignItems: 'center' }}>
                      <button
                        type="button"
                        className={`btn-layer-tab ${selectedLayer === 'maximum_depth' ? 'active' : ''}`}
                        onClick={() => {
                          setSelectedLayer('maximum_depth')
                          if (onDisplayHazardLayer && activeRun) {
                            onDisplayHazardLayer(project.project_id, activeRun.run_id, 'maximum_depth', results.processing_id)
                          }
                        }}
                      >
                        🌊 Maximum Depth (m)
                      </button>
                      <button
                        type="button"
                        className={`btn-layer-tab ${selectedLayer === 'maximum_velocity' ? 'active' : ''}`}
                        onClick={() => {
                          setSelectedLayer('maximum_velocity')
                          if (onDisplayHazardLayer && activeRun) {
                            onDisplayHazardLayer(project.project_id, activeRun.run_id, 'maximum_velocity', results.processing_id)
                          }
                        }}
                      >
                        💨 Maximum Velocity (m/s)
                      </button>
                      <button
                        type="button"
                        className={`btn-layer-tab ${selectedLayer === 'arrival_time' ? 'active' : ''}`}
                        onClick={() => {
                          setSelectedLayer('arrival_time')
                          if (onDisplayHazardLayer && activeRun) {
                            onDisplayHazardLayer(project.project_id, activeRun.run_id, 'arrival_time', results.processing_id)
                          }
                        }}
                      >
                        ⏱️ Flood Arrival Time (s)
                      </button>
                      {onDisplayHazardLayer && (
                        <button
                          type="button"
                          className="btn-project-action"
                          onClick={() => {
                            if (activeRun) {
                              onDisplayHazardLayer(project.project_id, activeRun.run_id, selectedLayer, results.processing_id)
                            }
                          }}
                          style={{ marginLeft: 'auto', background: '#0284c7', color: '#ffffff', borderColor: '#38bdf8' }}
                          title="Render active hazard raster tiles onto MapLibre map"
                        >
                          🗺️ Render on Map
                        </button>
                      )}
                    </div>

                    {/* Active Layer Statistics */}
                    {results.layer_statistics[selectedLayer] && (
                      <div className="layer-stats-grid font-mono" style={{ fontSize: '0.7rem' }}>
                        <div className="val-meta-item">
                          <span className="val-meta-label">Min</span>
                          <span className="val-meta-value">
                            {results.layer_statistics[selectedLayer].min != null
                              ? `${results.layer_statistics[selectedLayer].min?.toFixed(3)} ${results.layer_statistics[selectedLayer].unit}`
                              : 'N/A'}
                          </span>
                        </div>
                        <div className="val-meta-item">
                          <span className="val-meta-label">Max</span>
                          <span className="val-meta-value">
                            {results.layer_statistics[selectedLayer].max != null
                              ? `${results.layer_statistics[selectedLayer].max?.toFixed(3)} ${results.layer_statistics[selectedLayer].unit}`
                              : 'N/A'}
                          </span>
                        </div>
                        <div className="val-meta-item">
                          <span className="val-meta-label">Mean</span>
                          <span className="val-meta-value">
                            {results.layer_statistics[selectedLayer].mean != null
                              ? `${results.layer_statistics[selectedLayer].mean?.toFixed(3)} ${results.layer_statistics[selectedLayer].unit}`
                              : 'N/A'}
                          </span>
                        </div>
                        <div className="val-meta-item">
                          <span className="val-meta-label">Valid Cells</span>
                          <span className="val-meta-value">
                            {results.layer_statistics[selectedLayer].valid_pixels?.toLocaleString() || '0'}
                          </span>
                        </div>
                        <div className="val-meta-item">
                          <span className="val-meta-label">NoData Cells</span>
                          <span className="val-meta-value">
                            {results.layer_statistics[selectedLayer].nodata_pixels?.toLocaleString() || '0'}
                          </span>
                        </div>
                      </div>
                    )}

                    {/* Legend */}
                    {legend && (
                      <div className="layer-legend-container">
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.68rem', fontWeight: 600, color: '#94a3b8' }}>
                          <span>{legend.label || 'Layer'} Legend</span>
                          <span>Unit: {results.layer_statistics[selectedLayer]?.unit || 'N/A'}</span>
                        </div>
                        <div
                          className="legend-bar-gradient"
                          style={{
                            background:
                              selectedLayer === 'maximum_depth'
                                ? 'linear-gradient(to right, rgba(224,242,254,0.3), #38bdf8, #0284c7, #1e3a8a)'
                                : selectedLayer === 'maximum_velocity'
                                ? 'linear-gradient(to right, rgba(254,243,199,0.3), #f59e0b, #ef4444, #7f1d1d)'
                                : 'linear-gradient(to right, #ef4444, #f59e0b, #3b82f6, #6366f1)',
                          }}
                        />
                        <div className="legend-labels-row">
                          <span>{legend.min_value?.toFixed(2)} {results.layer_statistics[selectedLayer]?.unit}</span>
                          <span>{legend.max_value?.toFixed(2)} {results.layer_statistics[selectedLayer]?.unit}</span>
                        </div>
                      </div>
                    )}

                    {/* Point Probe Query */}
                    <div className="point-probe-card">
                      <span style={{ fontSize: '0.74rem', fontWeight: 600, color: '#38bdf8' }}>
                        🎯 Point Value Probe ({selectedLayer.replace('_', ' ')})
                      </span>
                      <form onSubmit={handleQueryPoint} className="point-probe-inputs">
                        <input
                          type="text"
                          placeholder="Longitude (e.g. 74.65)"
                          value={pointLon}
                          onChange={e => setPointLon(e.target.value)}
                          className="point-probe-input"
                        />
                        <input
                          type="text"
                          placeholder="Latitude (e.g. 16.12)"
                          value={pointLat}
                          onChange={e => setPointLat(e.target.value)}
                          className="point-probe-input"
                        />
                        <button type="submit" className="btn-point-query" disabled={queryingPoint}>
                          {queryingPoint ? 'Querying...' : 'Query Point'}
                        </button>
                      </form>

                      {pointError && (
                        <div className="damage-error-box font-mono" style={{ fontSize: '0.68rem' }}>
                          ⛔ {pointError}
                        </div>
                      )}

                      {pointResult && (
                        <div className="val-meta-item font-mono" style={{ fontSize: '0.7rem', background: '#0f172a', padding: '0.4rem', borderRadius: '4px' }}>
                          <div>
                            <strong>Value:</strong>{' '}
                            {pointResult.value != null
                              ? `${pointResult.value.toFixed(4)} ${pointResult.unit}`
                              : 'NoData (Outside Mesh or Dry)'}
                          </div>
                          <div style={{ fontSize: '0.65rem', color: '#94a3b8', marginTop: '0.2rem' }}>
                            ℹ️ <em>{pointResult.disclaimer}</em>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Direct GeoTIFF Downloads */}
                    <div style={{ marginTop: '0.4rem' }}>
                      <span style={{ fontSize: '0.72rem', color: '#94a3b8', display: 'block', marginBottom: '0.3rem' }}>
                        📥 Download Raw GeoTIFFs:
                      </span>
                      <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                        {Object.entries(results.layer_files).map(([key, filename]) => (
                          <a
                            key={key}
                            href={`${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/api/dam-projects/${encodeURIComponent(project.project_id)}/anuga/runs/${encodeURIComponent(activeRun.run_id)}/results/${key}/download`}
                            download={filename}
                            className="btn-preflight"
                            style={{ padding: '0.25rem 0.55rem', fontSize: '0.7rem', textDecoration: 'none' }}
                          >
                            💾 {filename}
                          </a>
                        ))}
                      </div>
                    </div>

                    {/* Scientific Metadata & Manifest Details */}
                    <div style={{ marginTop: '0.4rem' }}>
                      <button
                        type="button"
                        onClick={() => setShowManifestDetails(!showManifestDetails)}
                        style={{ background: 'none', border: 'none', color: '#38bdf8', fontSize: '0.72rem', cursor: 'pointer', padding: 0, textDecoration: 'underline' }}
                      >
                        {showManifestDetails ? 'Hide Scientific Manifest & Method Details' : '📋 View Scientific Manifest & Method Details'}
                      </button>

                      {showManifestDetails && (
                        <div className="val-metadata-grid font-mono" style={{ fontSize: '0.68rem', marginTop: '0.4rem', background: '#0f172a', padding: '0.5rem', borderRadius: '4px' }}>
                          <div className="val-meta-item">
                            <span className="val-meta-label">Interpolation Method</span>
                            <span className="val-meta-value">{results.interpolation_method}</span>
                          </div>
                          <div className="val-meta-item">
                            <span className="val-meta-label">Mesh Boundary Mask</span>
                            <span className="val-meta-value">{results.mesh_mask_method}</span>
                          </div>
                          <div className="val-meta-item">
                            <span className="val-meta-label">Mass Balance Status</span>
                            <span className="val-meta-value">{results.mass_balance_status}</span>
                          </div>
                          <div className="val-meta-item">
                            <span className="val-meta-label">Raster CRS & Resolution</span>
                            <span className="val-meta-value">{results.raster_crs} ({results.raster_resolution_m} m)</span>
                          </div>
                          <div className="val-meta-item" style={{ gridColumn: 'span 2' }}>
                            <span className="val-meta-label">Source SWW SHA-256</span>
                            <span className="val-meta-value">{results.sww_sha256}</span>
                          </div>
                          <div className="val-meta-item" style={{ gridColumn: 'span 2' }}>
                            <span className="val-meta-label">Solver Version Provenance</span>
                            <span className="val-meta-value">
                              {JSON.stringify({
                                version: results.anuga_version,
                                source: results.version_source,
                                raw: results.raw_distribution_version,
                              })}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

import React, { useState, useEffect, useRef } from 'react'
import type {
  DamProjectAnugaPreflightResponse,
  DamProjectAnugaPackageResponse,
  DamProjectAnugaCapabilitiesResponse,
  DamProjectAnugaRunResponse,
  DamProjectSummary,
  DamProjectDetailResponse,
} from '../../types/damProjects'
import {
  runAnugaPreflight,
  buildAnugaPackage,
  getAnugaPackageDownloadUrl,
  fetchDamProjectAnugaCapabilities,
  executeDamProjectAnugaRun,
  fetchDamProjectAnugaRuns,
  fetchDamProjectAnugaRunLogs,
} from '../../api/damProjects'

interface DamProjectAnugaReadinessProps {
  project: DamProjectSummary | DamProjectDetailResponse
  onPackageBuilt?: () => void
}

export const DamProjectAnugaReadiness: React.FC<DamProjectAnugaReadinessProps> = ({
  project,
  onPackageBuilt,
}) => {
  const [runningPreflight, setRunningPreflight] = useState<boolean>(false)
  const [preflightResult, setPreflightResult] = useState<DamProjectAnugaPreflightResponse | null>(null)
  const [preflightError, setPreflightError] = useState<string | null>(null)

  const [buildingPackage, setBuildingPackage] = useState<boolean>(false)
  const [packageResult, setPackageResult] = useState<DamProjectAnugaPackageResponse | null>(null)
  const [packageError, setPackageError] = useState<string | null>(null)

  // Execution state (Stage 3)
  const [capabilities, setCapabilities] = useState<DamProjectAnugaCapabilitiesResponse | null>(null)
  const [ackHypothetical, setAckHypothetical] = useState<boolean>(false)
  const [executingRun, setExecutingRun] = useState<boolean>(false)
  const [activeRun, setActiveRun] = useState<DamProjectAnugaRunResponse | null>(null)
  const [executionError, setExecutionError] = useState<string | null>(null)
  const [runLogs, setRunLogs] = useState<string | null>(null)
  const [showLogs, setShowLogs] = useState<boolean>(false)
  const pollingTimerRef = useRef<number | null>(null)

  useEffect(() => {
    fetchDamProjectAnugaCapabilities(project.project_id)
      .then(caps => setCapabilities(caps))
      .catch(() => setCapabilities(null))

    fetchDamProjectAnugaRuns(project.project_id)
      .then(runs => {
        if (runs && runs.length > 0) {
          setActiveRun(runs[0])
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
    if (activeRun && (activeRun.status === 'queued' || activeRun.status === 'running')) {
      if (!pollingTimerRef.current) {
        pollingTimerRef.current = window.setInterval(async () => {
          try {
            const updated = await fetchDamProjectAnugaRuns(project.project_id)
            if (updated && updated.length > 0) {
              setActiveRun(updated[0])
              if (updated[0].status !== 'queued' && updated[0].status !== 'running') {
                if (pollingTimerRef.current) {
                  clearInterval(pollingTimerRef.current)
                  pollingTimerRef.current = null
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

  const handleExecuteRun = async () => {
    if (!ackHypothetical) return
    setExecutingRun(true)
    setExecutionError(null)
    try {
      const res = await executeDamProjectAnugaRun(project.project_id, {
        acknowledge_hypothetical_unverified: true,
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
            <div className={`val-status-banner ${activeRun.status === 'completed' ? 'success' : activeRun.status === 'failed' || activeRun.status === 'timed_out' || activeRun.status === 'interrupted' ? 'failure' : 'running'}`}>
              <span>
                {activeRun.status === 'completed' && '✅ Simulation Completed Successfully'}
                {activeRun.status === 'failed' && '❌ Simulation Failed'}
                {activeRun.status === 'timed_out' && '⏱️ Simulation Timed Out'}
                {activeRun.status === 'interrupted' && '⚠️ Simulation Interrupted (Server restart / terminated)'}
                {activeRun.status === 'running' && '⏳ Simulation Running in Background...'}
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

            <div style={{ marginTop: '0.5rem' }}>
              <button
                type="button"
                className="btn-preflight"
                onClick={handleToggleLogs}
                style={{ padding: '0.25rem 0.5rem', fontSize: '0.72rem' }}
              >
                {showLogs ? 'Hide Logs' : '📄 View Sanitized Execution Logs'}
              </button>
            </div>

            {showLogs && (
              <pre className="font-mono" style={{ maxHeight: '180px', overflowY: 'auto', background: '#0f172a', padding: '0.5rem', borderRadius: '4px', fontSize: '0.7rem', color: '#94a3b8', marginTop: '0.4rem', whiteSpace: 'pre-wrap' }}>
                {runLogs || 'Loading logs...'}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

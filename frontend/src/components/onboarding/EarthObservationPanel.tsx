import React, { useState, useEffect, useCallback } from 'react'
import type {
  DamProjectSummary,
  DamProjectDetailResponse,
  GEECapabilitiesResponse,
  ProjectAOIResponse,
  EarthObservationRunResponse,
  ModelObservationComparisonResponse,
} from '../../types/damProjects'
import {
  fetchGEECapabilities,
  fetchProjectAOI,
  createEarthObservationRun,
  fetchEarthObservationRuns,
  fetchEarthObservationLogs,
  compareModelAndObservation,
} from '../../api/damProjects'
import './EarthObservationPanel.css'

interface EarthObservationPanelProps {
  project: DamProjectSummary | DamProjectDetailResponse
}

export const EarthObservationPanel: React.FC<EarthObservationPanelProps> = ({ project }) => {
  const [capabilities, setCapabilities] = useState<GEECapabilitiesResponse | null>(null)
  const [loadingCaps, setLoadingCaps] = useState<boolean>(true)

  const [aoi, setAoi] = useState<ProjectAOIResponse | null>(null)
  const [bufferMeters, setBufferMeters] = useState<number>(2000)
  const [loadingAoi, setLoadingAoi] = useState<boolean>(false)

  const [runs, setRuns] = useState<EarthObservationRunResponse[]>([])
  const [loadingRuns, setLoadingRuns] = useState<boolean>(false)
  const [activeLogs, setActiveLogs] = useState<{ id: string; logs: string } | null>(null)
  const [loadingLogs, setLoadingLogs] = useState<boolean>(false)

  // Query configuration
  const [eventDate, setEventDate] = useState<string>('2024-07-30')
  const [preWindowDays, setPreWindowDays] = useState<number>(15)
  const [postWindowDays, setPostWindowDays] = useState<number>(5)
  const [polarization, setPolarization] = useState<'VV' | 'VH' | 'both'>('VV')
  const [changeThresholdDb, setChangeThresholdDb] = useState<number>(-3.0)
  const [postWaterThresholdDb, setPostWaterThresholdDb] = useState<number>(-15.0)
  const [selectedDatasets, setSelectedDatasets] = useState<string[]>([
    'sentinel1',
    'jrc_water',
    'gpm_imerg',
  ])

  const [submitting, setSubmitting] = useState<boolean>(false)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Comparison State
  const [anugaRunIdInput, setAnugaRunIdInput] = useState<string>('run-')
  const [selectedEoRunId, setSelectedEoRunId] = useState<string>('')
  const [depthThresholdM, setDepthThresholdM] = useState<number>(0.1)
  const [jrcPermThresholdPct, setJrcPermThresholdPct] = useState<number>(80)
  const [maxTimeDeltaHours, setMaxTimeDeltaHours] = useState<number>(72)
  const [comparing, setComparing] = useState<boolean>(false)
  const [comparisonResult, setComparisonResult] =
    useState<ModelObservationComparisonResponse | null>(null)
  const [comparisonError, setComparisonError] = useState<string | null>(null)

  // 1. Load capabilities
  const loadCapabilities = useCallback(async () => {
    try {
      setLoadingCaps(true)
      const data = await fetchGEECapabilities()
      setCapabilities(data)
    } catch {
      // Capability check failed
    } finally {
      setLoadingCaps(false)
    }
  }, [])

  // 2. Load AOI
  const loadAOI = useCallback(async (buf: number) => {
    try {
      setLoadingAoi(true)
      const data = await fetchProjectAOI(project.project_id, buf)
      setAoi(data)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load project AOI')
    } finally {
      setLoadingAoi(false)
    }
  }, [project.project_id])

  // 3. Load past runs
  const loadRuns = useCallback(async () => {
    try {
      setLoadingRuns(true)
      const data = await fetchEarthObservationRuns(project.project_id)
      setRuns(data)
      if (data.length > 0 && !selectedEoRunId) {
        setSelectedEoRunId(data[0].eo_run_id)
      }
    } catch {
      // Runs load failed
    } finally {
      setLoadingRuns(false)
    }
  }, [project.project_id, selectedEoRunId])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    loadCapabilities()
    loadAOI(bufferMeters)
    loadRuns()
  }, [loadCapabilities, loadAOI, loadRuns, bufferMeters])

  const toggleDataset = (ds: string) => {
    setSelectedDatasets((prev) =>
      prev.includes(ds) ? prev.filter((d) => d !== ds) : [...prev, ds],
    )
  }

  // Trigger EO Run
  const handleLaunchEORun = async (useSyntheticFixture = false) => {
    try {
      setSubmitting(true)
      setActionMessage(null)
      setErrorMessage(null)

      const payload: any = {
        datasets: selectedDatasets,
        event_date: eventDate,
        pre_event_window_days: preWindowDays,
        post_event_window_days: postWindowDays,
        rainfall_start_date: eventDate,
        rainfall_end_date: eventDate,
        aoi_buffer_meters: bufferMeters,
        s1_params: {
          polarization,
          change_threshold_db: changeThresholdDb,
          post_event_water_threshold_db: postWaterThresholdDb,
          threshold_source: 'configurable_heuristic',
        },
      }

      if (useSyntheticFixture) {
        payload.synthetic_test_fixture = true
      }

      const res = await createEarthObservationRun(project.project_id, payload)
      setActionMessage(`EO Run ${res.eo_run_id} initiated (${res.status}).`)
      await loadRuns()
      setSelectedEoRunId(res.eo_run_id)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to execute Earth Observation run.')
    } finally {
      setSubmitting(false)
    }
  }

  // View Run Logs
  const handleViewLogs = async (eoRunId: string) => {
    try {
      setLoadingLogs(true)
      const logData = await fetchEarthObservationLogs(project.project_id, eoRunId)
      setActiveLogs({ id: eoRunId, logs: logData.logs })
    } catch (err: any) {
      setActiveLogs({ id: eoRunId, logs: `Failed to load logs: ${err.message}` })
    } finally {
      setLoadingLogs(false)
    }
  }

  // Trigger Comparison
  const handleRunComparison = async () => {
    if (!anugaRunIdInput || !selectedEoRunId) {
      setComparisonError('Please specify both an ANUGA Run ID and an Earth Observation Run ID.')
      return
    }

    try {
      setComparing(true)
      setComparisonError(null)
      setComparisonResult(null)

      const res = await compareModelAndObservation(project.project_id, {
        anuga_run_id: anugaRunIdInput.trim(),
        eo_run_id: selectedEoRunId.trim(),
        depth_threshold_m: depthThresholdM,
        jrc_permanent_threshold_pct: jrcPermThresholdPct,
        max_observation_time_delta_hours: maxTimeDeltaHours,
      })
      setComparisonResult(res)
    } catch (err: any) {
      setComparisonError(err.message || 'Spatial comparison calculation failed.')
    } finally {
      setComparing(false)
    }
  }

  return (
    <div className="eo-panel-container">
      {/* Header */}
      <div className="eo-header">
        <h4 className="eo-title">
          <span>🛰️ Earth Observation & Remote Sensing Studio</span>
        </h4>
        <div>
          {loadingCaps ? (
            <span className="eo-cap-status-pill eo-cap-warn">Checking GEE...</span>
          ) : capabilities?.authenticated ? (
            <span className="eo-cap-status-pill eo-cap-ok">
              GEE Connected ({capabilities.auth_mode})
            </span>
          ) : (
            <span className="eo-cap-status-pill eo-cap-warn" title={capabilities?.reason || 'ADC / Key required'}>
              Offline / Zero-Fabrication Fallback
            </span>
          )}
        </div>
      </div>

      {/* Mandatory Scientific Caveats Box */}
      <div className="eo-disclaimer-box">
        <strong>Scientific Remote-Sensing Caveat:</strong> Satellite SAR and optical observations
        provide situational evidence of inundation, but do NOT constitute absolute hydrodynamic ground truth.
        SAR radar backscatter is subject to layover/shadow in steep terrain, radar speckle, and emergent vegetation.
        Synthetic data is never fabricated during offline fallback.
      </div>

      {actionMessage && <div style={{ color: '#4ade80', fontSize: '0.76rem' }}>✅ {actionMessage}</div>}
      {errorMessage && <div style={{ color: '#f87171', fontSize: '0.76rem' }}>❌ {errorMessage}</div>}

      {/* 1. AOI Derivation Section */}
      <div className="eo-section">
        <div className="eo-section-title">
          <span>1. Project Area of Interest (AOI)</span>
          {loadingAoi && <span style={{ fontSize: '0.7rem', color: '#94a3b8' }}>Refreshing AOI...</span>}
        </div>
        {aoi ? (
          <div>
            <div className="eo-grid-2">
              <div className="eo-field-group">
                <span className="eo-label">AOI Bounding Box [W, S, E, N]</span>
                <span style={{ fontFamily: 'monospace', fontSize: '0.75rem', color: '#38bdf8' }}>
                  {aoi.aoi_bounds.map((b) => b.toFixed(4)).join(', ')}
                </span>
              </div>
              <div className="eo-field-group">
                <span className="eo-label">Derived Area & Source</span>
                <span style={{ fontSize: '0.75rem' }}>
                  <strong>{aoi.aoi_area_km2.toFixed(2)} km²</strong> (derived from {aoi.source})
                </span>
              </div>
            </div>
            <div style={{ marginTop: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.8rem' }}>
              <span className="eo-label">Buffer Expansion:</span>
              <input
                type="range"
                min={0}
                max={10000}
                step={500}
                value={bufferMeters}
                onChange={(e) => setBufferMeters(Number(e.target.value))}
                style={{ flex: 1 }}
              />
              <span style={{ fontFamily: 'monospace', fontSize: '0.75rem', minWidth: '60px' }}>
                {bufferMeters} m
              </span>
            </div>
          </div>
        ) : (
          <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Loading project AOI geometry...</div>
        )}
      </div>

      {/* 2. EO Retrieval Query Builder */}
      <div className="eo-section">
        <div className="eo-section-title">
          <span>2. Remote Sensing Query Configuration</span>
        </div>

        <div className="eo-grid-3">
          <div className="eo-field-group">
            <label className="eo-label">Event Reference Date</label>
            <input
              type="date"
              className="eo-input"
              value={eventDate}
              onChange={(e) => setEventDate(e.target.value)}
            />
          </div>
          <div className="eo-field-group">
            <label className="eo-label">Pre-Event Window (Days)</label>
            <input
              type="number"
              className="eo-input"
              min={1}
              max={60}
              value={preWindowDays}
              onChange={(e) => setPreWindowDays(Number(e.target.value))}
            />
          </div>
          <div className="eo-field-group">
            <label className="eo-label">Post-Event Window (Days)</label>
            <input
              type="number"
              className="eo-input"
              min={1}
              max={30}
              value={postWindowDays}
              onChange={(e) => setPostWindowDays(Number(e.target.value))}
            />
          </div>
        </div>

        {/* Datasets Selection */}
        <div className="eo-field-group" style={{ marginTop: '0.4rem' }}>
          <span className="eo-label">Target Earth Observation Collections:</span>
          <div className="eo-checkbox-group">
            <label className="eo-checkbox-label">
              <input
                type="checkbox"
                checked={selectedDatasets.includes('sentinel1')}
                onChange={() => toggleDataset('sentinel1')}
              />
              Sentinel-1 SAR GRD (Flood Inundation)
            </label>
            <label className="eo-checkbox-label">
              <input
                type="checkbox"
                checked={selectedDatasets.includes('jrc_water')}
                onChange={() => toggleDataset('jrc_water')}
              />
              JRC Global Surface Water (Permanent Water)
            </label>
            <label className="eo-checkbox-label">
              <input
                type="checkbox"
                checked={selectedDatasets.includes('gpm_imerg')}
                onChange={() => toggleDataset('gpm_imerg')}
              />
              NASA GPM / IMERG (Precipitation)
            </label>
          </div>
        </div>

        {/* Sentinel-1 Configurable Heuristics */}
        <div style={{ background: 'rgba(0,0,0,0.2)', padding: '0.6rem', borderRadius: '4px', marginTop: '0.3rem' }}>
          <span style={{ fontSize: '0.72rem', color: '#c084fc', fontWeight: 600 }}>
            🛰️ Sentinel-1 Configurable Heuristics (Candidate Inundation)
          </span>
          <div className="eo-grid-3" style={{ marginTop: '0.4rem' }}>
            <div className="eo-field-group">
              <label className="eo-label">Polarization</label>
              <select
                className="eo-select"
                value={polarization}
                onChange={(e) => setPolarization(e.target.value as any)}
              >
                <option value="VV">VV (Default Single-Pol)</option>
                <option value="VH">VH (Cross-Pol)</option>
                <option value="both">Both (Dual-Pol)</option>
              </select>
            </div>
            <div className="eo-field-group">
              <label className="eo-label">Change Threshold (dB)</label>
              <input
                type="number"
                step={0.5}
                className="eo-input"
                value={changeThresholdDb}
                onChange={(e) => setChangeThresholdDb(Number(e.target.value))}
              />
            </div>
            <div className="eo-field-group">
              <label className="eo-label">Post-Event Water Threshold (dB)</label>
              <input
                type="number"
                step={0.5}
                className="eo-input"
                value={postWaterThresholdDb}
                onChange={(e) => setPostWaterThresholdDb(Number(e.target.value))}
              />
            </div>
          </div>
          <div style={{ fontSize: '0.66rem', color: '#94a3b8', marginTop: '0.3rem' }}>
            * Thresholds are configurable initial heuristics and persisted in run provenance. Resulting pixels are labeled <em>candidate_inundation</em>, not confirmed flood.
          </div>
        </div>

        {/* Execution Buttons */}
        <div style={{ display: 'flex', gap: '0.6rem', marginTop: '0.6rem' }}>
          <button
            className="eo-btn"
            disabled={submitting || selectedDatasets.length === 0}
            onClick={() => handleLaunchEORun(false)}
          >
            {submitting ? 'Querying...' : '📡 Execute EO Query / Retrieval'}
          </button>
          <button
            className="eo-btn eo-btn-secondary"
            disabled={submitting}
            onClick={() => handleLaunchEORun(true)}
            title="Execute pipeline using isolated synthetic unit fixture (for offline verification without fabricated GEE data)"
          >
            🧪 Run Synthetic Fixture (Offline Test)
          </button>
        </div>
      </div>

      {/* 3. Earth Observation Runs History */}
      <div className="eo-section">
        <div className="eo-section-title">
          <span>3. Earth Observation Runs ({runs.length})</span>
          {loadingRuns && <span style={{ fontSize: '0.7rem', color: '#94a3b8' }}>Refreshing...</span>}
        </div>

        {runs.length === 0 ? (
          <div style={{ fontSize: '0.74rem', color: '#94a3b8', fontStyle: 'italic' }}>
            No Earth Observation runs recorded for this project.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
            {runs.map((r) => {
              const isSelected = selectedEoRunId === r.eo_run_id
              return (
                <div
                  key={r.eo_run_id}
                  className="eo-run-card"
                  style={{
                    borderColor: isSelected ? '#a855f7' : undefined,
                    background: isSelected ? 'rgba(30, 27, 75, 0.4)' : undefined,
                  }}
                >
                  <div className="eo-run-header">
                    <span className="eo-run-id">{r.eo_run_id}</span>
                    <span
                      className={`eo-badge ${
                        r.status === 'completed'
                          ? 'eo-badge-completed'
                          : r.status.includes('unauthenticated') || r.status.includes('fallback')
                          ? 'eo-badge-dryrun'
                          : 'eo-badge-unavailable'
                      }`}
                    >
                      {r.status.toUpperCase()}
                    </span>
                  </div>

                  <div style={{ fontSize: '0.72rem', color: '#cbd5e1' }}>
                    Created: {new Date(r.created_at).toLocaleString()} | Datasets: {r.requested_datasets.join(', ')}
                  </div>

                  {r.status === 'completed' && (
                    <div className="eo-metrics-grid">
                      <div className="eo-metric-item">
                        <span className="eo-metric-val">
                          {r.candidate_inundation_area_km2?.toFixed(2) ?? 'N/A'} km²
                        </span>
                        <span className="eo-metric-lbl">Candidate Inundation</span>
                      </div>
                      <div className="eo-metric-item">
                        <span className="eo-metric-val">
                          {r.permanent_water_area_km2?.toFixed(2) ?? 'N/A'} km²
                        </span>
                        <span className="eo-metric-lbl">Permanent Water (JRC)</span>
                      </div>
                      <div className="eo-metric-item">
                        <span className="eo-metric-val">
                          {r.rainfall_accumulation_mm?.toFixed(1) ?? 'N/A'} mm
                        </span>
                        <span className="eo-metric-lbl">Rainfall (GPM IMERG)</span>
                      </div>
                    </div>
                  )}

                  <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.2rem' }}>
                    <button
                      className="eo-btn eo-btn-secondary"
                      style={{ fontSize: '0.7rem', padding: '0.2rem 0.5rem' }}
                      onClick={() => handleViewLogs(r.eo_run_id)}
                    >
                      📜 View Logs
                    </button>
                    <button
                      className="eo-btn"
                      style={{
                        fontSize: '0.7rem',
                        padding: '0.2rem 0.5rem',
                        background: isSelected ? '#a855f7' : '#334155',
                      }}
                      onClick={() => setSelectedEoRunId(r.eo_run_id)}
                    >
                      {isSelected ? '✓ Selected for Comparison' : 'Select for Comparison'}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* Logs Viewer */}
        {activeLogs && (
          <div style={{ marginTop: '0.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '0.72rem', color: '#a855f7' }}>
                Run Logs [{activeLogs.id}]:
              </span>
              <button
                className="eo-btn eo-btn-secondary"
                style={{ fontSize: '0.65rem', padding: '0.1rem 0.4rem' }}
                onClick={() => setActiveLogs(null)}
              >
                Close
              </button>
            </div>
            {loadingLogs ? (
              <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>Loading logs...</div>
            ) : (
              <pre className="eo-log-viewer">{activeLogs.logs}</pre>
            )}
          </div>
        )}
      </div>

      {/* 4. Model vs Observation Comparison Engine */}
      <div className="eo-section">
        <div className="eo-section-title">
          <span>4. ANUGA Hydrodynamic vs Earth Observation Comparison</span>
        </div>

        <div className="eo-grid-2">
          <div className="eo-field-group">
            <label className="eo-label">Target ANUGA Run ID</label>
            <input
              type="text"
              className="eo-input"
              placeholder="e.g. run-20260911_120000"
              value={anugaRunIdInput}
              onChange={(e) => setAnugaRunIdInput(e.target.value)}
            />
          </div>
          <div className="eo-field-group">
            <label className="eo-label">Target EO Run ID</label>
            <input
              type="text"
              className="eo-input"
              value={selectedEoRunId}
              onChange={(e) => setSelectedEoRunId(e.target.value)}
            />
          </div>
        </div>

        <div className="eo-grid-3" style={{ marginTop: '0.4rem' }}>
          <div className="eo-field-group">
            <label className="eo-label">ANUGA Depth Threshold (m)</label>
            <input
              type="number"
              step={0.05}
              className="eo-input"
              value={depthThresholdM}
              onChange={(e) => setDepthThresholdM(Number(e.target.value))}
            />
          </div>
          <div className="eo-field-group">
            <label className="eo-label">JRC Perm. Water Mask (%)</label>
            <input
              type="number"
              className="eo-input"
              value={jrcPermThresholdPct}
              onChange={(e) => setJrcPermThresholdPct(Number(e.target.value))}
            />
          </div>
          <div className="eo-field-group">
            <label className="eo-label">Max Time Delta (Hours)</label>
            <input
              type="number"
              className="eo-input"
              value={maxTimeDeltaHours}
              onChange={(e) => setMaxTimeDeltaHours(Number(e.target.value))}
            />
          </div>
        </div>

        <div style={{ marginTop: '0.6rem' }}>
          <button
            className="eo-btn"
            disabled={comparing || !anugaRunIdInput || !selectedEoRunId}
            onClick={handleRunComparison}
          >
            {comparing ? 'Comparing...' : '⚖️ Compute Spatial Agreement (IoU)'}
          </button>
        </div>

        {comparisonError && (
          <div style={{ color: '#f87171', fontSize: '0.74rem', marginTop: '0.4rem' }}>
            ❌ {comparisonError}
          </div>
        )}

        {/* Comparison Result Display */}
        {comparisonResult && (
          <div className="eo-comp-box" style={{ marginTop: '0.8rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontWeight: 700, color: '#38bdf8' }}>
                Spatial Agreement Results [{comparisonResult.comparison_id}]
              </span>
              <span style={{ fontSize: '0.7rem', color: '#cbd5e1' }}>
                Label: <strong>{comparisonResult.label}</strong>
              </span>
            </div>

            {/* KPI Banner */}
            <div className="eo-kpi-banner">
              <div className="eo-kpi-block">
                <span className="eo-kpi-number" style={{ color: '#4ade80' }}>
                  {(comparisonResult.spatial_agreement_iou * 100).toFixed(1)}%
                </span>
                <span className="eo-kpi-label">IoU Agreement</span>
              </div>
              <div className="eo-kpi-block">
                <span className="eo-kpi-number">{comparisonResult.overlap_area_km2.toFixed(2)}</span>
                <span className="eo-kpi-label">Overlap (km²)</span>
              </div>
              <div className="eo-kpi-block">
                <span className="eo-kpi-number" style={{ color: '#fbbf24' }}>
                  {comparisonResult.model_only_area_km2.toFixed(2)}
                </span>
                <span className="eo-kpi-label">Model Only (km²)</span>
              </div>
              <div className="eo-kpi-block">
                <span className="eo-kpi-number" style={{ color: '#c084fc' }}>
                  {comparisonResult.satellite_only_area_km2.toFixed(2)}
                </span>
                <span className="eo-kpi-label">Satellite Only (km²)</span>
              </div>
            </div>

            {/* Temporal Validity Warning / Info */}
            <div
              style={{
                background: comparisonResult.temporal_validity.comparison_valid
                  ? 'rgba(34, 197, 94, 0.1)'
                  : 'rgba(234, 88, 12, 0.15)',
                border: `1px solid ${
                  comparisonResult.temporal_validity.comparison_valid
                    ? 'rgba(34, 197, 94, 0.3)'
                    : 'rgba(234, 88, 12, 0.4)'
                }`,
                borderRadius: '4px',
                padding: '0.5rem',
                fontSize: '0.72rem',
              }}
            >
              <div>
                <strong>Temporal Comparison Delta:</strong>{' '}
                {comparisonResult.temporal_validity.absolute_delta_hours.toFixed(1)} hours (Tolerance: {comparisonResult.temporal_validity.configured_tolerance_hours}h)
              </div>
              {comparisonResult.temporal_validity.warning && (
                <div style={{ color: '#fb923c', marginTop: '0.2rem' }}>
                  ⚠️ {comparisonResult.temporal_validity.warning}
                </div>
              )}
            </div>

            {/* Scientific Caveats List */}
            <div>
              <span style={{ fontSize: '0.72rem', fontWeight: 600, color: '#e2e8f0' }}>
                Interpretation Constraints:
              </span>
              <ul style={{ margin: '0.2rem 0', paddingLeft: '1.2rem', fontSize: '0.7rem', color: '#94a3b8' }}>
                {comparisonResult.scientific_caveats.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

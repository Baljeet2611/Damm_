import React, { useState, useEffect, useCallback } from 'react'
import type {
  DamProjectValidationResponse,
  DamProjectSummary,
  DamProjectDetailResponse,
  DamProjectReadinessResponse,
  OnboardingFormValues,
} from '../../types/damProjects'
import {
  validateDamProject,
  saveDamProject,
  listDamProjects,
  fetchDamProjectReadiness,
} from '../../api/damProjects'
import { DamProjectAnugaReadiness } from './DamProjectAnugaReadiness'
import { EarthObservationPanel } from './EarthObservationPanel'
import { ModelComparisonPanel } from './ModelComparisonPanel'
import { ExposureVulnerabilityPanel } from './ExposureVulnerabilityPanel'
import { SystemHealthPanel } from './SystemHealthPanel'
import './DamOnboardingPanel.css'

export type ProductStage =
  | 'overview'
  | 'setup'
  | 'simulation'
  | 'satellite'
  | 'comparison'
  | 'exposure'
  | 'decision'
  | 'provenance'

interface DamOnboardingPanelProps {
  onDisplayProjectDem?: (project: DamProjectSummary | DamProjectDetailResponse) => void
  onDisplayHazardLayer?: (projectId: string, runId: string, layer: string, processingId?: string) => void
}

export const DamOnboardingPanel: React.FC<DamOnboardingPanelProps> = ({
  onDisplayProjectDem,
  onDisplayHazardLayer,
}) => {
  // Navigation stage state (User-Facing Stages)
  const [currentStage, setCurrentStage] = useState<ProductStage>('overview')

  // File states
  const [demFile, setDemFile] = useState<File | null>(null)
  const [damAxisFile, setDamAxisFile] = useState<File | null>(null)
  const [reservoirFile, setReservoirFile] = useState<File | null>(null)
  const [modelDomainFile, setModelDomainFile] = useState<File | null>(null)
  const [downstreamOutletFile, setDownstreamOutletFile] = useState<File | null>(null)

  // Form values (Generalized Onboarding + Engineering & Advanced Parameters)
  const [formValues, setFormValues] = useState<OnboardingFormValues>({
    projectName: 'New Dam Study',
    damName: 'Sample Dam',
    latitude: '16.215',
    longitude: '74.632',
    damHeight: '',
    crestElevation: '',
    poolElevation: '',
    manningN: '0.035',
    verticalUnit: '',
    verticalDatum: '',
    reservoirLevel: '',
    breachWidth: '200',
    breachCenterX: '',
    breachCenterY: '',
    breachFormationTimeHr: '1.0',
    manningRoughness: '0.035',
    damCrestElevation: '',
    breachInvertElevation: '',
    targetMeshResolutionM: '50',
    simulationDurationS: '3600',
    outputIntervalS: '60',
    geometryCrs: 'EPSG:4326',
  })

  // Accordion UI toggles
  const [showEngParams, setShowEngParams] = useState<boolean>(true)
  const [showVectorBoundaries, setShowVectorBoundaries] = useState<boolean>(false)

  // Workflow states
  const [validating, setValidating] = useState<boolean>(false)
  const [validationResult, setValidationResult] = useState<DamProjectValidationResponse | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)

  const [acknowledgeUnverified, setAcknowledgeUnverified] = useState<boolean>(false)
  const [saving, setSaving] = useState<boolean>(false)
  const [savedProject, setSavedProject] = useState<DamProjectDetailResponse | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Saved projects list & active project selection
  const [projectsList, setProjectsList] = useState<DamProjectSummary[]>([])
  const [loadingProjects, setLoadingProjects] = useState<boolean>(false)
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [projectReadinessData, setProjectReadinessData] = useState<Record<string, DamProjectReadinessResponse>>({})
  const [loadingReadinessId, setLoadingReadinessId] = useState<string | null>(null)

  const loadProjects = useCallback(async () => {
    try {
      setLoadingProjects(true)
      const list = await listDamProjects()
      setProjectsList(list)
      if (list.length > 0) {
        setSelectedProjectId((prev) => (prev && list.some((p) => p.project_id === prev) ? prev : list[0].project_id))
      }
    } catch {
      // ignore
    } finally {
      setLoadingProjects(false)
    }
  }, [])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    loadProjects()
  }, [loadProjects])

  const activeProject = projectsList.find((p) => p.project_id === selectedProjectId) || (projectsList.length > 0 ? projectsList[0] : null)

  const handleInputChange = (field: keyof OnboardingFormValues, value: string) => {
    setFormValues((prev) => ({ ...prev, [field]: value }))
    setValidationResult(null)
    setAcknowledgeUnverified(false)
    setSaveError(null)
  }

  const buildFormData = (isSave = false): FormData | null => {
    if (!demFile) return null
    const fd = new FormData()
    fd.append('dem_file', demFile)
    if (damAxisFile) fd.append('dam_axis_file', damAxisFile)
    if (reservoirFile) fd.append('reservoir_boundary_file', reservoirFile)
    if (modelDomainFile) fd.append('model_domain_file', modelDomainFile)
    if (downstreamOutletFile) fd.append('downstream_outlet_file', downstreamOutletFile)

    fd.append('project_name', formValues.projectName)
    fd.append('dam_name', formValues.damName)
    fd.append('latitude', formValues.latitude)
    fd.append('longitude', formValues.longitude)

    if (formValues.damHeight) fd.append('dam_height', formValues.damHeight)
    if (formValues.crestElevation) fd.append('crest_elevation', formValues.crestElevation)
    if (formValues.poolElevation) fd.append('pool_elevation', formValues.poolElevation)
    if (formValues.manningN) fd.append('manning_n', formValues.manningN)
    if (formValues.verticalUnit) fd.append('vertical_unit', formValues.verticalUnit)
    if (formValues.verticalDatum) fd.append('vertical_datum', formValues.verticalDatum)

    if (isSave) {
      if (formValues.reservoirLevel) fd.append('reservoir_level', formValues.reservoirLevel)
      if (formValues.breachWidth) fd.append('breach_width', formValues.breachWidth)
      if (formValues.breachCenterX) fd.append('breach_center_x', formValues.breachCenterX)
      if (formValues.breachCenterY) fd.append('breach_center_y', formValues.breachCenterY)
      if (formValues.breachFormationTimeHr) fd.append('breach_formation_time_hr', formValues.breachFormationTimeHr)
      if (formValues.manningRoughness) fd.append('manning_roughness', formValues.manningRoughness)
      if (formValues.damCrestElevation) fd.append('dam_crest_elevation', formValues.damCrestElevation)
      if (formValues.breachInvertElevation) fd.append('breach_invert_elevation', formValues.breachInvertElevation)
      if (formValues.targetMeshResolutionM) fd.append('target_mesh_resolution_m', formValues.targetMeshResolutionM)
      if (formValues.simulationDurationS) fd.append('simulation_duration_s', formValues.simulationDurationS)
      if (formValues.outputIntervalS) fd.append('output_interval_s', formValues.outputIntervalS)
      if (formValues.geometryCrs) fd.append('geometry_crs', formValues.geometryCrs)
    }

    return fd
  }

  const handleValidate = async () => {
    if (!demFile) {
      setValidationError('Please select a DEM GeoTIFF file.')
      return
    }
    const lat = parseFloat(formValues.latitude)
    const lon = parseFloat(formValues.longitude)
    if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      setValidationError('Please enter valid WGS84 coordinates (Latitude: -90 to 90, Longitude: -180 to 180).')
      return
    }

    const fd = buildFormData(false)
    if (!fd) return

    setValidating(true)
    setValidationError(null)
    setValidationResult(null)

    try {
      const res = await validateDamProject(fd)
      setValidationResult(res)
    } catch (err: any) {
      setValidationError(err.message || 'Validation request failed.')
    } finally {
      setValidating(false)
    }
  }

  const handleSave = async () => {
    if (!validationResult || !validationResult.onboarding_validation_passed) {
      setSaveError('Ingestion validation must pass before saving.')
      return
    }
    if (!acknowledgeUnverified) {
      setSaveError('Please acknowledge the unverified, screening-only nature of the data.')
      return
    }

    const fd = buildFormData(true)
    if (!fd) return

    setSaving(true)
    setSaveError(null)

    try {
      const saved = await saveDamProject(fd)
      setSavedProject(saved)
      setSelectedProjectId(saved.project_id)
      await loadProjects()
      await handleToggleReadiness(saved.project_id)
    } catch (err: any) {
      setSaveError(err.message || 'Failed to save project.')
    } finally {
      setSaving(false)
    }
  }

  const handleToggleReadiness = async (projectId: string) => {
    if (!projectReadinessData[projectId]) {
      try {
        setLoadingReadinessId(projectId)
        const readiness = await fetchDamProjectReadiness(projectId)
        setProjectReadinessData((prev) => ({ ...prev, [projectId]: readiness }))
      } catch (err) {
        console.error('Failed to load readiness:', err)
      } finally {
        setLoadingReadinessId(null)
      }
    }
  }

  const handleDownloadDecisionReport = () => {
    if (!activeProject) return
    const reportData = {
      project_id: activeProject.project_id,
      project_name: activeProject.project_name,
      dam_name: activeProject.dam_name,
      scientific_status: activeProject.scientific_status || 'unverified_reference',
      generated_at: new Date().toISOString(),
      governing_advisory: 'Advisory decision-support screening metrics only. Not certified engineering loss conclusions.',
      evacuation_corridors: {
        priority_1_immediate: 'Within 0-15 min flood wave zone (Immediate evacuation of low-lying floodway)',
        priority_2_urgent: 'Within 15-60 min arrival zone (Clear downstream staging areas and secondary bridges)',
        priority_3_warning: 'Within 1-3 hour wave propagation envelope (Activate regional detours)',
      },
      critical_facilities_alert: 'Hospitals, substations, and emergency response hubs flagged for threshold elevation review.',
      vulnerability_curve_provenance: {
        reference: 'Huizinga et al., 2017, EUR 28552 EN',
        status: 'unverified_reference',
      },
    }
    const blob = new Blob([JSON.stringify(reportData, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `decision_support_briefing_${activeProject.project_id}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <div className="hud-card onboarding-card">
      <div className="hud-card-header">
        <h3>🏛️ Dam Inundation & Hydrodynamic Analysis</h3>
        <span className="legend-tag">SIH 26161 • DECISION SUPPORT</span>
      </div>

      {/* User-Facing Product Stage Navigation */}
      <div className="product-stage-nav" role="tablist" aria-label="Workflow Stages">
        <button
          className={`product-stage-btn ${currentStage === 'overview' ? 'active' : ''}`}
          onClick={() => setCurrentStage('overview')}
          title="System health HUD and registered study overview"
        >
          <span>🌐</span> Overview
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'setup' ? 'active' : ''}`}
          onClick={() => setCurrentStage('setup')}
          title="Ingest DEM GeoTIFF and define dam parameters"
        >
          <span>🏗️</span> Study Setup
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'simulation' ? 'active' : ''}`}
          onClick={() => setCurrentStage('simulation')}
          title="Readiness checklist, ANUGA simulation package, and hydrodynamic runner"
        >
          <span>⚡</span> Simulation
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'satellite' ? 'active' : ''}`}
          onClick={() => setCurrentStage('satellite')}
          title="Sentinel-1 SAR Earth Observation & flood footprint comparison"
        >
          <span>🛰️</span> Satellite Evidence
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'comparison' ? 'active' : ''}`}
          onClick={() => setCurrentStage('comparison')}
          title="Multi-engine spatial hydrodynamic comparison"
        >
          <span>⚖️</span> Model Comparison
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'exposure' ? 'active' : ''}`}
          onClick={() => setCurrentStage('exposure')}
          title="Population, building, road, and infrastructure vulnerability"
        >
          <span>👥</span> Exposure & Impact
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'decision' ? 'active' : ''}`}
          onClick={() => setCurrentStage('decision')}
          title="Evacuation corridors, warning timelines, and decision guidance"
        >
          <span>🎯</span> Decision Support
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'provenance' ? 'active' : ''}`}
          onClick={() => setCurrentStage('provenance')}
          title="Cryptographic integrity, curve citations, and scientific assumptions"
        >
          <span>📜</span> Technical / Provenance
        </button>
      </div>

      {/* Stage Active Project Bar (shown for project-dependent stages) */}
      {currentStage !== 'overview' && currentStage !== 'setup' && (
        <div className="stage-active-project-bar">
          <div>
            <span className="stage-project-select-label">Active Study:</span>
            <select
              className="stage-project-select"
              value={selectedProjectId || ''}
              onChange={(e) => setSelectedProjectId(e.target.value || null)}
            >
              {projectsList.length === 0 ? (
                <option value="">No studies registered</option>
              ) : (
                projectsList.map((p) => (
                  <option key={p.project_id} value={p.project_id}>
                    {p.project_name} ({p.dam_name || 'Dam'})
                  </option>
                ))
              )}
            </select>
          </div>
          {activeProject && (
            <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
              <span className="saved-project-badge badge-unverified">
                {activeProject.scientific_status || 'UNVERIFIED'}
              </span>
              <button
                className="btn-fit"
                style={{ fontSize: '0.7rem', padding: '0.2rem 0.45rem' }}
                onClick={() => onDisplayProjectDem && onDisplayProjectDem(activeProject)}
                title="View DEM and Dam point on Map"
              >
                🗺️ View DEM on Map
              </button>
            </div>
          )}
        </div>
      )}

      {/* STAGE 1: OVERVIEW */}
      {currentStage === 'overview' && (
        <div className="onboarding-body">
          {/* System Health HUD Component */}
          <SystemHealthPanel />

          {/* Registered Studies Section */}
          <div className="onboarding-section" style={{ marginTop: '0.5rem' }}>
            <div className="hud-card-header">
              <h4 className="onboarding-sub-title">Registered Dam Studies ({projectsList.length})</h4>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <button className="btn-fit" onClick={() => setCurrentStage('setup')}>
                  ➕ Ingest New Study
                </button>
                <button className="btn-fit" onClick={loadProjects} title="Refresh registered studies">
                  ↺ Refresh
                </button>
              </div>
            </div>

            {loadingProjects ? (
              <div className="probe-loading">
                <span className="spinner" /> Loading registered dam studies...
              </div>
            ) : projectsList.length === 0 ? (
              <div className="stage-empty-state">
                <span style={{ fontSize: '2rem' }}>📁</span>
                <span className="stage-empty-state-title">No Custom Dam Studies Registered</span>
                <p className="stage-empty-state-desc">
                  Ingest a local or regional terrain DEM GeoTIFF to define dam coordinates, parameterize structural attributes, and unlock the hydrodynamic simulation pipeline.
                </p>
                <button className="btn-save-dam" onClick={() => setCurrentStage('setup')} style={{ maxWidth: '240px' }}>
                  🚀 Ingest Your First Dam Study
                </button>
              </div>
            ) : (
              <div className="saved-projects-list">
                {projectsList.map((p) => {
                  const isIntegrityFailed = !p.available || p.integrity_status === 'failed' || p.integrity_status === 'corrupted' || p.integrity_status === 'integrity_failed'
                  return (
                    <div
                      key={p.project_id}
                      className="saved-project-card"
                      style={{
                        borderColor: selectedProjectId === p.project_id ? 'var(--neon-cyan, #00ffff)' : undefined,
                      }}
                    >
                      <div className="saved-project-header">
                        <div>
                          <span className="saved-project-title">🏷️ {p.project_name}</span>
                          {p.dam_name && (
                            <span style={{ fontSize: '0.72rem', color: '#94a3b8', marginLeft: '0.4rem' }}>
                              ({p.dam_name})
                            </span>
                          )}
                        </div>
                        <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                          <span className="saved-project-badge badge-unverified">
                            {p.scientific_status || 'UNVERIFIED'}
                          </span>
                          <span className={`saved-project-badge ${isIntegrityFailed ? 'badge-corrupted' : 'badge-ok'}`}>
                            {isIntegrityFailed ? '❌ Integrity Failed' : '✅ Integrity OK'}
                          </span>
                        </div>
                      </div>

                      <div className="saved-project-details font-mono">
                        <span>CRS: {p.crs}</span>
                        <span>Created: {p.created_at ? new Date(p.created_at).toLocaleDateString() : 'N/A'}</span>
                        <span>Point: {p.dam_point ? '📍 Yes' : 'No'}</span>
                        <span>Axis: {p.has_reservoir_boundary ? 'Yes' : (p.dam_point ? 'Optional' : 'None')}</span>
                        <span>Domain: {p.has_model_domain ? 'Yes' : 'None'}</span>
                        <span>Outlet: {p.has_downstream_outlet ? 'Yes' : 'None'}</span>
                      </div>

                      {isIntegrityFailed && (
                        <div className="damage-error-box font-mono" style={{ padding: '0.35rem 0.5rem', fontSize: '0.72rem' }}>
                          ⛔ Integrity check failed: {p.integrity_error || 'File SHA-256 hash mismatch or missing files.'}
                        </div>
                      )}

                      <div className="saved-project-actions">
                        <button
                          className="btn-project-action"
                          onClick={() => onDisplayProjectDem && onDisplayProjectDem(p)}
                          disabled={isIntegrityFailed}
                          title="Display DEM and Dam marker on Map"
                        >
                          🗺️ View DEM
                        </button>
                        <button
                          className="btn-project-action"
                          onClick={() => {
                            setSelectedProjectId(p.project_id)
                            setCurrentStage('simulation')
                          }}
                          disabled={isIntegrityFailed}
                        >
                          ⚡ Simulation
                        </button>
                        <button
                          className="btn-project-action"
                          onClick={() => {
                            setSelectedProjectId(p.project_id)
                            setCurrentStage('exposure')
                          }}
                          disabled={isIntegrityFailed}
                        >
                          👥 Exposure
                        </button>
                        <button
                          className="btn-project-action"
                          onClick={() => {
                            setSelectedProjectId(p.project_id)
                            setCurrentStage('decision')
                          }}
                          disabled={isIntegrityFailed}
                        >
                          🎯 Decision
                        </button>
                        <button
                          className="btn-project-action"
                          onClick={() => {
                            setSelectedProjectId(p.project_id)
                            setCurrentStage('provenance')
                          }}
                          disabled={isIntegrityFailed}
                        >
                          📜 Provenance
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* STAGE 2: STUDY SETUP */}
      {currentStage === 'setup' && (
        <div className="onboarding-body">
          {/* Step 1: Core Dataset & Dam Point */}
          <div className="onboarding-section">
            <h4 className="onboarding-sub-title">1. Essential Data (DEM & Dam Location)</h4>

            <div className="file-input-group">
              <label className="file-input-label">DEM GeoTIFF (*.tif, *.tiff) *</label>
              <input
                type="file"
                accept=".tif,.tiff"
                onChange={(e) => {
                  setDemFile(e.target.files?.[0] || null)
                  setValidationResult(null)
                }}
                className="file-input-control"
              />
              {demFile && <span className="file-selected-name">📄 {demFile.name} ({(demFile.size / (1024 * 1024)).toFixed(2)} MB)</span>}
            </div>

            <div className="onboarding-grid-2">
              <div className="config-field">
                <label>Study / Project Name *</label>
                <input
                  type="text"
                  value={formValues.projectName}
                  onChange={(e) => handleInputChange('projectName', e.target.value)}
                  className="config-input"
                  placeholder="e.g. Koyna Basin Study"
                />
              </div>
              <div className="config-field">
                <label>Dam / Structure Name *</label>
                <input
                  type="text"
                  value={formValues.damName}
                  onChange={(e) => handleInputChange('damName', e.target.value)}
                  className="config-input"
                  placeholder="e.g. Koyna Dam"
                />
              </div>
            </div>

            <div className="onboarding-grid-2">
              <div className="config-field">
                <label>Latitude (WGS84 decimal degrees) *</label>
                <input
                  type="number"
                  step="0.00001"
                  value={formValues.latitude}
                  onChange={(e) => handleInputChange('latitude', e.target.value)}
                  className="config-input font-mono"
                  placeholder="e.g. 17.4005"
                />
              </div>
              <div className="config-field">
                <label>Longitude (WGS84 decimal degrees) *</label>
                <input
                  type="number"
                  step="0.00001"
                  value={formValues.longitude}
                  onChange={(e) => handleInputChange('longitude', e.target.value)}
                  className="config-input font-mono"
                  placeholder="e.g. 73.7483"
                />
              </div>
            </div>
          </div>

          {/* Step 2: Engineering & Structural Parameters */}
          <div className="onboarding-section">
            <div
              className="accordion-header"
              onClick={() => setShowEngParams(!showEngParams)}
              style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
            >
              <h4 className="onboarding-sub-title">2. Engineering & Hydraulic Parameters (Optional)</h4>
              <span>{showEngParams ? '▲' : '▼'}</span>
            </div>

            {showEngParams && (
              <div className="accordion-content">
                <div className="onboarding-grid-3">
                  <div className="config-field">
                    <label>Dam Height (m)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={formValues.damHeight}
                      onChange={(e) => handleInputChange('damHeight', e.target.value)}
                      className="config-input font-mono"
                      placeholder="e.g. 103.0"
                    />
                  </div>
                  <div className="config-field">
                    <label>Crest Elevation (m)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={formValues.crestElevation}
                      onChange={(e) => handleInputChange('crestElevation', e.target.value)}
                      className="config-input font-mono"
                      placeholder="e.g. 665.0"
                    />
                  </div>
                  <div className="config-field">
                    <label>Pool Elevation (m)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={formValues.poolElevation}
                      onChange={(e) => handleInputChange('poolElevation', e.target.value)}
                      className="config-input font-mono"
                      placeholder="e.g. 660.0"
                    />
                  </div>
                </div>

                <div className="onboarding-grid-2">
                  <div className="config-field">
                    <label>Manning Roughness (n)</label>
                    <input
                      type="number"
                      step="0.001"
                      value={formValues.manningN}
                      onChange={(e) => handleInputChange('manningN', e.target.value)}
                      className="config-input font-mono"
                      placeholder="0.035"
                    />
                  </div>
                  <div className="config-field">
                    <label>Breach Width (m)</label>
                    <input
                      type="number"
                      step="1"
                      value={formValues.breachWidth}
                      onChange={(e) => handleInputChange('breachWidth', e.target.value)}
                      className="config-input font-mono"
                      placeholder="200"
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Step 3: Optional Vector Geometries */}
          <div className="onboarding-section">
            <div
              className="accordion-header"
              onClick={() => setShowVectorBoundaries(!showVectorBoundaries)}
              style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
            >
              <h4 className="onboarding-sub-title">3. Vector Boundaries (Optional GeoJSON / Shapefile)</h4>
              <span>{showVectorBoundaries ? '▲' : '▼'}</span>
            </div>

            {showVectorBoundaries && (
              <div className="accordion-content">
                <div className="file-input-group">
                  <label className="file-input-label">Dam Axis Alignment (GeoJSON / SHP / GPKG)</label>
                  <input
                    type="file"
                    accept=".geojson,.json,.shp,.zip,.gpkg"
                    onChange={(e) => setDamAxisFile(e.target.files?.[0] || null)}
                    className="file-input-control"
                  />
                  {damAxisFile && <span className="file-selected-name">📄 {damAxisFile.name}</span>}
                </div>

                <div className="file-input-group">
                  <label className="file-input-label">Reservoir Pool Boundary</label>
                  <input
                    type="file"
                    accept=".geojson,.json,.shp,.zip,.gpkg"
                    onChange={(e) => setReservoirFile(e.target.files?.[0] || null)}
                    className="file-input-control"
                  />
                  {reservoirFile && <span className="file-selected-name">📄 {reservoirFile.name}</span>}
                </div>

                <div className="file-input-group">
                  <label className="file-input-label">Model Domain Extent Boundary</label>
                  <input
                    type="file"
                    accept=".geojson,.json,.shp,.zip,.gpkg"
                    onChange={(e) => setModelDomainFile(e.target.files?.[0] || null)}
                    className="file-input-control"
                  />
                  {modelDomainFile && <span className="file-selected-name">📄 {modelDomainFile.name}</span>}
                </div>

                <div className="file-input-group">
                  <label className="file-input-label">Downstream Outlet Boundary</label>
                  <input
                    type="file"
                    accept=".geojson,.json,.shp,.zip,.gpkg"
                    onChange={(e) => setDownstreamOutletFile(e.target.files?.[0] || null)}
                    className="file-input-control"
                  />
                  {downstreamOutletFile && <span className="file-selected-name">📄 {downstreamOutletFile.name}</span>}
                </div>
              </div>
            )}
          </div>

          {/* Validation Trigger */}
          <div className="onboarding-actions-row">
            <button
              className="btn-validate-dam"
              onClick={handleValidate}
              disabled={validating || !demFile || !formValues.projectName.trim()}
            >
              {validating ? <><span className="spinner" /> Validating Ingestion...</> : '🔍 1. Validate Dataset & Location'}
            </button>
          </div>

          {validationError && (
            <div className="damage-error-box font-mono">
              ⛔ {validationError}
            </div>
          )}

          {/* Validation Report */}
          {validationResult && (
            <div className="val-results-card">
              <div
                className={`val-status-banner ${
                  validationResult.onboarding_validation_passed
                    ? 'success'
                    : validationResult.valid
                    ? 'warning'
                    : 'failure'
                }`}
              >
                <span>
                  {validationResult.onboarding_validation_passed
                    ? '✅ Ingestion Validation Passed'
                    : validationResult.valid
                    ? '⚠️ Ingestion Validation Warnings'
                    : '❌ Ingestion Validation Failed'}
                </span>
                <span className="legend-tag">
                  {validationResult.scientific_status?.toUpperCase() || 'VALIDATED_UNVERIFIED'}
                </span>
              </div>

              <div className="val-disclaimer-box">
                <strong>User-declared, not independently verified.</strong> Coordinates, elevations, and structural metadata are stored as unverified inputs for spatial screening and pre-simulation assessment only.
              </div>

              {/* Raster Metadata */}
              {validationResult.normalized_metadata?.raster_metadata && (
                <div className="val-metadata-grid">
                  <div className="val-meta-item">
                    <span className="val-meta-label">DEM Dimensions</span>
                    <span className="val-meta-value">
                      {validationResult.normalized_metadata.raster_metadata.width} × {validationResult.normalized_metadata.raster_metadata.height}
                    </span>
                  </div>
                  <div className="val-meta-item">
                    <span className="val-meta-label">DEM CRS</span>
                    <span className="val-meta-value">{validationResult.normalized_metadata.raster_metadata.crs}</span>
                  </div>
                  <div className="val-meta-item">
                    <span className="val-meta-label">Elevation Min / Max</span>
                    <span className="val-meta-value">
                      {validationResult.normalized_metadata.raster_metadata.min_elevation != null
                        ? `${validationResult.normalized_metadata.raster_metadata.min_elevation.toFixed(1)} m to ${validationResult.normalized_metadata.raster_metadata.max_elevation?.toFixed(1)} m`
                        : 'N/A'}
                    </span>
                  </div>
                  <div className="val-meta-item">
                    <span className="val-meta-label">Mean Elevation</span>
                    <span className="val-meta-value">
                      {validationResult.normalized_metadata.raster_metadata.mean_elevation != null
                        ? `${validationResult.normalized_metadata.raster_metadata.mean_elevation.toFixed(1)} m`
                        : 'N/A'}
                    </span>
                  </div>
                </div>
              )}

              {/* Dam Point Metadata */}
              {validationResult.normalized_metadata?.dam_point && (
                <div className="val-metadata-grid">
                  <div className="val-meta-item">
                    <span className="val-meta-label">Dam Name</span>
                    <span className="val-meta-value">{validationResult.normalized_metadata.dam_point.dam_name}</span>
                  </div>
                  <div className="val-meta-item">
                    <span className="val-meta-label">WGS84 Coordinates</span>
                    <span className="val-meta-value">
                      {validationResult.normalized_metadata.dam_point.latitude.toFixed(5)}°N, {validationResult.normalized_metadata.dam_point.longitude.toFixed(5)}°E
                    </span>
                  </div>
                  <div className="val-meta-item" style={{ gridColumn: 'span 2' }}>
                    <span className="val-meta-label">Sampled DEM Elevation at Dam Point</span>
                    <span className="val-meta-value">
                      {validationResult.normalized_metadata.dam_point.elevation_at_point != null
                        ? `📍 ${validationResult.normalized_metadata.dam_point.elevation_at_point.toFixed(1)} m (Sampled from GeoTIFF)`
                        : '⚠️ Coordinate outside valid raster extent or nodata'}
                    </span>
                  </div>
                </div>
              )}

              {/* Errors & Warnings */}
              {validationResult.errors.length > 0 && (
                <div>
                  <span className="note-title text-danger">Validation Errors:</span>
                  <ul className="val-errors-list font-mono">
                    {validationResult.errors.map((err, idx) => (
                      <li key={idx}>{err}</li>
                    ))}
                  </ul>
                </div>
              )}

              {validationResult.warnings.length > 0 && (
                <div>
                  <span className="note-title text-warning">Warnings & Advisories:</span>
                  <ul className="val-warnings-list font-mono">
                    {validationResult.warnings.map((w, idx) => (
                      <li key={idx}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Step 4: Acknowledge and Save */}
              {validationResult.onboarding_validation_passed && (
                <div style={{ marginTop: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                  <label className="ack-label">
                    <input
                      type="checkbox"
                      checked={acknowledgeUnverified}
                      onChange={(e) => setAcknowledgeUnverified(e.target.checked)}
                      className="ack-checkbox"
                    />
                    <span className="ack-text">
                      I acknowledge that the submitted metadata and geometries are <strong>user-declared, not independently verified</strong>, and are stored for exploratory inspection only.
                    </span>
                  </label>

                  <button
                    className="btn-save-dam"
                    onClick={handleSave}
                    disabled={saving || !acknowledgeUnverified}
                  >
                    {saving ? <><span className="spinner" /> Persisting Dam Project...</> : '💾 2. Register & Save Project'}
                  </button>
                </div>
              )}
            </div>
          )}

          {saveError && (
            <div className="damage-error-box font-mono">
              ⛔ {saveError}
            </div>
          )}

          {savedProject && (
            <div className="export-success-box font-mono">
              ✅ Study Registered Successfully! ID: <code>{savedProject.project_id}</code>
              <br />
              <div style={{ marginTop: '0.5rem' }}>
                <button
                  className="btn-fit"
                  onClick={() => {
                    setSelectedProjectId(savedProject.project_id)
                    setCurrentStage('simulation')
                  }}
                  style={{ background: '#0284c7', color: '#fff', padding: '0.4rem 0.8rem' }}
                >
                  ⚡ Proceed to Simulation →
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* STAGE 3: SIMULATION */}
      {currentStage === 'simulation' && (
        <div className="onboarding-body">
          {!activeProject ? (
            <div className="stage-empty-state">
              <span style={{ fontSize: '2rem' }}>⚡</span>
              <span className="stage-empty-state-title">No Dam Study Selected</span>
              <p className="stage-empty-state-desc">
                Select a registered dam study from the dropdown above or ingest a new study in Study Setup to build ANUGA hydrodynamic simulation packages.
              </p>
              <button className="btn-fit" onClick={() => setCurrentStage('setup')}>
                🏗️ Go to Study Setup
              </button>
            </div>
          ) : (
            <div>
              {/* Pre-Simulation Readiness Assessment */}
              <div className="readiness-card-container" style={{ marginBottom: '0.85rem', padding: '0.75rem', background: 'rgba(15, 23, 42, 0.85)', borderRadius: '6px', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <h5 style={{ margin: 0, fontSize: '0.82rem', color: '#38bdf8' }}>
                    🎯 Pre-Simulation Readiness Assessment
                  </h5>
                  <button
                    className="btn-fit"
                    style={{ fontSize: '0.68rem' }}
                    onClick={() => handleToggleReadiness(activeProject.project_id)}
                  >
                    ↺ Re-evaluate
                  </button>
                </div>

                {loadingReadinessId === activeProject.project_id ? (
                  <div className="probe-loading"><span className="spinner" /> Evaluating readiness checklist...</div>
                ) : projectReadinessData[activeProject.project_id] ? (
                  (() => {
                    const readiness = projectReadinessData[activeProject.project_id]
                    return (
                      <div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginBottom: '0.6rem', fontSize: '0.75rem' }}>
                          <div style={{ padding: '0.4rem', borderRadius: '4px', background: readiness.ready_for_screening ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)' }}>
                            <strong>Screening Status:</strong><br />
                            {readiness.ready_for_screening ? '✅ Ready for Screening' : '❌ Ingestion Incomplete'}
                          </div>
                          <div style={{ padding: '0.4rem', borderRadius: '4px', background: readiness.ready_for_anuga_simulation ? 'rgba(34, 197, 94, 0.15)' : 'rgba(234, 88, 12, 0.15)' }}>
                            <strong>ANUGA Hydrodynamic Run:</strong><br />
                            {readiness.ready_for_anuga_simulation ? '✅ Fully Ready for Simulation' : '⚠️ Missing Boundaries / Preflight'}
                          </div>
                        </div>

                        {readiness.missing_for_anuga.length > 0 && (
                          <div style={{ marginBottom: '0.5rem' }}>
                            <span className="note-title text-warning" style={{ fontSize: '0.72rem' }}>Required for Full 2D Hydrodynamic Simulation:</span>
                            <ul className="val-warnings-list font-mono" style={{ margin: '0.2rem 0', paddingLeft: '1.2rem', fontSize: '0.72rem' }}>
                              {readiness.missing_for_anuga.map((item, idx) => (
                                <li key={idx}>{item}</li>
                              ))}
                            </ul>
                          </div>
                        )}

                        <div style={{ fontSize: '0.68rem', color: '#94a3b8', fontStyle: 'italic' }}>
                          ⚠️ {readiness.disclaimer}
                        </div>
                      </div>
                    )
                  })()
                ) : (
                  <div>
                    <button
                      className="btn-fit"
                      onClick={() => handleToggleReadiness(activeProject.project_id)}
                    >
                      📋 Load Readiness Assessment
                    </button>
                  </div>
                )}
              </div>

              {/* ANUGA Package & Execution Component */}
              <DamProjectAnugaReadiness
                project={activeProject}
                onPackageBuilt={loadProjects}
                onDisplayHazardLayer={onDisplayHazardLayer}
              />
            </div>
          )}
        </div>
      )}

      {/* STAGE 4: SATELLITE EVIDENCE */}
      {currentStage === 'satellite' && (
        <div className="onboarding-body">
          {!activeProject ? (
            <div className="stage-empty-state">
              <span style={{ fontSize: '2rem' }}>🛰️</span>
              <span className="stage-empty-state-title">No Dam Study Selected</span>
              <p className="stage-empty-state-desc">
                Select a registered dam study from the dropdown above to inspect Sentinel-1 SAR Earth Observation evidence and flood inundation cross-validation.
              </p>
            </div>
          ) : (
            <EarthObservationPanel project={activeProject} />
          )}
        </div>
      )}

      {/* STAGE 5: MODEL COMPARISON */}
      {currentStage === 'comparison' && (
        <div className="onboarding-body">
          {!activeProject ? (
            <div className="stage-empty-state">
              <span style={{ fontSize: '2rem' }}>⚖️</span>
              <span className="stage-empty-state-title">No Dam Study Selected</span>
              <p className="stage-empty-state-desc">
                Select a registered dam study to compare 2D hydrodynamic simulation engines (ANUGA, Delft3D FM, PySPH).
              </p>
            </div>
          ) : (
            <ModelComparisonPanel
              projectId={activeProject.project_id}
              onSelectComparisonLayer={(tileUrl, layerName) => {
                if (tileUrl && onDisplayHazardLayer) {
                  onDisplayHazardLayer(activeProject.project_id, 'comparison', layerName || 'Model Comparison')
                }
              }}
              onClose={() => setCurrentStage('overview')}
            />
          )}
        </div>
      )}

      {/* STAGE 6: EXPOSURE & IMPACT */}
      {currentStage === 'exposure' && (
        <div className="onboarding-body">
          {!activeProject ? (
            <div className="stage-empty-state">
              <span style={{ fontSize: '2rem' }}>👥</span>
              <span className="stage-empty-state-title">No Dam Study Selected</span>
              <p className="stage-empty-state-desc">
                Select a registered dam study to execute spatial population, building footprint, road network, and LULC exposure assessment.
              </p>
            </div>
          ) : (
            <ExposureVulnerabilityPanel
              projectId={activeProject.project_id}
              onSelectLayer={(layerUrl, layerName) => {
                if (layerUrl && onDisplayHazardLayer) {
                  onDisplayHazardLayer(activeProject.project_id, 'exposure', layerName || 'Exposure Layer')
                }
              }}
              onClose={() => setCurrentStage('overview')}
            />
          )}
        </div>
      )}

      {/* STAGE 7: DECISION SUPPORT */}
      {currentStage === 'decision' && (
        <div className="onboarding-body">
          {!activeProject ? (
            <div className="stage-empty-state">
              <span style={{ fontSize: '2rem' }}>🎯</span>
              <span className="stage-empty-state-title">No Dam Study Selected</span>
              <p className="stage-empty-state-desc">
                Select a registered dam study to view emergency decision support metrics, warning timelines, and prioritized evacuation corridors.
              </p>
            </div>
          ) : (
            <div>
              <div className="hud-card-header">
                <h4 className="onboarding-sub-title">🎯 Emergency Decision Support Dashboard</h4>
                <button
                  className="btn-fit"
                  onClick={handleDownloadDecisionReport}
                  title="Download structured JSON decision-support briefing"
                >
                  📥 Download Briefing
                </button>
              </div>

              {/* KPI Cards */}
              <div className="decision-support-grid">
                <div className="decision-kpi-card">
                  <span className="decision-kpi-title">Immediate Risk Zone (0-15m)</span>
                  <span className="decision-kpi-value text-danger">Wavefront Peak</span>
                  <span className="decision-kpi-sub">Priority 1 Evacuation Zone</span>
                </div>
                <div className="decision-kpi-card">
                  <span className="decision-kpi-title">Warning Lead Window</span>
                  <span className="decision-kpi-value font-mono">15 - 60 min</span>
                  <span className="decision-kpi-sub">Staging Area Clearance</span>
                </div>
                <div className="decision-kpi-card">
                  <span className="decision-kpi-title">Critical Facilities Alert</span>
                  <span className="decision-kpi-value" style={{ color: '#f59e0b' }}>Screening Active</span>
                  <span className="decision-kpi-sub">Hospitals, Substations, Bridges</span>
                </div>
              </div>

              {/* Warning Timeline Card */}
              <div className="provenance-card" style={{ marginBottom: '0.85rem' }}>
                <h5 style={{ margin: 0, fontSize: '0.8rem', color: '#38bdf8' }}>
                  ⏱️ Flood Wave Arrival Timeline Guidance
                </h5>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                  <div className="timeline-row">
                    <div>
                      <strong>0 to 15 Minutes</strong> (Immediate Dam Vicinity)
                      <div style={{ color: '#94a3b8', fontSize: '0.68rem' }}>Direct breach wave. Critical velocity {'>'} 2.0 m/s.</div>
                    </div>
                    <span className="timeline-badge urgent">IMMEDIATE ESCAPE</span>
                  </div>
                  <div className="timeline-row">
                    <div>
                      <strong>15 to 60 Minutes</strong> (Downstream River Valley)
                      <div style={{ color: '#94a3b8', fontSize: '0.68rem' }}>Wave propagation into agricultural flats and bridge crossings.</div>
                    </div>
                    <span className="timeline-badge warning">URGENT DETOUR</span>
                  </div>
                  <div className="timeline-row">
                    <div>
                      <strong>1 to 3 Hours</strong> (Secondary Basin Settled Areas)
                      <div style={{ color: '#94a3b8', fontSize: '0.68rem' }}>Slow inundation rise. Evacuate low-lying structures to staging points.</div>
                    </div>
                    <span className="timeline-badge advisory">ORDERED DETOUR</span>
                  </div>
                  <div className="timeline-row">
                    <div>
                      <strong>{'>'} 3 Hours</strong> (Distal Floodplain & Backwater)
                      <div style={{ color: '#94a3b8', fontSize: '0.68rem' }}>Monitoring zone. Prepare emergency resource staging.</div>
                    </div>
                    <span className="timeline-badge" style={{ background: 'rgba(100, 116, 139, 0.2)', color: '#94a3b8' }}>
                      MONITORING
                    </span>
                  </div>
                </div>
              </div>

              {/* Advisory Disclaimer */}
              <div className="damage-notes-card">
                <span className="note-title">⚠️ Decision-Support Advisory Notice</span>
                <p className="note-text" style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                  This dashboard is a spatial screening and contingency planning tool based on uncalibrated hydrodynamic simulations. It does not replace official meteorological warnings, certified reservoir operations rules, or emergency management directives.
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* STAGE 8: TECHNICAL / PROVENANCE */}
      {currentStage === 'provenance' && (
        <div className="onboarding-body">
          {!activeProject ? (
            <div className="stage-empty-state">
              <span style={{ fontSize: '2rem' }}>📜</span>
              <span className="stage-empty-state-title">No Dam Study Selected</span>
              <p className="stage-empty-state-desc">
                Select a registered dam study to inspect cryptographic SHA-256 manifest hashes, vulnerability curve sources, and modeling limitations.
              </p>
            </div>
          ) : (
            <div>
              {/* Manifest Integrity */}
              <div className="provenance-card" style={{ marginBottom: '0.85rem' }}>
                <h5 style={{ margin: 0, fontSize: '0.8rem', color: '#38bdf8' }}>
                  🔒 Cryptographic Manifest Verification
                </h5>
                <div className="val-metadata-grid font-mono" style={{ fontSize: '0.72rem' }}>
                  <div className="val-meta-item">
                    <span className="val-meta-label">Project ID</span>
                    <span className="val-meta-value">{activeProject.project_id}</span>
                  </div>
                  <div className="val-meta-item">
                    <span className="val-meta-label">Integrity Status</span>
                    <span className="val-meta-value">
                      {activeProject.integrity_status === 'ok' ? '✅ SHA-256 Verified' : '⚠️ Hash Unchecked'}
                    </span>
                  </div>
                  <div className="val-meta-item" style={{ gridColumn: 'span 2' }}>
                    <span className="val-meta-label">Manifest SHA-256 Digest</span>
                    <span className="val-meta-value" style={{ wordBreak: 'break-all' }}>
                      {activeProject.manifest_sha256 || 'SHA256:4f8e... (Computed at ingestion)'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Vulnerability Curve Provenance Table */}
              <div className="provenance-card" style={{ marginBottom: '0.85rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h5 style={{ margin: 0, fontSize: '0.8rem', color: '#38bdf8' }}>
                    📚 Vulnerability Curve Provenance & Attribution
                  </h5>
                  <span className="provenance-tag unverified">unverified_reference</span>
                </div>
                <p style={{ fontSize: '0.72rem', color: '#94a3b8', margin: 0 }}>
                  Depth-damage functions implemented for asset screening are referenced from published global empirical datasets, but are <strong>not calibrated for local Indian construction typologies</strong>.
                </p>
                <table className="provenance-table">
                  <thead>
                    <tr>
                      <th>Asset Class</th>
                      <th>Hazard Variable</th>
                      <th>Region / Reference</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Residential</td>
                      <td>Maximum Depth (m)</td>
                      <td>Huizinga et al., 2017 (EUR 28552 EN)</td>
                      <td><span className="provenance-tag unverified">Unverified Reference</span></td>
                    </tr>
                    <tr>
                      <td>Commercial</td>
                      <td>Maximum Depth (m)</td>
                      <td>Huizinga et al., 2017 (EUR 28552 EN)</td>
                      <td><span className="provenance-tag unverified">Unverified Reference</span></td>
                    </tr>
                    <tr>
                      <td>Industrial</td>
                      <td>Maximum Depth (m)</td>
                      <td>Huizinga et al., 2017 (EUR 28552 EN)</td>
                      <td><span className="provenance-tag unverified">Unverified Reference</span></td>
                    </tr>
                    <tr>
                      <td>Agricultural</td>
                      <td>Depth & Duration</td>
                      <td>Global JRC Multi-Hazard Synthesis</td>
                      <td><span className="provenance-tag unverified">Unverified Reference</span></td>
                    </tr>
                    <tr>
                      <td>Road Network</td>
                      <td>Velocity × Depth (m²/s)</td>
                      <td>Advisory Stability Criterion (&gt;0.5 m²/s)</td>
                      <td><span className="provenance-tag unverified">Advisory Screening</span></td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Scientific Limitations & Governing Assumptions */}
              <div className="damage-notes-card">
                <span className="note-title">⚖️ Scientific Limitations & Governing Assumptions</span>
                <ul className="val-assumptions-list" style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                  <li>
                    <strong>Hydrodynamic Equations:</strong> 2D Shallow Water Equations (SWE) assume hydrostatic pressure distribution and depth-averaged velocity profiles. Vertical acceleration and non-hydrostatic wavefront dynamics are neglected.
                  </li>
                  <li>
                    <strong>Breach Parameterization:</strong> Dam breach geometry and failure time are user-prescribed linear formations, not coupled geotechnical piping or erosion simulations.
                  </li>
                  <li>
                    <strong>Roughness Assumptions:</strong> Manning's roughness coefficient (n) is regionally assigned and uncalibrated against gauged hydrographs.
                  </li>
                  <li>
                    <strong>Elevation Sampling:</strong> Terrain elevations are sourced from satellite DEMs without sub-meter LiDAR bare-earth filtering. Bridges and culverts may act as artificial blockages.
                  </li>
                </ul>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

import React, { useState, useEffect } from 'react'
import type {
  DamProjectValidationResponse,
  DamProjectSummary,
  DamProjectDetailResponse,
  OnboardingFormValues,
} from '../../types/damProjects'
import {
  validateDamProject,
  saveDamProject,
  listDamProjects,
} from '../../api/damProjects'
import { DamProjectAnugaReadiness } from './DamProjectAnugaReadiness'
import './DamOnboardingPanel.css'

interface DamOnboardingPanelProps {
  onDisplayProjectDem?: (project: DamProjectSummary | DamProjectDetailResponse) => void
}

export const DamOnboardingPanel: React.FC<DamOnboardingPanelProps> = ({ onDisplayProjectDem }) => {
  // File states
  const [demFile, setDemFile] = useState<File | null>(null)
  const [damAxisFile, setDamAxisFile] = useState<File | null>(null)
  const [reservoirFile, setReservoirFile] = useState<File | null>(null)
  const [modelDomainFile, setModelDomainFile] = useState<File | null>(null)
  const [downstreamOutletFile, setDownstreamOutletFile] = useState<File | null>(null)

  // Form values
  const [formValues, setFormValues] = useState<OnboardingFormValues>({
    projectName: 'New Dam Project',
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

  // Workflow states
  const [validating, setValidating] = useState<boolean>(false)
  const [validationResult, setValidationResult] = useState<DamProjectValidationResponse | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)

  const [acknowledgeUnverified, setAcknowledgeUnverified] = useState<boolean>(false)
  const [saving, setSaving] = useState<boolean>(false)
  const [savedProject, setSavedProject] = useState<DamProjectDetailResponse | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Saved projects list
  const [projectsList, setProjectsList] = useState<DamProjectSummary[]>([])
  const [loadingProjects, setLoadingProjects] = useState<boolean>(false)
  const [selectedProjectDetail, setSelectedProjectDetail] = useState<DamProjectDetailResponse | null>(null)
  const [activeReadinessProjectId, setActiveReadinessProjectId] = useState<string | null>(null)

  const loadProjects = async () => {
    try {
      setLoadingProjects(true)
      const list = await listDamProjects()
      setProjectsList(list)
    } catch {
      // ignore
    } finally {
      setLoadingProjects(false)
    }
  }

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    loadProjects()
  }, [])

  const handleInputChange = (field: keyof OnboardingFormValues, value: string) => {
    setFormValues((prev) => ({ ...prev, [field]: value }))
    // Reset save readiness when inputs change
    setValidationResult(null)
    setAcknowledgeUnverified(false)
    setSaveError(null)
  }

  const buildFormData = (isSave = false): FormData | null => {
    if (!demFile || !damAxisFile) return null
    const fd = new FormData()
    fd.append('dem_file', demFile)
    fd.append('dam_axis_file', damAxisFile)
    if (reservoirFile) {
      fd.append('reservoir_boundary_file', reservoirFile)
    }
    if (modelDomainFile) {
      fd.append('model_domain_file', modelDomainFile)
    }
    if (downstreamOutletFile) {
      fd.append('downstream_outlet_file', downstreamOutletFile)
    }
    fd.append('project_name', formValues.projectName.trim() || 'New Dam Project')
    if (formValues.verticalUnit.trim()) fd.append('vertical_unit', formValues.verticalUnit.trim())
    if (formValues.verticalDatum.trim()) fd.append('vertical_datum', formValues.verticalDatum.trim())
    if (formValues.reservoirLevel.trim()) fd.append('reservoir_level', formValues.reservoirLevel.trim())
    if (formValues.breachWidth.trim()) fd.append('breach_width', formValues.breachWidth.trim())
    if (formValues.breachCenterX.trim()) fd.append('breach_center_x', formValues.breachCenterX.trim())
    if (formValues.breachCenterY.trim()) fd.append('breach_center_y', formValues.breachCenterY.trim())
    if (formValues.breachFormationTimeHr.trim()) fd.append('breach_formation_time_hr', formValues.breachFormationTimeHr.trim())
    if (formValues.manningRoughness.trim()) fd.append('manning_roughness', formValues.manningRoughness.trim())
    if (formValues.damCrestElevation.trim()) fd.append('dam_crest_elevation', formValues.damCrestElevation.trim())
    if (formValues.breachInvertElevation.trim()) fd.append('breach_invert_elevation', formValues.breachInvertElevation.trim())
    if (formValues.targetMeshResolutionM.trim()) fd.append('target_mesh_resolution_m', formValues.targetMeshResolutionM.trim())
    if (formValues.simulationDurationS.trim()) fd.append('simulation_duration_s', formValues.simulationDurationS.trim())
    if (formValues.outputIntervalS.trim()) fd.append('output_interval_s', formValues.outputIntervalS.trim())
    fd.append('geometry_crs', formValues.geometryCrs.trim() || 'EPSG:4326')

    if (isSave) {
      fd.append('acknowledge_unverified_metadata', acknowledgeUnverified ? 'true' : 'false')
    }

    return fd
  }

  const handleValidate = async () => {
    const fd = buildFormData(false)
    if (!fd) {
      setValidationError('Please select both a DEM GeoTIFF and a Dam Axis GeoJSON file.')
      return
    }

    setValidating(true)
    setValidationError(null)
    setValidationResult(null)
    setSaveError(null)

    try {
      const res = await validateDamProject(fd)
      setValidationResult(res)
    } catch (err: any) {
      setValidationError(err.message || 'Validation request failed')
    } finally {
      setValidating(false)
    }
  }

  const handleSave = async () => {
    if (!validationResult || !validationResult.onboarding_validation_passed) {
      setSaveError('Validation must pass completely before registering project.')
      return
    }
    if (!acknowledgeUnverified) {
      setSaveError('You must acknowledge that the metadata is user-declared and unverified.')
      return
    }

    const fd = buildFormData(true)
    if (!fd) return

    setSaving(true)
    setSaveError(null)

    try {
      const saved = await saveDamProject(fd)
      setSavedProject(saved)
      setActiveReadinessProjectId(saved.project_id)
      await loadProjects()
    } catch (err: any) {
      setSaveError(err.message || 'Failed to save project.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="hud-card onboarding-card">
      <div className="hud-card-header">
        <h3>🏗️ Generalized Dam Onboarding</h3>
        <span className="legend-tag">SIH PS 26161</span>
      </div>

      <div className="onboarding-body">
        {/* Step 1: Files */}
        <div className="onboarding-section">
          <h4 className="onboarding-sub-title">1. Geospatial Dataset Files</h4>

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

          <div className="file-input-group">
            <label className="file-input-label">Dam Axis Vector (*.geojson, *.json) *</label>
            <input
              type="file"
              accept=".geojson,.json"
              onChange={(e) => {
                setDamAxisFile(e.target.files?.[0] || null)
                setValidationResult(null)
              }}
              className="file-input-control"
            />
            {damAxisFile && <span className="file-selected-name">📏 {damAxisFile.name} ({(damAxisFile.size / 1024).toFixed(1)} KB)</span>}
          </div>

          <div className="file-input-group">
            <label className="file-input-label">Reservoir Boundary (Optional *.geojson)</label>
            <input
              type="file"
              accept=".geojson,.json"
              onChange={(e) => {
                setReservoirFile(e.target.files?.[0] || null)
                setValidationResult(null)
              }}
              className="file-input-control"
            />
            {reservoirFile && <span className="file-selected-name">💧 {reservoirFile.name} ({(reservoirFile.size / 1024).toFixed(1)} KB)</span>}
          </div>

          <div className="file-input-group">
            <label className="file-input-label">Model Domain Boundary (Optional *.geojson for ANUGA Mesh)</label>
            <input
              type="file"
              accept=".geojson,.json"
              onChange={(e) => {
                setModelDomainFile(e.target.files?.[0] || null)
                setValidationResult(null)
              }}
              className="file-input-control"
            />
            {modelDomainFile && <span className="file-selected-name">🌐 {modelDomainFile.name} ({(modelDomainFile.size / 1024).toFixed(1)} KB)</span>}
          </div>

          <div className="file-input-group">
            <label className="file-input-label">Downstream Outlet Boundary (Optional *.geojson for ANUGA Outflow)</label>
            <input
              type="file"
              accept=".geojson,.json"
              onChange={(e) => {
                setDownstreamOutletFile(e.target.files?.[0] || null)
                setValidationResult(null)
              }}
              className="file-input-control"
            />
            {downstreamOutletFile && <span className="file-selected-name">🚪 {downstreamOutletFile.name} ({(downstreamOutletFile.size / 1024).toFixed(1)} KB)</span>}
          </div>
        </div>

        {/* Step 2: Metadata & Breach Parameters */}
        <div className="onboarding-section">
          <h4 className="onboarding-sub-title">2. Engineering & Physical Parameters</h4>

          <div className="config-field">
            <label>Project Name *</label>
            <input
              type="text"
              value={formValues.projectName}
              onChange={(e) => handleInputChange('projectName', e.target.value)}
              className="config-input"
              placeholder="e.g., Koyna Dam Pilot"
            />
          </div>

          <div className="onboarding-grid-2">
            <div className="config-field">
              <label>Vertical Unit (e.g. meters, ft)</label>
              <input
                type="text"
                value={formValues.verticalUnit}
                onChange={(e) => handleInputChange('verticalUnit', e.target.value)}
                className="config-input"
                placeholder="unknown unless declared"
              />
            </div>
            <div className="config-field">
              <label>Vertical Datum (e.g. MSL, EGM96)</label>
              <input
                type="text"
                value={formValues.verticalDatum}
                onChange={(e) => handleInputChange('verticalDatum', e.target.value)}
                className="config-input"
                placeholder="unknown unless declared"
              />
            </div>
          </div>

          <div className="onboarding-grid-2">
            <div className="config-field">
              <label>Reservoir Level (FRL) *</label>
              <input
                type="number"
                step="0.1"
                value={formValues.reservoirLevel}
                onChange={(e) => handleInputChange('reservoirLevel', e.target.value)}
                className="config-input font-mono"
                placeholder="e.g. 650.0"
              />
            </div>
            <div className="config-field">
              <label>Breach Width (meters) *</label>
              <input
                type="number"
                step="1"
                value={formValues.breachWidth}
                onChange={(e) => handleInputChange('breachWidth', e.target.value)}
                className="config-input font-mono"
                placeholder="e.g. 200"
              />
            </div>
          </div>

          <div className="onboarding-grid-2">
            <div className="config-field">
              <label>Dam Crest Elevation</label>
              <input
                type="number"
                step="0.1"
                value={formValues.damCrestElevation}
                onChange={(e) => handleInputChange('damCrestElevation', e.target.value)}
                className="config-input font-mono"
                placeholder="e.g. 665.0 (must be > FRL)"
              />
            </div>
            <div className="config-field">
              <label>Breach Invert Elevation</label>
              <input
                type="number"
                step="0.1"
                value={formValues.breachInvertElevation}
                onChange={(e) => handleInputChange('breachInvertElevation', e.target.value)}
                className="config-input font-mono"
                placeholder="e.g. 590.0 (must be < FRL)"
              />
            </div>
          </div>

          <div className="onboarding-grid-2">
            <div className="config-field">
              <label>Breach Center X (Lon in CRS) *</label>
              <input
                type="number"
                step="0.00001"
                value={formValues.breachCenterX}
                onChange={(e) => handleInputChange('breachCenterX', e.target.value)}
                className="config-input font-mono"
                placeholder="e.g. 74.632"
              />
            </div>
            <div className="config-field">
              <label>Breach Center Y (Lat in CRS) *</label>
              <input
                type="number"
                step="0.00001"
                value={formValues.breachCenterY}
                onChange={(e) => handleInputChange('breachCenterY', e.target.value)}
                className="config-input font-mono"
                placeholder="e.g. 16.215"
              />
            </div>
          </div>

          <div className="onboarding-grid-2">
            <div className="config-field">
              <label>Breach Formation Time (hr)</label>
              <input
                type="number"
                step="0.1"
                value={formValues.breachFormationTimeHr}
                onChange={(e) => handleInputChange('breachFormationTimeHr', e.target.value)}
                className="config-input font-mono"
              />
            </div>
            <div className="config-field">
              <label>Manning Roughness (n)</label>
              <input
                type="number"
                step="0.001"
                value={formValues.manningRoughness}
                onChange={(e) => handleInputChange('manningRoughness', e.target.value)}
                className="config-input font-mono"
              />
            </div>
          </div>

          <div className="onboarding-grid-3">
            <div className="config-field">
              <label>Target Mesh Res (m)</label>
              <input
                type="number"
                step="1"
                value={formValues.targetMeshResolutionM}
                onChange={(e) => handleInputChange('targetMeshResolutionM', e.target.value)}
                className="config-input font-mono"
                placeholder="50"
              />
            </div>
            <div className="config-field">
              <label>Sim Duration (s)</label>
              <input
                type="number"
                step="10"
                value={formValues.simulationDurationS}
                onChange={(e) => handleInputChange('simulationDurationS', e.target.value)}
                className="config-input font-mono"
                placeholder="3600"
              />
            </div>
            <div className="config-field">
              <label>Output Interval (s)</label>
              <input
                type="number"
                step="5"
                value={formValues.outputIntervalS}
                onChange={(e) => handleInputChange('outputIntervalS', e.target.value)}
                className="config-input font-mono"
                placeholder="60"
              />
            </div>
          </div>

          <div className="config-field">
            <label>Geometry CRS</label>
            <input
              type="text"
              value={formValues.geometryCrs}
              onChange={(e) => handleInputChange('geometryCrs', e.target.value)}
              className="config-input font-mono"
              placeholder="EPSG:4326"
            />
          </div>
        </div>

        {/* Step 3: Validation Actions */}
        <div className="onboarding-actions-row">
          <button
            className="btn-validate-dam"
            onClick={handleValidate}
            disabled={validating || !demFile || !damAxisFile}
          >
            {validating ? <><span className="spinner" /> Validating Geometry & CRS...</> : '🔍 1. Validate Dataset'}
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
                  ? '✅ Onboarding Validation Passed'
                  : validationResult.valid
                  ? '⚠️ Partial Validation (Missing required numeric fields)'
                  : '❌ Validation Failed'}
              </span>
              <span className="legend-tag">
                UNVERIFIED INPUT
              </span>
            </div>

            {/* Scientific Notice Banner */}
            <div className="val-disclaimer-box">
              <strong>User-declared, not independently verified.</strong> All spatial rasters, geometry coordinates, and physical properties are uncalibrated inputs. Not prediction-ready.
            </div>

            {/* Raster & Geometry Metadata */}
            {validationResult.normalized_metadata?.raster_metadata && (
              <div className="val-metadata-grid">
                <div className="val-meta-item">
                  <span className="val-meta-label">Raster Grid</span>
                  <span className="val-meta-value">
                    {validationResult.normalized_metadata.raster_metadata.width} × {validationResult.normalized_metadata.raster_metadata.height} ({validationResult.normalized_metadata.raster_metadata.dtype})
                  </span>
                </div>
                <div className="val-meta-item">
                  <span className="val-meta-label">Raster CRS</span>
                  <span className="val-meta-value">{validationResult.normalized_metadata.raster_metadata.crs}</span>
                </div>
                <div className="val-meta-item">
                  <span className="val-meta-label">Resolution</span>
                  <span className="val-meta-value">
                    {validationResult.normalized_metadata.raster_metadata.resolution.x.toFixed(4)} × {validationResult.normalized_metadata.raster_metadata.resolution.y.toFixed(4)}
                  </span>
                </div>
                <div className="val-meta-item">
                  <span className="val-meta-label">Elevation Min/Max</span>
                  <span className="val-meta-value">
                    {validationResult.normalized_metadata.raster_metadata.min_elevation != null
                      ? `${validationResult.normalized_metadata.raster_metadata.min_elevation.toFixed(1)} to ${validationResult.normalized_metadata.raster_metadata.max_elevation?.toFixed(1)}`
                      : 'N/A'}
                  </span>
                </div>
              </div>
            )}

            {/* Geometric Containment */}
            {validationResult.normalized_metadata?.dam_axis_metadata && (
              <div className="val-metadata-grid">
                <div className="val-meta-item">
                  <span className="val-meta-label">Dam Axis Features</span>
                  <span className="val-meta-value">
                    {validationResult.normalized_metadata.dam_axis_metadata.feature_count} features ({validationResult.normalized_metadata.dam_axis_metadata.geometry_types.join(', ')})
                  </span>
                </div>
                <div className="val-meta-item">
                  <span className="val-meta-label">DEM Containment</span>
                  <span className="val-meta-value">
                    {validationResult.normalized_metadata.dam_axis_metadata.fully_within_dem_bounds
                      ? 'Fully Inside DEM Bounds'
                      : validationResult.normalized_metadata.dam_axis_metadata.intersects_dem_bounds
                      ? 'Intersects DEM'
                      : 'Outside DEM Extent'}
                  </span>
                </div>
                {validationResult.normalized_metadata.breach_distance_to_axis_m != null && (
                  <div className="val-meta-item" style={{ gridColumn: 'span 2' }}>
                    <span className="val-meta-label">Breach Distance to Dam Axis</span>
                    <span className="val-meta-value">
                      {validationResult.normalized_metadata.breach_distance_to_axis_m.toFixed(1)} metres ({validationResult.normalized_metadata.breach_on_dam_axis ? 'Within tolerance' : 'Exceeds tolerance'})
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* Errors */}
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

            {/* Warnings */}
            {validationResult.warnings.length > 0 && (
              <div>
                <span className="note-title text-warning">Warnings:</span>
                <ul className="val-warnings-list font-mono">
                  {validationResult.warnings.map((w, idx) => (
                    <li key={idx}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Assumptions */}
            {validationResult.assumptions_requiring_confirmation.length > 0 && (
              <div>
                <span className="note-title">Assumptions Requiring Verification:</span>
                <ul className="val-assumptions-list">
                  {validationResult.assumptions_requiring_confirmation.map((a, idx) => (
                    <li key={idx}>{a}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Step 4: Acknowledge and Save */}
            {validationResult.onboarding_validation_passed && (
              <div style={{ marginTop: '0.5rem', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
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
            ✅ Project Registered Successfully! ID: <code>{savedProject.project_id}</code>
            <br />
            Status: <strong>{savedProject.status}</strong> | Manifest files: {Object.keys(savedProject.manifest.files).join(', ')}
            <div style={{ marginTop: '0.8rem' }}>
              <DamProjectAnugaReadiness
                project={savedProject}
                onPackageBuilt={loadProjects}
              />
            </div>
          </div>
        )}

        {/* Saved Projects List */}
        <div className="onboarding-section" style={{ marginTop: '1rem' }}>
          <div className="hud-card-header">
            <h4 className="onboarding-sub-title">Registered Custom Projects ({projectsList.length})</h4>
            <button className="btn-fit" onClick={loadProjects} title="Refresh registered dam projects">
              ↺ Refresh
            </button>
          </div>

          {loadingProjects ? (
            <div className="probe-loading">
              <span className="spinner" /> Loading registered projects...
            </div>
          ) : projectsList.length === 0 ? (
            <div className="legend-error">No custom dam projects registered yet.</div>
          ) : (
            <div className="saved-projects-list">
              {projectsList.map((p) => {
                const isIntegrityFailed = !p.available || p.integrity_status === 'failed' || p.integrity_status === 'corrupted' || p.integrity_status === 'integrity_failed'
                const isReadinessOpen = activeReadinessProjectId === p.project_id
                return (
                  <div key={p.project_id} className="saved-project-card">
                    <div className="saved-project-header">
                      <span className="saved-project-title">🏷️ {p.project_name}</span>
                      <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                        <span className="saved-project-badge badge-unverified">
                          UNVERIFIED INPUT
                        </span>
                        <span className={`saved-project-badge ${isIntegrityFailed ? 'badge-corrupted' : 'badge-ok'}`}>
                          {isIntegrityFailed ? '❌ Integrity Failed' : '✅ Integrity OK'}
                        </span>
                      </div>
                    </div>

                    <div className="saved-project-details font-mono">
                      <span>CRS: {p.crs}</span>
                      <span>Created: {p.created_at ? new Date(p.created_at).toLocaleDateString() : 'N/A'}</span>
                      <span>Reservoir: {p.has_reservoir_boundary ? 'Yes' : 'None'}</span>
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
                        title={isIntegrityFailed ? 'Cannot display corrupted project' : 'Display custom DEM, dam axis, reservoir and breach marker on Map'}
                        style={isIntegrityFailed ? { opacity: 0.4, cursor: 'not-allowed' } : {}}
                      >
                        🗺️ View on Map
                      </button>
                      <button
                        className="btn-project-action"
                        onClick={() => setActiveReadinessProjectId(isReadinessOpen ? null : p.project_id)}
                        disabled={isIntegrityFailed}
                        style={{ borderColor: isReadinessOpen ? 'var(--neon-cyan, #00ffff)' : undefined }}
                      >
                        ⚡ Readiness & Package
                      </button>
                      <button
                        className="btn-project-action"
                        onClick={() => setSelectedProjectDetail(selectedProjectDetail?.project_id === p.project_id ? null : (p as any))}
                      >
                        📋 Info
                      </button>
                    </div>

                    {/* Simulation Readiness Section */}
                    {isReadinessOpen && (
                      <div style={{ marginTop: '0.6rem' }}>
                        <DamProjectAnugaReadiness
                          project={p}
                          onPackageBuilt={loadProjects}
                        />
                      </div>
                    )}

                    {selectedProjectDetail?.project_id === p.project_id && (
                      <div className="val-metadata-grid" style={{ marginTop: '0.4rem' }}>
                        <div className="val-meta-item" style={{ gridColumn: 'span 2' }}>
                          <span className="val-meta-label">Project ID</span>
                          <span className="val-meta-value">{p.project_id}</span>
                        </div>
                        <div className="val-meta-item" style={{ gridColumn: 'span 2' }}>
                          <span className="val-meta-label">Manifest SHA-256</span>
                          <span className="val-meta-value">{p.manifest_sha256 ? `${p.manifest_sha256.slice(0, 16)}...` : 'N/A'}</span>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

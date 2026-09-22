import React, { useState, useEffect, useCallback } from 'react'
import type {
  DamProjectValidationResponse,
  DamProjectSummary,
  DamProjectDetailResponse,
  DamProjectReadinessResponse,
  OnboardingFormValues,
  DemoReadinessResponse,
} from '../../types/damProjects'
import type { SPHAnimationFrame } from '../../api/damProjects'
import {
  validateDamProject,
  saveDamProject,
  listDamProjects,
  fetchDamProjectReadiness,
  fetchDemoReadiness,
  loadHidkalDemoProject,
  loadRiverBlockageDemoProject,
} from '../../api/damProjects'
import { DamProjectAnugaReadiness } from './DamProjectAnugaReadiness'
import { EarthObservationPanel } from './EarthObservationPanel'
import { ModelComparisonPanel } from './ModelComparisonPanel'
import { ExposureVulnerabilityPanel } from './ExposureVulnerabilityPanel'
import { SystemHealthPanel } from './SystemHealthPanel'
import { DecisionSupportDashboard } from './DecisionSupportDashboard'
import { WorkflowSummaryDashboard } from './WorkflowSummaryDashboard'
import { ThreeSphSimulation } from '../ThreeSphSimulation'
import './DamOnboardingPanel.css'

export type ProductStage =
  | 'overview'
  | 'setup'
  | 'simulation'
  | 'three_sph'
  | 'results'
  | 'decision_support'
  | 'comparison'
  | 'workflow_summary'
  | 'satellite'
  | 'exposure'
  | 'export'

interface DamOnboardingPanelProps {
  onDisplayProjectDem?: (project: DamProjectSummary | DamProjectDetailResponse) => void
  onDisplayHazardLayer?: (projectId: string, runId: string, layer: string, processingId?: string) => void
  onDisplayTimestepLayer?: (projectId: string, runId: string, stepIdx: number, processingId?: string) => void
  onDisplaySPHParticleFrame?: (frameData: SPHAnimationFrame, colorMode: 'depth' | 'velocity') => void
  onClearSPHParticleLayer?: () => void
  onUpdateDamBreachState?: (isOpen: boolean) => void
}

export const DamOnboardingPanel: React.FC<DamOnboardingPanelProps> = ({
  onDisplayProjectDem,
  onDisplayHazardLayer,
  onDisplayTimestepLayer,
  onDisplaySPHParticleFrame,
  onClearSPHParticleLayer,
  onUpdateDamBreachState,
}) => {
  // Navigation stage state (8-Step User Journey)
  const [currentStage, setCurrentStage] = useState<ProductStage>('overview')

  // Export Stage State
  const [exportLayer, setExportLayer] = useState<'assets' | 'roads'>('assets')
  const [exportFormat, setExportFormat] = useState<'geojson' | 'kml' | 'shp'>('shp')
  const [exportFilter, setExportFilter] = useState<'all' | 'screening_positive' | 'not_exposed' | 'not_assessed'>('all')
  const [exportLoading, setExportLoading] = useState<boolean>(false)
  const [exportSuccessMsg, setExportSuccessMsg] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

  const handleDownloadExport = async () => {
    setExportLoading(true)
    setExportError(null)
    setExportSuccessMsg(null)
    try {
      const url = `${apiBaseUrl}/api/export/${exportLayer}?format=${exportFormat}&exposure_filter=${exportFilter}&hazard_source=sample_hidkal`
      const res = await fetch(url)
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `Export failed with HTTP ${res.status}`)
      }
      const blob = await res.blob()
      const ext = exportFormat === 'shp' ? 'zip' : exportFormat
      const filename = `${exportLayer}_export_${exportFilter}.${ext}`
      const downloadUrl = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = downloadUrl
      link.download = filename
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(downloadUrl)
      setExportSuccessMsg(`Successfully generated and downloaded ${filename}`)
    } catch (err: any) {
      setExportError(err.message || 'Failed to download export package.')
    } finally {
      setExportLoading(false)
    }
  }

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
  const [_projectReadinessData, setProjectReadinessData] = useState<Record<string, DamProjectReadinessResponse>>({})
  const [demoReadiness, setDemoReadiness] = useState<DemoReadinessResponse | null>(null)
  const [loadingDemo, setLoadingDemo] = useState<boolean>(false)
  const [demoLoadError, setDemoLoadError] = useState<string | null>(null)

  const handleToggleReadiness = async (projectId: string) => {
    try {
      const readiness = await fetchDamProjectReadiness(projectId)
      setProjectReadinessData((prev) => ({ ...prev, [projectId]: readiness }))
    } catch (err) {
      console.error('Failed to load readiness:', err)
    }
  }

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

  const handleLoadHidkalDemo = async () => {
    setLoadingDemo(true)
    setDemoLoadError(null)
    try {
      const demoProj = await loadHidkalDemoProject()
      await loadProjects()
      setSelectedProjectId(demoProj.project_id)
      if (onDisplayProjectDem) {
        onDisplayProjectDem(demoProj)
      }
      setCurrentStage('simulation')
    } catch (err: any) {
      setDemoLoadError(err.message || 'Failed to load Hidkal demo project.')
    } finally {
      setLoadingDemo(false)
    }
  }

  const handleLoadRiverBlockageDemo = async () => {
    setLoadingDemo(true)
    setDemoLoadError(null)
    try {
      const demoProj = await loadRiverBlockageDemoProject()
      await loadProjects()
      setSelectedProjectId(demoProj.project_id)
      if (onDisplayProjectDem) {
        onDisplayProjectDem(demoProj)
      }
      setCurrentStage('simulation')
    } catch (err: any) {
      setDemoLoadError(err.message || 'Failed to load River Blockage demo project.')
    } finally {
      setLoadingDemo(false)
    }
  }

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    loadProjects()
  }, [loadProjects])

  useEffect(() => {
    if (selectedProjectId) {
      fetchDemoReadiness(selectedProjectId)
        .then(setDemoReadiness)
        .catch(() => setDemoReadiness(null))
    } else {
      // oxlint-disable-next-line react/set-state-in-effect
      setDemoReadiness(null)
    }
  }, [selectedProjectId])

  const activeProject = projectsList.find((p) => p.project_id === selectedProjectId) || (projectsList.length > 0 ? projectsList[0] : null)

  const CORE_VALIDATION_FIELDS: (keyof OnboardingFormValues)[] = [
    'projectName',
    'damName',
    'latitude',
    'longitude',
  ]

  const handleInputChange = (field: keyof OnboardingFormValues, value: string) => {
    setFormValues((prev) => ({ ...prev, [field]: value }))
    setSaveError(null)
    // Invalidate validation result only when core geometric/identity fields change
    if (CORE_VALIDATION_FIELDS.includes(field)) {
      setValidationResult(null)
    }
    // Per requirements: Do NOT reset acknowledgeUnverified on input or optional field changes.
    // Only reset after successful project registration or explicit form reset.
  }

  const handleResetForm = () => {
    setDemFile(null)
    setDamAxisFile(null)
    setReservoirFile(null)
    setModelDomainFile(null)
    setDownstreamOutletFile(null)
    setFormValues({
      projectName: 'New Dam Study',
      scenarioType: 'DAM_BREAK',
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
    setValidationResult(null)
    setValidationError(null)
    setAcknowledgeUnverified(false)
    setSavedProject(null)
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
    if (formValues.scenarioType) fd.append('scenario_type', formValues.scenarioType)
    if (formValues.is_intact_control !== undefined) fd.append('is_intact_control', formValues.is_intact_control ? 'true' : 'false')
    fd.append('latitude', formValues.latitude)
    fd.append('longitude', formValues.longitude)

    if (formValues.damHeight) fd.append('dam_height', formValues.damHeight)
    if (formValues.crestElevation) fd.append('crest_elevation', formValues.crestElevation)
    if (formValues.poolElevation) fd.append('pool_elevation', formValues.poolElevation)
    if (formValues.manningN) fd.append('manning_n', formValues.manningN)
    if (formValues.verticalUnit) fd.append('vertical_unit', formValues.verticalUnit)
    if (formValues.verticalDatum) fd.append('vertical_datum', formValues.verticalDatum)

    if (formValues.blockageHeight) fd.append('blockage_height', formValues.blockageHeight)
    if (formValues.blockageCrestElevation) fd.append('blockage_crest_elevation', formValues.blockageCrestElevation)
    if (formValues.blockageWidth) fd.append('blockage_width', formValues.blockageWidth)
    if (formValues.upstreamWaterLevel) fd.append('upstream_water_level', formValues.upstreamWaterLevel)
    if (formValues.openingWidth) fd.append('opening_width', formValues.openingWidth)

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

      // Exact backend required field name: acknowledge_unverified_metadata
      fd.append('acknowledge_unverified_metadata', acknowledgeUnverified ? 'true' : 'false')
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

    // Temporary console logging to verify acknowledgment state and payload
    console.log('[Study Setup Registration] Acknowledgment state before submit:', acknowledgeUnverified)
    console.log(
      '[Study Setup Registration] Final registration payload entries:',
      Array.from(fd.entries()).map(([k, v]) => [k, v instanceof File ? `File(${v.name}, ${v.size}B)` : v])
    )

    setSaving(true)
    setSaveError(null)

    try {
      const saved = await saveDamProject(fd)
      console.log('[Study Setup Registration] Backend response:', saved)
      setSavedProject(saved)
      setSelectedProjectId(saved.project_id)
      // Only reset acknowledgment state after successful project registration
      setAcknowledgeUnverified(false)
      await loadProjects()
      await handleToggleReadiness(saved.project_id)
    } catch (err: any) {
      console.error('[Study Setup Registration] Backend error:', err)
      setSaveError(err.message || 'Failed to save project.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="hud-card onboarding-card">
      <div className="hud-card-header">
        <h3>🏛️ Dam Inundation & Hydrodynamic Analysis</h3>
        <span className="legend-tag">SIH 26161 • DECISION SUPPORT</span>
      </div>

      {/* 8-Step User Journey Navigation */}
      <div className="product-stage-nav" role="tablist" aria-label="Workflow Stages">
        <button
          className={`product-stage-btn ${currentStage === 'overview' ? 'active' : ''}`}
          onClick={() => setCurrentStage('overview')}
          title="Project overview, system health, and registered studies"
        >
          <span>🌐</span> 1. Project Input
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'setup' ? 'active' : ''}`}
          onClick={() => setCurrentStage('setup')}
          title="Ingest DEM GeoTIFF and configure dam geometry"
        >
          <span>📐</span> 2. Terrain & Geometry
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'simulation' ? 'active' : ''}`}
          onClick={() => setCurrentStage('simulation')}
          title="Hydrodynamic solver readiness and simulation execution"
        >
          <span>⚡</span> 3. Simulation
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'three_sph' ? 'active' : ''}`}
          onClick={() => setCurrentStage('three_sph')}
          title="Interactive Three.js 3D hydrodynamic particle & terrain visualization"
        >
          <span>🧊</span> 3D SPH Sim
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'results' ? 'active' : ''}`}
          onClick={() => setCurrentStage('results')}
          title="Hazard depth, velocity, arrival time maps & transient flood animation"
        >
          <span>🌊</span> 4. Flood Results
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'decision_support' ? 'active' : ''}`}
          onClick={() => setCurrentStage('decision_support')}
          title="Hydrodynamic decision-support dashboard, hydraulic severity, and downstream intelligence"
        >
          <span>📊</span> 5. Decision Support
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'comparison' ? 'active' : ''}`}
          onClick={() => setCurrentStage('comparison')}
          title="Near-Field SPH vs Regional ANUGA hydrodynamic comparison"
        >
          <span>⚖️</span> 6. SPH vs ANUGA
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'workflow_summary' ? 'active' : ''}`}
          onClick={() => setCurrentStage('workflow_summary')}
          title="Unified end-to-end workflow dashboard (PySPH, ANUGA, Delft3D FM, HADR, GEE & GIS Exports)"
        >
          <span>📋</span> 7. Unified Summary
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'satellite' ? 'active' : ''}`}
          onClick={() => setCurrentStage('satellite')}
          title="Sentinel-1 SAR Earth Observation & candidate water change"
        >
          <span>🛰️</span> 8. Satellite Evidence
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'exposure' ? 'active' : ''}`}
          onClick={() => setCurrentStage('exposure')}
          title="Population, buildings, roads, and infrastructure exposure"
        >
          <span>👥</span> 9. Exposure & Damage
        </button>
        <button
          className={`product-stage-btn ${currentStage === 'export' ? 'active' : ''}`}
          onClick={() => setCurrentStage('export')}
          title="Export Shapefile, KML, and GeoJSON GIS datasets"
        >
          <span>💾</span> 10. Export
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
              {demoReadiness && (
                <span
                  className="saved-project-badge"
                  style={{
                    background: demoReadiness.is_ready ? '#059669' : '#d97706',
                    color: '#fff',
                    fontWeight: 700,
                  }}
                  title={demoReadiness.summary_message}
                >
                  {demoReadiness.status_badge}
                </span>
              )}
              {(activeProject.provenance === 'HYPOTHETICAL_UNVERIFIED' || activeProject.project_name.toLowerCase().includes('demo') || activeProject.project_name.toLowerCase().includes('hypothetical')) ? (
                <>
                  <span className="saved-project-badge" style={{ background: '#7c3aed', color: '#fff' }} title="Not for engineering or operational decision-making.">
                    🧪 HYPOTHETICAL DEMO
                  </span>
                  <span className="saved-project-badge badge-unverified" title="Not for engineering or operational decision-making.">
                    NOT FOR OPERATIONAL USE
                  </span>
                </>
              ) : (
                <span className="saved-project-badge badge-unverified">
                  {activeProject.scientific_status || 'UNVERIFIED'}
                </span>
              )}
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

      {/* SIH Presenter Quick Switch Bar */}
      {activeProject && currentStage !== 'overview' && (
        <div style={{
          display: 'flex',
          gap: '0.35rem',
          padding: '0.35rem 0.75rem',
          background: '#0f172a',
          borderBottom: '1px solid #334155',
          alignItems: 'center',
          overflowX: 'auto',
          fontSize: '0.72rem',
        }}>
          <span style={{ color: '#94a3b8', fontWeight: 600, whiteSpace: 'nowrap' }}>⚡ Quick Switch:</span>
          <button
            className="btn-fit"
            style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem' }}
            onClick={() => setCurrentStage('overview')}
          >
            📋 1. Scenario
          </button>
          <button
            className={`btn-fit ${currentStage === 'three_sph' ? 'active' : ''}`}
            style={{
              fontSize: '0.68rem',
              padding: '0.15rem 0.45rem',
              background: currentStage === 'three_sph' ? '#0284c7' : undefined,
              color: currentStage === 'three_sph' ? '#fff' : undefined,
            }}
            onClick={() => setCurrentStage('three_sph')}
          >
            🧊 3D Visualizer
          </button>
          <button
            className={`btn-fit ${currentStage === 'results' ? 'active' : ''}`}
            style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem' }}
            onClick={() => setCurrentStage('results')}
          >
            🌊 4. ANUGA Flood
          </button>
          <button
            className={`btn-fit ${currentStage === 'decision_support' ? 'active' : ''}`}
            style={{
              fontSize: '0.68rem',
              padding: '0.15rem 0.45rem',
              background: currentStage === 'decision_support' ? '#0284c7' : undefined,
              color: currentStage === 'decision_support' ? '#fff' : undefined,
            }}
            onClick={() => setCurrentStage('decision_support')}
          >
            📊 5. Decision Support
          </button>
          <button
            className={`btn-fit ${currentStage === 'comparison' ? 'active' : ''}`}
            style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem' }}
            onClick={() => setCurrentStage('comparison')}
          >
            ⚖️ 6. SPH vs ANUGA
          </button>
          <button
            className={`btn-fit ${currentStage === 'workflow_summary' ? 'active' : ''}`}
            style={{
              fontSize: '0.68rem',
              padding: '0.15rem 0.45rem',
              background: currentStage === 'workflow_summary' ? '#0284c7' : undefined,
              color: currentStage === 'workflow_summary' ? '#fff' : undefined,
            }}
            onClick={() => setCurrentStage('workflow_summary')}
          >
            📋 7. Summary
          </button>
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
              <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                <button
                  className="btn-fit"
                  style={{ background: '#2563eb', color: '#fff', border: 'none', fontWeight: 600 }}
                  onClick={handleLoadHidkalDemo}
                  disabled={loadingDemo}
                  title="Load pre-configured Hidkal Dam hypothetical demo configuration"
                >
                  {loadingDemo ? <><span className="spinner" /> Loading Demo...</> : '🧪 Load Hidkal Demo'}
                </button>
                <button
                  className="btn-fit"
                  style={{ background: '#059669', color: '#fff', border: 'none', fontWeight: 600 }}
                  onClick={handleLoadRiverBlockageDemo}
                  disabled={loadingDemo}
                  title="Load natural landslide dam / valley river blockage scenario"
                >
                  {loadingDemo ? <><span className="spinner" /> Loading Demo...</> : '🏔️ Load Landslide Dam Demo'}
                </button>
                <button className="btn-fit" onClick={() => setCurrentStage('setup')}>
                  ➕ Ingest New Study
                </button>
                <button className="btn-fit" onClick={loadProjects} title="Refresh registered studies">
                  ↺ Refresh
                </button>
              </div>
            </div>

            {demoLoadError && (
              <div className="damage-error-box font-mono" style={{ margin: '0.5rem 0', fontSize: '0.75rem' }}>
                ⛔ {demoLoadError}
              </div>
            )}

            {loadingProjects ? (
              <div className="probe-loading">
                <span className="spinner" /> Loading registered dam studies...
              </div>
            ) : projectsList.length === 0 ? (
              <div className="stage-empty-state">
                <span style={{ fontSize: '2rem' }}>📁</span>
                <span className="stage-empty-state-title">No Custom Dam Studies Registered</span>
                <p className="stage-empty-state-desc">
                  Load our verified Hidkal Dam demonstration study with real SRTM DEM bounds or the Natural Landslide Dam / River Blockage scenario with intact control and failed hydrodynamic routing.
                </p>
                <div style={{ display: 'flex', gap: '0.6rem', justifyContent: 'center' }}>
                  <button
                    className="btn-save-dam"
                    onClick={handleLoadHidkalDemo}
                    disabled={loadingDemo}
                    style={{ maxWidth: '240px', background: '#2563eb' }}
                  >
                    {loadingDemo ? <><span className="spinner" /> Loading Demo...</> : '🧪 Load Hidkal Demo'}
                  </button>
                  <button
                    className="btn-save-dam"
                    onClick={handleLoadRiverBlockageDemo}
                    disabled={loadingDemo}
                    style={{ maxWidth: '240px', background: '#059669' }}
                  >
                    {loadingDemo ? <><span className="spinner" /> Loading Demo...</> : '🏔️ Load Landslide Dam Demo'}
                  </button>
                  <button className="btn-fit" onClick={() => setCurrentStage('setup')} style={{ padding: '0.5rem 1rem' }}>
                    🚀 Ingest Custom DEM
                  </button>
                </div>
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
                          {p.scenario_type === 'RIVER_BLOCKAGE' && (
                            <span className="legend-tag" style={{ background: '#059669', color: '#fff', fontSize: '0.62rem', marginLeft: '0.4rem' }}>
                              🏔️ RIVER BLOCKAGE / LANDSLIDE DAM
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
                            setCurrentStage('export')
                          }}
                          disabled={isIntegrityFailed}
                        >
                          📦 Export
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
          {/* Quick Demo Pre-population Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1rem' }}>
            <div className="preflight-report-card" style={{ background: '#0f172a', border: '1px solid #3b82f6', margin: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <strong style={{ fontSize: '0.85rem' }}>🧪 Hidkal Dam Break Study</strong>
                  <span className="legend-tag" style={{ background: '#7c3aed', color: '#fff', fontSize: '0.62rem' }}>
                    DEMO
                  </span>
                </div>
              </div>
              <p style={{ fontSize: '0.72rem', color: '#94a3b8', margin: '0 0 0.5rem 0' }}>
                Loads Hidkal SRTM DEM bounds, domain polygon, reservoir boundary, dam crest axis, and conservative elevations.
              </p>
              <button
                type="button"
                className="btn-preflight"
                onClick={handleLoadHidkalDemo}
                disabled={loadingDemo}
                style={{
                  background: '#2563eb',
                  color: '#fff',
                  padding: '0.4rem 0.8rem',
                  fontSize: '0.74rem',
                  fontWeight: 600,
                  borderRadius: '4px',
                  width: '100%',
                }}
              >
                {loadingDemo ? <><span className="spinner" /> Loading...</> : '⚡ Load Hidkal Dam Demo'}
              </button>
            </div>

            <div className="preflight-report-card" style={{ background: '#0f172a', border: '1px solid #059669', margin: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <strong style={{ fontSize: '0.85rem' }}>🏔️ Natural Landslide Dam / River Blockage</strong>
                  <span className="legend-tag" style={{ background: '#059669', color: '#fff', fontSize: '0.62rem' }}>
                    PS161 REQ B
                  </span>
                </div>
              </div>
              <p style={{ fontSize: '0.72rem', color: '#94a3b8', margin: '0 0 0.5rem 0' }}>
                Valley debris obstruction model with intact upstream retention vs breach release wave propagation.
              </p>
              <button
                type="button"
                className="btn-preflight"
                onClick={handleLoadRiverBlockageDemo}
                disabled={loadingDemo}
                style={{
                  background: '#059669',
                  color: '#fff',
                  padding: '0.4rem 0.8rem',
                  fontSize: '0.74rem',
                  fontWeight: 600,
                  borderRadius: '4px',
                  width: '100%',
                }}
              >
                {loadingDemo ? <><span className="spinner" /> Loading...</> : '⚡ Load Landslide Dam Demo'}
              </button>
            </div>
          </div>

          <div className="val-disclaimer-box font-mono" style={{ fontSize: '0.7rem', margin: '0 0 0.8rem 0', borderColor: '#f59e0b', color: '#fbbf24' }}>
            ⚠️ <strong>Disclaimer:</strong> Models the hydraulic consequences of an engineered dam or natural valley debris blockage on DEM elevation surfaces. Does NOT model geotechnical slope mechanics, landslide triggering, or sediment transport.
          </div>

          {demoLoadError && (
            <div className="damage-error-box font-mono" style={{ margin: '0 0 0.8rem 0', fontSize: '0.75rem' }}>
              ⛔ {demoLoadError}
            </div>
          )}

          {/* Step 1: Core Dataset & Dam Point */}
          <div className="onboarding-section">
            <h4 className="onboarding-sub-title">1. Essential Data & Scenario Mode</h4>

            <div className="config-field" style={{ marginBottom: '0.75rem' }}>
              <label>Scenario / Barrier Type *</label>
              <select
                value={formValues.scenarioType || 'DAM_BREAK'}
                onChange={(e) => handleInputChange('scenarioType', e.target.value as any)}
                className="config-input"
                style={{ fontWeight: 600 }}
              >
                <option value="DAM_BREAK">🏗️ Engineered Dam Break Scenario</option>
                <option value="RIVER_BLOCKAGE">🏔️ River Blockage / Natural Landslide Dam Scenario</option>
              </select>
            </div>

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
                  placeholder="e.g. Valley Blockage Assessment"
                />
              </div>
              <div className="config-field">
                <label>{formValues.scenarioType === 'RIVER_BLOCKAGE' ? 'Obstruction / Valley Name *' : 'Dam / Structure Name *'}</label>
                <input
                  type="text"
                  value={formValues.damName}
                  onChange={(e) => handleInputChange('damName', e.target.value)}
                  className="config-input"
                  placeholder={formValues.scenarioType === 'RIVER_BLOCKAGE' ? 'e.g. Upper Valley Landslide Dam' : 'e.g. Koyna Dam'}
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
              <h4 className="onboarding-sub-title">
                {formValues.scenarioType === 'RIVER_BLOCKAGE'
                  ? '2. Blockage & Hydraulic Parameters (Optional)'
                  : '2. Engineering & Hydraulic Parameters (Optional)'}
              </h4>
              <span>{showEngParams ? '▲' : '▼'}</span>
            </div>

            {showEngParams && (
              <div className="accordion-content">
                <div className="onboarding-grid-3">
                  <div className="config-field">
                    <label>{formValues.scenarioType === 'RIVER_BLOCKAGE' ? 'Blockage Height (m)' : 'Dam Height (m)'}</label>
                    <input
                      type="number"
                      step="0.1"
                      value={formValues.damHeight}
                      onChange={(e) => handleInputChange('damHeight', e.target.value)}
                      className="config-input font-mono"
                      placeholder="e.g. 35.0"
                    />
                  </div>
                  <div className="config-field">
                    <label>{formValues.scenarioType === 'RIVER_BLOCKAGE' ? 'Blockage Crest Elevation (m)' : 'Crest Elevation (m)'}</label>
                    <input
                      type="number"
                      step="0.1"
                      value={formValues.crestElevation}
                      onChange={(e) => handleInputChange('crestElevation', e.target.value)}
                      className="config-input font-mono"
                      placeholder="e.g. 525.0"
                    />
                  </div>
                  <div className="config-field">
                    <label>{formValues.scenarioType === 'RIVER_BLOCKAGE' ? 'Upstream Water Level (m)' : 'Pool Elevation (m)'}</label>
                    <input
                      type="number"
                      step="0.1"
                      value={formValues.poolElevation}
                      onChange={(e) => handleInputChange('poolElevation', e.target.value)}
                      className="config-input font-mono"
                      placeholder="e.g. 520.0"
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
                    <label>{formValues.scenarioType === 'RIVER_BLOCKAGE' ? 'Breach Opening Width (m)' : 'Breach Width (m)'}</label>
                    <input
                      type="number"
                      step="1"
                      value={formValues.breachWidth}
                      onChange={(e) => handleInputChange('breachWidth', e.target.value)}
                      className="config-input font-mono"
                      placeholder="60"
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

          {/* Validation Trigger & Reset Row */}
          <div className="onboarding-actions-row" style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
            <button
              id="btn-validate-dam-dataset"
              className="btn-validate-dam"
              onClick={handleValidate}
              disabled={validating || !demFile || !formValues.projectName.trim()}
            >
              {validating ? <><span className="spinner" /> Validating Ingestion...</> : '🔍 1. Validate Dataset & Location'}
            </button>
            <button
              type="button"
              id="btn-reset-dam-form"
              className="btn-fit"
              onClick={handleResetForm}
              style={{ background: '#334155', color: '#cbd5e1', padding: '0.55rem 0.9rem' }}
              title="Reset all inputs, files, and validation state"
            >
              🔄 Reset Form
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
                  <label className="ack-label" htmlFor="ack-unverified-metadata">
                    <input
                      type="checkbox"
                      id="ack-unverified-metadata"
                      checked={acknowledgeUnverified}
                      onChange={(e) => setAcknowledgeUnverified(e.target.checked)}
                      className="ack-checkbox"
                    />
                    <span className="ack-text">
                      I acknowledge that the submitted metadata and geometries are <strong>user-declared, not independently verified</strong>, and are stored for exploratory inspection only.
                    </span>
                  </label>

                  <button
                    id="btn-register-save-project"
                    className="btn-save-dam"
                    onClick={handleSave}
                    disabled={saving || !validationResult.onboarding_validation_passed || !acknowledgeUnverified}
                    title={!acknowledgeUnverified ? 'Check the acknowledgment above to enable registration' : 'Register and save this dam study'}
                  >
                    {saving ? <><span className="spinner" /> Persisting Dam Project...</> : '💾 2. Register & Save Project'}
                  </button>
                  {!acknowledgeUnverified && (
                    <span style={{ fontSize: '0.75rem', color: '#f59e0b' }}>
                      ⚠️ Check acknowledgment above to enable registration.
                    </span>
                  )}
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

      {/* STAGE 3: HYDRODYNAMIC SIMULATION */}
      {currentStage === 'simulation' && (
        <div className="onboarding-body">
          {!activeProject ? (
            <div className="stage-empty-state">
              <span style={{ fontSize: '2rem' }}>⚡</span>
              <span className="stage-empty-state-title">No Dam Study Selected</span>
              <p className="stage-empty-state-desc">
                Select a registered dam study from the dropdown above or ingest a new study in Terrain & Geometry to execute hydrodynamic models.
              </p>
              <button className="btn-fit" onClick={() => setCurrentStage('setup')}>
                🏗️ Go to Terrain & Geometry
              </button>
            </div>
          ) : (
            <div>
              {/* Solver Suite Capability Summary */}
              <div className="readiness-card-container" style={{ marginBottom: '0.85rem', padding: '0.75rem', background: 'rgba(15, 23, 42, 0.85)', borderRadius: '6px', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <h5 style={{ margin: 0, fontSize: '0.82rem', color: '#38bdf8' }}>
                    🏛️ Multi-Engine Hydrodynamic Solver Status
                  </h5>
                  <button
                    className="btn-fit"
                    style={{ fontSize: '0.68rem' }}
                    onClick={() => handleToggleReadiness(activeProject.project_id)}
                  >
                    ↺ Re-evaluate
                  </button>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.4rem', fontSize: '0.72rem' }}>
                  <div style={{ padding: '0.4rem', borderRadius: '4px', background: 'rgba(56, 189, 248, 0.1)', borderLeft: '3px solid #38bdf8' }}>
                    <strong>SPH (PySPH):</strong><br />
                    <span style={{ color: '#38bdf8' }}>Target Engine</span> • Package / Import Ready
                  </div>
                  <div style={{ padding: '0.4rem', borderRadius: '4px', background: 'rgba(59, 130, 246, 0.1)', borderLeft: '3px solid #3b82f6' }}>
                    <strong>Delft3D (D-Flow FM):</strong><br />
                    <span style={{ color: '#60a5fa' }}>Target Engine</span> • Package / Import Ready
                  </div>
                  <div style={{ padding: '0.4rem', borderRadius: '4px', background: 'rgba(34, 197, 94, 0.1)', borderLeft: '3px solid #22c55e' }}>
                    <strong>ANUGA (2D SWE):</strong><br />
                    <span style={{ color: '#4ade80' }}>Reference Engine</span> • Executable Locally
                  </div>
                </div>
              </div>

              {/* ANUGA Package & Execution Component */}
              <DamProjectAnugaReadiness
                project={activeProject}
                onPackageBuilt={loadProjects}
                onDisplayHazardLayer={onDisplayHazardLayer}
                onDisplayTimestepLayer={onDisplayTimestepLayer}
                onNavigateToSimulation={() => setCurrentStage('simulation')}
              />
            </div>
          )}
        </div>
      )}

      {/* STAGE: 3D SPH SIMULATION VISUALIZATION */}
      {currentStage === 'three_sph' && (
        <div className="onboarding-body" style={{ minHeight: '650px', position: 'relative', borderRadius: '8px', overflow: 'hidden' }}>
          <ThreeSphSimulation
            projectId={activeProject?.project_id}
          />
        </div>
      )}

      {/* STAGE 4: FLOOD RESULTS & ANIMATION */}
      {currentStage === 'results' && (
        <div className="onboarding-body">
          {!activeProject ? (
            <div className="stage-empty-state">
              <span style={{ fontSize: '2rem' }}>🌊</span>
              <span className="stage-empty-state-title">No Dam Study Selected</span>
              <p className="stage-empty-state-desc">
                Select a registered dam study from the dropdown above to inspect simulated maximum depth, velocity, arrival time maps, and transient flood animations.
              </p>
              <button className="btn-fit" onClick={() => setCurrentStage('overview')}>
                🌐 Go to Project Overview
              </button>
            </div>
          ) : (
            <div>
              <DamProjectAnugaReadiness
                project={activeProject}
                onPackageBuilt={loadProjects}
                onDisplayHazardLayer={onDisplayHazardLayer}
                onDisplayTimestepLayer={onDisplayTimestepLayer}
                focusResultsOnly={true}
                onNavigateToSimulation={() => setCurrentStage('simulation')}
              />
            </div>
          )}
        </div>
      )}

      {/* STAGE 5: DECISION-SUPPORT DASHBOARD */}
      {currentStage === 'decision_support' && (
        <div className="onboarding-body">
          {!activeProject ? (
            <div className="stage-empty-state">
              <span style={{ fontSize: '2rem' }}>📊</span>
              <span className="stage-empty-state-title">No Dam Study Selected</span>
              <p className="stage-empty-state-desc">
                Select a registered dam study from the dropdown above to view the hydrodynamic decision-support dashboard and hydraulic severity metrics.
              </p>
            </div>
          ) : (
            <DecisionSupportDashboard
              projectId={activeProject.project_id}
              onSelectLayer={(tileUrl, layerName) => {
                if (tileUrl && onDisplayHazardLayer) {
                  onDisplayHazardLayer(activeProject.project_id, 'decision_support', layerName)
                }
              }}
              onOpenComparison={() => setCurrentStage('comparison')}
            />
          )}
        </div>
      )}

      {/* STAGE 6: SPH VS ANUGA MODEL COMPARISON */}
      {currentStage === 'comparison' && (
        <div className="onboarding-body">
          {!activeProject ? (
            <div className="stage-empty-state">
              <span style={{ fontSize: '2rem' }}>⚖️</span>
              <span className="stage-empty-state-title">No Dam Study Selected</span>
              <p className="stage-empty-state-desc">
                Select a registered dam study to compare SPH and Delft3D hydrodynamic simulation outputs.
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
              onDisplaySPHParticleFrame={onDisplaySPHParticleFrame}
              onClearSPHParticleLayer={onClearSPHParticleLayer}
              onUpdateDamBreachState={onUpdateDamBreachState}
            />
          )}
        </div>
      )}

      {/* STAGE 7: UNIFIED WORKFLOW SUMMARY DASHBOARD */}
      {currentStage === 'workflow_summary' && (
        <div className="onboarding-body">
          <WorkflowSummaryDashboard
            projectId={activeProject?.project_id}
            onNavigateToTab={(tab) => {
              if (tab === 'simulation') setCurrentStage('simulation')
              else if (tab === 'results') setCurrentStage('results')
              else if (tab === 'decision_support') setCurrentStage('decision_support')
              else if (tab === 'comparison') setCurrentStage('comparison')
              else if (tab === 'three_sph') setCurrentStage('three_sph')
              else if (tab === 'satellite') setCurrentStage('satellite')
              else if (tab === 'exposure') setCurrentStage('exposure')
              else if (tab === 'export') setCurrentStage('export')
            }}
          />
        </div>
      )}

      {/* STAGE 8: SATELLITE EVIDENCE */}
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

      {/* STAGE 7: EXPOSURE & DAMAGE */}
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

      {/* STAGE 8: GEOSPATIAL EXPORT */}
      {currentStage === 'export' && (
        <div className="onboarding-body">
          <div className="hud-card export-card">
            <div className="hud-card-header">
              <h4 className="onboarding-sub-title">💾 Geospatial Data Export (Multi-Format)</h4>
              <span className="legend-tag">GIS-READY</span>
            </div>

            <div className="export-body">
              {/* Export Layer Selector */}
              <div className="export-section">
                <label className="export-field-label">1. Select Target Spatial Layer</label>
                <div className="export-options-grid">
                  <button
                    type="button"
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
                    type="button"
                    className={`export-select-btn ${exportLayer === 'roads' ? 'active' : ''}`}
                    onClick={() => setExportLayer('roads')}
                  >
                    <span className="export-btn-icon">🛣️</span>
                    <div className="export-btn-text">
                      <span className="export-btn-title">Road Network Graph</span>
                      <span className="export-btn-sub">8,047 road network segments</span>
                    </div>
                  </button>
                </div>
              </div>

              {/* Exposure Status Filter */}
              <div className="export-section">
                <label className="export-field-label">2. Exposure Status Filter</label>
                <div className="filter-options-grid">
                  {[
                    { id: 'all', label: 'All Features', desc: 'Complete dataset' },
                    { id: 'screening_positive', label: 'Screening-positive Only', desc: 'Depth > 0 in flood raster' },
                    { id: 'not_exposed', label: 'Not Exposed Only', desc: 'Assessed with zero depth' },
                    { id: 'not_assessed', label: 'Not Assessed Only', desc: 'Outside domain extent' },
                  ].map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={`filter-select-btn ${exportFilter === item.id ? 'active' : ''}`}
                      onClick={() => setExportFilter(item.id as any)}
                    >
                      <span className="filter-btn-title">{item.label}</span>
                      <span className="filter-btn-sub">{item.desc}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Format Selector */}
              <div className="export-section">
                <label className="export-field-label">3. Select Export Format</label>
                <div className="format-options-grid">
                  <button
                    type="button"
                    className={`format-select-btn ${exportFormat === 'geojson' ? 'active' : ''}`}
                    onClick={() => setExportFormat('geojson')}
                  >
                    <span className="format-title">GeoJSON</span>
                    <span className="format-ext">.geojson</span>
                    <span className="format-desc">Standard Web GIS FeatureCollection</span>
                  </button>

                  <button
                    type="button"
                    className={`format-select-btn ${exportFormat === 'kml' ? 'active' : ''}`}
                    onClick={() => setExportFormat('kml')}
                  >
                    <span className="format-title">Google Earth KML</span>
                    <span className="format-ext">.kml</span>
                    <span className="format-desc">Styled placemarks with attribute metadata</span>
                  </button>

                  <button
                    type="button"
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
              <div className="calculate-action-row" style={{ marginTop: '0.75rem' }}>
                <button
                  type="button"
                  className="btn-calculate"
                  disabled={exportLoading}
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

              {exportSuccessMsg && <div className="export-success-box" style={{ marginTop: '0.5rem' }}>✅ {exportSuccessMsg}</div>}
              {exportError && <div className="damage-error-box" style={{ marginTop: '0.5rem' }}>⛔ {exportError}</div>}

              {/* Package Metadata Summary */}
              <div className="export-info-card" style={{ marginTop: '0.75rem' }}>
                <span className="note-title">ℹ️ Export Specifications</span>
                <ul className="export-specs-list font-mono" style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                  <li><strong>CRS:</strong> WGS84 Geographic Coordinates (<code>EPSG:4326</code>)</li>
                  <li><strong>Shapefile Bundles:</strong> Zipped archive includes complete <code>.shp</code>, <code>.shx</code>, <code>.dbf</code>, <code>.prj</code>, <code>.cpg</code> sets.</li>
                  <li><strong>Mixed Geometries:</strong> Automatically split into separated <code>_points.shp</code>, <code>_lines.shp</code>, and <code>_polygons.shp</code>.</li>
                  <li><strong>Audit Metadata:</strong> Every ZIP package includes a <code>README_METADATA.txt</code> containing column mappings and screening disclaimers.</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

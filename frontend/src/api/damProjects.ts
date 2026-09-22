import type {
  DamProjectValidationResponse,
  DamProjectSummary,
  DamProjectDetailResponse,
  DamProjectAnugaPreflightResponse,
  DamProjectAnugaPackageResponse,
  DamProjectAnugaCapabilitiesResponse,
  DamProjectAnugaRunRequest,
  DamProjectAnugaRunResponse,
  RasterDerivedMetadata,
  DamProjectAnugaPostprocessRequest,
  DamProjectAnugaResultsResponse,
  DamProjectAnugaPointValueResponse,
  DamProjectReadinessResponse,
  HeuristicAssistRequest,
  HeuristicAssistResponse,
  SimulationInputsUpdateRequest,
  DemoInputsRequest,
  DemoInputsResponse,
  DamProjectAnugaOutputsResponse,
  ProjectAOIResponse,
  EarthObservationRunRequest,
  EarthObservationRunResponse,
  ModelObservationComparisonRequest,
  ModelObservationComparisonResponse,
  GEECapabilitiesResponse,
  ModelComparisonCapabilitiesResponse,
  ModelComparisonRunRequest,
  ModelComparisonRunResponse,
  SPHvsANUGAComparisonResponse,
  ProjectDelft3DPackageResponse,
  ProjectSPHPackageResponse,
  ExposureCapabilitiesResponse,
  ExposureRunRequest,
  ExposureRunSummary,
  ExposureRunDetailResponse,
  SystemHealthSummaryResponse,
  DecisionSupportResponse,
  DemoReadinessResponse,
} from '../types/damProjects'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export async function validateDamProject(formData: FormData): Promise<DamProjectValidationResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/validate`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const errorBody = await res.json().catch(() => null)
    if (res.status === 413 || res.status === 422) {
      if (errorBody && errorBody.detail) {
        if (typeof errorBody.detail === 'string') {
          throw new Error(errorBody.detail)
        } else if (errorBody.detail.message) {
          throw new Error(errorBody.detail.message)
        }
      }
    }
    throw new Error(`Validation failed with status ${res.status}`)
  }
  return res.json()
}

export async function saveDamProject(formData: FormData): Promise<DamProjectDetailResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const errorBody = await res.json().catch(() => null)
    if (errorBody && errorBody.detail) {
      if (typeof errorBody.detail === 'string') {
        throw new Error(errorBody.detail)
      } else if (errorBody.detail.message) {
        throw new Error(errorBody.detail.message)
      }
    }
    throw new Error(`Save failed with status ${res.status}`)
  }
  return res.json()
}

export async function listDamProjects(): Promise<DamProjectSummary[]> {
  const res = await fetch(`${API_BASE}/api/dam-projects`)
  if (!res.ok) {
    throw new Error(`Failed to list dam projects: HTTP ${res.status}`)
  }
  return res.json()
}

export async function getDamProject(projectId: string): Promise<DamProjectDetailResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}`)
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (res.status === 409 && errBody?.detail?.code === 'project_integrity_failed') {
      throw new Error(`Project integrity failure: ${errBody.detail.message}`)
    }
    throw new Error(`Failed to fetch project details: HTTP ${res.status}`)
  }
  return res.json()
}

export async function getDamProjectDemMetadata(projectId: string): Promise<RasterDerivedMetadata> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/dem/metadata`)
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (res.status === 409 && errBody?.detail?.code === 'project_integrity_failed') {
      throw new Error(`Project integrity failure: ${errBody.detail.message}`)
    }
    throw new Error(`Failed to fetch project DEM metadata: HTTP ${res.status}`)
  }
  return res.json()
}

export function getDamProjectDemTileUrl(projectId: string): string {
  return `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/dem/tiles/{z}/{x}/{y}.png`
}

export async function getDamProjectDamAxisGeometry(projectId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/geometry/dam-axis`)
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (res.status === 409 && errBody?.detail?.code === 'project_integrity_failed') {
      throw new Error(`Project integrity failure: ${errBody.detail.message}`)
    }
    throw new Error(`Failed to fetch dam axis geometry: HTTP ${res.status}`)
  }
  return res.json()
}

export async function getDamProjectReservoirGeometry(projectId: string): Promise<any | null> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/geometry/reservoir`)
  if (res.status === 404) {
    return null
  }
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (res.status === 409 && errBody?.detail?.code === 'project_integrity_failed') {
      throw new Error(`Project integrity failure: ${errBody.detail.message}`)
    }
    throw new Error(`Failed to fetch reservoir geometry: HTTP ${res.status}`)
  }
  return res.json()
}

export async function getDamProjectBreachGeometry(projectId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/geometry/breach`)
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (res.status === 409 && errBody?.detail?.code === 'project_integrity_failed') {
      throw new Error(`Project integrity failure: ${errBody.detail.message}`)
    }
    throw new Error(`Failed to fetch breach geometry: HTTP ${res.status}`)
  }
  return res.json()
}

export async function getDamProjectModelDomainGeometry(projectId: string): Promise<any | null> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/geometry/model-domain`)
  if (res.status === 404) {
    return null
  }
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (res.status === 409 && errBody?.detail?.code === 'project_integrity_failed') {
      throw new Error(`Project integrity failure: ${errBody.detail.message}`)
    }
    throw new Error(`Failed to fetch model domain geometry: HTTP ${res.status}`)
  }
  return res.json()
}

export async function getDamProjectOutletGeometry(projectId: string): Promise<any | null> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/geometry/outlet`)
  if (res.status === 404) {
    return null
  }
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (res.status === 409 && errBody?.detail?.code === 'project_integrity_failed') {
      throw new Error(`Project integrity failure: ${errBody.detail.message}`)
    }
    throw new Error(`Failed to fetch downstream outlet geometry: HTTP ${res.status}`)
  }
  return res.json()
}

export async function runAnugaPreflight(projectId: string): Promise<DamProjectAnugaPreflightResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/preflight`, {
    method: 'POST',
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (res.status === 409 && errBody?.detail?.code === 'project_integrity_failed') {
      throw new Error(`Project integrity failure: ${errBody.detail.message}`)
    }
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Preflight assessment failed: HTTP ${res.status}`)
  }
  return res.json()
}

export async function buildAnugaPackage(projectId: string): Promise<DamProjectAnugaPackageResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/build-package`, {
    method: 'POST',
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (res.status === 409 && errBody?.detail?.code === 'project_integrity_failed') {
      throw new Error(`Project integrity failure: ${errBody.detail.message}`)
    }
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) {
        const blockers = errBody.detail.blockers ? ` Blockers: ${errBody.detail.blockers.join('; ')}` : ''
        throw new Error(`${errBody.detail.message}${blockers}`)
      }
    }
    throw new Error(`Package generation failed: HTTP ${res.status}`)
  }
  return res.json()
}

export function getAnugaPackageDownloadUrl(projectId: string): string {
  return `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/package`
}

export async function fetchDamProjectAnugaCapabilities(projectId: string): Promise<DamProjectAnugaCapabilitiesResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/capabilities`)
  if (!res.ok) {
    throw new Error(`Failed to fetch ANUGA capabilities: HTTP ${res.status}`)
  }
  return res.json()
}

export async function executeDamProjectAnugaRun(
  projectId: string,
  req: DamProjectAnugaRunRequest,
): Promise<DamProjectAnugaRunResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (res.status === 403 && errBody?.detail?.code === 'custom_anuga_execution_disabled') {
      throw new Error(errBody.detail.message)
    }
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Simulation execution failed: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchDamProjectAnugaRuns(projectId: string): Promise<DamProjectAnugaRunResponse[]> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/runs`)
  if (!res.ok) {
    throw new Error(`Failed to fetch simulation runs: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchDamProjectAnugaRun(projectId: string, runId: string): Promise<DamProjectAnugaRunResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/runs/${encodeURIComponent(runId)}`)
  if (!res.ok) {
    throw new Error(`Failed to fetch simulation run status: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchDamProjectAnugaRunLogs(projectId: string, runId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/runs/${encodeURIComponent(runId)}/logs`)
  if (!res.ok) {
    throw new Error(`Failed to fetch simulation logs: HTTP ${res.status}`)
  }
  return res.text()
}

export async function postprocessDamProjectAnugaRun(
  projectId: string,
  runId: string,
  req: DamProjectAnugaPostprocessRequest = {},
): Promise<DamProjectAnugaResultsResponse> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/runs/${encodeURIComponent(runId)}/postprocess`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    },
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Postprocessing failed: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchDamProjectAnugaResults(
  projectId: string,
  runId: string,
): Promise<DamProjectAnugaResultsResponse> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/runs/${encodeURIComponent(runId)}/results`,
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to fetch simulation results: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchDamProjectAnugaLayerMetadata(
  projectId: string,
  runId: string,
  layer: string,
): Promise<any> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/runs/${encodeURIComponent(runId)}/results/${encodeURIComponent(layer)}/metadata`,
  )
  if (!res.ok) {
    throw new Error(`Failed to fetch layer metadata: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchDamProjectAnugaLayerLegend(
  projectId: string,
  runId: string,
  layer: string,
): Promise<any> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/runs/${encodeURIComponent(runId)}/results/${encodeURIComponent(layer)}/legend`,
  )
  if (!res.ok) {
    throw new Error(`Failed to fetch layer legend: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchDamProjectAnugaLayerPointValue(
  projectId: string,
  runId: string,
  layer: string,
  lon: number,
  lat: number,
): Promise<DamProjectAnugaPointValueResponse> {
  const params = new URLSearchParams({ lon: String(lon), lat: String(lat) })
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/runs/${encodeURIComponent(runId)}/results/${encodeURIComponent(layer)}/point?${params.toString()}`,
  )
  if (!res.ok) {
    throw new Error(`Failed to query point value: HTTP ${res.status}`)
  }
  return res.json()
}

export function getDamProjectAnugaLayerTileUrl(
  projectId: string,
  runId: string,
  layer: string,
): string {
  return `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/runs/${encodeURIComponent(runId)}/results/${encodeURIComponent(layer)}/tiles/{z}/{x}/{y}.png`
}

export function getDamProjectAnugaTimestepTileUrl(
  projectId: string,
  runId: string,
  stepIdx: number,
  processingId?: string,
): string {
  let url = `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/runs/${encodeURIComponent(runId)}/timesteps/${encodeURIComponent(stepIdx)}/tiles/{z}/{x}/{y}.png`
  if (processingId) {
    url += `?processing_id=${encodeURIComponent(processingId)}`
  }
  return url
}

export interface DamProjectAnugaTimestepsInfo {
  project_id: string
  run_id: string
  total_timesteps: number
  duration_seconds: number
  interval_seconds: number
  times: number[]
  valid_min: number
  valid_max: number
  unit: string
}

export async function fetchDamProjectAnugaTimestepsInfo(
  projectId: string,
  runId: string,
  processingId?: string,
): Promise<DamProjectAnugaTimestepsInfo> {
  let url = `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/runs/${encodeURIComponent(runId)}/timesteps/info`
  if (processingId) {
    url += `?processing_id=${encodeURIComponent(processingId)}`
  }
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`Failed to fetch ANUGA timesteps info: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchDamProjectReadiness(
  projectId: string,
): Promise<DamProjectReadinessResponse> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/readiness`,
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (res.status === 409 && errBody?.detail?.code === 'project_integrity_failed') {
      throw new Error(`Project integrity failure: ${errBody.detail.message}`)
    }
    throw new Error(`Failed to assess project simulation readiness: HTTP ${res.status}`)
  }
  return res.json()
}

export function getDamProjectDemLegendUrl(projectId: string): string {
  return `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/dem/legend`
}

export async function fetchDamProjectDemLegend(projectId: string): Promise<any> {
  const res = await fetch(getDamProjectDemLegendUrl(projectId))
  if (!res.ok) {
    throw new Error(`Failed to fetch project DEM legend: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchDamProjectDamMarkerGeometry(projectId: string): Promise<any> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/geometry/dam-marker`,
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (res.status === 409 && errBody?.detail?.code === 'project_integrity_failed') {
      throw new Error(`Project integrity failure: ${errBody.detail.message}`)
    }
    throw new Error(`Failed to fetch dam marker geometry: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchDamProjectDemPointValue(
  projectId: string,
  lon: number,
  lat: number,
): Promise<any> {
  const params = new URLSearchParams({ lon: String(lon), lat: String(lat) })
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/dem/value?${params.toString()}`,
  )
  if (!res.ok) {
    throw new Error(`Failed to sample DEM elevation: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchTerrainHeuristicAssist(
  projectId: string,
  req: HeuristicAssistRequest = {},
): Promise<HeuristicAssistResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/heuristic-assist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Heuristic assist calculation failed: HTTP ${res.status}`)
  }
  return res.json()
}

export async function saveProjectSimulationInputs(
  projectId: string,
  req: SimulationInputsUpdateRequest,
): Promise<DamProjectDetailResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/simulation-inputs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Saving simulation inputs failed: HTTP ${res.status}`)
  }
  return res.json()
}

export async function prepareDamProjectDemoInputs(
  projectId: string,
  req: DemoInputsRequest = {},
): Promise<DemoInputsResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/demo-inputs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Preparing demo inputs failed: HTTP ${res.status}`)
  }
  return res.json()
}

export async function loadHidkalDemoProject(): Promise<DamProjectDetailResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/load-hidkal-demo`, {
    method: 'POST',
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Loading Hidkal demo project failed: HTTP ${res.status}`)
  }
  return res.json()
}

export async function loadRiverBlockageDemoProject(): Promise<DamProjectDetailResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/load-river-blockage-demo`, {
    method: 'POST',
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Loading River Blockage demo project failed: HTTP ${res.status}`)
  }
  return res.json()
}

export async function cancelDamProjectAnugaRun(
  projectId: string,
  runId: string,
): Promise<DamProjectAnugaRunResponse> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/runs/${encodeURIComponent(runId)}/cancel`,
    {
      method: 'POST',
    },
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to cancel simulation run: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchDamProjectAnugaOutputs(
  projectId: string,
  runId: string,
): Promise<DamProjectAnugaOutputsResponse> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/anuga/runs/${encodeURIComponent(runId)}/outputs`,
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to fetch simulation outputs: HTTP ${res.status}`)
  }
  return res.json()
}

// Phase 20: Earth Observation & Comparison API functions

export async function fetchGEECapabilities(): Promise<GEECapabilitiesResponse> {
  const res = await fetch(`${API_BASE}/api/gee/capabilities`)
  if (!res.ok) {
    throw new Error(`Failed to fetch GEE capabilities: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchProjectAOI(
  projectId: string,
  bufferMeters: number = 2000,
): Promise<ProjectAOIResponse> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/earth-observation/aoi?buffer_meters=${bufferMeters}`,
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to fetch project AOI: HTTP ${res.status}`)
  }
  return res.json()
}

export async function createEarthObservationRun(
  projectId: string,
  req: EarthObservationRunRequest,
): Promise<EarthObservationRunResponse> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/earth-observation/runs`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    },
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to create Earth Observation run: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchEarthObservationRuns(
  projectId: string,
): Promise<EarthObservationRunResponse[]> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/earth-observation/runs`,
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to fetch Earth Observation runs: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchEarthObservationRun(
  projectId: string,
  eoRunId: string,
): Promise<EarthObservationRunResponse> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/earth-observation/runs/${encodeURIComponent(eoRunId)}`,
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to fetch Earth Observation run detail: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchEarthObservationLogs(
  projectId: string,
  eoRunId: string,
): Promise<{ eo_run_id: string; logs: string }> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/earth-observation/runs/${encodeURIComponent(eoRunId)}/logs`,
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to fetch Earth Observation logs: HTTP ${res.status}`)
  }
  return res.json()
}

export async function compareModelAndObservation(
  projectId: string,
  req: ModelObservationComparisonRequest,
): Promise<ModelObservationComparisonResponse> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/earth-observation/compare`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    },
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to compare model and observation: HTTP ${res.status}`)
  }
  return res.json()
}

// ==========================================
// Phase 21: Multi-Engine Spatial Comparison
// ==========================================

export async function fetchModelComparisonCapabilities(
  projectId: string,
): Promise<ModelComparisonCapabilitiesResponse> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/model-comparison/capabilities`,
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to fetch model comparison capabilities: HTTP ${res.status}`)
  }
  return res.json()
}

export async function createModelComparisonRun(
  projectId: string,
  req: ModelComparisonRunRequest,
): Promise<ModelComparisonRunResponse> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/model-comparison/runs`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    },
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to create model comparison run: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchModelComparisonRuns(
  projectId: string,
): Promise<ModelComparisonRunResponse[]> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/model-comparison/runs`,
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to fetch model comparison runs: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchModelComparisonRun(
  projectId: string,
  comparisonId: string,
): Promise<ModelComparisonRunResponse> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/model-comparison/runs/${encodeURIComponent(comparisonId)}`,
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to fetch model comparison run detail: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchModelComparisonLogs(
  projectId: string,
  comparisonId: string,
): Promise<{ comparison_id: string; logs: string }> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/model-comparison/runs/${encodeURIComponent(comparisonId)}/logs`,
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to fetch model comparison logs: HTTP ${res.status}`)
  }
  const text = await res.text()
  return { comparison_id: comparisonId, logs: text }
}

export function getModelComparisonTileUrl(
  projectId: string,
  comparisonId: string,
  layer: string,
): string {
  return `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/model-comparison/runs/${encodeURIComponent(comparisonId)}/tiles/${encodeURIComponent(layer)}/{z}/{x}/{y}.png`
}

// Phase 28: SPH vs ANUGA Specialized Comparison API Functions

export async function fetchSPHvsANUGAComparison(
  projectId: string,
  sphRunId?: string,
  anugaRunId?: string,
): Promise<SPHvsANUGAComparisonResponse> {
  const params = new URLSearchParams()
  if (sphRunId) params.set('sph_run_id', sphRunId)
  if (anugaRunId) params.set('anuga_run_id', anugaRunId)
  const qs = params.toString() ? `?${params.toString()}` : ''
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/model-comparison${qs}`)
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to fetch SPH vs ANUGA comparison: HTTP ${res.status}`)
  }
  return res.json()
}

export function getSPHvsANUGAExportUrl(
  projectId: string,
  format: 'json' | 'csv' = 'json',
  sphRunId?: string,
  anugaRunId?: string,
): string {
  const params = new URLSearchParams({ format })
  if (sphRunId) params.set('sph_run_id', sphRunId)
  if (anugaRunId) params.set('anuga_run_id', anugaRunId)
  return `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/model-comparison/export?${params.toString()}`
}

// Phase 25: Project Delft3D & SPH API Functions

export async function buildDamProjectDelft3DPackage(projectId: string): Promise<ProjectDelft3DPackageResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/delft3d/build-package`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(`Failed to build Delft3D package: HTTP ${res.status}`)
  return res.json()
}

export function getDamProjectDelft3DPackageDownloadUrl(projectId: string): string {
  return `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/delft3d/download-package`
}

export async function importDamProjectDelft3DRun(projectId: string, formData: FormData): Promise<any> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/delft3d/import-run`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) throw new Error(typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail))
    throw new Error(`Failed to import Delft3D run: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchDamProjectDelft3DRuns(projectId: string): Promise<any[]> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/delft3d/runs`)
  if (!res.ok) throw new Error(`Failed to list Delft3D runs: HTTP ${res.status}`)
  return res.json()
}

export async function buildDamProjectSPHPackage(projectId: string): Promise<ProjectSPHPackageResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/sph/build-package`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(`Failed to build SPH package: HTTP ${res.status}`)
  return res.json()
}

export function getDamProjectSPHPackageDownloadUrl(projectId: string): string {
  return `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/sph/download-package`
}

export async function importDamProjectSPHRun(projectId: string, formData: FormData): Promise<any> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/sph/import-run`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) throw new Error(typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail))
    throw new Error(`Failed to import SPH run: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchDamProjectSPHRuns(projectId: string): Promise<any[]> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/sph/runs`)
  if (!res.ok) throw new Error(`Failed to list SPH runs: HTTP ${res.status}`)
  return res.json()
}

export async function runDamProjectSPHBenchmark(projectId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/api/runs/sph`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ custom_notes: `Benchmark run for dam project ${projectId}` }),
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) throw new Error(typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail))
    throw new Error(`Failed to run SPH benchmark: HTTP ${res.status}`)
  }
  return res.json()
}

export async function executeDamProjectSPHRun(projectId: string, options?: any): Promise<any> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/sph/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options || {}),
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) throw new Error(typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail))
    throw new Error(`Failed to execute project-based SPH simulation: HTTP ${res.status}`)
  }
  return res.json()
}

// Phase 26: SPH Flood Animation Pipeline

export interface SPHAnimationFrameStats {
  time_s: number
  wet_particle_count: number
  downstream_particle_count: number
  max_depth_m: number
  max_velocity_ms: number
}

export interface SPHAnimationFrame {
  type: 'FeatureCollection'
  frame_index: number
  time_s: number
  stats?: SPHAnimationFrameStats
  features: Array<{
    type: 'Feature'
    geometry: { type: 'Point'; coordinates: [number, number] }
    properties: { d: number; v: number }
  }>
}

export interface SPHAnimationFrameMeta {
  index: number
  time_s: number
  stats?: SPHAnimationFrameStats
}

export interface SPHAnimationManifest {
  run_id: string
  total_frames: number
  duration_s: number
  particle_count?: number
  particle_count_per_frame: number
  arrival_threshold_m: number
  breach_start_time_s?: number
  first_downstream_arrival_time_s?: number | null
  frames: SPHAnimationFrameMeta[]
}

export async function fetchSPHAnimationManifest(
  projectId: string,
  runId: string,
): Promise<SPHAnimationManifest> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/sph/runs/${encodeURIComponent(runId)}/animation`,
  )
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody?.detail) throw new Error(typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail))
    throw new Error(`Failed to fetch SPH animation manifest: HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchSPHAnimationFrame(
  projectId: string,
  runId: string,
  frameIndex: number,
): Promise<SPHAnimationFrame> {
  const res = await fetch(
    `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/sph/runs/${encodeURIComponent(runId)}/animation/frames/${frameIndex}`,
  )
  if (!res.ok) {
    throw new Error(`Failed to fetch SPH animation frame ${frameIndex}: HTTP ${res.status}`)
  }
  return res.json()
}



// Phase 22: Exposure & Vulnerability API Functions

export async function getExposureCapabilities(projectId: string): Promise<ExposureCapabilitiesResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/exposure/capabilities`)
  if (!res.ok) throw new Error(`Failed to fetch exposure capabilities: HTTP ${res.status}`)
  return res.json()
}

export async function createExposureRun(projectId: string, request: ExposureRunRequest): Promise<ExposureRunDetailResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/exposure/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => null)
    if (errBody && errBody.detail) {
      if (typeof errBody.detail === 'string') throw new Error(errBody.detail)
      if (errBody.detail.message) throw new Error(errBody.detail.message)
    }
    throw new Error(`Failed to create exposure run: HTTP ${res.status}`)
  }
  return res.json()
}

export async function listExposureRuns(projectId: string): Promise<ExposureRunSummary[]> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/exposure/runs`)
  if (!res.ok) throw new Error(`Failed to list exposure runs: HTTP ${res.status}`)
  return res.json()
}

export async function getExposureRunDetail(projectId: string, runId: string): Promise<ExposureRunDetailResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/exposure/runs/${encodeURIComponent(runId)}`)
  if (!res.ok) throw new Error(`Failed to get exposure run detail: HTTP ${res.status}`)
  return res.json()
}

export async function getExposureRunLogs(projectId: string, runId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/exposure/runs/${encodeURIComponent(runId)}/logs`)
  if (!res.ok) throw new Error(`Failed to get exposure run logs: HTTP ${res.status}`)
  return res.text()
}

export async function getExposureRunAssets(projectId: string, runId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/exposure/runs/${encodeURIComponent(runId)}/assets`)
  if (!res.ok) throw new Error(`Failed to get exposure run assets: HTTP ${res.status}`)
  return res.json()
}

export async function getExposureRunRoads(projectId: string, runId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/exposure/runs/${encodeURIComponent(runId)}/roads`)
  if (!res.ok) throw new Error(`Failed to get exposure run roads: HTTP ${res.status}`)
  return res.json()
}

export async function getExposureRunLayers(projectId: string, runId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/exposure/runs/${encodeURIComponent(runId)}/layers`)
  if (!res.ok) throw new Error(`Failed to get exposure run layers: HTTP ${res.status}`)
  return res.json()
}

export async function getSystemHealthSummary(): Promise<SystemHealthSummaryResponse> {
  const res = await fetch(`${API_BASE}/api/system/health-summary`)
  if (!res.ok) throw new Error(`Failed to get system health summary: HTTP ${res.status}`)
  return res.json()
}

// Phase 29: Dam-Break Decision-Support API functions

export async function fetchDecisionSupportSummary(
  projectId: string,
  runId?: string,
): Promise<DecisionSupportResponse> {
  const q = runId ? `?run_id=${encodeURIComponent(runId)}` : ''
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/decision-support${q}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Failed to fetch decision support summary: HTTP ${res.status}`)
  }
  return res.json()
}

export function getDecisionSupportExportUrl(
  projectId: string,
  format: 'json' | 'csv' = 'json',
  runId?: string,
): string {
  const qRun = runId ? `&run_id=${encodeURIComponent(runId)}` : ''
  return `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/decision-support/export?format=${format}${qRun}`
}

export async function fetchDemoReadiness(projectId: string): Promise<DemoReadinessResponse> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/demo-readiness`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Failed to fetch demo readiness: HTTP ${res.status}`)
  }
  return res.json()
}

// Phase C1 & B3: Unified Canonical Scenario, Result & Workflow Summary API

export async function fetchWorkflowSummary(projectId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/workflow-summary`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Failed to fetch workflow summary: HTTP ${res.status}`)
  }
  return res.json()
}

export async function listCanonicalResults(projectId: string): Promise<any[]> {
  const res = await fetch(`${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/canonical-results`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Failed to list canonical results: HTTP ${res.status}`)
  }
  return res.json()
}

export async function listCanonicalScenarios(projectId?: string): Promise<any[]> {
  const url = projectId
    ? `${API_BASE}/api/dam-projects/${encodeURIComponent(projectId)}/canonical-scenarios`
    : `${API_BASE}/api/canonical-scenarios`
  const res = await fetch(url)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Failed to list canonical scenarios: HTTP ${res.status}`)
  }
  return res.json()
}


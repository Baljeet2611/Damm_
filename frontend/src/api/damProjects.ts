import type {
  DamProjectValidationResponse,
  DamProjectSummary,
  DamProjectDetailResponse,
  RasterDerivedMetadata,
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

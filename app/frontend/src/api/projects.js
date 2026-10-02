import { apiRequest } from './client'

export function listProjects() {
  return apiRequest('/projects')
}

export function getProject(id) {
  return apiRequest(`/projects/${encodeURIComponent(id)}`)
}

export function createProject(payload) {
  return apiRequest('/projects', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateProjectDesign(id, payload) {
  return apiRequest(`/projects/${encodeURIComponent(id)}/design`, { method: 'PUT', body: JSON.stringify(payload) })
}

export function uploadProjectAsset(id, file, metadata) {
  const body = new FormData()
  body.append('file', file)
  body.append('alt_text', metadata.alt_text)
  body.append('asset_type', metadata.asset_type)
  body.append('section', metadata.section)
  return apiRequest(`/projects/${encodeURIComponent(id)}/assets`, { method: 'POST', body, headers: {} })
}
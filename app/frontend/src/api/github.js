import { apiRequest } from './client'

// Admin-authenticated routes go through the same-origin dev/preview proxy, which adds
// X-Factory-Admin-Token server side. The browser never holds a GitHub or admin secret.
function githubRequest(path, options = {}) {
  return apiRequest(path, { timeout: 60000, sameOrigin: true, ...options })
}

export function getGitHubStatus() {
  return githubRequest('/api/github/status')
}

export function getGitHubInstallations() {
  return githubRequest('/api/github/installations')
}

export function getGitHubRepositories() {
  return githubRequest('/api/github/repositories')
}

export function createGitHubRepository(body) {
  return githubRequest('/api/github/repositories', { method: 'POST', body: JSON.stringify(body) })
}

export function getProjectGitHub(projectId) {
  return githubRequest(`/api/github/projects/${projectId}`)
}

export function connectProjectGitHub(projectId, body) {
  return githubRequest(`/api/github/projects/${projectId}/connect`, { method: 'POST', body: JSON.stringify(body) })
}

export function disconnectProjectGitHub(projectId) {
  return githubRequest(`/api/github/projects/${projectId}`, { method: 'DELETE' })
}

export function publishProjectRun(projectId, runId) {
  return githubRequest(`/api/github/projects/${projectId}/runs/${runId}/publish`, { method: 'POST' })
}

export function createProjectPullRequest(projectId, runId, body = {}) {
  return githubRequest(`/api/github/projects/${projectId}/runs/${runId}/pull-request`, { method: 'POST', body: JSON.stringify(body) })
}

export function getProjectPullRequest(projectId, runId) {
  return githubRequest(`/api/github/projects/${projectId}/runs/${runId}/pull-request`)
}

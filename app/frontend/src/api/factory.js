import { apiRequest } from './client'

export function startFactoryRun(projectId, idempotencyKey) {
  return apiRequest('/api/factory/runs', { method: 'POST', body: JSON.stringify({ project_id: projectId, idempotency_key: idempotencyKey }) })
}

export function getFactoryRun(runId) {
  return apiRequest(`/api/factory/runs/${encodeURIComponent(runId)}`)
}

export function getFactoryEvents(runId) {
  return apiRequest(`/api/factory/runs/${encodeURIComponent(runId)}/events`)
}

export function getFactoryTasks(runId) {
  return apiRequest(`/api/factory/runs/${encodeURIComponent(runId)}/tasks`)
}

export function approveFactoryRun(runId, reason) {
  return apiRequest(`/api/factory/runs/${encodeURIComponent(runId)}/approve`, { method: 'POST', body: JSON.stringify({ reason }) })
}

export function getFactoryTimeline(runId) {
  return apiRequest(`/api/factory/runs/${encodeURIComponent(runId)}/timeline`)
}

export function getFactoryRuntime() {
  return apiRequest('/api/factory/runtime')
}

export function getFactoryMetrics() {
  return apiRequest('/api/factory/metrics')
}

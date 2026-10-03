import { apiRequest } from './client'

export function createTable(payload) {
  return apiRequest('/tables', { method: 'POST', body: JSON.stringify(payload) })
}

export function createReservation(payload) {
  return apiRequest('/reservations', { method: 'POST', body: JSON.stringify(payload) })
}

export function createReservationWithStatus(payload) {
  return apiRequest('/reservations', { method: 'POST', body: JSON.stringify(payload), includeStatus: true })
}

export function getReservation(id) {
  return apiRequest(`/reservations/${encodeURIComponent(id)}`)
}

export function getAvailability(tableId, startTime, endTime) {
  const query = `start_time=${encodeURIComponent(startTime)}&end_time=${encodeURIComponent(endTime)}`
  return apiRequest(`/tables/${encodeURIComponent(tableId)}/availability?${query}`)
}
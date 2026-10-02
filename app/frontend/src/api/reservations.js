import { apiRequest } from './client'

export function createTable(payload) {
  return apiRequest('/tables', { method: 'POST', body: JSON.stringify(payload) })
}

export function createReservation(payload) {
  return apiRequest('/reservations', { method: 'POST', body: JSON.stringify(payload) })
}

export function getReservation(id) {
  return apiRequest(`/reservations/${encodeURIComponent(id)}`)
}
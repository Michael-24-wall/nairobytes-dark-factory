import { apiRequest } from './client'

export function createAccount(payload) {
  return apiRequest('/payments/accounts', { method: 'POST', body: JSON.stringify(payload) })
}

export function getAccount(accountId) {
  return apiRequest(`/payments/accounts/${encodeURIComponent(accountId)}`)
}

export function getAccountEntries(accountId) {
  return apiRequest(`/payments/accounts/${encodeURIComponent(accountId)}/entries`)
}

export function createTransfer(payload) {
  return apiRequest('/payments/transfers', { method: 'POST', body: JSON.stringify(payload), includeStatus: true })
}

export function getTransfer(transferId) {
  return apiRequest(`/payments/transfers/${encodeURIComponent(transferId)}`)
}

export function getTrialBalance() {
  return apiRequest('/payments/ledger/trial-balance')
}
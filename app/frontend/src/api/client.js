const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

export async function apiRequest(path, options = {}) {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), options.timeout || 10000)
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      signal: controller.signal,
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok) {
      const error = new Error(body.message || body.error || `Request failed with ${response.status}`)
      error.status = response.status
      error.code = body.error
      throw error
    }
    return body
  } finally {
    window.clearTimeout(timeout)
  }
}

export const apiBaseUrl = API_BASE_URL
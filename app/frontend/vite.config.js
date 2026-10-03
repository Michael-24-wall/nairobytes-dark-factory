import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const BACKEND_URL = process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

// GitHub routes are admin authenticated. The shared token is injected by the dev/preview
// server on the way to FastAPI so it never reaches the browser bundle.
function adminProxy(env) {
  const adminToken = env.FACTORY_ADMIN_TOKEN
  return {
    '/api/github': {
      target: BACKEND_URL,
      changeOrigin: false,
      configure: (proxy) => {
        proxy.on('proxyReq', (proxyReq) => {
          if (adminToken) proxyReq.setHeader('X-Factory-Admin-Token', adminToken)
        })
      },
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react()],
    server: {
      port: 5173,
      host: '127.0.0.1',
      proxy: adminProxy(env),
    },
    preview: {
      port: 4173,
      host: '127.0.0.1',
      proxy: adminProxy(env),
    },
  }
})

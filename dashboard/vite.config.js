import { existsSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const isDocker = existsSync('/.dockerenv')
const backendTarget = process.env.OPENSHORTS_BACKEND_URL || (isDocker ? 'http://backend:8000' : 'http://localhost:8000')
const rendererTarget = process.env.OPENSHORTS_RENDERER_URL || (isDocker ? 'http://renderer:3100' : 'http://localhost:3100')

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: [
      'openshorts.app',
      'www.openshorts.app'
    ],
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
      },
      '/videos': {
        target: backendTarget,
        changeOrigin: true,
      },
      '/thumbnails': {
        target: backendTarget,
        changeOrigin: true,
      },
      '/gallery': {
        target: backendTarget,
        changeOrigin: true,
      },
      '/video': {
        target: backendTarget,
        changeOrigin: true,
      },
      '/render': {
        target: rendererTarget,
        changeOrigin: true,
      }
    }
  }
})

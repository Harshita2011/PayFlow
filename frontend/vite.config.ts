import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import { validateApiBase } from './src/apiConfiguration.js'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  validateApiBase(env.VITE_API_BASE_URL || 'http://localhost:8001', process.env.VERCEL === '1')
  return { plugins: [react()] }
})

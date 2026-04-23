import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In production (Vercel), VITE_API_URL is set to the deployed backend URL.
// In local dev, requests are proxied to localhost:8000.
const backendUrl = process.env.VITE_API_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/validate': backendUrl,
      '/health': backendUrl,
    },
  },
})

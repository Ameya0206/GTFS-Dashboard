import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxy API calls to the FastAPI backend during development so the frontend
// dev server (port 5173) can reach the backend (port 8000) without CORS issues.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/validate': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Served under https://<service>.onrender.com/app — base must match.
export default defineConfig({
  plugins: [react()],
  base: '/app/',
})

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Render serves the app under https://<service>.onrender.com/app; Telegram
// Serverless (VITE_BACKEND=serverless) from the root of app<id>.tgcloud.ai.
export default defineConfig({
  plugins: [react()],
  base: process.env.VITE_BACKEND === 'serverless' ? '/' : '/app/',
})

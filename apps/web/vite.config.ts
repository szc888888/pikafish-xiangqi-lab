import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: process.env.VITE_HOST || '127.0.0.1',
    port: 1239,
    proxy: {
      '/api': process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000',
      '/auth': process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000',
    },
  },
})


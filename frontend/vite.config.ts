import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: '/ppt/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1024,
  },
  server: {
    proxy: {
      '/ppt/api': {
        target: 'http://127.0.0.1:8000',
        rewrite: (p) => p.replace(/^\/ppt\/api/, '/api'),
      },
    },
  },
})

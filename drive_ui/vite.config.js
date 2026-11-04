import path from 'path'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'

const outDir = path.resolve(import.meta.dirname, '../mpd_customizations/public/drive')
const indexHtmlPath = path.resolve(import.meta.dirname, '../mpd_customizations/www/drive.html')

export default defineConfig({
  plugins: [
    frappeui({
      frappeProxy: true,
      lucideIcons: true,
      jinjaBootData: false,
      buildConfig: {
        outDir,
        indexHtmlPath,
        emptyOutDir: true,
        sourcemap: false,
      },
    }),
    vue(),
  ],
  server: {
    port: 8080,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})

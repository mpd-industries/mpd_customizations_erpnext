import fs from 'fs'
import path from 'path'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const outDir = path.resolve(import.meta.dirname, '../mpd_customizations/public/compliance')
const wwwPage = path.resolve(import.meta.dirname, '../mpd_customizations/www/compliance.html')

export default defineConfig({
  plugins: [
    vue(),
    {
      name: 'compliance-www',
      closeBundle() {
        const built = path.join(outDir, 'index.html')
        if (fs.existsSync(built)) fs.copyFileSync(built, wwwPage)
      },
    },
  ],
  base: '/assets/mpd_customizations/compliance/',
  build: { outDir, emptyOutDir: true },
})

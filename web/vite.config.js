import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import { readdirSync, writeFileSync, mkdirSync, copyFileSync, readFileSync, existsSync } from 'fs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const analysisDir = resolve(root, 'analysis')
const channelsPath = resolve(root, 'channels', 'channels.json')

export default defineConfig({
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://localhost:3001', changeOrigin: true }
    }
  },
  plugins: [
    vue(),
    {
      name: 'analysis-copy',
      writeBundle(opts) {
        const outDir = opts.dir || resolve(root, 'web', 'dist')
        const destDir = resolve(outDir, 'analysis')
        mkdirSync(destDir, { recursive: true })

        const channelsConfig = existsSync(channelsPath)
          ? JSON.parse(readFileSync(channelsPath, 'utf-8'))
          : { channels: [] }
        const channels = (channelsConfig.channels || []).sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
        const index = []

        for (const ch of channels) {
          const channelAnalysisDir = resolve(analysisDir, ch.id)
          if (!existsSync(channelAnalysisDir)) continue

          const allFiles = readdirSync(channelAnalysisDir).filter((f) => f.endsWith('.json'))
          const videos = allFiles.filter((f) => f !== '_channel.json')
          if (videos.length === 0) continue

          const destChannelDir = resolve(destDir, ch.id)
          mkdirSync(destChannelDir, { recursive: true })
          for (const f of allFiles) {
            copyFileSync(resolve(channelAnalysisDir, f), resolve(destChannelDir, f))
          }
          const entry = { id: ch.id, name: ch.name, order: ch.order ?? 999, videos }
          if (allFiles.includes('_channel.json')) {
            entry.channel_analysis = '_channel.json'
          }
          index.push(entry)
        }

        writeFileSync(resolve(destDir, 'index.json'), JSON.stringify(index))
      }
    }
  ]
})

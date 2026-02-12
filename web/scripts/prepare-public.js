import { readdirSync, mkdirSync, copyFileSync, writeFileSync, readFileSync, existsSync, rmSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const root = resolve(__dirname, '../..')
const analysisDir = resolve(root, 'analysis')
const channelsPath = resolve(root, 'channels', 'channels.json')
const publicDir = resolve(__dirname, '../public/analysis')
if (existsSync(publicDir)) rmSync(publicDir, { recursive: true })
mkdirSync(publicDir, { recursive: true })

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

  const destChannelDir = resolve(publicDir, ch.id)
  mkdirSync(destChannelDir, { recursive: true })
  for (const f of allFiles) {
    copyFileSync(resolve(channelAnalysisDir, f), resolve(destChannelDir, f))
  }

  const entry = {
    id: ch.id,
    name: ch.name,
    order: ch.order ?? 999,
    videos
  }
  if (allFiles.includes('_channel.json')) {
    entry.channel_analysis = '_channel.json'
  }
  index.push(entry)
}

writeFileSync(resolve(publicDir, 'index.json'), JSON.stringify(index))

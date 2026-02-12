<script setup>
import { ref, computed, onMounted, watch } from 'vue'

const channelsData = ref([]) // [{ id, name, order, analyses: [...], channel_analysis? }]
const loading = ref(true)
const error = ref(null)
const sortBy = ref('published')
const filterChannel = ref('')
const channelAnalysis = ref(null)
const channelAnalysisLoading = ref(false)
const theme = ref('light')

function initTheme() {
  const stored = localStorage.getItem('media-advisor-theme')
  const prefersDark = matchMedia('(prefers-color-scheme: dark)').matches
  theme.value = stored ?? (prefersDark ? 'dark' : 'light')
  document.documentElement.setAttribute('data-theme', theme.value)
}

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  localStorage.setItem('media-advisor-theme', theme.value)
  document.documentElement.setAttribute('data-theme', theme.value)
}

async function loadAnalyses() {
  loading.value = true
  error.value = null
  try {
    const r = await fetch('/analysis/index.json')
    if (!r.ok) throw new Error('Failed to load index')
    const index = await r.json()
    if (!Array.isArray(index) || index.length === 0) {
      channelsData.value = []
      return
    }

    const channels = []
    for (const ch of index) {
      const analyses = []
      for (const file of ch.videos || []) {
        const res = await fetch(`/analysis/${ch.id}/${file}`)
        if (!res.ok) continue
        const data = await res.json()
        analyses.push({ ...data, channel_id: ch.id, channel_name: ch.name })
      }
      if (analyses.length > 0) {
        channels.push({
          id: ch.id,
          name: ch.name,
          order: ch.order ?? 999,
          analyses,
          channel_analysis: ch.channel_analysis || null
        })
      }
    }
    channels.sort((a, b) => a.order - b.order)
    channelsData.value = channels
  } catch (e) {
    error.value = e.message
    channelsData.value = []
  } finally {
    loading.value = false
  }
}

const channelList = computed(() =>
  channelsData.value.map((ch) => ({ id: ch.id, name: ch.name, count: ch.analyses.length }))
)

const displayAnalyses = computed(() => {
  if (filterChannel.value) {
    const ch = channelsData.value.find((c) => c.id === filterChannel.value)
    return ch ? ch.analyses : []
  }
  return channelsData.value.flatMap((ch) => ch.analyses)
})

const sortedDisplayAnalyses = computed(() => sortedAnalyses(displayAnalyses.value))

function sortedAnalyses(analyses) {
  const list = [...analyses]
  if (sortBy.value === 'published') {
    return list.sort((a, b) => {
      const da = a.metadata?.published_at || a.analyzed_at || ''
      const db = b.metadata?.published_at || b.analyzed_at || ''
      return db.localeCompare(da)
    })
  }
  return list.sort((a, b) =>
    (a.metadata?.title || '').localeCompare(b.metadata?.title || '')
  )
}

function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('it-IT', {
    day: 'numeric',
    month: 'short',
    year: 'numeric'
  })
}

const totalCount = computed(() =>
  channelsData.value.reduce((sum, ch) => sum + ch.analyses.length, 0)
)

async function loadChannelAnalysis(channelId) {
  if (!channelId) {
    channelAnalysis.value = null
    return
  }
  channelAnalysisLoading.value = true
  channelAnalysis.value = null
  try {
    const r = await fetch(`/analysis/${channelId}/_channel.json`)
    if (r.ok) {
      channelAnalysis.value = await r.json()
    }
  } catch {
    // ignore
  } finally {
    channelAnalysisLoading.value = false
  }
}

watch(filterChannel, (id) => loadChannelAnalysis(id || ''))

onMounted(() => {
  initTheme()
  loadAnalyses()
})
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="topbar-inner">
        <h1 class="logo">Media Advisor</h1>
        <div class="channel-pills">
          <button
            type="button"
            class="pill"
            :class="{ active: !filterChannel }"
            @click="filterChannel = ''"
          >
            Tutti
            <span class="pill-badge">{{ totalCount }}</span>
          </button>
          <button
            v-for="ch in channelList"
            :key="ch.id"
            type="button"
            class="pill"
            :class="{ active: filterChannel === ch.id }"
            @click="filterChannel = ch.id"
          >
            {{ ch.name }}
            <span class="pill-badge">{{ ch.count }}</span>
          </button>
        </div>
        <div class="topbar-right">
          <button
            type="button"
            class="theme-toggle"
            :title="theme === 'light' ? 'Modalità scura' : 'Modalità chiara'"
            @click="toggleTheme"
          >
            <span v-if="theme === 'light'" class="theme-icon">☀</span>
            <span v-else class="theme-icon">☽</span>
          </button>
          <select v-model="sortBy" class="sort-select">
            <option value="published">Più recenti</option>
            <option value="title">A–Z</option>
          </select>
        </div>
      </div>
    </header>

    <div v-if="filterChannel" class="channel-banner">
      <div v-if="channelAnalysisLoading" class="channel-analysis-loading">Caricamento analisi canale...</div>
      <div v-else-if="channelAnalysis" class="channel-banner-grid">
        <div class="channel-banner-block">
          <span class="channel-banner-label">Temi</span>
          <p class="channel-banner-text">{{ channelAnalysis.themes?.summary }}</p>
          <div v-if="channelAnalysis.themes?.main_topics?.length" class="channel-banner-tags">
            <span v-for="t in channelAnalysis.themes.main_topics" :key="t" class="channel-tag">{{ t }}</span>
          </div>
        </div>
        <div class="channel-banner-block">
          <span class="channel-banner-label">Incoerenze</span>
          <template v-if="channelAnalysis.inconsistencies?.length">
            <div v-for="(inc, i) in channelAnalysis.inconsistencies" :key="i" class="channel-banner-item">
              <strong>{{ inc.topic }}</strong>
              <p>{{ inc.description }}</p>
            </div>
          </template>
          <p v-else class="channel-banner-empty">Nessuna</p>
        </div>
        <div class="channel-banner-block">
          <span class="channel-banner-label">Bias</span>
          <p v-if="channelAnalysis.bias?.summary" class="channel-banner-text">{{ channelAnalysis.bias.summary }}</p>
          <template v-if="(channelAnalysis.bias?.patterns || []).length">
            <div v-for="p in channelAnalysis.bias.patterns" :key="p.subject" class="channel-banner-item">
              <strong>{{ p.subject }}</strong>
              <p>{{ p.description }}</p>
            </div>
          </template>
          <p v-else-if="!channelAnalysis.bias?.summary" class="channel-banner-empty">Nessuno</p>
        </div>
      </div>
      <p v-else class="channel-banner-empty">Analisi canale non disponibile</p>
    </div>

    <main class="feed">
        <div v-if="loading" class="loading">Caricamento...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="channelsData.length === 0" class="empty-state">
      <p class="empty-state-title">Nessuna analisi</p>
      <p class="empty-state-text">Aggiungi canali in <code>channels/channels.json</code> e esegui <code>npm run run-list</code>.</p>
    </div>
    <div v-else class="feed-grid">
      <a
        v-for="a in sortedDisplayAnalyses"
        :key="`${a.channel_id}-${a.video_id}`"
        :href="`https://www.youtube.com/watch?v=${a.video_id}`"
        target="_blank"
        rel="noopener"
        class="video-card"
      >
        <div class="video-card-thumb">
          <img
            :src="`https://i.ytimg.com/vi/${a.video_id}/mqdefault.jpg`"
            :alt="a.metadata?.title || 'Video'"
            loading="lazy"
          />
          <span class="video-card-badge">▶</span>
        </div>
        <div class="video-card-body">
          <h3 class="video-card-title">{{ a.metadata?.title || 'Senza titolo' }}</h3>
          <div class="video-card-meta">
            <span v-if="!filterChannel && a.channel_name" class="video-card-channel">{{ a.channel_name }}</span>
            <span v-if="a.metadata?.published_at" class="video-card-date">{{ formatDate(a.metadata.published_at) }}</span>
          </div>
          <p class="video-card-summary">{{ (a.summary || '').slice(0, 120) }}{{ (a.summary || '').length > 120 ? '…' : '' }}</p>
          <div class="video-card-topics">
            <span
              v-for="t in (a.topics || []).slice(0, 4)"
              :key="t.name"
              class="video-tag"
              :class="t.relevance"
            >{{ t.name }}</span>
          </div>
        </div>
      </a>
    </div>
      </main>
  </div>
</template>

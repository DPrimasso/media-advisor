<script setup>
import { ref, computed, onMounted, onUnmounted, inject } from 'vue'
import { useFeed } from '../composables/useFeed.js'
import {
  CONFIDENCE_LABELS,
  CONFIDENCE_CLASSES,
  OUTCOME_LABELS,
  OUTCOME_CLASSES,
  CONFIDENCE_CHIP,
  CONFIDENCE_DOT,
  OUTCOME_CHIP,
  OUTCOME_DOT,
} from '../composables/useMercatoLabels.js'

const { channelsData, loading: analysesLoading, loadAnalyses } = inject('channelsData')

const tips = ref([])
const tipsLoading = ref(true)

async function fetchTips() {
  tipsLoading.value = true
  try {
    const res = await fetch('/api/mercato/tips')
    if (res.ok) tips.value = await res.json()
  } finally {
    tipsLoading.value = false
  }
}

// Sync: stato letto da /api/sync/status al mount (se running sul server, UI + poll riprendono)
const syncStatus = ref(null)   // null | { status, log, result, error }
const syncType = ref(null)     // 'recent' | 'total' | 'daily' | null
let syncPollInterval = null

function ensurePollStopped() {
  if (syncPollInterval) {
    clearInterval(syncPollInterval)
    syncPollInterval = null
  }
}

function ensurePollRunning() {
  if (syncPollInterval) return
  syncPollInterval = setInterval(pollSync, 2000)
}

async function hydrateSyncFromServer() {
  try {
    const res = await fetch('/api/sync/status')
    if (!res.ok) return
    const data = await res.json()
    if (data.status === 'idle') {
      syncStatus.value = null
      ensurePollStopped()
      return
    }
    syncStatus.value = data
    if (data.status === 'running') ensurePollRunning()
    else ensurePollStopped()
  } catch {}
}

onMounted(async () => {
  await Promise.all([fetchTips(), hydrateSyncFromServer()])
})

async function _doSync(endpoint, type) {
  const res = await fetch(endpoint, { method: 'POST' })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    syncStatus.value = { status: 'error', error: data.detail || `Errore ${res.status}`, log: [] }
    syncType.value = type
    return
  }
  syncStatus.value = { status: 'running', log: [], result: null, error: null }
  syncType.value = type
  ensurePollRunning()
}

function startSyncRecent()    { return _doSync('/api/sync/recent', 'recent') }
function startSync()          { return _doSync('/api/sync', 'total') }
function startDailyReport()   { return _doSync('/api/sync/daily-report', 'daily') }

async function pollSync() {
  try {
    const res = await fetch('/api/sync/status')
    if (!res.ok) return
    const data = await res.json()
    syncStatus.value = data
    if (data.status === 'done' || data.status === 'error') {
      ensurePollStopped()
      if (data.status === 'done') {
        await fetchTips()
        await loadAnalyses()
        if (data.result?.digest) {
          digest.value = data.result.digest
          digestDate.value = new Date().toISOString().slice(0, 10)
        }
        if (Array.isArray(data.result?.digest_items)) {
          digestItems.value = data.result.digest_items
        }
      }
    }
  } catch {}
}

onUnmounted(() => {
  ensurePollStopped()
})

const loading = computed(() => tipsLoading.value || analysesLoading.value)

const { feedDays, isEmpty } = useFeed(tips, channelsData)

// Sommario
const todayISO = new Date().toISOString().slice(0, 10)
const digest = ref(null)
const digestRaw = ref(null)
const digestItems = ref([])
const digestFromCache = ref(false)
const digestLoading = ref(false)
const digestError = ref(null)
const digestDate = ref(todayISO)
const digestCopied = ref(false)
const telegramStatus = ref(null)  // null | 'loading' | 'done' | 'error'
const telegramError = ref(null)

const DIGEST_SECTIONS = [
  { title: '✅ Situazioni calde / scenari aperti', toneClass: 'digest-sec--hot' },
  { title: '🕐 Situazioni da monitorare', toneClass: 'digest-sec--watch' },
  { title: '🚫 Voci ridimensionate / smentite', toneClass: 'digest-sec--deny' },
]
const DIGEST_SECTION_ORDER = DIGEST_SECTIONS.map((section) => section.title)
const DIGEST_SECTION_SET = new Set(DIGEST_SECTION_ORDER)
const DIGEST_SECTION_TONE_CLASS = Object.fromEntries(
  DIGEST_SECTIONS.map((section) => [section.title, section.toneClass]),
)

function parseDigestSections(rawDigest) {
  if (!rawDigest || typeof rawDigest !== 'string') return null

  const lines = rawDigest
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)

  if (!lines.length) return null

  const sections = []
  let currentSection = null
  let expectedSectionIndex = 0

  for (const rawLine of lines) {
    const normalizedLine = rawLine
      .replace(/^#{1,6}\s+/, '')
      .replace(/^\*\*(.+)\*\*$/, '$1')
      .replace(/:$/, '')
      .replace(/\s+/g, ' ')
      .trim()

    if (DIGEST_SECTION_SET.has(normalizedLine)) {
      if (normalizedLine !== DIGEST_SECTION_ORDER[expectedSectionIndex]) return null
      currentSection = { title: normalizedLine, items: [] }
      sections.push(currentSection)
      expectedSectionIndex += 1
      continue
    }

    if (!currentSection) return null

    const item = rawLine
      .replace(/^[-*•](?:\s+|$)/, '')
      .replace(/^\d+[.)]\s+/, '')
      .trim()
    if (!item) continue
    currentSection.items.push(item)
  }

  if (expectedSectionIndex !== DIGEST_SECTION_ORDER.length) return null
  if (sections.some((section) => section.items.length === 0)) return null

  return sections
}

const parsedDigestSections = computed(() => parseDigestSections(digest.value))

const digestStructuredSections = computed(() => {
  if (!Array.isArray(digestItems.value) || digestItems.value.length === 0) return null
  const map = new Map()
  for (const row of digestItems.value) {
    const sec = row.section
    if (typeof sec !== 'string' || !DIGEST_SECTION_SET.has(sec)) continue
    if (!map.has(sec)) map.set(sec, [])
    map.get(sec).push(row)
  }
  return DIGEST_SECTION_ORDER.map((title) => ({
    title,
    items: map.get(title) || [],
  }))
})

function digestStateIcon(stato) {
  if (stato === 'caldo') return '🔥'
  if (stato === 'monitorare') return '👀'
  if (stato === 'smentita') return '🧊'
  return '•'
}

function digestSourceTimeLabel(startSec) {
  const off = formatYoutubeOffset(startSec)
  return off || '??:??'
}

async function copyDigest() {
  if (!digest.value) return
  try {
    await navigator.clipboard.writeText(digest.value)
    digestCopied.value = true
    setTimeout(() => { digestCopied.value = false }, 2000)
  } catch {
    // fallback silenzioso se clipboard non disponibile
  }
}

async function publishToTelegram() {
  if (!digestRaw.value) return
  telegramStatus.value = 'loading'
  telegramError.value = null
  try {
    const res = await fetch('/api/feed/digest/publish-telegram', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ digest: digestRaw.value, date: digestDate.value }),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || `Errore ${res.status}`)
    telegramStatus.value = 'done'
  } catch (e) {
    telegramStatus.value = 'error'
    telegramError.value = e.message
  }
}

async function generateDigest(force = false) {
  digestLoading.value = true
  digestError.value = null
  digest.value = null
  digestRaw.value = null
  digestItems.value = []
  digestFromCache.value = false
  telegramStatus.value = null
  telegramError.value = null
  try {
    const url = `/api/feed/digest?date=${digestDate.value}${force ? '&force=true' : ''}`
    const res = await fetch(url)
    if (!res.ok) throw new Error(`Errore ${res.status}`)
    const data = await res.json()
    if (data.digest) {
      digest.value = data.digest
      digestRaw.value = data.digest_raw ?? null
      digestItems.value = Array.isArray(data.digest_items) ? data.digest_items : []
      digestFromCache.value = data.cached === true
    } else {
      digestError.value = data.message || 'Nessun contenuto per questa data'
    }
  } catch (e) {
    digestError.value = e.message
  } finally {
    digestLoading.value = false
  }
}

const formattedToday = new Date().toLocaleDateString('it-IT', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
}).replace(/\b\w/g, (c) => c.toUpperCase())

function formatTime(dateObj) {
  return dateObj.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
}

function formatChannelName(channelId) {
  return channelId
    .split('-')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

function truncate(text, len) {
  if (!text) return ''
  return text.length > len ? text.slice(0, len) + '…' : text
}

function formatYoutubeOffset(sec) {
  if (sec == null || Number.isNaN(Number(sec))) return ''
  const s = Math.max(0, Math.floor(Number(sec)))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
    : `${m}:${String(ss).padStart(2, '0')}`
}

function youtubeWatchUrl(videoId, startSec) {
  if (!videoId) return ''
  const base = `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`
  if (startSec == null || Number.isNaN(Number(startSec))) return base
  const t = Math.max(0, Math.floor(Number(startSec)))
  return `${base}&t=${t}s`
}

function tipSourceHref(item) {
  return youtubeWatchUrl(item.video_id, item.quote_start_sec)
}

function tipSourceLabel(item) {
  const off = formatYoutubeOffset(item.quote_start_sec)
  return off ? `▶ ${off}` : '▶ Video'
}

function analysisEarliestQuoteSec(item) {
  let min = null
  for (const c of item.claims || []) {
    const s = c.evidence_quotes?.[0]?.start_sec
    if (s != null && !Number.isNaN(Number(s))) {
      const n = Number(s)
      min = min == null ? n : Math.min(min, n)
    }
  }
  return min
}

function analysisSourceHref(item) {
  return youtubeWatchUrl(item.video_id, analysisEarliestQuoteSec(item))
}

function analysisSourceLabel(item) {
  const off = formatYoutubeOffset(analysisEarliestQuoteSec(item))
  return off ? `▶ ${off}` : '▶ Video'
}
</script>

<template>
  <div class="page">
    <header class="masthead">
      <div>
        <h2 class="masthead-title">Rassegna Stampa</h2>
        <p class="masthead-date">{{ formattedToday }}</p>
      </div>
      <div class="masthead-actions">
        <button
          class="btn btn-primary"
          :disabled="syncStatus?.status === 'running'"
          @click="startSyncRecent"
          title="Scarica i nuovi video, esegue transcript e analisi"
        >
          <svg v-if="!(syncStatus?.status === 'running' && syncType === 'recent')" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>
          <span v-else class="spin-sm"></span>
          {{ syncStatus?.status === 'running' && syncType === 'recent' ? 'Sincronizzando…' : 'Sincronizza' }}
        </button>
        <button
          class="btn btn-secondary"
          style="opacity:0.55;font-size:12px"
          :disabled="syncStatus?.status === 'running'"
          @click="startSync"
          title="Riscarica e analizza tutti i video"
        >
          Totale
        </button>
      </div>
    </header>

    <div v-if="syncStatus && syncStatus.status !== 'idle'" class="sync-panel">
      <div class="sync-head">
        <span class="sync-lbl">
          <template v-if="syncStatus.status === 'running'">
            {{ syncType === 'daily' ? 'Pubblicazione in corso' : 'Sincronizzazione' }}
          </template>
          <template v-else-if="syncStatus.status === 'done'">Completata</template>
          <template v-else>Errore</template>
        </span>
        <div v-if="syncStatus.status === 'done' && syncStatus.result" style="display:flex;gap:5px;flex-wrap:wrap">
          <span class="chip chip--green">+{{ syncStatus.result.new_videos ?? 0 }} video</span>
          <span class="chip chip--green">{{ syncStatus.result.analyzed ?? 0 }} analisi</span>
          <span v-if="syncStatus.result.mercato_tips" class="chip chip--amber">{{ syncStatus.result.mercato_tips }} tip</span>
          <span v-if="syncStatus.result.digest" class="chip chip--gold">Sommario generato</span>
        </div>
        <button v-if="syncStatus.status !== 'running'" class="btn-icon" style="width:24px;height:24px;font-size:11px;margin-left:auto" @click="syncStatus = null">✕</button>
      </div>
      <div v-if="syncStatus.status === 'running' && syncStatus.progress?.total > 0">
        <div class="progress-track">
          <div
            class="progress-fill"
            :style="{ width: Math.round((syncStatus.progress.current / syncStatus.progress.total) * 100) + '%' }"
          ></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-family:var(--m);font-size:11px;color:var(--tm);margin-bottom:7px">
          <span>{{ syncStatus.progress.channel || '' }}</span>
          <span>{{ Math.round((syncStatus.progress.current / syncStatus.progress.total) * 100) }}%</span>
        </div>
      </div>
      <div v-if="syncStatus.log?.length" class="sync-log">
        <div v-for="(line, i) in syncStatus.log.slice(-8)" :key="i">{{ line }}</div>
      </div>
      <p v-if="syncStatus.error" style="font-size:12px;color:var(--re);margin-top:6px">{{ syncStatus.error }}</p>
    </div>

    <div class="digest">
      <div class="digest-head">
        <div>
          <div class="label digest-eyebrow">Sommario AI</div>
          <h3 class="digest-title">Briefing del Giorno</h3>
        </div>
        <div class="digest-controls">
          <input
            type="date"
            class="digest-input"
            v-model="digestDate"
            :max="todayISO"
          />
          <button
            class="btn btn-primary btn-sm"
            :disabled="digestLoading"
            @click="generateDigest(false)"
          >
            {{ digestLoading && !digest ? '…' : '✦ Genera' }}
          </button>
          <button
            v-if="digest"
            class="btn btn-secondary btn-sm"
            :disabled="digestLoading"
            @click="generateDigest(true)"
          >
            {{ digestLoading ? '…' : '↺ Rigenera' }}
          </button>
          <span v-if="digestFromCache && !digestLoading" class="chip chip--gold" style="font-size:11px">salvato</span>
        </div>
      </div>

      <div v-if="digest" class="digest-body">
        <div v-if="digestStructuredSections">
          <div
            v-for="section in digestStructuredSections"
            :key="section.title"
            :class="['digest-sec', DIGEST_SECTION_TONE_CLASS[section.title] || '']"
          >
            <div class="digest-sec-title">{{ section.title }}</div>
            <ul class="digest-list">
              <li
                v-for="(item, index) in section.items"
                :key="`${section.title}-${index}-${item.player}`"
                class="digest-item digest-item--structured"
              >
                <span class="digest-item-dot"></span>
                <div class="digest-item-stack">
                  <div class="digest-item-line1">
                    <span class="digest-item-icon">{{ digestStateIcon(item.stato) }}</span>
                    <strong>{{ item.player }}</strong>
                    <span class="digest-item-club">({{ item.club }})</span>
                    <span class="digest-item-dash">—</span>
                    <span>{{ item.movimento }}</span>
                  </div>
                  <div v-if="item.motivo" class="digest-item-motivo">{{ item.motivo }}</div>
                  <div
                    v-if="item.sources?.length || item.fonte"
                    class="digest-item-fonte digest-item-fonte--row"
                  >
                    <span class="digest-item-fonte-lbl">Fonte:</span>
                    <template v-if="item.sources?.length">
                      <template v-for="(s, si) in item.sources" :key="`${s.channel_id}-${s.video_id}-${si}`">
                        <a
                          class="digest-fonte-link"
                          :href="s.watch_url"
                          target="_blank"
                          rel="noopener noreferrer"
                          @click.stop
                        >{{ s.channel_label }} ({{ digestSourceTimeLabel(s.start_sec) }})</a>
                        <span v-if="si < item.sources.length - 1" class="digest-fonte-sep" aria-hidden="true">·</span>
                      </template>
                    </template>
                    <template v-else>{{ item.fonte }}</template>
                  </div>
                </div>
              </li>
            </ul>
          </div>
        </div>
        <div v-else-if="parsedDigestSections">
          <div
            v-for="section in parsedDigestSections"
            :key="section.title"
            :class="['digest-sec', DIGEST_SECTION_TONE_CLASS[section.title] || '']"
          >
            <div class="digest-sec-title">{{ section.title }}</div>
            <ul class="digest-list">
              <li
                v-for="(item, index) in section.items"
                :key="`${section.title}-${index}`"
                class="digest-item"
              >
                <span class="digest-item-dot"></span>
                <span>{{ item }}</span>
              </li>
            </ul>
          </div>
        </div>
        <div v-else style="padding:16px 22px">
          <p style="font-size:13.5px;color:var(--t2);white-space:pre-wrap">{{ digest }}</p>
        </div>
        <div class="digest-foot">
          <button class="btn btn-secondary btn-sm" @click="copyDigest">
            {{ digestCopied ? '✓ Copiato' : 'Copia testo' }}
          </button>
          <button
            class="btn btn-secondary btn-sm"
            :disabled="telegramStatus === 'loading' || !digestRaw"
            @click="publishToTelegram"
            title="Invia il sommario su Telegram"
          >
            <svg v-if="telegramStatus !== 'loading'" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            <span v-else class="spin-sm"></span>
            <span v-if="telegramStatus === 'done'">Inviato ✓</span>
            <span v-else-if="telegramStatus === 'error'">Errore</span>
            <span v-else>Telegram</span>
          </button>
          <span v-if="telegramStatus === 'error' && telegramError" style="font-size:12px;color:var(--re)">{{ telegramError }}</span>
          <span style="margin-left:auto;font-family:var(--m);font-size:11px;color:var(--tm)">{{ digestDate }}</span>
        </div>
      </div>
      <p v-else-if="digestError" style="padding:16px 22px;font-size:13px;color:var(--re)">{{ digestError }}</p>
      <div v-else class="digest-placeholder">
        Clicca <strong>Genera</strong> per ricevere il briefing giornaliero elaborato dall'AI.
      </div>
    </div>

    <div v-if="loading" class="loading-wrap">
      <div class="spinner"></div>
      <span>Caricamento…</span>
    </div>

    <div v-else-if="isEmpty" class="empty">
      <div class="empty-icon">◦</div>
      <div class="empty-title">Nessun contenuto recente</div>
      <div class="empty-sub">Non ci sono notizie o analisi negli ultimi 7 giorni.</div>
    </div>

    <template v-else>
      <div v-for="day in feedDays" :key="day.key" class="day-group">
        <h3 class="day-head">
          {{ day.label }}
          <span class="day-count">{{ day.items.length }}</span>
        </h3>
        <div class="day-items">
          <template
            v-for="item in day.items"
            :key="item.type + '-' + (item.tip_id || item.video_id)"
          >
            <article v-if="item.type === 'tip'" class="fc">
              <div class="fc-meta">
                <span class="cat-tag cat-tag--mercato">Mercato</span>
                <span class="fc-src">{{ item.channel_name || formatChannelName(item.channel_id) }}</span>
                <a
                  v-if="item.video_id"
                  class="fc-yt"
                  :href="tipSourceHref(item)"
                  target="_blank"
                  rel="noopener noreferrer"
                  @click.stop
                >{{ tipSourceLabel(item) }}</a>
                <span class="fc-time">{{ formatTime(item.date) }}</span>
              </div>
              <div class="fc-chips">
                <span class="chip" :class="CONFIDENCE_CHIP[item.confidence] || 'chip--muted'">
                  <span class="status-dot" :class="CONFIDENCE_DOT[item.confidence] || 'dot-muted'"></span>
                  {{ CONFIDENCE_LABELS[item.confidence] || item.confidence }}
                </span>
                <span class="chip" :class="OUTCOME_CHIP[item.outcome] || 'chip--muted'">
                  <span class="status-dot" :class="OUTCOME_DOT[item.outcome] || 'dot-muted'"></span>
                  {{ OUTCOME_LABELS[item.outcome] || item.outcome }}
                </span>
              </div>
              <button class="fc-player">{{ item.player_name }}</button>
              <div v-if="item.from_club || item.to_club" class="fc-transfer">
                <span v-if="item.from_club" class="fc-from">{{ item.from_club }}</span>
                <span class="fc-arr">→</span>
                <span v-if="item.to_club" class="fc-to">{{ item.to_club }}</span>
                <span v-else class="fc-to-unk">destinazione aperta</span>
              </div>
              <p class="fc-text">{{ item.tip_text }}</p>
            </article>

            <article v-else-if="item.type === 'analysis'" class="fc">
              <div class="fc-meta">
                <span class="cat-tag cat-tag--video">Analisi</span>
                <span class="fc-src">{{ item.channel_name || formatChannelName(item.channel_id) }}</span>
                <a
                  v-if="item.video_id"
                  class="fc-yt"
                  :href="analysisSourceHref(item)"
                  target="_blank"
                  rel="noopener noreferrer"
                  @click.stop
                >{{ analysisSourceLabel(item) }}</a>
                <span class="fc-time">{{ formatTime(item.date) }}</span>
              </div>
              <h4 class="fc-title">{{ item.metadata?.title }}</h4>
              <p v-if="item.summary" class="fc-text">{{ truncate(item.summary, 220) }}</p>
              <div v-if="item.topics?.length" class="fc-topics">
                <span
                  v-for="t in item.topics.slice(0, 4)"
                  :key="t.name || t"
                  :class="['fc-topic', t.relevance === 'high' ? 'fc-topic--hi' : '']"
                >{{ t.name || t }}</span>
              </div>
            </article>
          </template>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.spin-sm {
  display: inline-block;
  width: 12px; height: 12px;
  border: 2px solid var(--line-md);
  border-top-color: #0B0C10;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>

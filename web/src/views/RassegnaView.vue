<script setup>
import { ref, computed, onMounted, onUnmounted, inject } from 'vue'
import { useFeed } from '../composables/useFeed.js'
import {
  CONFIDENCE_LABELS,
  CONFIDENCE_CLASSES,
  OUTCOME_LABELS,
  OUTCOME_CLASSES,
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

onMounted(fetchTips)

// Sync
const syncStatus = ref(null)   // null | { status, log, result, error }
let syncPollInterval = null

async function _doSync(endpoint) {
  const res = await fetch(endpoint, { method: 'POST' })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    syncStatus.value = { status: 'error', error: data.detail || `Errore ${res.status}`, log: [] }
    return
  }
  syncStatus.value = { status: 'running', log: [], result: null, error: null }
  syncPollInterval = setInterval(pollSync, 2000)
}

function startSyncRecent() { return _doSync('/api/sync/recent') }
function startSync()       { return _doSync('/api/sync') }

async function pollSync() {
  try {
    const res = await fetch('/api/sync/status')
    if (!res.ok) return
    const data = await res.json()
    syncStatus.value = data
    if (data.status === 'done' || data.status === 'error') {
      clearInterval(syncPollInterval)
      syncPollInterval = null
      if (data.status === 'done') {
        // Ricarica i dati
        await fetchTips()
        await loadAnalyses()
      }
    }
  } catch {}
}

onUnmounted(() => {
  if (syncPollInterval) clearInterval(syncPollInterval)
})

const loading = computed(() => tipsLoading.value || analysesLoading.value)

const { feedDays, isEmpty } = useFeed(tips, channelsData)

// Sommario
const digest = ref(null)
const digestLoading = ref(false)
const digestError = ref(null)

async function generateDigest() {
  digestLoading.value = true
  digestError.value = null
  try {
    const today = new Date().toISOString().slice(0, 10)
    const res = await fetch(`/api/feed/digest?date=${today}`)
    if (!res.ok) throw new Error(`Errore ${res.status}`)
    const data = await res.json()
    if (data.digest) {
      digest.value = data.digest
    } else {
      digestError.value = data.message || 'Nessun contenuto per oggi'
    }
  } catch (e) {
    digestError.value = e.message
  } finally {
    digestLoading.value = false
  }
}

const formattedToday = computed(() => {
  return new Date().toLocaleDateString('it-IT', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).replace(/\b\w/g, (c) => c.toUpperCase())
})

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
</script>

<template>
  <div class="rassegna-view">
    <header class="rassegna-masthead">
      <div class="rassegna-masthead-left">
        <h2 class="rassegna-title">Rassegna Stampa</h2>
        <p class="rassegna-date">{{ formattedToday }}</p>
      </div>
      <div class="sync-buttons">
        <!-- Sincronizza Recenti: solo video nuovi dall'ultima sync -->
        <button
          class="btn-sync"
          :class="{
            'btn-sync--running': syncStatus?.status === 'running',
            'btn-sync--done': syncStatus?.status === 'done',
            'btn-sync--error': syncStatus?.status === 'error',
          }"
          :disabled="syncStatus?.status === 'running'"
          @click="startSyncRecent"
          title="Scarica solo i video usciti dopo l'ultima sincronizzazione"
        >
          <span class="btn-sync-icon">
            <svg v-if="syncStatus?.status !== 'running'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>
            <span v-else class="sync-spinner"></span>
          </span>
          <span class="btn-sync-label">
            <template v-if="!syncStatus || syncStatus.status === 'idle'">Sincronizza Recenti</template>
            <template v-else-if="syncStatus.status === 'running'">In corso…</template>
            <template v-else-if="syncStatus.status === 'done'">Aggiornato</template>
            <template v-else-if="syncStatus.status === 'error'">Errore</template>
          </span>
        </button>

        <!-- Sincronizza Totale: comportamento originale, tutti i video mancanti -->
        <button
          class="btn-sync btn-sync--secondary"
          :disabled="syncStatus?.status === 'running'"
          @click="startSync"
          title="Scarica tutti i video e ri-analizza quelli mancanti"
        >
          <span class="btn-sync-icon">
            <svg v-if="syncStatus?.status !== 'running'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>
            <span v-else class="sync-spinner"></span>
          </span>
          <span class="btn-sync-label">Sincronizza Totale</span>
        </button>
      </div>
    </header>

    <!-- Pannello log sync -->
    <div v-if="syncStatus && syncStatus.status !== 'idle'" class="sync-panel">
      <div class="sync-panel-header">
        <span class="sync-panel-title">
          <template v-if="syncStatus.status === 'running'">Sincronizzazione in corso</template>
          <template v-else-if="syncStatus.status === 'done'">Sincronizzazione completata</template>
          <template v-else>Sincronizzazione fallita</template>
        </span>
        <div v-if="syncStatus.status === 'done' && syncStatus.result" class="sync-result-badges">
          <span class="sync-badge">+{{ syncStatus.result.new_videos ?? 0 }} video</span>
          <span class="sync-badge">{{ syncStatus.result.analyzed ?? 0 }} analisi</span>
          <span v-if="syncStatus.result.mercato_tips" class="sync-badge sync-badge--mercato">{{ syncStatus.result.mercato_tips }} tip mercato</span>
        </div>
        <button v-if="syncStatus.status !== 'running'" class="sync-panel-close" @click="syncStatus = null">✕</button>
      </div>
      <!-- Progress bar (solo durante il run, quando abbiamo total > 0) -->
      <div v-if="syncStatus.status === 'running' && syncStatus.progress?.total > 0" class="sync-progress-wrap">
        <div class="sync-progress-bar">
          <div
            class="sync-progress-fill"
            :style="{ width: Math.round((syncStatus.progress.current / syncStatus.progress.total) * 100) + '%' }"
          ></div>
        </div>
        <div class="sync-progress-meta">
          <span class="sync-progress-count">{{ syncStatus.progress.current }} / {{ syncStatus.progress.total }} video</span>
          <span v-if="syncStatus.progress.channel" class="sync-progress-channel">{{ syncStatus.progress.channel }}</span>
          <span class="sync-progress-pct">{{ Math.round((syncStatus.progress.current / syncStatus.progress.total) * 100) }}%</span>
        </div>
      </div>

      <div v-if="syncStatus.log?.length" class="sync-log">
        <div
          v-for="(line, i) in syncStatus.log.slice(-8)"
          :key="i"
          class="sync-log-line"
        >{{ line }}</div>
      </div>
      <p v-if="syncStatus.error" class="sync-error">{{ syncStatus.error }}</p>
    </div>

    <section class="sommario-section">
      <div class="sommario-header">
        <h3 class="sommario-title">Sommario del Giorno</h3>
        <button
          class="btn-genera"
          :disabled="digestLoading"
          @click="generateDigest"
        >
          {{ digestLoading ? 'Generando…' : digest ? '↺ Rigenera' : '✦ Genera Sommario' }}
        </button>
      </div>
      <p v-if="digest" class="sommario-text">{{ digest }}</p>
      <p v-else-if="digestError" class="sommario-error">{{ digestError }}</p>
      <p v-else-if="!digestLoading" class="sommario-placeholder">
        Clicca "Genera Sommario" per ricevere un briefing giornalistico generato da AI.
      </p>
    </section>

    <div v-if="loading" class="loading">Caricamento…</div>

    <div v-else-if="isEmpty" class="empty-state">
      <p class="empty-state-title">Nessun contenuto recente</p>
      <p class="empty-state-text">Non ci sono notizie o analisi negli ultimi 7 giorni.</p>
    </div>

    <div v-else class="feed-days">
      <section v-for="day in feedDays" :key="day.key" class="feed-day">
        <h3 class="day-header">{{ day.label }}</h3>
        <div class="day-items">
          <template
            v-for="item in day.items"
            :key="item.type + '-' + (item.tip_id || item.video_id)"
          >
            <!-- Tip card -->
            <div v-if="item.type === 'tip'" class="feed-card feed-card--tip">
              <div class="fc-meta">
                <span class="fc-type-badge fc-type-badge--tip">Mercato</span>
                <span class="fc-channel">{{ item.channel_name || formatChannelName(item.channel_id) }}</span>
                <span class="fc-time">{{ formatTime(item.date) }}</span>
              </div>
              <div class="fc-tip-header">
                <span class="fc-player">{{ item.player_name }}</span>
                <span :class="['badge', CONFIDENCE_CLASSES[item.confidence]]">
                  {{ CONFIDENCE_LABELS[item.confidence] || item.confidence }}
                </span>
                <span :class="['badge', OUTCOME_CLASSES[item.outcome]]">
                  {{ OUTCOME_LABELS[item.outcome] || item.outcome }}
                </span>
              </div>
              <div v-if="item.from_club || item.to_club" class="fc-transfer">
                <span v-if="item.from_club" class="fc-from">{{ item.from_club }}</span>
                <span class="fc-arrow">→</span>
                <span v-if="item.to_club" class="fc-to">{{ item.to_club }}</span>
                <span v-else class="fc-to fc-to--unknown">?</span>
              </div>
              <p class="fc-text">{{ item.tip_text }}</p>
            </div>

            <!-- Analysis card -->
            <div v-else-if="item.type === 'analysis'" class="feed-card feed-card--analysis">
              <div class="fc-meta">
                <span class="fc-type-badge fc-type-badge--analysis">Video</span>
                <span class="fc-channel">{{ item.channel_name || formatChannelName(item.channel_id) }}</span>
                <span class="fc-time">{{ formatTime(item.date) }}</span>
              </div>
              <h4 class="fc-video-title">{{ item.metadata?.title }}</h4>
              <p v-if="item.summary" class="fc-text">{{ truncate(item.summary, 220) }}</p>
              <div v-if="item.topics?.length" class="fc-topics">
                <span
                  v-for="t in item.topics.slice(0, 4)"
                  :key="t.name || t"
                  class="fc-topic-tag"
                >{{ t.name || t }}</span>
              </div>
            </div>
          </template>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.rassegna-view {
  min-height: 60vh;
}

/* Masthead */
.rassegna-masthead {
  padding: 1.5rem 0 1rem;
  border-bottom: 2px solid var(--text);
  margin-bottom: 1.5rem;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}

.rassegna-masthead-left {
  flex: 1;
  min-width: 0;
}

.rassegna-title {
  font-size: 2rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  margin: 0 0 0.2rem;
  color: var(--text);
  text-transform: uppercase;
}

.rassegna-date {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text-muted);
  margin: 0;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

/* Sync buttons wrapper */
.sync-buttons {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
  flex-wrap: wrap;
}

/* Sync button */
.btn-sync {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.5rem 1rem;
  background: var(--bg-card);
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
  white-space: nowrap;
  flex-shrink: 0;
}

.btn-sync:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text);
  border-color: var(--accent);
}

.btn-sync:disabled {
  cursor: not-allowed;
  opacity: 0.75;
}

.btn-sync--done {
  border-color: var(--success);
  color: var(--success);
}

.btn-sync--error {
  border-color: var(--danger);
  color: var(--danger);
}

.btn-sync--secondary {
  opacity: 0.7;
  font-size: 0.8rem;
}

.btn-sync-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
}

.sync-spinner {
  display: block;
  width: 13px;
  height: 13px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

/* Sync panel */
.sync-panel {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1rem 1.25rem;
  margin-bottom: 1.5rem;
}

.sync-panel-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-bottom: 0.5rem;
}

.sync-panel-title {
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

.sync-result-badges {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.sync-badge {
  font-size: 0.75rem;
  padding: 0.15rem 0.5rem;
  background: rgba(5, 150, 105, 0.1);
  color: var(--success);
  border-radius: 4px;
  font-weight: 600;
}

.sync-badge--mercato {
  background: rgba(217, 119, 6, 0.1);
  color: var(--warning);
}

.sync-panel-close {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 0.85rem;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  font-family: inherit;
}

.sync-panel-close:hover {
  background: var(--bg-hover);
  color: var(--text);
}

/* Progress bar */
.sync-progress-wrap {
  margin-bottom: 0.75rem;
}

.sync-progress-bar {
  height: 6px;
  background: var(--bg-hover);
  border-radius: 99px;
  overflow: hidden;
  margin-bottom: 0.35rem;
}

.sync-progress-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 99px;
  transition: width 0.4s ease;
  min-width: 2px;
}

.sync-progress-meta {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-size: 0.75rem;
}

.sync-progress-count {
  font-weight: 600;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.sync-progress-channel {
  color: var(--accent);
  font-weight: 500;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sync-progress-pct {
  margin-left: auto;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.sync-log {
  font-size: 0.8rem;
  color: var(--text-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  line-height: 1.6;
  background: var(--bg-hover);
  border-radius: var(--radius-sm);
  padding: 0.5rem 0.75rem;
  max-height: 160px;
  overflow-y: auto;
}

.sync-log-line {
  white-space: pre-wrap;
  word-break: break-all;
}

.sync-error {
  font-size: 0.85rem;
  color: var(--danger);
  margin: 0.5rem 0 0;
}

/* Sommario */
.sommario-section {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.25rem 1.5rem;
  margin-bottom: 2rem;
}

.sommario-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.75rem;
}

.sommario-title {
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  margin: 0;
}

.btn-genera {
  padding: 0.45rem 1rem;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: var(--radius-pill);
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.15s, opacity 0.15s;
  white-space: nowrap;
}

.btn-genera:hover:not(:disabled) {
  background: var(--accent-hover);
}

.btn-genera:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.sommario-text {
  font-size: 1rem;
  line-height: 1.7;
  color: var(--text);
  margin: 0;
  font-style: italic;
}

.sommario-placeholder {
  font-size: 0.9rem;
  color: var(--text-muted);
  margin: 0;
}

.sommario-error {
  font-size: 0.9rem;
  color: var(--danger);
  margin: 0;
}

/* Feed days */
.feed-days {
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

.feed-day {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.day-header {
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  margin: 0 0 0.75rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border);
}

.day-items {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

/* Feed card base */
.feed-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  transition: box-shadow 0.18s;
}

.feed-card:hover {
  box-shadow: var(--shadow-card);
}

/* Left accent line per tipo */
.feed-card--tip {
  border-left: 3px solid var(--warning);
}

.feed-card--analysis {
  border-left: 3px solid var(--accent);
}

/* Meta row */
.fc-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.78rem;
  color: var(--text-muted);
  flex-wrap: wrap;
}

.fc-type-badge {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
}

.fc-type-badge--tip {
  background: rgba(217, 119, 6, 0.14);
  color: var(--warning);
}

.fc-type-badge--analysis {
  background: var(--accent-soft);
  color: var(--accent);
}

.fc-channel {
  font-weight: 600;
  color: var(--accent);
}

.fc-time {
  color: var(--text-muted);
  margin-left: auto;
}

/* Tip header */
.fc-tip-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.fc-player {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text);
}

/* Transfer arrow */
.fc-transfer {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.9rem;
  color: var(--text-secondary);
}

.fc-from {
  font-weight: 500;
}

.fc-arrow {
  color: var(--text-muted);
}

.fc-to {
  font-weight: 500;
}

.fc-to--unknown {
  color: var(--text-muted);
  font-style: italic;
}

/* Text */
.fc-text {
  font-size: 0.9rem;
  color: var(--text-secondary);
  line-height: 1.55;
  margin: 0;
}

/* Analysis title */
.fc-video-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text);
  margin: 0;
  line-height: 1.4;
}

/* Topics */
.fc-topics {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.1rem;
}

.fc-topic-tag {
  font-size: 0.72rem;
  padding: 0.2rem 0.5rem;
  background: var(--bg-hover);
  color: var(--text-secondary);
  border-radius: 6px;
}

/* Reuse badge styles from mercato */
.badge {
  display: inline-flex;
  align-items: center;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  white-space: nowrap;
}

.conf-rumor { background: rgba(148,163,184,.14); color: var(--text-muted); }
.conf-likely { background: rgba(217,119,6,.12); color: var(--warning); }
.conf-confirmed { background: rgba(5,150,105,.12); color: var(--success); }
.conf-denied { background: rgba(220,38,38,.10); color: var(--danger); }

.outcome-pending { background: rgba(148,163,184,.14); color: var(--text-muted); }
.outcome-true { background: rgba(5,150,105,.12); color: var(--success); }
.outcome-partial { background: rgba(217,119,6,.12); color: var(--warning); }
.outcome-false { background: rgba(220,38,38,.10); color: var(--danger); }
.outcome-stalled { background: rgba(79,70,229,.10); color: var(--accent); }

@media (max-width: 700px) {
  .rassegna-title {
    font-size: 1.4rem;
  }
  .sommario-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>

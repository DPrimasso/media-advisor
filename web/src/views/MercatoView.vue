<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { OUTCOME_LABELS, CONFIDENCE_LABELS, OUTCOME_CLASSES, CONFIDENCE_CLASSES } from '../composables/useMercatoLabels.js'

const router = useRouter()

const FORCED_CHANNEL_ID = 'fabrizio-romano-italiano'

const tips = ref([])
const stats = ref([])
const loading = ref(false)
const error = ref(null)

// Filtri
const filterPlayer = ref('')
const filterOutcome = ref('')
const filterConfidence = ref('')

async function fetchTips() {
  loading.value = true
  error.value = null
  try {
    const params = new URLSearchParams()
    if (filterPlayer.value) params.set('player', filterPlayer.value)
    params.set('channel', FORCED_CHANNEL_ID)
    if (filterOutcome.value) params.set('outcome', filterOutcome.value)
    const res = await fetch(`/api/mercato/tips?${params}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    tips.value = await res.json()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    const res = await fetch('/api/mercato/channels/stats')
    if (res.ok) {
      const data = await res.json()
      stats.value = Array.isArray(data) ? data.filter(s => s.channel_id === FORCED_CHANNEL_ID) : []
    }
  } catch {}
}

const filteredTips = computed(() => {
  if (!filterConfidence.value) return tips.value
  return tips.value.filter(t => t.confidence === filterConfidence.value)
})

function goToPlayer(playerName) {
  const slug = playerName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  router.push({ name: 'mercato-player', params: { slug } })
}

async function setOutcome(tipId, outcome) {
  try {
    await fetch(`/api/mercato/tip/${tipId}/outcome`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ outcome }),
    })
    await fetchTips()
    await fetchStats()
  } catch (e) {
    alert('Errore aggiornamento: ' + e.message)
  }
}

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('it-IT', { day: '2-digit', month: 'short', year: 'numeric' })
}

onMounted(() => {
  fetchTips()
  fetchStats()
})
</script>

<template>
  <div class="mercato-view">
    <div class="mercato-header">
      <h2 class="mercato-title">Calciomercato</h2>
      <p class="mercato-subtitle">Tracking indiscrezioni e veridicità degli esperti</p>
    </div>

    <!-- Stats canali -->
    <div v-if="stats.length" class="stats-row">
      <div v-for="s in stats" :key="s.channel_id" class="stat-card">
        <div class="stat-channel">{{ s.channel_id }}</div>
        <div class="stat-numbers">
          <span class="stat-total">{{ s.total_tips }} tip</span>
          <span v-if="s.veracity_score !== null" class="stat-score">
            {{ Math.round(s.veracity_score * 100) }}% vere
          </span>
          <span v-else class="stat-score-na">nessun esito</span>
        </div>
      </div>
    </div>

    <!-- Filtri -->
    <div class="filters">
      <input
        v-model="filterPlayer"
        class="filter-input"
        placeholder="Cerca giocatore..."
        @input="fetchTips"
      />
      <select v-model="filterOutcome" class="filter-select" @change="fetchTips">
        <option value="">Tutti gli esiti</option>
        <option value="pending">In attesa</option>
        <option value="true">Vere</option>
        <option value="false">False</option>
        <option value="partial">Parziali</option>
      </select>
      <select v-model="filterConfidence" class="filter-select">
        <option value="">Tutte le confidenze</option>
        <option value="rumor">Voce</option>
        <option value="likely">Probabile</option>
        <option value="confirmed">Confermata</option>
        <option value="denied">Smentita</option>
      </select>
    </div>

    <div v-if="loading" class="loading">Caricamento...</div>
    <div v-else-if="error" class="error">Errore: {{ error }}</div>
    <div v-else-if="!filteredTips.length" class="empty">Nessuna indiscrezione trovata.</div>

    <!-- Lista tip -->
    <div v-else class="tips-list">
      <div v-for="tip in filteredTips" :key="tip.tip_id" class="tip-card">
        <div class="tip-header">
          <button class="player-link" @click="goToPlayer(tip.player_name)">
            {{ tip.player_name }}
          </button>
          <span :class="['badge', CONFIDENCE_CLASSES[tip.confidence]]">
            {{ CONFIDENCE_LABELS[tip.confidence] }}
          </span>
          <span :class="['badge', OUTCOME_CLASSES[tip.outcome]]">
            {{ OUTCOME_LABELS[tip.outcome] }}
          </span>
          <span v-if="tip.corroboration_score > 0" class="badge conf-corr">
            {{ tip.corroborated_by.length + 1 }} fonti
          </span>
        </div>

        <div class="tip-transfer">
          <span v-if="tip.from_club" class="club from">{{ tip.from_club }}</span>
          <span v-if="tip.from_club || tip.to_club" class="arrow">→</span>
          <span v-if="tip.to_club" class="club to">{{ tip.to_club }}</span>
          <span class="transfer-type">({{ tip.transfer_type }})</span>
        </div>

        <p class="tip-text">{{ tip.tip_text }}</p>
        <blockquote class="tip-quote">{{ tip.quote_text }}</blockquote>

        <div class="tip-footer">
          <span class="tip-meta">{{ tip.channel_id }} · {{ formatDate(tip.mentioned_at) }}</span>

          <!-- Bottoni outcome (solo se pending) -->
          <div v-if="tip.outcome === 'pending'" class="outcome-actions">
            <button class="btn-outcome btn-true" @click="setOutcome(tip.tip_id, 'true')">Vera</button>
            <button class="btn-outcome btn-partial" @click="setOutcome(tip.tip_id, 'partial')">Parziale</button>
            <button class="btn-outcome btn-false" @click="setOutcome(tip.tip_id, 'false')">Falsa</button>
          </div>
          <div v-else class="outcome-note">
            <span v-if="tip.outcome_notes" class="note-text">{{ tip.outcome_notes }}</span>
            <button class="btn-reset" @click="setOutcome(tip.tip_id, 'pending')">Reset</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mercato-view { max-width: 900px; margin: 0 auto; padding: 1.5rem 1rem; }
.mercato-header { margin-bottom: 1.5rem; }
.mercato-title { font-size: 1.6rem; font-weight: 700; margin: 0 0 .25rem; }
.mercato-subtitle { color: var(--color-text-muted, #888); margin: 0; font-size: .9rem; }

.stats-row { display: flex; gap: .75rem; flex-wrap: wrap; margin-bottom: 1.25rem; }
.stat-card {
  background: var(--color-surface, #f5f5f5);
  border-radius: 8px; padding: .6rem 1rem;
  min-width: 140px;
}
.stat-channel { font-weight: 600; font-size: .85rem; margin-bottom: .25rem; }
.stat-numbers { display: flex; gap: .5rem; font-size: .8rem; }
.stat-total { color: var(--color-text-muted, #888); }
.stat-score { color: #22a06b; font-weight: 600; }
.stat-score-na { color: var(--color-text-muted, #aaa); font-style: italic; }

.filters { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: 1.25rem; }
.filter-input, .filter-select {
  padding: .4rem .7rem; border-radius: 6px;
  border: 1px solid var(--color-border, #ddd);
  background: var(--color-bg, #fff);
  color: var(--color-text, #111);
  font-size: .875rem;
}
.filter-input { flex: 1; min-width: 180px; }

.loading, .empty { color: var(--color-text-muted, #888); padding: 2rem 0; text-align: center; }
.error { color: #e03e3e; padding: 1rem 0; }

.tips-list { display: flex; flex-direction: column; gap: .75rem; }
.tip-card {
  background: var(--color-surface, #f9f9f9);
  border: 1px solid var(--color-border, #e0e0e0);
  border-radius: 10px; padding: 1rem 1.1rem;
}
.tip-header { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; margin-bottom: .5rem; }
.player-link {
  font-weight: 700; font-size: 1rem; background: none; border: none;
  color: var(--color-accent, #0066cc); cursor: pointer; padding: 0;
  text-decoration: underline;
}
.badge {
  font-size: .72rem; font-weight: 600; padding: .18rem .5rem;
  border-radius: 4px; text-transform: uppercase; letter-spacing: .03em;
}
.conf-rumor    { background: #fff3cd; color: #856404; }
.conf-likely   { background: #cfe2ff; color: #084298; }
.conf-confirmed{ background: #d1e7dd; color: #0a3622; }
.conf-denied   { background: #f8d7da; color: #842029; }
.conf-corr     { background: #e0d7ff; color: #3a006f; }
.outcome-pending { background: #f0f0f0; color: #555; }
.outcome-true    { background: #d1e7dd; color: #0a3622; }
.outcome-false   { background: #f8d7da; color: #842029; }
.outcome-partial { background: #fff3cd; color: #856404; }

.tip-transfer { display: flex; align-items: center; gap: .4rem; margin-bottom: .4rem; font-size: .875rem; }
.club { font-weight: 600; }
.from { color: #e03e3e; }
.to   { color: #22a06b; }
.arrow { color: var(--color-text-muted, #aaa); }
.transfer-type { color: var(--color-text-muted, #aaa); font-size: .8rem; }

.tip-text { margin: 0 0 .4rem; font-size: .9rem; }
.tip-quote {
  margin: 0 0 .6rem; padding: .3rem .6rem;
  border-left: 3px solid var(--color-border, #ddd);
  font-style: italic; font-size: .82rem;
  color: var(--color-text-muted, #666);
}

.tip-footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: .5rem; }
.tip-meta { font-size: .78rem; color: var(--color-text-muted, #999); }
.outcome-actions { display: flex; gap: .35rem; }
.btn-outcome {
  font-size: .78rem; font-weight: 600; padding: .25rem .6rem;
  border: none; border-radius: 5px; cursor: pointer;
}
.btn-true    { background: #d1e7dd; color: #0a3622; }
.btn-partial { background: #fff3cd; color: #856404; }
.btn-false   { background: #f8d7da; color: #842029; }
.btn-true:hover    { background: #a3cfbb; }
.btn-partial:hover { background: #ffe69c; }
.btn-false:hover   { background: #f1aeb5; }
.outcome-note { display: flex; align-items: center; gap: .5rem; font-size: .8rem; }
.note-text { color: var(--color-text-muted, #666); font-style: italic; }
.btn-reset {
  font-size: .75rem; padding: .2rem .5rem; background: #f0f0f0;
  border: 1px solid #ccc; border-radius: 4px; cursor: pointer; color: #555;
}
</style>

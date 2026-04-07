<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { OUTCOME_LABELS, CONFIDENCE_LABELS, OUTCOME_CLASSES, CONFIDENCE_CLASSES } from '../composables/useMercatoLabels.js'

const route = useRoute()
const router = useRouter()
const player = ref(null)
const loading = ref(false)
const error = ref(null)

const FABRIZIO_CHANNEL_ID = 'fabrizio-romano-italiano'

const filteredTips = computed(() => {
  const tips = player.value?.tips ?? []
  return tips.filter((t) => t?.channel_id === FABRIZIO_CHANNEL_ID)
})

const filteredCounts = computed(() => {
  const tips = filteredTips.value
  const out = { total: tips.length, true: 0, false: 0, partial: 0, pending: 0 }
  for (const t of tips) {
    if (t?.outcome === 'true') out.true++
    else if (t?.outcome === 'false') out.false++
    else if (t?.outcome === 'partial') out.partial++
    else out.pending++
  }
  return out
})

async function fetchPlayer() {
  loading.value = true
  error.value = null
  try {
    const res = await fetch(`/api/mercato/players/${route.params.slug}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    player.value = await res.json()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function setOutcome(tipId, outcome) {
  try {
    await fetch(`/api/mercato/tip/${tipId}/outcome`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ outcome }),
    })
    await fetchPlayer()
  } catch (e) {
    alert('Errore: ' + e.message)
  }
}

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('it-IT', { day: '2-digit', month: 'short', year: 'numeric' })
}

onMounted(fetchPlayer)
</script>

<template>
  <div class="player-view">
    <button class="back-btn" @click="router.push({ name: 'mercato' })">← Mercato</button>

    <div v-if="loading" class="loading">Caricamento...</div>
    <div v-else-if="error" class="error">Errore: {{ error }}</div>

    <template v-else-if="player">
      <div class="player-header">
        <h2 class="player-name">{{ player.player_name }}</h2>
        <div class="player-stats">
          <span class="stat-pill">{{ filteredCounts.total }} tip</span>
          <span class="stat-pill outcome-true">{{ filteredCounts.true }} vere</span>
          <span class="stat-pill outcome-false">{{ filteredCounts.false }} false</span>
          <span class="stat-pill outcome-partial">{{ filteredCounts.partial }} parziali</span>
          <span class="stat-pill outcome-pending">{{ filteredCounts.pending }} in attesa</span>
        </div>
      </div>

      <div class="timeline">
        <div v-for="tip in filteredTips" :key="tip.tip_id" class="tip-card">
          <div class="tip-header">
            <span class="tip-date">{{ formatDate(tip.mentioned_at) }}</span>
            <span :class="['badge', CONFIDENCE_CLASSES[tip.confidence]]">
              {{ CONFIDENCE_LABELS[tip.confidence] }}
            </span>
            <span :class="['badge', OUTCOME_CLASSES[tip.outcome]]">
              {{ OUTCOME_LABELS[tip.outcome] }}
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

          <div v-if="tip.outcome === 'pending'" class="outcome-actions">
            <button class="btn-outcome btn-true"    @click="setOutcome(tip.tip_id, 'true')">Vera</button>
            <button class="btn-outcome btn-partial" @click="setOutcome(tip.tip_id, 'partial')">Parziale</button>
            <button class="btn-outcome btn-false"   @click="setOutcome(tip.tip_id, 'false')">Falsa</button>
          </div>
          <div v-else class="outcome-done">
            <span v-if="tip.outcome_notes" class="note-text">{{ tip.outcome_notes }}</span>
            <button class="btn-reset" @click="setOutcome(tip.tip_id, 'pending')">Reset</button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.player-view { max-width: 800px; margin: 0 auto; padding: 1.5rem 1rem; }
.back-btn {
  background: none; border: none; color: var(--color-accent, #0066cc);
  cursor: pointer; font-size: .875rem; padding: 0; margin-bottom: 1.25rem;
  text-decoration: underline;
}
.loading, .error { padding: 2rem 0; text-align: center; color: var(--color-text-muted, #888); }
.error { color: #e03e3e; }

.player-header { margin-bottom: 1.5rem; }
.player-name { font-size: 1.8rem; font-weight: 700; margin: 0 0 .6rem; }
.player-stats { display: flex; gap: .4rem; flex-wrap: wrap; margin-bottom: .5rem; }
.stat-pill {
  font-size: .78rem; font-weight: 600; padding: .2rem .6rem;
  border-radius: 12px; background: #f0f0f0; color: #555;
}
.player-channels { display: flex; gap: .4rem; flex-wrap: wrap; }
.channel-tag {
  font-size: .78rem; background: var(--color-surface, #f5f5f5);
  border-radius: 4px; padding: .15rem .5rem; color: var(--color-text-muted, #666);
}

.timeline { display: flex; flex-direction: column; gap: .75rem; }
.tip-card {
  background: var(--color-surface, #f9f9f9);
  border: 1px solid var(--color-border, #e0e0e0);
  border-radius: 10px; padding: 1rem 1.1rem;
}
.tip-header { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; margin-bottom: .5rem; }
.tip-date { font-size: .82rem; color: var(--color-text-muted, #888); }
.tip-channel { font-size: .78rem; color: var(--color-text-muted, #aaa); margin-left: auto; }

.badge {
  font-size: .72rem; font-weight: 600; padding: .18rem .5rem;
  border-radius: 4px; text-transform: uppercase; letter-spacing: .03em;
}
.conf-rumor    { background: #fff3cd; color: #856404; }
.conf-likely   { background: #cfe2ff; color: #084298; }
.conf-confirmed{ background: #d1e7dd; color: #0a3622; }
.conf-denied   { background: #f8d7da; color: #842029; }
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
.outcome-done { display: flex; align-items: center; gap: .5rem; font-size: .8rem; }
.note-text { color: var(--color-text-muted, #666); font-style: italic; }
.btn-reset {
  font-size: .75rem; padding: .2rem .5rem; background: #f0f0f0;
  border: 1px solid #ccc; border-radius: 4px; cursor: pointer; color: #555;
}
</style>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { OUTCOME_LABELS, OUTCOME_SOURCE_LABELS, CONFIDENCE_LABELS, OUTCOME_CLASSES, CONFIDENCE_CLASSES } from '../composables/useMercatoLabels.js'

const expandedTips = ref(new Set())
function toggleRelated(tipId) {
  if (expandedTips.value.has(tipId)) {
    expandedTips.value.delete(tipId)
  } else {
    expandedTips.value.add(tipId)
  }
  expandedTips.value = new Set(expandedTips.value)
}

const manualOverrideTips = ref(new Set())
function toggleManualOverride(tipId) {
  if (manualOverrideTips.value.has(tipId)) {
    manualOverrideTips.value.delete(tipId)
  } else {
    manualOverrideTips.value.add(tipId)
  }
  manualOverrideTips.value = new Set(manualOverrideTips.value)
}

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
  const out = { total: tips.length, confermata: 0, smentita: 0, parziale: 0, non_verificata: 0 }
  for (const t of tips) {
    if (t?.outcome === 'confermata') out.confermata++
    else if (t?.outcome === 'smentita') out.smentita++
    else if (t?.outcome === 'parziale') out.parziale++
    else out.non_verificata++
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

async function verifyTip(tipId) {
  try {
    await fetch(`/api/mercato/tip/${tipId}/verify`, { method: 'POST' })
    await fetchPlayer()
  } catch (e) {
    alert('Errore verifica: ' + e.message)
  }
}

async function setOutcome(tipId, outcome) {
  try {
    await fetch(`/api/mercato/tip/${tipId}/outcome`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ outcome, source: 'manual' }),
    })
    await fetchPlayer()
  } catch (e) {
    alert('Errore: ' + e.message)
  }
}

function formatDate(iso) {
  if (!iso) return 'Senza data'
  return new Date(iso).toLocaleDateString('it-IT', { day: '2-digit', month: 'short', year: 'numeric' })
}

// Editing della data di una tip senza data
const dateEditingTip = ref(null)
const dateEditValue = ref('')

function startDateEdit(tipId) {
  dateEditingTip.value = tipId
  dateEditValue.value = new Date().toISOString().slice(0, 10)
}

function cancelDateEdit() {
  dateEditingTip.value = null
  dateEditValue.value = ''
}

async function submitDateEdit(tipId) {
  if (!dateEditValue.value) return
  try {
    const res = await fetch(`/api/mercato/tip/${tipId}/date`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: dateEditValue.value }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    cancelDateEdit()
    await fetchPlayer()
  } catch (e) {
    alert('Errore impostazione data: ' + e.message)
  }
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
          <span class="stat-pill outcome-true">{{ filteredCounts.confermata }} confermate</span>
          <span class="stat-pill outcome-false">{{ filteredCounts.smentita }} smentite</span>
          <span class="stat-pill outcome-partial">{{ filteredCounts.parziale }} parziali</span>
          <span class="stat-pill outcome-pending">{{ filteredCounts.non_verificata }} non verificate</span>
        </div>
      </div>

      <div class="timeline">
        <div v-for="tip in filteredTips" :key="tip.tip_id" class="tip-card">
          <div class="tip-header">
            <template v-if="!tip.mentioned_at">
              <template v-if="dateEditingTip === tip.tip_id">
                <input type="date" v-model="dateEditValue" class="date-input-inline" />
                <button class="btn-date-ok" @click="submitDateEdit(tip.tip_id)">✓</button>
                <button class="btn-date-cancel" @click="cancelDateEdit">✗</button>
              </template>
              <span v-else class="tip-no-date" @click="startDateEdit(tip.tip_id)" title="Clicca per aggiungere la data">Senza data</span>
            </template>
            <span v-else class="tip-date">{{ formatDate(tip.mentioned_at) }}</span>
            <span :class="['badge', CONFIDENCE_CLASSES[tip.confidence]]">
              {{ CONFIDENCE_LABELS[tip.confidence] }}
            </span>
            <span :class="['badge', OUTCOME_CLASSES[tip.outcome]]">
              {{ OUTCOME_LABELS[tip.outcome] }}
              <span v-if="tip.outcome !== 'non_verificata' && tip.outcome_source" class="outcome-source">[{{ OUTCOME_SOURCE_LABELS[tip.outcome_source] ?? tip.outcome_source }}]</span>
            </span>
            <span v-if="tip.same_channel_consistent?.length" class="badge badge-same-ok" title="Stesso canale, stessa direzione in altri video">
              ↔ {{ tip.same_channel_consistent.length }} coerenti
            </span>
            <span v-if="tip.same_channel_inconsistent?.length" class="badge badge-same-ko" title="Stesso canale, direzione diversa in altri video">
              ⚠ {{ tip.same_channel_inconsistent.length }} incoerenti
            </span>
            <span v-if="tip.other_channel_confirming?.length" class="badge badge-corr" title="Altri canali confermano">
              ✓ {{ tip.other_channel_confirming.length }} conferme
            </span>
            <span v-if="tip.other_channel_contradicting?.length" class="badge badge-contr" title="Altri canali smentiscono">
              ✗ {{ tip.other_channel_contradicting.length }} smentite
            </span>
          </div>

          <div class="tip-transfer">
            <span v-if="tip.from_club" class="club from">{{ tip.from_club }}</span>
            <span v-if="tip.from_club || tip.to_club" class="arrow">→</span>
            <span v-if="tip.to_club" class="club to">{{ tip.to_club }}</span>
            <span class="transfer-type">({{ tip.transfer_type }})</span>
          </div>

          <p class="tip-text">{{ tip.tip_text }}</p>

          <!-- Sezione fonti correlate -->
          <div v-if="tip.same_channel_consistent?.length || tip.same_channel_inconsistent?.length || tip.other_channel_confirming?.length || tip.other_channel_contradicting?.length" class="related-section">
            <button class="toggle-related" @click="toggleRelated(tip.tip_id)">
              {{ expandedTips.has(tip.tip_id) ? '▲' : '▼' }} Cronologia correlate
              <span v-if="tip.same_channel_inconsistent?.length" class="rel-count same-ko-count">⚠ {{ tip.same_channel_inconsistent.length }} incoerenti</span>
              <span v-if="tip.same_channel_consistent?.length" class="rel-count same-ok-count">↔ {{ tip.same_channel_consistent.length }} coerenti</span>
              <span v-if="tip.other_channel_contradicting?.length" class="rel-count contr-count">✗ {{ tip.other_channel_contradicting.length }} smentite</span>
              <span v-if="tip.other_channel_confirming?.length" class="rel-count corr-count">✓ {{ tip.other_channel_confirming.length }} conferme</span>
            </button>
            <div v-if="expandedTips.has(tip.tip_id)" class="related-tips">
              <template v-if="tip.same_channel_inconsistent?.length">
                <div class="rel-section-label label-incoherent">⚠ Incoerente con lo stesso canale</div>
                <div v-for="rt in tip.same_channel_inconsistent" :key="rt.tip_id" class="related-tip related-same-ko">
                  <div class="rel-header">
                    <span class="rel-channel">{{ rt.channel_id }}</span>
                    <span class="rel-date">{{ formatDate(rt.mentioned_at) }}</span>
                    <span v-if="rt.to_club" class="rel-club contr-club">→ {{ rt.to_club }}</span>
                    <span :class="['badge', OUTCOME_CLASSES[rt.outcome]]" style="font-size:.65rem">{{ OUTCOME_LABELS[rt.outcome] }}</span>
                  </div>
                  <p class="rel-text">{{ rt.tip_text }}</p>
                </div>
              </template>
              <template v-if="tip.same_channel_consistent?.length">
                <div class="rel-section-label label-coherent">↔ Coerente con lo stesso canale</div>
                <div v-for="rt in tip.same_channel_consistent" :key="rt.tip_id" class="related-tip related-same-ok">
                  <div class="rel-header">
                    <span class="rel-channel">{{ rt.channel_id }}</span>
                    <span class="rel-date">{{ formatDate(rt.mentioned_at) }}</span>
                    <span v-if="rt.to_club" class="rel-club">→ {{ rt.to_club }}</span>
                    <span :class="['badge', OUTCOME_CLASSES[rt.outcome]]" style="font-size:.65rem">{{ OUTCOME_LABELS[rt.outcome] }}</span>
                  </div>
                  <p class="rel-text">{{ rt.tip_text }}</p>
                </div>
              </template>
              <template v-if="tip.other_channel_contradicting?.length">
                <div class="rel-section-label label-smentita">✗ Smentite da altri canali</div>
                <div v-for="rt in tip.other_channel_contradicting" :key="rt.tip_id" class="related-tip related-contr">
                  <div class="rel-header">
                    <span class="rel-channel">{{ rt.channel_id }}</span>
                    <span class="rel-date">{{ formatDate(rt.mentioned_at) }}</span>
                    <span v-if="rt.to_club" class="rel-club contr-club">→ {{ rt.to_club }}</span>
                    <span :class="['badge', OUTCOME_CLASSES[rt.outcome]]" style="font-size:.65rem">{{ OUTCOME_LABELS[rt.outcome] }}</span>
                  </div>
                  <p class="rel-text">{{ rt.tip_text }}</p>
                </div>
              </template>
              <template v-if="tip.other_channel_confirming?.length">
                <div class="rel-section-label label-conferma">✓ Confermate da altri canali</div>
                <div v-for="rt in tip.other_channel_confirming" :key="rt.tip_id" class="related-tip related-corr">
                  <div class="rel-header">
                    <span class="rel-channel">{{ rt.channel_id }}</span>
                    <span class="rel-date">{{ formatDate(rt.mentioned_at) }}</span>
                    <span v-if="rt.to_club" class="rel-club">→ {{ rt.to_club }}</span>
                    <span :class="['badge', OUTCOME_CLASSES[rt.outcome]]" style="font-size:.65rem">{{ OUTCOME_LABELS[rt.outcome] }}</span>
                  </div>
                  <p class="rel-text">{{ rt.tip_text }}</p>
                </div>
              </template>
            </div>
          </div>

          <div class="outcome-actions">
            <button v-if="tip.outcome === 'non_verificata'" class="btn-outcome btn-verify" @click="verifyTip(tip.tip_id)">
              ⟳ Verifica
            </button>
            <button class="btn-manual-toggle" @click="toggleManualOverride(tip.tip_id)">
              {{ manualOverrideTips.has(tip.tip_id) ? '▲' : '▼' }} Override manuale
            </button>
            <template v-if="manualOverrideTips.has(tip.tip_id)">
              <button class="btn-outcome btn-true"    @click="setOutcome(tip.tip_id, 'confermata')">Confermata</button>
              <button class="btn-outcome btn-partial" @click="setOutcome(tip.tip_id, 'parziale')">Parziale</button>
              <button class="btn-outcome btn-false"   @click="setOutcome(tip.tip_id, 'smentita')">Smentita</button>
              <button class="btn-outcome btn-reset"   @click="setOutcome(tip.tip_id, 'non_verificata')">Non verif.</button>
            </template>
          </div>
          <div v-if="tip.outcome_notes" class="outcome-note-row">
            <span class="note-text">{{ tip.outcome_notes }}</span>
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
  color: var(--color-text, #111);
}
.tip-header { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; margin-bottom: .5rem; }
.tip-date { font-size: .82rem; color: var(--color-text-muted, #888); }
.tip-no-date { font-size: .82rem; color: #e07b00; cursor: pointer; border-bottom: 1px dashed #e07b00; }
.tip-no-date:hover { color: #c06000; }
.date-input-inline { font-size: .8rem; padding: .1rem .3rem; border: 1px solid #ccc; border-radius: 4px; }
.btn-date-ok { font-size: .8rem; padding: .1rem .4rem; background: #2a9d2a; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
.btn-date-cancel { font-size: .8rem; padding: .1rem .4rem; background: #999; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
.tip-channel { font-size: .78rem; color: var(--color-text-muted, #aaa); margin-left: auto; }

.badge {
  font-size: .72rem; font-weight: 600; padding: .18rem .5rem;
  border-radius: 4px; text-transform: uppercase; letter-spacing: .03em;
}
.conf-rumor    { background: #fff3cd; color: #856404; }
.conf-likely   { background: #cfe2ff; color: #084298; }
.conf-confirmed{ background: #d1e7dd; color: #0a3622; }
.conf-denied   { background: #f8d7da; color: #842029; }
.badge-same-ok { background: #e0f2fe; color: #0369a1; }
.badge-same-ko { background: #fef9c3; color: #854d0e; }
.badge-corr    { background: #d1fae5; color: #065f46; }
.badge-contr   { background: #fee2e2; color: #991b1b; }
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

.tip-text {
  margin: 0 0 .4rem;
  font-size: .9rem;
  color: var(--color-text, var(--text-secondary));
}
.tip-quote {
  margin: 0 0 .6rem; padding: .3rem .6rem;
  border-left: 3px solid var(--color-border, #ddd);
  font-style: italic; font-size: .82rem;
  color: var(--color-text-muted, #666);
}

.outcome-source { font-size: .65rem; opacity: .7; margin-left: .2rem; }
.outcome-actions { display: flex; gap: .35rem; align-items: center; flex-wrap: wrap; }
.btn-verify {
  background: #0066cc; color: #fff; border: none; border-radius: 5px;
  font-size: .78rem; font-weight: 600; padding: .25rem .6rem; cursor: pointer;
}
.btn-verify:hover { background: #0052a3; }
.btn-manual-toggle {
  background: none; border: 1px solid var(--color-border, #ddd); border-radius: 5px;
  font-size: .72rem; color: var(--color-text-muted, #888); padding: .2rem .45rem; cursor: pointer;
}
.btn-manual-toggle:hover { color: var(--color-text, #111); }
.btn-outcome {
  font-size: .78rem; font-weight: 600; padding: .25rem .6rem;
  border: none; border-radius: 5px; cursor: pointer;
}
.btn-true    { background: #d1e7dd; color: #0a3622; }
.btn-partial { background: #fff3cd; color: #856404; }
.btn-false   { background: #f8d7da; color: #842029; }
.btn-reset   { background: #f0f0f0; color: #555; }
.btn-true:hover    { background: #a3cfbb; }
.btn-partial:hover { background: #ffe69c; }
.btn-false:hover   { background: #f1aeb5; }
.btn-reset:hover   { background: #e0e0e0; }
.outcome-note-row { margin-top: .25rem; font-size: .8rem; }
.note-text { color: var(--color-text-muted, #666); font-style: italic; }

/* Fonti correlate */
.related-section { margin: .5rem 0 .25rem; }
.toggle-related {
  background: none; border: none; cursor: pointer;
  font-size: .78rem; color: var(--color-text-muted, #666);
  padding: 0; display: flex; align-items: center; gap: .35rem;
}
.toggle-related:hover { color: var(--color-text, #111); }
.rel-count { font-weight: 600; font-size: .72rem; padding: .1rem .35rem; border-radius: 3px; }
.same-ok-count { background: #e0f2fe; color: #0369a1; }
.same-ko-count { background: #fef9c3; color: #854d0e; }
.corr-count    { background: #d1fae5; color: #065f46; }
.contr-count   { background: #fee2e2; color: #991b1b; }

.related-tips { margin-top: .4rem; display: flex; flex-direction: column; gap: .25rem; }
.rel-section-label {
  font-size: .72rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .04em; padding: .2rem 0 .1rem; margin-top: .3rem;
}
.label-incoherent { color: #854d0e; }
.label-coherent   { color: #0369a1; }
.label-smentita   { color: #991b1b; }
.label-conferma   { color: #065f46; }

.related-tip { border-radius: 6px; padding: .4rem .6rem; font-size: .82rem; }
.related-same-ok { border-left: 3px solid #38bdf8; }
.related-same-ko { border-left: 3px solid #facc15; }
.related-corr    { border-left: 3px solid #22c55e; }
.related-contr   { border-left: 3px solid #ef4444; }

.rel-header { display: flex; align-items: center; gap: .35rem; flex-wrap: wrap; margin-bottom: .2rem; }
.rel-channel { font-weight: 600; font-size: .75rem; color: var(--color-text-muted, #666); }
.rel-date { font-size: .72rem; color: var(--color-text-muted, #aaa); }
.rel-club { font-size: .78rem; font-weight: 600; }
.contr-club { color: #dc2626; }
.rel-text { margin: 0; color: var(--color-text, #222); }
</style>

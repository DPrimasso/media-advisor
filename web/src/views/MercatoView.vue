<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { OUTCOME_LABELS, OUTCOME_SOURCE_LABELS, CONFIDENCE_LABELS, CONFIDENCE_CHIP, OUTCOME_CHIP } from '../composables/useMercatoLabels.js'

const expandedTips = ref(new Set())
function toggleRelated(tipId) {
  if (expandedTips.value.has(tipId)) {
    expandedTips.value.delete(tipId)
  } else {
    expandedTips.value.add(tipId)
  }
  expandedTips.value = new Set(expandedTips.value)
}

// Override manuale collassabile
const manualOverrideTips = ref(new Set())
function toggleManualOverride(tipId) {
  if (manualOverrideTips.value.has(tipId)) {
    manualOverrideTips.value.delete(tipId)
  } else {
    manualOverrideTips.value.add(tipId)
  }
  manualOverrideTips.value = new Set(manualOverrideTips.value)
}

const router = useRouter()

const tips = ref([])
const stats = ref([])
const transfers = ref([])
const loading = ref(false)
const verifying = ref(false)
const error = ref(null)
const showTransfers = ref(false)

// Filtri
const filterPlayer = ref('')
const filterChannel = ref('')
const filterOutcome = ref('')
const filterConfidence = ref('')
const filterSeason = ref('')
const seasons = ref([])

function channelLabel(id) {
  return id.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

let _playerDebounceTimer = null
function onPlayerInput() {
  clearTimeout(_playerDebounceTimer)
  _playerDebounceTimer = setTimeout(fetchTips, 300)
}

// Form nuovo trasferimento
const newTransfer = ref({ player_name: '', to_club: '', from_club: '', transfer_type: 'unknown', season: '', confirmed_at: '', source_url: '' })
const addingTransfer = ref(false)

// Fetch TM
const fetchPlayer = ref('')
const fetchSeason = ref('')
const fetchingTM = ref(false)
const fetchResult = ref(null)

const rosterState = ref({ status: 'idle', log: [], result: null, error: null })
const rosterLeagues = ref('IT1,GB1,ES1,L1,FR1')
let _rosterPollTimer = null

async function startFetchRosters() {
  if (rosterState.value.status === 'running') return
  rosterState.value = { status: 'running', log: [], result: null, error: null }
  try {
    const res = await fetch('/api/mercato/fetch-rosters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ leagues: rosterLeagues.value }),
    })
    if (!res.ok) {
      const data = await res.json()
      rosterState.value = { status: 'error', log: [], result: null, error: data.detail || `HTTP ${res.status}` }
      return
    }
  } catch (e) {
    rosterState.value = { status: 'error', log: [], result: null, error: e.message }
    return
  }
  _rosterPollTimer = setInterval(async () => {
    try {
      const res = await fetch('/api/mercato/fetch-rosters/status')
      if (res.ok) {
        const data = await res.json()
        rosterState.value = data
        if (data.status !== 'running') {
          clearInterval(_rosterPollTimer)
          _rosterPollTimer = null
        }
      }
    } catch { /* ignore */ }
  }, 2000)
}

async function fetchTips() {
  loading.value = true
  error.value = null
  try {
    const params = new URLSearchParams()
    if (filterPlayer.value) params.set('player', filterPlayer.value)
    if (filterChannel.value) params.set('channel', filterChannel.value)
    if (filterOutcome.value) params.set('outcome', filterOutcome.value)
    if (filterSeason.value) params.set('season', filterSeason.value)
    const res = await fetch(`/api/mercato/tips?${params}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    tips.value = Array.isArray(data) ? data : []
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
      stats.value = Array.isArray(data) ? data : []
    }
  } catch {}
}

async function fetchTransfers() {
  try {
    const res = await fetch('/api/mercato/transfers')
    if (res.ok) {
      const data = await res.json()
      transfers.value = Array.isArray(data) ? data : []
    }
  } catch {}
}

const filteredTips = computed(() => {
  const list = Array.isArray(tips.value) ? tips.value : []
  if (!filterConfidence.value) return list
  return list.filter((t) => t.confidence === filterConfidence.value)
})

function goToPlayer(playerName) {
  const slug = playerName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  router.push({ name: 'mercato-player', params: { slug } })
}

async function verifyTip(tipId) {
  try {
    await fetch(`/api/mercato/tip/${tipId}/verify`, { method: 'POST' })
    await Promise.all([fetchTips(), fetchStats()])
  } catch (e) {
    alert('Errore verifica: ' + e.message)
  }
}

async function verifyAll() {
  verifying.value = true
  try {
    await fetch('/api/mercato/verify', { method: 'POST' })
    await Promise.all([fetchTips(), fetchStats()])
  } catch (e) {
    alert('Errore verifica: ' + e.message)
  } finally {
    verifying.value = false
  }
}

async function setOutcome(tipId, outcome) {
  let notes = null
  if (outcome === 'non_conclusa') {
    notes = prompt('Motivo per cui la trattativa non si è conclusa (obbligatorio):')
    if (!notes || !notes.trim()) return
    notes = notes.trim()
  }
  try {
    await fetch(`/api/mercato/tip/${tipId}/outcome`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ outcome, source: 'manual', notes }),
    })
    await Promise.all([fetchTips(), fetchStats()])
  } catch (e) {
    alert('Errore aggiornamento: ' + e.message)
  }
}

async function addTransfer() {
  if (!newTransfer.value.player_name || !newTransfer.value.to_club || !newTransfer.value.confirmed_at || !newTransfer.value.season) {
    alert('Compila almeno: giocatore, club destinazione, stagione e data.')
    return
  }
  addingTransfer.value = true
  try {
    const res = await fetch('/api/mercato/transfers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newTransfer.value),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    newTransfer.value = { player_name: '', to_club: '', from_club: '', transfer_type: 'unknown', season: '', confirmed_at: '', source_url: '' }
    await Promise.all([fetchTransfers(), fetchTips(), fetchStats()])
  } catch (e) {
    alert('Errore aggiunta trasferimento: ' + e.message)
  } finally {
    addingTransfer.value = false
  }
}

async function deleteTransfer(transferId) {
  if (!confirm('Rimuovere questo trasferimento?')) return
  try {
    await fetch(`/api/mercato/transfers/${transferId}`, { method: 'DELETE' })
    await fetchTransfers()
  } catch (e) {
    alert('Errore rimozione: ' + e.message)
  }
}

async function fetchFromTM() {
  if (!fetchPlayer.value) return
  fetchingTM.value = true
  fetchResult.value = null
  try {
    const res = await fetch('/api/mercato/transfers/fetch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ player_name: fetchPlayer.value, season: fetchSeason.value || null }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
    fetchResult.value = data
    await Promise.all([fetchTransfers(), fetchTips(), fetchStats()])
  } catch (e) {
    fetchResult.value = { error: e.message }
  } finally {
    fetchingTM.value = false
  }
}

function formatDate(iso) {
  if (!iso) return 'Senza data'
  return new Date(iso).toLocaleDateString('it-IT', { day: '2-digit', month: 'short', year: 'numeric' })
}

function pad2(n) {
  return String(n).padStart(2, '0')
}

function formatTime(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return null
  const s = Math.max(0, Math.floor(Number(seconds)))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  return h > 0 ? `${h}:${pad2(m)}:${pad2(ss)}` : `${m}:${pad2(ss)}`
}

function tipVideoUrl(tip) {
  if (!tip?.video_id) return null
  const t = tip?.quote_start_sec != null ? Math.max(0, Math.floor(Number(tip.quote_start_sec))) : null
  const base = `https://www.youtube.com/watch?v=${encodeURIComponent(tip.video_id)}`
  return t != null ? `${base}&t=${t}s` : base
}

// Mapping nomi
const aliasModal = ref({ show: false, alias: '', canonical: '', saving: false, error: null })

function openAliasModal(playerName) {
  aliasModal.value = { show: true, alias: playerName, canonical: '', saving: false, error: null }
}

function closeAliasModal() {
  aliasModal.value.show = false
}

async function submitAlias() {
  const m = aliasModal.value
  if (!m.alias || !m.canonical.trim()) return
  m.saving = true
  m.error = null
  try {
    const res = await fetch('/api/mercato/aliases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alias: m.alias, canonical: m.canonical.trim() }),
    })
    if (!res.ok) {
      const data = await res.json()
      throw new Error(data.detail || `HTTP ${res.status}`)
    }
    closeAliasModal()
    await fetchTips()
  } catch (e) {
    m.error = e.message
  } finally {
    m.saving = false
  }
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
    await fetchTips()
  } catch (e) {
    alert('Errore impostazione data: ' + e.message)
  }
}

async function fetchSeasons() {
  try {
    const res = await fetch('/api/mercato/seasons')
    if (res.ok) seasons.value = await res.json()
  } catch { /* ignore */ }
}

onMounted(() => Promise.all([fetchTips(), fetchStats(), fetchTransfers(), fetchSeasons()]))
onUnmounted(() => { if (_rosterPollTimer) clearInterval(_rosterPollTimer) })
</script>

<template>
  <div class="page page--wide">

    <!-- Header -->
    <div class="masthead">
      <div style="flex:1">
        <h1 class="masthead-title">Calciomercato</h1>
        <div class="masthead-date">Tracking indiscrezioni — verifica automatica via Transfermarkt</div>
      </div>
      <div class="masthead-actions">
        <button class="btn btn-secondary btn-sm" :disabled="verifying" @click="verifyAll">
          {{ verifying ? 'Verificando...' : '⟳ Verifica tutte' }}
        </button>
        <button class="btn btn-ghost btn-sm" @click="showTransfers = !showTransfers">
          {{ showTransfers ? '▲' : '▼' }} Trasferimenti ({{ transfers.length }})
        </button>
      </div>
    </div>

    <!-- Trasferimenti ufficiali -->
    <div v-if="showTransfers" class="tf-panel">
      <div class="tf-panel-head">
        <span class="sec-label">Trasferimenti ufficiali</span>
      </div>
      <div class="tf-body">

      <!-- Fetch da TM -->
      <div class="tm-fetch-row">
        <input v-model="fetchPlayer" class="fi" placeholder="Nome giocatore..." style="max-width:200px" />
        <input v-model="fetchSeason" class="fi" placeholder="Stagione (es. 2025)" style="max-width:140px" />
        <button class="btn btn-secondary btn-sm" :disabled="fetchingTM || !fetchPlayer" @click="fetchFromTM">
          {{ fetchingTM ? 'Scaricando...' : '↓ Fetch da Transfermarkt' }}
        </button>
        <span v-if="fetchResult && !fetchResult.error" class="fetch-ok">✓ {{ fetchResult.added }} aggiunto/i</span>
        <span v-if="fetchResult?.error" class="fetch-err">✗ {{ fetchResult.error }}</span>
      </div>

      <!-- Aggiornamento rose squadre -->
      <div class="roster-fetch-row">
        <span class="sec-label" style="white-space:nowrap">Rose squadre</span>
        <input v-model="rosterLeagues" class="fi" placeholder="IT1,GB1,ES1,L1,FR1" style="max-width:220px" :disabled="rosterState.status === 'running'" />
        <button class="btn btn-secondary btn-sm" :disabled="rosterState.status === 'running'" @click="startFetchRosters">
          {{ rosterState.status === 'running' ? '⟳ Scaricando...' : '↓ Aggiorna rosa' }}
        </button>
        <span v-if="rosterState.status === 'done' && rosterState.result" class="fetch-ok">
          ✓ {{ rosterState.result.players }} giocatori ({{ rosterState.result.leagues.join(', ') }})
        </span>
        <span v-if="rosterState.status === 'error'" class="fetch-err">✗ {{ rosterState.error }}</span>
      </div>
      <div v-if="rosterState.status === 'running' && rosterState.log.length" class="roster-log">
        <span v-for="(line, i) in rosterState.log.slice(-6)" :key="i" class="roster-log-line">{{ line }}</span>
      </div>

      <!-- Form aggiunta manuale -->
      <details class="add-transfer-details">
        <summary>+ Aggiungi trasferimento manuale</summary>
        <div class="add-transfer-form">
          <input v-model="newTransfer.player_name" class="fi" placeholder="Giocatore *" />
          <input v-model="newTransfer.from_club" class="fi" placeholder="Da club" />
          <input v-model="newTransfer.to_club" class="fi" placeholder="A club *" />
          <select v-model="newTransfer.transfer_type" class="fi">
            <option value="unknown">Tipo</option>
            <option value="permanent">Permanente</option>
            <option value="loan">Prestito</option>
            <option value="free_agent">Svincolato</option>
            <option value="extension">Rinnovo</option>
          </select>
          <input v-model="newTransfer.season" class="fi" placeholder="Stagione * (es. 2025-26)" />
          <input v-model="newTransfer.confirmed_at" class="fi" type="date" placeholder="Data *" />
          <input v-model="newTransfer.source_url" class="fi" placeholder="URL Transfermarkt" />
          <button class="btn btn-primary btn-sm" :disabled="addingTransfer" @click="addTransfer">
            {{ addingTransfer ? '...' : 'Aggiungi' }}
          </button>
        </div>
      </details>

      <!-- Lista trasferimenti -->
      <div v-if="transfers.length" class="tf-list">
        <div v-for="tr in transfers" :key="tr.transfer_id" class="tf-row">
          <span class="tf-player">{{ tr.player_name }}</span>
          <span v-if="tr.from_club" class="tf-from">{{ tr.from_club }}</span>
          <span v-if="tr.from_club || tr.to_club" class="tf-arr">→</span>
          <span v-if="tr.to_club" class="tf-to">{{ tr.to_club }}</span>
          <span class="tf-meta">{{ tr.transfer_type }}</span>
          <span class="tf-meta">{{ tr.season }}</span>
          <span class="tf-meta">{{ formatDate(tr.confirmed_at) }}</span>
          <span class="tf-meta">{{ tr.source }}</span>
          <a v-if="tr.source_url" :href="tr.source_url" target="_blank" class="tf-link">TM ↗</a>
          <button class="tf-del" @click="deleteTransfer(tr.transfer_id)" title="Rimuovi">✕</button>
        </div>
      </div>
      <p v-else class="empty">Nessun trasferimento nel database.</p>
      </div><!-- /tf-body -->
    </div>

    <!-- Stats canali -->
    <div v-if="stats.length" class="stats-bar">
      <div v-for="s in stats" :key="s.channel_id" class="stat-card">
        <div class="stat-name">{{ s.channel_id }}</div>
        <div class="stat-numbers">
          <span class="stat-val">{{ s.total_tips }}</span><span class="stat-unit"> tip</span>
          <span v-if="s.veracity_score !== null" class="stat-score">
            · {{ Math.round(s.veracity_score * 100) }}% vere
          </span>
          <span v-else class="stat-score-na"> · nessun esito</span>
        </div>
      </div>
    </div>

    <!-- Filtri -->
    <div class="filter-bar">
      <input
        v-model="filterPlayer"
        class="fi"
        placeholder="Cerca giocatore..."
        @input="onPlayerInput"
      />
      <select v-model="filterChannel" class="fi" @change="fetchTips">
        <option value="">Tutti i canali</option>
        <option v-for="s in stats" :key="s.channel_id" :value="s.channel_id">
          {{ channelLabel(s.channel_id) }}
        </option>
      </select>
      <select v-model="filterOutcome" class="fi" @change="fetchTips">
        <option value="">Tutti gli esiti</option>
        <option value="non_verificata">Non verificate</option>
        <option value="confermata">Confermate</option>
        <option value="parziale">Parziali</option>
        <option value="smentita">Smentite</option>
        <option value="non_conclusa">Non concluse</option>
      </select>
      <select v-model="filterSeason" class="fi" @change="fetchTips">
        <option value="">Tutte le sessioni</option>
        <option v-for="s in seasons" :key="s.id" :value="s.id">{{ s.label }}</option>
      </select>
      <select v-model="filterConfidence" class="fi">
        <option value="">Tutte le confidenze</option>
        <option value="rumor">Voce</option>
        <option value="likely">Probabile</option>
        <option value="confirmed">Confermata</option>
        <option value="denied">Smentita</option>
      </select>
    </div>

    <div v-if="loading" class="loading-wrap"><span class="spinner"></span></div>
    <div v-else-if="error" class="empty" style="color:var(--re)">Errore: {{ error }}</div>
    <div v-else-if="!filteredTips.length" class="empty">Nessuna indiscrezione trovata.</div>

    <!-- Lista tip -->
    <div v-else style="display:flex;flex-direction:column;gap:10px">
      <div v-for="tip in filteredTips" :key="tip.tip_id" class="tip-card">

        <div class="tip-head">
          <button class="tip-name" @click="goToPlayer(tip.player_name)">
            {{ tip.player_name }}
          </button>
          <button class="btn btn-ghost btn-xs" @click="openAliasModal(tip.player_name)" title="Mappa nome sbagliato">
            Mappa nome
          </button>
          <span :class="['chip', CONFIDENCE_CHIP[tip.confidence]]">
            {{ CONFIDENCE_LABELS[tip.confidence] }}
          </span>
          <span :class="['chip', OUTCOME_CHIP[tip.outcome]]">
            {{ OUTCOME_LABELS[tip.outcome] }}
            <span v-if="tip.outcome !== 'non_verificata' && tip.outcome_source" class="outcome-source">
              [{{ OUTCOME_SOURCE_LABELS[tip.outcome_source] ?? tip.outcome_source }}]
            </span>
          </span>
          <span v-if="tip.same_channel_consistent?.length" class="chip chip--blue" title="Stesso canale, stessa direzione in altri video">
            ↔ {{ tip.same_channel_consistent.length }} coerenti
          </span>
          <span v-if="tip.same_channel_inconsistent?.length" class="chip chip--amber" title="Stesso canale, direzione diversa in altri video">
            ⚠ {{ tip.same_channel_inconsistent.length }} incoerenti
          </span>
          <span v-if="tip.other_channel_confirming?.length" class="chip chip--green" title="Altri canali confermano">
            ✓ {{ tip.other_channel_confirming.length }} conferme
          </span>
          <span v-if="tip.other_channel_contradicting?.length" class="chip chip--red" title="Altri canali smentiscono">
            ✗ {{ tip.other_channel_contradicting.length }} smentite
          </span>
        </div>

        <div class="tip-transfer">
          <span v-if="tip.from_club" class="tip-from">{{ tip.from_club }}</span>
          <span v-if="tip.from_club || tip.to_club" class="tip-arr">→</span>
          <span v-if="tip.to_club" class="tip-to">{{ tip.to_club }}</span>
          <span class="tip-type">({{ tip.transfer_type }})</span>
          <span class="tip-ch">{{ channelLabel(tip.channel_id) }}</span>
        </div>

        <p class="tip-body">{{ tip.tip_text }}</p>

        <div v-if="tipVideoUrl(tip)" class="tip-link-row">
          <a class="fc-yt" :href="tipVideoUrl(tip)" target="_blank" rel="noopener noreferrer">
            Apri video<span v-if="formatTime(tip.quote_start_sec)"> @ {{ formatTime(tip.quote_start_sec) }}</span>
          </a>
        </div>

        <!-- Fonti correlate -->
        <div v-if="tip.same_channel_consistent?.length || tip.same_channel_inconsistent?.length || tip.other_channel_confirming?.length || tip.other_channel_contradicting?.length">
          <button class="related-toggle" @click="toggleRelated(tip.tip_id)">
            {{ expandedTips.has(tip.tip_id) ? '▲' : '▼' }} Cronologia correlate
            <span v-if="tip.same_channel_inconsistent?.length" class="chip chip--amber" style="font-size:.65rem;padding:.1rem .3rem">⚠ {{ tip.same_channel_inconsistent.length }}</span>
            <span v-if="tip.same_channel_consistent?.length" class="chip chip--blue" style="font-size:.65rem;padding:.1rem .3rem">↔ {{ tip.same_channel_consistent.length }}</span>
            <span v-if="tip.other_channel_contradicting?.length" class="chip chip--red" style="font-size:.65rem;padding:.1rem .3rem">✗ {{ tip.other_channel_contradicting.length }}</span>
            <span v-if="tip.other_channel_confirming?.length" class="chip chip--green" style="font-size:.65rem;padding:.1rem .3rem">✓ {{ tip.other_channel_confirming.length }}</span>
          </button>
          <div v-if="expandedTips.has(tip.tip_id)" class="related-body">
            <template v-if="tip.same_channel_inconsistent?.length">
              <div class="related-sec-lbl" style="color:var(--am)">⚠ Incoerente con lo stesso canale</div>
              <div v-for="rt in tip.same_channel_inconsistent" :key="rt.tip_id" class="related-item related-item--ko">
                <div class="rel-header">
                  <span class="rel-ch">{{ rt.channel_id }}</span>
                  <span class="rel-dt">{{ formatDate(rt.mentioned_at) }}</span>
                  <span v-if="rt.to_club" style="font-size:.78rem;font-weight:600;color:var(--re)">→ {{ rt.to_club }}</span>
                  <span :class="['chip', OUTCOME_CHIP[rt.outcome]]" style="font-size:.65rem;padding:.1rem .3rem">{{ OUTCOME_LABELS[rt.outcome] }}</span>
                </div>
                <p class="rel-text">{{ rt.tip_text }}</p>
              </div>
            </template>
            <template v-if="tip.same_channel_consistent?.length">
              <div class="related-sec-lbl" style="color:var(--bl)">↔ Coerente con lo stesso canale</div>
              <div v-for="rt in tip.same_channel_consistent" :key="rt.tip_id" class="related-item related-item--ok">
                <div class="rel-header">
                  <span class="rel-ch">{{ rt.channel_id }}</span>
                  <span class="rel-dt">{{ formatDate(rt.mentioned_at) }}</span>
                  <span v-if="rt.to_club" style="font-size:.78rem;font-weight:600">→ {{ rt.to_club }}</span>
                  <span :class="['chip', OUTCOME_CHIP[rt.outcome]]" style="font-size:.65rem;padding:.1rem .3rem">{{ OUTCOME_LABELS[rt.outcome] }}</span>
                </div>
                <p class="rel-text">{{ rt.tip_text }}</p>
              </div>
            </template>
            <template v-if="tip.other_channel_contradicting?.length">
              <div class="related-sec-lbl" style="color:var(--re)">✗ Smentite da altri canali</div>
              <div v-for="rt in tip.other_channel_contradicting" :key="rt.tip_id" class="related-item related-item--contr">
                <div class="rel-header">
                  <span class="rel-ch">{{ rt.channel_id }}</span>
                  <span class="rel-dt">{{ formatDate(rt.mentioned_at) }}</span>
                  <span v-if="rt.to_club" style="font-size:.78rem;font-weight:600;color:var(--re)">→ {{ rt.to_club }}</span>
                  <span :class="['chip', OUTCOME_CHIP[rt.outcome]]" style="font-size:.65rem;padding:.1rem .3rem">{{ OUTCOME_LABELS[rt.outcome] }}</span>
                </div>
                <p class="rel-text">{{ rt.tip_text }}</p>
              </div>
            </template>
            <template v-if="tip.other_channel_confirming?.length">
              <div class="related-sec-lbl" style="color:var(--gr)">✓ Confermate da altri canali</div>
              <div v-for="rt in tip.other_channel_confirming" :key="rt.tip_id" class="related-item related-item--corr">
                <div class="rel-header">
                  <span class="rel-ch">{{ rt.channel_id }}</span>
                  <span class="rel-dt">{{ formatDate(rt.mentioned_at) }}</span>
                  <span v-if="rt.to_club" style="font-size:.78rem;font-weight:600">→ {{ rt.to_club }}</span>
                  <span :class="['chip', OUTCOME_CHIP[rt.outcome]]" style="font-size:.65rem;padding:.1rem .3rem">{{ OUTCOME_LABELS[rt.outcome] }}</span>
                </div>
                <p class="rel-text">{{ rt.tip_text }}</p>
              </div>
            </template>
          </div>
        </div>

        <div class="tip-foot">
          <span class="tip-meta">
            {{ tip.channel_id }} ·
            <template v-if="!tip.mentioned_at">
              <template v-if="dateEditingTip === tip.tip_id">
                <input type="date" v-model="dateEditValue" class="date-inline" />
                <button class="btn btn-primary btn-xs" @click="submitDateEdit(tip.tip_id)">✓</button>
                <button class="btn btn-ghost btn-xs" @click="cancelDateEdit">✗</button>
              </template>
              <span v-else class="tip-no-date" @click="startDateEdit(tip.tip_id)" title="Clicca per aggiungere la data">Senza data</span>
            </template>
            <template v-else>{{ formatDate(tip.mentioned_at) }}</template>
          </span>

          <div class="tip-actions">
            <button v-if="tip.outcome === 'non_verificata'" class="btn btn-secondary btn-sm" @click="verifyTip(tip.tip_id)">
              ⟳ Verifica
            </button>
            <button class="btn btn-ghost btn-sm" @click="toggleManualOverride(tip.tip_id)">
              {{ manualOverrideTips.has(tip.tip_id) ? '▲' : '▼' }} Override
            </button>
            <template v-if="manualOverrideTips.has(tip.tip_id)">
              <button class="btn-outcome btn-true" @click="setOutcome(tip.tip_id, 'confermata')">Confermata</button>
              <button class="btn-outcome btn-partial" @click="setOutcome(tip.tip_id, 'parziale')">Parziale</button>
              <button class="btn-outcome btn-false" @click="setOutcome(tip.tip_id, 'smentita')">Smentita</button>
              <button class="btn-outcome btn-stalled" @click="setOutcome(tip.tip_id, 'non_conclusa')">Non conclusa</button>
              <button class="btn-outcome btn-reset" @click="setOutcome(tip.tip_id, 'non_verificata')">Reset</button>
            </template>
          </div>
        </div>

        <div v-if="tip.outcome_notes" class="outcome-note-row">
          <span class="note-text">{{ tip.outcome_notes }}</span>
        </div>
      </div>
    </div>

    <!-- Modal mappa nome -->
    <div v-if="aliasModal.show" class="overlay" @click.self="closeAliasModal">
      <div class="modal">
        <h3 class="modal-title">Mappa nome giocatore</h3>
        <p class="modal-sub">Il nome sbagliato verrà sostituito con quello corretto al prossimo caricamento.</p>
        <div class="modal-field">
          <label class="modal-lbl">Nome attuale (sbagliato)</label>
          <input class="modal-inp modal-inp--readonly" :value="aliasModal.alias" readonly />
        </div>
        <div class="modal-field">
          <label class="modal-lbl">Nome corretto</label>
          <input
            class="modal-inp"
            v-model="aliasModal.canonical"
            placeholder="Es. Victor Osimhen"
            @keyup.enter="submitAlias"
            autofocus
          />
        </div>
        <p v-if="aliasModal.error" class="modal-error">{{ aliasModal.error }}</p>
        <div class="modal-foot">
          <button class="btn btn-ghost" @click="closeAliasModal">Annulla</button>
          <button
            class="btn btn-primary"
            :disabled="aliasModal.saving || !aliasModal.canonical.trim()"
            @click="submitAlias"
          >
            {{ aliasModal.saving ? 'Salvataggio...' : 'Salva mapping' }}
          </button>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
/* Outcome override buttons */
.btn-outcome {
  font-size: .78rem; font-weight: 600; padding: .25rem .6rem;
  border: 1px solid var(--line); border-radius: var(--rs); cursor: pointer;
  background: var(--bg-el); color: var(--t1);
}
.btn-true    { border-color: var(--gr); color: var(--gr); }
.btn-partial { border-color: var(--am); color: var(--am); }
.btn-false   { border-color: var(--re); color: var(--re); }
.btn-stalled { border-color: var(--am); color: var(--am); }
.btn-reset   { color: var(--t3); }
.btn-true:hover    { background: rgba(122,185,138,0.15); }
.btn-partial:hover { background: rgba(197,168,106,0.15); }
.btn-false:hover   { background: rgba(184,122,122,0.15); }
.btn-stalled:hover { background: rgba(197,168,106,0.15); }

/* Trasferimenti panel */
.tf-list { display: flex; flex-direction: column; gap: .3rem; margin-top: .5rem; }
.tf-player { font-weight: 700; font-family: var(--s); }
.tf-from { color: var(--re); font-weight: 600; }
.tf-to { color: var(--gr); font-weight: 600; }
.tf-arr { color: var(--t3); }
.tf-meta { color: var(--t3); font-size: .75rem; }
.tf-link { color: var(--au); font-size: .75rem; text-decoration: none; }
.tf-link:hover { text-decoration: underline; }
.tm-fetch-row { display: flex; gap: .4rem; flex-wrap: wrap; align-items: center; margin-bottom: .75rem; }
.roster-fetch-row { display: flex; gap: .4rem; flex-wrap: wrap; align-items: center; margin-bottom: .4rem; }
.roster-log { display: flex; flex-direction: column; gap: .1rem; margin-bottom: .75rem; padding: .35rem .6rem; background: var(--bg-el); border-radius: 4px; }
.roster-log-line { font-size: .75rem; color: var(--t3); font-family: monospace; white-space: pre-wrap; }
.add-transfer-details { margin-bottom: .75rem; }
.add-transfer-details summary { cursor: pointer; font-size: .85rem; color: var(--au); font-weight: 600; margin-bottom: .5rem; }
.add-transfer-form { display: flex; gap: .35rem; flex-wrap: wrap; align-items: center; padding: .5rem 0; }
.fetch-ok { color: var(--gr); font-size: .82rem; font-weight: 600; }
.fetch-err { color: var(--re); font-size: .82rem; }

/* Stats */
.stat-numbers { display: flex; gap: .25rem; align-items: baseline; font-size: .8rem; }
.stat-val { font-weight: 600; }
.stat-unit { color: var(--t3); }
.stat-score { color: var(--gr); font-weight: 600; }
.stat-score-na { color: var(--t3); font-style: italic; }

/* Tip internals */
.tip-transfer { display: flex; align-items: center; gap: .4rem; margin-bottom: .4rem; font-size: .875rem; }
.tip-from { color: var(--re); font-weight: 600; }
.tip-to { color: var(--gr); font-weight: 600; }
.tip-arr { color: var(--t3); }
.tip-type { color: var(--t3); font-size: .8rem; }
.tip-ch { margin-left: auto; font-size: .75rem; color: var(--t3); background: var(--bg-el); padding: .1rem .45rem; border-radius: var(--rs); }
.tip-link-row { margin-bottom: .4rem; }

/* Related source items */
.rel-header { display: flex; align-items: center; gap: .35rem; flex-wrap: wrap; margin-bottom: .2rem; }
.rel-ch { font-weight: 600; font-size: .75rem; color: var(--t2); }
.rel-dt { font-size: .72rem; color: var(--t3); font-family: var(--m); }
.rel-text { margin: 0; font-size: .82rem; color: var(--t2); }
.related-sec-lbl { font-size: .72rem; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; padding: .2rem 0 .1rem; margin-top: .3rem; }

/* Date editing inline */
.date-inline { font-size: .8rem; padding: .1rem .3rem; border: 1px solid var(--line); border-radius: var(--rs); background: var(--bg-el); color: var(--t1); }
.tip-no-date { color: var(--am); cursor: pointer; border-bottom: 1px dashed var(--am); }
.tip-no-date:hover { color: var(--au); }

/* Modal internals */
.btn-xs { font-size: .7rem; padding: .15rem .4rem; }
.modal-field { display: flex; flex-direction: column; gap: .25rem; margin-bottom: .8rem; }
.modal-lbl { font-size: .78rem; font-weight: 600; color: var(--t2); }
.modal-inp--readonly { opacity: .65; }
.modal-error { color: var(--re); font-size: .82rem; margin: 0 0 .75rem; }

/* Outcome note + source */
.outcome-note-row { margin-top: .25rem; }
.note-text { color: var(--t3); font-style: italic; font-size: .82rem; }
.outcome-source { font-size: .65rem; opacity: .7; margin-left: .2rem; }
</style>

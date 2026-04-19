<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
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
</script>

<template>
  <div class="mercato-view">
    <div class="mercato-header">
      <div class="mercato-title-row">
        <div>
          <h2 class="mercato-title">Calciomercato</h2>
          <p class="mercato-subtitle">Tracking indiscrezioni — verifica automatica via Transfermarkt</p>
        </div>
        <div class="header-actions">
          <button class="btn-verify-all" :disabled="verifying" @click="verifyAll">
            {{ verifying ? 'Verificando...' : '⟳ Verifica tutte' }}
          </button>
          <button class="btn-transfers-toggle" @click="showTransfers = !showTransfers">
            {{ showTransfers ? '▲' : '▼' }} Trasferimenti ufficiali ({{ transfers.length }})
          </button>
        </div>
      </div>
    </div>

    <!-- Sezione trasferimenti ufficiali -->
    <div v-if="showTransfers" class="transfers-section">
      <h3 class="transfers-title">Trasferimenti ufficiali</h3>

      <!-- Fetch da TM -->
      <div class="tm-fetch-row">
        <input v-model="fetchPlayer" class="filter-input" placeholder="Nome giocatore..." style="max-width:200px" />
        <input v-model="fetchSeason" class="filter-input" placeholder="Stagione (es. 2025)" style="max-width:140px" />
        <button class="btn-tm-fetch" :disabled="fetchingTM || !fetchPlayer" @click="fetchFromTM">
          {{ fetchingTM ? 'Scaricando...' : '↓ Fetch da Transfermarkt' }}
        </button>
        <span v-if="fetchResult && !fetchResult.error" class="fetch-ok">✓ {{ fetchResult.added }} aggiunto/i</span>
        <span v-if="fetchResult?.error" class="fetch-err">✗ {{ fetchResult.error }}</span>
      </div>

      <!-- Form aggiunta manuale -->
      <details class="add-transfer-details">
        <summary>+ Aggiungi trasferimento manuale</summary>
        <div class="add-transfer-form">
          <input v-model="newTransfer.player_name" class="tf-input" placeholder="Giocatore *" />
          <input v-model="newTransfer.from_club" class="tf-input" placeholder="Da club" />
          <input v-model="newTransfer.to_club" class="tf-input" placeholder="A club *" />
          <select v-model="newTransfer.transfer_type" class="tf-select">
            <option value="unknown">Tipo</option>
            <option value="permanent">Permanente</option>
            <option value="loan">Prestito</option>
            <option value="free_agent">Svincolato</option>
            <option value="extension">Rinnovo</option>
          </select>
          <input v-model="newTransfer.season" class="tf-input" placeholder="Stagione * (es. 2025-26)" />
          <input v-model="newTransfer.confirmed_at" class="tf-input" type="date" placeholder="Data *" />
          <input v-model="newTransfer.source_url" class="tf-input" placeholder="URL Transfermarkt" />
          <button class="btn-add-transfer" :disabled="addingTransfer" @click="addTransfer">
            {{ addingTransfer ? '...' : 'Aggiungi' }}
          </button>
        </div>
      </details>

      <!-- Lista trasferimenti -->
      <div v-if="transfers.length" class="transfers-list">
        <div v-for="tr in transfers" :key="tr.transfer_id" class="transfer-row">
          <span class="tr-player">{{ tr.player_name }}</span>
          <span v-if="tr.from_club" class="tr-club tr-from">{{ tr.from_club }}</span>
          <span v-if="tr.from_club || tr.to_club" class="tr-arrow">→</span>
          <span v-if="tr.to_club" class="tr-club tr-to">{{ tr.to_club }}</span>
          <span class="tr-type">{{ tr.transfer_type }}</span>
          <span class="tr-season">{{ tr.season }}</span>
          <span class="tr-date">{{ formatDate(tr.confirmed_at) }}</span>
          <span class="tr-source">{{ tr.source }}</span>
          <a v-if="tr.source_url" :href="tr.source_url" target="_blank" class="tr-link">TM ↗</a>
          <button class="tr-delete" @click="deleteTransfer(tr.transfer_id)" title="Rimuovi">✕</button>
        </div>
      </div>
      <p v-else class="empty">Nessun trasferimento nel database. Aggiungine uno sopra.</p>
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
        @input="onPlayerInput"
      />
      <select v-model="filterChannel" class="filter-select" @change="fetchTips">
        <option value="">Tutti i canali</option>
        <option v-for="s in stats" :key="s.channel_id" :value="s.channel_id">
          {{ channelLabel(s.channel_id) }}
        </option>
      </select>
      <select v-model="filterOutcome" class="filter-select" @change="fetchTips">
        <option value="">Tutti gli esiti</option>
        <option value="non_verificata">Non verificate</option>
        <option value="confermata">Confermate</option>
        <option value="parziale">Parziali</option>
        <option value="smentita">Smentite</option>
        <option value="non_conclusa">Non concluse</option>
      </select>
      <select v-model="filterSeason" class="filter-select" @change="fetchTips">
        <option value="">Tutte le sessioni</option>
        <option v-for="s in seasons" :key="s.id" :value="s.id">{{ s.label }}</option>
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
          <button class="btn-map-alias" @click="openAliasModal(tip.player_name)" title="Mappa nome sbagliato">
            Mappa nome
          </button>
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
          <span class="tip-channel-badge">{{ channelLabel(tip.channel_id) }}</span>
        </div>

        <p class="tip-text">{{ tip.tip_text }}</p>
        <div v-if="tipVideoUrl(tip)" class="tip-source-row">
          <a class="tip-video-link" :href="tipVideoUrl(tip)" target="_blank" rel="noopener noreferrer">
            Apri video<span v-if="formatTime(tip.quote_start_sec)"> @ {{ formatTime(tip.quote_start_sec) }}</span>
          </a>
        </div>

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

        <div class="tip-footer">
          <span class="tip-meta">
            {{ tip.channel_id }} ·
            <template v-if="!tip.mentioned_at">
              <template v-if="dateEditingTip === tip.tip_id">
                <input type="date" v-model="dateEditValue" class="date-input-inline" />
                <button class="btn-date-ok" @click="submitDateEdit(tip.tip_id)">✓</button>
                <button class="btn-date-cancel" @click="cancelDateEdit">✗</button>
              </template>
              <span v-else class="tip-no-date" @click="startDateEdit(tip.tip_id)" title="Clicca per aggiungere la data">Senza data</span>
            </template>
            <template v-else>{{ formatDate(tip.mentioned_at) }}</template>
          </span>

          <div class="outcome-actions">
            <!-- Verifica automatica (sempre disponibile se non_verificata) -->
            <button v-if="tip.outcome === 'non_verificata'" class="btn-outcome btn-verify" @click="verifyTip(tip.tip_id)">
              ⟳ Verifica
            </button>

            <!-- Override manuale toggle -->
            <button class="btn-manual-toggle" @click="toggleManualOverride(tip.tip_id)">
              {{ manualOverrideTips.has(tip.tip_id) ? '▲' : '▼' }} Override manuale
            </button>

            <!-- Bottoni override (collassabili) -->
            <template v-if="manualOverrideTips.has(tip.tip_id)">
              <button class="btn-outcome btn-true" @click="setOutcome(tip.tip_id, 'confermata')">Confermata</button>
              <button class="btn-outcome btn-partial" @click="setOutcome(tip.tip_id, 'parziale')">Parziale</button>
              <button class="btn-outcome btn-false" @click="setOutcome(tip.tip_id, 'smentita')">Smentita</button>
              <button class="btn-outcome btn-stalled" @click="setOutcome(tip.tip_id, 'non_conclusa')">Non conclusa</button>
              <button class="btn-outcome btn-reset" @click="setOutcome(tip.tip_id, 'non_verificata')">Non verif.</button>
            </template>
          </div>
        </div>

        <!-- Note outcome -->
        <div v-if="tip.outcome_notes" class="outcome-note-row">
          <span class="note-text">{{ tip.outcome_notes }}</span>
        </div>
      </div>
    </div>

    <!-- Modal mappa nome -->
    <div v-if="aliasModal.show" class="alias-overlay" @click.self="closeAliasModal">
      <div class="alias-modal">
        <h3 class="alias-title">Mappa nome giocatore</h3>
        <p class="alias-desc">Il nome sbagliato verrà sostituito con quello corretto al prossimo caricamento.</p>
        <div class="alias-field">
          <label class="alias-label">Nome attuale (sbagliato)</label>
          <input class="alias-input alias-input-readonly" :value="aliasModal.alias" readonly />
        </div>
        <div class="alias-field">
          <label class="alias-label">Nome corretto</label>
          <input
            class="alias-input"
            v-model="aliasModal.canonical"
            placeholder="Es. Victor Osimhen"
            @keyup.enter="submitAlias"
            autofocus
          />
        </div>
        <p v-if="aliasModal.error" class="alias-error">{{ aliasModal.error }}</p>
        <div class="alias-actions">
          <button class="btn-alias-cancel" @click="closeAliasModal">Annulla</button>
          <button
            class="btn-alias-save"
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
.mercato-view { max-width: 900px; margin: 0 auto; padding: 1.5rem 1rem; }
.mercato-header { margin-bottom: 1.5rem; }
.mercato-title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.mercato-title { font-size: 1.6rem; font-weight: 700; margin: 0 0 .25rem; }
.mercato-subtitle { color: var(--color-text-muted, #888); margin: 0; font-size: .9rem; }
.header-actions { display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; }
.btn-verify-all {
  background: #0066cc; color: #fff; border: none; border-radius: 6px;
  padding: .4rem .9rem; font-size: .82rem; font-weight: 600; cursor: pointer;
}
.btn-verify-all:disabled { opacity: .6; cursor: default; }
.btn-verify-all:hover:not(:disabled) { background: #0052a3; }
.btn-transfers-toggle {
  background: var(--color-surface, #f5f5f5); border: 1px solid var(--color-border, #ddd);
  border-radius: 6px; padding: .4rem .9rem; font-size: .82rem; cursor: pointer;
  color: var(--color-text, #111);
}

/* Trasferimenti ufficiali */
.transfers-section {
  background: var(--color-surface, #f5f5f5);
  border: 1px solid var(--color-border, #e0e0e0);
  border-radius: 10px; padding: 1rem 1.1rem; margin-bottom: 1.5rem;
}
.transfers-title { font-size: 1rem; font-weight: 700; margin: 0 0 .75rem; }
.tm-fetch-row { display: flex; gap: .4rem; flex-wrap: wrap; align-items: center; margin-bottom: .75rem; }
.btn-tm-fetch {
  background: #1d4ed8; color: #fff; border: none; border-radius: 6px;
  padding: .35rem .8rem; font-size: .82rem; font-weight: 600; cursor: pointer;
}
.btn-tm-fetch:disabled { opacity: .6; cursor: default; }
.fetch-ok { color: #16a34a; font-size: .82rem; font-weight: 600; }
.fetch-err { color: #dc2626; font-size: .82rem; }

.add-transfer-details { margin-bottom: .75rem; }
.add-transfer-details summary { cursor: pointer; font-size: .85rem; color: #0066cc; font-weight: 600; margin-bottom: .5rem; }
.add-transfer-form { display: flex; gap: .35rem; flex-wrap: wrap; align-items: center; padding: .5rem 0; }
.tf-input, .tf-select {
  padding: .3rem .5rem; border: 1px solid var(--color-border, #ddd);
  border-radius: 5px; background: var(--color-bg, #fff); color: var(--color-text, #111);
  font-size: .82rem;
}
.btn-add-transfer {
  background: #16a34a; color: #fff; border: none; border-radius: 5px;
  padding: .3rem .7rem; font-size: .82rem; font-weight: 600; cursor: pointer;
}
.btn-add-transfer:disabled { opacity: .6; }

.transfers-list { display: flex; flex-direction: column; gap: .3rem; margin-top: .5rem; }
.transfer-row {
  display: flex; align-items: center; gap: .4rem; flex-wrap: wrap;
  padding: .3rem .5rem; background: var(--color-bg, #fff);
  border: 1px solid var(--color-border, #eee); border-radius: 6px; font-size: .8rem;
}
.tr-player { font-weight: 700; }
.tr-club { font-weight: 600; }
.tr-from { color: #e03e3e; }
.tr-to { color: #22a06b; }
.tr-arrow { color: var(--color-text-muted, #aaa); }
.tr-type, .tr-season, .tr-date, .tr-source { color: var(--color-text-muted, #888); font-size: .75rem; }
.tr-link { color: #0066cc; font-size: .75rem; text-decoration: none; }
.tr-delete {
  margin-left: auto; background: none; border: none; color: #aaa;
  cursor: pointer; font-size: .8rem; padding: 0 .2rem;
}
.tr-delete:hover { color: #dc2626; }

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
  color: var(--color-text, #111);
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
.badge-same-ok { background: #e0f2fe; color: #0369a1; }
.badge-same-ko { background: #fef9c3; color: #854d0e; }
.badge-corr    { background: #d1fae5; color: #065f46; }
.badge-contr   { background: #fee2e2; color: #991b1b; }
.outcome-pending  { background: #f0f0f0; color: #555; }
.outcome-true     { background: #d1e7dd; color: #0a3622; }
.outcome-false    { background: #f8d7da; color: #842029; }
.outcome-partial  { background: #fff3cd; color: #856404; }
.outcome-stalled  { background: #ffedd5; color: #9a3412; }

.tip-transfer { display: flex; align-items: center; gap: .4rem; margin-bottom: .4rem; font-size: .875rem; }
.club { font-weight: 600; }
.from { color: #e03e3e; }
.to   { color: #22a06b; }
.arrow { color: var(--color-text-muted, #aaa); }
.tip-channel-badge { margin-left: auto; font-size: .75rem; color: var(--color-text-muted, #aaa); background: var(--color-bg-soft, #2a2a2a); padding: .1rem .45rem; border-radius: 4px; }
.transfer-type { color: var(--color-text-muted, #aaa); font-size: .8rem; }

.tip-text {
  margin: 0 0 .4rem;
  font-size: .9rem;
  color: var(--color-text, var(--text-secondary));
}
.tip-source-row { margin: 0 0 .5rem; }
.tip-video-link {
  font-size: .78rem;
  color: var(--color-accent, #0066cc);
  text-decoration: underline;
}
.tip-video-link:hover { color: #0052a3; }
.tip-quote {
  margin: 0 0 .6rem; padding: .3rem .6rem;
  border-left: 3px solid var(--color-border, #ddd);
  font-style: italic; font-size: .82rem;
  color: var(--color-text-muted, #666);
}

.tip-footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: .5rem; }
.tip-meta { font-size: .78rem; color: var(--color-text-muted, #999); }
.tip-no-date { color: #e07b00; cursor: pointer; border-bottom: 1px dashed #e07b00; }
.tip-no-date:hover { color: #c06000; }
.date-input-inline { font-size: .8rem; padding: .1rem .3rem; border: 1px solid #ccc; border-radius: 4px; }
.btn-date-ok { font-size: .8rem; padding: .1rem .4rem; background: #2a9d2a; color: #fff; border: none; border-radius: 4px; cursor: pointer; margin-left: .2rem; }
.btn-date-cancel { font-size: .8rem; padding: .1rem .4rem; background: #999; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
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
.btn-stalled { background: #ffedd5; color: #9a3412; }
.btn-reset   { background: #f0f0f0; color: #555; }
.btn-true:hover    { background: #a3cfbb; }
.btn-partial:hover { background: #ffe69c; }
.btn-false:hover   { background: #f1aeb5; }
.btn-stalled:hover { background: #fed7aa; }
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

/* Mappa nome */
.btn-map-alias {
  background: none; border: 1px solid var(--color-border, #ddd);
  border-radius: 4px; padding: .1rem .45rem; font-size: .7rem;
  color: var(--color-text-muted, #888); cursor: pointer;
  white-space: nowrap;
}
.btn-map-alias:hover { border-color: #0066cc; color: #0066cc; }

.alias-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.45);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
}
.alias-modal {
  background: var(--color-bg, #fff); border-radius: 12px;
  padding: 1.5rem 1.75rem; max-width: 420px; width: 90%;
  box-shadow: 0 8px 32px rgba(0,0,0,.2);
}
.alias-title { font-size: 1.1rem; font-weight: 700; margin: 0 0 .4rem; }
.alias-desc { font-size: .82rem; color: var(--color-text-muted, #888); margin: 0 0 1rem; }
.alias-field { display: flex; flex-direction: column; gap: .25rem; margin-bottom: .8rem; }
.alias-label { font-size: .78rem; font-weight: 600; color: var(--color-text-muted, #666); }
.alias-input {
  padding: .45rem .65rem; border: 1px solid var(--color-border, #ddd); border-radius: 6px;
  background: var(--color-bg, #fff); color: var(--color-text, #111); font-size: .9rem;
}
.alias-input:focus { outline: 2px solid #0066cc; border-color: transparent; }
.alias-input-readonly { background: var(--color-surface, #f5f5f5); color: var(--color-text-muted, #666); }
.alias-error { color: #dc2626; font-size: .82rem; margin: 0 0 .75rem; }
.alias-actions { display: flex; gap: .6rem; justify-content: flex-end; margin-top: .5rem; }
.btn-alias-cancel {
  background: none; border: 1px solid var(--color-border, #ddd); border-radius: 6px;
  padding: .4rem .9rem; font-size: .85rem; cursor: pointer; color: var(--color-text, #111);
}
.btn-alias-save {
  background: #0066cc; color: #fff; border: none; border-radius: 6px;
  padding: .4rem .9rem; font-size: .85rem; font-weight: 600; cursor: pointer;
}
.btn-alias-save:disabled { opacity: .6; cursor: default; }
.btn-alias-save:hover:not(:disabled) { background: #0052a3; }
</style>

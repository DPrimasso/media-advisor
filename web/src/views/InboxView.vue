<script setup>
import { ref, computed, onMounted } from 'vue'

const pending = ref(null)
const loading = ref(true)
const fetching = ref(false)
const confirming = ref(false)
const message = ref(null)
const selected = ref(new Set())

const items = computed(() => pending.value?.items ?? [])

const selectedCount = computed(() => selected.value.size)

const allSelected = computed({
  get: () => items.value.length > 0 && selected.value.size === items.value.length,
  set: (v) => {
    if (v) {
      selected.value = new Set(items.value.map((i) => `${i.channel_id}:${i.video_id}`))
    } else {
      selected.value = new Set()
    }
  }
})

function itemKey(item) {
  return `${item.channel_id}:${item.video_id}`
}

function isSelected(item) {
  return selected.value.has(itemKey(item))
}

function toggleItem(item) {
  const key = itemKey(item)
  const next = new Set(selected.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  selected.value = next
}

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('it-IT', {
    day: 'numeric',
    month: 'short',
    year: 'numeric'
  })
}

async function loadPending() {
  loading.value = true
  message.value = null
  try {
    const r = await fetch('/api/pending')
    if (r.ok) {
      pending.value = await r.json()
      selected.value = new Set()
    } else {
      pending.value = { fetched_at: null, items: [] }
    }
  } catch (e) {
    message.value = { type: 'error', text: e?.message ?? String(e) }
    pending.value = { fetched_at: null, items: [] }
  } finally {
    loading.value = false
  }
}

async function fetchNow() {
  fetching.value = true
  message.value = null
  try {
    const r = await fetch('/api/fetch-now', { method: 'POST' })
    if (!r.ok) {
      const err = await r.json().catch(() => ({}))
      throw new Error(err.error || r.statusText)
    }
    const data = await r.json()
    pending.value = data
    selected.value = new Set()
    message.value = { type: 'success', text: `${data.items?.length ?? 0} nuovi video trovati` }
  } catch (e) {
    message.value = { type: 'error', text: e?.message ?? String(e) }
  } finally {
    fetching.value = false
  }
}

async function confirmSelected() {
  const toConfirm = items.value.filter((i) => selected.value.has(itemKey(i)))
  if (toConfirm.length === 0) return
  confirming.value = true
  message.value = null
  try {
    const r = await fetch('/api/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        items: toConfirm.map((i) => ({ channel_id: i.channel_id, video_id: i.video_id })),
        trigger_pipeline: true
      })
    })
    if (!r.ok) {
      const err = await r.json().catch(() => ({}))
      throw new Error(err.error || r.statusText)
    }
    const data = await r.json()
    message.value = { type: 'success', text: `${data.confirmed} video confermati. Transcript e analisi in corso.` }
    await loadPending()
  } catch (e) {
    message.value = { type: 'error', text: e?.message ?? String(e) }
  } finally {
    confirming.value = false
  }
}

onMounted(loadPending)
</script>

<template>
  <div class="inbox-view">
    <div class="inbox-header">
      <h2 class="inbox-title">Inbox — Video da confermare</h2>
      <p class="inbox-intro">
        I video qui sotto sono stati trovati dai canali configurati e non sono ancora nella lista di download.
        Seleziona quelli da aggiungere e conferma per avviare transcript e analisi.
      </p>
    </div>

    <div v-if="message" class="inbox-message" :class="message.type">
      {{ message.text }}
    </div>

    <div v-if="loading" class="loading">Caricamento...</div>

    <div v-else-if="!items.length" class="inbox-empty">
      <p class="empty-state-title">Nessun video in attesa</p>
      <p class="empty-state-text">
        Esegui una ricerca per trovare nuovi video dai canali configurati.
      </p>
      <button
        type="button"
        class="inbox-fetch-btn"
        :disabled="fetching"
        @click="fetchNow"
      >
        {{ fetching ? 'Ricerca in corso...' : 'Cerca nuovi video' }}
      </button>
    </div>

    <div v-else class="inbox-content">
      <div class="inbox-toolbar">
        <label class="inbox-select-all">
          <input type="checkbox" :checked="allSelected" @change="allSelected = $event.target.checked" />
          Seleziona tutti
        </label>
        <span class="inbox-count">{{ items.length }} video · {{ selectedCount }} selezionati</span>
        <button
          type="button"
          class="inbox-confirm-btn"
          :disabled="selectedCount === 0 || confirming"
          @click="confirmSelected"
        >
          {{ confirming ? 'Conferma in corso...' : `Conferma (${selectedCount})` }}
        </button>
      </div>

      <div class="feed-grid inbox-grid">
        <article
          v-for="item in items"
          :key="itemKey(item)"
          class="video-card inbox-card"
          :class="{ selected: isSelected(item) }"
        >
          <label class="inbox-card-inner">
            <input
              type="checkbox"
              :checked="isSelected(item)"
              class="inbox-checkbox"
              @change="toggleItem(item)"
            />
            <a
              :href="item.url"
              target="_blank"
              rel="noopener"
              class="video-card-thumb-link"
              @click.stop
            >
              <div class="video-card-thumb">
                <img
                  :src="`https://i.ytimg.com/vi/${item.video_id}/mqdefault.jpg`"
                  :alt="item.title"
                  loading="lazy"
                />
                <span class="video-card-badge">▶</span>
              </div>
            </a>
            <div class="video-card-body">
              <h3 class="video-card-title">{{ item.title || 'Senza titolo' }}</h3>
              <div class="video-card-meta">
                <span class="video-card-channel">{{ item.channel_name }}</span>
                <span v-if="item.published" class="video-card-date">
                  {{ formatDate(item.published) }}
                </span>
              </div>
            </div>
          </label>
        </article>
      </div>
    </div>
  </div>
</template>

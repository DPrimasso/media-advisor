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
  <div class="page">
    <div class="masthead">
      <div style="flex:1">
        <h1 class="masthead-title">Inbox</h1>
        <div class="masthead-date">Video da confermare per download e analisi</div>
      </div>
    </div>

    <div v-if="message" class="inbox-msg" :class="message.type === 'error' ? 'inbox-msg--err' : 'inbox-msg--ok'">
      {{ message.text }}
    </div>

    <div v-if="loading" class="loading-wrap"><span class="spinner"></span></div>

    <div v-else-if="!items.length" class="empty">
      <div class="empty-icon">📭</div>
      <div class="empty-title">Nessun video in attesa</div>
      <div class="empty-sub">Esegui una ricerca per trovare nuovi video dai canali configurati.</div>
      <button type="button" class="btn btn-primary" style="margin-top:1rem" :disabled="fetching" @click="fetchNow">
        {{ fetching ? 'Ricerca in corso...' : 'Cerca nuovi video' }}
      </button>
    </div>

    <div v-else>
      <div class="inbox-toolbar">
        <label class="inbox-select-all">
          <input type="checkbox" :checked="allSelected" @change="allSelected = $event.target.checked" />
          Seleziona tutti
        </label>
        <span class="tip-meta">{{ items.length }} video · {{ selectedCount }} selezionati</span>
        <button
          type="button"
          class="btn btn-primary btn-sm"
          :disabled="selectedCount === 0 || confirming"
          @click="confirmSelected"
        >
          {{ confirming ? 'Conferma in corso...' : `Conferma (${selectedCount})` }}
        </button>
      </div>

      <div class="inbox-grid">
        <article
          v-for="item in items"
          :key="itemKey(item)"
          class="inbox-item"
          :class="{ 'inbox-item--sel': isSelected(item) }"
        >
          <label class="inbox-item-inner">
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
              class="inbox-thumb-link"
              @click.stop
            >
              <div class="inbox-thumb">
                <img
                  :src="`https://i.ytimg.com/vi/${item.video_id}/mqdefault.jpg`"
                  :alt="item.title"
                  loading="lazy"
                />
                <span class="inbox-play">▶</span>
              </div>
            </a>
            <div class="inbox-body">
              <h3 class="inbox-title-text">{{ item.title || 'Senza titolo' }}</h3>
              <div class="inbox-meta">
                <span class="fc-src">{{ item.channel_name }}</span>
                <span v-if="item.published" class="fc-time">{{ formatDate(item.published) }}</span>
              </div>
            </div>
          </label>
        </article>
      </div>
    </div>
  </div>
</template>

<style scoped>
.inbox-toolbar { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; margin-bottom: 1rem; }
.inbox-select-all { display: flex; align-items: center; gap: .35rem; font-size: .875rem; color: var(--t2); cursor: pointer; }
.inbox-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: .75rem; }
.inbox-item { display: block; padding: 0; margin-bottom: 0; border: 1px solid var(--line); border-radius: var(--r); overflow: hidden; background: var(--bg-card); transition: border-color .15s; }
.inbox-item--sel { border-color: var(--au); }
.inbox-item-inner { display: flex; flex-direction: column; cursor: pointer; position: relative; }
.inbox-checkbox { position: absolute; top: .5rem; left: .5rem; accent-color: var(--au); z-index: 1; }
.inbox-thumb-link { display: block; }
.inbox-thumb { position: relative; aspect-ratio: 16/9; overflow: hidden; background: var(--bg-el); }
.inbox-thumb img { width: 100%; height: 100%; object-fit: cover; }
.inbox-play { position: absolute; bottom: .4rem; right: .4rem; background: rgba(0,0,0,.7); color: #fff; font-size: .7rem; padding: .15rem .35rem; border-radius: 3px; }
.inbox-body { padding: .6rem .75rem .75rem; }
.inbox-title-text { margin: 0 0 .35rem; font-size: .875rem; font-weight: 600; line-height: 1.3; color: var(--t1); }
.inbox-meta { display: flex; gap: .5rem; flex-wrap: wrap; }
.inbox-msg { padding: .6rem 1rem; border-radius: var(--rs); margin-bottom: 1rem; font-size: .875rem; }
.inbox-msg--ok { background: rgba(122,185,138,0.15); color: var(--gr); border: 1px solid var(--gr); }
.inbox-msg--err { background: rgba(184,122,122,0.15); color: var(--re); border: 1px solid var(--re); }
</style>

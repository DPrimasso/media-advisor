<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  claims: { type: Array, default: () => [] }
})

const expandedId = ref(null)

function toggleExpand(claim) {
  const id = claim.claim_id || `${claim.video_id}-${claim.claim_text?.slice(0, 20)}`
  expandedId.value = expandedId.value === id ? null : id
}

function isExpanded(claim) {
  const id = claim.claim_id || `${claim.video_id}-${claim.claim_text?.slice(0, 20)}`
  return expandedId.value === id
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

function formatTimestamp(sec) {
  if (sec == null || isNaN(sec)) return ''
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function getTimestamp(claim) {
  const q = claim.evidence_quotes?.[0]
  const sec = q?.start_sec
  return sec != null && !isNaN(parseFloat(sec)) ? parseFloat(sec) : null
}

function getPreview(claim) {
  const text = claim.claim_text || claim.position || ''
  return text.length > 100 ? text.slice(0, 100) + '…' : text
}

function getYoutubeUrl(claim) {
  const t = getTimestamp(claim)
  const base = `https://www.youtube.com/watch?v=${claim.video_id}`
  if (t == null) return base
  const sec = Math.floor(t)
  return `${base}&t=${sec}`
}
</script>

<template>
  <div class="claim-list">
    <div v-if="!claims.length" class="claim-list-empty">Nessun claim trovato</div>
    <div v-for="claim in claims" :key="claim.claim_id || claim.video_id + '-' + (claim.claim_text || '').slice(0, 30)" class="claim-card">
      <div
        class="claim-card-main"
        role="button"
        tabindex="0"
        @click="toggleExpand(claim)"
        @keydown.enter="toggleExpand(claim)"
      >
        <div class="claim-card-header">
          <span class="claim-channel">{{ claim.channel_name }}</span>
          <span class="claim-date">{{ formatDate(claim.metadata?.published_at) }}</span>
        </div>
        <h3 class="claim-video-title">{{ claim.metadata?.title || 'Senza titolo' }}</h3>
        <p class="claim-preview">{{ getPreview(claim) }}</p>
        <a
          v-if="getTimestamp(claim) != null"
          :href="getYoutubeUrl(claim)"
          target="_blank"
          rel="noopener"
          class="claim-timestamp-link"
          @click.stop
        >
          Vai al punto esatto {{ formatTimestamp(getTimestamp(claim)) }} →
        </a>
      </div>
      <div v-show="isExpanded(claim)" class="claim-card-detail">
        <p class="claim-full-text">{{ claim.claim_text || claim.position }}</p>
        <blockquote v-if="claim.evidence_quotes?.[0]?.quote_text" class="claim-quote">
          «{{ claim.evidence_quotes[0].quote_text }}»
        </blockquote>
        <a
          :href="getYoutubeUrl(claim)"
          target="_blank"
          rel="noopener"
          class="claim-detail-link"
        >
          {{ getTimestamp(claim) != null ? `Guarda dal minuto ${formatTimestamp(getTimestamp(claim))} →` : 'Apri video →' }}
        </a>
      </div>
    </div>
  </div>
</template>

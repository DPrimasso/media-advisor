<script setup>
import { ref, computed, watch, onMounted, nextTick, inject } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { aggregateTopicsByTime } from '../composables/useTopicAggregation'

const route = useRoute()
const router = useRouter()
const { channelsData, loading, error, getChannelAnalyses } = inject('channelsData')

const channelAnalysis = ref(null)
const channelAnalysisLoading = ref(false)
const detailAnalysis = ref(null)
const detailOverlayRef = ref(null)
const sortBy = ref('published')

const channelId = computed(() => route.params.id)

const channel = computed(() =>
  channelsData?.value?.find((c) => c.id === channelId.value)
)

const channelAnalyses = computed(() => getChannelAnalyses(channelId.value) ?? [])

const topicsWeek = computed(() =>
  aggregateTopicsByTime(channelAnalyses.value, 7)
)

const topicsMonth = computed(() =>
  aggregateTopicsByTime(channelAnalyses.value, 30)
)

const sortedAnalyses = computed(() => {
  const list = [...channelAnalyses.value]
  if (sortBy.value === 'published') {
    return list.sort((a, b) => {
      const da = a.metadata?.published_at || a.analyzed_at || ''
      const db = b.metadata?.published_at || b.analyzed_at || ''
      return db.localeCompare(da)
    })
  }
  return list.sort((a, b) =>
    (a.metadata?.title || '').localeCompare(b.metadata?.title || '')
  )
})

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

function openDetail(a) {
  detailAnalysis.value = a
  nextTick(() => detailOverlayRef.value?.focus())
}

function closeDetail() {
  detailAnalysis.value = null
}

function onDetailKeydown(e) {
  if (e.key === 'Escape') closeDetail()
}

async function loadChannelAnalysis(id) {
  if (!id) {
    channelAnalysis.value = null
    return
  }
  channelAnalysisLoading.value = true
  channelAnalysis.value = null
  try {
    const r = await fetch(`/analysis/${id}/_channel.json`)
    if (r.ok) {
      channelAnalysis.value = await r.json()
    }
  } catch {
    // ignore
  } finally {
    channelAnalysisLoading.value = false
  }
}

watch(channelId, (id) => loadChannelAnalysis(id || ''))

onMounted(() => loadChannelAnalysis(channelId.value))
</script>

<template>
  <div class="channel-view">
    <div v-if="loading" class="loading">Caricamento...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="!channel" class="empty-state">
      <p class="empty-state-title">Canale non trovato</p>
      <button type="button" class="back-btn" @click="router.push({ name: 'home' })">
        ← Torna alla home
      </button>
    </div>
    <div v-else class="channel-content">
      <button type="button" class="back-btn channel-back" @click="router.push({ name: 'home' })">
        ← Tutti i canali
      </button>

      <section class="channel-banner">
        <div v-if="channelAnalysisLoading" class="channel-analysis-loading">
          Caricamento analisi canale...
        </div>
        <div v-else-if="channelAnalysis" class="channel-banner-grid">
          <div class="channel-banner-block">
            <span class="channel-banner-label">Presentazione</span>
            <p class="channel-banner-text">{{ channelAnalysis.themes?.summary }}</p>
            <div v-if="channelAnalysis.themes?.main_topics?.length" class="channel-banner-tags">
              <span
                v-for="t in channelAnalysis.themes.main_topics"
                :key="t"
                class="channel-tag"
              >
                {{ t }}
              </span>
            </div>
          </div>
        </div>
        <p v-else class="channel-banner-empty">Analisi canale non disponibile</p>
      </section>

      <section class="topics-section">
        <h3 class="topics-section-title">Argomenti — Ultima settimana</h3>
        <div v-if="topicsWeek.length" class="topics-list topics-list-detailed">
          <div v-for="t in topicsWeek" :key="t.name" class="topic-card">
            <div class="topic-card-header">
              <span class="topic-name">{{ t.name }}</span>
              <span class="topic-badges">
                <span class="topic-total">{{ t.count }} video</span>
              </span>
            </div>
            <div v-if="t.channels?.length" class="topic-card-channels">
              <span v-for="ch in t.channels" :key="ch.id" class="topic-channel-tag">
                {{ ch.name }} ({{ ch.videoCount }})
              </span>
            </div>
          </div>
        </div>
        <p v-else class="topics-empty">Nessun video negli ultimi 7 giorni</p>
      </section>

      <section class="topics-section">
        <h3 class="topics-section-title">Argomenti — Ultimo mese</h3>
        <div v-if="topicsMonth.length" class="topics-list topics-list-detailed">
          <div v-for="t in topicsMonth" :key="t.name" class="topic-card">
            <div class="topic-card-header">
              <span class="topic-name">{{ t.name }}</span>
              <span class="topic-badges">
                <span class="topic-total">{{ t.count }} video</span>
              </span>
            </div>
            <div v-if="t.channels?.length" class="topic-card-channels">
              <span v-for="ch in t.channels" :key="ch.id" class="topic-channel-tag">
                {{ ch.name }} ({{ ch.videoCount }})
              </span>
            </div>
          </div>
        </div>
        <p v-else class="topics-empty">Nessun video negli ultimi 30 giorni</p>
      </section>

      <section class="channel-videos-section">
        <div class="channel-videos-header">
          <h3 class="channel-videos-title">Video analizzati</h3>
          <select v-model="sortBy" class="sort-select">
            <option value="published">Più recenti</option>
            <option value="title">A–Z</option>
          </select>
        </div>
        <div class="feed-grid">
          <article
            v-for="a in sortedAnalyses"
            :key="a.video_id"
            class="video-card"
          >
            <a
              :href="`https://www.youtube.com/watch?v=${a.video_id}`"
              target="_blank"
              rel="noopener"
              class="video-card-thumb-link"
            >
              <div class="video-card-thumb">
                <img
                  :src="`https://i.ytimg.com/vi/${a.video_id}/mqdefault.jpg`"
                  :alt="a.metadata?.title || 'Video'"
                  loading="lazy"
                />
                <span class="video-card-badge">▶</span>
              </div>
            </a>
            <div
              class="video-card-body"
              role="button"
              tabindex="0"
              @click="openDetail(a)"
              @keydown.enter="openDetail(a)"
            >
              <h3 class="video-card-title">{{ a.metadata?.title || 'Senza titolo' }}</h3>
              <div class="video-card-meta">
                <span v-if="a.metadata?.published_at" class="video-card-date">
                  {{ formatDate(a.metadata.published_at) }}
                </span>
              </div>
              <p class="video-card-summary">{{ a.summary || '—' }}</p>
              <div v-if="(a.topics || []).length" class="video-card-topics">
                <span
                  v-for="t in (a.topics || []).slice(0, 4)"
                  :key="t.name"
                  class="video-tag"
                  :class="t.relevance"
                >
                  {{ t.name }}
                </span>
              </div>
              <a
                :href="`https://www.youtube.com/watch?v=${a.video_id}`"
                target="_blank"
                rel="noopener"
                class="video-card-yt-link"
                @click.stop
              >
                Apri video
              </a>
            </div>
          </article>
        </div>
      </section>
    </div>

    <Teleport to="body">
      <div
        v-if="detailAnalysis"
        ref="detailOverlayRef"
        class="detail-overlay"
        tabindex="-1"
        role="dialog"
        aria-modal="true"
        aria-label="Dettaglio video"
        @click.self="closeDetail"
        @keydown="onDetailKeydown"
      >
        <div class="detail-modal">
          <button type="button" class="detail-close" aria-label="Chiudi" @click="closeDetail">
            ×
          </button>
          <div class="detail-header">
            <a
              :href="`https://www.youtube.com/watch?v=${detailAnalysis.video_id}`"
              target="_blank"
              rel="noopener"
              class="detail-thumb-link"
            >
              <img
                :src="`https://i.ytimg.com/vi/${detailAnalysis.video_id}/hqdefault.jpg`"
                :alt="detailAnalysis.metadata?.title"
                class="detail-thumb"
              />
              <span class="detail-play-badge">▶</span>
            </a>
            <div class="detail-meta-block">
              <h2 class="detail-title">{{ detailAnalysis.metadata?.title || 'Senza titolo' }}</h2>
              <div class="detail-meta">
                <span v-if="detailAnalysis.metadata?.published_at" class="detail-date">
                  {{ formatDate(detailAnalysis.metadata?.published_at) }}
                </span>
              </div>
              <a
                :href="`https://www.youtube.com/watch?v=${detailAnalysis.video_id}`"
                target="_blank"
                rel="noopener"
                class="detail-yt-btn"
              >
                Guarda su YouTube →
              </a>
            </div>
          </div>
          <div class="detail-body">
            <section v-if="detailAnalysis.summary" class="detail-section">
              <h3 class="detail-section-title">Riepilogo</h3>
              <p class="detail-summary">{{ detailAnalysis.summary }}</p>
            </section>
            <section
              v-if="(detailAnalysis.topics || detailAnalysis.themes || []).length"
              class="detail-section"
            >
              <h3 class="detail-section-title">Temi</h3>
              <div class="detail-topics">
                <span
                  v-for="(t, i) in (detailAnalysis.themes || detailAnalysis.topics || [])"
                  :key="t.theme || t.name || i"
                  class="video-tag"
                  :class="
                    t.relevance ||
                    (t.weight > 20 ? 'high' : t.weight > 10 ? 'medium' : 'low')
                  "
                  :title="t.weight != null ? `${t.weight}%` : ''"
                >
                  {{ t.theme || t.name }}
                </span>
              </div>
            </section>
            <section v-if="(detailAnalysis.claims || []).length" class="detail-section">
              <h3 class="detail-section-title">Top claim</h3>
              <ul class="detail-claims">
                <li
                  v-for="(c, i) in (detailAnalysis.claims || []).slice(0, 12)"
                  :key="i"
                  class="detail-claim"
                  :class="c.polarity || c.stance?.toLowerCase()"
                >
                  <span
                    v-if="c.subject || c.target_entity"
                    class="detail-claim-subject"
                  >
                    {{ c.subject || c.target_entity }}:
                  </span>
                  <span class="detail-claim-position">{{ c.claim_text || c.position }}</span>
                  <template v-if="c.evidence_quotes?.[0]">
                    <a
                      v-if="c.evidence_quotes[0].start_sec != null"
                      :href="`https://www.youtube.com/watch?v=${detailAnalysis.video_id}&t=${Math.floor(c.evidence_quotes[0].start_sec)}s`"
                      target="_blank"
                      rel="noopener"
                      class="detail-claim-timestamp"
                      title="Vai al timestamp"
                    >
                      {{ formatTimestamp(c.evidence_quotes[0].start_sec) }}
                    </a>
                    <span v-else class="detail-claim-quote">
                      «{{
                        c.evidence_quotes[0].quote_text?.slice(0, 80)
                      }}{{
                        (c.evidence_quotes[0].quote_text?.length || 0) > 80 ? '…' : ''
                      }}»
                    </span>
                  </template>
                </li>
              </ul>
            </section>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

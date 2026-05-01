<script setup>
import { inject, computed } from 'vue'
import { useRouter } from 'vue-router'
import { aggregateTopicsByTime } from '../composables/useTopicAggregation'

const { channelsData, loading, error, channelList } = inject('channelsData')

const topicsWeek = computed(() =>
  aggregateTopicsByTime(channelsData?.value?.flatMap((ch) => ch.analyses) ?? [], 7)
)
const topicsMonth = computed(() =>
  aggregateTopicsByTime(channelsData?.value?.flatMap((ch) => ch.analyses) ?? [], 30)
)

const router = useRouter()

</script>

<template>
  <div class="page page--wide">
    <div v-if="loading" class="loading-wrap"><span class="spinner"></span></div>
    <div v-else-if="error" class="empty" style="color:var(--re)">{{ error }}</div>
    <div v-else-if="channelList?.length === 0" class="empty">
      <div class="empty-icon">📭</div>
      <div class="empty-title">Nessuna analisi</div>
      <div class="empty-sub">
        Aggiungi canali in <code>channels/channels.json</code> e esegui <code>npm run run-list</code>.
      </div>
    </div>
    <template v-else>

      <div class="sec-head">
        <span class="sec-label">Canali</span>
      </div>
      <div class="ch-grid">
        <button
          v-for="ch in channelList"
          :key="ch.id"
          type="button"
          class="ch-card"
          @click="router.push({ name: 'channel', params: { id: ch.id } })"
        >
          <span class="ch-name">{{ ch.name }}</span>
          <span class="ch-n">{{ ch.count }}<span class="ch-u"> video</span></span>
        </button>
      </div>

      <div class="sec-head">
        <span class="sec-label">Ultima settimana</span>
      </div>
      <div v-if="topicsWeek.length" class="topics-list">
        <div v-for="t in topicsWeek" :key="t.name" class="topic-row">
          <span class="topic-name">{{ t.name }}</span>
          <span class="topic-counts">
            <span class="chip chip--muted">{{ t.count }} video</span>
            <span class="chip chip--muted">{{ t.channelCount }} {{ t.channelCount === 1 ? 'canale' : 'canali' }}</span>
          </span>
          <div class="topic-channels">
            <span v-for="ch in t.channels" :key="ch.id" class="fc-topic">
              {{ ch.name }} ({{ ch.videoCount }})
            </span>
          </div>
        </div>
      </div>
      <p v-else class="empty" style="padding:1rem 0">Nessun video negli ultimi 7 giorni</p>

      <div class="sec-head">
        <span class="sec-label">Ultimo mese</span>
      </div>
      <div v-if="topicsMonth.length" class="topics-list">
        <div v-for="t in topicsMonth" :key="t.name" class="topic-row">
          <span class="topic-name">{{ t.name }}</span>
          <span class="topic-counts">
            <span class="chip chip--muted">{{ t.count }} video</span>
            <span class="chip chip--muted">{{ t.channelCount }} {{ t.channelCount === 1 ? 'canale' : 'canali' }}</span>
          </span>
          <div class="topic-channels">
            <span v-for="ch in t.channels" :key="ch.id" class="fc-topic">
              {{ ch.name }} ({{ ch.videoCount }})
            </span>
          </div>
        </div>
      </div>
      <p v-else class="empty" style="padding:1rem 0">Nessun video negli ultimi 30 giorni</p>

    </template>
  </div>
</template>

<style scoped>
.topics-list { display: flex; flex-direction: column; gap: 0; margin-bottom: 1.5rem; }
.topic-row { display: flex; align-items: baseline; gap: .5rem; flex-wrap: wrap; padding: .5rem 0; border-bottom: 1px solid var(--line); }
.topic-name { font-family: var(--s); font-size: 1rem; font-weight: 600; flex: 1; min-width: 140px; }
.topic-counts { display: flex; gap: .25rem; flex-wrap: wrap; }
.topic-channels { width: 100%; display: flex; gap: .25rem; flex-wrap: wrap; margin-top: .25rem; }
</style>

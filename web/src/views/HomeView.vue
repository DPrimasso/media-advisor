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
  <div class="home-view">
    <div v-if="loading" class="loading">Caricamento...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="channelList?.length === 0" class="empty-state">
      <p class="empty-state-title">Nessuna analisi</p>
      <p class="empty-state-text">
        Aggiungi canali in <code>channels/channels.json</code> e esegui <code>npm run run-list</code>.
      </p>
    </div>
    <div v-else class="home-content">
      <section class="home-intro">
        <h2 class="home-intro-title">Riepilogo degli argomenti</h2>
        <p class="home-intro-text">
          Argomenti maggiormente trattati dai canali in analisi negli ultimi periodi.
        </p>
      </section>

      <section class="topics-section">
        <h3 class="topics-section-title">Ultima settimana</h3>
        <div v-if="topicsWeek.length" class="topics-list topics-list-detailed">
          <div v-for="t in topicsWeek" :key="t.name" class="topic-card">
            <div class="topic-card-header">
              <span class="topic-name">{{ t.name }}</span>
              <span class="topic-badges">
                <span class="topic-total">{{ t.count }} video</span>
                <span class="topic-channels">{{ t.channelCount }} {{ t.channelCount === 1 ? 'canale' : 'canali' }}</span>
              </span>
            </div>
            <div class="topic-card-channels">
              <span v-for="ch in t.channels" :key="ch.id" class="topic-channel-tag">
                {{ ch.name }} ({{ ch.videoCount }})
              </span>
            </div>
          </div>
        </div>
        <p v-else class="topics-empty">Nessun video negli ultimi 7 giorni</p>
      </section>

      <section class="topics-section">
        <h3 class="topics-section-title">Ultimo mese</h3>
        <div v-if="topicsMonth.length" class="topics-list topics-list-detailed">
          <div v-for="t in topicsMonth" :key="t.name" class="topic-card">
            <div class="topic-card-header">
              <span class="topic-name">{{ t.name }}</span>
              <span class="topic-badges">
                <span class="topic-total">{{ t.count }} video</span>
                <span class="topic-channels">{{ t.channelCount }} {{ t.channelCount === 1 ? 'canale' : 'canali' }}</span>
              </span>
            </div>
            <div class="topic-card-channels">
              <span v-for="ch in t.channels" :key="ch.id" class="topic-channel-tag">
                {{ ch.name }} ({{ ch.videoCount }})
              </span>
            </div>
          </div>
        </div>
        <p v-else class="topics-empty">Nessun video negli ultimi 30 giorni</p>
      </section>

      <section class="channel-links-section">
        <h3 class="channel-links-title">Canali</h3>
        <div class="channel-cards">
          <button
            v-for="ch in channelList"
            :key="ch.id"
            type="button"
            class="channel-card"
            @click="router.push({ name: 'channel', params: { id: ch.id } })"
          >
            <span class="channel-card-name">{{ ch.name }}</span>
            <span class="channel-card-count">{{ ch.count }} video</span>
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

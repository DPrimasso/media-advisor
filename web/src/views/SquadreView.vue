<script setup>
import { inject, computed } from 'vue'
import { useRouter } from 'vue-router'
import { SERIE_A_TEAMS } from '../config/serieA.js'
import { useClaimsFilter } from '../composables/useClaimsFilter.js'

const { channelsData, loading, error } = inject('channelsData')
const { filterByTeam } = useClaimsFilter(channelsData)

const router = useRouter()

const teamCounts = computed(() => {
  const counts = {}
  for (const t of SERIE_A_TEAMS) {
    counts[t.id] = filterByTeam(t.id).length
  }
  return counts
})
</script>

<template>
  <div class="squadre-view">
    <div v-if="loading" class="loading">Caricamento...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else class="squadre-content">
      <button type="button" class="back-btn" @click="router.push('/')">← Indietro</button>
      <h2 class="squadre-title">Squadre Serie A</h2>
      <p class="squadre-intro">Clicca su una squadra per vedere chi ne ha parlato e cosa ha detto</p>
      <div class="squadre-grid">
        <button
          v-for="team in SERIE_A_TEAMS"
          :key="team.id"
          type="button"
          class="squadra-card"
          @click="router.push({ name: 'squadre-team', params: { teamId: team.id } })"
        >
          <span class="squadra-name">{{ team.name }}</span>
          <span class="squadra-count">{{ teamCounts[team.id] || 0 }} claim</span>
        </button>
      </div>
    </div>
  </div>
</template>

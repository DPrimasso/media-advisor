<script setup>
import { inject, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { SERIE_A_TEAMS } from '../config/serieA.js'
import { useClaimsFilter } from '../composables/useClaimsFilter.js'
import ClaimList from '../components/ClaimList.vue'

const route = useRoute()
const router = useRouter()
const { channelsData, loading, error } = inject('channelsData')
const { filterByTeam } = useClaimsFilter(channelsData)

const teamId = computed(() => route.params.teamId)
const team = computed(() => SERIE_A_TEAMS.find((t) => t.id === teamId.value))

const claims = computed(() => {
  if (!teamId.value) return []
  return filterByTeam(teamId.value)
})
</script>

<template>
  <div class="squadre-team-view">
    <div v-if="loading" class="loading">Caricamento...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="!team" class="empty-state">
      <p class="empty-state-title">Squadra non trovata</p>
      <button type="button" class="back-btn" @click="router.push({ name: 'squadre' })">← Squadre</button>
    </div>
    <div v-else class="squadre-team-content">
      <button type="button" class="back-btn" @click="router.push({ name: 'squadre' })">← Squadre</button>
      <h2 class="squadre-team-title">{{ team.name }}</h2>
      <p class="squadre-team-subtitle">{{ claims.length }} claim trovati</p>
      <ClaimList :claims="claims" />
    </div>
  </div>
</template>

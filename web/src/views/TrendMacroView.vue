<script setup>
import { inject, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useClaimsFilter } from '../composables/useClaimsFilter.js'
import { getMacroList } from '../config/macroTrends.js'
import ClaimList from '../components/ClaimList.vue'

const route = useRoute()
const router = useRouter()
const { channelsData, loading, error } = inject('channelsData')
const { enrichedClaims, filterByMacro } = useClaimsFilter(channelsData)

const macroId = computed(() => route.params.macroId)

const macroInfo = computed(() => {
  const list = getMacroList(enrichedClaims.value)
  return list.find((m) => m.id === macroId.value)
})

const claims = computed(() => {
  if (!macroId.value) return []
  return filterByMacro(macroId.value)
})
</script>

<template>
  <div class="trend-macro-view">
    <div v-if="loading" class="loading">Caricamento...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="!macroInfo" class="empty-state">
      <p class="empty-state-title">Trend non trovato</p>
      <button type="button" class="back-btn" @click="router.push({ name: 'trend' })">← Trend</button>
    </div>
    <div v-else class="trend-macro-content">
      <button type="button" class="back-btn" @click="router.push({ name: 'trend' })">← Trend</button>
      <h2 class="trend-macro-title">{{ macroInfo.label }}</h2>
      <p class="trend-macro-subtitle">{{ claims.length }} claim trovati</p>
      <ClaimList :claims="claims" />
    </div>
  </div>
</template>

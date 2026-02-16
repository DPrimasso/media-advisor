<script setup>
import { inject, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useClaimsFilter } from '../composables/useClaimsFilter.js'
import { useMacroTrends } from '../composables/useMacroTrends.js'

const { channelsData, loading, error } = inject('channelsData')
const { enrichedClaims } = useClaimsFilter(channelsData)
const { macroList } = useMacroTrends(enrichedClaims)

const router = useRouter()
</script>

<template>
  <div class="trend-view">
    <div v-if="loading" class="loading">Caricamento...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else class="trend-content">
      <button type="button" class="back-btn" @click="router.push('/')">← Indietro</button>
      <h2 class="trend-title">Trend</h2>
      <p class="trend-intro">Clicca su un trend per vedere chi ne ha parlato e cosa ha detto</p>
      <div class="trend-macros">
        <button
          v-for="m in macroList"
          :key="m.id"
          type="button"
          class="trend-macro-card"
          @click="router.push({ name: 'trend-macro', params: { macroId: m.id } })"
        >
          <span class="trend-macro-label">{{ m.label }}</span>
          <span class="trend-macro-count">{{ m.count }} claim</span>
        </button>
      </div>
      <p v-if="!macroList.length" class="topics-empty">Nessun trend trovato</p>
    </div>
  </div>
</template>

<script setup>
import { inject, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const { channelsData, loading, error } = inject('channelsData')

const channelId = computed(() => route.params.id)
const channel = computed(() => channelsData?.value?.find((c) => c.id === channelId.value))
const advisor = computed(() => channel.value?.advisor || null)

const metricCards = computed(() => {
  if (!advisor.value?.scores) return []
  const s = advisor.value.scores
  return [
    { key: 'evidence_coverage', label: 'Evidence coverage', value: s.evidence_coverage, hint: 'Claim con quote verificabile' },
    { key: 'evidence_fidelity', label: 'Evidence fidelity', value: s.evidence_fidelity, hint: 'Claim supportati o riparati dal validator' },
    { key: 'coherence_score', label: 'Coerenza', value: s.coherence_score, hint: 'Penalizza contraddizioni HARD/SOFT/DRIFT' },
    { key: 'specificity_score', label: 'Specificità', value: s.specificity_score, hint: 'Claim concreti, poco vaghi' },
    { key: 'prediction_accountability', label: 'Predizioni', value: s.prediction_accountability, hint: 'Tracking previsioni (fase iniziale)' },
    { key: 'bias_concentration', label: 'Bias concentration', value: 100 - s.bias_concentration, hint: '100 = meno sbilanciato' },
    { key: 'absolutism_rate', label: 'Linguaggio assoluto', value: 100 - s.absolutism_rate, hint: '100 = meno “sempre/mai”' },
    { key: 'topic_diversity', label: 'Topic diversity', value: s.topic_diversity, hint: 'Varietà dei temi trattati' }
  ]
})

function formatPct(v) {
  if (v == null || isNaN(v)) return '—'
  return `${Math.round(v)}%`
}

function formatDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('it-IT', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function scoreToneClass(score) {
  const n = Number(score) || 0
  if (n >= 75) return 'good'
  if (n >= 55) return 'mid'
  return 'low'
}
</script>

<template>
  <div class="advisor-view">
    <div v-if="loading" class="loading">Caricamento advisor...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="!channel" class="empty-state">
      <p class="empty-state-title">Canale non trovato</p>
      <button type="button" class="back-btn" @click="router.push({ name: 'home' })">
        ← Torna alla home
      </button>
    </div>
    <div v-else-if="!advisor" class="empty-state">
      <p class="empty-state-title">Advisor non ancora disponibile</p>
      <p class="empty-state-text">
        Esegui pipeline + prepare-public per generare <code>_advisor.json</code>.
      </p>
      <button type="button" class="back-btn" @click="router.push({ name: 'channel', params: { id: channel.id } })">
        ← Torna al canale
      </button>
    </div>
    <div v-else class="advisor-content">
      <button type="button" class="back-btn" @click="router.push({ name: 'channel', params: { id: channel.id } })">
        ← Torna al canale
      </button>

      <section class="advisor-hero">
        <div class="advisor-hero-copy">
          <h2 class="advisor-title">{{ channel.name }} · Creator Advisor</h2>
          <p class="advisor-subtitle">
            Ultimo aggiornamento: {{ formatDateTime(advisor.generated_at) }} ·
            {{ advisor.videos_analyzed }} video · {{ advisor.claims_analyzed }} claim
          </p>
        </div>
        <div class="advisor-score-pill" :class="scoreToneClass(advisor.scores?.advisor_score)">
          {{ Math.round(advisor.scores?.advisor_score || 0) }}/100
        </div>
      </section>

      <section class="advisor-score-grid">
        <article v-for="metric in metricCards" :key="metric.key" class="advisor-score-card">
          <span class="advisor-score-label">{{ metric.label }}</span>
          <strong class="advisor-score-value">{{ formatPct(metric.value) }}</strong>
          <span class="advisor-score-hint">{{ metric.hint }}</span>
        </article>
      </section>

      <section class="advisor-formula">
        <h3 class="topics-section-title">Formula score</h3>
        <p>
          Advisor = 20% coverage + 20% fidelity + 20% coerenza + 15% specificità + 10% predizioni + 10% (100-bias) + 5% (100-assolutismo)
        </p>
      </section>

      <section class="advisor-panels">
        <article class="advisor-panel">
          <h3 class="topics-section-title">Coerenza</h3>
          <ul class="advisor-kv-list">
            <li><span>Eventi totali</span><strong>{{ advisor.breakdown?.inconsistencies?.total ?? 0 }}</strong></li>
            <li><span>HARD</span><strong>{{ advisor.breakdown?.inconsistencies?.hard ?? 0 }}</strong></li>
            <li><span>SOFT</span><strong>{{ advisor.breakdown?.inconsistencies?.soft ?? 0 }}</strong></li>
            <li><span>DRIFT</span><strong>{{ advisor.breakdown?.inconsistencies?.drift ?? 0 }}</strong></li>
            <li><span>NOT (solo informativo)</span><strong>{{ advisor.breakdown?.inconsistencies?.not ?? 0 }}</strong></li>
          </ul>
        </article>

        <article class="advisor-panel">
          <h3 class="topics-section-title">Predizioni</h3>
          <ul class="advisor-kv-list">
            <li><span>Totali</span><strong>{{ advisor.breakdown?.predictions?.total ?? 0 }}</strong></li>
            <li><span>Open</span><strong>{{ advisor.breakdown?.predictions?.open ?? 0 }}</strong></li>
            <li><span>Resolved</span><strong>{{ advisor.breakdown?.predictions?.resolved ?? 0 }}</strong></li>
            <li><span>Hit</span><strong>{{ advisor.breakdown?.predictions?.hit ?? 0 }}</strong></li>
            <li><span>Miss</span><strong>{{ advisor.breakdown?.predictions?.miss ?? 0 }}</strong></li>
          </ul>
        </article>
      </section>

      <section class="advisor-panels">
        <article class="advisor-panel">
          <h3 class="topics-section-title">Entità più citate</h3>
          <div class="advisor-rows">
            <div v-for="e in (advisor.breakdown?.top_entities || []).slice(0, 10)" :key="e.entity" class="advisor-row">
              <span>{{ e.entity }}</span>
              <span class="advisor-row-meta">
                {{ e.total }} claim · +{{ e.positive }}/-{{ e.negative }}/={{ e.neutral }}
              </span>
            </div>
          </div>
        </article>

        <article class="advisor-panel">
          <h3 class="topics-section-title">Top topic</h3>
          <div class="advisor-tags">
            <span v-for="t in (advisor.breakdown?.top_topics || []).slice(0, 14)" :key="t.topic" class="channel-tag">
              {{ t.topic }} ({{ t.total }})
            </span>
          </div>
        </article>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  evaluation: { type: Object, default: null },
  compact: { type: Boolean, default: false }
})

const scores = computed(() => {
  if (!props.evaluation) return []
  const e = props.evaluation
  return [
    { key: 'overall', label: 'Credibilit\u00e0', value: e.overall_credibility, icon: '\u2605' },
    { key: 'factuality', label: 'Fattualit\u00e0', value: e.factuality_index, icon: '\u2713' },
    { key: 'objectivity', label: 'Oggettivit\u00e0', value: e.objectivity_index, icon: '\u2696' },
    { key: 'argumentation', label: 'Argomentazione', value: e.argumentation_quality, icon: '\u2742' },
    { key: 'density', label: 'Densit\u00e0 info', value: e.information_density, icon: '\u25A3' },
    { key: 'sources', label: 'Fonti citate', value: e.source_reliability, icon: '\u2709' },
    { key: 'sensationalism', label: 'Sensazionalismo', value: e.sensationalism_index, icon: '\u26A0', inverted: true },
  ]
})

function scoreColor(value, inverted) {
  const v = inverted ? 100 - value : value
  if (v >= 70) return 'score-high'
  if (v >= 40) return 'score-mid'
  return 'score-low'
}

function scoreLabel(value) {
  if (value >= 80) return 'Ottimo'
  if (value >= 60) return 'Buono'
  if (value >= 40) return 'Sufficiente'
  if (value >= 20) return 'Basso'
  return 'Molto basso'
}
</script>

<template>
  <div v-if="evaluation" class="eval-scores" :class="{ compact }">
    <div class="eval-scores-grid">
      <div
        v-for="s in scores"
        :key="s.key"
        class="eval-score-item"
        :class="scoreColor(s.value, s.inverted)"
      >
        <div class="eval-score-header">
          <span class="eval-score-icon">{{ s.icon }}</span>
          <span class="eval-score-label">{{ s.label }}</span>
          <span class="eval-score-value">{{ s.value }}</span>
        </div>
        <div class="eval-score-bar-track">
          <div
            class="eval-score-bar-fill"
            :style="{ width: s.value + '%' }"
          />
        </div>
        <span v-if="!compact" class="eval-score-level">
          {{ s.inverted ? (s.value <= 30 ? 'Sobrio' : s.value <= 60 ? 'Moderato' : 'Alto') : scoreLabel(s.value) }}
        </span>
      </div>
    </div>

    <div v-if="!compact && evaluation.emotional_tone?.length" class="eval-section">
      <h4 class="eval-section-title">Registro emotivo</h4>
      <div class="eval-tags">
        <span v-for="t in evaluation.emotional_tone" :key="t" class="eval-tag tone-tag">
          {{ t }}
        </span>
      </div>
    </div>

    <div v-if="!compact && evaluation.rhetorical_techniques?.length" class="eval-section">
      <h4 class="eval-section-title">Tecniche retoriche rilevate</h4>
      <div class="eval-techniques">
        <div v-for="(tech, i) in evaluation.rhetorical_techniques" :key="i" class="eval-technique">
          <div class="eval-technique-header">
            <span class="eval-technique-name">{{ tech.technique }}</span>
            <span class="eval-technique-freq" :class="'freq-' + tech.frequency">
              {{ tech.frequency === 'high' ? 'Frequente' : tech.frequency === 'medium' ? 'Moderata' : 'Rara' }}
            </span>
          </div>
          <p v-if="tech.example" class="eval-technique-example">\u00AB{{ tech.example }}\u00BB</p>
        </div>
      </div>
    </div>

    <div v-if="!compact && evaluation.content_type_breakdown" class="eval-section">
      <h4 class="eval-section-title">Composizione del contenuto</h4>
      <div class="eval-breakdown">
        <div class="eval-breakdown-bar">
          <div
            class="eval-bd-facts"
            :style="{ width: evaluation.content_type_breakdown.facts_pct + '%' }"
            :title="'Fatti: ' + evaluation.content_type_breakdown.facts_pct + '%'"
          />
          <div
            class="eval-bd-opinions"
            :style="{ width: evaluation.content_type_breakdown.opinions_pct + '%' }"
            :title="'Opinioni: ' + evaluation.content_type_breakdown.opinions_pct + '%'"
          />
          <div
            class="eval-bd-predictions"
            :style="{ width: evaluation.content_type_breakdown.predictions_pct + '%' }"
            :title="'Previsioni: ' + evaluation.content_type_breakdown.predictions_pct + '%'"
          />
          <div
            class="eval-bd-prescriptions"
            :style="{ width: evaluation.content_type_breakdown.prescriptions_pct + '%' }"
            :title="'Prescrizioni: ' + evaluation.content_type_breakdown.prescriptions_pct + '%'"
          />
        </div>
        <div class="eval-breakdown-legend">
          <span class="eval-bd-legend-item"><span class="eval-bd-dot eval-bd-facts" /> Fatti {{ evaluation.content_type_breakdown.facts_pct }}%</span>
          <span class="eval-bd-legend-item"><span class="eval-bd-dot eval-bd-opinions" /> Opinioni {{ evaluation.content_type_breakdown.opinions_pct }}%</span>
          <span class="eval-bd-legend-item"><span class="eval-bd-dot eval-bd-predictions" /> Previsioni {{ evaluation.content_type_breakdown.predictions_pct }}%</span>
          <span class="eval-bd-legend-item"><span class="eval-bd-dot eval-bd-prescriptions" /> Prescrizioni {{ evaluation.content_type_breakdown.prescriptions_pct }}%</span>
        </div>
      </div>
    </div>

    <div v-if="!compact && (evaluation.key_strengths?.length || evaluation.key_weaknesses?.length)" class="eval-section eval-strengths-weaknesses">
      <div v-if="evaluation.key_strengths?.length" class="eval-sw-col">
        <h4 class="eval-section-title eval-sw-title strengths">Punti di forza</h4>
        <ul class="eval-sw-list">
          <li v-for="s in evaluation.key_strengths" :key="s">{{ s }}</li>
        </ul>
      </div>
      <div v-if="evaluation.key_weaknesses?.length" class="eval-sw-col">
        <h4 class="eval-section-title eval-sw-title weaknesses">Punti deboli</h4>
        <ul class="eval-sw-list">
          <li v-for="w in evaluation.key_weaknesses" :key="w">{{ w }}</li>
        </ul>
      </div>
    </div>
  </div>
</template>

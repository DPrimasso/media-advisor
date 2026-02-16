const DIMENSION_LABELS = {
  injury: 'Infortuni',
  injuries: 'Infortuni',
  infortuni: 'Infortuni',
  market: 'Mercato',
  mercato: 'Mercato',
  transfers: 'Mercato',
  performance: 'Prestazioni',
  tactics: 'Tattica',
  refereeing: 'Arbitri e VAR',
  leadership: 'Leadership',
  standings: 'Classifica',
  europe: 'Europa',
  rivalry: 'Rivalità',
  finance: 'Finanza',
  media: 'Comunicazione',
  lineup_prediction: 'Formazione',
  fan_behavior: 'Tifosi',
}

function normalizeEntity(s) {
  return (s || '').toString().toLowerCase().trim().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')
}

/**
 * @param {Array} enrichedClaims - claim arricchiti con metadata
 * @returns {Array<{id: string, label: string, count: number}>}
 */
export function getMacroList(enrichedClaims) {
  if (!enrichedClaims?.length) return []

  const macroMap = new Map()

  for (const c of enrichedClaims) {
    const dim = (c.dimension || c.topic || '').toString().toLowerCase().trim()
    const entity = (c.target_entity || c.subject || '').toString().trim()
    const label = DIMENSION_LABELS[dim] || (dim ? dim.charAt(0).toUpperCase() + dim.slice(1) : 'Altro')

    const entityNorm = normalizeEntity(entity)
    if (!entityNorm || /^(mercato|media|opinione|generale|altre?|situazioni)$/.test(entityNorm)) continue

    const macroId = `${dim || 'other'}-${entityNorm}`
    const displayLabel = entity ? `${label} ${entity}` : label

    if (!macroMap.has(macroId)) {
      macroMap.set(macroId, { id: macroId, label: displayLabel, count: 0 })
    }
    macroMap.get(macroId).count++
  }

  return Array.from(macroMap.values())
    .sort((a, b) => b.count - a.count)
}

/**
 * @param {string} macroId - formato "dimension-entity" (es. injury-napoli)
 */
export function parseMacroId(macroId) {
  if (!macroId) return { dimension: '', entity: '' }
  const idx = macroId.indexOf('-')
  if (idx < 0) return { dimension: macroId, entity: '' }
  return {
    dimension: macroId.slice(0, idx),
    entity: macroId.slice(idx + 1).replace(/-/g, ' ')
  }
}

export { DIMENSION_LABELS }

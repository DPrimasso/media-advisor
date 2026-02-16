import { computed } from 'vue'
import { SERIE_A_TEAMS, TEAM_ROSTER } from '../config/serieA.js'
import { parseMacroId } from '../config/macroTrends.js'

function normalizeForMatch(s) {
  return (s || '').toString().toLowerCase().trim()
}

function enrichClaims(channelsData) {
  if (!channelsData?.length) return []
  const enriched = []
  for (const ch of channelsData) {
    for (const a of ch.analyses || []) {
      const meta = { channel_id: ch.id, channel_name: ch.name, video_id: a.video_id, metadata: a.metadata }
      for (const c of a.claims || []) {
        enriched.push({ ...c, ...meta })
      }
    }
  }
  return enriched
}

function matchTeam(claim, teamId, teamName) {
  const entity = normalizeForMatch(claim.target_entity || claim.subject || '')
  const text = normalizeForMatch(claim.claim_text || '')
  const tags = (claim.tags || []).map(normalizeForMatch)
  const teamLower = normalizeForMatch(teamName)

  if (entity === teamLower || entity.includes(teamLower) || teamLower.includes(entity)) return true
  if (text.includes(teamLower)) return true
  if (tags.some((t) => t.includes(teamLower))) return true

  const roster = TEAM_ROSTER[teamId]
  if (roster) {
    const all = [...(roster.players || []), ...(roster.coaches || [])]
    for (const r of all) {
      if (entity.includes(normalizeForMatch(r)) || normalizeForMatch(r).includes(entity)) return true
    }
  }
  return false
}

function matchMacro(claim, macroId) {
  const { dimension, entity } = parseMacroId(macroId)
  const claimDim = normalizeForMatch(claim.dimension || claim.topic || '')
  const claimEntity = normalizeForMatch(claim.target_entity || claim.subject || '').replace(/\s+/g, ' ')

  if (dimension && claimDim !== dimension) return false
  if (entity) {
    const entityNorm = entity.replace(/-/g, ' ')
    if (!claimEntity.includes(entityNorm) && !entityNorm.includes(claimEntity)) return false
  }
  return true
}

/**
 * @param {import('vue').Ref} channelsDataRef - ref a channelsData
 */
export function useClaimsFilter(channelsDataRef) {
  const enrichedClaims = computed(() =>
    enrichClaims(channelsDataRef?.value ?? channelsDataRef ?? [])
  )

  function filterByTeam(teamId) {
    const team = SERIE_A_TEAMS.find((t) => t.id === teamId)
    if (!team) return []
    return enrichedClaims.value
      .filter((c) => matchTeam(c, teamId, team.name))
      .sort((a, b) => {
        const da = a.metadata?.published_at || a.analyzed_at || ''
        const db = b.metadata?.published_at || b.analyzed_at || ''
        return (db || '').localeCompare(da || '')
      })
  }

  function filterByMacro(macroId) {
    return enrichedClaims.value
      .filter((c) => matchMacro(c, macroId))
      .sort((a, b) => {
        const da = a.metadata?.published_at || a.analyzed_at || ''
        const db = b.metadata?.published_at || b.analyzed_at || ''
        return (db || '').localeCompare(da || '')
      })
  }

  function getTeamClaimCounts() {
    const counts = {}
    for (const t of SERIE_A_TEAMS) {
      counts[t.id] = filterByTeam(t.id).length
    }
    return counts
  }

  return {
    enrichedClaims,
    filterByTeam,
    filterByMacro,
    getTeamClaimCounts
  }
}

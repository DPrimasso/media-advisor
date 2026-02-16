import { computed } from 'vue'

const TOP_N = 20

// Dimensioni che generano TREND concreti (non meta/categorie)
// injury, market = temi caldi. media, performance = troppi generici.
const TREND_DIMENSIONS = new Set(['injury', 'injuries', 'infortuni', 'market', 'mercato', 'transfers'])

// Soggetti da escludere (meta, generici)
const SKIP_SUBJECTS = /^(mercato|media|opinione|generale|altre?|situazioni|opinionista|interpretazione|comunicazione|informazioni)$/i

// Topic/categorie da NON includere come trend (sono tassonomie, non trend)
const SKIP_TOPICS = /^(media|opinionista|interpretazione|comunicazione|situazione|opinione|prestazioni generali|match performance|individual performance|information reliability)$/i

function normalizeKey(s) {
  return (s || '').toString().toLowerCase().trim().replace(/\s+/g, ' ')
}

function capitalize(s) {
  if (!s) return ''
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase()
}

/**
 * Estrae TREND (chi/cosa si sta discutendo), non categorie.
 * Es: "Di Lorenzo", "Napoli", "Partita Napoli-Roma", "Infortuni Napoli", "Stadio Maradona"
 */
export function aggregateTopicsByTime(analyses, days) {
  if (!analyses?.length) return []

  const cutoff = new Date()
  cutoff.setDate(cutoff.getDate() - days)

  const filtered = analyses.filter((a) => {
    const pub = a.metadata?.published_at || a.analyzed_at
    if (!pub) return false
    const d = new Date(pub)
    return !isNaN(d.getTime()) && d >= cutoff
  })

  const topicData = new Map()

  function addTopic(displayName, channelId, channelName, videoId) {
    const key = normalizeKey(displayName)
    if (!key || key.length < 2) return
    if (SKIP_TOPICS.test(key)) return

    if (!topicData.has(key)) {
      topicData.set(key, { name: displayName, channelVideos: new Map() })
    }
    const data = topicData.get(key)
    if (!data.channelVideos.has(channelId)) {
      data.channelVideos.set(channelId, { name: channelName, videoIds: new Set() })
    }
    data.channelVideos.get(channelId).videoIds.add(videoId)
  }

  const trendLabels = { injury: 'Infortuni', injuries: 'Infortuni', infortuni: 'Infortuni', market: 'Mercato', mercato: 'Mercato', transfers: 'Mercato' }

  for (const a of filtered) {
    const channelId = a.channel_id || 'unknown'
    const channelName = a.channel_name || channelId
    const videoId = a.video_id || ''
    const title = (a.metadata?.title || '').toString()

    // 1. ENTITÀ dai claims — chi/cosa si discute (trend principale)
    const claims = a.claims || []
    const seenSubjects = new Set()
    for (const c of claims) {
      const subject = (c.subject || c.target_entity || '').toString().trim()
      if (!subject || SKIP_SUBJECTS.test(subject)) continue

      const dim = (c.topic || c.dimension || '').toString().toLowerCase().trim()
      const key = normalizeKey(subject)
      if (seenSubjects.has(key)) continue
      seenSubjects.add(key)

      // Trend = entità (Di Lorenzo, Napoli, Conte)
      addTopic(subject, channelId, channelName, videoId)

      // Trend = entità + tema SOLO se tema è concreto (infortuni, mercato)
      if (TREND_DIMENSIONS.has(dim)) {
        const label = trendLabels[dim] || 'Infortuni'
        addTopic(`${label} ${subject}`, channelId, channelName, videoId)
      }
    }

    // 2. Da TITOLO — eventi e casi (partite, casi, stadio)
    const matchPattern = /\b(napoli|roma|inter|milan|juve|juventus|lazio|atalanta|fiorentina|como|torino|bologna|genoa|lecce|udinese|cagliari|empoli|verona|sassuolo|monza)\s*[-–vV]\s*(napoli|roma|inter|milan|juve|juventus|lazio|atalanta|fiorentina|como|torino|bologna|genoa|lecce|udinese|cagliari|empoli|verona|sassuolo|monza)\b/i
    const matchM = title.match(matchPattern)
    if (matchM) {
      const parts = matchM[0].split(/\s*[-–vV]\s*/i)
      if (parts.length >= 2) {
        addTopic(`Partita ${capitalize(parts[0].trim())} - ${capitalize(parts[1].trim())}`, channelId, channelName, videoId)
      }
    }

    const casoM = title.match(/(?:caso|verità\s+su|episodio)\s+([\w\s'-]+?)(?:\s+balle|!|\.|$|,)/i)
    if (casoM && casoM[1] && casoM[1].trim().length >= 3) {
      addTopic(`Caso ${casoM[1].trim()}`, channelId, channelName, videoId)
    }

    // Stadio, nomi propri nel titolo
    if (/\bstadio\s+maradona\b/i.test(title)) addTopic('Stadio Maradona', channelId, channelName, videoId)

    // 3. Da TOPICS — solo eventi concreti (partita X-Y, stadio, ristrutturazione)
    const topics = a.topics || a.themes || []
    const seenT = new Set()
    for (const t of topics) {
      const raw = (t.name || t.theme || '').toString().trim()
      if (!raw) continue
      const key = normalizeKey(raw)
      if (seenT.has(key)) continue
      if (SKIP_TOPICS.test(key)) continue

      const isEvent = /partita\s|stadio\s|derby|ristrutturazione|napoli\s|inter\s|roma\s|maradona/i.test(raw) || raw.includes('-') || raw.includes(' vs ')
      if (isEvent && raw.split(/\s+/).length >= 2) {
        seenT.add(key)
        addTopic(raw, channelId, channelName, videoId)
      }
    }
  }

  return Array.from(topicData.values())
    .map((data) => {
      const channels = []
      let totalVideos = 0
      for (const [cid, info] of data.channelVideos) {
        const videoCount = info.videoIds.size
        totalVideos += videoCount
        channels.push({ id: cid, name: info.name, videoCount })
      }
      channels.sort((a, b) => b.videoCount - a.videoCount)
      return { name: data.name, count: totalVideos, channelCount: channels.length, channels }
    })
    .sort((a, b) => b.count - a.count)
    .slice(0, TOP_N)
}

export function useTopicAggregation(analysesRef, days) {
  return computed(() => aggregateTopicsByTime(analysesRef?.value ?? analysesRef ?? [], days))
}

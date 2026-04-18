import { computed } from 'vue'

function startOfDay(d) {
  const c = new Date(d)
  c.setHours(0, 0, 0, 0)
  return c
}

function daysDiff(a, b) {
  return Math.round((a - b) / 86400000)
}

function toDayKey(dateObj) {
  const y = dateObj.getFullYear()
  const m = String(dateObj.getMonth() + 1).padStart(2, '0')
  const d = String(dateObj.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function hasSyntheticMentionedAt(tip) {
  if (!tip?.mentioned_at || !tip?.extracted_at) return false
  const mentioned = new Date(tip.mentioned_at)
  const extracted = new Date(tip.extracted_at)
  if (Number.isNaN(mentioned.getTime()) || Number.isNaN(extracted.getTime())) return false
  // Quando coincide al millisecondo è quasi certamente un fallback (no data reale del video).
  return mentioned.getTime() === extracted.getTime()
}

function italianDayLabel(dateObj) {
  const today = startOfDay(new Date())
  const d = startOfDay(dateObj)
  const diff = daysDiff(today, d)
  if (diff === 0) return 'Oggi'
  if (diff === 1) return 'Ieri'
  const raw = dateObj.toLocaleDateString('it-IT', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })
  return raw.replace(/\b\w/g, (c) => c.toUpperCase())
}

export function useFeed(tipsRef, channelsDataRef) {
  const feedDays = computed(() => {
    const tips = tipsRef.value || []
    const channelsData = channelsDataRef.value || []

    // Ultimi 7 giorni reali in timezone locale: oggi + 6 giorni precedenti.
    const cutoff = startOfDay(new Date())
    cutoff.setDate(cutoff.getDate() - 6)

    // 1. Flatten analyses
    const allAnalyses = channelsData
      .flatMap((ch) => ch.analyses || [])
      .filter((a) => a.metadata?.published_at)
      .map((a) => ({
        type: 'analysis',
        date: new Date(a.metadata.published_at),
        ...a,
      }))
      .filter((a) => !isNaN(a.date) && startOfDay(a.date) >= cutoff)

    // 2. Filter tips (must have mentioned_at; beyond 7 days only resolved)
    const visibleTips = tips
      .filter((t) => t.mentioned_at)
      .filter((t) => !hasSyntheticMentionedAt(t))
      .filter((t) => {
        const d = startOfDay(new Date(t.mentioned_at))
        return d >= cutoff || t.outcome !== 'non_verificata'
      })
      .map((t) => ({
        type: 'tip',
        date: new Date(t.mentioned_at),
        ...t,
      }))
      .filter((t) => !isNaN(t.date))

    // 3. Merge + sort descending
    const all = [...visibleTips, ...allAnalyses].sort((a, b) => b.date - a.date)

    // 4. Group by UTC date
    const groups = []
    for (const item of all) {
      const key = toDayKey(item.date)
      let group = groups.find((g) => g.key === key)
      if (!group) {
        group = { key, label: italianDayLabel(item.date), items: [] }
        groups.push(group)
      }
      group.items.push(item)
    }

    return groups
  })

  const isEmpty = computed(() => feedDays.value.length === 0)

  return { feedDays, isEmpty }
}

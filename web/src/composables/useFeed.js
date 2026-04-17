import { computed } from 'vue'

function startOfDay(d) {
  const c = new Date(d)
  c.setUTCHours(0, 0, 0, 0)
  return c
}

function daysDiff(a, b) {
  return Math.round((a - b) / 86400000)
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

    const cutoff = new Date()
    cutoff.setUTCDate(cutoff.getUTCDate() - 7)

    // 1. Flatten analyses
    const allAnalyses = channelsData
      .flatMap((ch) => ch.analyses || [])
      .filter((a) => a.metadata?.published_at)
      .map((a) => ({
        type: 'analysis',
        date: new Date(a.metadata.published_at),
        ...a,
      }))
      .filter((a) => !isNaN(a.date))

    // 2. Filter tips (must have mentioned_at; beyond 7 days only resolved)
    const visibleTips = tips
      .filter((t) => t.mentioned_at)
      .filter((t) => {
        const d = new Date(t.mentioned_at)
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
      const key = item.date.toISOString().slice(0, 10)
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

import { ref, computed, onMounted } from 'vue'

export function useChannelsData() {
  const channelsData = ref([])
  const loading = ref(true)
  const error = ref(null)

  async function loadAnalyses() {
    loading.value = true
    error.value = null
    try {
      const r = await fetch('/analysis/index.json')
      if (!r.ok) throw new Error('Failed to load index')
      const index = await r.json()
      if (!Array.isArray(index) || index.length === 0) {
        channelsData.value = []
        return
      }

      const channels = []
      for (const ch of index) {
        const analyses = []
        let advisor = null
        for (const file of ch.videos || []) {
          const res = await fetch(`/analysis/${ch.id}/${file}`)
          if (!res.ok) continue
          const data = await res.json()
          analyses.push({ ...data, channel_id: ch.id, channel_name: ch.name })
        }
        if (ch.advisor) {
          const advisorRes = await fetch(`/analysis/${ch.id}/${ch.advisor}`)
          if (advisorRes.ok) advisor = await advisorRes.json()
        }
        if (analyses.length > 0) {
          channels.push({
            id: ch.id,
            name: ch.name,
            order: ch.order ?? 999,
            analyses,
            channel_analysis: ch.channel_analysis || null,
            advisor
          })
        }
      }
      channels.sort((a, b) => a.order - b.order)
      channelsData.value = channels
    } catch (e) {
      error.value = e.message
      channelsData.value = []
    } finally {
      loading.value = false
    }
  }

  const channelList = computed(() =>
    channelsData.value.map((ch) => ({ id: ch.id, name: ch.name, count: ch.analyses.length }))
  )

  const allAnalyses = computed(() =>
    channelsData.value.flatMap((ch) => ch.analyses)
  )

  function getChannelAnalyses(channelId) {
    const ch = channelsData.value.find((c) => c.id === channelId)
    return ch ? ch.analyses : []
  }

  onMounted(loadAnalyses)

  return {
    channelsData,
    loading,
    error,
    channelList,
    allAnalyses,
    getChannelAnalyses,
    loadAnalyses
  }
}

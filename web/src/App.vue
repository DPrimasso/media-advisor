<script setup>
import { useChannelsData } from './composables/useChannelsData'
import { ref, computed, onMounted, provide } from 'vue'

const channelsContext = useChannelsData()
provide('channelsData', channelsContext)

const { channelsData, channelList } = channelsContext
const theme = ref('light')

const totalCount = computed(
  () => channelsData.value?.reduce((sum, ch) => sum + ch.analyses.length, 0) ?? 0
)

function initTheme() {
  const stored = localStorage.getItem('media-advisor-theme')
  const prefersDark = matchMedia('(prefers-color-scheme: dark)').matches
  theme.value = stored ?? (prefersDark ? 'dark' : 'light')
  document.documentElement.setAttribute('data-theme', theme.value)
}

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  localStorage.setItem('media-advisor-theme', theme.value)
  document.documentElement.setAttribute('data-theme', theme.value)
}

onMounted(initTheme)
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="topbar-inner">
        <router-link to="/" class="logo-link">
          <h1 class="logo">Media Advisor</h1>
        </router-link>
        <div class="channel-pills">
          <router-link
            to="/"
            class="pill"
            :class="{ active: $route.path === '/' }"
          >
            Tutti
            <span v-if="totalCount" class="pill-badge">{{ totalCount }}</span>
          </router-link>
          <router-link
            to="/squadre"
            class="pill"
            :class="{ active: $route.path.startsWith('/squadre') }"
          >
            Squadre
          </router-link>
          <router-link
            to="/trend"
            class="pill"
            :class="{ active: $route.path.startsWith('/trend') }"
          >
            Trend
          </router-link>
          <router-link
            to="/inbox"
            class="pill"
            :class="{ active: $route.path === '/inbox' }"
          >
            Inbox
          </router-link>
          <router-link
            v-for="ch in channelList"
            :key="ch.id"
            :to="{ name: 'channel', params: { id: ch.id } }"
            class="pill"
            :class="{ active: $route.params.id === ch.id }"
          >
            {{ ch.name }}
            <span class="pill-badge">{{ ch.count }}</span>
          </router-link>
        </div>
        <div class="topbar-right">
          <button
            type="button"
            class="theme-toggle"
            :title="theme === 'light' ? 'Modalità scura' : 'Modalità chiara'"
            @click="toggleTheme"
          >
            <span v-if="theme === 'light'" class="theme-icon">☀</span>
            <span v-else class="theme-icon">☽</span>
          </button>
        </div>
      </div>
    </header>

    <main class="feed">
      <router-view />
    </main>
  </div>
</template>

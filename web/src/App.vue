<script setup>
import { useChannelsData } from './composables/useChannelsData'
import { ref, onMounted, provide } from 'vue'

const channelsContext = useChannelsData()
provide('channelsData', channelsContext)

const theme = ref('light')

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

onMounted(() => {
  initTheme()
})
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="topbar-inner">
        <router-link to="/mercato" class="logo-link">
          <h1 class="logo">Media Advisor</h1>
        </router-link>
        <div class="channel-pills">
          <router-link
            to="/mercato"
            class="pill"
            :class="{ active: $route.path.startsWith('/mercato') }"
          >
            Mercato
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

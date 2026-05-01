<script setup>
import { useChannelsData } from './composables/useChannelsData'
import { ref, onMounted, provide } from 'vue'

const channelsContext = useChannelsData()
provide('channelsData', channelsContext)

const theme = ref('dark')

const formattedToday = new Date().toLocaleDateString('it-IT', {
  day: 'numeric', month: 'long', year: 'numeric',
})

function initTheme() {
  const stored = localStorage.getItem('media-advisor-theme')
  theme.value = stored ?? 'dark'
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
      <router-link to="/rassegna" class="topbar-brand">
        Media<em> Advisor</em>
      </router-link>

      <nav class="topbar-nav">
        <router-link
          to="/rassegna"
          class="nav-item"
          :class="{ active: $route.path === '/rassegna' }"
        >
          Rassegna
        </router-link>
        <router-link
          to="/canali"
          class="nav-item"
          :class="{ active: $route.path === '/canali' }"
        >
          Analisi video
        </router-link>
        <router-link
          to="/mercato"
          class="nav-item"
          :class="{ active: $route.path.startsWith('/mercato') }"
        >
          Mercato
        </router-link>
      </nav>

      <div class="topbar-right">
        <span class="topbar-date">{{ formattedToday }}</span>
        <button
          type="button"
          class="theme-btn"
          :title="theme === 'light' ? 'Modalità scura' : 'Modalità chiara'"
          @click="toggleTheme"
        >
          <span v-if="theme === 'light'">☀</span>
          <span v-else>☽</span>
        </button>
      </div>
    </header>

    <div class="page-scroll">
      <router-view />
    </div>
  </div>
</template>

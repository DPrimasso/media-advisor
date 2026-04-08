import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/mercato' },
    {
      path: '/canali',
      name: 'home',
      component: () => import('../views/HomeView.vue'),
    },
    { path: '/inbox', name: 'inbox', component: () => import('../views/InboxView.vue') },
    { path: '/channel/:id', name: 'channel', component: () => import('../views/ChannelView.vue') },
    { path: '/squadre', name: 'squadre', component: () => import('../views/SquadreView.vue') },
    { path: '/squadre/:teamId', name: 'squadre-team', component: () => import('../views/SquadreTeamView.vue') },
    { path: '/trend', name: 'trend', component: () => import('../views/TrendView.vue') },
    { path: '/trend/:macroId', name: 'trend-macro', component: () => import('../views/TrendMacroView.vue') },
    { path: '/mercato', name: 'mercato', component: () => import('../views/MercatoView.vue') },
    { path: '/mercato/player/:slug', name: 'mercato-player', component: () => import('../views/MercatoPlayerView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/mercato' }
  ]
})

router.onError((err) => {
  const msg = err?.message || String(err)
  if (
    msg.includes('Failed to fetch dynamically imported module') ||
    msg.includes('Importing a module script failed') ||
    msg.includes('error loading dynamically imported module')
  ) {
    window.location.reload()
  }
})

export default router

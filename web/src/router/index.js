import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/mercato' },
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

export default router

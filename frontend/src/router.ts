import { createRouter, createWebHashHistory } from 'vue-router'
import { isAuthed } from './api'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('./views/LoginView.vue') },
    { path: '/', name: 'search', component: () => import('./views/SearchView.vue') },
    { path: '/library', name: 'library', component: () => import('./views/LibraryView.vue') },
    { path: '/file/:id', name: 'file', component: () => import('./views/FileDetailView.vue') },
    { path: '/settings', name: 'settings', component: () => import('./views/SettingsView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  if (to.name !== 'login' && !isAuthed()) {
    return { name: 'login' }
  }
  if (to.name === 'login' && isAuthed()) {
    return { name: 'search' }
  }
  return true
})

export { router }

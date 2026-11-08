import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import { FrappeUI, setConfig, frappeRequest } from 'frappe-ui'

import App from './App.vue'
import './index.css'

setConfig('resourceFetcher', frappeRequest)

const router = createRouter({
  history: createWebHistory('/drive'),
  routes: [
    { path: '/', name: 'home', component: () => import('./views/Browser.vue') },
    { path: '/folder/:id', name: 'folder', component: () => import('./views/Browser.vue') },
    { path: '/recent', name: 'recent', component: () => import('./views/Browser.vue') },
    { path: '/trash', name: 'trash', component: () => import('./views/Browser.vue') },
    { path: '/review', name: 'review', component: () => import('./views/Browser.vue') },
    { path: '/duplicates', name: 'duplicates', component: () => import('./views/Duplicates.vue') },
  ],
})

createApp(App).use(router).use(FrappeUI).mount('#app')

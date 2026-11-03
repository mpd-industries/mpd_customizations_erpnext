import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'

const router = createRouter({
  history: createWebHistory('/compliance'),
  routes: [
    { path: '/', name: 'home', component: () => import('./views/Home.vue') },
    { path: '/calendar', name: 'calendar', component: () => import('./views/Calendar.vue') },
    { path: '/activities', name: 'activities', component: () => import('./views/Activities.vue') },
    { path: '/activity/:name', name: 'activity', component: () => import('./views/Activity.vue') },
    { path: '/register', name: 'register', component: () => import('./views/Register.vue') },
    { path: '/registrations', name: 'registrations', component: () => import('./views/Registrations.vue') },
    { path: '/sites', name: 'sites', component: () => import('./views/Sites.vue') },
    { path: '/coverage', name: 'coverage', component: () => import('./views/Coverage.vue') },
    { path: '/unmatched', name: 'unmatched', component: () => import('./views/Unmatched.vue') },
  ],
})

createApp(App).use(router).mount('#app')

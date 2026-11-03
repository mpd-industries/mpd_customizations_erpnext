<script setup>
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const links = [
  ['home', 'Home', '/'],
  ['calendar', 'Calendar', '/calendar'],
  ['activities', 'Activities', '/activities'],
  ['register', 'Register', '/register'],
  ['registrations', 'Registrations', '/registrations'],
  ['sites', 'Sites', '/sites'],
  ['coverage', 'Coverage', '/coverage'],
  ['unmatched', 'Unmatched', '/unmatched'],
]
</script>

<template>
  <div class="shell">
    <aside>
      <div class="brand">Compliance</div>
      <button
        v-for="[name, label, path] in links"
        :key="name"
        :class="{ on: route.name === name }"
        @click="router.push(path)"
      >
        {{ label }}
      </button>
      <a href="/drive">Drive</a>
      <a href="/desk">Desk</a>
    </aside>
    <main>
      <router-view />
    </main>
  </div>
</template>

<style>
html, body, #app { height: 100%; margin: 0; }
body { font-family: 'Segoe UI', sans-serif; color: #202124; background: #f6f7f9; }
.shell { display: flex; height: 100%; }
aside { width: 220px; background: #fff; border-right: 1px solid #e4e4e4; padding: 16px; display: flex; flex-direction: column; gap: 4px; }
.brand { font-size: 20px; margin-bottom: 12px; }
button, a { text-align: left; background: none; border: 0; padding: 8px 12px; border-radius: 999px; color: inherit; text-decoration: none; cursor: pointer; }
button.on { background: #d3e3fd; font-weight: 600; }
main { flex: 1; overflow: auto; padding: 20px; }
table { width: 100%; border-collapse: collapse; background: #fff; }
th, td { text-align: left; padding: 8px; border-bottom: 1px solid #eee; font-size: 14px; }
.cards { display: flex; gap: 12px; flex-wrap: wrap; }
.card { background: #fff; border-radius: 12px; padding: 16px; min-width: 140px; }
.card strong { display: block; font-size: 28px; }
.error { color: #b3261e; }
</style>

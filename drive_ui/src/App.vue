<script setup>
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const searchText = ref(route.query.q || '')

const links = [
  { name: 'home', label: 'My Drive', path: '/' },
  { name: 'recent', label: 'Recent', path: '/recent' },
  { name: 'review', label: 'Needs Review', path: '/review' },
  { name: 'trash', label: 'Trash', path: '/trash' },
]

watch(
  () => route.query.q,
  (value) => {
    searchText.value = value || ''
  },
)

function active(name) {
  if (route.query.q) return false
  if (name === 'home') return route.name === 'home' || route.name === 'folder'
  return route.name === name
}

function runSearch() {
  const q = searchText.value.trim()
  router.push(q ? { path: '/', query: { q } } : { path: '/' })
}

const embedded = new URLSearchParams(window.location.search).get('embed') === '1'
</script>

<template>
  <div class="flex h-full bg-[#f8fafd]">
    <aside class="flex w-64 shrink-0 flex-col border-r border-[#e0e0e0] bg-white">
      <div class="px-5 pb-2 pt-5 text-xl font-normal tracking-tight text-[#202124]">Drive</div>
      <form class="px-3 pb-3" @submit.prevent="runSearch">
        <input
          v-model="searchText"
          class="w-full rounded-full border border-[#dadce0] px-4 py-2 text-sm"
          placeholder="Search files and folders"
          @keyup.enter="runSearch"
        />
      </form>
      <nav class="flex flex-1 flex-col gap-1 px-3">
        <button
          v-for="link in links"
          :key="link.name"
          class="rounded-full px-4 py-2 text-left text-sm"
          :class="active(link.name) ? 'bg-[#c2e7ff] font-medium text-[#001d35]' : 'text-[#202124] hover:bg-[#f1f3f4]'"
          @click="router.push(link.path)"
        >
          {{ link.label }}
        </button>
      </nav>
      <div v-if="!embedded" class="mt-auto flex flex-col gap-1 border-t border-[#e0e0e0] px-3 py-3">
        <a class="rounded-full px-4 py-2 text-sm text-[#202124] hover:bg-[#f1f3f4]" href="/desk/compliance">Desk</a>
        <a class="rounded-full px-4 py-2 text-sm text-[#202124] hover:bg-[#f1f3f4]" href="/desk/home">ERPNext</a>
      </div>
    </aside>
    <main class="min-w-0 flex-1">
      <router-view />
    </main>
  </div>
</template>

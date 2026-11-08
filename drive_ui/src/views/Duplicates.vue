<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button } from 'frappe-ui'
import { api } from '../api.js'

const router = useRouter()
const groups = ref([])
const error = ref('')
const busy = ref('')

async function load() {
  error.value = ''
  const result = await api('mpd_customizations.drive.api.duplicates.list_duplicates')
  groups.value = result.groups || []
}

async function keepOne(group, file) {
  busy.value = group.content_hash
  try {
    await api('mpd_customizations.drive.api.duplicates.keep_one', {
      content_hash: group.content_hash,
      file_id: file.name,
    })
    await load()
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = ''
  }
}

async function keepAll(group) {
  busy.value = group.content_hash
  try {
    await api('mpd_customizations.drive.api.duplicates.keep_all', { content_hash: group.content_hash })
    await load()
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = ''
  }
}

async function preview(file) {
  const result = await api('mpd_customizations.drive.api.upload.get_download_url', {
    file_id: file.name,
    inline: 1,
  })
  window.open(result.url, '_blank')
}

async function rescan() {
  try {
    await api('mpd_customizations.drive.api.duplicates.rescan')
    error.value = ''
  } catch (err) {
    error.value = err.message
  }
}

function formatSize(size) {
  const value = Number(size || 0)
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

onMounted(load)
</script>

<template>
  <div class="h-full overflow-auto p-4">
    <header class="mb-4 flex items-center justify-between gap-4">
      <div>
        <h1 class="text-lg">Duplicates</h1>
        <p class="mt-1 max-w-3xl text-sm text-gray-600">
          These copies have the same file contents. The match is a SHA-256 hash of the bytes, not the file name, so two copies can have different names. Only folders with duplicate check turned on are included, and everything inside them.
        </p>
      </div>
      <Button variant="outline" label="Rescan" @click="rescan" />
    </header>
    <p v-if="error" class="mb-3 text-sm text-red-700">{{ error }}</p>
    <p v-if="!groups.length" class="py-16 text-center text-gray-500">
      No duplicate files in folders where duplicate check is on.
    </p>
    <section v-for="group in groups" :key="group.content_hash" class="mb-4 rounded-lg bg-white p-4 shadow-sm">
      <p class="mb-1 text-sm font-medium">Same file in {{ group.files.length }} places</p>
      <p class="mb-3 text-xs text-gray-500">{{ formatSize(group.wasted_bytes) }} extra · content hash {{ group.content_hash.slice(0, 12) }}</p>
      <article v-for="file in group.files" :key="file.name" class="flex items-start justify-between gap-3 border-t border-gray-100 py-3">
        <div class="min-w-0">
          <div class="font-medium">{{ file.title }}</div>
          <div class="mt-1 break-words text-sm text-[#202124]">{{ file.path }}</div>
          <div v-if="file.original_filename && file.original_filename !== file.title" class="mt-1 break-words text-xs text-gray-500">
            Original file name: {{ file.original_filename }}
          </div>
          <div class="mt-1 text-xs text-gray-500">{{ file.owner }} · {{ file.creation }} · {{ file.ai_status || 'No AI status' }}</div>
        </div>
        <div class="flex shrink-0 gap-2">
          <button class="text-xs text-[#1a73e8]" @click="preview(file)">Preview</button>
          <button class="text-xs text-[#1a73e8]" @click="router.push(`/folder/${file.folder}`)">Open folder</button>
          <Button variant="outline" label="Keep this one" :disabled="busy === group.content_hash" @click="keepOne(group, file)" />
        </div>
      </article>
      <Button class="mt-2" variant="solid" label="Keep all" :disabled="busy === group.content_hash" @click="keepAll(group)" />
    </section>
  </div>
</template>

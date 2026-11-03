<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
const rows = ref([])
const error = ref('')
const activity = ref('')
async function load() {
  rows.value = (await api('mpd_customizations.compliance.api.query.unmatched')).evidence
}
async function link(name) {
  error.value = ''
  try {
    await api('mpd_customizations.compliance.api.evidence.link_unmatched', { name, activity: activity.value })
    await load()
  } catch (err) {
    error.value = err.message
  }
}
onMounted(() => load().catch((err) => (error.value = err.message)))
</script>
<template>
  <h1>Unmatched evidence</h1>
  <p class="error">{{ error }}</p>
  <input v-model="activity" placeholder="Activity id to link" />
  <table>
    <thead><tr><th>File</th><th>Kind</th><th>Summary</th><th></th></tr></thead>
    <tbody>
      <tr v-for="row in rows" :key="row.name">
        <td>{{ row.drive_file }}</td><td>{{ row.document_kind }}</td><td>{{ row.summary }}</td>
        <td><button @click="link(row.name)">Link</button></td>
      </tr>
    </tbody>
  </table>
</template>

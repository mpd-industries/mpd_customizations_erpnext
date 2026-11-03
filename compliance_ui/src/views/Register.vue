<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const rows = ref([])
const error = ref('')
onMounted(async () => {
  try {
    rows.value = (await api('mpd_customizations.compliance.api.query.register')).obligations
  } catch (err) {
    error.value = err.message
  }
})
async function activate(name) {
  await api('mpd_customizations.compliance.api.actions.set_obligation_status', { name, status: 'Active' })
  rows.value = (await api('mpd_customizations.compliance.api.query.register')).obligations
}
</script>

<template>
  <h1>Register</h1>
  <p class="error">{{ error }}</p>
  <table>
    <thead><tr><th>Title</th><th>Domain</th><th>Scope</th><th>Status</th><th>Law</th><th></th></tr></thead>
    <tbody>
      <tr v-for="row in rows" :key="row.name">
        <td>{{ row.title }}</td>
        <td>{{ row.domain }}</td>
        <td>{{ row.scope }} {{ row.company }} {{ row.site }}</td>
        <td>{{ row.status }} <span v-if="row.source === 'Agent'">(agent)</span></td>
        <td>{{ row.law_reference }}</td>
        <td><button v-if="row.status === 'Draft'" @click="activate(row.name)">Activate</button></td>
      </tr>
    </tbody>
  </table>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
const rows = ref([])
const error = ref('')
onMounted(async () => {
  try {
    rows.value = (await api('mpd_customizations.compliance.api.query.list_registrations')).registrations
  } catch (err) {
    error.value = err.message
  }
})
</script>
<template>
  <h1>Registrations</h1>
  <p class="error">{{ error }}</p>
  <table>
    <thead><tr><th>Type</th><th>Number</th><th>Company</th><th>Status</th><th>Valid to</th></tr></thead>
    <tbody>
      <tr v-for="row in rows" :key="row.name">
        <td>{{ row.registration_type }}</td><td>{{ row.registration_number }}</td>
        <td>{{ row.company }}</td><td>{{ row.status }}</td><td>{{ row.valid_to }}</td>
      </tr>
    </tbody>
  </table>
</template>

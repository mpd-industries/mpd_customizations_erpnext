<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
const sites = ref([])
const error = ref('')
onMounted(async () => {
  try {
    sites.value = (await api('mpd_customizations.compliance.api.query.context')).sites
  } catch (err) {
    error.value = err.message
  }
})
</script>
<template>
  <h1>Sites</h1>
  <p class="error">{{ error }}</p>
  <table>
    <thead><tr><th>Location</th><th>Company</th><th>Type</th><th>Facts</th></tr></thead>
    <tbody>
      <tr v-for="row in sites" :key="row.name">
        <td>{{ row.location }}</td>
        <td>{{ row.company }}</td>
        <td>{{ row.site_type }}</td>
        <td>
          {{ [row.has_boiler && 'Boiler', row.has_etp && 'ETP', row.has_hazardous_chemicals && 'Hazardous'].filter(Boolean).join(', ') }}
        </td>
      </tr>
    </tbody>
  </table>
</template>

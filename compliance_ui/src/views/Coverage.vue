<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
const data = ref(null)
const error = ref('')
onMounted(async () => {
  try {
    data.value = await api('mpd_customizations.compliance.api.query.coverage')
  } catch (err) {
    error.value = err.message
  }
})
</script>
<template>
  <h1>Coverage</h1>
  <p class="error">{{ error }}</p>
  <template v-if="data">
    <h2>Gaps</h2>
    <ul><li v-for="(gap, index) in data.gaps" :key="index">{{ gap.message }}</li></ul>
    <h2>Matrix</h2>
    <table>
      <thead><tr><th>Company</th><th>Site</th><th>Domain</th><th>Obligations</th></tr></thead>
      <tbody>
        <tr v-for="(row, index) in data.matrix" :key="index">
          <td>{{ row.company }}</td><td>{{ row.site }}</td><td>{{ row.domain }}</td><td>{{ row.obligations }}</td>
        </tr>
      </tbody>
    </table>
  </template>
</template>

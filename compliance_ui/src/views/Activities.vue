<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api.js'

const router = useRouter()
const rows = ref([])
const error = ref('')
const filters = ref({ company: '', domain: '', status: '', overdue: false })

async function load() {
  try {
    const args = {}
    for (const [key, value] of Object.entries(filters.value)) {
      if (value) args[key] = value
    }
    rows.value = (await api('mpd_customizations.compliance.api.query.list_activities', args)).activities
  } catch (err) {
    error.value = err.message
  }
}
onMounted(load)
</script>

<template>
  <h1>Activities</h1>
  <p class="error">{{ error }}</p>
  <form @submit.prevent="load">
    <input v-model="filters.company" placeholder="Company" />
    <input v-model="filters.domain" placeholder="Domain" />
    <input v-model="filters.status" placeholder="Status" />
    <label><input v-model="filters.overdue" type="checkbox" /> Overdue</label>
    <button type="submit">Filter</button>
  </form>
  <table>
    <thead><tr><th>Title</th><th>Period</th><th>Due</th><th>Status</th></tr></thead>
    <tbody>
      <tr v-for="row in rows" :key="row.name" @click="router.push(`/activity/${row.name}`)">
        <td>{{ row.title }}</td>
        <td>{{ row.period_label }}</td>
        <td>{{ row.due_date }}</td>
        <td>{{ row.is_overdue ? 'Overdue' : row.status }}</td>
      </tr>
    </tbody>
  </table>
</template>

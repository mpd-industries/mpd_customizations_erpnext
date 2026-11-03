<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api.js'

const router = useRouter()
const rows = ref([])
const error = ref('')
const cursor = ref(startOfMonth(new Date()))

function startOfMonth(date) {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

function iso(date) {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function addMonths(date, count) {
  return new Date(date.getFullYear(), date.getMonth() + count, 1)
}

const label = computed(() =>
  cursor.value.toLocaleString(undefined, { month: 'long', year: 'numeric' })
)

const cells = computed(() => {
  const start = cursor.value
  const end = addMonths(start, 1)
  const byDay = {}
  for (const row of rows.value) {
    if (!row.due_date) continue
    ;(byDay[row.due_date] ||= []).push(row)
  }
  const days = []
  for (let date = new Date(start); date < end; date.setDate(date.getDate() + 1)) {
    const key = iso(date)
    days.push({ key, day: date.getDate(), items: byDay[key] || [] })
  }
  return days
})

async function load() {
  const start = cursor.value
  const end = new Date(addMonths(start, 1).getTime() - 86400000)
  try {
    rows.value = (
      await api('mpd_customizations.compliance.api.query.list_activities', {
        due_from: iso(start),
        due_to: iso(end),
      })
    ).activities
  } catch (err) {
    error.value = err.message
  }
}

function shift(count) {
  cursor.value = addMonths(cursor.value, count)
  load()
}

onMounted(load)
</script>

<template>
  <h1>Calendar</h1>
  <p class="error">{{ error }}</p>
  <p>
    <button type="button" @click="shift(-1)">Previous</button>
    {{ label }}
    <button type="button" @click="shift(1)">Next</button>
  </p>
  <div class="month">
    <div v-for="cell in cells" :key="cell.key" class="day">
      <strong>{{ cell.day }}</strong>
      <button
        v-for="row in cell.items"
        :key="row.name"
        type="button"
        @click="router.push(`/activity/${row.name}`)"
      >
        {{ row.title }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.month { display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; }
.day { background: #fff; min-height: 88px; padding: 8px; border-radius: 8px; }
.day button { display: block; width: 100%; margin-top: 4px; background: #d3e3fd; border-radius: 6px; font-size: 12px; }
</style>

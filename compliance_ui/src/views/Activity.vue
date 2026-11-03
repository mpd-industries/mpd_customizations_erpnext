<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api.js'

const route = useRoute()
const activity = ref(null)
const error = ref('')
const ack = ref('')
const reason = ref('')

async function load() {
  const result = await api('mpd_customizations.compliance.api.query.get_activity', { name: route.params.name })
  activity.value = result.activity
  ack.value = result.activity.ack_no || ''
}

async function run(action) {
  error.value = ''
  try {
    await api('mpd_customizations.compliance.api.actions.act', {
      name: route.params.name,
      action,
      ack_no: ack.value,
      na_reason: reason.value,
    })
    await load()
  } catch (err) {
    error.value = err.message
  }
}

async function upload(event) {
  const file = event.target.files[0]
  if (!file) return
  const body = new FormData()
  body.append('activity', route.params.name)
  body.append('file', file)
  const response = await fetch('/api/method/mpd_customizations.compliance.api.evidence.upload', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-Frappe-CSRF-Token': document.cookie.match(/csrf_token=([^;]+)/)?.[1] ? decodeURIComponent(document.cookie.match(/csrf_token=([^;]+)/)[1]) : '' },
    body,
  })
  if (!response.ok) error.value = 'Upload failed'
  await load()
}

onMounted(load)
</script>

<template>
  <p v-if="error" class="error">{{ error }}</p>
  <template v-if="activity">
    <h1>{{ activity.title }}</h1>
    <p>{{ activity.domain }} · {{ activity.company || 'Group' }} · {{ activity.period_label }} · due {{ activity.due_date }}</p>
    <p>Status: {{ activity.status }} <span v-if="activity.is_overdue">(overdue {{ activity.days_late }} days)</span></p>
    <p v-if="activity.task">Task {{ activity.task }}</p>
    <h2>Checklist</h2>
    <ul>
      <li v-for="row in activity.checklist" :key="row.name">{{ row.is_done ? '✓' : '○' }} {{ row.step }}</li>
    </ul>
    <h2>Evidence</h2>
    <ul>
      <li v-for="row in activity.evidence" :key="row.name">{{ row.drive_file }} — {{ row.note }}</li>
    </ul>
    <input type="file" @change="upload" />
    <p><label>Acknowledgement <input v-model="ack" /></label></p>
    <p>
      <button @click="run('start')">Start</button>
      <button @click="run('submit')">Submit</button>
      <button @click="run('complete')">Complete</button>
      <button @click="run('approve')">Approve</button>
      <button @click="run('reject')">Reject</button>
    </p>
    <p>
      <input v-model="reason" placeholder="Why it does not apply" />
      <button @click="run('not_applicable')">Not applicable</button>
    </p>
  </template>
</template>

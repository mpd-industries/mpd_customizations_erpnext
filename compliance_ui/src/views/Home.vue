<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const data = ref(null)
const error = ref('')
onMounted(async () => {
  try {
    data.value = await api('mpd_customizations.compliance.api.query.dashboard')
  } catch (err) {
    error.value = err.message
  }
})
</script>

<template>
  <h1>Compliance</h1>
  <p class="error">{{ error }}</p>
  <div v-if="data" class="cards">
    <div class="card"><strong>{{ data.overdue }}</strong>Overdue</div>
    <div class="card"><strong>{{ data.due_this_week }}</strong>Due this week</div>
    <div class="card"><strong>{{ data.pending_review }}</strong>Pending review</div>
    <div class="card"><strong>{{ data.my_open }}</strong>My open</div>
    <div class="card"><strong>{{ data.on_time_percent ?? '—' }}</strong>On time %</div>
    <div class="card"><strong>{{ data.draft_obligations }}</strong>Draft obligations</div>
  </div>
  <p>Use Claude with the compliance MCP tools to compare this register with the law and add drafts.</p>
</template>

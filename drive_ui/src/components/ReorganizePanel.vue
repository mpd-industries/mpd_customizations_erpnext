<script setup>
import { computed, ref, watch } from 'vue'
import { Button } from 'frappe-ui'

const props = defineProps({
  run: { type: Object, default: null },
})
const emit = defineEmits(['apply', 'cancel', 'revise'])

const checked = ref({})
const showAll = ref(false)
const openJson = ref({})
const filter = ref('all')
const followup = ref('')
const copied = ref(false)

watch(
  () => [props.run?.name, props.run?.revision, props.run?.status],
  () => {
    if (props.run?.status !== 'Ready') return
    const next = {}
    const threshold = Number(props.run.threshold ?? 0.75)
    for (const item of props.run.items || []) {
      const samePath = item.proposed_path && item.proposed_path === item.current_path
      next[item.name] =
        item.status === 'Proposed' && !samePath && Number(item.confidence) >= threshold
    }
    checked.value = next
    openJson.value = {}
  },
  { immediate: true },
)

const working = computed(() => ['Queued', 'Running'].includes(props.run?.status))
const progress = computed(() => {
  const total = Number(props.run?.total_count || 0)
  if (!total) return 0
  return Math.round((Number(props.run?.done_count || 0) / total) * 100)
})

const visible = computed(() => {
  const threshold = Number(props.run?.threshold ?? 0.75)
  return (props.run?.items || []).filter((item) => {
    if (filter.value === 'failed') return item.status === 'Failed'
    if (filter.value === 'low') return Number(item.confidence) < threshold
    const samePath = item.proposed_path === item.current_path
    const sameTitle = (item.proposed_title || '') === (item.current_title || '')
    if (filter.value === 'unchanged') return samePath && sameTitle
    if (filter.value === 'move') return !samePath || !sameTitle
    return true
  })
})

const selectedNames = computed(() =>
  (props.run?.items || []).filter((item) => checked.value[item.name]).map((item) => item.name),
)

function pretty(text) {
  if (!text) return ''
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}

function showJson(item) {
  return showAll.value || openJson.value[item.name]
}

async function copyAll() {
  const payload = (props.run?.items || []).map((item) => ({
    file: item.file,
    current_path: item.current_path,
    proposed_path: item.proposed_path,
    input: parseJson(item.model_input),
    output: parseJson(item.model_output),
  }))
  await navigator.clipboard.writeText(JSON.stringify(payload, null, 2))
  copied.value = true
}

function parseJson(text) {
  try {
    return JSON.parse(text)
  } catch {
    return text || null
  }
}

function submitFollowup() {
  const text = followup.value.trim()
  if (!text) return
  emit('revise', text)
  followup.value = ''
}
</script>

<template>
  <div v-if="run" class="text-sm">
    <p v-if="run.instruction" class="mb-2 text-gray-700">{{ run.instruction }}</p>
    <ol v-if="run.followups?.length" class="mb-3 list-decimal pl-5 text-gray-600">
      <li v-for="(note, index) in run.followups" :key="index">{{ note }}</li>
    </ol>
    <div v-if="working" class="py-6">
      <p class="mb-2">Reading files… {{ run.done_count || 0 }} / {{ run.total_count || 0 }}</p>
      <div class="h-2 rounded bg-gray-100">
        <div class="h-2 rounded bg-[#1a73e8]" :style="{ width: progress + '%' }" />
      </div>
    </div>
    <template v-else>
      <div class="mb-3 flex flex-wrap items-center gap-2">
        <select v-model="filter" class="rounded border px-2 py-1">
          <option value="all">All</option>
          <option value="move">Will move</option>
          <option value="unchanged">Unchanged</option>
          <option value="low">Low confidence</option>
          <option value="failed">Failed</option>
        </select>
        <label class="flex items-center gap-1">
          <input v-model="showAll" type="checkbox" />
          Show all JSON
        </label>
        <button class="text-[#1a73e8]" @click="copyAll">{{ copied ? 'Copied' : 'Copy JSON' }}</button>
      </div>
      <div class="max-h-[50vh] space-y-2 overflow-auto">
        <article v-for="item in visible" :key="item.name" class="rounded border border-gray-200 p-2">
          <label class="flex items-start gap-2">
            <input v-model="checked[item.name]" type="checkbox" :disabled="item.status !== 'Proposed'" />
            <span class="min-w-0">
              <span class="block text-gray-500">{{ item.current_path }} / {{ item.current_title }}</span>
              <span class="block">{{ item.proposed_path || 'No proposal' }} / {{ item.proposed_title }}</span>
              <span class="text-xs text-gray-500">
                {{ item.status }}
                <template v-if="item.confidence != null"> · {{ Number(item.confidence).toFixed(2) }}</template>
              </span>
            </span>
          </label>
          <button class="mt-1 text-xs text-[#1a73e8]" @click="openJson[item.name] = !openJson[item.name]">
            {{ showJson(item) ? 'Hide JSON' : 'View JSON' }}
          </button>
          <pre v-if="showJson(item)" class="mt-1 max-h-48 overflow-auto rounded bg-gray-50 p-2 text-xs">{{ pretty(item.model_input) }}

{{ pretty(item.model_output) }}</pre>
        </article>
        <p v-if="!visible.length" class="py-4 text-gray-500">Nothing in this filter.</p>
      </div>
      <div v-if="run.status === 'Ready'" class="mt-3">
        <textarea
          v-model="followup"
          class="w-full rounded border px-2 py-1"
          rows="2"
          placeholder="Follow-up, for example: put GST files under Challans"
        />
        <button class="mt-1 text-[#1a73e8]" @click="submitFollowup">Redo plan</button>
      </div>
      <div class="mt-3 flex gap-2">
        <Button variant="solid" label="Apply selected" :disabled="!selectedNames.length" @click="emit('apply', selectedNames)" />
        <Button variant="outline" label="Cancel" @click="emit('cancel')" />
      </div>
    </template>
  </div>
</template>

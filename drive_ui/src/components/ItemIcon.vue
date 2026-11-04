<script setup>
defineProps({
  kind: { type: String, default: 'file' },
  title: { type: String, default: '' },
})

function ext(title) {
  const parts = (title || '').toLowerCase().split('.')
  return parts.length > 1 ? parts.pop() : ''
}
</script>

<template>
  <svg v-if="kind === 'folder'" viewBox="0 0 48 48" class="h-8 w-8 shrink-0" aria-hidden="true">
    <path fill="#FFA000" d="M40 12H22l-4-4H8c-2.2 0-4 1.8-4 4v8h40v-4c0-2.2-1.8-4-4-4z" />
    <path fill="#FFCA28" d="M40 40H8c-2.2 0-4-1.8-4-4V16h40v20c0 2.2-1.8 4-4 4z" />
  </svg>
  <svg v-else viewBox="0 0 48 48" class="h-8 w-8 shrink-0" aria-hidden="true">
    <path
      :fill="['xls', 'xlsx', 'csv'].includes(ext(title)) ? '#188038' : ['pdf'].includes(ext(title)) ? '#D93025' : ['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext(title)) ? '#7B1FA2' : '#1A73E8'"
      d="M12 4h16l10 10v28a2 2 0 0 1-2 2H12a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"
    />
    <path fill="#fff" d="M28 4v10h10" opacity=".9" />
    <path fill="#fff" d="M16 28h16v2H16zm0 6h12v2H16z" />
  </svg>
</template>

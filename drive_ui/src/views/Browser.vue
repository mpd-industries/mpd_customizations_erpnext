<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, Dialog } from 'frappe-ui'
import { api, downloadBlob, postFile, putWithProgress } from '../api.js'
import { isJunk, readDroppedItems, runPool } from '../dropTree.js'
import ItemIcon from '../components/ItemIcon.vue'
import ReorganizePanel from '../components/ReorganizePanel.vue'

const route = useRoute()
const router = useRouter()

const listing = ref({ folders: [], files: [], breadcrumbs: [], level: null, folder: null })
const viewMode = ref('grid')
const sortKey = ref('title')
const selected = ref([])
const menu = ref(null)
const dragging = ref(false)
const uploads = ref([])
const details = ref(null)
const purposeDraft = ref('')
const error = ref('')
const notice = ref('')

const dialogs = reactive({
  folder: false,
  share: false,
  move: false,
  preview: false,
  inbox: false,
  review: false,
  reorganize: false,
  reorganizePreview: false,
})
const folderTitle = ref('')
const share = ref({ inherit: 1, rules: [] })
const shareChoices = ref({ roles: [], users: [] })
const moving = ref(null)
const moveFolder = ref(null)
const moveCrumbs = ref([])
const moveError = ref('')
const moveListing = ref({ folders: [] })
const draggingItem = ref(null)
const dropTarget = ref(null)
const previewUrl = ref('')
const previewTitle = ref('')
const reviewForm = ref({ title: '', subject: '', year: '' })
const inboxForm = ref({ is_ai_inbox: 0, inbox_kind: 'General', organise_into: '' })
const fileInput = ref(null)
const folderInput = ref(null)
const lastSelected = ref(null)
const reorganizeForm = ref({ instruction: '', input_mode: 'Full JSON', preview: true })
const reorgRun = ref(null)
let reorgTimer = 0

const mode = computed(() => route.name)
const searchQuery = computed(() => String(route.query.q || '').trim())
const canEdit = computed(() => ['Edit', 'Manage'].includes(listing.value.level))
const canManage = computed(() => listing.value.level === 'Manage')
const hasAiInput = computed(() => (listing.value.folders || []).some((folder) => folder.is_ai_inbox))
const targetFolders = ref([])

const backTo = computed(() => {
  if (searchQuery.value) return '/'
  if (mode.value === 'recent' || mode.value === 'trash' || mode.value === 'review') return '/'
  const crumbs = listing.value.breadcrumbs || []
  if (crumbs.length > 1) return `/folder/${crumbs[crumbs.length - 2].name}`
  if (mode.value === 'folder') return '/'
  return ''
})

const movingNames = computed(() => new Set((moving.value || []).map((item) => item.name)))
const moveChoices = computed(() =>
  (moveListing.value.folders || []).filter((folder) => !movingNames.value.has(folder.name)),
)
const canMoveHere = computed(() => {
  if (!moving.value?.length || !moveFolder.value) return false
  return moving.value.some((item) => !(item.kind === 'folder' && item.name === moveFolder.value))
})
const moveTitle = computed(() => {
  const group = moving.value || []
  if (group.length > 1) return `Move ${group.length} items`
  return group[0] ? `Move ${group[0].title}` : 'Move'
})

const selectedItems = computed(() => items.value.filter((item) => selected.value.includes(item.name)))
const selectedFiles = computed(() => selectedItems.value.filter((item) => item.kind === 'file'))
const duplicateUploads = computed(() => uploads.value.filter((entry) => entry.status === 'duplicate'))

function selectionFor(item) {
  if (item && selected.value.includes(item.name) && selectedItems.value.length > 1) return selectedItems.value
  return item ? [item] : selectedItems.value
}

function onItemClick(event, item) {
  const names = items.value.map((row) => row.name)
  if (event.shiftKey && lastSelected.value && names.includes(lastSelected.value)) {
    const start = names.indexOf(lastSelected.value)
    const end = names.indexOf(item.name)
    const [from, to] = start < end ? [start, end] : [end, start]
    const range = names.slice(from, to + 1)
    selected.value = event.metaKey || event.ctrlKey ? [...new Set([...selected.value, ...range])] : range
    details.value = item
    return
  }
  if (event.metaKey || event.ctrlKey) {
    selected.value = selected.value.includes(item.name)
      ? selected.value.filter((name) => name !== item.name)
      : [...selected.value, item.name]
  } else {
    selected.value = [item.name]
  }
  lastSelected.value = item.name
  details.value = item
}

function canEditItem(item) {
  return ['Edit', 'Manage'].includes(item.level || listing.value.level)
}

const items = computed(() => {
  const rows = [...(listing.value.folders || []), ...(listing.value.files || [])]
  const key = sortKey.value
  return rows.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === 'folder' ? -1 : 1
    if (key === 'size') return (a.size || 0) - (b.size || 0)
    if (key === 'modified') return String(a.modified || '').localeCompare(String(b.modified || ''))
    return String(a.title || '').localeCompare(String(b.title || ''))
  })
})

let loadToken = 0

async function load() {
  const token = ++loadToken
  error.value = ''
  selected.value = []
  try {
    let next
    if (searchQuery.value) {
      const result = await api('mpd_customizations.drive.api.browse.search', { query: searchQuery.value })
      next = {
        folders: result.folders || [],
        files: result.files || [],
        breadcrumbs: [],
        level: null,
        folder: null,
      }
    } else if (mode.value === 'recent') {
      const result = await api('mpd_customizations.drive.api.browse.get_recent')
      next = { folders: [], files: result.files, breadcrumbs: [], level: null, folder: null }
    } else if (mode.value === 'trash') {
      next = await api('mpd_customizations.drive.api.browse.list_trash')
    } else if (mode.value === 'review') {
      const result = await api('mpd_customizations.drive.api.browse.list_review')
      next = { folders: [], files: result.files, breadcrumbs: [], level: 'Edit', folder: null }
    } else if (route.params.id) {
      next = await api('mpd_customizations.drive.api.browse.list_folder', { folder: route.params.id })
    } else {
      next = await api('mpd_customizations.drive.api.browse.list_folder')
    }
    if (token !== loadToken) return
    listing.value = next
  } catch (err) {
    if (token !== loadToken) return
    error.value = err.message
  }
}

watch(() => route.fullPath, load, { immediate: true })

function openItem(item) {
  if (item.kind === 'folder') router.push(`/folder/${item.name}`)
  else preview(item)
}

async function preview(item) {
  const result = await api('mpd_customizations.drive.api.upload.get_download_url', {
    file_id: item.name,
    inline: 1,
  })
  previewUrl.value = result.url
  previewTitle.value = item.title
  details.value = item
  dialogs.preview = true
}

function onContext(event, item) {
  event.preventDefault()
  menu.value = { x: event.clientX, y: event.clientY, item }
}

function closeMenu() {
  menu.value = null
}

async function createFolder() {
  await api('mpd_customizations.drive.api.browse.create_folder_item', {
    title: folderTitle.value,
    parent: listing.value.folder?.name,
  })
  dialogs.folder = false
  folderTitle.value = ''
  await load()
}

function pickFiles() {
  fileInput.value.click()
}

function pickFolder() {
  folderInput.value.click()
}

async function onFiles(event) {
  const picked = [...event.target.files]
  event.target.value = ''
  const folder = listing.value.folder?.name
  if (!folder) {
    error.value = 'Open a folder before uploading.'
    return
  }
  const files = picked
    .filter((file) => !isJunk(file.name))
    .map((file) => ({ relativePath: file.webkitRelativePath || file.name, file }))
  await uploadTree(folder, { files, folders: [] }, files.some((item) => item.relativePath.includes('/')) ? 'Folder' : '')
}

function uploadOne(file, folder) {
  const entry = reactive({ name: file.name, file, folder, progress: 0, status: 'uploading', error: '' })
  uploads.value.push(entry)
  runUpload(file, folder, entry)
}

async function runUpload(file, folder, entry, options = {}) {
  try {
    entry.status = 'uploading'
    const plan = await api('mpd_customizations.drive.api.upload.get_upload_url', {
      folder,
      file_name: file.name,
      size: file.size,
      mime_type: file.type || 'application/octet-stream',
    })
    entry.fileId = plan.file_id
    if (plan.mode === 'put') {
      const stored = await postFile(
        plan.file_id,
        file,
        (loaded, total) => {
          entry.progress = Math.round((loaded / total) * 100)
        },
        { allow_copy: options.allowCopy ? 1 : 0 },
      )
      if (stored?.duplicate) {
        entry.status = 'duplicate'
        entry.duplicate = stored.duplicate
        entry.progress = 0
        return
      }
    } else {
      const parts = []
      let sent = 0
      for (const part of plan.parts) {
        const blob = file.slice(part.start, part.end)
        const etag = await putWithProgress(part.url, blob, file.type, (loaded) => {
          entry.progress = Math.round(((sent + loaded) / file.size) * 100)
        })
        sent += blob.size
        parts.push({ part_number: part.part_number, etag })
      }
      await api('mpd_customizations.drive.api.upload.confirm_upload', {
        file_id: plan.file_id,
        parts,
      })
    }
    entry.status = 'done'
    entry.progress = 100
    await load()
  } catch (err) {
    entry.status = 'error'
    entry.error = err.message
  }
}

async function cancelUpload(entry) {
  if (entry.fileId) {
    await api('mpd_customizations.drive.api.upload.abort_upload', { file_id: entry.fileId }).catch(() => {})
  }
  entry.status = 'cancelled'
}

async function download(item) {
  const result = await api('mpd_customizations.drive.api.upload.get_download_url', { file_id: item.name, inline: 0 })
  window.open(result.url, '_blank')
}

async function rename(item) {
  const title = window.prompt('Name', item.title)
  if (!title) return
  await api('mpd_customizations.drive.api.browse.rename', { kind: item.kind, name: item.name, title })
  await load()
}

async function trash(item) {
  await api('mpd_customizations.drive.api.browse.trash', { kind: item.kind, name: item.name })
  await load()
}

async function restore(item) {
  await api('mpd_customizations.drive.api.browse.restore', { kind: item.kind, name: item.name })
  await load()
}

async function removeForever(item) {
  if (!window.confirm('Remove this from Drive? The file stays in S3.')) return
  await api('mpd_customizations.drive.api.browse.delete_permanently', { kind: item.kind, name: item.name })
  await load()
}

async function openShare(item) {
  if (item.kind !== 'folder') return
  const [current, choices] = await Promise.all([
    api('mpd_customizations.drive.api.sharing.get_sharing', { folder: item.name }),
    api('mpd_customizations.drive.api.sharing.share_choices', { folder: item.name }),
  ])
  share.value = current
  share.value.folder = item.name
  shareChoices.value = choices
  dialogs.share = true
}

function addRule() {
  share.value.rules.push({ principal_type: 'Role', role: '', user: '', level: 'View', draft: '', open: false })
}

function principalOptions(rule) {
  if (rule.principal_type === 'User') {
    return (shareChoices.value.users || []).map((user) => ({
      value: user.name,
      label: user.full_name && user.full_name !== user.name ? `${user.full_name} (${user.name})` : user.name,
    }))
  }
  return (shareChoices.value.roles || []).map((name) => ({ value: name, label: name }))
}

function principalValue(rule) {
  return rule.principal_type === 'User' ? rule.user || '' : rule.role || ''
}

function setPrincipalValue(rule, value) {
  if (rule.principal_type === 'User') {
    rule.user = value
    rule.role = ''
  } else {
    rule.role = value
    rule.user = ''
  }
}

function filteredPrincipals(rule) {
  const query = rule.typing ? (rule.draft || '').trim().toLowerCase() : ''
  const options = principalOptions(rule)
  const matched = query
    ? options.filter((option) => option.label.toLowerCase().includes(query) || option.value.toLowerCase().includes(query))
    : options
  return matched.slice(0, 50)
}

function onPrincipalType(rule, type) {
  rule.principal_type = type
  rule.role = ''
  rule.user = ''
  rule.draft = ''
  rule.typing = false
  rule.open = false
}

function onPrincipalFocus(rule) {
  rule.open = true
  rule.typing = false
  rule.draft = ''
}

function onPrincipalInput(rule, text) {
  rule.typing = true
  rule.draft = text
  rule.open = true
}

function choosePrincipal(rule, option) {
  setPrincipalValue(rule, option.value)
  rule.typing = false
  rule.draft = ''
  rule.open = false
}

function commitPrincipal(rule) {
  if (rule.typing) {
    const text = (rule.draft || '').trim().toLowerCase()
    const match = principalOptions(rule).find(
      (option) => option.value.toLowerCase() === text || option.label.toLowerCase() === text,
    )
    setPrincipalValue(rule, match ? match.value : '')
  }
  rule.typing = false
  rule.draft = ''
  rule.open = false
}

async function saveShare() {
  const rules = share.value.rules
    .map((rule) => ({
      principal_type: rule.principal_type,
      role: rule.principal_type === 'Role' ? rule.role : '',
      user: rule.principal_type === 'User' ? rule.user : '',
      level: rule.level || 'View',
    }))
    .filter((rule) => (rule.principal_type === 'User' ? rule.user : rule.role))
  await api('mpd_customizations.drive.api.sharing.set_folder_sharing', {
    folder: share.value.folder,
    rules,
    inherit: share.value.inherit_permissions ? 1 : 0,
  })
  dialogs.share = false
}

function canDrag(item) {
  return ['Edit', 'Manage'].includes(item.level || listing.value.level)
}

async function openMove(item) {
  const group = (item ? selectionFor(item) : selectedItems.value).filter(canEditItem)
  if (!group.length) return
  moving.value = group
  moveError.value = ''
  await showMoveFolder(null, [])
  dialogs.move = true
}

async function showMoveFolder(folder, crumbs) {
  moveFolder.value = folder
  moveCrumbs.value = crumbs
  moveListing.value = await api(
    'mpd_customizations.drive.api.browse.list_folder',
    folder ? { folder } : {},
  )
}

async function drill(folder) {
  await showMoveFolder(folder.name, [...moveCrumbs.value, { name: folder.name, title: folder.title }])
}

async function moveToCrumb(index) {
  if (index < 0) {
    await showMoveFolder(null, [])
    return
  }
  const crumbs = moveCrumbs.value.slice(0, index + 1)
  await showMoveFolder(crumbs[index].name, crumbs)
}

async function confirmMove() {
  const group = moving.value || []
  if (!group.length || !canMoveHere.value) return
  moveError.value = ''
  const failures = []
  for (const item of group) {
    if (item.kind === 'folder' && item.name === moveFolder.value) continue
    try {
      await api('mpd_customizations.drive.api.browse.move', {
        kind: item.kind,
        name: item.name,
        folder: moveFolder.value,
      })
    } catch (err) {
      failures.push(`${item.title}: ${err.message}`)
    }
  }
  if (failures.length) {
    moveError.value = failures.join(' ')
    return
  }
  dialogs.move = false
  moving.value = null
  await load()
}

async function moveItem(item, folder) {
  await api('mpd_customizations.drive.api.browse.move', {
    kind: item.kind,
    name: item.name,
    folder,
  })
  await load()
}

function onItemDragStart(event, item) {
  const group = selectionFor(item).filter(canEditItem)
  if (!group.length) {
    event.preventDefault()
    return
  }
  draggingItem.value = group
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('application/x-drive-item', group.map((row) => row.name).join(','))
}

function onItemDragEnd() {
  draggingItem.value = null
  dropTarget.value = null
  dragging.value = false
}

function onItemDragOver(event, item) {
  if (item.kind !== 'folder') return
  const dragged = draggingItem.value || []
  const internal = dragged.length && dragged.some((row) => row.name !== item.name)
  const external = [...(event.dataTransfer?.types || [])].includes('Files')
  if (!internal && !external) return
  event.preventDefault()
  event.stopPropagation()
  dropTarget.value = item.name
  event.dataTransfer.dropEffect = internal ? 'move' : 'copy'
}

async function onItemDrop(event, item) {
  if (item.kind !== 'folder') return
  event.preventDefault()
  event.stopPropagation()
  const dragged = draggingItem.value || []
  draggingItem.value = null
  dropTarget.value = null
  dragging.value = false
  if (dragged.length) {
    const failures = []
    for (const row of dragged) {
      if (row.name === item.name) continue
      try {
        await moveItem(row, item.name)
      } catch (err) {
        failures.push(`${row.title}: ${err.message}`)
      }
    }
    if (failures.length) error.value = failures.join(' ')
    return
  }
  await acceptExternalDrop(event.dataTransfer, item.name)
}

async function showDetails(item) {
  details.value = item
  purposeDraft.value = item.purpose || ''
}

async function savePurpose() {
  if (!details.value || details.value.kind !== 'folder') return
  try {
    const result = await api('mpd_customizations.drive.api.browse.set_folder_purpose', {
      folder: details.value.name,
      purpose: purposeDraft.value,
    })
    details.value.purpose = result.purpose
    details.value.purpose_custom = result.purpose_custom
    const listed = items.value.find((item) => item.name === details.value.name)
    if (listed) {
      listed.purpose = result.purpose
      listed.purpose_custom = result.purpose_custom
    }
    if (listing.value.folder?.name === details.value.name) {
      listing.value.folder.purpose = result.purpose
      listing.value.folder.purpose_custom = result.purpose_custom
    }
  } catch (err) {
    error.value = err.message
  }
}

async function toggleDuplicateCheck(item, enabled) {
  const next = enabled === undefined ? (item.check_duplicates ? 0 : 1) : enabled ? 1 : 0
  try {
    const result = await api('mpd_customizations.drive.api.duplicates.set_duplicate_check', {
      folder: item.name,
      enabled: next,
    })
    item.check_duplicates = result.check_duplicates
    if (listing.value.folder?.name === item.name) listing.value.folder.check_duplicates = result.check_duplicates
    if (details.value?.name === item.name) details.value.check_duplicates = result.check_duplicates
  } catch (err) {
    error.value = err.message
  }
}

async function acceptReview(item, edited) {
  const form = edited ? reviewForm.value : { title: item.title, subject: item.ai_subject, year: '' }
  await api('mpd_customizations.drive.api.inbox.accept_filing', {
    file_id: item.name,
    title: form.title,
    subject: form.subject,
    year: form.year,
  })
  dialogs.review = false
  await load()
}

function editReview(item) {
  const parts = (item.ai_suggested_path || '').split('/')
  reviewForm.value = {
    title: item.title,
    subject: item.ai_subject || '',
    year: parts.at(-1) || '',
    item,
  }
  dialogs.review = true
}

async function rerun(item) {
  await api('mpd_customizations.drive.api.inbox.rerun', { file_id: item.name })
  await load()
}

function openReorganize() {
  if (!listing.value.folder?.name) return
  reorganizeForm.value = { instruction: '', input_mode: 'Full JSON', preview: true }
  dialogs.reorganize = true
}

async function startReorganize() {
  const folder = listing.value.folder?.name
  if (!folder) return
  const form = reorganizeForm.value
  if (form.input_mode === 'Name only') form.preview = true
  notice.value = ''
  error.value = ''
  try {
    const result = await api('mpd_customizations.drive.api.inbox.start_reorganize', {
      folder,
      instruction: form.instruction,
      input_mode: form.input_mode,
      preview: form.preview ? 1 : 0,
    })
    dialogs.reorganize = false
    if (!form.preview) {
      notice.value = 'Reorganizing this folder in the background.'
      return
    }
    reorgRun.value = { name: result.name, status: 'Queued', items: [], followups: [] }
    dialogs.reorganizePreview = true
    pollReorganize()
  } catch (err) {
    error.value = err.message
  }
}

async function pollReorganize() {
  window.clearTimeout(reorgTimer)
  if (!reorgRun.value?.name || !dialogs.reorganizePreview) return
  try {
    reorgRun.value = await api('mpd_customizations.drive.api.inbox.get_reorganize_run', { run: reorgRun.value.name })
  } catch (err) {
    error.value = err.message
    return
  }
  if (['Queued', 'Running'].includes(reorgRun.value.status)) {
    reorgTimer = window.setTimeout(pollReorganize, 1500)
  }
}

async function applyReorganize(itemNames) {
  try {
    const result = await api('mpd_customizations.drive.api.inbox.apply_reorganize', {
      run: reorgRun.value.name,
      item_names: itemNames,
    })
    dialogs.reorganizePreview = false
    notice.value = `Moved ${result.applied} file${result.applied === 1 ? '' : 's'}.`
    if (result.skipped) notice.value += ` ${result.skipped} had been moved already and were left.`
    await load()
  } catch (err) {
    error.value = err.message
  }
}

async function reviseReorganize(followup) {
  try {
    await api('mpd_customizations.drive.api.inbox.revise_reorganize', {
      run: reorgRun.value.name,
      followup,
    })
    reorgRun.value = { ...reorgRun.value, status: 'Queued', items: [] }
    pollReorganize()
  } catch (err) {
    error.value = err.message
  }
}

async function cancelReorganize() {
  if (reorgRun.value?.name) {
    await api('mpd_customizations.drive.api.inbox.cancel_reorganize', { run: reorgRun.value.name }).catch(() => {})
  }
  dialogs.reorganizePreview = false
}

async function downloadZip() {
  const ids = selectedFiles.value.map((item) => item.name)
  if (ids.length < 2) return
  try {
    await downloadBlob(
      'mpd_customizations.drive.api.upload.download_zip',
      { file_ids: ids, folder_title: listing.value.folder?.title || '' },
      `${listing.value.folder?.title || 'Drive'}.zip`,
    )
  } catch (err) {
    error.value = err.message
  }
}

async function trashSelected(item) {
  const group = (item ? selectionFor(item) : selectedItems.value).filter((row) => mode.value === 'trash' || canEditItem(row))
  for (const row of group) {
    if (mode.value === 'trash') await restore(row)
    else await api('mpd_customizations.drive.api.browse.trash', { kind: row.kind, name: row.name })
  }
  await load()
}

async function uploadTree(parent, dropped, batchLabel) {
  const paths = [
    ...dropped.folders.map((folder) => `${folder}/`),
    ...dropped.files.map((item) => item.relativePath),
  ]
  let targets = { folders: {}, files: dropped.files.map((item) => item.relativePath) }
  if (paths.some((path) => path.includes('/'))) {
    targets = await api('mpd_customizations.drive.api.browse.ensure_folder_tree', { parent, paths })
  }
  const keep = new Set(targets.files || [])
  const label = batchLabel || dropped.files[0]?.relativePath.split('/')[0] || 'Upload'
  const tasks = []
  for (const item of dropped.files) {
    if (item.relativePath.includes('/') && !keep.has(item.relativePath)) continue
    const dir = item.relativePath.includes('/') ? item.relativePath.split('/').slice(0, -1).join('/') : ''
    const folder = dir ? targets.folders[dir] : parent
    if (!folder) continue
    const entry = reactive({
      name: item.file.name,
      file: item.file,
      folder,
      progress: 0,
      status: 'uploading',
      error: '',
      batch: label,
    })
    uploads.value.push(entry)
    tasks.push(() => runUpload(item.file, folder, entry))
  }
  await runPool(tasks, 4)
  await load()
}

async function acceptExternalDrop(dataTransfer, parent) {
  const dropped = await readDroppedItems(dataTransfer)
  if (!parent) {
    error.value = 'Open a folder before uploading.'
    return
  }
  if (!dropped.files.length && !dropped.folders.length) return
  await uploadTree(parent, dropped)
}

function skipDuplicate(entry) {
  entry.status = 'skipped'
}

function skipAllDuplicates() {
  for (const entry of uploads.value) {
    if (entry.status === 'duplicate') entry.status = 'skipped'
  }
}

async function keepCopy(entry) {
  await runUpload(entry.file, entry.folder, entry, { allowCopy: true })
  await load()
}

async function keepAllCopies() {
  const pending = uploads.value.filter((entry) => entry.status === 'duplicate')
  await runPool(pending.map((entry) => () => keepCopy(entry)), 4)
}

async function addAiInput() {
  const folder = listing.value.folder?.name
  if (!folder) return
  await api('mpd_customizations.drive.api.browse.ensure_ai_input', { folder })
  await load()
}

async function openInboxSettings() {
  const folder = listing.value.folder
  const roots = await api('mpd_customizations.drive.api.browse.list_folder')
  targetFolders.value = roots.folders || []
  inboxForm.value = {
    is_ai_inbox: 1,
    inbox_kind: folder.inbox_kind || 'General',
    organise_into: folder.organise_into || folder.parent_drive_folder || folder.name,
  }
  dialogs.inbox = true
}

async function saveInbox() {
  await api('mpd_customizations.drive.api.sharing.set_inbox', {
    folder: listing.value.folder.name,
    ...inboxForm.value,
  })
  dialogs.inbox = false
  await load()
}

function onDragOver(event) {
  if (draggingItem.value?.length) {
    dragging.value = false
    return
  }
  dragging.value = true
  event.preventDefault()
}

async function onDrop(event) {
  dragging.value = false
  dropTarget.value = null
  if (draggingItem.value?.length) {
    draggingItem.value = null
    return
  }
  await acceptExternalDrop(event.dataTransfer, listing.value.folder?.name)
}

function itemTileClass(item) {
  if (dropTarget.value === item.name) return 'border-[#1a73e8] bg-[#e8f0fe]'
  if (selected.value.includes(item.name)) return 'border-[#c2e7ff] bg-[#c2e7ff]'
  return 'border-[#dadce0] bg-white hover:bg-[#f1f3f4]'
}

function formatSize(size) {
  if (!size) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

onMounted(() => document.addEventListener('click', closeMenu))
onUnmounted(() => {
  document.removeEventListener('click', closeMenu)
  window.clearTimeout(reorgTimer)
})
</script>

<template>
  <div
    class="relative flex h-full flex-col"
    @dragover="onDragOver"
    @dragleave.prevent="dragging = false"
    @drop.prevent="onDrop"
  >
    <header class="flex items-center gap-3 border-b border-gray-200 bg-white px-4 py-3">
      <button
        v-if="backTo"
        class="rounded-full px-3 py-1.5 text-sm text-[#1a73e8] hover:bg-[#e8f0fe]"
        @click="router.push(backTo)"
      >
        Back
      </button>
      <Button v-if="mode === 'folder' || mode === 'home'" variant="solid" label="New" @click="dialogs.folder = true" />
      <Button v-if="canEdit" variant="outline" label="Upload files" @click="pickFiles" />
      <Button v-if="canEdit" variant="outline" label="Upload folder" @click="pickFolder" />
      <Button
        v-if="canEdit && listing.folder && !listing.folder.is_ai_inbox && !hasAiInput"
        variant="outline"
        label="Add AI Input"
        @click="addAiInput"
      />
      <Button v-if="canManage && listing.folder?.is_ai_inbox" variant="outline" label="AI target" @click="openInboxSettings" />
      <Button
        v-if="canEdit && listing.folder"
        variant="outline"
        :label="listing.folder.check_duplicates ? 'Duplicate check on' : 'Duplicate check off'"
        @click="toggleDuplicateCheck(listing.folder)"
      />
      <Button
        v-if="canEdit && listing.folder"
        variant="outline"
        label="Reorganize"
        @click="openReorganize"
      />
      <Button v-if="selectedFiles.length >= 2" variant="outline" label="Download ZIP" @click="downloadZip" />
      <Button v-if="selectedItems.length && canEdit" variant="outline" label="Move" @click="openMove()" />
      <Button
        v-if="selectedItems.length && canEdit && mode !== 'trash'"
        variant="outline"
        label="Move to trash"
        @click="trashSelected()"
      />
      <span v-if="selectedItems.length > 1" class="text-sm text-[#5f6368]">{{ selectedItems.length }} selected</span>
      <input ref="fileInput" class="hidden" type="file" multiple @change="onFiles" />
      <input ref="folderInput" class="hidden" type="file" webkitdirectory multiple @change="onFiles" />
      <nav class="flex min-w-0 flex-1 items-center gap-1 truncate text-sm text-[#3c4043]">
        <button class="shrink-0 hover:underline" @click="router.push('/')">My Drive</button>
        <template v-if="searchQuery">
          <span class="shrink-0 text-[#5f6368]">/</span>
          <span class="truncate">Results for “{{ searchQuery }}”</span>
        </template>
        <template v-for="crumb in listing.breadcrumbs || []" :key="crumb.name">
          <span class="shrink-0 text-[#5f6368]">/</span>
          <button class="truncate hover:underline" @click="router.push(`/folder/${crumb.name}`)">{{ crumb.title }}</button>
        </template>
      </nav>
      <select v-model="sortKey" class="rounded border border-gray-300 px-2 py-1 text-sm">
        <option value="title">Name</option>
        <option value="modified">Modified</option>
        <option value="size">Size</option>
      </select>
      <button class="text-sm text-gray-600" @click="viewMode = viewMode === 'grid' ? 'list' : 'grid'">
        {{ viewMode === 'grid' ? 'List' : 'Grid' }}
      </button>
    </header>

    <p v-if="listing.folder?.purpose" class="px-4 pt-3 text-sm text-[#5f6368]">{{ listing.folder.purpose }}</p>
    <p v-if="error" class="bg-red-50 px-4 py-2 text-sm text-red-700">{{ error }}</p>
    <p v-if="notice" class="bg-blue-50 px-4 py-2 text-sm text-blue-800">{{ notice }}</p>

    <div
      v-if="dragging"
      class="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-blue-50/80 text-lg text-blue-800"
    >
      Drop files to upload
    </div>

    <section class="flex min-h-0 flex-1">
      <div class="min-w-0 flex-1 overflow-auto p-4" @click="selected = []">
        <div v-if="viewMode === 'grid'" class="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3">
          <button
            v-for="item in items"
            :key="item.name"
            class="flex items-center gap-3 rounded-2xl border px-3 py-2.5 text-left"
            :class="itemTileClass(item)"
            :draggable="canDrag(item)"
            @click.stop="onItemClick($event, item)"
            @dblclick="openItem(item)"
            @contextmenu="onContext($event, item)"
            @dragstart="onItemDragStart($event, item)"
            @dragend="onItemDragEnd"
            @dragover="onItemDragOver($event, item)"
            @drop="onItemDrop($event, item)"
          >
            <ItemIcon :kind="item.kind" :title="item.title" />
            <span class="min-w-0">
              <span class="block truncate text-sm text-[#202124]">{{ item.title }}</span>
              <span v-if="item.kind === 'folder' && item.purpose" class="block truncate text-xs text-[#5f6368]">{{ item.purpose }}</span>
              <span v-if="item.is_ai_inbox" class="block truncate text-xs text-[#1a73e8]">Drop files to organise</span>
              <span v-else-if="item.check_duplicates" class="block truncate text-xs text-[#1a73e8]">Duplicate check on</span>
              <span v-else-if="item.original_filename && item.original_filename !== item.title" class="block truncate text-xs text-[#5f6368]">
                {{ item.original_filename }}
              </span>
              <span v-else-if="item.ai_status || item.size" class="block truncate text-xs text-[#5f6368]">
                {{ item.ai_status || formatSize(item.size) }}
              </span>
            </span>
          </button>
        </div>
        <table v-else class="w-full text-left text-sm">
          <thead class="text-xs uppercase text-[#5f6368]">
            <tr>
              <th class="py-2 font-medium">Name</th>
              <th class="font-medium">Modified</th>
              <th class="font-medium">Size</th>
              <th class="font-medium">AI</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in items"
              :key="item.name"
              class="cursor-pointer border-t border-[#e8eaed] hover:bg-white"
              :class="dropTarget === item.name ? 'bg-[#e8f0fe]' : ''"
              :draggable="canDrag(item)"
              @dblclick="openItem(item)"
              @contextmenu="onContext($event, item)"
              @click.stop="onItemClick($event, item)"
              @dragstart="onItemDragStart($event, item)"
              @dragend="onItemDragEnd"
              @dragover="onItemDragOver($event, item)"
              @drop="onItemDrop($event, item)"
            >
              <td class="py-2">
                <span class="flex items-center gap-3">
                  <ItemIcon :kind="item.kind" :title="item.title" />
                  <span class="min-w-0">
                    <span class="block truncate">{{ item.title }}</span>
                    <span v-if="item.kind === 'folder' && item.purpose" class="block truncate text-xs text-[#5f6368]">{{ item.purpose }}</span>
                  </span>
                  <span v-if="item.check_duplicates" class="ml-2 text-xs text-[#1a73e8]">Duplicate check</span>
                </span>
              </td>
              <td class="text-[#5f6368]">{{ item.modified }}</td>
              <td class="text-[#5f6368]">{{ formatSize(item.size) }}</td>
              <td class="text-[#5f6368]">{{ item.ai_status }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="!items.length" class="py-16 text-center text-gray-500">Nothing here yet.</p>

        <div v-if="mode === 'review'" class="mt-4 space-y-3">
          <article v-for="item in listing.files" :key="item.name" class="rounded-lg bg-white p-4 shadow-sm">
            <div class="font-medium">{{ item.title }}</div>
            <p class="text-sm text-gray-600">{{ item.ai_summary }}</p>
            <p class="text-xs text-gray-500">Suggested: {{ item.ai_suggested_path }}</p>
            <div class="mt-2 flex gap-2">
              <Button variant="solid" label="Accept" @click="acceptReview(item, false)" />
              <Button variant="outline" label="Edit" @click="editReview(item)" />
              <Button variant="outline" label="Re-run AI" @click="rerun(item)" />
            </div>
          </article>
        </div>
      </div>

      <aside v-if="details" class="w-80 shrink-0 overflow-auto border-l border-gray-200 bg-white p-4 text-sm">
        <div class="mb-2 flex items-center justify-between">
          <h2 class="font-medium">{{ details.title }}</h2>
          <button @click="details = null">Close</button>
        </div>
        <template v-if="details.kind === 'folder'">
          <h3 class="text-xs text-gray-500">Meaning</h3>
          <textarea
            v-model="purposeDraft"
            rows="4"
            class="mt-1 w-full rounded border border-gray-300 p-2 text-sm"
            placeholder="What belongs in this folder"
          />
          <p class="mt-1 text-xs text-gray-500">
            <template v-if="details.purpose_custom">You wrote this. A reorganization keeps it.</template>
            <template v-else-if="details.purpose">Written by the filing model from the files here. Saving your own wording keeps it.</template>
            <template v-else>The filing model writes this after files land here. You can write it yourself.</template>
          </p>
          <Button class="mt-2" variant="outline" label="Save meaning" @click="savePurpose" />
        </template>
        <h3 v-else class="text-xs text-gray-500">Overview</h3>
        <p v-if="details.kind !== 'folder'" class="mt-1 text-gray-600">{{ details.ai_summary || 'No overview yet.' }}</p>
        <dl v-if="details.kind !== 'folder'" class="mt-3 space-y-1 text-xs">
          <div><dt class="text-gray-500">Type</dt><dd>{{ details.ai_document_type }}</dd></div>
          <div><dt class="text-gray-500">Subject</dt><dd>{{ details.ai_subject }}</dd></div>
          <div><dt class="text-gray-500">Date</dt><dd>{{ details.ai_document_date }}</dd></div>
          <div><dt class="text-gray-500">Tags</dt><dd>{{ details.ai_tags }}</dd></div>
          <div><dt class="text-gray-500">Status</dt><dd>{{ details.ai_status }}</dd></div>
          <div><dt class="text-gray-500">Facts</dt><dd class="whitespace-pre-wrap">{{ details.ai_context }}</dd></div>
          <div v-if="details.routed_to_name">
            <dt class="text-gray-500">Routed</dt>
            <dd>
              <a class="text-blue-700" :href="`/app/${(details.routed_to_doctype || '').toLowerCase().replaceAll(' ', '-')}/${details.routed_to_name}`">
                {{ details.routed_to_name }}
              </a>
            </dd>
          </div>
        </dl>
        <label v-if="details.kind === 'folder' && canEditItem(details)" class="mt-3 flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            :checked="!!details.check_duplicates"
            @change="toggleDuplicateCheck(details, $event.target.checked)"
          />
          <span>Check duplicates in this folder and the folders inside it. The match is the file contents, not the name.</span>
        </label>
        <Button v-if="details.kind === 'file'" class="mt-3" variant="outline" label="Re-run AI" @click="rerun(details)" />
      </aside>
    </section>

    <div v-if="uploads.length" class="absolute bottom-4 right-4 w-80 rounded-lg bg-white p-3 shadow-lg">
      <div class="mb-2 text-sm font-medium">Uploads</div>
      <p v-if="uploads.some((entry) => entry.batch)" class="mb-2 text-xs text-gray-500">
        {{ uploads.find((entry) => entry.batch)?.batch }} —
        {{ uploads.filter((entry) => entry.status === 'done' || entry.status === 'duplicate' || entry.status === 'error' || entry.status === 'skipped').length }}/{{ uploads.length }}
      </p>
      <div v-for="entry in uploads" :key="entry.name + entry.status" class="mb-2 text-xs">
        <div class="flex justify-between">
          <span class="truncate">{{ entry.name }}</span>
          <button v-if="entry.status === 'uploading'" @click="cancelUpload(entry)">Cancel</button>
          <button v-else-if="entry.status === 'error'" @click="runUpload(entry.file, entry.folder, entry)">Retry</button>
        </div>
        <div class="mt-1 h-1.5 rounded bg-gray-100">
          <div class="h-1.5 rounded bg-blue-600" :style="{ width: entry.progress + '%' }" />
        </div>
        <p v-if="entry.status === 'duplicate'" class="text-amber-800">
          Already in {{ entry.duplicate?.path || 'Drive' }}
          <button class="ml-2 text-[#1a73e8]" @click="skipDuplicate(entry)">Skip</button>
          <button class="ml-2 text-[#1a73e8]" @click="keepCopy(entry)">Keep a copy</button>
        </p>
        <p v-if="entry.error" class="text-red-600">{{ entry.error }}</p>
      </div>
      <div v-if="duplicateUploads.length" class="mt-2 flex gap-2">
        <button class="text-[#1a73e8]" @click="skipAllDuplicates">Skip all duplicates</button>
        <button class="text-[#1a73e8]" @click="keepAllCopies">Keep all copies</button>
      </div>
    </div>

    <div
      v-if="menu"
      class="fixed z-20 min-w-40 rounded-md bg-white py-1 text-sm shadow-lg"
      :style="{ left: menu.x + 'px', top: menu.y + 'px' }"
      @click.stop
    >
      <button class="block w-full px-3 py-1.5 text-left hover:bg-gray-100" @click="openItem(menu.item); closeMenu()">Open</button>
      <button v-if="menu.item.kind === 'file'" class="block w-full px-3 py-1.5 text-left hover:bg-gray-100" @click="preview(menu.item); closeMenu()">Preview</button>
      <button v-if="menu.item.kind === 'file' && !(selectedFiles.length >= 2 && selected.includes(menu.item.name))" class="block w-full px-3 py-1.5 text-left hover:bg-gray-100" @click="download(menu.item); closeMenu()">Download</button>
      <button v-if="selectedFiles.length >= 2 && selected.includes(menu.item.name)" class="block w-full px-3 py-1.5 text-left hover:bg-gray-100" @click="downloadZip(); closeMenu()">Download ZIP</button>
      <button class="block w-full px-3 py-1.5 text-left hover:bg-gray-100" @click="rename(menu.item); closeMenu()">Rename</button>
      <button class="block w-full px-3 py-1.5 text-left hover:bg-gray-100" @click="openMove(menu.item); closeMenu()">Move</button>
      <button v-if="menu.item.kind === 'folder'" class="block w-full px-3 py-1.5 text-left hover:bg-gray-100" @click="openShare(menu.item); closeMenu()">Share</button>
      <button v-if="menu.item.kind === 'folder' && canEditItem(menu.item)" class="block w-full px-3 py-1.5 text-left hover:bg-gray-100" @click="toggleDuplicateCheck(menu.item); closeMenu()">
        {{ menu.item.check_duplicates ? 'Turn duplicate check off' : 'Turn duplicate check on' }}
      </button>
      <button class="block w-full px-3 py-1.5 text-left hover:bg-gray-100" @click="showDetails(menu.item); closeMenu()">Details</button>
      <button v-if="mode !== 'trash'" class="block w-full px-3 py-1.5 text-left hover:bg-gray-100" @click="trashSelected(menu.item); closeMenu()">Move to trash</button>
      <button v-else class="block w-full px-3 py-1.5 text-left hover:bg-gray-100" @click="trashSelected(menu.item); closeMenu()">Restore</button>
      <button v-if="mode === 'trash'" class="block w-full px-3 py-1.5 text-left text-red-700 hover:bg-gray-100" @click="removeForever(menu.item); closeMenu()">Delete forever</button>
    </div>

    <Dialog v-model="dialogs.folder" :options="{ title: 'New folder' }">
      <template #body-content>
        <input v-model="folderTitle" class="w-full rounded border px-3 py-2" placeholder="Folder name" />
        <Button class="mt-3" variant="solid" label="Create" @click="createFolder" />
      </template>
    </Dialog>

    <Dialog v-model="dialogs.share" :options="{ title: 'Share' }">
      <template #body-content>
        <label class="mb-2 flex items-center gap-2 text-sm">
          <input v-model="share.inherit_permissions" type="checkbox" />
          Inherit from parent
        </label>
        <div v-for="(rule, index) in share.rules" :key="index" class="mb-2 flex items-start gap-2 text-sm">
          <select class="rounded border px-1" :value="rule.principal_type" @change="onPrincipalType(rule, $event.target.value)">
            <option>Role</option>
            <option>User</option>
          </select>
          <div class="min-w-0 flex-1 text-left">
            <input
              class="w-full rounded border px-2 py-1"
              :placeholder="rule.principal_type === 'Role' ? 'Role' : 'User'"
              :value="rule.typing ? rule.draft : principalValue(rule)"
              @focus="onPrincipalFocus(rule)"
              @input="onPrincipalInput(rule, $event.target.value)"
              @blur="commitPrincipal(rule)"
            />
            <ul v-if="rule.open" class="mt-1 max-h-36 overflow-auto rounded border bg-white shadow">
              <li
                v-for="option in filteredPrincipals(rule)"
                :key="option.value"
                class="cursor-pointer px-2 py-1 hover:bg-[#f1f3f4]"
                @mousedown.prevent="choosePrincipal(rule, option)"
              >
                {{ option.label }}
              </li>
              <li v-if="!filteredPrincipals(rule).length" class="px-2 py-1 text-gray-500">No matches</li>
            </ul>
          </div>
          <select v-model="rule.level" class="rounded border px-1">
            <option>View</option>
            <option>Edit</option>
            <option>Manage</option>
          </select>
        </div>
        <Button variant="outline" label="Add" @click="addRule" />
        <Button class="ml-2" variant="solid" label="Save" @click="saveShare" />
      </template>
    </Dialog>

    <Dialog v-model="dialogs.move" :options="{ title: moveTitle }">
      <template #body-content>
        <nav class="mb-3 flex flex-wrap items-center gap-1 text-sm text-[#3c4043]">
          <button class="text-[#1a73e8] hover:underline" @click="moveToCrumb(-1)">My Drive</button>
          <template v-for="(crumb, index) in moveCrumbs" :key="crumb.name">
            <span class="text-[#5f6368]">/</span>
            <button class="hover:underline" @click="moveToCrumb(index)">{{ crumb.title }}</button>
          </template>
        </nav>
        <button
          v-for="folder in moveChoices"
          :key="folder.name"
          class="block w-full rounded px-2 py-1.5 text-left text-sm hover:bg-[#f1f3f4]"
          @click="drill(folder)"
        >
          {{ folder.title }}
        </button>
        <p v-if="!moveChoices.length" class="py-3 text-sm text-gray-500">No folders in here.</p>
        <p v-if="moveError" class="mt-2 text-sm text-red-700">{{ moveError }}</p>
        <Button
          class="mt-3"
          variant="solid"
          :label="moveCrumbs.length ? `Move here` : 'Choose a folder'"
          :disabled="!canMoveHere"
          @click="confirmMove"
        />
      </template>
    </Dialog>

    <Dialog v-model="dialogs.preview" :options="{ title: previewTitle, size: '4xl' }">
      <template #body-content>
        <iframe v-if="previewUrl" :src="previewUrl" class="h-[70vh] w-full" />
      </template>
    </Dialog>

    <Dialog v-model="dialogs.review" :options="{ title: 'Edit suggestion' }">
      <template #body-content>
        <input v-model="reviewForm.title" class="mb-2 w-full rounded border px-2 py-1" placeholder="Name" />
        <input v-model="reviewForm.subject" class="mb-2 w-full rounded border px-2 py-1" placeholder="Subject" />
        <input v-model="reviewForm.year" class="mb-2 w-full rounded border px-2 py-1" placeholder="FY 2026-27" />
        <Button variant="solid" label="File" @click="acceptReview(reviewForm.item, true)" />
      </template>
    </Dialog>

    <Dialog v-model="dialogs.inbox" :options="{ title: 'Where should AI file these?' }">
      <template #body-content>
        <p class="mb-2 text-sm text-gray-600">Files dropped in this AI Input folder are named and moved into the target. Pick the parent, or a folder outside it.</p>
        <select v-model="inboxForm.inbox_kind" class="mb-2 w-full rounded border px-2 py-1">
          <option>General</option>
          <option>Statutory Compliance</option>
        </select>
        <select v-model="inboxForm.organise_into" class="mb-3 w-full rounded border px-2 py-1">
          <option v-if="listing.folder?.parent_drive_folder" :value="listing.folder.parent_drive_folder">Parent folder</option>
          <option v-for="folder in targetFolders" :key="folder.name" :value="folder.name">{{ folder.title }}</option>
        </select>
        <Button variant="solid" label="Save" @click="saveInbox" />
      </template>
    </Dialog>

    <Dialog v-model="dialogs.reorganize" :options="{ title: 'Reorganize' }">
      <template #body-content>
        <label class="mb-1 block text-sm text-gray-600">What should this do?</label>
        <textarea v-model="reorganizeForm.instruction" class="mb-3 w-full rounded border px-2 py-1" rows="3" placeholder="Optional. For example: group GST files under Challans" />
        <label class="mb-1 block text-sm text-gray-600">What the AI reads</label>
        <select v-model="reorganizeForm.input_mode" class="mb-3 w-full rounded border px-2 py-1" @change="reorganizeForm.input_mode === 'Name only' && (reorganizeForm.preview = true)">
          <option>Full JSON</option>
          <option>Name only</option>
        </select>
        <label class="mb-3 flex items-center gap-2 text-sm">
          <input v-model="reorganizeForm.preview" type="checkbox" :disabled="reorganizeForm.input_mode === 'Name only'" />
          Review before moving
        </label>
        <Button variant="solid" label="Reorganize" @click="startReorganize" />
      </template>
    </Dialog>

    <Dialog v-model="dialogs.reorganizePreview" :options="{ title: 'Reorganize plan', size: '4xl' }">
      <template #body-content>
        <ReorganizePanel :run="reorgRun" @apply="applyReorganize" @cancel="cancelReorganize" @revise="reviseReorganize" />
      </template>
    </Dialog>
  </div>
</template>

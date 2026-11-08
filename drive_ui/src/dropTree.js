const JUNK = new Set(['.ds_store', 'thumbs.db', 'desktop.ini'])

export function isJunk(name) {
  return JUNK.has(String(name || '').toLowerCase())
}

function fileOf(entry) {
  return new Promise((resolve, reject) => entry.file(resolve, reject))
}

function readDirectory(entry) {
  return new Promise((resolve, reject) => {
    const reader = entry.createReader()
    const all = []
    const read = () => {
      reader.readEntries((batch) => {
        if (!batch.length) resolve(all)
        else {
          all.push(...batch)
          read()
        }
      }, reject)
    }
    read()
  })
}

async function walk(entry, path, files, folders) {
  if (entry.isFile) {
    const file = await fileOf(entry)
    if (!isJunk(file.name)) files.push({ relativePath: `${path}${file.name}`, file })
    return
  }
  if (!entry.isDirectory) return
  const dir = `${path}${entry.name}`
  const children = await readDirectory(entry)
  if (!children.length) folders.push(dir)
  for (const child of children) await walk(child, `${dir}/`, files, folders)
}

export function readDroppedItems(dataTransfer) {
  const items = [...(dataTransfer?.items || [])]
  const entries = []
  for (const item of items) {
    const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null
    if (entry) entries.push(entry)
  }
  if (!entries.length) {
    const files = [...(dataTransfer?.files || [])]
      .filter((file) => !isJunk(file.name))
      .map((file) => ({ relativePath: file.webkitRelativePath || file.name, file }))
    return Promise.resolve({ files, folders: [] })
  }
  return (async () => {
    const files = []
    const folders = []
    for (const entry of entries) await walk(entry, '', files, folders)
    return { files, folders }
  })()
}

export async function runPool(tasks, limit = 4) {
  const queue = [...tasks]
  const size = Math.min(limit, queue.length)
  const workers = Array.from({ length: size }, async () => {
    while (queue.length) {
      const task = queue.shift()
      await task()
    }
  })
  await Promise.all(workers)
}

function csrfToken() {
  if (window.csrf_token && window.csrf_token !== '{{ csrf_token }}') {
    return window.csrf_token
  }
  const match = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

function errorMessage(data) {
  if (data._server_messages) {
    try {
      const messages = JSON.parse(data._server_messages)
      return JSON.parse(messages[0]).message
    } catch {
      return 'Request failed'
    }
  }
  return data.message || data.exc || 'Request failed'
}

export async function api(method, args = {}) {
  const response = await fetch(`/api/method/${method}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'X-Frappe-CSRF-Token': csrfToken(),
    },
    body: JSON.stringify(args),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok || data.exc) {
    throw new Error(errorMessage(data))
  }
  return data.message
}

export async function downloadBlob(method, args, filename) {
  const response = await fetch(`/api/method/${method}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      'X-Frappe-CSRF-Token': csrfToken(),
    },
    body: JSON.stringify(args),
  })
  const type = response.headers.get('content-type') || ''
  if (!response.ok || type.includes('application/json')) {
    const data = await response.json().catch(() => ({}))
    throw new Error(errorMessage(data))
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename || 'download'
  link.click()
  URL.revokeObjectURL(url)
}

export function postFile(fileId, file, onProgress, extra = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/method/mpd_customizations.drive.api.upload.receive_upload')
    xhr.setRequestHeader('Accept', 'application/json')
    xhr.setRequestHeader('X-Frappe-CSRF-Token', csrfToken())
    const body = new FormData()
    body.append('file_id', fileId)
    if (extra.allow_copy) body.append('allow_copy', '1')
    body.append('file', file, file.name)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded, event.total)
    }
    xhr.onload = () => {
      const data = JSON.parse(xhr.responseText || '{}')
      if (xhr.status >= 200 && xhr.status < 300 && !data.exc) resolve(data.message)
      else reject(new Error(errorMessage(data) || `Upload failed (${xhr.status})`))
    }
    xhr.onerror = () => reject(new Error('Upload failed'))
    xhr.send(body)
  })
}

export function putWithProgress(url, body, contentType, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', url)
    if (contentType) xhr.setRequestHeader('Content-Type', contentType)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded, event.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve((xhr.getResponseHeader('ETag') || '').replaceAll('"', ''))
      } else {
        reject(new Error(`Upload failed (${xhr.status})`))
      }
    }
    xhr.onerror = () => reject(new Error('Upload failed'))
    xhr.send(body)
  })
}

function csrfToken() {
  if (window.csrf_token && window.csrf_token !== '{{ csrf_token }}') return window.csrf_token
  const match = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

function errorMessage(data) {
  if (data._server_messages) {
    try {
      return JSON.parse(JSON.parse(data._server_messages)[0]).message
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
  if (!response.ok || data.exc) throw new Error(errorMessage(data))
  return data.message
}

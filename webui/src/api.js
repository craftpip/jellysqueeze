const BASE = ''

export async function api(method, path, body) {
  const opts = { method, headers: {} }
  if (body) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const r = await fetch(BASE + path, opts)
  const data = await r.json().catch(() => ({}))
  if (!r.ok) {
    throw new Error(data.detail || data.error || `Request failed (${r.status})`)
  }
  return data
}

export function relTime(ts) {
  if (!ts) return 'Never'
  const sec = Math.floor(Date.now() / 1000 - ts)
  if (sec < 60) return 'just now'
  if (sec < 3600) return Math.floor(sec / 60) + 'm ago'
  if (sec < 86400) return Math.floor(sec / 3600) + 'h ago'
  return Math.floor(sec / 86400) + 'd ago'
}

export function encTag(enc) {
  const e = enc || 'nvidia'
  const cls = e === 'cpu' ? 'tag ok' : 'tag skip'
  return `<span class="${cls}">${e}</span>`
}

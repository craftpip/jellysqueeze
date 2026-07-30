import { useState, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api } from '../api'

export default function Settings() {
  const { setPageTitle } = useOutletContext()
  useEffect(() => setPageTitle('Settings'), [setPageTitle])
  const [form, setForm] = useState({
    TARGET_BR: '', MAX_BR: '', DEFAULT_CRF: '',
    JELLYFIN_BASE_URL: '', JELLYFIN_API_KEY: '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api('GET', '/api/env').then(data => {
      setForm({
        TARGET_BR: data.TARGET_BR || '',
        MAX_BR: data.MAX_BR || '',
        DEFAULT_CRF: data.DEFAULT_CRF || '',
        JELLYFIN_BASE_URL: data.JELLYFIN_BASE_URL || '',
        JELLYFIN_API_KEY: '',
      })
    }).catch(err => setError(err.message))
  }, [])

  const set = (key) => (e) => setForm(f => ({ ...f, [key]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    const body = {}
    Object.entries(form).forEach(([k, v]) => { if (v) body[k] = v })
    try {
      await api('POST', '/api/env', body)
      alert('Settings saved.')
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card">
      <h3>Settings</h3>
      {error && <div className="error-message">{error}</div>}
      <form onSubmit={submit}>
        <div className="form-row">
          <div className="field">
            <label>Target bitrate (kbps)</label>
            <input type="text" value={form.TARGET_BR} onChange={set('TARGET_BR')} />
          </div>
          <div className="field">
            <label>Max bitrate (kbps)</label>
            <input type="text" value={form.MAX_BR} onChange={set('MAX_BR')} />
          </div>
          <div className="field">
            <label>CRF (CPU mode)</label>
            <input type="text" value={form.DEFAULT_CRF} onChange={set('DEFAULT_CRF')} />
          </div>
        </div>
        <div className="form-row">
          <div className="field">
            <label>Jellyfin URL</label>
            <input type="text" value={form.JELLYFIN_BASE_URL} onChange={set('JELLYFIN_BASE_URL')} placeholder="http://jellyfin:8096" />
          </div>
          <div className="field">
            <label>Jellyfin API Key</label>
            <input type="password" value={form.JELLYFIN_API_KEY} onChange={set('JELLYFIN_API_KEY')} placeholder="(hidden, enter to change)" />
          </div>
        </div>
        <button type="submit" className={`btn primary${saving ? ' loading' : ''}`} disabled={saving}>Save Settings</button>
      </form>
    </div>
  )
}

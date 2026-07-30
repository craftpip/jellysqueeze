import { useState, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api } from '../api'

const s = {
  section: { marginBottom: 28 },
  h3: { fontSize: 11, fontWeight: 600, color: '#666', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 14, paddingBottom: 6, borderBottom: '1px solid #2a2a2a' },
}

const Hint = ({ children }) => (
  <span style={{ display: 'block', fontSize: 11, color: '#555', lineHeight: 1.3, marginTop: 2 }}>{children}</span>
)

export default function Settings() {
  const { setPageTitle } = useOutletContext()
  useEffect(() => setPageTitle('Settings'), [setPageTitle])

  const [form, setForm] = useState({
    BUFSIZE: '', DEFAULT_CRF: '',
    DEFAULT_WORKERS: '',
    JELLYFIN_BASE_URL: '', JELLYFIN_API_KEY: '',
    DEFAULT_EXCLUDE: '', DEFAULT_IGNORE_PATH: '',
    CLEANUP_TMP: false, BACKUP_ORIGINALS: false,
    FFMPEG_BIN: '', FFPROBE_BIN: '',
  })
  const [sysinfo, setSysinfo] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const [testResult, setTestResult] = useState(null)
  const [testing, setTesting] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)

  useEffect(() => {
    api('GET', '/api/env').then(data => {
      setForm({
        BUFSIZE: data.BUFSIZE ?? '',
        DEFAULT_CRF: data.DEFAULT_CRF ?? '',
        DEFAULT_WORKERS: data.DEFAULT_WORKERS ?? '',
        JELLYFIN_BASE_URL: data.JELLYFIN_BASE_URL ?? '',
        JELLYFIN_API_KEY: '',
        DEFAULT_EXCLUDE: data.DEFAULT_EXCLUDE ?? '',
        DEFAULT_IGNORE_PATH: data.DEFAULT_IGNORE_PATH ?? '',
        CLEANUP_TMP: !!data.CLEANUP_TMP,
        BACKUP_ORIGINALS: !!data.BACKUP_ORIGINALS,
        FFMPEG_BIN: data.FFMPEG_BIN ?? '',
        FFPROBE_BIN: data.FFPROBE_BIN ?? '',
      })
    }).catch(err => setError(err.message))
    api('GET', '/api/system-info').then(setSysinfo).catch(() => {})
  }, [])

  const set = (key) => (e) => {
    const val = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm(f => ({ ...f, [key]: val }))
  }

  const submit = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    const body = {}
    Object.entries(form).forEach(([k, v]) => {
      if (k === 'JELLYFIN_API_KEY' && !v) return
      if (typeof v === 'boolean') { body[k] = v ? '1' : '0'; return }
      if (v !== '' && v !== null && v !== undefined) body[k] = v
    })
    try {
      await api('POST', '/api/env', body)
      setSaving(false)
      setSaved(true)
      setError('')
      setTimeout(() => setSaved(false), 3000)
    } catch (err) {
      setError(err.message)
      setSaving(false)
    }
  }

  const testConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const data = await api('POST', '/api/test-jellyfin', {
        url: form.JELLYFIN_BASE_URL || undefined,
        key: form.JELLYFIN_API_KEY || undefined,
      })
      setTestResult(data)
    } catch (err) {
      setTestResult({ ok: false, message: err.message })
    } finally {
      setTesting(false)
    }
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', gap: 28, alignItems: 'flex-start' }}>
      <div style={{ flex: 3, minWidth: 0 }}>
        {error && <div className="error-message">{error}</div>}

        <div style={s.section}>
          <h3 style={s.h3}>Conversion</h3>
          <div className="form-row">
            <div className="field">
              <label>Buffer size (kbps)</label>
              <input type="text" value={form.BUFSIZE} onChange={set('BUFSIZE')} placeholder="6600" />
              <Hint>FFmpeg rate-control buffer</Hint>
            </div>
            <div className="field">
              <label>CRF (CPU mode)</label>
              <input type="text" value={form.DEFAULT_CRF} onChange={set('DEFAULT_CRF')} placeholder="23" />
              <Hint>Lower is better quality. Range 18–28.</Hint>
            </div>
            <div className="field">
              <label>Workers</label>
              <input type="text" value={form.DEFAULT_WORKERS} onChange={set('DEFAULT_WORKERS')} placeholder="1" />
              <Hint>Parallel file conversions</Hint>
            </div>
          </div>
        </div>

        <div style={s.section}>
          <h3 style={s.h3}>Jellyfin</h3>
          <div className="form-row">
            <div className="field">
              <label>Server URL</label>
              <input type="text" value={form.JELLYFIN_BASE_URL} onChange={set('JELLYFIN_BASE_URL')} placeholder="http://jellyfin:8096" />
              <Hint>Base URL including port</Hint>
            </div>
            <div className="field">
              <label>API Key</label>
              <input type="password" value={form.JELLYFIN_API_KEY} onChange={set('JELLYFIN_API_KEY')} placeholder="(hidden, enter to change)" />
              <Hint>From Jellyfin Dashboard → API Keys</Hint>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
            <button type="button" className="btn outline" onClick={testConnection} disabled={testing}>
              {testing ? 'Testing...' : 'Test Connection'}
            </button>
            {testResult && (
              <span style={{ fontSize: 12, color: testResult.ok ? '#33ff33' : '#e05050' }}>
                {testResult.ok ? '✓ ' : '✗ '}{testResult.message}
              </span>
            )}
          </div>
        </div>

        <div style={s.section}>
          <h3 style={{ ...s.h3, display: 'flex', alignItems: 'center', gap: 12, borderBottom: '1px solid #2a2a2a' }}>
            Advanced
            <button type="button" className="link-btn" onClick={() => setShowAdvanced(s => !s)}>
              {showAdvanced ? 'Hide' : 'Show'}
            </button>
          </h3>
          {showAdvanced && (
            <>
              <div className="form-row">
                <div className="field">
                  <label>FFmpeg path</label>
                  <input type="text" value={form.FFMPEG_BIN} onChange={set('FFMPEG_BIN')} placeholder="(default: from PATH)" />
                  <Hint>Custom ffmpeg binary</Hint>
                </div>
                <div className="field">
                  <label>FFprobe path</label>
                  <input type="text" value={form.FFPROBE_BIN} onChange={set('FFPROBE_BIN')} placeholder="(default: from PATH)" />
                  <Hint>Custom ffprobe binary</Hint>
                </div>
              </div>
              <div className="form-row">
                <div className="field">
              <label>Exclude directories from scanning</label>
              <input type="text" value={form.DEFAULT_EXCLUDE} onChange={set('DEFAULT_EXCLUDE')} placeholder="sample, extras" />
              <Hint>Skip these folder names during library scan</Hint>
                </div>
                <div className="field">
                  <label>Ignore paths</label>
                  <input type="text" value={form.DEFAULT_IGNORE_PATH} onChange={set('DEFAULT_IGNORE_PATH')} placeholder="media1t, archive" />
                  <Hint>Skip paths containing these substrings</Hint>
                </div>
              </div>
              <div className="form-row">
                <div className="field checkbox">
                  <input type="checkbox" checked={form.CLEANUP_TMP} onChange={set('CLEANUP_TMP')} id="ck-cleanup" />
                  <label htmlFor="ck-cleanup">Clean temp files before scan</label>
                  <Hint>Remove leftover .__transcoding__ files on start</Hint>
                </div>
                <div className="field checkbox">
                  <input type="checkbox" checked={form.BACKUP_ORIGINALS} onChange={set('BACKUP_ORIGINALS')} id="ck-orig" />
                  <label htmlFor="ck-orig">Keep original backup</label>
                  <Hint>Rename originals with .__original__ suffix</Hint>
                </div>
              </div>
            </>
          )}
        </div>

        <div style={{ marginBottom: 28, display: 'flex', alignItems: 'center', gap: 12 }}>
          <button type="submit" className={`btn primary${saving ? ' loading' : ''}`} disabled={saving}>
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
          {saved && <span style={{ color: '#33ff33', fontSize: 12 }}>Saved</span>}
        </div>
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={s.section}>
          <h3 style={s.h3}>System Info</h3>
          {sysinfo ? (
            <>
              <div className="detail-row">
                <span className="label">ffmpeg path</span>
                <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>{sysinfo.ffmpeg_path}</span>
              </div>
              <div className="detail-row">
                <span className="label">ffprobe path</span>
                <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>{sysinfo.ffprobe_path}</span>
              </div>
              <div className="detail-row">
                <span className="label">Encoders</span>
                <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>
                  {sysinfo.encoders && sysinfo.encoders.length > 0
                    ? sysinfo.encoders.join(', ')
                    : '(probing...)'}
                </span>
              </div>
              <div className="detail-row">
                <span className="label">GPU</span>
                <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>
                  {Object.entries(sysinfo.gpu || {}).filter(([, v]) => v).map(([k]) => k).join(', ') || 'none detected'}
                </span>
              </div>
              <div className="detail-row">
                <span className="label">Config</span>
                <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>
                  {sysinfo.config_found ? '✓ ' : '✗ '}{sysinfo.config_path}
                </span>
              </div>
              <div className="detail-row">
                <span className="label">.env</span>
                <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>{sysinfo.env_path}</span>
              </div>
            </>
          ) : (
            <div className="text-muted">Loading...</div>
          )}
        </div>
      </div>
    </form>
  )
}
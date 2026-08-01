import { useState, useEffect, useRef } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { api } from '../api'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const Hint = ({ children }) => (
  <span style={{ display: 'block', fontSize: 11, color: '#555', lineHeight: 1.3, marginTop: 2 }}>{children}</span>
)

const toBody = s => ({
  name: s.name,
  enabled: s.enabled !== false,
  repeat: s.repeat,
  day: s.day,
  time: s.time,
  mode: s.mode,
  library: s.library,
  flags: s.flags,
})

export default function Schedules() {
  const { setPageTitle } = useOutletContext()
  const navigate = useNavigate()
  const [schedules, setSchedules] = useState([])
  const [libraries, setLibraries] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const pollRef = useRef(null)

  useEffect(() => setPageTitle('Schedules'), [setPageTitle])

  const load = () => {
    api('GET', '/api/schedules').then(d => setSchedules(d.schedules || [])).catch(err => setError(err.message))
  }

  useEffect(() => {
    load()
    api('GET', '/api/libraries').then(d => setLibraries(d.libraries || [])).catch(() => {})
      .finally(() => setLoading(false))
    pollRef.current = setInterval(load, 15000)
    return () => clearInterval(pollRef.current)
  }, [])

  const scheduleLabel = s => {
    const t = s.time || '--:--'
    if (s.repeat === 'daily') return 'Daily at ' + t
    if (s.repeat === 'weekly') return 'Weekly on ' + (WEEKDAYS[s.day] ?? s.day) + ' at ' + t
    if (s.repeat === 'monthly') return 'Monthly on day ' + (s.day ?? '?') + ' at ' + t
    return s.repeat || '—'
  }

  const targetLabel = s => {
    if (s.mode === 'library') return 'Libraries: ' + (s.library || '—').split(',').filter(Boolean).join(', ')
    if (s.mode === 'jellyfin_recent') {
      const libs = (s.flags || {}).libraries || '—'
      return 'Recent: ' + libs + ' (' + ((s.flags || {}).since_hours || 72) + 'h)'
    }
    return '—'
  }

  const toggleEnabled = async (s) => {
    setError('')
    try {
      await api('PUT', '/api/schedules/' + encodeURIComponent(s.name), { ...toBody(s), enabled: !s.enabled })
      load()
    } catch (err) { setError(err.message) }
  }

  const runNow = async (s) => {
    setError('')
    try {
      const data = await api('POST', '/api/schedules/' + encodeURIComponent(s.name) + '/run')
      navigate('/run-detail/' + data.run_id)
    } catch (err) { setError(err.message) }
  }

  const remove = async (s) => {
    if (!window.confirm('Delete schedule "' + s.name + '"?')) return
    setError('')
    try {
      await api('DELETE', '/api/schedules/' + encodeURIComponent(s.name))
      load()
    } catch (err) { setError(err.message) }
  }

  const openNew = () => { setEditing(null); setModalOpen(true) }
  const openEdit = (s) => { setEditing(s); setModalOpen(true) }

  if (loading) return <div className="loading-overlay" style={{ position: 'relative', height: 200 }}><div className="spinner"></div></div>

  return (
    <>
      <div className="dash-header">
        <h2>Schedules</h2>
        <div className="dash-actions">
          <button className="btn primary" onClick={openNew}>New Schedule</button>
        </div>
      </div>
      {error && <div className="error-message">{error}</div>}
      {!schedules.length ? (
        <div className="empty">No schedules yet. Create one to run a library scan or a recently-added check on a timer.</div>
      ) : (
        <table className="libs-table"><thead><tr><th>Name</th><th>Schedule</th><th>Run</th><th>Next run</th><th>Status</th><th>Last run</th><th></th></tr></thead><tbody>
          {schedules.map(s => (
            <tr key={s.name}>
              <td><span className="lib-name">{s.name}</span></td>
              <td>{scheduleLabel(s)}</td>
              <td>{targetLabel(s)}</td>
              <td><span className="mono">{s.next_run ? new Date(s.next_run).toLocaleString() : '—'}</span></td>
              <td>
                <span className={'tag ' + (s.enabled === false ? 'pending' : 'ok')}>
                  {s.enabled === false ? 'disabled' : 'enabled'}
                </span>
              </td>
              <td>
                {s.run_id ? (
                  <button className="live-link" onClick={() => navigate('/run-detail/' + s.run_id)}>
                    {s.skipped_reason ? 'skipped' : 'view'}
                  </button>
                ) : (
                  <span className="status-idle">never</span>
                )}
              </td>
              <td className="cell-actions">
                <button className="btn outline sm" onClick={() => toggleEnabled(s)}>{s.enabled === false ? 'Enable' : 'Disable'}</button>
                <button className="btn outline sm" onClick={() => runNow(s)}>Run now</button>
                <button className="btn outline sm" onClick={() => openEdit(s)}>Edit</button>
                <button className="btn danger sm" onClick={() => remove(s)}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody></table>
      )}
      {modalOpen && <ScheduleForm
        schedule={editing}
        libraries={libraries}
        onClose={() => setModalOpen(false)}
        onSaved={() => { setModalOpen(false); load() }}
        onError={setError}
      />}
    </>
  )
}

function ScheduleForm({ schedule, libraries, onClose, onSaved, onError }) {
  const [name, setName] = useState(schedule ? schedule.name : '')
  const [enabled, setEnabled] = useState(schedule ? schedule.enabled !== false : true)
  const [repeat, setRepeat] = useState(schedule ? schedule.repeat : 'daily')
  const [day, setDay] = useState(schedule && schedule.day != null ? schedule.day : 1)
  const [time, setTime] = useState(schedule ? schedule.time : '03:00')
  const [mode, setMode] = useState(schedule ? schedule.mode : 'library')
  const [selectedLibs, setSelectedLibs] = useState(() => {
    if (!schedule) return []
    const raw = schedule.mode === 'jellyfin_recent'
      ? (schedule.flags.libraries || '')
      : (schedule.library || '')
    return raw.split(',').map(x => x.trim()).filter(Boolean)
  })
  const [sinceHours, setSinceHours] = useState(schedule && schedule.flags ? (schedule.flags.since_hours || 72) : 72)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const toggleLib = lib => {
    setSelectedLibs(prev => prev.includes(lib) ? prev.filter(x => x !== lib) : [...prev, lib])
  }

  const submit = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    const body = {
      name: name.trim(),
      enabled,
      repeat,
      time,
      mode,
    }
    if (repeat !== 'daily') body.day = parseInt(day) || 0
    if (!selectedLibs.length) { setError('Choose at least one library'); return }
    if (mode === 'library') {
      body.library = selectedLibs.join(',')
    } else {
      body.flags = { libraries: selectedLibs.join(','), since_hours: parseInt(sinceHours) || 72 }
    }
    setSaving(true)
    setError('')
    try {
      if (schedule) {
        await api('PUT', '/api/schedules/' + encodeURIComponent(schedule.name), body)
      } else {
        await api('POST', '/api/schedules', body)
      }
      onSaved()
    } catch (err) {
      setError(err.message)
      onError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={e => e.stopPropagation()} style={{ maxWidth: 520 }}>
        <h3>{schedule ? 'Edit schedule' : 'New schedule'}</h3>
        {error && <div className="error-message">{error}</div>}
        <form onSubmit={submit}>
          <div className="form-row">
            <div className="field" style={{ flex: 2 }}>
              <label>Name</label>
              <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="Nightly Shows scan" required />
              <Hint>Used as the schedule id in config.yml</Hint>
            </div>
            <div className="field checkbox checkbox-input">
              <input type="checkbox" id="ck-enabled" checked={enabled} onChange={e => setEnabled(e.target.checked)} />
              <label htmlFor="ck-enabled">Enabled</label>
            </div>
          </div>
          <div className="form-row">
            <div className="field">
              <label>Repeat</label>
              <select value={repeat} onChange={e => setRepeat(e.target.value)}>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </select>
            </div>
            {repeat === 'weekly' && (
              <div className="field">
                <label>Weekday</label>
                <select value={day} onChange={e => setDay(e.target.value)}>
                  {WEEKDAYS.map((d, i) => <option key={i} value={i}>{d}</option>)}
                </select>
              </div>
            )}
            {repeat === 'monthly' && (
              <div className="field">
                <label>Day of month</label>
                <input type="number" min="1" max="31" value={day} onChange={e => setDay(e.target.value)} />
                <Hint>Months without this day skip to the next one</Hint>
              </div>
            )}
            <div className="field">
              <label>Time</label>
              <input type="time" value={time} onChange={e => setTime(e.target.value)} />
              <Hint>Server local time ({Intl.DateTimeFormat().resolvedOptions().timeZone})</Hint>
            </div>
          </div>
          <div className="form-row">
            <div className="field">
              <label>Run</label>
              <select value={mode} onChange={e => setMode(e.target.value)}>
                <option value="library">Library scan</option>
                <option value="jellyfin_recent">Recently added (Jellyfin)</option>
              </select>
            </div>
          </div>
          <div className="form-row">
            <div className="field">
              <label>Libraries</label>
              <div className="lib-chips">
                {libraries.map(lib => (
                  <button
                    key={lib.name}
                    type="button"
                    className={'lib-chip' + (selectedLibs.includes(lib.name) ? ' active' : '')}
                    onClick={() => toggleLib(lib.name)}
                  >
                    {selectedLibs.includes(lib.name) && '\u2713 '}{lib.name}
                  </button>
                ))}
              </div>
              <Hint>{mode === 'library'
                ? 'Libraries are scanned and converted one after another'
                : 'Libraries to check for recently added items'}</Hint>
            </div>
          </div>
          {mode === 'jellyfin_recent' && (
            <div className="form-row">
              <div className="field">
                <label>Since (hours)</label>
                <input type="number" min="1" value={sinceHours} onChange={e => setSinceHours(e.target.value)} />
                <Hint>Files added or updated in the last N hours</Hint>
              </div>
            </div>
          )}
          <div className="modal-actions">
            <button type="submit" className={'btn primary' + (saving ? ' loading' : '')} disabled={saving}>
              {schedule ? 'Save Changes' : 'Create Schedule'}
            </button>
            <button type="button" className="btn outline" onClick={onClose} disabled={saving}>Cancel</button>
          </div>
        </form>
      </div>
    </div>
  )
}

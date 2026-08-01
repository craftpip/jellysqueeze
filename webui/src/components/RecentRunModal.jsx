import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

const Hint = ({ children }) => (
  <span style={{ display: 'block', fontSize: 11, color: '#555', lineHeight: 1.3, marginTop: 2 }}>{children}</span>
)

export default function RecentRunModal({ open, onClose, libraries, fixedLibrary, title }) {
  const navigate = useNavigate()
  const [allLibs, setAllLibs] = useState([])
  const [selected, setSelected] = useState([])
  const [sinceHours, setSinceHours] = useState(72)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [jellyfinConfigured, setJellyfinConfigured] = useState(true)

  useEffect(() => {
    if (!open) return
    const libs = (libraries || '').split(',').map(s => s.trim()).filter(Boolean)
    setAllLibs(libs)
    setSelected(libs)
    setSinceHours(72)
    setError('')
    setRunning(false)
    api('GET', '/api/env').then(d => {
      setJellyfinConfigured(d.jellyfin_configured !== false)
    }).catch(() => {})
  }, [open, libraries])

  if (!open) return null

  const toggle = name => {
    if (fixedLibrary) return
    setSelected(prev => prev.includes(name) ? prev.filter(x => x !== name) : [...prev, name])
  }

  const run = async () => {
    setRunning(true)
    setError('')
    try {
      const data = await api('POST', '/api/run', {
        mode: 'jellyfin_recent',
        flags: { libraries: selected.join(','), since_hours: sinceHours },
      })
      navigate('/run-detail/' + data.run_id)
    } catch (err) {
      setError(err.message)
      setRunning(false)
    }
  }

  const canRun = selected.length > 0 && !running

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={e => e.stopPropagation()}>
        <h3>{title || 'Recently Added'}</h3>
        {error && <div className="error-message">{error}</div>}
        {!jellyfinConfigured && (
          <div className="info-message">Jellyfin is not configured. Set the server URL and API key in Settings first.</div>
        )}
        <div className="form-row">
          <div className="field">
            <label>Libraries</label>
            <div className="lib-chips">
              {allLibs.map(lib => (
                <button
                  key={lib}
                  type="button"
                  className={'lib-chip' + (selected.includes(lib) ? ' active' : '')}
                  onClick={() => toggle(lib)}
                  disabled={fixedLibrary}
                >
                  {selected.includes(lib) && '\u2713 '}{lib}
                </button>
              ))}
            </div>
            <Hint>{fixedLibrary ? 'This run checks the current library only' : 'Select libraries to check'}</Hint>
          </div>
        </div>
        <div className="form-row">
          <div className="field">
            <label>Since (hours)</label>
            <input type="number" min="1" value={sinceHours} onChange={e => setSinceHours(e.target.value)} placeholder="72" />
            <Hint>Files added or updated in the last N hours</Hint>
          </div>
        </div>
        <div className="modal-actions">
          <button className="btn primary" onClick={run} disabled={!canRun}>
            {running ? 'Starting...' : '\u25b6 Run'}
          </button>
          <button className="btn outline" onClick={onClose} disabled={running}>Cancel</button>
        </div>
      </div>
    </div>
  )
}

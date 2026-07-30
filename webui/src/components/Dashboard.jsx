import { useState, useEffect } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { api, relTime } from '../api'

export default function Dashboard() {
  const { setPageTitle } = useOutletContext()
  const [libs, setLibs] = useState([])
  const [stats, setStats] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  useEffect(() => setPageTitle('Libraries'), [setPageTitle])

  useEffect(() => {
    async function load() {
      try {
        const [libsRes, statsRes] = await Promise.all([
          api('GET', '/api/libraries'),
          api('GET', '/api/stats'),
        ])
        setLibs(libsRes.libraries || [])
        setStats(statsRes)
        setError('')
      } catch (err) {
        setError(err.message)
      }
      setLoading(false)
    }
    load()
    const iv = setInterval(load, 5000)
    return () => clearInterval(iv)
  }, [])

  if (loading) return <div className="loading-overlay" style={{ position: 'relative', height: 200 }}><div className="spinner"></div></div>

  const savedGb = ((stats.total_saved_mb || 0) / 1024).toFixed(2)

  const startRun = async (mode, library) => {
    const body = mode === 'all' ? { mode: 'all', flags: {} } : { mode: 'library', library, flags: {} }
    try {
      const data = await api('POST', '/api/run', body)
      navigate('/run-detail/' + data.run_id)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <>
      <div className="stats-line">
        <span>{stats.total_runs ?? 0} runs</span>
        <span className="sep">&middot;</span>
        <span>{libs.length} libraries</span>
        <span className="sep">&middot;</span>
        <span>{stats.total_ok ?? 0} converted</span>
        <span className="sep">&middot;</span>
        <span>{savedGb} GB saved</span>
      </div>
      {error && <div className="error-message">{error}</div>}

      {!libs.length ? (
        <div className="empty">No libraries yet. <a href="#" onClick={e => { e.preventDefault(); navigate('/new-library') }}>Create one</a>.</div>
      ) : (
        <>
          <div className="dash-header">
            <h2>Libraries</h2>
            <div className="dash-actions">
              <button className="link-btn" onClick={() => navigate('/new-library')}>+ New Library</button>
              <button className="link-btn primary" onClick={() => startRun('all')}>Run All</button>
            </div>
          </div>
          <table className="libs-table"><thead><tr><th>Name</th><th>Status</th><th>Folders</th><th>Encoder</th><th>Bitrate</th><th>Saved</th><th></th></tr></thead><tbody>
            {libs.map(lib => {
              const p = lib.profile || {}
              const saved = lib.total_saved_mb > 0 ? (lib.total_saved_mb / 1024).toFixed(2) + ' GB' : '-'
              const paths = lib.paths || []
              const enc = p.encoder || 'nvidia'
              const isRunning = lib.running
              const lastRun = lib.last_run ? relTime(lib.last_run) : null
              return (
                <tr key={lib.name} className={isRunning ? 'row-running' : ''}>
                  <td><strong>{lib.name}</strong></td>
                  <td>{isRunning ? <span className="running-indicator">Running</span> : lastRun ? <span className="ago">{lastRun}</span> : <span className="ago">-</span>}</td>
                  <td><span className="folder-count">{paths.length}</span></td>
                  <td><span className="mono">{enc}</span></td>
                  <td><span className="mono">{p.target_bitrate || '-'}k</span></td>
                  <td><span className="mono">{saved}</span></td>
                  <td className="actions-cell">
                    <button className="link-btn" onClick={() => navigate('/library-detail/' + encodeURIComponent(lib.name))}>View</button>
                    <button className="link-btn primary" onClick={() => startRun('library', lib.name)} disabled={isRunning}>Convert</button>
                  </td>
                </tr>
              )
            })}
          </tbody></table>
        </>
      )}
    </>
  )
}

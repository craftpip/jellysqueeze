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
  useEffect(() => setPageTitle('Dashboard'), [setPageTitle])

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
      <div className="stat-grid mb-8">
        <div className="stat-card accent-blue"><div className="icon">&#9654;</div><div className="value">{stats.total_runs}</div><div className="label">Total Runs</div></div>
        <div className="stat-card accent-orange"><div className="icon">&#128218;</div><div className="value">{libs.length}</div><div className="label">Libraries</div></div>
        <div className="stat-card accent-green"><div className="icon">&#10003;</div><div className="value">{stats.total_ok}</div><div className="label">Files Converted</div></div>
        <div className="stat-card accent-purple"><div className="icon">&#128190;</div><div className="value">{savedGb} GB</div><div className="label">Space Saved</div></div>
      </div>
      {error && <div className="error-message">{error}</div>}

      <div className="card">
        <h3>Libraries</h3>
        {!libs.length ? (
          <div className="empty">No libraries configured. <a href="#" onClick={e => { e.preventDefault(); navigate('/new-library') }}>Create one</a>.</div>
        ) : (
          <>
            <div className="action-bar">
              <button className="btn outline sm" onClick={() => navigate('/new-library')}>+ New Library</button>
              <button className="btn primary sm" onClick={() => startRun('all')}>&#9654; Run All</button>
            </div>
            <table><thead><tr><th>Name</th><th>Status</th><th>Folders</th><th>Encoder</th><th>Bitrate</th><th>Saved</th><th></th></tr></thead><tbody>
              {libs.map(lib => {
                const p = lib.profile || {}
                const saved = lib.total_saved_mb > 0 ? (lib.total_saved_mb / 1024).toFixed(2) + ' GB' : '-'
                const paths = lib.paths || []
                const enc = p.encoder || 'nvidia'
                const encCls = enc === 'cpu' ? 'tag ok' : 'tag skip'
                const isRunning = lib.running
                const lastRun = lib.last_run ? relTime(lib.last_run) : null
                return (
                  <tr key={lib.name} className={isRunning ? 'row-running' : ''}>
                    <td><strong>{lib.name}</strong></td>
                    <td>{isRunning ? <span className="tag running">Running <span className="dot running" style={{ verticalAlign: 'middle', marginLeft: 4 }}></span></span> : lastRun ? <span className="text-muted">{lastRun}</span> : <span className="text-muted">—</span>}</td>
                    <td>{!paths.length ? <span className="text-muted">none</span> : <span className="lib-path-count" title={paths.join('\n')}>{paths.length} folder{paths.length > 1 ? 's' : ''}</span>}</td>
                    <td><span className={encCls}>{enc}</span></td>
                    <td>{p.target_bitrate || '—'}k</td>
                    <td>{saved}</td>
                    <td>
                      <button className="btn outline sm" onClick={() => navigate('/library-detail/' + encodeURIComponent(lib.name))}>View</button>
                      <button className="btn primary sm" onClick={() => startRun('library', lib.name)} disabled={isRunning} style={{ marginLeft: 4 }}>&#9654;</button>
                    </td>
                  </tr>
                )
              })}
            </tbody></table>
          </>
        )}
      </div>
    </>
  )
}

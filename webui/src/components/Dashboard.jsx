import { useState, useEffect } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { api, relTime } from '../api'

export default function Dashboard() {
  const { setPageTitle } = useOutletContext()
  const [libs, setLibs] = useState([])
  const [stats, setStats] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [runProgress, setRunProgress] = useState({})
  const navigate = useNavigate()
  useEffect(() => setPageTitle('Dashboard'), [setPageTitle])

  useEffect(() => {
    let mounted = true
    async function load() {
      try {
        const [libsRes, statsRes] = await Promise.all([
          api('GET', '/api/libraries'),
          api('GET', '/api/stats'),
        ])
        if (!mounted) return
        setLibs(libsRes.libraries || [])
        setStats(statsRes)
        setError('')

        const running = (libsRes.libraries || []).filter(l => l.running && l.active_run_id)
        if (running.length) {
          const progress = {}
          await Promise.all(running.map(async lib => {
            try {
              const st = await api('GET', '/api/status/' + lib.active_run_id)
              if (st) {
                const done = (st.results || []).length
                const totals = st.folder_totals || {}
                const total = Object.values(totals).reduce((a, b) => a + b, 0)
                progress[lib.active_run_id] = { done, total }
              }
            } catch {}
          }))
          if (mounted) setRunProgress(progress)
        } else if (mounted) {
          setRunProgress({})
        }
      } catch (err) {
        if (mounted) setError(err.message)
      }
      if (mounted) setLoading(false)
    }
    load()
    const iv = setInterval(load, 5000)
    return () => { mounted = false; clearInterval(iv) }
  }, [])

  if (loading) return <div className="loading-overlay" style={{ position: 'relative', height: 200 }}><div className="spinner"></div></div>

  const savedGb = ((stats.total_saved_mb || 0) / 1024).toFixed(2)


  const runLib = async (e, name) => {
    e.stopPropagation()
    try {
      const data = await api('POST', '/api/run', { mode: 'library', library: name, flags: {} })
      navigate('/run-detail/' + data.run_id)
    } catch (err) {
      setError(err.message)
    }
  }

  const openLibrary = (name) => {
    navigate('/library-detail/' + encodeURIComponent(name))
  }

  const openLiveRun = (e, runId) => {
    e.stopPropagation()
    navigate('/run-detail/' + runId)
  }

  return (
    <>
      <div className="stats-grid">
        <div className="stat-block">
          <span className="num">{stats.total_runs ?? 0}</span>
          <span className="lbl">runs</span>
        </div>
        <div className="stat-block">
          <span className="num">{libs.length}</span>
          <span className="lbl">libraries</span>
        </div>
        <div className="stat-block">
          <span className="num">{stats.total_ok ?? 0}</span>
          <span className="lbl">ok</span>
        </div>
        <div className="stat-block">
          <span className="num">{stats.total_skip ?? 0}</span>
          <span className="lbl">skip</span>
        </div>
        <div className="stat-block">
          <span className="num">{stats.total_fail ?? 0}</span>
          <span className="lbl">fail</span>
        </div>
        <div className="stat-block">
          <span className="num">{savedGb}</span>
          <span className="lbl">GB saved</span>
        </div>
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
            </div>
          </div>
          <table className="libs-table"><thead><tr><th>Name</th><th>Last Run</th><th>Encoder</th><th>Bitrate</th><th>OK</th><th>Skip</th><th>Fail</th><th>Saved</th><th></th></tr></thead><tbody>
            {libs.map(lib => {
              const p = lib.profile || {}
              const saved = lib.total_saved_mb > 0 ? (lib.total_saved_mb / 1024).toFixed(2) + ' GB' : '-'
              const enc = p.encoder || 'nvidia'
              const isRunning = lib.running
              const lastRun = lib.last_run ? relTime(lib.last_run) : null
              const prog = lib.active_run_id ? runProgress[lib.active_run_id] : null
              const summary = lib.last_run_summary || {}
              return (
                <tr key={lib.name} className={'clickable' + (isRunning ? ' row-running' : '')} onClick={() => openLibrary(lib.name)}>
                  <td><span className="lib-name">{lib.name}</span></td>
                  <td>
                    {isRunning ? (
                      <span className="status-running">
                        <span className="pulse-dot"></span>
                        Running
                        {prog && prog.total > 0 ? (
                          <span className="progress-frac">  {prog.done}/{prog.total}</span>
                        ) : null}
                        <button className="live-link" onClick={e => openLiveRun(e, lib.active_run_id)}>Live</button>
                      </span>
                    ) : lastRun ? (
                      <span className="status-idle">{lastRun}</span>
                    ) : (
                      <span className="status-idle">-</span>
                    )}
                  </td>
                  <td><span className="mono">{enc}</span></td>
                  <td><span className="mono">{p.target_bitrate || '-'}k</span></td>
                  <td><span className="mono ok">{summary.ok ?? '-'}</span></td>
                  <td><span className="mono skip">{summary.skip ?? '-'}</span></td>
                  <td><span className="mono fail">{summary.fail ?? '-'}</span></td>
                  <td><span className="mono">{saved}</span></td>
                  <td className="cell-actions">
                    <button className="link-btn primary" onClick={e => runLib(e, lib.name)} disabled={isRunning}>&#9654; Run Now</button>
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

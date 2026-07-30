import { useState, useEffect } from 'react'
import { useParams, useNavigate, useOutletContext } from 'react-router-dom'
import { api } from '../api'

export default function LibraryDetail() {
  const { setPageTitle } = useOutletContext()
  const { name } = useParams()
  const navigate = useNavigate()
  useEffect(() => setPageTitle(name), [name, setPageTitle])
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let mounted = true
    async function load() {
      try {
        const d = await api('GET', '/api/libraries/' + encodeURIComponent(name))
        if (!mounted) return
        setData(d)
        setError('')
      } catch (err) {
        if (mounted) setError(err.message)
      } finally {
        if (mounted) setLoading(false)
      }
    }
    load()
    const id = setInterval(load, 5000)
    return () => { mounted = false; clearInterval(id) }
  }, [name])

  if (loading) return <div className="loading-overlay" style={{ position: 'relative', height: 200 }}><div className="spinner"></div></div>
  if (!data || data.error) return <div className="card"><div className="empty">Library not found.</div></div>

  const p = data.profile || {}
  const runs = Object.values((data.runs || []).reduce((acc, r) => { acc[r.run_id] = r; return acc }, {}))
  const activeRun = runs.find(r => r.running)

  const deleteLib = async () => {
    if (!confirm('Delete library "' + name + '"?')) return
    try {
      await api('DELETE', '/api/libraries/' + encodeURIComponent(name))
      navigate('/')
    } catch (err) {
      setError(err.message)
    }
  }

  const runNow = async () => {
    try {
      const d = await api('POST', '/api/run', { mode: 'library', library: name, flags: {} })
      navigate('/run-detail/' + d.run_id)
    } catch (err) {
      setError(err.message)
    }
  }

  const stopActive = async () => {
    if (!activeRun) return
    try {
      await api('POST', '/api/stop/' + activeRun.run_id)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <>
      <div className="flex items-center gap-8 mb-8">
        <button className="btn outline sm" onClick={() => navigate('/')}>&#8592; Back</button>
        <h3 style={{ flex: 1 }}>{name}</h3>
        {activeRun ? (
          <>
            <span className="tag running">Running</span>
            <button className="btn outline sm" onClick={() => navigate('/run-detail/' + activeRun.run_id)}>&#9654; View Live</button>
            <button className="btn danger sm" onClick={stopActive}>&#9632; Stop</button>
          </>
        ) : (
          <button className="btn primary sm" onClick={runNow}>&#9654; Run Now</button>
        )}
        <button className="btn outline sm" onClick={() => navigate('/edit-library/' + encodeURIComponent(name))}>Edit</button>
        <button className="btn danger sm" onClick={deleteLib}>Delete</button>
      </div>
      {error && <div className="error-message">{error}</div>}

      <div className="card">
        <div className="detail-row"><span className="label">Encoder</span><span className="value">{p.encoder || 'nvidia'}</span></div>
        <div className="detail-row"><span className="label">Target bitrate</span><span className="value">{p.target_bitrate || '—'} kbps</span></div>
        <div className="detail-row"><span className="label">Max bitrate</span><span className="value">{p.max_bitrate || '—'} kbps</span></div>
        <div className="detail-row"><span className="label">Min savings</span><span className="value">{p.minimum_savings_percent || 0}%</span></div>
        <div className="detail-row"><span className="label">Audio langs</span><span className="value">{(p.keep_audio_langs || []).join(', ') || '—'}</span></div>
        <div className="detail-row"><span className="label">Folders</span><span className="value">{(data.paths || []).join(', ') || '—'}</span></div>
      </div>

      <div className="card">
        <h3>Run History</h3>
        {!runs.length ? (
          <div className="empty">No runs yet.</div>
        ) : (
          <table><thead><tr><th>Date</th><th>OK</th><th>Skip</th><th>Fail</th><th>Saved</th><th>Status</th><th></th></tr></thead><tbody>
            {runs.map(r => {
              const s = r.summary || {}
              const date = r.started_at ? new Date(r.started_at * 1000).toLocaleString() : '—'
              const saved = s.space_saved_mb > 0 ? (s.space_saved_mb / 1024).toFixed(2) + ' GB' : '—'
              let status
              let statusClass
              let viewLink
              if (r.running) {
                status = 'Running'; statusClass = 'running'
                viewLink = '/run-detail/' + r.run_id
              } else if (r.exit_code === 0) {
                status = 'OK'; statusClass = 'ok'
                viewLink = '/run-detail/' + r.run_id
              } else if (r.exit_code === -15) {
                status = 'Stopped'; statusClass = 'skip'
                viewLink = '/run-detail/' + r.run_id
              } else if (r.exit_code == null) {
                status = 'Incomplete'; statusClass = 'skip'
                viewLink = '/run-detail/' + r.run_id
              } else {
                status = 'FAIL'; statusClass = 'fail'
                viewLink = '/run-detail/' + r.run_id
              }
              return (
                <tr key={r.run_id}>
                  <td>{date}</td>
                  <td>{s.ok || 0}</td>
                  <td>{s.skip || 0}</td>
                  <td>{s.fail || 0}</td>
                  <td>{saved}</td>
                  <td><span className={'tag ' + statusClass}>{status}</span></td>
                  <td><button className="btn outline sm" onClick={() => navigate(viewLink)}>View</button></td>
                </tr>
              )
            })}
          </tbody></table>
        )}
      </div>
    </>
  )
}

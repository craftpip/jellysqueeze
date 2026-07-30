import { useState, useEffect } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { api } from '../api'

export default function RunHistory() {
  const { setPageTitle } = useOutletContext()
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  useEffect(() => setPageTitle('Run History'), [setPageTitle])

  useEffect(() => {
    api('GET', '/api/runs').then(data => {
      const deduped = Object.values((data.runs || []).reduce((acc, r) => { acc[r.run_id] = r; return acc }, {}))
      setRuns(deduped)
    }).catch(err => setError(err.message)).finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="loading-overlay" style={{ position: 'relative', height: 200 }}><div className="spinner"></div></div>

  return (
    <div className="card">
      <h3>All Runs</h3>
      {error && <div className="error-message">{error}</div>}
      {!runs.length ? (
        <div className="empty">No runs yet.</div>
      ) : (
        <table><thead><tr><th>Date</th><th>Library</th><th>OK</th><th>Skip</th><th>Fail</th><th>Saved</th><th>Status</th><th></th></tr></thead><tbody>
          {runs.map(r => {
            const s = r.summary || {}
            const running = r.running
            const date = running ? (r.started_at ? new Date(r.started_at * 1000).toLocaleString() : '—') : (r.ended_at ? new Date(r.ended_at * 1000).toLocaleString() : '—')
            const saved = s.space_saved_mb > 0 ? (s.space_saved_mb / 1024).toFixed(2) + ' GB' : '—'
            let status
            let statusClass
            if (running) {
              status = 'Running'; statusClass = 'running'
            } else if (r.exit_code === 0) {
              status = 'OK'; statusClass = 'ok'
            } else if (r.exit_code === -15) {
              status = 'Stopped'; statusClass = 'skip'
            } else if (r.exit_code == null) {
              status = 'Incomplete'; statusClass = 'skip'
            } else {
              status = String(r.exit_code); statusClass = 'fail'
            }
            return (
              <tr key={r.run_id} className={running ? 'row-running' : ''}>
                <td>{date}</td>
                <td>{r.library || '—'}</td>
                <td>{s.ok || 0}</td>
                <td>{s.skip || 0}</td>
                <td>{s.fail || 0}</td>
                <td>{saved}</td>
                <td><span className={'tag ' + statusClass}>{status}</span></td>
                <td><button className="btn outline sm" onClick={() => navigate('/run-detail/' + r.run_id)}>View</button></td>
              </tr>
            )
          })}
        </tbody></table>
      )}
    </div>
  )
}

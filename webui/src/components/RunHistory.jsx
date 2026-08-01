import { useState, useEffect, useMemo } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { api } from '../api'

const runStatus = r => {
  if (r.running) return { text: 'Running', cls: 'running' }
  if (r.exit_code === 0) return { text: 'OK', cls: 'ok' }
  if (r.exit_code === -15) return { text: 'Stopped', cls: 'skip' }
  if (r.exit_code == null) return { text: 'Incomplete', cls: 'skip' }
  return { text: String(r.exit_code), cls: 'fail' }
}

export default function RunHistory() {
  const { setPageTitle } = useOutletContext()
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [libFilter, setLibFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const navigate = useNavigate()
  useEffect(() => setPageTitle('Run History'), [setPageTitle])

  useEffect(() => {
    api('GET', '/api/runs').then(data => {
      const deduped = Object.values((data.runs || []).reduce((acc, r) => { acc[r.run_id] = r; return acc }, {}))
      setRuns(deduped)
    }).catch(err => setError(err.message)).finally(() => setLoading(false))
  }, [])

  const libraries = useMemo(() => [...new Set(runs.map(r => r.library || '—'))].sort(), [runs])
  const statuses = useMemo(() => [...new Set(runs.map(r => runStatus(r).text))].sort(), [runs])
  const filtered = runs.filter(r =>
    (!libFilter || (r.library || '—') === libFilter) &&
    (!statusFilter || runStatus(r).text === statusFilter)
  )

  if (loading) return <div className="loading-overlay" style={{ position: 'relative', height: 200 }}><div className="spinner"></div></div>

  return (
    <>
      <div className="dash-header">
        <h2>Run History</h2>
        <select className="run-filter" value={libFilter} onChange={e => setLibFilter(e.target.value)}>
          <option value="">All libraries</option>
          {libraries.map(l => <option key={l} value={l}>{l}</option>)}
        </select>
        <select className="run-filter" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          {statuses.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      {error && <div className="error-message">{error}</div>}
      {!runs.length ? (
        <div className="empty">No runs yet.</div>
      ) : !filtered.length ? (
        <div className="empty">No runs match the filter.</div>
      ) : (
        <div className="table-wrap"><table className="libs-table"><thead><tr><th>Date</th><th>Library</th><th>OK</th><th>Skip</th><th>Fail</th><th>Saved</th><th>Status</th><th></th></tr></thead><tbody>
          {filtered.map(r => {
            const s = r.summary || {}
            const running = r.running
            const date = running ? (r.started_at ? new Date(r.started_at * 1000).toLocaleString() : '—') : (r.ended_at ? new Date(r.ended_at * 1000).toLocaleString() : '—')
            const saved = s.space_saved_mb > 0 ? (s.space_saved_mb / 1024).toFixed(2) + ' GB' : '—'
            const st = runStatus(r)
            return (
              <tr key={r.run_id} className={running ? 'row-running' : ''} onClick={() => navigate('/run-detail/' + r.run_id)} style={{cursor:'pointer'}}>
                <td><span className="mono">{date}</span></td>
                <td>{r.library || '—'}</td>
                <td><span className="mono ok">{s.ok || 0}</span></td>
                <td><span className="mono skip">{s.skip || 0}</span></td>
                <td><span className="mono fail">{s.fail || 0}</span></td>
                <td><span className="mono">{saved}</span></td>
                <td><span className={'tag ' + st.cls}>{st.text}</span></td>
                <td className="cell-actions"><button className="btn outline sm" onClick={e => { e.stopPropagation(); navigate('/run-detail/' + r.run_id) }}>View</button></td>
              </tr>
            )
          })}
        </tbody></table></div>
      )}
    </>
  )
}

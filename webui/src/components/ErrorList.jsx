import { useState, useEffect } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { api } from '../api'

function friendlyTime(ts) {
  if (!ts) return ''
  const diff = Math.floor((Date.now() - ts * 1000) / 1000)
  if (diff < 60) return 'just now'
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago'
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago'
  if (diff < 604800) return Math.floor(diff / 86400) + 'd ago'
  return Math.floor(diff / 604800) + 'w ago'
}

export default function ErrorList() {
  const { setPageTitle } = useOutletContext()
  const [errors, setErrors] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  useEffect(() => setPageTitle('Errors'), [setPageTitle])

  useEffect(() => {
    api('GET', '/api/errors').then(data => {
      setErrors(data.errors || [])
    }).catch(err => setError(err.message)).finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="loading-overlay" style={{ position: 'relative', height: 200 }}><div className="spinner"></div></div>

  return (
    <>
      <div className="dash-header">
        <h2>Errors</h2>
      </div>
      {error && <div className="error-message">{error}</div>}
      {!errors.length ? (
        <div className="empty">No errors found.</div>
      ) : (
        <table className="libs-table" style={{ tableLayout: 'fixed' }}><thead><tr><th style={{ width: 170 }}>Date</th><th style={{ width: 100 }}>Library</th><th style={{ width: 220 }}>File</th><th>Error</th></tr></thead><tbody>
          {errors.map((e, i) => {
            const full = e.started_at ? new Date(e.started_at * 1000).toLocaleString() : '—'
            const fileName = e.file.split(/[\\/]/).pop()
            return (
              <tr key={i} onClick={() => navigate('/run-detail/' + e.run_id)} style={{ cursor: 'pointer' }}>
                <td style={{ whiteSpace: 'nowrap' }}><span className="mono">{full}</span><br /><span className="text-muted">{friendlyTime(e.started_at)}</span></td>
                <td>{e.library || '—'}</td>
                <td className="file-ellipsis" title={e.file}>{fileName}</td>
                <td style={{ whiteSpace: 'normal', wordBreak: 'break-word' }} title={e.message}>{e.message || '—'}</td>
              </tr>
            )
          })}
        </tbody></table>
      )}
    </>
  )
}

import { useState, useEffect } from 'react'
import { useParams, useNavigate, useOutletContext } from 'react-router-dom'
import { api } from '../api'
import RecentRunModal from './RecentRunModal'

const s = {
  section: { marginBottom: 28 },
  h3: { fontSize: 11, fontWeight: 600, color: '#666', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 14, paddingBottom: 6, borderBottom: '1px solid #2a2a2a' },
}

export default function LibraryDetail() {
  const { setPageTitle } = useOutletContext()
  const { name } = useParams()
  const navigate = useNavigate()
  useEffect(() => setPageTitle(name), [name, setPageTitle])
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [recentOpen, setRecentOpen] = useState(false)

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
  if (!data || data.error) return <div className="empty">Library not found.</div>

  const p = data.profile || {}
  const runs = Object.values((data.runs || []).reduce((acc, r) => { acc[r.run_id] = r; return acc }, {}))
  const activeRun = runs.find(r => r.running)
  const lastRun = runs.find(r => !r.running)

  const totalOk = runs.reduce((sum, r) => sum + (r.summary?.ok || 0), 0)
  const totalSkip = runs.reduce((sum, r) => sum + (r.summary?.skip || 0), 0)
  const totalFail = runs.reduce((sum, r) => sum + (r.summary?.fail || 0), 0)
  const totalSaved = runs.reduce((sum, r) => sum + (r.summary?.space_saved_mb || 0), 0)
  const totalFiles = totalOk + totalSkip + totalFail

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
      <button className="link-btn mb-8" onClick={() => navigate('/')}>&#8592; Back</button>
      <div className="dash-header">
        <h2 style={{ margin: 0 }}>{name}</h2>
        <div className="dash-actions" style={{ gap: 12 }}>
          {activeRun ? (
            <>
              <span className="tag running">Running</span>
              <button className="link-btn primary" onClick={() => navigate('/run-detail/' + activeRun.run_id)}>&#9654; View Live</button>
              <button className="link-btn" style={{color:'#e05050'}} onClick={stopActive}>&#9632; Stop</button>
            </>
          ) : (
            <button className="link-btn primary" onClick={runNow}>&#9654; Run Now</button>
          )}
          <button className="link-btn" onClick={() => setRecentOpen(true)}>Recently Added</button>
          <button className="link-btn" onClick={() => navigate('/edit-library/' + encodeURIComponent(name))}>Edit</button>
          <button className="link-btn" style={{color:'#e05050'}} onClick={deleteLib}>Delete</button>
        </div>
      </div>
      {error && <div className="error-message">{error}</div>}

      <div className="row2">
        <div className="col-main">
          <div style={s.section}>
            <h3 style={s.h3}>Profile</h3>
            <div className="detail-row"><span className="label">Encoder</span><span className="value" style={{fontFamily:'monospace',fontSize:12}}>{p.encoder || 'nvidia'}</span></div>
            <div className="detail-row"><span className="label">Target bitrate</span><span className="value" style={{fontFamily:'monospace',fontSize:12}}>{p.target_bitrate || '—'} kbps</span></div>
            <div className="detail-row"><span className="label">Max bitrate</span><span className="value" style={{fontFamily:'monospace',fontSize:12}}>{p.max_bitrate || '—'} kbps</span></div>
            <div className="detail-row"><span className="label">Min savings</span><span className="value" style={{fontFamily:'monospace',fontSize:12}}>{p.minimum_savings_percent || 0}%</span></div>
            <div className="detail-row"><span className="label">Workers</span><span className="value" style={{fontFamily:'monospace',fontSize:12}}>{p.workers || 1}</span></div>
            <div className="detail-row"><span className="label">Audio langs</span><span className="value" style={{fontFamily:'monospace',fontSize:12}}>{(p.keep_audio_langs || []).join(', ') || 'all'}</span></div>
            <div className="detail-row"><span className="label">Subtitle langs</span><span className="value" style={{fontFamily:'monospace',fontSize:12}}>{p.keep_subtitle_langs == null ? '(same as audio)' : (p.keep_subtitle_langs.length ? p.keep_subtitle_langs.join(', ') : 'all')}</span></div>
          </div>

          <div style={s.section}>
            <h3 style={s.h3}>Paths</h3>
            {!(data.paths || []).length ? (
              <div className="empty">No paths configured.</div>
            ) : (
              <div className="path-list">
                {(data.paths || []).map((path, i) => (
                  <div className="path-item" key={i}>
                    <span style={{color:'#33ff33'}}>{'\u2713'}</span>
                    {path}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="col-side">
          <div style={s.section}>
            <h3 style={s.h3}>Lifetime</h3>
            <div className="detail-row"><span className="label">Total runs</span><span className="value" style={{fontFamily:'monospace',fontSize:12}}>{runs.length}</span></div>
            <div className="detail-row"><span className="label">Files processed</span><span className="value" style={{fontFamily:'monospace',fontSize:12}}>{totalFiles}</span></div>
            <div className="detail-row"><span className="label">Total saved</span><span className="value" style={{fontFamily:'monospace',fontSize:12}}>{(totalSaved / 1024).toFixed(2)} GB</span></div>
          </div>

          {lastRun && (
            <div style={s.section}>
              <h3 style={s.h3}>Last Run</h3>
              <div className="detail-row"><span className="label">Date</span><span className="value" style={{fontFamily:'monospace',fontSize:12}}>{lastRun.ended_at ? new Date(lastRun.ended_at * 1000).toLocaleString() : '—'}</span></div>
              <div className="detail-row"><span className="label">Status</span><span className="value"><span className={'tag ' + (lastRun.exit_code === 0 ? 'ok' : lastRun.exit_code === -15 ? 'skip' : 'fail')}>{lastRun.exit_code === 0 ? 'OK' : lastRun.exit_code === -15 ? 'Stopped' : lastRun.exit_code == null ? 'Incomplete' : 'FAIL'}</span></span></div>
              <div className="detail-row"><span className="label">Result</span><span className="value" style={{fontFamily:'monospace',fontSize:12}}>{(lastRun.summary?.ok || 0) + ' ok / ' + (lastRun.summary?.skip || 0) + ' skip / ' + (lastRun.summary?.fail || 0) + ' fail'}</span></div>
              <div className="detail-row"><span className="label">Saved</span><span className="value" style={{fontFamily:'monospace',fontSize:12}}>{lastRun.summary?.space_saved_mb > 0 ? (lastRun.summary.space_saved_mb / 1024).toFixed(2) + ' GB' : '—'}</span></div>
            </div>
          )}
        </div>
      </div>

      <div style={s.section}>
        <h3 style={s.h3}>Run History</h3>
        {!runs.length ? (
          <div className="empty">No runs yet.</div>
        ) : (
          <div className="table-wrap"><table className="libs-table"><thead><tr><th>Date</th><th>OK</th><th>Skip</th><th>Fail</th><th>Saved</th><th>Status</th><th></th></tr></thead><tbody>
            {runs.map(r => {
              const rs = r.summary || {}
              const date = r.started_at ? new Date(r.started_at * 1000).toLocaleString() : '—'
              const saved = rs.space_saved_mb > 0 ? (rs.space_saved_mb / 1024).toFixed(2) + ' GB' : '—'
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
                <tr key={r.run_id} className={r.running ? 'row-running' : ''} onClick={() => navigate(viewLink)} style={{cursor:'pointer'}}>
                  <td><span className="mono">{date}</span></td>
                  <td><span className="mono ok">{rs.ok || 0}</span></td>
                  <td><span className="mono skip">{rs.skip || 0}</span></td>
                  <td><span className="mono fail">{rs.fail || 0}</span></td>
                  <td><span className="mono">{saved}</span></td>
                  <td><span className={'tag ' + statusClass}>{status}</span></td>
                  <td className="cell-actions"><button className="link-btn" onClick={e => { e.stopPropagation(); navigate(viewLink) }}>View</button></td>
                </tr>
              )
            })}
          </tbody></table></div>
        )}
      </div>

      <RecentRunModal
        open={recentOpen}
        onClose={() => setRecentOpen(false)}
        libraries={name}
        fixedLibrary
        title={'Recently Added - ' + name}
      />
    </>
  )
}

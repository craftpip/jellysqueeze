import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate, useOutletContext } from 'react-router-dom'
import { api } from '../api'

const MAX_LINES = 200

function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const remainingSeconds = total % 60
  return hours
    ? String(hours) + ':' + String(minutes).padStart(2, '0') + ':' + String(remainingSeconds).padStart(2, '0')
    : String(minutes) + ':' + String(remainingSeconds).padStart(2, '0')
}

export default function RunDetail() {
  const { setPageTitle } = useOutletContext()
  const { runId } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [lines, setLines] = useState([])
  const [results, setResults] = useState([])
  const [running, setRunning] = useState(false)
  const [library, setLibrary] = useState('')
  const [summary, setSummary] = useState({})
  const [stopping, setStopping] = useState(false)
  const [startedAt, setStartedAt] = useState(null)
  const [endedAt, setEndedAt] = useState(null)
  const [exitCode, setExitCode] = useState(null)
  const [activeProgress, setActiveProgress] = useState({})
  const [resultFilter, setResultFilter] = useState('done-failed')
  const [folderTotals, setFolderTotals] = useState({})
  const [runStatus, setRunStatus] = useState({ phase: '', message: '' })
  const [error, setError] = useState('')
  const wsRef = useRef(null)
  const pollRef = useRef(null)
  const outputRef = useRef(null)

  useEffect(() => {
    let mounted = true

    async function load() {
      let buf
      try {
        buf = await api('GET', '/api/status/' + runId)
      } catch (err) {
        if (mounted) { setError(err.message); setLoading(false) }
        return
      }
      if (!mounted) return
      setData(buf)
      setLoading(false)
      if (!buf || buf.error) return

      const rawLines = buf.terminal_output && buf.terminal_output.length
        ? buf.terminal_output.map(o => String(o.data || '')).slice(-MAX_LINES)
        : buf.output && buf.output.length
          ? buf.output.map(o => String(o.data || '')).filter(line => {
              try { return !JSON.parse(line.trim()).type } catch (_) { return true }
            }).slice(-MAX_LINES)
          : []
      const initialLines = rawLines.length ? rawLines : ['Connecting...']
      setLines(initialLines)
      setResults(buf.results || [])
      setFolderTotals(buf.folder_totals || {})
      setLibrary(buf.library || '')
      setSummary(buf.summary || {})
      setStartedAt(buf.started_at || null)
      setEndedAt(buf.ended_at || null)
      setExitCode(buf.exit_code)
      setRunning(!!buf.running)

      if (buf.running) {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
        const ws = new WebSocket(proto + '//' + location.host + '/api/ws/' + runId)
        wsRef.current = ws

        ws.onmessage = (e) => {
          if (!mounted) return
          const msg = JSON.parse(e.data)
          if (msg.type === 'stdout' || msg.type === 'stderr') {
            const d = String(msg.data || '')
            const trimmed = d.trim()
            if (trimmed.startsWith('{')) {
              try {
                const p = JSON.parse(trimmed)
                if (p.type === 'progress') {
                  setActiveProgress(prev => {
                    const next = { ...prev }
                    if (typeof p.percent === 'number' && p.file) {
                      next[p.file] = {
                        percent: p.percent,
                        finalizing: !!p.finalizing,
                        positionSeconds: p.position_seconds,
                        durationSeconds: p.duration_seconds,
                        frameCount: p.frame_count,
                        totalFrames: p.total_frames,
                      }
                    } else if (p.file) {
                      delete next[p.file]
                    }
                    return next
                  })
                } else if (p.type === 'run_status') {
                  setRunStatus({ phase: p.phase || '', message: p.message || '' })
                } else if (p.type === 'run_folder' && p.root) {
                  setFolderTotals(prev => ({ ...prev, [p.root]: p.total || 0 }))
                }
              } catch (_) {}
            } else {
              setLines(prev => [...prev, d].slice(-MAX_LINES))
            }
          } else if (msg.type === 'exit') {
            setLines(prev => [...prev, '--- Process exited with code ' + msg.code + ' ---'].slice(-MAX_LINES))
            setRunning(false)
            setExitCode(msg.code)
            setEndedAt(Date.now() / 1000)
            setActiveProgress({})
            setTimeout(() => { if (ws) ws.close() }, 500)
          }
        }

        ws.onerror = () => { if (mounted) setLines(prev => [...prev, 'WebSocket error'].slice(-MAX_LINES)) }
        ws.onclose = () => { if (mounted) setLines(prev => [...prev, 'Connection closed'].slice(-MAX_LINES)) }

        pollRef.current = setInterval(async () => {
          if (!mounted) return
          let st
          try {
            st = await api('GET', '/api/status/' + runId)
          } catch (err) {
            if (mounted) setError(err.message)
            return
          }
          if (!st) return
          setResults(st.results || [])
          setSummary(st.summary || {})
          if (st.started_at) setStartedAt(st.started_at)
          if (!st.running && mounted) {
            clearInterval(pollRef.current)
            setRunning(false)
            setExitCode(st.exit_code)
            setEndedAt(st.ended_at || Date.now() / 1000)
          }
        }, 2000)
      }
    }

    load()

    return () => {
      mounted = false
      if (wsRef.current) wsRef.current.close()
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [runId])

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [lines])

  useEffect(() => {
    setPageTitle(library ? (running ? library + ' (LIVE)' : library) : 'Run Detail')
  }, [library, running, setPageTitle])

  const stopRun = async () => {
    setStopping(true)
    try {
      await api('POST', '/api/stop/' + runId)
    } catch (err) {
      setError(err.message)
      setStopping(false)
    }
  }

  const downloadLog = () => {
    window.open('/api/log/' + runId, '_blank')
  }

  if (loading) return <div className="loading-overlay" style={{ position: 'relative', height: 200 }}><div className="spinner"></div></div>
  if (!data || data.error) return <div className="card"><div className="empty">{error || 'Run not found.'}</div></div>

  const okCount = results.filter(r => r.status === 'OK').length
  const skipCount = results.filter(r => r.status === 'SKIP').length
  const failCount = results.filter(r => r.status === 'FAIL').length

  const savedFromResults = results
    .filter(r => r.before && r.after)
    .reduce((sum, r) => sum + (r.before - r.after) / (1024 * 1024), 0)
  const s = summary || {}
  const savedMb = savedFromResults || s.space_saved_mb || 0
  const saved = savedMb > 0 ? (savedMb / 1024).toFixed(2) + ' GB' : '—'
  const startedStr = startedAt ? new Date(startedAt * 1000).toLocaleString() : '—'
  const endedStr = endedAt ? new Date(endedAt * 1000).toLocaleString() : '—'

  const activeFiles = Object.entries(activeProgress)
  const runTotal = Object.values(folderTotals).reduce((sum, total) => sum + total, 0)
  const runPct = runTotal > 0 ? results.length / runTotal * 100 : 0
  const visibleResults = results.filter(r => {
    if (resultFilter === 'all') return true
    if (resultFilter === 'done') return r.status === 'OK'
    if (resultFilter === 'failed') return r.status === 'FAIL'
    if (resultFilter === 'skipped') return r.status === 'SKIP'
    return r.status === 'OK' || r.status === 'FAIL'
  })

  const activeFilePaths = activeFiles.map(([fp]) => fp)

  const folderEntries = Object.entries(folderTotals).map(([root, total]) => {
    const done = results.filter(r => r.file && r.file.startsWith(root)).length
    const isActive = activeFilePaths.some(fp => fp.startsWith(root))
    const status = done >= total ? 'complete' : isActive ? 'active' : 'pending'
    return { root, total, done, status }
  }).sort((a, b) => {
    const order = { active: 0, pending: 1, complete: 2 }
    return order[a.status] - order[b.status]
  })

  return (
    <>
      <div className="flex items-center gap-8 mb-8">
        <button className="btn outline sm" onClick={() => navigate(-1)}>&#8592; Back</button>
        <h3 style={{ flex: 1 }}>
          {library || 'Run'}
          {running ? <><span className="dot running" style={{ margin: '0 6px 0 8px', verticalAlign: 'middle' }}></span><span className="text-green">LIVE</span></> : ''}
        </h3>
        <button className="btn outline sm" onClick={downloadLog}>&#8615; Log</button>
        {running ? (
          <button className="btn danger sm" onClick={stopRun} disabled={stopping}>&#9632; Stop</button>
        ) : null}
      </div>
      {error && <div className="error-message">{error}</div>}

      <div id="card-info" className="card">
        <div className="detail-row"><span className="label">Library</span><span className="value">{library || '—'}</span></div>
        <div className="detail-row"><span className="label">Started</span><span className="value">{startedStr}</span></div>
        {!running && <div className="detail-row"><span className="label">Ended</span><span className="value">{endedStr}</span></div>}
        {!running && <div className="detail-row"><span className="label">Exit code</span><span className="value">{exitCode != null ? exitCode : '—'}</span></div>}
        <div className="detail-row"><span className="label">OK/Skip/Fail</span><span className="value">{okCount} / {skipCount} / {failCount}</span></div>
        <div className="detail-row"><span className="label">Space saved</span><span className="value">{saved}</span></div>
        <div className="detail-row"><span className="label">Files processed</span><span className="value">{results.length}</span></div>
        <div className="detail-row"><span className="label">Files total</span><span className="value">{runTotal || '—'}</span></div>
      </div>

      {running && runTotal > 0 && (
        <div id="card-run-progress" className="card" style={{ padding: '10px 16px' }}>
          <div className="flex items-center gap-8" style={{ marginBottom: 6 }}>
            <span className="text-muted" style={{ fontSize: 12, minWidth: 82 }}>Run Progress</span>
            <span className="text-muted" style={{ flex: 1, fontSize: 12 }}>OK {okCount} / Skip {skipCount} / Fail {failCount}</span>
            <span className="text-muted" style={{ fontSize: 12, minWidth: 150, textAlign: 'right' }}>{results.length} / {runTotal} ({runPct.toFixed(1)}%)</span>
          </div>
          <div style={{ height: 6, background: '#2a2a2a', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: runPct + '%', background: '#66bb6a', borderRadius: 3, transition: 'width .3s ease' }}></div>
          </div>
        </div>
      )}

      {running && activeFiles.length > 0 && (
        <div id="card-encoding-progress" className="card" style={{ padding: '10px 16px' }}>
          {activeFiles.map(([file, progress], index) => {
            const fileName = file.split(/[\\/]/).pop()
            return (
              <div key={file} style={{ marginTop: index ? 10 : 0 }}>
                <div className="flex items-center gap-8" style={{ marginBottom: 6 }}>
                  <span className="text-muted" style={{ fontSize: 12, minWidth: 50 }}>{progress.finalizing ? 'Finalizing' : 'Encoding'}</span>
                  <span className="file" title={file} style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12, color: '#ccc' }}>{fileName}</span>
                  <span className="text-muted" style={{ fontSize: 12, minWidth: 140, textAlign: 'right' }}>
                    {progress.finalizing
                      ? ''
                      : (progress.positionSeconds != null && progress.durationSeconds
                        ? formatDuration(progress.positionSeconds) + ' / ' + formatDuration(progress.durationSeconds) + ' (' + progress.percent.toFixed(1) + '%)'
                        : (progress.frameCount != null && progress.totalFrames
                          ? 'Frame ' + progress.frameCount.toLocaleString() + ' / ~' + progress.totalFrames.toLocaleString()
                        : progress.percent.toFixed(1) + '%'))}
                  </span>
                </div>
                <div style={{ height: 6, background: '#2a2a2a', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: progress.percent + '%', background: '#4c9aff', borderRadius: 3, transition: 'width .3s ease' }}></div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {running && activeFiles.length === 0 && runStatus.message && (
        <div id="card-run-status" className="card" style={{ padding: '8px 16px', fontSize: 13, color: '#999' }}>
          {runStatus.message}
        </div>
      )}

      {running && folderEntries.length > 1 && (
        <div id="card-directory-progress" className="card" style={{ padding: '10px 16px' }}>
          <div className="flex items-center gap-8" style={{ marginBottom: 8 }}>
            <span className="text-muted" style={{ fontSize: 12 }}>Directory Progress</span>
          </div>
          {folderEntries.map(({ root, total, done, status }) => {
            const pct = total > 0 ? done / total * 100 : 0
            const label = root
            return (
              <div key={root} style={{ marginTop: 6 }}>
                <div className="flex items-center gap-8" style={{ marginBottom: 4 }}>
                  <span className={'tag ' + status} style={{ minWidth: 100, textAlign: 'center' }}>
                    {status === 'active' ? 'Encoding' : status === 'complete' ? 'Done' : 'Pending'}
                  </span>
                  <span className="file" title={root} style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12, color: '#ccc' }}>{label}</span>
                  <span className="text-muted" style={{ fontSize: 12, minWidth: 100, textAlign: 'right' }}>{done} / {total}</span>
                </div>
                <div style={{ height: 4, background: '#2a2a2a', borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: pct + '%', borderRadius: 2, transition: 'width .3s ease',
                    background: status === 'active' ? '#4c9aff' : status === 'complete' ? '#66bb6a' : '#555' }}></div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      <div id="card-terminal" className="run-terminal" ref={outputRef} style={{ height: 300 }}>{lines.join('\n')}</div>

      {results.length > 0 && (
        <div id="card-processed-files" className="card">
          <div className="flex items-center gap-8" style={{ marginBottom: 12 }}>
            <h3 style={{ flex: 1, margin: 0 }}>Processed Files</h3>
            <button className={'btn outline sm' + (resultFilter === 'done-failed' ? ' active' : '')} onClick={() => setResultFilter('done-failed')}>Done &amp; Failed</button>
            <button className={'btn outline sm' + (resultFilter === 'done' ? ' active' : '')} onClick={() => setResultFilter('done')}>Done {okCount > 0 && <span className="badge">{okCount}</span>}</button>
            <button className={'btn outline sm' + (resultFilter === 'failed' ? ' active' : '')} onClick={() => setResultFilter('failed')}>Failed {failCount > 0 && <span className="badge">{failCount}</span>}</button>
            <button className={'btn outline sm' + (resultFilter === 'skipped' ? ' active' : '')} onClick={() => setResultFilter('skipped')}>Skipped {skipCount > 0 && <span className="badge">{skipCount}</span>}</button>
            <button className={'btn outline sm' + (resultFilter === 'all' ? ' active' : '')} onClick={() => setResultFilter('all')}>All</button>
          </div>
          <table><thead><tr><th>Status</th><th>File</th><th>Result</th><th>Saved</th></tr></thead><tbody>
          {visibleResults.slice().reverse().map((r, i) => {
            const tag = r.status === 'OK' ? 'ok' : r.status === 'SKIP' ? 'skip' : 'fail'
            const saved2 = r.before && r.after ? ((r.before - r.after) / (1024 * 1024)).toFixed(1) + ' MB' : '—'
            return (
              <tr key={i}>
                <td><span className={'tag ' + tag}>{r.status}</span></td>
                <td className="file" title={r.file || ''}>{r.file || ''}</td>
                <td className="text-muted">{r.msg || '—'}</td>
                <td className="text-muted">{saved2}</td>
              </tr>
            )
          })}
          {!visibleResults.length && <tr><td colSpan="4" className="text-muted">No matching files.</td></tr>}
          </tbody></table>
        </div>
      )}
    </>
  )
}

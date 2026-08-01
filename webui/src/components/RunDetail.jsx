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
  const [filterChecks, setFilterChecks] = useState({ done: true, failed: true, skipped: false })
  const [nameFilter, setNameFilter] = useState('')
  const [folderTotals, setFolderTotals] = useState({})
  const [runStatus, setRunStatus] = useState({ phase: '', message: '' })
  const [error, setError] = useState('')
  const wsRef = useRef(null)
  const pollRef = useRef(null)
  const outputRef = useRef(null)
  const pendingLinesRef = useRef([])
  const flushTimerRef = useRef(null)
  const lastRenderedRef = useRef('')

  const appendLine = (d) => {
    const pending = pendingLinesRef.current
    const last = pending.length ? pending[pending.length - 1] : lastRenderedRef.current
    if (last === d) return
    pending.push(d)
  }

  const flushLines = () => {
    const pending = pendingLinesRef.current
    if (!pending.length) return
    pendingLinesRef.current = []
    setLines(prev => {
      const merged = prev.concat(pending).slice(-MAX_LINES)
      lastRenderedRef.current = merged.length ? merged[merged.length - 1] : ''
      return merged
    })
  }

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
      setRunStatus(buf.run_status || { phase: '', message: '' })
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
                  setRunStatus(prev => ({
                    phase: p.phase || '',
                    message: p.message || '',
                    files_total: p.files_total != null ? p.files_total : (prev.files_total || 0),
                  }))
                } else if (p.type === 'run_folder' && p.root) {
                  setFolderTotals(prev => ({ ...prev, [p.root]: p.total || 0 }))
                } else if (p.type === 'result' && p.file) {
                  const entry = {
                    file: p.file,
                    status: p.status || 'FAIL',
                    msg: p.msg || '',
                    before: p.before || 0,
                    after: p.after || 0,
                  }
                  setResults(prev => {
                    const idx = prev.findIndex(r => r.file === p.file)
                    if (idx === -1) return [...prev, entry]
                    const next = prev.slice()
                    next[idx] = entry
                    return next
                  })
                  setActiveProgress(prev => {
                    const next = { ...prev }
                    delete next[p.file]
                    return next
                  })
                }
              } catch (_) {}
            } else {
              appendLine(d)
            }
          } else if (msg.type === 'exit') {
            appendLine('--- Process exited with code ' + msg.code + ' ---')
            setRunning(false)
            setExitCode(msg.code)
            setEndedAt(Date.now() / 1000)
            setActiveProgress({})
            setTimeout(() => { if (ws) ws.close() }, 500)
          }
        }

        ws.onerror = () => { if (mounted) appendLine('WebSocket error') }
        ws.onclose = () => { if (mounted) appendLine('Connection closed') }

        flushTimerRef.current = setInterval(() => {
          if (!mounted) return
          flushLines()
        }, 200)

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
          setRunStatus(st.run_status || { phase: '', message: '' })
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
      flushLines()
      pendingLinesRef.current = []
      mounted = false
      if (flushTimerRef.current) clearInterval(flushTimerRef.current)
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
  const folderTotal = Object.values(folderTotals).reduce((sum, total) => sum + total, 0)
  const runTotal = folderTotal > 0 ? folderTotal : (runStatus.files_total || 0)
  const runPct = runTotal > 0 ? results.length / runTotal * 100 : 0
  const visibleResults = results.filter(r => {
    if (r.status === 'OK' && !filterChecks.done) return false
    if (r.status === 'FAIL' && !filterChecks.failed) return false
    if (r.status === 'SKIP' && !filterChecks.skipped) return false
    const q = nameFilter.trim().toLowerCase()
    if (q && !(r.file || '').toLowerCase().includes(q)) return false
    return true
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
      <button className="link-btn mb-8" onClick={() => navigate(-1)}>&#8592; Back</button>
      <div className="dash-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: 8, margin: 0 }}>
            {library || 'Run'}
            {running && (
              <span className="status-running">
                <span className="pulse-dot"></span>LIVE
              </span>
            )}
          </h2>
          <div className="dash-actions" style={{ gap: 12 }}>
            <button className="link-btn" onClick={downloadLog}>&#8615; Log</button>
            {running && (
              <button className="link-btn" style={{color:'#e05050'}} onClick={stopRun} disabled={stopping}>&#9632; Stop</button>
            )}
          </div>
        </div>
      </div>
      {error && <div className="error-message">{error}</div>}

      <div className="run-detail-grid" style={{ display: 'flex', gap: 16, alignItems: 'flex-start', marginBottom: 20 }}>
        <div className="run-detail-left" style={{ flex: 1, minWidth: 0 }}>
          <div id="section-info" className="detail-rows">
            <div className="detail-row"><span className="label">Library</span><span className="value">{library || '—'}</span></div>
            <div className="detail-row"><span className="label">Started</span><span className="value">{startedStr}</span></div>
            {!running && <div className="detail-row"><span className="label">Ended</span><span className="value">{endedStr}</span></div>}
            {!running && <div className="detail-row"><span className="label">Exit code</span><span className="value">{exitCode != null ? exitCode : '—'}</span></div>}
            <div className="detail-row"><span className="label">OK/Skip/Fail</span><span className="value">{okCount} / {skipCount} / {failCount}</span></div>
            <div className="detail-row"><span className="label">Space saved</span><span className="value">{saved}</span></div>
            <div className="detail-row"><span className="label">Files processed</span><span className="value">{results.length}</span></div>
            <div className="detail-row"><span className="label">Files total</span><span className="value">{runTotal || '—'}</span></div>
          </div>
        </div>
        <div className="run-detail-right" style={{ flex: 1, minWidth: 0 }}>
          {running && runTotal > 0 && (
            <div id="section-run-progress" style={{ marginBottom: 16 }}>
              <div className="flex items-center gap-8">
                <span className="text-muted" style={{ minWidth: 82 }}>Run Progress</span>
                <span className="text-muted" style={{ flex: 1 }}>OK {okCount} / Skip {skipCount} / Fail {failCount}</span>
                <span className="text-muted" style={{ minWidth: 150, textAlign: 'right' }}>{results.length} / {runTotal} ({runPct.toFixed(1)}%)</span>
              </div>
              <div style={{ height: 6, background: '#2a2a2a', borderRadius: 3, overflow: 'hidden', marginTop: 6 }}>
                <div style={{ height: '100%', width: runPct + '%', background: '#66bb6a', borderRadius: 3, transition: 'width .3s ease' }}></div>
              </div>
            </div>
          )}

          {running && activeFiles.length > 0 && (
            <div id="section-encoding-progress" style={{ marginBottom: 16 }}>
              {activeFiles.map(([file, progress], index) => {
                const fileName = file.split(/[\\/]/).pop()
                return (
                  <div key={file} style={{ marginTop: index ? 10 : 0 }}>
                    <div className="flex items-center gap-8" style={{ marginBottom: 6 }}>
                      <span className="text-muted" style={{ minWidth: 50 }}>{progress.finalizing ? 'Finalizing' : 'Encoding'}</span>
                      <span className="file-ellipsis" title={file}>{fileName}</span>
                      <span className="text-muted" style={{ minWidth: 140, textAlign: 'right' }}>
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
            <div id="section-run-status" className="text-muted" style={{ marginBottom: 16 }}>
              {runStatus.message}
            </div>
          )}

          {running && folderEntries.length > 1 && (
            <div id="section-directory-progress" style={{ marginBottom: 16 }}>
              <div className="flex items-center gap-8" style={{ marginBottom: 8 }}>
                <span className="text-muted">Directory Progress</span>
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
                      <span className="file-ellipsis" title={root}>{label}</span>
                      <span className="text-muted" style={{ minWidth: 100, textAlign: 'right' }}>{done} / {total}</span>
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
        </div>
      </div>

      {results.length > 0 && (
        <div id="section-processed-files" style={{ marginBottom: 16 }}>
          <div className="flex items-center gap-8 mb-8">
            <h3 style={{ flex: 1, margin: 0, fontSize: 14, fontWeight: 600, color: '#ccc' }}>Processed Files</h3>
            <input
              className="filter-input"
              type="text"
              placeholder="Filter by name..."
              value={nameFilter}
              onChange={e => setNameFilter(e.target.value)}
            />
            <button className={'btn outline sm' + (filterChecks.done ? ' active' : '')} onClick={() => setFilterChecks(p => ({ ...p, done: !p.done }))}>Done <span className="badge">{okCount}</span></button>
            <button className={'btn outline sm' + (filterChecks.failed ? ' active' : '')} onClick={() => setFilterChecks(p => ({ ...p, failed: !p.failed }))}>Failed <span className="badge">{failCount}</span></button>
            <button className={'btn outline sm' + (filterChecks.skipped ? ' active' : '')} onClick={() => setFilterChecks(p => ({ ...p, skipped: !p.skipped }))}>Skipped <span className="badge">{skipCount}</span></button>
          </div>
           <table className="libs-table" style={{ tableLayout: 'fixed' }}><thead><tr><th style={{ width: 70 }}>Status</th><th>File</th><th style={{ width: 200 }}>Result</th><th style={{ width: 80 }}>Saved</th></tr></thead><tbody>
          {visibleResults.slice().reverse().map((r, i) => {
            const tag = r.status === 'OK' ? 'ok' : r.status === 'SKIP' ? 'skip' : 'fail'
            const saved2 = r.before && r.after ? ((r.before - r.after) / (1024 * 1024)).toFixed(1) + ' MB' : '—'
            return (
              <tr key={i}>
                <td><span className={'tag ' + tag}>{r.status}</span></td>
                <td className="file-ellipsis" title={r.file || ''}>{r.file || ''}</td>
                <td className="text-muted">{r.msg || '—'}</td>
                <td><span className="mono">{saved2}</span></td>
              </tr>
            )
          })}
          {!visibleResults.length && <tr><td colSpan="4" className="text-muted">No matching files.</td></tr>}
          </tbody></table>
        </div>
      )}

      <div id="section-terminal-wrapper" style={{ marginTop: 20, marginBottom: 20 }}>
        <h3 style={{ margin: '0 0 10px 0', fontSize: 14, fontWeight: 600, color: '#ccc' }}>Terminal Output</h3>
        <div id="section-terminal" className="run-terminal" ref={outputRef} style={{ height: 300 }}>{lines.join('\n')}</div>
      </div>
    </>
  )
}

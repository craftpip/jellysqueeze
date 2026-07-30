import { useState, useEffect } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '../api'

export default function Layout() {
  const [stats, setStats] = useState(null)
  const [pageTitle, setPageTitle] = useState('Dashboard')

  useEffect(() => {
    const poll = async () => {
      try {
        const d = await api('GET', '/api/system-stats')
        setStats(d)
      } catch {}
    }
    poll()
    const id = setInterval(poll, 4000)
    return () => clearInterval(id)
  }, [])

  function bar(pct, w = 20) {
    if (pct == null) return ''
    const filled = Math.round(pct / 100 * w)
    return '\u2588'.repeat(filled) + '\u2591'.repeat(Math.max(0, w - filled))
  }

  return (
    <div className="app">
      <div className="sidebar">
        <h1>Media Convert</h1>
        <ul className="nav">
          <li><NavLink to="/" end><span>&#9632;</span> Dashboard</NavLink></li>
          <li><NavLink to="/new-library"><span>+</span> New Library</NavLink></li>
          <li><NavLink to="/runs"><span>&#9776;</span> Run History</NavLink></li>
          <li><NavLink to="/settings"><span>&#9881;</span> Settings</NavLink></li>
        </ul>
        <div className="sidebar-stats">
          {stats && (
            <>
              <div className="stat-row">
                <span className="stat-label">CPU</span>
                <span className="stat-val">{stats.cpu?.percent ?? '?'}%</span>
                <span className="stat-bar">{bar(stats.cpu?.percent)}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">MEM</span>
                <span className="stat-val">{stats.memory?.percent ?? '?'}%</span>
                <span className="stat-bar">{bar(stats.memory?.percent)}</span>
              </div>
              {stats.gpu && stats.gpu.length > 0 && stats.gpu.map((g, i) => (
                <div className="stat-row" key={i}>
                  <span className="stat-label">GPU{i}</span>
                  <span className="stat-val">
                    {g.util_percent != null ? g.util_percent + '%' : '?'}
                  </span>
                  <span className="stat-bar">{bar(g.util_percent)}</span>
                </div>
              ))}
              {stats.gpu && stats.gpu.length > 0 && (
                <div className="stat-row gpu-mem">
                  <span className="stat-label">VRAM</span>
                  <span className="stat-val">
                    {stats.gpu.map(g =>
                      (g.mem_used_mb != null ? (g.mem_used_mb / 1024).toFixed(1) : '?') + '/' +
                      (g.mem_total_mb != null ? (g.mem_total_mb / 1024).toFixed(1) : '?') + 'G'
                    ).join(' ')}
                  </span>
                </div>
              )}
              {stats.gpu && stats.gpu.length > 0 && (
                <div className="stat-row">
                  <span className="stat-label">TEMP</span>
                  <span className="stat-val">
                    {stats.gpu.map(g =>
                      g.temp_c != null ? g.temp_c + '\u00B0C' : '?'
                    ).join(' ')}
                  </span>
                </div>
              )}
            </>
          )}
        </div>
      </div>
      <div className="main">
        <div className="topbar">
          <h2 id="page-title">{pageTitle}</h2>
          <div className="status" id="top-status-bar" style={{ display: 'none' }}></div>
        </div>
        <div className="content">
          <Outlet context={{ setPageTitle }} />
        </div>
      </div>
    </div>
  )
}

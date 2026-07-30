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

  function bar(pct, w = 10) {
    if (pct == null) return ''
    const filled = Math.round(pct / 100 * w)
    return '\u2588'.repeat(filled) + '\u2591'.repeat(Math.max(0, w - filled))
  }

  return (
    <div className="app">
      <div className="topbar">
        <div className="topbar-left">
          <h1>Media Convert</h1>
          <ul className="nav">
            <li><NavLink to="/" end>Dashboard</NavLink></li>
            <li><NavLink to="/new-library">New Library</NavLink></li>
            <li><NavLink to="/runs">Run History</NavLink></li>
            <li><NavLink to="/errors">Errors</NavLink></li>
            <li><NavLink to="/settings">Settings</NavLink></li>
          </ul>
        </div>
        <div className="topbar-stats">
          {stats && (
            <>
              <span className="stat-item">CPU {stats.cpu?.percent ?? '?'}% {bar(stats.cpu?.percent)}</span>
              {stats.gpu && stats.gpu.length > 0 && stats.gpu.map((g, i) => (
                <span className="stat-item" key={i}>
                  GPU{i} {g.util_percent != null ? g.util_percent + '%' : '?'} {bar(g.util_percent)}
                </span>
              ))}
              {stats.gpu && stats.gpu.length > 0 && (
                <span className="stat-item">
                  TEMP {stats.gpu.map(g => g.temp_c != null ? g.temp_c + '\u00B0C' : '?').join(' ')}
                </span>
              )}
            </>
          )}
        </div>
      </div>
      <div className="content">
        <Outlet context={{ setPageTitle }} />
      </div>
    </div>
  )
}

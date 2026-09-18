import { useState, useEffect } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '../api'

export default function Layout({ passwordSet }) {
  const [stats, setStats] = useState(null)
  const [pageTitle, setPageTitle] = useState('Dashboard')

  const signOut = async () => {
    try {
      await api('POST', '/api/logout')
    } catch {}
    window.location.reload()
  }

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
          <NavLink to="/" end className="brand" aria-label="JellySqueeze dashboard">
            <svg className="logo-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="6" y="6" width="12" height="12" rx="2" />
              <path d="M12 2.5v5M12 7.5l-2.5-2.5M12 7.5l2.5-2.5" />
              <path d="M12 21.5v-5M12 16.5l-2.5 2.5M12 16.5l2.5 2.5" />
            </svg>
            <h1>JellySqueeze</h1>
          </NavLink>
          <ul className="nav">
            <li><NavLink to="/" end>Dashboard</NavLink></li>
            <li><NavLink to="/new-library">Add Library</NavLink></li>
            <li><NavLink to="/runs">Run History</NavLink></li>
            <li><NavLink to="/schedules">Schedules</NavLink></li>
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
        {passwordSet && (
          <button type="button" className="btn outline sm signout" onClick={signOut}>Signout</button>
        )}
      </div>
      <div className="content">
        <Outlet context={{ setPageTitle }} />
      </div>
    </div>
  )
}

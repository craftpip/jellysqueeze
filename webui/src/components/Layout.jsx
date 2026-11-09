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

  function bar(pct, w = 8) {
    if (pct == null) return ''
    const filled = Math.round(pct / 100 * w)
    return '\u2588'.repeat(filled) + '\u2591'.repeat(Math.max(0, w - filled))
  }

  return (
    <div className="app">
      <div className="topbar">
        <div className="topbar-left">
          <NavLink to="/" end className="brand" aria-label="JellySqueeze dashboard">
<img src="/static/logo.png" className="logo-icon" width="18" height="18" alt="" />
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
        {stats && (
          <div className="topbar-stats" aria-label="System stats">
            <span className="stat-line"><span className="stat-lbl">CPU</span><span className="stat-val">{stats.cpu?.percent ?? '?'}%</span><span className="stat-bar">{bar(stats.cpu?.percent)}</span></span>
            {stats.gpu && stats.gpu.length > 0 ? (
              stats.gpu.map((g, i) => (
                <span className="stat-line" key={i}><span className="stat-lbl">GPU{i}</span><span className="stat-val">{g.util_percent != null ? g.util_percent + '%' : '?'}</span><span className="stat-bar">{bar(g.util_percent)}</span></span>
              ))
            ) : (
              <span className="stat-line"><span className="stat-lbl">GPU</span><span className="stat-val">n/a</span><span className="stat-bar"></span></span>
            )}
          </div>
        )}
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

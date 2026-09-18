import { useState } from 'react'
import { api } from '../api'

export default function Login({ onSuccess }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api('POST', '/api/login', { password })
      onSuccess()
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="login-brand">
          <svg className="logo-icon" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="6" y="6" width="12" height="12" rx="2" />
            <path d="M12 2.5v5M12 7.5l-2.5-2.5M12 7.5l2.5-2.5" />
            <path d="M12 21.5v-5M12 16.5l-2.5 2.5M12 16.5l2.5 2.5" />
          </svg>
          <h1>JellySqueeze</h1>
        </div>
        <form className="login-form" onSubmit={submit}>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            autoFocus
            required
          />
          <button className="btn primary" type="submit" disabled={busy || !password}>
            {busy ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
        {error && <div className="error-message">{error}</div>}
      </div>
    </div>
  )
}

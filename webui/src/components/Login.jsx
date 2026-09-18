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
<img src="/static/logo.png" className="logo-icon" width="22" height="22" alt="" />
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

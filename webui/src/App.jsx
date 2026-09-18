import { useEffect, useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import { api } from './api'
import Layout from './components/Layout'
import Dashboard from './components/Dashboard'
import LibraryForm from './components/LibraryForm'
import LibraryDetail from './components/LibraryDetail'
import RunHistory from './components/RunHistory'
import Schedules from './components/Schedules'
import RunDetail from './components/RunDetail'
import ErrorList from './components/ErrorList'
import Settings from './components/Settings'
import Login from './components/Login'

export default function App() {
  const [auth, setAuth] = useState({ loading: true, showLogin: false, passwordSet: false })

  const checkAuth = async () => {
    try {
      const data = await api('GET', '/api/auth-status')
      setAuth({ loading: false, showLogin: !!(data.password_set && !data.authenticated), passwordSet: !!data.password_set })
    } catch {
      setAuth({ loading: false, showLogin: false, passwordSet: false })
    }
  }

  useEffect(() => { checkAuth() }, [])

  if (auth.loading) {
    return (
      <div className="loading-overlay">
        <div className="spinner" />
      </div>
    )
  }

  if (auth.showLogin) {
    return <Login onSuccess={checkAuth} />
  }

  return (
    <Routes>
      <Route element={<Layout passwordSet={auth.passwordSet} />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/new-library" element={<LibraryForm />} />
        <Route path="/edit-library/:name" element={<LibraryForm />} />
        <Route path="/library-detail/:name" element={<LibraryDetail />} />
        <Route path="/runs" element={<RunHistory />} />
        <Route path="/schedules" element={<Schedules />} />
        <Route path="/errors" element={<ErrorList />} />
        <Route path="/run-detail/:runId" element={<RunDetail />} />
        <Route path="/live-run/:runId" element={<RunDetail />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}

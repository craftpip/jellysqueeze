import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './components/Dashboard'
import LibraryForm from './components/LibraryForm'
import LibraryDetail from './components/LibraryDetail'
import RunHistory from './components/RunHistory'
import Schedules from './components/Schedules'
import RunDetail from './components/RunDetail'
import ErrorList from './components/ErrorList'
import Settings from './components/Settings'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
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

import { useState, useEffect } from 'react'
import { useNavigate, useParams, useOutletContext } from 'react-router-dom'
import { api } from '../api'

export default function LibraryForm() {
  const { setPageTitle } = useOutletContext()
  const { name } = useParams()
  const navigate = useNavigate()
  const isEdit = !!name
  useEffect(() => setPageTitle(isEdit ? 'Edit: ' + name : 'New Library'), [name, isEdit, setPageTitle])

  const [form, setForm] = useState({
    name: '', encoder: 'nvidia', target_bitrate: '', max_bitrate: '',
    minimum_savings_percent: 10, keep_audio_langs: 'eng,en,jpn,ja,hin,hi',
    keep_subtitle_langs: 'eng,en,jpn,ja',
  })
  const [paths, setPaths] = useState([])
  const [newPath, setNewPath] = useState('')
  const [saving, setSaving] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!isEdit) { setLoaded(true); return }
    api('GET', '/api/libraries/' + encodeURIComponent(name)).then(data => {
      const p = data.profile || {}
      setForm({
        name: name,
        encoder: p.encoder || 'nvidia',
        target_bitrate: p.target_bitrate || '',
        max_bitrate: p.max_bitrate || '',
        minimum_savings_percent: p.minimum_savings_percent || 10,
        keep_audio_langs: (p.keep_audio_langs || []).join(',') || 'eng,en,jpn,ja,hin,hi',
        keep_subtitle_langs: (p.keep_subtitle_langs || []).join(',') || 'eng,en,jpn,ja',
      })
      setPaths((data.paths || []).map(p => ({ path: p, valid: true })))
      setLoaded(true)
    }).catch(err => { setError(err.message); setLoaded(true) })
  }, [name, navigate])

  const set = (key) => (e) => setForm(f => ({ ...f, [key]: e.target.value }))
  const addPath = async () => {
    const p = newPath.trim()
    if (!p) return
    try {
      const res = await api('GET', '/api/validate-path?path=' + encodeURIComponent(p))
      setPaths(prev => [...prev, { path: p, valid: res.valid && res.is_dir }])
      setNewPath('')
    } catch (err) {
      setError(err.message)
    }
  }

  const removePath = (i) => setPaths(prev => prev.filter((_, idx) => idx !== i))

  const submit = async (e) => {
    e.preventDefault()
    if (!form.name.trim()) return
    if (!paths.length) { alert('Add at least one media folder path.'); return }
    const invalid = paths.filter(p => !p.valid)
    if (invalid.length) { alert('Remove invalid paths:\n' + invalid.map(p => '  ' + p.path).join('\n')); return }

    setSaving(true)
    setError('')
    const body = {
      name: form.name.trim(),
      encoder: form.encoder,
      target_bitrate: parseInt(form.target_bitrate) || undefined,
      max_bitrate: parseInt(form.max_bitrate) || undefined,
      minimum_savings_percent: parseInt(form.minimum_savings_percent) || 0,
      keep_audio_langs: form.keep_audio_langs.split(',').map(s => s.trim()).filter(Boolean),
      keep_subtitle_langs: form.keep_subtitle_langs.split(',').map(s => s.trim()).filter(Boolean),
      paths: paths.map(p => p.path),
    }
    try {
      if (isEdit) {
        await api('PUT', '/api/libraries/' + encodeURIComponent(name), body)
      } else {
        await api('POST', '/api/libraries', body)
      }
      const savedName = body.name || name
      navigate('/library-detail/' + encodeURIComponent(savedName))
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (!loaded) return <div className="loading-overlay" style={{ position: 'relative', height: 200 }}><div className="spinner"></div></div>

  return (
    <div className="card">
      <h3>{isEdit ? 'Edit Library: ' + name : 'New Library'}</h3>
      {error && <div className="error-message">{error}</div>}
      <form onSubmit={submit}>
        <div className="form-row">
          <div className="field">
            <label>Library Name</label>
            <input type="text" value={form.name} onChange={set('name')} required />
          </div>
          <div className="field">
            <label>Encoder</label>
            <select value={form.encoder} onChange={set('encoder')}>
              <option value="nvidia">NVIDIA (NVENC)</option>
              <option value="intel">Intel (QSV)</option>
              <option value="vaapi">VAAPI</option>
              <option value="amdgpu">AMD (AMF)</option>
              <option value="cpu">CPU (libx264)</option>
            </select>
          </div>
        </div>
        <div className="form-row">
          <div className="field">
            <label>Target bitrate (kbps)</label>
            <input type="number" value={form.target_bitrate} onChange={set('target_bitrate')} placeholder="3000" />
          </div>
          <div className="field">
            <label>Max bitrate (kbps)</label>
            <input type="number" value={form.max_bitrate} onChange={set('max_bitrate')} placeholder="4500" />
          </div>
          <div className="field">
            <label>Min savings %</label>
            <input type="number" value={form.minimum_savings_percent} onChange={set('minimum_savings_percent')} min="0" />
          </div>
        </div>
        <div className="form-row">
          <div className="field">
            <label>Keep audio languages (comma-sep)</label>
            <input type="text" value={form.keep_audio_langs} onChange={set('keep_audio_langs')} />
          </div>
          <div className="field">
            <label>Keep subtitle languages</label>
            <input type="text" value={form.keep_subtitle_langs} onChange={set('keep_subtitle_langs')} />
          </div>
        </div>
        <div className="form-row">
          <div className="field" style={{ flex: 2 }}>
            <label>Media folders</label>
            <div className="path-list">
              {paths.map((p, i) => (
                <div className="path-item" key={i}>
                  <span className={p.valid ? 'check' : 'cross'}>{p.valid ? '\u2713' : '\u2717'}</span>
                  {p.path}
                  <span className="remove" onClick={() => removePath(i)}>&#10005;</span>
                </div>
              ))}
            </div>
            <div className="flex gap-8 mt-8">
              <input type="text" value={newPath} onChange={e => setNewPath(e.target.value)} placeholder="/path/to/media" style={{ flex: 1, fontSize: 13, padding: '7px 10px', border: '1px solid #444', borderRadius: 4, background: '#2a2a2a', color: '#e0e0e0', outline: 'none' }} />
              <button type="button" className="btn outline" onClick={addPath}>Add</button>
            </div>
          </div>
        </div>
        <div className="flex gap-8 mt-8">
          <button type="submit" className={`btn primary${saving ? ' loading' : ''}`} disabled={saving}>{isEdit ? 'Save Changes' : 'Create Library'}</button>
          <button type="button" className="btn outline" onClick={() => navigate('/')}>Cancel</button>
        </div>
      </form>
    </div>
  )
}

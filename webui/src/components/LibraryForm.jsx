import { useState, useEffect, useRef } from 'react'
import { useNavigate, useParams, useOutletContext } from 'react-router-dom'
import { api } from '../api'

const s = {
  section: { marginBottom: 28 },
  h3: { fontSize: 11, fontWeight: 600, color: '#666', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 14, paddingBottom: 6, borderBottom: '1px solid #2a2a2a' },
}

const Hint = ({ children }) => (
  <span style={{ display: 'block', fontSize: 11, color: '#555', lineHeight: 1.3, marginTop: 2 }}>{children}</span>
)

const encoderHints = {
  nvidia: 'NVIDIA GPU with NVENC — best performance on supported hardware',
  intel: 'Intel Quick Sync Video — integrated GPU encoder',
  vaapi: 'VA-API — AMD/Intel open-source driver',
  amdgpu: 'AMD AMF — experimental, Linux support limited',
  cpu: 'libx264 — software encode, highest quality, slower',
}

const normLangs = (s) =>
  (s || '').split(',').map(x => x.trim().toLowerCase()).filter(Boolean).sort().join(',')

export default function LibraryForm() {
  const { setPageTitle } = useOutletContext()
  const { name } = useParams()
  const navigate = useNavigate()
  const isEdit = !!name
  useEffect(() => setPageTitle(isEdit ? 'Edit: ' + name : 'New Library'), [name, isEdit, setPageTitle])

  const [form, setForm] = useState({
    name: '', encoder: 'nvidia', target_bitrate: '', max_bitrate: '',
    minimum_savings_percent: 10, workers: 1, ignore_dirs: '', ignore_paths: '',
    keep_audio_langs: '',
    keep_subtitle_langs: '',
  })
  const [paths, setPaths] = useState([])
  const [newPath, setNewPath] = useState('')
  const [pathStatus, setPathStatus] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const pathTimer = useRef(null)
  const baselineBr = useRef(null)

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
        workers: p.workers || 1,
        ignore_dirs: (p.ignore_dirs || []).join('\n'),
        ignore_paths: (p.ignore_paths || []).join('\n'),
        keep_audio_langs: (p.keep_audio_langs || []).join(','),
        keep_subtitle_langs: (p.keep_subtitle_langs || []).join(','),
      })
      setPaths((data.paths || []).map(p => ({ path: p, valid: true })))
      baselineBr.current = {
        target: parseInt(p.target_bitrate) || 3000,
        max: parseInt(p.max_bitrate) || 3300,
        encoder: (p.encoder || 'nvidia').trim().toLowerCase(),
        audio: normLangs((p.keep_audio_langs || []).join(',')),
        subtitles: normLangs((p.keep_subtitle_langs || []).join(',')),
        savings: parseInt(p.minimum_savings_percent) || 10,
      }
      setLoaded(true)
    }).catch(err => { setError(err.message); setLoaded(true) })
  }, [name, navigate])

  const set = (key) => (e) => setForm(f => ({ ...f, [key]: e.target.value }))

  const onPathChange = (e) => {
    const val = e.target.value
    setNewPath(val)
    if (pathTimer.current) clearTimeout(pathTimer.current)
    if (!val.trim()) { setPathStatus(null); return }
    setPathStatus('checking')
    pathTimer.current = setTimeout(async () => {
      try {
        const res = await api('GET', '/api/validate-path?path=' + encodeURIComponent(val.trim()))
        setPathStatus(res.valid && res.is_dir ? 'valid' : 'invalid')
      } catch { setPathStatus(null) }
    }, 400)
  }

  const addPath = async () => {
    const p = newPath.trim()
    if (!p) return
    try {
      const res = await api('GET', '/api/validate-path?path=' + encodeURIComponent(p))
      setPaths(prev => [...prev, { path: p, valid: res.valid && res.is_dir }])
      setNewPath('')
      setPathStatus(null)
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
    const parseList = (str) => (str || '').split(/[\n,]/).map(x => x.trim()).filter(Boolean)
    const body = {
      name: form.name.trim(),
      encoder: form.encoder,
      target_bitrate: parseInt(form.target_bitrate) || undefined,
      max_bitrate: parseInt(form.max_bitrate) || undefined,
      minimum_savings_percent: parseInt(form.minimum_savings_percent) || 0,
      workers: parseInt(form.workers) || 1,
      ignore_dirs: parseList(form.ignore_dirs),
      ignore_paths: parseList(form.ignore_paths),
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
      setSaved(true)
      setTimeout(() => {
        const savedName = body.name || name
        navigate('/library-detail/' + encodeURIComponent(savedName))
      }, 600)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (!loaded) return <div className="loading-overlay" style={{ position: 'relative', height: 200 }}><div className="spinner"></div></div>

  const encLabel = form.encoder === 'nvidia' ? 'NVIDIA NVENC'
    : form.encoder === 'intel' ? 'Intel QSV'
    : form.encoder === 'vaapi' ? 'VA-API'
    : form.encoder === 'amdgpu' ? 'AMD AMF'
    : 'libx264'

  const targetBr = form.target_bitrate || 3000
  const maxBr = form.max_bitrate || 3300

  const base = baselineBr.current || {
    target: 3000,
    max: 3300,
    encoder: 'nvidia',
    audio: '',
    subtitles: '',
    savings: 10,
  }
  const cacheInvalidated =
    parseInt(targetBr) !== base.target ||
    parseInt(maxBr) !== base.max ||
    form.encoder.trim().toLowerCase() !== base.encoder ||
    normLangs(form.keep_audio_langs) !== base.audio ||
    normLangs(form.keep_subtitle_langs) !== base.subtitles ||
    (parseInt(form.minimum_savings_percent) || 10) !== base.savings

  return (
    <form onSubmit={submit} className="row2">
      <div className="col-main">
        <button className="link-btn" style={{ marginBottom: 20 }} onClick={() => navigate(isEdit ? '/library-detail/' + encodeURIComponent(name) : '/')}>&#8592; Back</button>
        {error && <div className="error-message">{error}</div>}
        {saved && <div className="error-message" style={{ borderColor: '#1a3a1a', background: '#1a3a1a', color: '#33ff33' }}>Saved! Redirecting...</div>}

        <div style={s.section}>
          <h3 style={s.h3}>General</h3>
          <div className="form-row">
            <div className="field">
              <label>Library Name <span className="req">*</span></label>
              <input type="text" value={form.name} onChange={set('name')} required />
              <Hint>Visible in the library list and used for library scans</Hint>
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
              <Hint>{encoderHints[form.encoder]}</Hint>
            </div>
          </div>
        </div>

        <div style={s.section}>
          <h3 style={s.h3}>Conversion Settings</h3>
          <div className="form-row">
            <div className="field">
              <label>Target bitrate (kbps)</label>
              <input type="number" value={form.target_bitrate} onChange={set('target_bitrate')} placeholder="3000" />
              <Hint>Re-encode to this bitrate. Default: 3000 kbps</Hint>
            </div>
            <div className="field">
              <label>Max bitrate (kbps)</label>
              <input type="number" value={form.max_bitrate} onChange={set('max_bitrate')} placeholder="3300" />
              <Hint>Only convert files above this bitrate. Default: 3300 kbps</Hint>
            </div>
            <div className="field">
              <label>Min savings %</label>
              <input type="number" value={form.minimum_savings_percent} onChange={set('minimum_savings_percent')} min="0" placeholder="10" />
              <Hint>Skip conversion if savings are below this. Default: 10%</Hint>
            </div>
            <div className="field">
              <label>Workers</label>
              <input type="number" value={form.workers} onChange={set('workers')} min="1" placeholder="1" />
              <Hint>Files to convert in parallel. Default: 1 (sequential)</Hint>
            </div>
          </div>
        </div>

        <div style={s.section}>
          <h3 style={s.h3}>Scan Filters</h3>
          <div className="form-row">
            <div className="field">
              <label>Ignore directories</label>
              <textarea value={form.ignore_dirs} onChange={set('ignore_dirs')} rows="3" placeholder={'sample\nextras'} />
              <Hint>Skip any folder with this exact name, anywhere in the tree (e.g. sample, extras). One per line.</Hint>
            </div>
            <div className="field">
              <label>Ignore paths</label>
              <textarea value={form.ignore_paths} onChange={set('ignore_paths')} rows="3" placeholder={'/media/staging\n00__folders'} />
              <Hint>Skip any file or folder whose full path contains this text (e.g. /media/staging). One per line.</Hint>
            </div>
          </div>
        </div>

        <div style={s.section}>
          <h3 style={s.h3}>Language Filters</h3>
          <div className="form-row">
            <div className="field">
              <label>Keep audio languages</label>
              <input type="text" value={form.keep_audio_langs} onChange={set('keep_audio_langs')} placeholder="eng,en,jpn,ja" />
              <Hint>Comma-separated codes, e.g. eng,en,jpn,ja. Leave empty to keep all audio.</Hint>
            </div>
            <div className="field">
              <label>Keep subtitle languages</label>
              <input type="text" value={form.keep_subtitle_langs} onChange={set('keep_subtitle_langs')} placeholder="eng,en,jpn,ja" />
              <Hint>Comma-separated codes, e.g. eng,en,jpn,ja. Leave empty to keep all subtitles.</Hint>
            </div>
          </div>
        </div>

        <div style={s.section}>
          <h3 style={s.h3}>Media Paths <span className="req">*</span></h3>
          <div className="form-row">
            <div className="field" style={{ flex: 2 }}>
              <div className="path-list" style={{ marginBottom: 8 }}>
                {paths.map((p, i) => (
                  <div className="path-item" key={i}>
                    <span className={p.valid ? 'check' : 'cross'}>{p.valid ? '\u2713' : '\u2717'}</span>
                    {p.path}
                    <span className="remove" onClick={() => removePath(i)}>&#10005;</span>
                  </div>
                ))}
              </div>
              <div className="flex gap-8" style={{ alignItems: 'center' }}>
                <input type="text" value={newPath} onChange={onPathChange} placeholder="/path/to/media" style={{ flex: 1 }} />
                {pathStatus === 'checking' && <span className="text-muted" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>checking...</span>}
                {pathStatus === 'valid' && <span style={{ color: '#33ff33', fontSize: 12, whiteSpace: 'nowrap' }}>&#10003; exists</span>}
                {pathStatus === 'invalid' && <span style={{ color: '#e05050', fontSize: 12, whiteSpace: 'nowrap' }}>&#10007; not found</span>}
                <button type="button" className="btn outline" onClick={addPath}>Add</button>
              </div>
            </div>
          </div>
        </div>

        <div style={{ marginBottom: 28, display: 'flex', alignItems: 'center', gap: 12 }}>
          <button type="submit" className={`btn primary${saving ? ' loading' : ''}`} disabled={saving || saved}>
            {isEdit ? 'Save Changes' : 'Create Library'}
          </button>
          {saved && <span style={{ color: '#33ff33', fontSize: 12 }}>Saved</span>}
          <button type="button" className="btn outline" onClick={() => navigate('/')}>Cancel</button>
        </div>
      </div>

      <div className="col-side">
        <div style={s.section}>
          <h3 style={s.h3}>Summary</h3>
          <div className="detail-row">
            <span className="label">Encoder</span>
            <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>{encLabel}</span>
          </div>
          <div className="detail-row">
            <span className="label">Target</span>
            <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>{targetBr} kbps</span>
          </div>
          <div className="detail-row">
            <span className="label">Max before convert</span>
            <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>{maxBr} kbps</span>
          </div>
          <div className="detail-row">
            <span className="label">Min savings</span>
            <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>{form.minimum_savings_percent}%</span>
          </div>
          <div className="detail-row">
            <span className="label">Workers</span>
            <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>{form.workers || 1}</span>
          </div>
          <div className="detail-row">
            <span className="label">Ignored dirs</span>
            <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>{(form.ignore_dirs.split(/[\n,]/).map(x => x.trim()).filter(Boolean)).length}</span>
          </div>
          <div className="detail-row">
            <span className="label">Ignored paths</span>
            <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>{(form.ignore_paths.split(/[\n,]/).map(x => x.trim()).filter(Boolean)).length}</span>
          </div>
          <div className="detail-row">
            <span className="label">Media folders</span>
            <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>{paths.length}</span>
          </div>
          <div className="detail-row">
            <span className="label">Acceleration</span>
            <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>{form.encoder !== 'cpu' ? 'Hardware' : 'Software'}</span>
          </div>
        </div>
        {cacheInvalidated && (
          <div className="info-message" style={{ marginTop: 12 }}>
            Changing conversion settings (target/max bitrate, encoder, audio/subtitle languages, or
            min savings) invalidates the probe cache. The next scan of this library will re-probe
            every file from scratch.
          </div>
        )}
      </div>
    </form>
  )
}

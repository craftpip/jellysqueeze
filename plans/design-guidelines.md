# Design Guidelines

How to build pages that look exactly like the web UI.

## Choose Your Template

| Template | Used by |
|---|---|
| **Settings-style form** | Settings, New/Edit Library |
| **Dashboard-style** | Dashboard |
| **Table page** | Run History |
| **Detail page** | Library Detail |
| **Run detail** | Run Detail |

## Settings-Style Form Template

This is the form pattern used by Settings.jsx and LibraryForm.jsx.

### Page Shell

```jsx
import { useState, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api } from '../api'

const s = {
  section: { marginBottom: 28 },
  h3: { fontSize: 11, fontWeight: 600, color: '#666', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 14, paddingBottom: 6, borderBottom: '1px solid #2a2a2a' },
}

const Hint = ({ children }) => (
  <span style={{ display: 'block', fontSize: 11, color: '#555', lineHeight: 1.3, marginTop: 2 }}>{children}</span>
)

export default function MyPage() {
  const { setPageTitle } = useOutletContext()
  useEffect(() => setPageTitle('My Page Title'), [setPageTitle])

  const [form, setForm] = useState({ field1: '', field2: '' })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  const set = (key) => (e) => {
    const val = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm(f => ({ ...f, [key]: val }))
  }

  const submit = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    const body = {}
    Object.entries(form).forEach(([k, v]) => {
      if (typeof v === 'boolean') { body[k] = v ? '1' : '0'; return }
      if (v !== '' && v !== null && v !== undefined) body[k] = v
    })
    try {
      await api('POST', '/api/my-endpoint', body)
      setSaving(false)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (err) {
      setError(err.message)
      setSaving(false)
    }
  }

  // Load initial data
  useEffect(() => {
    api('GET', '/api/my-endpoint').then(data => {
      setForm({ field1: data.field1 ?? '' })
    }).catch(err => setError(err.message))
  }, [])

  return (
    <form onSubmit={submit} style={{ display: 'flex', gap: 28, alignItems: 'flex-start' }}>
      <div style={{ flex: 3, minWidth: 0 }}>
        {error && <div className="error-message">{error}</div>}

        <div style={s.section}>
          <h3 style={s.h3}>Section Name</h3>
          <div className="form-row">
            <div className="field">
              <label>Field label</label>
              <input type="text" value={form.field1} onChange={set('field1')} placeholder="optional placeholder" />
              <Hint>Help text for this field</Hint>
            </div>
            <div className="field">
              <label>Another field</label>
              <input type="text" value={form.field2} onChange={set('field2')} />
            </div>
          </div>
        </div>

        <div style={{ marginBottom: 28, display: 'flex', alignItems: 'center', gap: 12 }}>
          <button type="submit" className={`btn primary${saving ? ' loading' : ''}`} disabled={saving}>
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
          {saved && <span style={{ color: '#33ff33', fontSize: 12 }}>Saved</span>}
        </div>
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={s.section}>
          <h3 style={s.h3}>Sidebar</h3>
          <div className="detail-row">
            <span className="label">Key</span>
            <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>value</span>
          </div>
        </div>
      </div>
    </form>
  )
}
```

### Section Anatomy (in exact order)

```
section div (marginBottom: 28)
  └── h3 (uppercase, #666, bottom border 1px solid #2a2a2a)
       └── (optional) link-btn toggle inline
  └── .form-row (flex, gap: 12, flex-wrap, margin-bottom: 12)
       └── .field (flex: 1, flex-column, min-width: 150px, gap: 3px)
            ├── label (12px, #999, font-weight: 500)
            ├── input or select (13px, 7px 10px padding, #2a2a2a bg, #444 border, #e0e0e0 text)
            └── <Hint>...</Hint> (block, 11px, #555, margin-top: 2)
```

### Field Variants

**Text input:**
```jsx
<div className="field">
  <label>Buffer size (kbps)</label>
  <input type="text" value={form.BUFSIZE} onChange={set('BUFSIZE')} placeholder="6600" />
  <Hint>FFmpeg rate-control buffer</Hint>
</div>
```

**Number input:**
```jsx
<div className="field">
  <label>Target bitrate (kbps)</label>
  <input type="number" value={form.target_bitrate} onChange={set('target_bitrate')} placeholder="3000" />
  <Hint>Re-encode to this bitrate. Default: 3000 kbps</Hint>
</div>
```

**Select:**
```jsx
<div className="field">
  <label>Encoder</label>
  <select value={form.encoder} onChange={set('encoder')}>
    <option value="nvidia">NVIDIA (NVENC)</option>
    <option value="cpu">CPU (libx264)</option>
  </select>
  <Hint>NVIDIA GPU with NVENC</Hint>
</div>
```

**Checkbox (uses `.field.checkbox` — note: reverse direction row):**
```jsx
<div className="field checkbox">
  <input type="checkbox" checked={form.CLEANUP_TMP} onChange={set('CLEANUP_TMP')} id="ck-cleanup" />
  <label htmlFor="ck-cleanup">Clean temp files before scan</label>
  <Hint>Remove leftover .__transcoding__ files on start</Hint>
</div>
```

**Password:**
```jsx
<input type="password" value={form.JELLYFIN_API_KEY} onChange={set('JELLYFIN_API_KEY')} placeholder="(hidden, enter to change)" />
```

**Action button inline with result** (e.g. Test Connection):
```jsx
<div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
  <button type="button" className="btn outline" onClick={testConnection} disabled={testing}>
    {testing ? 'Testing...' : 'Test Connection'}
  </button>
  {testResult && (
    <span style={{ fontSize: 12, color: testResult.ok ? '#33ff33' : '#e05050' }}>
      {testResult.ok ? '✓ ' : '✗ '}{testResult.message}
    </span>
  )}
</div>
```

**Path list with add/remove:**
```jsx
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
```

**Section with collapsible toggle** (Advanced):
```jsx
<div style={s.section}>
  <h3 style={{ ...s.h3, display: 'flex', alignItems: 'center', gap: 12 }}>
    Section Name
    <button type="button" className="link-btn" onClick={() => setShow(v => !v)}>
      {show ? 'Hide' : 'Show'}
    </button>
  </h3>
  {show && (
    <>{/* fields */}</>
  )}
</div>
```

**Success message (not error)** — green-tinted instead of red:
```jsx
{saved && <div className="error-message" style={{ borderColor: '#1a3a1a', background: '#1a3a1a', color: '#33ff33' }}>Saved! Redirecting...</div>}
```

**Back button** before form fields:
```jsx
<button className="link-btn" style={{ marginBottom: 20 }} onClick={() => navigate('/')}>&#8592; Back</button>
```

**Cancel button** next to Save:
```jsx
<button type="button" className="btn outline" onClick={() => navigate('/')}>Cancel</button>
```

**Sidebar** uses `.detail-row` with optional monospace values:
```jsx
<div className="detail-row">
  <span className="label">Label</span>
  <span className="value" style={{ fontFamily: 'monospace', fontSize: 12 }}>{value}</span>
</div>
```

## Dashboard Template

### Page Structure

```
.stats-grid (flex, gap: 32px, padding: 8px 0 20px)
  └── .stat-block (flex-column, gap: 1)
       ├── .num (24px, 700, #e0e0e0)
       └── .lbl (11px, uppercase, #666)

.error-message (optional, only when error)

.dash-header (flex, align-center, mb: 8)
  ├── h2 (15px, 600, #e0e0e0, flex: 1, margin: 0)
  └── .dash-actions (flex, gap: 16px, align-center)
       ├── .link-btn (e.g. "+ New Library")
       └── .link-btn.primary (e.g. "Run All")

.libs-table or regular table
```

### Loading State

For initial data fetch — inline spinner, not full overlay:
```jsx
if (loading) return <div className="loading-overlay" style={{ position: 'relative', height: 200 }}><div className="spinner"></div></div>
```

For non-initial — use existing elements with loading text:
```jsx
<div className="text-muted">Loading...</div>
```

### Data Fetching Pattern

Always use the `mounted` flag + cleanup:
```jsx
useEffect(() => {
  let mounted = true
  async function load() {
    try {
      const data = await api('GET', '/api/endpoint')
      if (!mounted) return
      setData(data)
    } catch (err) {
      if (mounted) setError(err.message)
    }
  }
  load()
  const id = setInterval(load, 5000)
  return () => { mounted = false; clearInterval(id) }
}, [])
```

### Row Click Pattern (Dashboard libs-table rows)

Rows are clickable with `onClick` on `<tr>`. The Convert button uses `e.stopPropagation()` to prevent row click:
```jsx
<tr key={lib.name} className={'clickable' + (isRunning ? ' row-running' : '')} onClick={() => openLibrary(lib.name)}>
  <td><span className="lib-name">{lib.name}</span></td>
  <td>{/* status/last-run */}</td>
  <td className="cell-actions">
    <button className="link-btn primary" onClick={e => runLib(e, lib.name)} disabled={isRunning}>Convert</button>
  </td>
</tr>
```

### Running State in Table

```
.status-running (#4c9aff, 12px, inline-flex, gap: 5px)
  └── .pulse-dot (6px circle, #4c9aff, pulse animation)
  └── "Running"
  └── .progress-frac (#666) "  done/total"
  └── .live-link (12px, underline, #4c9aff)

.status-idle (#555, 12px) — for "5m ago" or "-"
```

## Table Page Template

Used by Run History.

```jsx
<div className="dash-header">
  <h2>Page Title</h2>
</div>
{error && <div className="error-message">{error}</div>}
{!data.length ? (
  <div className="empty">No items yet.</div>
) : (
  <table className="libs-table">
    <thead><tr><th>Column</th><th></th></tr></thead>
    <tbody>
      {data.map(r => (
        <tr key={r.id} className={r.running ? 'row-running' : ''}>
          <td><span className="mono">{value}</span></td>
          <td className="cell-actions">
            <button className="btn outline sm" onClick={action}>View</button>
          </td>
        </tr>
      ))}
    </tbody>
  </table>
)}
```

## Detail Page Template

Used by Library Detail.

```jsx
<button className="link-btn mb-8" onClick={() => navigate('/')}>&#8592; Back</button>
<div className="dash-header">
  <h2>{title}</h2>
  <div className="dash-actions">
    <button className="btn primary sm" onClick={action}>&#9654; Run Now</button>
    <button className="btn outline sm" onClick={action}>Edit</button>
    <button className="btn danger sm" onClick={action}>Delete</button>
  </div>
</div>
{error && <div className="error-message">{error}</div>}

<div className="card">
  <div className="detail-row"><span className="label">Key</span><span className="value">value</span></div>
  <div className="detail-row"><span className="label">Key</span><span className="value">value</span></div>
</div>

<div className="card">
  <h3>Section Title</h3>
  {!data.length ? (
    <div className="empty">No items yet.</div>
  ) : (
    <table className="libs-table">...</table>
  )}
</div>
```

## Run Detail Template

Two-column layout with live progress, terminal, and processed files table. See RunDetail.jsx for full implementation.

```
.link-btn.mb-8 (Back)
.dash-header
  ├── h2 + optional .status-running with .pulse-dot + LIVE label
  └── .dash-actions (Log, Stop buttons)

.error-message (optional)

.run-detail-grid (display: flex, gap: 16, align-items: flex-start)
  ├── .run-detail-left (flex: 1, min-width: 0)
  │   └── #section-info (.detail-rows container)
  │       └── .detail-row entries
  │
  └── .run-detail-right (flex: 1, min-width: 0)
      ├── #section-run-progress (only when running + total > 0)
      ├── #section-encoding-progress (only when running + active files)
      ├── #section-run-status (only when running + no active files)
      └── #section-directory-progress (only when running + multiple folders)

#section-processed-files (always when results exist)
  ├── filter toggle buttons (.btn.outline.sm + .active)
  ├── .libs-table (Status, File, Result, Saved)
  └── empty row "No matching files."

#section-terminal (.run-terminal, height: 300, margin-bottom: 20)
```

## Common Snippets

### Page Title

Every page must set its title via `useOutletContext`:
```jsx
const { setPageTitle } = useOutletContext()
useEffect(() => setPageTitle('Page Name'), [setPageTitle])
```

### Loading Overlay (inline for initial load)
```jsx
if (loading) return <div className="loading-overlay" style={{ position: 'relative', height: 200 }}><div className="spinner"></div></div>
```

### Error
```jsx
{error && <div className="error-message">{error}</div>}
```

### Empty State
```jsx
{!items.length ? (
  <div className="empty">No items yet. <a href="#" onClick={e => { e.preventDefault(); navigate('/create') }}>Create one</a>.</div>
) : ( ... )}
```

### Delete Confirmation
```jsx
const deleteItem = async () => {
  if (!confirm('Delete "' + name + '"?')) return
  await api('DELETE', '/api/item/' + name)
  navigate('/')
}
```

### Unicode Icons (no icon library)
| Character | Usage |
|---|---|
| `&#8592;` | ← Back |
| `&#9654;` | ▶ Run / Play |
| `&#9632;` | ■ Stop |
| `&#8615;` | ↧ Download |
| `&#10003;` / `&#10005;` | ✓ valid / ✗ invalid |
| `&#10007;` | ✗ not found |

### Status Tags
| Status | Class | Text |
|---|---|---|
| OK | `tag ok` | `OK` |
| Skipped | `tag skip` | `SKIP` |
| Failed | `tag fail` | `FAIL` |
| Running | `tag running` | `Running` |
| Active | `tag active` | `Encoding` |
| Pending | `tag pending` | `Pending` |
| Done | (no tag) | inline `"Done"` text |

### Action Button States
- `.btn.loading` + `disabled` + text changes to `"Saving..."` / `"Testing..."` etc
- `.btn.outline.active` = filter toggle engaged
- `disabled` = grayed out, `opacity: .5`
- `:disabled` on `.link-btn` = `opacity: .35`

## Styling Conventions

1. **No CSS framework.** 127 lines of hand-written CSS. No Tailwind, Bootstrap.
2. **No CSS-in-JS.** All styles in `styles.css`. Inline `style={}` only for one-off layout/flex/positioning — never for colors, typography, or reusable values.
3. **Dark theme always.** `#121212` background. No light mode.
4. **No rounded corners larger than 8px.** Cards are 8px, tags/buttons are 3-4px.
5. **Accent blue is `#4c9aff`** for interactive elements, focus states, active nav, primary buttons.
6. **Cards are flat** — no box-shadow, no elevation. Depth from color only.
7. **Uppercase labels** for stats (`lbl`), table headers (`th`), and section headings.
8. **No icons library.** Use Unicode characters (←, ↔, ■, ✓, ✗, ▲, ▼) or CSS-only indicators (pulse dot, spinner).
9. **No state management library.** React `useState`/`useEffect` only.
10. **No HTTP client library.** 30-line `fetch()` wrapper in `api.js`.
11. **Hover feedback** on rows (background change), buttons (lighter/darker), links (color change), nav items (background).
12. **Transition duration** is consistently `0.15s` or `.3s` (progress bars).

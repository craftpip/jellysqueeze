# Settings Page Redesign

## Goal

Turn the flat one-card Settings form into a professional, organized page that matches the Dashboard's clean card-based layout.

## Current State

A single `<div className="card">` with 5 fields in 2 rows. No grouping, no system info, no advanced section.

## Proposed Layout

Split into **4 cards**, matching the Dashboard's visual style:

```
┌─ Conversion ───────────────────────────────────────┐
│  [Target bitrate]  [Max bitrate]  [Buffer size]    │
│  [CRF]            [Encoder ▼]     [Workers]        │
└────────────────────────────────────────────────────┘

┌─ Jellyfin ─────────────────────────────────────────┐
│  [Jellyfin URL]  [API Key]  [Test Connection]      │
└────────────────────────────────────────────────────┘

┌─ Advanced ─────────────────────────────────────────┐
│  ▼ Show advanced options                            │
│  (collapsible, revealed on click)                   │
│  [FFMPEG path]  [FFPROBE path]                     │
│  [Exclude dirs]  [Ignore paths]                    │
│  ☐ Clean temp files  ☐ Keep originals  ☐ Dry run  │
└────────────────────────────────────────────────────┘

┌─ System Info ──────────────────────────────────────┐
│  ffmpeg path:     /usr/bin/ffmpeg                   │
│  ffprobe path:    /usr/bin/ffprobe                  │
│  ffmpeg version:  n6.0                               │
│  GPU:             NVIDIA (nvidia-smi OK)            │
│  Encoders:        h264_nvenc, hevc_nvenc, libx264  │
│  .env:            /app/.env                         │
│  config.yml:      /app/config.yml (loaded)          │
└────────────────────────────────────────────────────┘
```

## Card Details

### 1. Conversion card
- **TARGET_BR** — text, label "Target bitrate (kbps)"
- **MAX_BR** — text, label "Max bitrate (kbps)"
- **BUFSIZE** — text, label "Buffer size (kbps)"
- **DEFAULT_CRF** — text, label "CRF (CPU mode)"
- **Encoder** — `<select>` dropdown: auto/nvidia/intel/amd/cpu
- **Workers** — text, label "Workers (parallel files)", default 1

### 2. Jellyfin card
- **JELLYFIN_BASE_URL** — text, placeholder "http://jellyfin:8096"
- **JELLYFIN_API_KEY** — password, placeholder "(hidden, enter to change)"
- **Test Connection** — `<button className="btn outline">` that calls `POST /api/test-jellyfin` (new endpoint)
  - Shows green check or red X next to the button after response

### 3. Advanced card (collapsible)
- Toggle button: "Show advanced options" / "Hide advanced options" — uses a `useState` to toggle visibility
- **FFMPEG_BIN** — text, label "FFmpeg path override"
- **FFPROBE_BIN** — text, label "FFprobe path override"
- **Exclude dirs** — text, label "Exclude directories (comma-separated)"
- **Ignore paths** — text, label "Ignore paths (comma-separated)"
- Checkboxes (using existing `.field.checkbox` style):
  - `--cleanup-tmp` — "Clean temp files before scan"
  - `--keep-original` — "Keep original backup"
  - `--dry-run` — "Dry run (preview only)"

### 4. System Info card (read-only)
- Same as originally planned (see below for details)

## Backend Changes

### GET /api/env — add new keys
```
TARGET_BR, MAX_BR, BUFSIZE, DEFAULT_CRF,
JELLYFIN_BASE_URL,
FFMPEG_BIN, FFPROBE_BIN,
DEFAULT_ENCODER, DEFAULT_WORKERS,
DEFAULT_EXCLUDE, DEFAULT_IGNORE_PATH,
CLEANUP_TMP, BACKUP_ORIGINALS, DRY_RUN
```

### POST /api/env — accept new keys
Accept all of the above. Validate ints for BUFSIZE, WORKERS. Validate encoder against known profiles.

### POST /api/test-jellyfin (new)
```python
@app.post("/api/test-jellyfin")
def api_test_jellyfin(body: dict):
    url = body.get("url") or os.getenv("JELLYFIN_BASE_URL", "")
    key = body.get("key") or os.getenv("JELLYFIN_API_KEY", "")
    try:
        client = JellyfinClient(url, key)
        client.get_playlist_libraries()  # or any simple API call
        return {"ok": True, "message": "Connected successfully"}
    except Exception as e:
        return {"ok": False, "message": str(e)}
```

### GET /api/system-info (new)
As previously planned.

## Styling

No new CSS — use existing classes:
- `.card` for each section
- `.form-row` / `.field` for form inputs
- `.field.checkbox` for toggles
- `.detail-row` style for system info key-value pairs
- `.btn`, `.btn.outline`, `.btn.primary` for buttons
- `.stats-grid` look for system info (or `.detail-row` pattern from RunDetail)

## Frontend Details

### Settings.jsx restructure
```jsx
function AdvancedSection() {
  const [show, setShow] = useState(false)
  return (
    <div className="card">
      <h3>Advanced <button className="link-btn" onClick={...}>
        {show ? 'Hide' : 'Show'} advanced options
      </button></h3>
      {show && (
        <>
          {/* ffmpeg paths, checkboxes */}
        </>
      )}
    </div>
  )
}
```

### Multiple useState groups
Keep all form state in one object, but render in separate cards. Single submit saves everything.

### System info uses detail-row pattern
```jsx
<div className="card">
  <h3>System Info</h3>
  {sysinfo && Object.entries(sysinfo).map(([k, v]) => (
    <div className="detail-row" key={k}>
      <span className="label">{formatLabel(k)}</span>
      <span className="value">{v}</span>
    </div>
  ))}
</div>
```

## User preferences saved

- Split settings into 4 cards: Conversion, Jellyfin, Advanced (collapsible), System Info
- Add BUFSIZE, default encoder, workers to Conversion card
- Add test connection button to Jellyfin card
- Add collapsible Advanced section with ffmpeg paths, exclude patterns, checkboxes for cleanup/keep-original/dry-run
- Add read-only System Info card
- Backend: expand GET/POST /api/env, add POST /api/test-jellyfin, add GET /api/system-info
- Match Dashboard visual style — same existing CSS classes, no new framework

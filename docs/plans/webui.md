# Web UI Plan

## Objective

Replace manual config.yml editing with a full web panel to manage libraries, run conversions, and track history. No auth, no login, no register.

## Pages / Views

### 1. Dashboard

Shows every library from config.yml as a card or row with:

| Field | What it shows |
|---|---|
| Library name | From config |
| Folders (paths) | All paths for that library, validated (green check / red x) |
| Encoder | nvidia / intel / amdgpu / cpu / vaapi |
| Target bitrate | e.g. 3000k |
| Last run | Timestamp of most recent run, or "Never" |
| Status | Running / Stopped / Never run |
| Total saved | Data saved across all runs |
| Actions | Edit / Delete / Run now |

Each row has a **Run now** button that triggers conversion with that library's settings.

### 2. Library Form (create / edit)

Single form page with all fields:

**Paths**
- Text input for directory path + Add button (or comma-separated)
- Each path validated on entry:
  - Must exist on disk (check via API)
  - Green check if valid, red x if not found
  - Can add multiple paths per library

**Settings**
- Encoder (dropdown): nvidia / intel / amdgpu / cpu / vaapi
- Target bitrate (number, kbps)
- Max bitrate (number, kbps)
- CRF (number, 0-51)
- Minimum savings % (number)
- Keep audio languages (text, comma-separated)
- Keep subtitle languages (text, comma-separated)
- Workers (number, default 1)
- Exclude dirs (text, comma-separated)
- Keep original (checkbox)
- Dry run (checkbox)
- Verbose (checkbox)

**Submit**
- Creates or updates the library entry in config.yml
- If new, appends to the libraries list
- If edit, replaces the existing entry
- Writes config.yml via API

### 3. Library Detail / Run History

Clicking a library opens a detail view showing:

- **Library config** (read-only summary of current settings)
- **Run history** — table of all runs for that library:

  | Run ID | Date/time | Files changed | Data saved | Status |
  |---|---|---|---|---|
  | e7a3f2 | 2026-07-28 14:32 | 12 | 2.4 GB | Completed |
  | b1c9d0 | 2026-07-27 09:15 | 3 | 640 MB | Completed |
  | f4a2e8 | 2026-07-26 18:00 | — | — | Failed |

  Sorted newest first. Each run expands or links to a detailed log view.

- **Per-run detail** (expandable):
  - Full terminal output from that run
  - List of files converted
  - Before/after sizes

### 4. Live Run View

When a run is kicked off (from dashboard or library detail):

- Terminal panel with real-time output (WebSocket, reuse existing)
- Status bar with elapsed time
- Stop button
- On completion, refresh the dashboard stats

## API Endpoints needed

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/libraries` | List all libraries with run history summary |
| `GET` | `/api/libraries/{name}` | Single library with full run history |
| `POST` | `/api/libraries` | Create a new library (writes config.yml) |
| `PUT` | `/api/libraries/{name}` | Update an existing library |
| `DELETE` | `/api/libraries/{name}` | Remove a library from config |
| `GET` | `/api/validate-path` | Check if a path exists on disk (query param: `path`) |
| `GET` | `/api/runs` | List all runs ever, or filter by library |
| `GET` | `/api/runs/{run_id}` | Full detail of one run (files, sizes, output log) |
| `GET` | `/api/stats` | Aggregate stats (total saved, total files, by library) |
| `POST` | `/api/run` | Start a conversion run (existing) |
| `POST` | `/api/stop/{run_id}` | Stop a run (existing) |
| `GET` | `/api/status/{run_id}` | Poll run status (existing) |
| `WS` | `/api/ws/{run_id}` | Live output (existing) |
| `GET` | `/api/config` | Existing config endpoint |
| `GET` | `/api/env` | Existing env endpoint |

## Run history data

Run history needs to be stored somewhere persistent, not just in memory.
Options:

1. **Append to a JSON log file** per run in `var/runs/` — simple, no DB
   - `var/runs/{run_id}.json` — metadata + file list + sizes
   - `var/runs/{run_id}.log` — full terminal output
2. **SQLite** — proper queries, aggregation
   - `var/runs.db` with tables: `runs`, `run_files`, `run_logs`

Start with JSON files. Migrate to SQLite if needed.

Each run record:

```json
{
  "run_id": "e7a3f2...",
  "library": "Shows",
  "mode": "library",
  "started_at": "2026-07-28T14:32:00",
  "ended_at": "2026-07-28T16:45:00",
  "exit_code": 0,
  "files_total": 12,
  "files_ok": 10,
  "files_skip": 1,
  "files_fail": 1,
  "bytes_before": 5000000000,
  "bytes_after": 2600000000,
  "bytes_saved": 2400000000,
  "command": "python src/convert.py --library Shows --use nvidia"
}
```

## Frontend tech

Keep it simple. No framework — plain HTML + CSS + JS served from FastAPI (same as current index.html). Dark theme consistent with current design.

## Implementation order

1. Run history logging (JSON files in `var/runs/`) — hooks into `convert_if_needed` results
2. New API endpoints (libraries CRUD, run history, path validation)
3. Dashboard page (list libraries with stats)
4. Library form (create + edit, path validation)
5. Library detail + run history view
6. Live run trigger from dashboard

## Files

- `src/webui/` — existing backend
  - `main.py` — add new routes
  - `runner.py` — extend to write run history
  - `templates/index.html` — replace with new frontend
- `var/runs/` — run history as JSON files (auto-created)

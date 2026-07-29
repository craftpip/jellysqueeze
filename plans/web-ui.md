# Web UI Plan

## Overview

A web panel that wraps `convert.py` — reads `config.yml`, lets the user pick a profile (or all), tweak CLI params, and run the conversion in one of 5 modes, streaming live terminal output to the browser.

## Tech Stack

- **FastAPI** + **Starlette** — async, WebSocket built-in
- **Single HTML page** with vanilla JS + CSS — no build step, no npm
- **WebSocket** for real-time terminal output streaming
- **asyncio subprocess** to run `convert.py` and capture stdout/stderr live
- Dependencies: `fastapi`, `uvicorn[standard]`, `websockets` added to `requirements.txt`

## Status

| Area | Status |
|---|---|
| Config sections (webui/mcp in config.yml) | Done |
| setup.py prompts | Done |
| convert.py server launch helpers | Done |
| webui/__init__.py | Done |
| webui/runner.py (async subprocess mgr) | Done |
| webui/main.py (FastAPI app, routes, WS) | Done |
| webui/mcp.py (MCP REST endpoints) | Done |
| webui/templates/index.html (frontend) | Done |
| --webui-only / --mcp-only flags | Done |
| requirements.txt update | Done |
| Server start + API tests | Done |
| Browser UI interactive testing | Done (all features verified) |
| Real conversion run via web UI | Tested (dry-run, ffmpeg not found in test env) |

## Config sections

Two new optional sections in `config.yml`:

```yaml
webui:
  enabled: true
  host: "0.0.0.0"
  port: 8080

mcp:
  enabled: true
  host: "0.0.0.0"
  port: 9090
```

### `webui`

Controls the web panel server. When `enabled: false`, the web UI server won't start during `convert.py` CLI run.

### `mcp`

Controls the MCP (Model Context Protocol) endpoint server — REST endpoints that AI tools (like opencode) can use to interact with the conversion system:
- List profiles/libraries
- Start a conversion
- Check run status
- Get recent results

MCP endpoints live under `/mcp/` prefix on the MCP server port (separate from the web UI for security isolation).

## Modes (matching the CLI exactly)

The user picks one of these modes in the UI:

| Mode | What it does | CLI equivalent |
|---|---|---|
| **Direct path** | Scan a single directory | `python convert.py /path [flags]` |
| **All libraries** | Scan all libraries from config.yml | `python convert.py --all [flags]` |
| **Single library** | Scan one library from config.yml | `python convert.py --library Shows [flags]` |
| **Jellyfin recent** | Check recently added items | `python convert.py --jellyfin-recent --libraries Shows,Movies --since-hours 72 [flags]` |
| **Remote** | SCP download/convert/upload | `python convert.py --remote user@host:/path [flags]` |

## Pages / Routes

### `GET /` — Main panel

Single-page UI with:
- **Mode selector** (tabs): Direct, All Libraries, Single Library, Jellyfin Recent, Remote
- **Directory input** (shown only for Direct mode)
- **Profile selector** (shown for Direct mode) — dropdown populated from `config.yml` profiles. Selecting a profile pre-fills the flags (bitrate, encoder, etc.)
- **Library dropdown** (shown for Library / Jellyfin Recent modes) — populated from `config.yml` libraries
- **All flag controls** (see Flags section below)
- **Run / Stop buttons**
- **Terminal output panel** with status bar

### `GET /api/config` — Fetch config

Returns parsed `config.yml` as JSON.

### `GET /api/env` — Fetch env defaults

Returns current `.env` values as JSON (without secrets like API key).

### `POST /api/run` — Launch conversion

Accepts JSON with mode, profile, directory/library, flags. Returns `{"run_id": "uuid", "command": "..."}`.

### `WS /api/ws/{run_id}` — Live output stream

WebSocket pushes lines as they're produced:
```json
{"type": "stdout", "data": "Scanning: /mnt/media1t/downloads/movies", "ts": "..."}
{"type": "stderr", "data": "[1/42] Checking: Movie.mkv", "ts": "..."}
{"type": "exit", "code": 0}
```

### `POST /api/stop/{run_id}` — Kill running process

Sends SIGTERM, then SIGKILL after 5s timeout.

### `GET /api/status/{run_id}` — Check if still running

Returns `{"running": true/false, "exit_code": null|int}`.

## MCP Endpoints (port 9090, prefixed with /mcp/)

All MCP endpoints return JSON. No authentication for v1 (intended for localhost-only AI tool access).

| Endpoint | Method | Description |
|---|---|---|
| `/mcp/profiles` | GET | List available profiles from config.yml |
| `/mcp/libraries` | GET | List libraries from config.yml with paths and profiles |
| `/mcp/run` | POST | Start a conversion (same schema as POST /api/run) |
| `/mcp/status/{run_id}` | GET | Check if a run is still in progress |
| `/mcp/stop/{run_id}` | POST | Kill a running conversion |
| `/mcp/ws/{run_id}` | WS | Live output streaming |

## Config-aware startup

When `convert.py` starts, it checks `config.yml` for `webui.enabled` and `mcp.enabled`:

```
convert.py startup
  ├── load config.yml
  ├── if webui.enabled → launch web UI server on configured host:port
  ├── if mcp.enabled  → launch MCP server on configured host:port
  └── run normal CLI mode
```

Both servers are launched as background threads so the CLI still functions normally.

Also supports standalone via `--webui-only` and `--mcp-only` flags.

## Flags (all CLI arguments mapped)

| Flag | Type | Default | Description |
|---|---|---|---|
| `use` | dropdown | `nvidia` | Transcoder: nvidia, intel, amdgpu, cpu, or raw encoder name |
| `bitrate` | number (nullable) | null | Override target bitrate (kbps) |
| `crf` | number (nullable) | null | CRF mode value |
| `workers` | number | 1 | Concurrent files |
| `verbose` | checkbox | false | Debug logs |
| `dry_run` | checkbox | false | Preview only |
| `min_savings` | number | 0 | Minimum savings % to keep |
| `keep_original` | checkbox | false | Skip backup |
| `exclude` | text | "" | Comma-separated dir names to skip |
| `ignore_path` | text (repeatable) | [] | Path substrings to skip |
| `cleanup_tmp` | checkbox | false | Clean temp files before scan |
| `libraries` | text (multi) | "" | Jellyfin library names (comma sep) |
| `since_hours` | number | 72 | Hours back for jellyfin-recent |
| `remote` | text | "" | user@host:/path |
| `local_tmp` | text | "" | Local temp dir for remote mode |

## Profile-aware flag pre-fill

When user selects a profile (in Direct or Library mode), these flags auto-populate:

| Profile field | Maps to flag |
|---|---|
| `encoder` | `use` |
| `target_bitrate` | `bitrate` |
| `minimum_savings_percent` | `min_savings` |
| `keep_audio_langs` | shown as info (not a CLI flag — set internally) |
| `keep_subtitles` | shown as info |

The profile also sets `max_bitrate` internally via `set_profile_globals()` — this is not a CLI flag but the UI should show it as read-only info when a profile is active.

## Backend runner

- **Only one run at a time**: `POST /api/run` rejects if a run is already in progress.
- Process is spawned via `asyncio.create_subprocess_exec(sys.executable, "convert.py", ...)`.
- stdout and stderr are read line by line and pushed to the WebSocket.
- **Reconnection**: WebSocket client stores output in a RingBuffer (last 500 lines). Reconnecting sends a replay of buffered lines.

## Frontend terminal panel

- `<pre id="terminal">` block styled like xterm:
  - Black background (`#1e1e1e`)
  - Green/white monospace text (13px)
  - Scrollable, auto-scroll to bottom on new output
  - Pause auto-scroll if user has scrolled up
- Status bar below terminal: `RUNNING 42s` or `EXITED code 0` or `STOPPED code -15`
- The `[▶ Run]` button is disabled while running; `[■ Stop]` button becomes active.

## File structure

```
webui/
  __init__.py
  main.py       — FastAPI app, routes, WebSocket handler
  runner.py     — background process manager (asyncio subprocess)
  mcp.py        — MCP endpoint router
  templates/
    index.html  — single-page UI with inline CSS/JS
```

## Run commands

```bash
# Web UI server standalone
python -m uvicorn webui.main:app --host 0.0.0.0 --port 8080

# MCP server standalone (needs wrapper — mcp_app is an APIRouter)
python -c "
from fastapi import FastAPI
from webui.mcp import mcp_app
server = FastAPI()
server.include_router(mcp_app)
import uvicorn
uvicorn.run(server, host='0.0.0.0', port=9090, log_level='info')
"

# From convert.py (handles wrapping internally)
python convert.py --webui-only
python convert.py --mcp-only
```

Or both launched automatically from `convert.py` if `webui.enabled` / `mcp.enabled` in config.

## Test Results (2026-07-22)

All features manually verified in browser and via API tests:

| Test | Result | Notes |
|---|---|---|
| Server boots (uvicorn) | ✅ | Returns 200 on `/` |
| Index page renders all UI elements | ✅ | H1, mode tabs, flag controls, terminal, status bar |
| `/api/config` returns full config JSON | ✅ | 4 libraries, 4 profiles, webui/mcp settings |
| `/api/env` returns env defaults | ✅ | No secrets exposed |
| Mode tab switching | ✅ | Direct, All Libraries, Single Library, Jellyfin Recent, Remote — correct tab-content toggling |
| Profile dropdown populated from config | ✅ | 4 profiles listed |
| Profile pre-fill (flag values) | ✅ | encoder→`use`, target_bitrate→`bitrate`, min_savings→`min_savings` |
| Profile info card | ✅ | Shows encoder, target, max, min savings | |
| Library dropdown populated | ✅ | 4 libraries listed with profile names |
| Direct mode: enter path, click Run | ✅ | Terminal shows command + output |
| `POST /api/run` returns run_id + command | ✅ | Correct CLI args built for all modes |
| `GET /api/status/{run_id}` | ✅ | Returns running/exit_code correctly |
| `POST /api/stop/{run_id}` | ✅ | Returns stopped/error correctly |
| `WS /api/ws/{run_id}` live streaming | ✅ | stdout/stderr and exit messages received |
| Timer + status bar on run | ✅ | Shows elapsed time, dot animation |
| Run/Stop button state management | ✅ | Run disabled while running, Stop active |
| Process exit → UI cleanup | ✅ | Buttons re-enable, status shows exit code |
| `--webui-only` flag | ✅ | Starts server on 0.0.0.0:8080 |
| `--mcp-only` flag | ✅ | Starts server on 0.0.0.0:9090 |
| MCP `/mcp/profiles` | ✅ | Returns all profiles with settings |
| MCP `/mcp/libraries` | ✅ | Returns libraries with paths + profile_settings |
| MCP `/mcp/run` → run_id | ✅ | Process spawned, command returned |
| MCP `/mcp/status/{run_id}` | ✅ | Running/exit code returned |
| MCP `/mcp/stop/{run_id}` | ✅ | Stopped/error response |
| MCP `/mcp/ws/{run_id}` | ✅ | Streaming stdout/stderr/exit works |
| `POST /api/run` concurrency enforcement | ✅ | Handles 409 when run in progress |

## Known issues

1. **MCP server cannot run as `uvicorn webui.mcp:mcp_app`** — `mcp_app` is an `APIRouter`, not a `FastAPI` app. Must wrap it: create `FastAPI()`, call `include_router(mcp_app)`. The run commands section below has been corrected.
2. **Encoder dropdown is hardcoded** — UI only shows 5 options (nvidia, intel, amdgpu, cpu, vaapi). Profile with a custom encoder name (e.g. `h264_nvenc`) won't match the dropdown.
3. **No encoding detection** — the web UI doesn't call `get_available_encoders()` before showing the dropdown.
4. **Separate RunManager instances** — web UI (port 8080) and MCP server (port 9090) each have their own `RunManager` singleton. Runs started on one aren't visible on the other. This is by design for security isolation but worth noting.
5. **WebSocket replay timing** — `subscribe()` happens after `get_buffer()` replay. If a process exits between buffer replay and subscribe, the exit message is not replayed to the newly connecting WS client (but IS in the buffer). Mitigation: clients should also poll `/api/status` on WS close.
6. **Port conflict** — no fallback to random port (not yet implemented).

## Edge cases

- **ffmpeg not found**: `resolve_ffmpeg_tools()` returns False — convert.py will fail at the start and output to terminal
- **Config not found**: `/api/config` returns `{"config_found": false}` — UI shows a warning
- **Config has webui/mcp disabled**: servers are not started; `/api/config` still returns the config values
- **Invalid profile encoder**: `resolve_transcoder()` fails — convert.py logs error and exits
- **WebSocket disconnect**: process keeps running; reconnecting replays last 500 lines
- **Browser closes mid-run**: process continues to completion (or until stop is requested from another tab)
- **Port conflict**: log a warning and fall back to a random port (not yet implemented)

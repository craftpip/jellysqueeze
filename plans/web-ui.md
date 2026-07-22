# Web UI Plan

## Overview

A web panel that wraps `convert.py` — reads `config.yml`, lets the user pick a profile (or all), tweak CLI params, and run the conversion in one of 5 modes, streaming live terminal output to the browser.

## Tech Stack

- **FastAPI** + **Starlette** — async, WebSocket built-in
- **Single HTML page** with vanilla JS + CSS — no build step, no npm
- **WebSocket** for real-time terminal output streaming
- **asyncio subprocess** to run `convert.py` and capture stdout/stderr live
- Dependencies: add `fastapi`, `uvicorn`, `websockets` to `requirements.txt`

## Config sections (new)

Add two new optional sections to `config.yml`:

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

Controls the web panel server. When `enabled: false`, the web UI server won't start.

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
- **Mode selector** (radio buttons or tabs): Direct, All Libraries, Single Library, Jellyfin Recent, Remote
- **Directory input** (shown only for Direct mode)
- **Profile selector** (shown for Direct mode) — dropdown populated from `config.yml` profiles. Selecting a profile pre-fills the flags (bitrate, encoder, etc.)
- **Library dropdown** (shown for Library / All / Jellyfin Recent modes) — populated from `config.yml` libraries
- **All flag controls** (see Flags section below)
- **Run / Stop buttons**
- **Terminal output panel**

### `GET /api/config` — Fetch config

Returns parsed `config.yml` as JSON:
```json
{
  "libraries": [
    {"name": "Movies R", "paths": [...], "profile": "profile_movies_r"}
  ],
  "profiles": { ... },
  "webui": {"enabled": true, "host": "0.0.0.0", "port": 8080},
  "mcp": {"enabled": true, "host": "0.0.0.0", "port": 9090}
}
```

### `GET /api/env` — Fetch env defaults

Returns current `.env` values as JSON (without secrets):
```json
{
  "TARGET_BR": 3000,
  "MAX_BR": 3300,
  "BITRATE_TOLERANCE": 300,
  "DEFAULT_CRF": 23,
  "JELLYFIN_BASE_URL": "http://10.69.1.164:8096"
}
```

### `POST /api/run` — Launch conversion

Accepts JSON:
```json
{
  "mode": "direct|all|library|jellyfin_recent|remote",
  "profile": "profile_movies_r|null",
  "directory": "/custom/path",
  "library": "Shows",
  "flags": {
    "bitrate": null,
    "crf": null,
    "use": "nvidia",
    "workers": 2,
    "verbose": true,
    "dry_run": false,
    "min_savings": 10,
    "no_backup_original": false,
    "exclude": "",
    "ignore_path": [],
    "cleanup_tmp": false,
    "libraries": "Shows,Movies",
    "since_hours": 72,
    "remote": "",
    "local_tmp": ""
  }
}
```

Returns:
```json
{ "run_id": "uuid", "command": "python convert.py ..." }
```

### `WS /api/ws/{run_id}` — Live output stream

WebSocket pushes lines as they're produced:
```json
{"type": "stdout", "data": "Scanning: /mnt/media1t/downloads/movies", "ts": "..."}
{"type": "stderr", "data": "[1/42] Checking: Movie.mkv", "ts": "..."}
{"type": "exit", "code": 0}
```

### `POST /api/stop/{run_id}` — Kill running process

Sends SIGTERM. Returns `{"stopped": true}`.

### `GET /api/status/{run_id}` — Check if still running

Returns `{"running": true/false, "exit_code": null|int}`.

## MCP Endpoints (port 9090, prefixed with /mcp/)

All MCP endpoints return JSON. No authentication for v1 (intended for localhost-only AI tool access).

### `GET /mcp/profiles`

List available profiles from config.yml.

```json
{
  "profiles": [
    {"name": "profile_movies_r", "target_bitrate": 3000, "encoder": "nvidia"}
  ]
}
```

### `GET /mcp/libraries`

List libraries from config.yml with their paths and profiles.

### `POST /mcp/run`

Start a conversion. Same schema as `POST /api/run` but returns immediately with a `run_id`. Output is pushed to a corresponding WebSocket at `WS /mcp/ws/{run_id}`.

### `GET /mcp/status/{run_id}`

Check if a run is still in progress, and get the exit code if finished.

### `POST /mcp/stop/{run_id}`

Kill a running conversion.

### `WS /mcp/ws/{run_id}`

Same live output streaming as the web UI WebSocket, but on the MCP server.

## Config-aware startup

When `convert.py` starts, it checks `config.yml` for `webui.enabled` and `mcp.enabled`:

```
convert.py startup
  ├── load config.yml
  ├── if webui.enabled → launch web UI server on configured host:port
  ├── if mcp.enabled  → launch MCP server on configured host:port
  └── run normal CLI mode
```

Both servers are launched as background processes (or threads) so the CLI still functions normally.

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
| `no_backup_original` | checkbox | false | Skip backup |
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

The profile also sets `max_bitrate` and `tolerance` internally via `set_profile_globals()` — these are not CLI flags but the UI should show them as read-only info when a profile is active.

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

# MCP server standalone
python -m uvicorn webui.mcp:mcp_app --host 0.0.0.0 --port 9090
```

Or both launched automatically from `convert.py` if `webui.enabled` / `mcp.enabled` in config.

## Implementation order

1. Add `webui` and `mcp` sections to `config.yml` and `config.yml.example`.
2. Update `setup.py` to prompt for webui/mcp enable during config generation.
3. Add config loading helpers in `convert.py` for `webui` and `mcp` sections.
4. Scaffold FastAPI app with `/api/config`, `/api/env`, `/api/run`, WebSocket.
5. Build `webui/runner.py` — asyncio subprocess manager.
6. Build `webui/mcp.py` — MCP REST endpoints.
7. Build the frontend HTML: mode selector, flag controls, terminal panel.
8. Wire everything together and test with `--dry-run` on a small directory.

## Edge cases

- **ffmpeg not found**: `resolve_ffmpeg_tools()` returns False — route returns error before spawning.
- **Config not found**: `/api/config` returns `{"config_found": false}` — UI shows a warning.
- **Config has webui.mcp disabled**: servers are not started; `/api/config` still returns the config values.
- **Invalid profile encoder**: `resolve_transcoder()` fails — show error in terminal before run.
- **WebSocket disconnect**: process keeps running; reconnecting replays last 500 lines.
- **Browser closes mid-run**: process continues to completion (or until stop is requested from another tab).
- **Port conflict**: log a warning and fall back to a random port.

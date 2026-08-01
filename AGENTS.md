# JellySqueeze — LLM Guide

## Project Overview

Python tool (`convert.py`) that shrinks video files by re-encoding oversized videos to a target bitrate and stripping unwanted audio/subtitle tracks. Uses ffmpeg/ffprobe. Integrates with Jellyfin API for checking recently-added media.

## Key files

- `plans/` — test plans stored as `plans/<topic>.md`
- `src/convert.py` — entry point (~2700 lines)
- `src/jellyfin_client.py` — Jellyfin API client (sync httpx)
- `src/_detect_encoder.py` — encoder detection helper (runs at setup time)
- `src/state_db.py` — SQLite state store for conversions, cache, runs, results, and events
- `src/webui/main.py` — FastAPI web UI server (~575 lines)
- `src/webui/mcp.py` — MCP REST API router (profiles, libraries, runs, config)
- `src/webui/runner.py` — background run management (start, stop, logs, status)
- `webui/` — React SPA (Vite, `npm run build`)
- `config.yml` — optional YAML config for libraries + webui/mcp settings
- `.env` — configuration (Jellyfin API key, bitrate settings, etc.)
- `config.yml.example` — example config with webui/mcp sections
- `var/media-convert.sqlite3` — active transactional state store for conversions, cache, runs, results, and events
- `var/_progress.txt` — legacy completed-conversion source imported into SQLite; preserve it
- `var/size-report.csv` — global output with before/after sizes (auto-generated)
- `var/probe-cache.json` — legacy probe-cache source imported into SQLite; preserve it
- `var/logs/` — dated log files and per-run size reports
- `var/runs/` — legacy web UI run JSON imported into SQLite; preserve it
- `Dockerfile.cpu` / `Dockerfile.nvidia` / `Dockerfile.intel` / `Dockerfile.amd` — single-stage Dockerfiles using jrottenberg/ffmpeg as base (includes all codecs)
- `docker-compose.yml` (CPU), `docker-compose.nvidia.yml`, `docker-compose.intel.yml`, `docker-compose.amd.yml` — runtime compose files
- `test_convert.py` — 9 tests for state DB, conversion options, progress tracking
- `scripts/convert.sh` — auto-generated venv wrapper script
- `ROADMAP.md` — original aspirational plan (all features now implemented)
- `transcoding-guide.md` — Linux GPU transcoding setup notes (AMD VA-API, Intel QSV)
- `requirements.txt` — python-dotenv, httpx, pyyaml, fastapi, uvicorn, websockets, psutil

## Key Architecture

- `discover_videos_and_cleanup()` — walks directory tree with `os.scandir`, cleans up temp files (`. TMP_TAG`) during scan
- `convert_if_needed()` — per-file decision: checks bitrate against MAX_BR, runs ffmpeg with fallback attempts, replaces original
- `build_ffmpeg_cmd()` — probes streams, builds ffmpeg args with proper stream maps, HW accel, encoder params, subtitle mode
- `safe_replace()` — atomic `os.replace()` with up to 12 retries (250ms delay) on PermissionError
- `main()` — local mode: sequential or parallel (ThreadPoolExecutor with done_lock)
- `main_remote()` — remote mode: sequential SCP download → convert → upload loop
- `resolve_ffmpeg_tools()` — finds ffmpeg/ffprobe via env override, `shutil.which()`, or PATH prefix scan
- `get_available_encoders()` — runs `ffmpeg -encoders` and parses output, cached globally
- `device_available(profile)` — checks device files (nvidia-smi, /dev/dri/renderD128) before trusting encoder list (key for Docker, where jrottenberg images have all encoders compiled in regardless of GPU presence)
- `ffprobe_json()` / `probe_streams()` / `get_estimated_bitrate_kbps()` — media probing helpers
- `JellyfinClient` in `jellyfin_client.py` — sync Jellyfin API client (list libraries, get recently added items)
- `load_config()` / `set_profile_globals()` / `_extract_profile()` — config.yml loading, inline profile extraction, and setting application
- `_extract_profile(config, lib)` — reads profile settings directly from library entry (inline keys preferred, falls back to old `profile:` reference)
- `main_all()` / `main_library()` / `main_jellyfin_recent()` — new mode dispatchers
- `run_library_scan()` — per-library scan with profile settings, restores globals on exit
- `validate_output_media()` — checks duration match + decode validation after encoding
- `get_resume_seconds()` / `concat_transcode_parts()` — resume partial encodes via concat
- `state_db.py` — WAL SQLite state shared by converter and Web UI; legacy state files are imported once without deletion
- `RunManager` in `runner.py` — launches conversion in a dedicated process group (`start_new_session=True`), permits independent library runs, rejects overlapping runs, and stops the full group via `killpg()`. Dual ring buffers: `_buffer` (500, all lines + JSON for parsing) and `_terminal_buffer` (500, non-JSON stdout + stderr only) — keeps log lines from being crowded out by JSON progress events during long encodes. WebSocket broadcasting via listener callbacks, dual reader tasks for stdout/stderr. `wait()` saves run history only after process exits.
- `build_convert_cmd()` in `main.py` — converts a JSON run request body into `convert.py` CLI args. Mode dispatch: all, library, jellyfin_recent, remote, direct.
- `start_run()` in `runner.py` — global lock serializes starts. Checks: duplicate library, exclusive modes (`all`, `jellyfin-recent`, direct path). Returns HTTP 409 on overlap.
- `emit_json()` — structured JSON-lines output for web UI
- `draw_progress_bar()` — live per-file progress with in-flight tracking
- `ProgressAwareStreamHandler` — logging handler that clears progress bars before log lines
- `save_env()`, `save_config()` — persist .env and config.yml changes

## Web UI API Endpoints

All under `/api` in `main.py`:

- **Config**: `GET /api/config` (sanitized config.yml), `GET /api/env`, `POST /api/env` (update .env)
- **Libraries CRUD**: `GET /api/libraries` (with run stats), `GET /api/libraries/{name}`, `POST /api/libraries`, `PUT /api/libraries/{name}`, `DELETE /api/libraries/{name}`
- **Path validation**: `GET /api/validate-path` (checks dir exists)
- **Run history**: `GET /api/runs` (last 100 + active), `GET /api/runs/{run_id}`
- **Stats**: `GET /api/stats` (aggregated across runs)
- **Run control**: `POST /api/run` (start), `POST /api/stop/{run_id}`, `GET /api/status`, `GET /api/status/{run_id}`
- **Logs**: `GET /api/log/{run_id}` (plain text)
- **WebSocket**: `WS /api/ws/{run_id}` (real-time streaming)
- **System**: `GET /api/system-stats` (CPU, memory, NVIDIA GPU)

## MCP API (`src/webui/mcp.py`)

Mounted under `/mcp` prefix on the same uvicorn instance (not a separate port despite `mcp.port: 9090` in config). Subset of main API:

- `GET /mcp/profiles` — lists named profiles with encoder/bitrate
- `GET /mcp/libraries` — libraries with resolved profile settings
- `POST /mcp/run` — starts a run (same infrastructure as main API)
- `GET /mcp/status/{run_id}` — minimal `{running, exit_code}` only (no results, buffer, or summary)
- `POST /mcp/stop/{run_id}` — stops a run (does NOT call `cleanup_run()`)
- `WS /mcp/ws/{run_id}` — independent WebSocket listener namespace (`mcp_ws_` prefix)

MCP has no history, stats, config, system-stats, or library-detail endpoints. Errors return `{"error": str}` instead of HTTP 409.

## Web UI ↔ convert.py Communication Protocol

The web UI and `convert.py` communicate through a **subprocess + stdout protocol**. No HTTP, IPC, or shared memory.

### Command Flow (Web UI → convert.py)

```
React SPA → POST /api/run {mode, library, flags}
  → api_run() in main.py
    → build_convert_cmd(req) — builds CLI args from JSON body
    → start_run(cmd) in runner.py
      → appends `--json` to the command
      → asyncio.create_subprocess_exec(cmd_with_json, stdout=PIPE, stderr=PIPE, start_new_session=True)
      → returns run_id (uuid hex)
```

`build_convert_cmd()` translates a JSON body into `convert.py` CLI arguments:

| JSON field | CLI mapping |
|---|---|
| `mode: "all"` | `--all` |
| `mode: "library"` + `library: "Shows"` | `--library Shows` |
| `mode: "jellyfin_recent"` + `flags.libraries + flags.since_hours` | `--jellyfin-recent --libraries ... --since-hours ...` |
| `mode: "remote"` + `flags.remote` | `--remote ...` |
| `mode: "direct"` + `directory: "/path"` | `/path` |
| `flags.bitrate` | `--bitrate N` |
| `flags.crf` | `--crf N` |
| `flags.use` | `--use nvidia` |
| `flags.workers > 1` | `--workers N` |
| `flags.verbose` | `--verbose` |
| `flags.dry_run` | `--dry-run` |
| `flags.min_savings` | `--min-savings N` |
| `flags.keep_original` | `--keep-original` |
| `flags.exclude` | `--exclude pattern` |
| `flags.ignore_path[]` | `--ignore-path path` (one per entry) |
| `flags.cleanup_tmp` | `--cleanup-tmp` |

### Process Group Isolation

`start_new_session=True` creates a new OS process group. The `RunManager` kills the entire group (including ffmpeg children) via `os.killpg(pid, SIGTERM)` with 5s timeout then `SIGKILL`. Docker Compose `init: true` reaps zombies.

### JSON Protocol (convert.py → Web UI)

When `--json` is passed, `JSON_MODE = True` in convert.py. Instead of terminal progress bars, all structured output is printed as one JSON object per line via `emit_json()`:

```python
def emit_json(type_: str, **data):
    if JSON_MODE:
        print(json.dumps({"type": type_, **data}, default=str), flush=True)
```

#### Event Types

| Type | When emitted | Payload |
|---|---|---|
| `run_status` | Probe phase, scan start, encode start, process start, done | `{phase, message}` |
| `run_folder` | After scanning each configured root directory | `{root: str, total: int}` |
| `progress` | Every ~500ms during per-file encoding | `{file, percent, finalizing, position_seconds, duration_seconds, frame_count, total_frames}` |
| `result` | Terminal per-file outcome (sequential mode) or after each file completes (parallel mode) | `{file, status: "OK"\|"SKIP"\|"FAIL", msg, before, after}` |
| `summary` | End of a scan() call or end of main_all()/main_library() mode | `{mode, files_total, ok, skip, fail, space_saved_mb}` |
| `overall_progress` | After each terminal-mode file (only emitted alongside `result` events in non-JSON terminal output path) | `{completed, total, ok, skip, fail}` |
| `exit` (from RunManager, not convert.py) | After subprocess exits | `{type: "exit", code: N}` |

### Output Capture (RunManager side)

```python
# runner.py — dual reader tasks
async def read_stdout(stream):
    while True:
        line = await stream.readline()
        if not line: break
        text = line.decode("utf-8", errors="replace").rstrip("\n\r")
        msg = {"type": "stdout", "data": text, "ts": time.time()}
        self._buffer.append(msg)           # ring buffer (max 500)
        self._broadcast(msg)               # → WebSocket listeners
        self._try_parse_json(text)         # → structured state

async def read_stderr(stream):
    # Same pattern but stderr lines are not parsed for JSON
```

Stderr is captured and broadcast but **never parsed for JSON** — only stdout carries structured events.

### JSON Parsing into Structured State

```python
def _try_parse_json(self, text: str):
    if not text.startswith("{"): return
    data = json.loads(text)  # try/except wrapped
    t = data.get("type")
    if t == "result":
        self._results.append(data)
    elif t == "summary":
        self._summary = data
    elif t == "run_folder":
        self._folder_totals[root] = int(total)
```

### Progress Event Flow (per-file)

1. `convert_if_needed()` receives `progress_callback=on_progress` closure
2. `on_progress()` calls `emit_json("progress", file, percent, finalizing, position_seconds, duration_seconds, frame_count, total_frames)`
3. `RunManager` reads the JSON line from stdout → broadcasts to WebSocket
4. In JSON mode: no separate terminal ticker thread, no progress bar drawing
5. In parallel mode: `on_progress` still fires from inside ThreadPoolExecutor workers via the same `progress_callback` parameter in `convert_if_needed()`

### Result Event Flow (per-file terminal)

- **Sequential mode**: `result` is emitted right after `convert_if_needed()` returns, in the main loop at lines 1992, 2010, 2021
- **Parallel mode**: `process_file()` returns a dict, and `result` is emitted in the `as_completed()` loop at lines 2194-2201 — after the worker finishes but before the next summary

### Termination Flow

```
User clicks Stop → POST /api/stop/{run_id}
  → api_stop() → mgr.stop()
    → os.killpg(pid, SIGTERM)
    → wait 5s for process
    → if still alive: os.killpg(pid, SIGKILL)
    → await self.wait()  # saves history with "stopped" summary
```

The `_stop_requested` flag changes the summary status from `"completed"` to `"stopped"`.

### Lifecycle Summary

```
POST /api/run → build_convert_cmd → start_run
  → RunManager.start(cmd + ["--json"])
    → subprocess starts, reader tasks begin
    → returns run_id → response to client
  → asyncio.ensure_future(mgr.wait())  # background
    → (conversion runs, reader tasks capture JSON lines)
    → process exits
    → reader tasks complete
    → _save_run_history() writes to SQLite
    → RunManager stays in _managers dict
```

```
WS /api/ws/{run_id}
  → sends ring buffer (past output)
  → subscribes to live updates via _broadcast()
  → on disconnect: unsubscribes
```

### Key Differences: Terminal Mode vs JSON Mode

| Aspect | Terminal mode | JSON mode |
|---|---|---|
| Progress bar | `draw_progress_bar()` + ticker thread | No ticker, `on_progress` emits JSON |
| stderr | Regular progress bar lines | Captured as `stderr` events but not parsed |
| `result` events | Not emitted (only log + progress file) | Emitted for every file |
| `summary` | Logged only | Emitted as JSON |
| Use case | CLI/local usage | Web UI / MCP |

## Web UI Run Flow

- `POST /api/run` body is a JSON with `mode` (all/library/jellyfin_recent/remote/direct), `library`, `directory`, and `flags` (bitrate, crf, use, workers, verbose, dry_run, etc.). `build_convert_cmd()` converts this to CLI args, `start_run()` creates a `RunManager`.
- `RunManager.start()` spawns `convert.py --json` via `asyncio.create_subprocess_exec()` with `start_new_session=True` (process group isolation).
- Two background `asyncio.Task`s read stdout/stderr line by line. Each line is wrapped as `{"type": "stdout"|"stderr", "data": ..., "ts": ...}`, appended to ring buffer (max 500), broadcast to WebSocket listeners, and parsed for JSON events.
- `_try_parse_json()` extracts structured types: `result` (terminal OK/SKIP/FAIL), `summary`, `run_folder` (folder file counts), `progress` (per-file encoding), `run_status` (discovery phase messages).
- Stop calls `os.killpg(self._process.pid, signal.SIGTERM)` with 5s timeout then `SIGKILL`. `_stop_requested` flag changes summary from `"completed"` to `"stopped"`.
- Different library runs may run simultaneously. Duplicate library, `--all`, Jellyfin-recent, and direct-path runs are exclusive (HTTP 409 on overlap).
- `wait()` saves run history to SQLite only after the converter process exits (not on intermediate per-folder summaries).
- Global `_managers: dict[str, RunManager]` holds all managers; `cleanup_run()` removes completed ones.
- On server shutdown, `stop_all_runs()` stops every running manager (SIGTERM → SIGKILL).
- SQLite is source of truth: `completed_files`, `probe_cache`, `runs`, `run_results`, `run_events`.
- Legacy `_progress.txt`, `probe-cache.json`, `var/runs/*.json` imported once and preserved.

## Web UI React SPA (`webui/`)

- **Stack**: Vite 5, React 18, React Router 6 (HashRouter). 3 dependencies — no state mgmt, no CSS framework, no HTTP client. Build output → `src/webui/static/`.
- **`api.js`**: 30-line `fetch()` wrapper. No auth (internal network only). All paths absolute (`/api/...`).
- **Pages**: Dashboard (stat cards + library table + Run All), LibraryForm (create/edit), LibraryDetail (profile + run history), RunDetail (live progress bars + terminal + filtered results table), RunHistory (all runs table), Settings (env vars).
- **Layout.jsx**: Sidebar with nav links + system stats bar (polls `/api/system-stats` every 4s, CSS-only bar visualization with Unicode blocks). Top bar with page title from OutletContext.
- **RunDetail.jsx** (most complex): Initial load via `GET /api/status/{runId}`. Opens WebSocket for live streaming, parses `progress`/`run_status`/`run_folder` JSON events. 2s HTTP polling fallback for results/summary. Auto-scroll terminal (max 200 lines). Filterable processed-files table. Cleanup closes WS + clears poll interval.
- **Styles**: 107 lines hand-written CSS, dark theme (`#121212`), flexbox layout, no framework.
- **Dev proxy**: Vite dev server on port 5173 proxies `/api` to `http://localhost:9238` and `/api/ws` to `ws://localhost:9238`.

## Config Integration

The `webui:` and `mcp:` sections in `config.yml` (`enabled`, `host`, `port`) are returned by `/api/config` but **not actually used at runtime** — the Docker entrypoint hardcodes `--host 0.0.0.0 --port 8080`, and MCP endpoints are always mounted on the same uvicorn under `/mcp`. These config values are informational/UI-facing only.

## SQLite State

- `completed_files` — tracks accepted conversions
- `probe_cache` — tracks reusable skips
- `runs` — run summaries
- `run_results` — terminal per-file outcomes
- `run_events` — buffered structured/log events
- Legacy `_progress.txt`, `probe-cache.json`, `var/runs/*.json` imported once and preserved.

## Progress Semantics

### Three Progress Layers

1. **Discovery progress** — `run_status(phase="scan")` + `run_folder(root, total)` per scanned directory. The web UI sums all `folderTotals` into `runTotal` for the run progress bar denominator.
2. **Per-file encoding progress** — `progress` events every ~500ms from within `convert_if_needed()`. Carries `percent`, `finalizing`, `position_seconds`, `duration_seconds`, `frame_count`, `total_frames`.
3. **Aggregate file-count progress** — `result` events per terminal file outcome. The web UI counts `results.length` against `runTotal` for the run progress bar numerator.

### How RunDetail.jsx Processes Events

**WebSocket path** (live):
- `progress` → updates `activeProgress[file]` state → renders per-file progress bars with time/frame info
- `run_status` → sets `runStatus` bar (shown when no active files yet — e.g. scanning phase)
- `run_folder` → merges into `folderTotals` → `runTotal = sum(folderTotals)`
- Non-JSON stdout/stderr lines → appended to terminal view (max 200 lines, auto-scroll)
- `exit` → marks `running=false`, clears `activeProgress`, closes WebSocket after 500ms

**HTTP polling path** (2s fallback via `setInterval`):
- `GET /api/status/{runId}` every 2s → syncs `results`, `summary`, `startedAt`, `running`, `exit_code`, `endedAt`
- Runs alongside WebSocket — catches state the WS might miss (e.g. if WS drops a `result` or `summary` line)

### Run Progress Bar

```
runTotal = sum(folderTotals)         # sum of all run_folder totals
runPct   = results.length / runTotal * 100
```
Rendered as a green bar (`#66bb6a`) with label `"OK {ok} / Skip {skip} / Fail {fail}"` and `"{results.length} / {runTotal} ({runPct}%)"`.

### Per-File Encoding Progress Bar

Rendered per-file in `activeFiles.map()`:
- Label: `"Encoding"` or `"Finalizing"` (when `finalizing=true`)
- File name: last path segment
- Progress info (priority order):
  1. If `position_seconds` and `duration_seconds` available: `"MM:SS / MM:SS (XX.X%)"`
  2. If `frame_count` and `total_frames` available: `"Frame NNN / ~NNN"`
  3. Fallback: just `"XX.X%"`
- Blue bar (`#4c9aff`) at `progress.percent%` width with CSS transition

### Per-File Progress Emission in convert.py

In `convert_if_needed()` (line 1568-1656):
- ffmpeg spawned with `-progress pipe:` and `Popen(stdout=PIPE, text=True, bufsize=1)`
- stdout lines parsed for `out_time_us`/`out_time` → seconds against source duration → percentage
- Some files emit `out_time = N/A` while frames still advance. After 2 consecutive N/A timestamps with no valid timestamp, falls back to `frame / estimated total frames`
- Updates emitted at most every 500ms (`now - last_up >= 0.5`)
- When ffmpeg reports `progress = end`, emits `finalizing=True` at 99.5%
- After ffmpeg exits, validation, savings checks, and `safe_replace()` still run before the `result` event

### Result Event Flow

- `result` fields: `{file, status: "OK"|"SKIP"|"FAIL", msg, before, after}`
- Sequential mode: emitted right after `convert_if_needed()` returns in the main for-loop (lines 1992-2021)
- Parallel mode: `process_file()` returns a dict, emitted in `as_completed()` loop (lines 2194-2201)
- Cache skips and already-done files also emit `result` events — they are terminal outcomes
- `before` and `after` are byte sizes (used by web UI to compute `saved_mb`)

### Summary Event

At the end of `scan()` (line 2252):
```python
emit_json("summary", files_total=total, ok=ok, skip=skip, fail=fail, space_saved_mb=...)
```
Also emitted at end of `main_all()`/`main_library()`/`main_jellyfin_recent()` with `mode` and `library_count`.

The `RunManager.wait()` uses either the parsed `_summary` dict or builds a `_partial_summary()` from `_results` if the process exits with non-0 or was stopped.

### Important Rules

- `run_folder` reports every discovered configured root and its file total. Run progress is the sum of all discovered folder totals; never present a single folder total as the whole run total.
- `result` is emitted only when a file reaches a terminal `OK`, `SKIP`, or `FAIL` outcome. Processed-file counts and stopped-run summaries must use these events only.
- Cache skips and already-done files are terminal results and must emit `result` events, including in parallel-worker mode.
- Files with usable ffmpeg `out_time_*` fields report `encoded time / source duration` progress.
- Some files emit `out_time_* = N/A` while frames advance. Only after repeated unavailable timestamps and no valid timestamp for that file may the UI fall back to `frame / estimated total frames`.
- When ffmpeg reports completion, the file changes to `Finalizing`; validation, savings checks, and atomic replacement can still be running. Do not show it as completed until a terminal result is emitted.
- Run detail defaults the processed-files table to `OK` and `FAIL`; skipped files remain available through the Skipped/All filters. Newest terminal result is shown first.

## Web UI Performance

- Library and run-history endpoints return compact run summaries only. Full results and buffered output are loaded only by the selected run-detail endpoint.
- Library detail polls every 5 seconds, so never include full event/log payloads in its response.

## Key functions — what they do

| Function | Role |
|---|---|
| `convert_if_needed(file, crf, verbose)` | Main per-file entry. Returns `(status, msg, size_row)` where status is `OK`, `SKIP`, or `FAIL` |
| `build_ffmpeg_cmd(...)` | Builds full ffmpeg command list. Can return `(None, error)` on probe failure |
| `pick_primary_video(vids)` | Picks default video stream, or first if none marked default |
| `select_audio_streams(auds)` | Filters by `ALLOWED_AUDIO_LANGS`, falls back to default then first |
| `select_subtitle_streams(subs)` | Filters by `ALLOWED_SUBTITLE_LANGS` (defaults to `ALLOWED_AUDIO_LANGS` if unset) |
| `tmp_name_for(file)` | Appends `.__transcoding__` before extension |
| `safe_replace(src, dst)` | Retries os.replace up to 12 times on PermissionError, returns bool |
| `source_fingerprint(file)` | Returns `(dev, ino, size, mtime_ns)` tuple to detect changes during conversion |
| `validate_output_media(src, dst)` | Returns `(bool, str)` — checks duration ±1% and ffmpeg decode validation |
| `expected_output_signature()` / `probe_output_signature()` | Compares expected vs actual stream layout to catch encoding issues |

## Important Rules

- **Never modify or delete `var/_progress.txt`** — it prevents re-converting already-processed files.
- **Always write the temp file first**, then replace the original via `safe_replace()`.
- The `TMP_TAG = ".__transcoding__"` is used to identify in-progress temp files. Files with this tag are deleted during discovery.
- GPU decoder support varies per profile — check `HWACCEL_DECODABLE` (line 48) before suggesting hardware acceleration.
- **Docker images use jrottenberg/ffmpeg as base** (not multi-stage). Trying to copy ffmpeg from jrottenberg images into python:slim causes libc conflicts (jrottenberg uses Ubuntu, slim uses Debian). Always install Python on top of the jrottenberg image instead.
- Keep `--workers` defaulting to `1`; parallel conversion must remain opt-in.
- **SQLite probe cache** only stores SKIP results. OK and FAIL results delete the cache entry so they are re-checked next run.
- **Legacy done.txt format** (in `var/_progress.txt`): one `path|option` per line. New completed checks use SQLite; preserve this file as migration source.
- Discovery skips `.trickplay` directories and names containing `.trickplay`. It also skips any dir listed in `--exclude`.
- `--bitrate` overrides: `MAX_BR = bitrate + 1000`, `BUFSIZE = MAX_BR * 2`.
- `safe_replace()` returns `bool` — always check it.
- `ORIGINAL_TAG = ".__original__"` — used for backups when `--keep-original`/`BACKUP_ORIGINALS` is set.
- Remote mode (`main_remote`) is **disabled at runtime** for media safety (SCP overwrite is not atomic).
- Output is validated after encoding: duration must match ±1% and the output must pass ffmpeg decode validation.
- The probe cache key uses `(path, opt, size, mtime_ns)`. Cached entries are only valid if all four match.
- `config.yml` can have `webui:` and `mcp:` sections for server configuration in addition to `libraries:`.
- `convert.py` must never start Uvicorn, MCP, or any server. The container Web UI is the only service binding its configured ports.
- Do not enable Uvicorn `--reload` in the running container: source/static changes would drop in-memory run tracking. Rebuild static assets and restart explicitly when backend code must reload.

## Conversion Fallback Strategy

Each file may be retried up to 4 times before marking FAIL:

1. Normal: HW decode + HW encode
2. Software decode + HW encode
3. Software decode + HW encode + drop subtitles (`-sn`)
4. CPU encode (`libx264`) + drop subtitles (only if libx264 is available and not already the primary encoder)

Fallback attempts cover: GPU decode failures, unsupported subtitle streams, cover art issues, weird container metadata.

## .env Variables

| Variable | Default | Description |
|---|---|---|
| `TARGET_BR` | 3000 | Target video bitrate in kbps |
| `MAX_BR` | 3300 | Files above this bitrate trigger conversion |
| `BUFSIZE` | 6000 | ffmpeg bufSize |
| `DEFAULT_CRF` | 23 | Default CRF value for CPU mode |
| `FFMPEG_BIN` | — | Override ffmpeg binary path |
| `FFPROBE_BIN` | — | Override ffprobe binary path |

## Known Issues

- **duration_mismatch failure** — Some files fail with `duration_mismatch(source=..., output=...)` meaning the encoded output is shorter than the source by 30-50s. This has hit KonoSuba episodes. The output file exists but is truncated. Not sure if ffmpeg drops frames or seeks wrong.
- **multiple_or_missing_video_streams** — Some files (Made in Abyss S02, KonoSuba S01E09) have unusual stream layouts that ffprobe can't parse into a clean primary video stream. The probe logic in `build_ffmpeg_cmd()` can't handle these and returns a FAIL.
- **NVENC p4 preset is slow** — The current run uses `-preset p4` with `h264_nvenc`, which encodes at roughly 1-2x realtime. A 24min episode takes ~1.5-2 hours.
- **Progress bar only visible in log file** — ffmpeg progress bars (carriage-return based) are logged to the log file but the current percentage can't be seen via `tail` easily since each line overwrites the previous. Use `lsof` or temp file size to estimate progress.
- **AMD Dockerfile is WIP** — `Dockerfile.amd` uses VA-API via `radeonsi` driver. AMF (`h264_amf`) is Windows-only and not compiled into jrottenberg images.

## Fix Patterns

- **Check real encoding progress**: Look at the temp file (`.__transcoding__.mkv`) size growing using `ls -lh`, or check the ffmpeg child process via `pgrep -P <parent_pid> -a`.
- **Check what file is being processed**: Use `ls -lt var/_progress.txt | tail -3` for recent completions, or `find ... -name "*__transcoding__*"` for in-progress files.
- **Check process health**: Use `ps -o pid,state,etime,pcpu -p <ffmpeg_pid>` to see if ffmpeg is actually encoding vs stuck.
- **Circular import between main.py and mcp.py**: `mcp.py` imports `build_convert_cmd` from `main.py`, and `main.py` imports `mcp_app` from `mcp.py`. Keep the import in `mcp.py` lazy (inside the function body) to avoid circular import at module level.

## Do Not Do

- **Never delete or move user data files without asking first.** Logs, progress files, probe caches, and size reports contain real operational data. Moving them to a new location should preserve the originals or ask the user before removing.
- **Don't be hyperactive and rush through tasks.** Slow down. Read carefully. Ask before doing destructive things like deleting files or moving data.
- **Don't assume cleanup is safe.** `rm -rf` on user data is never safe without explicit confirmation.
- **When restructuring paths (e.g. moving files to new directories), keep the old files in place** until the user confirms the new setup works and is ready to clean up.
- **Don't run npm install or npm commands on the host.** The running `jellysqueeze` container should be used for all validation (tests, syntax checks, imports). The `webui/` React app is already built and its output lives in `src/webui/static/`. If you need to rebuild, have the user do it inside the container or in their own environment.

## Safety

- Temp files (`.__transcoding__`) are cleaned up on startup.
- `safe_replace()` retries 12 times with 250ms delay on permission errors.
- Discovery skips `.trickplay` directories automatically.
- A file is only replaced if ffmpeg exits 0 and the output file exists with non-zero size.
- Probe cache prevents re-probing files whose size + mtime + conversion option hasn't changed.

## User Preferences

- During an active investigation, continue through evidence gathering, fixes, and verification without routine progress questions. Keep `plans/live-run-investigation.md` updated with relevant user observations, evidence, changes, and test results. Interrupt only for a destructive or irreversible action not already approved.
- During development, application correctness takes priority over preserving active conversions. Do not treat an in-progress conversion as a reason to defer deployment; conversion work resumes after the application is complete.
- Run History page: prefer table view (no card toggle). No bulk delete — history is read-only.
- Plan files live in `plans/` dir as `<topic>.md`. Use them to capture agreed scoping before coding.

## Testing

- 9 tests total, all pass
- State DB tests, conversion option tests, run manager lifecycle tests
- Run with: `docker exec jellysqueeze python -m pytest src/test_convert.py -v`

## Commands

| Command | Description |
|---|---|
| `python convert.py /path/to/media --use nvidia` | Basic GPU conversion |
| `python convert.py /path/to/media --use cpu --crf 23` | CPU with CRF quality |
| `python convert.py /path/to/media --bitrate 2800` | Target bitrate mode |
| `python convert.py /path/to/media --use nvidia --workers 2` | Parallel conversion |
| `python convert.py --all` | Convert all libraries from config.yml |
| `python convert.py --library Shows` | Convert one library from config.yml |
| `python convert.py --jellyfin-recent --libraries Shows,Movies --since-hours 72` | Check recently added Jellyfin items |
| `python convert.py --all --dry-run` | Preview without modifying files |
| `python convert.py --min-savings 10` | Require 10% minimum savings to keep converted file |
| `docker exec jellysqueeze python -m pytest src/test_convert.py -v` | Run tests |
| `docker compose build` | Build CPU image |
| `docker compose -f docker-compose.nvidia.yml build` | Build NVIDIA image |
| `docker compose -f docker-compose.intel.yml build` | Build Intel QSV image |
| `docker compose -f docker-compose.amd.yml build` | Build AMD VA-API image (WIP/untested) |
| `docker run --rm --entrypoint /venv/bin/python jellysqueeze:cpu -c "..."` | Smoke-test container without running uvicorn |
| `npm run build` | Build SPA (in webui/) |
| `docker compose up -d` | Start container with rebuilt image |

# media-convert-for-jellyfin — LLM Guide

## Project Overview

Python tool (`convert.py`) that shrinks video files by re-encoding oversized videos to a target bitrate and stripping unwanted audio/subtitle tracks. Uses ffmpeg/ffprobe. Integrates with Jellyfin API for checking recently-added media.

## Key files

- `convert.py` — entry point (~1600 lines)
- `jellyfin_client.py` — Jellyfin API client (sync httpx)
- `config.yml` — optional YAML config for libraries and profiles (copy from `config.yml.example`)
- `.env` — configuration (Jellyfin API key, bitrate settings, etc.)
- `done.txt` — tracks completed conversions (auto-generated, do not delete). Format: `path|option` one per line
- `size-report.csv` — output with before/after sizes (auto-generated)
- `probe-cache.json` — caches ffprobe results for files that haven't changed. Only caches SKIP results, not OK or FAIL.
- `test_convert.py` — 8 tests for done.txt tracking logic. 4 pass, 4 need a real video in `test_files/`
- `config.yml.example` — example config for libraries and profiles
- `ROADMAP.md` — original aspirational plan (all features now implemented)
- `transcoding-guide.md` — Linux GPU transcoding setup notes (AMD VA-API, Intel QSV)
- `requirements.txt` — python-dotenv, httpx, pyyaml

## Key Architecture

- `discover_videos_and_cleanup()` — walks directory tree with `os.scandir`, cleans up temp files (`. TMP_TAG`) during scan
- `convert_if_needed()` — per-file decision: checks bitrate against threshold, runs ffmpeg with fallback attempts, replaces original
- `build_ffmpeg_cmd()` — probes streams, builds ffmpeg args with proper stream maps, HW accel, encoder params, subtitle mode
- `safe_replace()` — atomic `os.replace()` with up to 12 retries (250ms delay) on PermissionError
- `main()` — local mode: sequential or parallel (ThreadPoolExecutor with done_lock)
- `main_remote()` — remote mode: sequential SCP download → convert → upload loop
- `resolve_ffmpeg_tools()` — finds ffmpeg/ffprobe via env override, `shutil.which()`, or PATH prefix scan
- `get_available_encoders()` — runs `ffmpeg -encoders` and parses output, cached globally
- `ffprobe_json()` / `probe_streams()` / `get_estimated_bitrate_kbps()` — media probing helpers
- `JellyfinClient` in `jellyfin_client.py` — sync Jellyfin API client (list libraries, get recently added items)
- `load_config()` / `set_profile_globals()` — config.yml loading and per-profile setting application
- `main_all()` / `main_library()` / `main_jellyfin_recent()` — new mode dispatchers

## Key functions — what they do

| Function | Role |
|---|---|
| `convert_if_needed(file, crf, verbose)` | Main per-file entry. Returns `(status, msg, size_row)` where status is `OK`, `SKIP`, or `FAIL` |
| `build_ffmpeg_cmd(...)` | Builds full ffmpeg command list. Can return `(None, error)` on probe failure |
| `pick_primary_video(vids)` | Picks default video stream, or first if none marked default |
| `select_audio_streams(auds)` | Filters by `ALLOWED_AUDIO_LANGS`, falls back to default then first |
| `tmp_name_for(file)` | Appends `.__transcoding__` before extension |
| `safe_replace(src, dst)` | Retries os.replace up to 12 times on PermissionError |

## Important Rules

- **Never modify or delete `done.txt`** — it prevents re-converting already-processed files.
- **Always write the temp file first**, then replace the original via `safe_replace()`.
- The `TMP_TAG = ".__transcoding__"` is used to identify in-progress temp files. Files with this tag are deleted during discovery.
- GPU decoder support varies per profile — check `HWACCEL_DECODABLE` (line 48) before suggesting hardware acceleration.
- Keep `--workers` defaulting to `1`; parallel conversion must remain opt-in.
- **probe-cache.json** only stores SKIP results. OK and FAIL results delete the cache entry so they are re-checked next run.
- **done.txt format**: one `path|option` per line. The option is `crf:N` or `br:TARGET_BR`. A file is skipped only if path + option both match.
- Discovery skips `.trickplay` directories and names containing `.trickplay`. It also skips any dir listed in `--exclude`.
- `--bitrate` overrides: `MAX_BR = bitrate + 1000`, `BUFSIZE = MAX_BR * 2`.

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
| `MAX_BR` | 3300 | Maximum bitrate before conversion triggers |
| `BITRATE_TOLERANCE` | 300 | Tolerance above MAX_BR |
| `BUFSIZE` | 6000 | ffmpeg bufSize |
| `DEFAULT_CRF` | 23 | Default CRF value for CPU mode |
| `FFMPEG_BIN` | — | Override ffmpeg binary path |
| `FFPROBE_BIN` | — | Override ffprobe binary path |

## Safety

- Temp files (`.__transcoding__`) are cleaned up on startup.
- `safe_replace()` retries 12 times with 250ms delay on permission errors.
- Discovery skips `.trickplay` directories automatically.
- A file is only replaced if ffmpeg exits 0 and the output file exists with non-zero size.
- Probe cache prevents re-probing files whose size + mtime + conversion option hasn't changed.

## Testing

- 8 tests total in `test_convert.py`
- 4 tests pass (empty load, save/load roundtrip, single entry per file, multiple files)
- 4 tests fail because they require a real video file in `test_files/` but the directory only has `.gitkeep`
- Tests mock nothing — they need actual files or refactoring to use mocks
- Run with: `python -m pytest test_convert.py -v`

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
| `python -m pytest test_convert.py -v` | Run tests |

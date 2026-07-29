# media-convert-for-jellyfin — LLM Guide

## Project Overview

Python tool (`convert.py`) that shrinks video files by re-encoding oversized videos to a target bitrate and stripping unwanted audio/subtitle tracks. Uses ffmpeg/ffprobe. Integrates with Jellyfin API for checking recently-added media.

## Key files

- `plans/` — test plans stored as `plans/<topic>.md`
- `src/convert.py` — entry point (~2500 lines)
- `src/jellyfin_client.py` — Jellyfin API client (sync httpx)
- `src/_detect_encoder.py` — encoder detection helper
- `config.yml` — optional YAML config for libraries and profiles (copy from `config.yml.example`)
- `.env` — configuration (Jellyfin API key, bitrate settings, etc.)
- `config.yml.example` — example config for libraries and profiles
- `var/_progress.txt` — tracks completed conversions (auto-generated, do not delete). Format: `path|option` one per line
- `var/size-report.csv` — global output with before/after sizes (auto-generated)
- `var/probe-cache.json` — caches ffprobe results for files that haven't changed. Only caches SKIP results, not OK or FAIL.
- `var/logs/` — dated log files and per-run size reports
- `test_convert.py` — 8 tests for progress tracking logic. 4 pass, 4 need a real video in `test_files/`
- `scripts/convert.sh` — auto-generated venv wrapper script
- `ROADMAP.md` — original aspirational plan (all features now implemented)
- `transcoding-guide.md` — Linux GPU transcoding setup notes (AMD VA-API, Intel QSV)
- `requirements.txt` — python-dotenv, httpx, pyyaml

## Key Architecture

- `discover_videos_and_cleanup()` — walks directory tree with `os.scandir`, cleans up temp files (`. TMP_TAG`) during scan
- `convert_if_needed()` — per-file decision: checks bitrate against MAX_BR, runs ffmpeg with fallback attempts, replaces original
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

- **Never modify or delete `var/_progress.txt`** — it prevents re-converting already-processed files.
- **Always write the temp file first**, then replace the original via `safe_replace()`.
- The `TMP_TAG = ".__transcoding__"` is used to identify in-progress temp files. Files with this tag are deleted during discovery.
- GPU decoder support varies per profile — check `HWACCEL_DECODABLE` (line 48) before suggesting hardware acceleration.
- Keep `--workers` defaulting to `1`; parallel conversion must remain opt-in.
- **probe-cache.json** only stores SKIP results. OK and FAIL results delete the cache entry so they are re-checked next run.
- **done.txt format** (in `var/_progress.txt`): one `path|option` per line. The option is `crf:N` or `br:TARGET_BR`. A file is skipped only if path + option both match.
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

## Fix Patterns

- **Check real encoding progress**: Look at the temp file (`.__transcoding__.mkv`) size growing using `ls -lh`, or check the ffmpeg child process via `pgrep -P <parent_pid> -a`.
- **Check what file is being processed**: Use `ls -lt var/_progress.txt | tail -3` for recent completions, or `find ... -name "*__transcoding__*"` for in-progress files.
- **Check process health**: Use `ps -o pid,state,etime,pcpu -p <ffmpeg_pid>` to see if ffmpeg is actually encoding vs stuck.

## Do Not Do

- **Never delete or move user data files without asking first.** Logs, progress files, probe caches, and size reports contain real operational data. Moving them to a new location should preserve the originals or ask the user before removing.
- **Don't be hyperactive and rush through tasks.** Slow down. Read carefully. Ask before doing destructive things like deleting files or moving data.
- **Don't assume cleanup is safe.** `rm -rf` on user data is never safe without explicit confirmation.
- **When restructuring paths (e.g. moving files to new directories), keep the old files in place** until the user confirms the new setup works and is ready to clean up.

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

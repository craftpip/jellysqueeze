# Logging & Reporting to Dated Directories

## What already works

- `make_auto_log_path()` in `convert.py` creates `logs/YYYY-MM-DD/HH-MM-SS_mode.log`
- `setup_logging()` creates parent directories as needed
- All modes go through this

## Changes

### 1. Move logs under var/

- Change `LOGS_DIR` from `logs/` to `var/logs/`
- Path becomes: `var/logs/YYYY-MM-DD/HH-MM-SS_mode.log`

### 2. Remove legacy root log

- Delete `convert-all.log` from project root
- Only date-stamped logs in `var/logs/` kept

### 3. Per-run size report

- Keep global `size-report.csv` at `var/size-report.csv`
- Add per-run size report: `var/logs/YYYY-MM-DD/HH-MM-SS_mode.size.csv`

### 4. Rename done.txt to _progress.txt

- `var/_progress.txt` — same format, update all references

### 5. probe-cache.json

- Move to `var/probe-cache.json`

### 6. Log cleanup / retention (optional)

- Optionally auto-clean logs older than N days

## Non-goals

- No log rotation daemon or external tooling

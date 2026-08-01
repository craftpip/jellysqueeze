# Scheduled Runs (cron-like timer)

Schedule library scans and jellyfin-recent checks to run on a timer, without having to click Run in the web UI.

## Scope (agreed)

- Schedules are human friendly: repeat `daily`, `weekly`, or `monthly` at a set time (HH:MM, 24h).
- Fully editable in the web UI (create / edit / enable-disable / delete), persisted to `config.yml`.
- Target modes: `library` (one library) and `jellyfin_recent` (libraries + since_hours).
- Overlap: if a scheduled run fires while a run for the same target is already active, **skip it and wait for the next tick** (no queueing).
- Runs started by the scheduler use the existing `start_run()` path, so the normal exclusivity rules and process isolation apply.

## Status

Implemented and verified live (8/1/2026). 46 tests total (36 prior + 10 scheduler).

- Backend: `src/webui/scheduler.py` (`next_run`, `validate_schedule`, `Scheduler` class), CRUD + run-now endpoints in `main.py`, scheduler started on app startup.
- Schedules page: `webui/src/components/Schedules.jsx` (table + create/edit modal, enable toggle, run now, delete), route `/schedules`, nav link.
- Live verification: create/edit/delete via UI and API; enable/disable toggle round-trips; "Run now" starts a run and navigates to run detail; scheduler auto-fired a real run (exit 0, 5945 files, all probe-cache skips) and rolled next_run to the next day; overlap skip logic unit-tested.
- Bugs found and fixed during implementation:
  - `run_now` stored `next_run: None` in `_last`, which clobbered the computed next run in `get_status` — now computed after the merge.
  - Minute-granularity bug: a tick landing mid-minute made the due time already `<= now`, rolling the schedule to the next day so it could never fire. Rollover now compares against the minute-floor of `now`, so a schedule is "due" throughout its target minute.

## Config storage

New `schedules:` section in `config.yml`, managed by the web UI through the existing `save_config()` (whole-file write, already handles the single-file bind-mount fallback).

```yaml
schedules:
  - name: "Nightly Shows scan"
    enabled: true
    repeat: daily          # daily | weekly | monthly
    day: 1                 # weekly: weekday 0-6 (Mon-Sun); monthly: day-of-month 1-31
    time: "03:00"          # HH:MM
    mode: library          # library | jellyfin_recent
    library: "Shows"       # required when mode=library
    flags:
      libraries: "Shows"   # required when mode=jellyfin_recent
      since_hours: 72
```

Notes:
- `repeat: daily` ignores `day`.
- `name` is the schedule's id (must be unique; used for edit/delete).
- Validation at save time: time must parse, day must be 0-6 (weekly) or 1-31 (monthly), mode fields filled.

## Scheduler (backend)

New module `src/webui/scheduler.py`:

- `next_run(schedule, now)` — pure function returning the next strictly-future datetime for daily/weekly/monthly at the given time. Monthly day-of-month rolls into the next month if this month's occurrence already passed; missing days (e.g. 31) roll to the next month that has it.
- `Scheduler` class with a background asyncio task, started on FastAPI app startup (lifespan/startup event) and cancelled on shutdown:
  - Ticks every 30s.
  - Re-reads `config.yml` each tick so UI edits apply without a restart (file is small; reads are cheap).
  - For each enabled schedule, computes `next_run`; if `now >= next_run`, builds the CLI command (via `build_convert_cmd`, same as the MCP runner) and calls `await start_run(cmd)`.
  - Because `next_run` is always the next strictly-future occurrence, a fired occurrence won't re-fire on the next tick. In-memory `fired` set keyed by `(name, occurrence)` as a belt-and-braces guard; entries older than one occurrence are dropped.
  - Catches `RuntimeError` from `start_run()` (overlap/exclusivity) — logs and skips to the next occurrence.
  - Exposes `get_status()` → per-schedule `{next_run, last_run_started_at, last_run_id, last_skipped_reason}`.

## API (main.py)

CRUD under `/api/schedules`, all writing through `save_config()` then triggering a scheduler reload:

- `GET /api/schedules` — schedules + `next_run` + `enabled` + last-run info
- `POST /api/schedules` — create (409 on duplicate name)
- `PUT /api/schedules/{name}` — update
- `DELETE /api/schedules/{name}` — delete
- `POST /api/schedules/{name}/run` — "run now" (immediate single fire, same overlap rules; optional, nice for testing)

## Web UI

New "Schedules" page (sidebar item):

- Table of schedules: name, repeat + day, time, mode/target, next run, enabled toggle, last run.
- "New schedule" button opens a form (modal or inline): repeat select (daily/weekly/monthly), day picker (weekday select for weekly, number input for monthly, hidden for daily), time input, mode select, library select (from `/api/libraries`), for recent mode a multi-select of libraries + since-hours input.
- Edit reuses the form; delete asks for confirmation (matches existing patterns — history is read-only, forms are modal).
- Shows "next run" in local browser time.

## Testing

Add to `src/test_convert.py`:

- `next_run` cases: daily today-later, daily tomorrow-after-time-passed, weekly rollover, monthly rollover and day-31-missing-month, disabled schedule → None.
- Schedule validation: bad time, bad day range, missing mode fields.
- Scheduler tick: fake config with a due schedule, mock `start_run` to assert it fires once and does not re-fire on the next tick; overlap `RuntimeError` → skipped and recorded.
- API CRUD round-trip against `config.yml` (temp copy) — create, update, disable, delete.

Run with: `docker exec jellysqueeze python -m pytest src/test_convert.py -v`

## Out of scope / notes

- No queueing of missed runs (e.g. server down at 03:00 → next occurrence is tomorrow 03:00; matches "skip and wait").
- Scheduler is part of the app process (single uvicorn, no reload). If the container is down, nothing fires — that's expected.
- Optionally tag scheduled runs in history (a `source` column) so Run History can filter "Scheduled" — deferred unless wanted.
- Timezone: uses the container's local time (UTC by default in the image). Note in the UI that times are server-local.

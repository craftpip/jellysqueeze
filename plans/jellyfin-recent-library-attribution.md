# Jellyfin-Recent Library Attribution

## Problem

A `jellyfin_recent` run covers multiple libraries (e.g. Shows + Movies) but is
stored in run history with `library = "jellyfin-recent"` (see
`RunManager._extract_library` in `src/webui/runner.py`). `api_list_libraries()`
and `api_get_library()` filter runs by `run["library"] == name`, so none of the
per-library savings / run history / last-run info appears on the individual
library pages.

Verified: Dashboard **total** metrics (`/api/stats`) already include
jellyfin-recent runs — it sums every saved run's summary with no library filter.
The gap is only per-library attribution.

The persisted `run_results` table has no library column, so attribution comes
from the run **summary** (stored as free-form JSON), not per-file rows.

## Scope

- Scheduled `jellyfin_recent` runs attribute their per-library stats to each
  library they touch.
- `--all` runs and multi-name `--library A,B` runs have the identical gap but
  are **out of scope** for this change (schedules cannot use them).

## Changes

1. `src/convert.py` — `main_jellyfin_recent()`:
   - Track `lib_stats: {name: {ok, skip, fail, space_saved_mb}}` accumulators.
   - Emit `library=<lib_name>` on every `result` event (live / stop-path
     attribution).
   - Add a `libraries` breakdown to both emitted `summary` events (the
     no-recent-files early return and the final summary).

2. `src/webui/runner.py` — `_partial_summary()`: build the same `libraries`
   breakdown from `_results` (which now carry `library`) so stopped/failed runs
   are attributed too.

3. `src/webui/main.py`:
   - New `_library_scoped_summary(run, name)` helper: whole summary for direct
     `run.library == name` runs, the breakdown entry for jellyfin-recent runs,
     else `None`.
   - `api_list_libraries()`: include all runs touching the library (existing
     direct match + breakdown attribution); sum scoped saved MB; newest touched
     run becomes `last_run`; `run_count` counts touched runs.
   - `api_get_library()`: build run-history entries from touching runs with
     library-scoped summaries; attribute live active runs by matching
     `result.library` against `mgr.results`.

## Explicitly Not Changed

- `/api/stats` (dashboard totals) — already correct.
- `run_results` schema — no migration; attribution rides the summary JSON.
- `--all` / multi-name `--library` attribution.
- Past completed jellyfin-recent runs (saved before this fix) stay
  unattributed. Future runs attribute forward.

## Verification

- Existing test suite passes.
- Manual: run `--jellyfin-recent --libraries ...`, confirm each library's
  `/api/libraries` `total_saved_mb` / `run_count` / `last_run` reflect the run
  and dashboard totals are unchanged.
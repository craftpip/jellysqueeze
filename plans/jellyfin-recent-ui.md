# Jellyfin Recent — Web UI Run Buttons

**Status: implemented and verified live (8/1/2026).** All plan items done, 36 tests pass, browser flow verified against a real Jellyfin query (Dashboard modal run → RunDetail with 18-file total, 2 already-done SKIPs, refresh persistence, 409 inline error). Two pre-existing bugs found and fixed while verifying (see below).

Add "Recently Added" run buttons to the Dashboard and Library Detail pages so users can trigger `--jellyfin-recent` without curl.

## Is the flow different? Yes.

`jellyfin-recent` mode (`main_jellyfin_recent()` in convert.py) works differently from a library scan:

| Aspect | Library scan | Jellyfin recent |
|---|---|---|
| Discovery | Scans directories on disk, emits `run_folder(root, total)` per root | Queries Jellyfin API (`/Users/{id}/Items`, sorted by DateCreated within `since_hours`), resolves item paths to local files |
| Progress bar | `runTotal` = sum of `run_folder` totals; works end to end | **No `run_folder` events** — run progress bar denominator stays 0 |
| Status events | `run_status` for probe/scan/process phases | Startup emits general probe/cache statuses, but recent mode emits no query, total, or per-file status events of its own |
| Parallelism | `--workers N` supported | Sequential only; `workers` flag ignored |
| Run overlap | Duplicate library = 409 | Exclusive with itself / `all` / direct; not alongside a library scan (conservative — see Bugs) |
| Run history label | library name | `"jellyfin-recent"` (from `_extract_library`) |
| Per-file profile | applied per library via settings | applied per library via `set_profile_globals` (bitrate etc.) |
| Library `workers`/`ignore_dirs` | applied | NOT applied (only CLI `--ignore-path` filters) |

The conversion decision path is similar after discovery, but recent mode must be brought up to the same JSON terminal-event contract as scan mode: every selected file must emit exactly one `result`, including missing, already-done, cached, and dry-run outcomes.

## Changes

### 1. New modal component `webui/src/components/RecentRunModal.jsx`

Reusable for both pages. **Done** (`RecentRunModal.jsx` + `.modal-overlay`/`.modal-panel`/`.modal-actions` styles). Fields:
- Libraries: comma-separated textarea/input, prefilled with all config library names (Dashboard) or fixed to the current library (Library Detail).
- `since_hours`: number input, default 72.
- Buttons: `Run` / `Cancel`.
- On Run: `POST /api/run` with `{mode: "jellyfin_recent", flags: {libraries, since_hours}}`, then navigate to `/run-detail/{run_id}`.
- Show inline error on 409/500 (e.g. "a run is already active").
- Styling: reuse `.form-row` / `.field` / `.link-btn`; add minimal modal overlay + panel styles to `styles.css` (no framework).

### 2. Dashboard (`Dashboard.jsx`)

**Done.** "Recently Added" link-btn in the `dash-header` actions next to "+ New Library". Clicking opens `RecentRunModal` prefilled with all config libraries (comma-joined). Dashboard already has `libs` loaded, so names come from there.

### 3. Library Detail (`LibraryDetail.jsx`)

**Done.** "Recently Added" link-btn next to "Run Now". Clicking opens `RecentRunModal` fixed to the current library name (read-only field), same `since_hours`.
- Keep this button available when that library has an active library scan, since the runner permits a recent run alongside it. **Done** — button renders regardless of active run state.

### 4. Backend progress and event contract

**Done.**

- In `main_jellyfin_recent()`: emit `run_status` events:
  - `phase="jellyfin"` before querying: `"Querying Jellyfin: {lib_names}"`
  - `phase="process"` with `files_total=N` after dedupe: `"Found {N} recent file(s)"`
  - `phase="checking"` before handling every file, including paths that later become missing, already-done, cached, or dry-run skips. `checking`/`done` events also carry `files_total` so the latest retained `run_status` always has the total.
- Emit `result` exactly once for every deduped file in every terminal branch. Match scan-mode payloads for missing, already-done, cached, dry-run, OK, SKIP, and FAIL outcomes. **Also removed the query-phase `p.exists()` skip** that silently dropped missing files before they could emit a `missing` result.
- When no recent files are found, emit `run_status(phase="process", files_total=0)` followed by a zero-value `summary` instead of returning without structured completion output.
- Extend `RunManager._try_parse_json()` to retain the latest `run_status` payload. Expose it from `/api/status/{run_id}` for active runs, alongside `folder_totals`. Persisted in SQLite `run_status_json` column (with `ALTER TABLE` migration) so historical runs keep it too. **Files_total is inherited across `run_status` events that omit it** (e.g. the shared `encode` phase), so the retained status always carries the total once the `process` event fires.
- RunDetail must initialize and refresh `runStatus` from `/api/status` as well as WebSocket events. This prevents a fast query from losing the total before the page has subscribed to the socket.
- RunDetail progress bar: use the sum of `run_folder` totals when present; otherwise use the latest `run_status.files_total`. This shows live `done/files_total` for recent mode and works after a refresh or WebSocket reconnect.

### 5. Tests

**Done.** All 33 tests pass (`docker exec media-convert python -m pytest src/test_convert.py -q`).

- `src/test_convert.py`: added `build_convert_cmd` test asserting jellyfin_recent mapping:
  - `{mode:"jellyfin_recent", flags:{libraries:"Shows,Movies", since_hours:24}}` → `--jellyfin-recent --libraries Shows,Movies --since-hours 24`
  - default since_hours → 72
- Added mocked `main_jellyfin_recent()` coverage asserting:
  - query and process statuses are emitted, including `files_total` after dedupe;
  - every selected file emits one terminal `result`, including already-done/cache/missing/dry-run paths;
  - an empty query emits `files_total=0` and a zero-value summary.
  - Shared `_run_recent()` helper fakes the `jellyfin_client` module via `sys.modules`.
- Added a `RunManager` parsing test for the latest `run_status`, including `files_total`, and a persistence round-trip test.

### 6. Rebuild SPA

**Done.** `npm run build` in `webui/` produced `assets/index-B8IZy-QC.js` + `index-Duawk3RU.css`; `index.html` updated by the build. New bundle contains the recent-run strings.

## Edge cases

- Empty/blank libraries → disable Run button in modal.
- Jellyfin not configured (no API key) → backend emits FATAL and exits. Do not return API-key material from `/api/env`; add a non-secret `jellyfin_configured` boolean and show the modal hint from that field.
- Overlapping run → server 409, show message in modal.
- Ambiguous/unknown Jellyfin library name → convert.py logs warning, continues with other libs; summary still emitted.
- `flags.libraries` must be a string (build_convert_cmd passes it straight to `--libraries`).

## Not in scope

- Making jellyfin-recent parallel (`--workers`).
- Applying library `ignore_dirs`/`workers` to recent mode.
- Jellyfin URL/key config UI (already exists in Settings with a Test Connection button).

## Bugs found and fixed while verifying (pre-existing, not caused by this plan)

1. **Exclusive runs could never start.** `start_run()` treated the requested library being an exclusive mode (`all`/`jellyfin-recent`/direct) as an automatic 409 even with nothing running, so those runs always failed. Fixed in `runner.py:start_run` to only conflict on a real overlap: duplicate library, or an exclusive request while something runs, or an exclusive run active while requesting anything. Intentionally conservative: a recent run is NOT allowed alongside a library scan, because recent lists overlap library scans and two processes could race on the same temp file.
2. **`/api/libraries` intermittently 500ed at boot.** `_migrate_runs_columns()` guards the ALTER with `PRAGMA table_info`, but FastAPI runs sync endpoints in a threadpool, so a concurrent `initialize()` could run the ALTER while the column already existed → `OperationalError: duplicate column name`. Fixed in `state_db.py` by treating a duplicate-column `OperationalError` as success unless the column is still absent after re-checking.

## Verification

1. `docker exec media-convert python -m pytest src/test_convert.py -q` — all pass. **Done (36/36, incl. 2 new exclusivity tests + 1 files_total-retention test).**
2. Rebuild SPA, recreate container (or just `docker compose restart` since static is bind-mounted via whole-repo mount). **Done — both.**
3. Browser: Dashboard → "Recently Added" → Run → RunDetail shows status events + results + progress bar with files_total denominator. **Done — 18 files, 2 already-done SKIPs, `2 / 18 (11.1%)` progress bar.**
4. Browser: Library Detail → "Recently Added" → same, scoped to that library. **Done — modal locks to the current library (read-only).**
5. With a duplicate run: verify 409 message appears in the modal. **Done — "A conversion run is already active for this library" shown inline.**
6. Refresh RunDetail immediately after starting a recent run and verify the total/progress remains visible. **Done — full reload during encode still shows `2 / 18` via retained `run_status.files_total`.**
7. Run with no matching recent files and verify a completed zero-file history entry and RunDetail summary. **Covered by unit test (`test_jellyfin_recent_empty_query_emits_zero_summary`); not run live.**
8. Verify an already-done or cached recent file increments processed progress through a terminal `SKIP` result. **Done — `already_done` files emitted `result` SKIP events counted in the progress bar.**

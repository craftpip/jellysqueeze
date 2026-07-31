# Jellyfin Recent — Web UI Run Buttons

Add "Recently Added" run buttons to the Dashboard and Library Detail pages so users can trigger `--jellyfin-recent` without curl.

## Is the flow different? Yes.

`jellyfin-recent` mode (`main_jellyfin_recent()` in convert.py) works differently from a library scan:

| Aspect | Library scan | Jellyfin recent |
|---|---|---|
| Discovery | Scans directories on disk, emits `run_folder(root, total)` per root | Queries Jellyfin API (`/Users/{id}/Items`, sorted by DateCreated within `since_hours`), resolves item paths to local files |
| Progress bar | `runTotal` = sum of `run_folder` totals; works end to end | **No `run_folder` events** — run progress bar denominator stays 0 |
| Status events | `run_status` for probe/scan/process phases | Startup emits general probe/cache statuses, but recent mode emits no query, total, or per-file status events of its own |
| Parallelism | `--workers N` supported | Sequential only; `workers` flag ignored |
| Run overlap | Duplicate library = 409 | Exclusive with itself / `all` / direct; but can run alongside a library run |
| Run history label | library name | `"jellyfin-recent"` (from `_extract_library`) |
| Per-file profile | applied per library via settings | applied per library via `set_profile_globals` (bitrate etc.) |
| Library `workers`/`ignore_dirs` | applied | NOT applied (only CLI `--ignore-path` filters) |

The conversion decision path is similar after discovery, but recent mode must be brought up to the same JSON terminal-event contract as scan mode: every selected file must emit exactly one `result`, including missing, already-done, cached, and dry-run outcomes.

## Changes

### 1. New modal component `webui/src/components/RecentRunModal.jsx`

Reusable for both pages. Fields:
- Libraries: comma-separated textarea/input, prefilled with all config library names (Dashboard) or fixed to the current library (Library Detail).
- `since_hours`: number input, default 72.
- Buttons: `Run` / `Cancel`.
- On Run: `POST /api/run` with `{mode: "jellyfin_recent", flags: {libraries, since_hours}}`, then navigate to `/run-detail/{run_id}`.
- Show inline error on 409/500 (e.g. "a run is already active").
- Styling: reuse `.form-row` / `.field` / `.link-btn`; add minimal modal overlay + panel styles to `styles.css` (no framework).

### 2. Dashboard (`Dashboard.jsx`)

- Add "Recently Added" button in the `dash-header` actions next to "+ New Library".
- Clicking opens `RecentRunModal` prefilled with all config libraries (comma-joined). Dashboard already has `libs` loaded, so names come from there.

### 3. Library Detail (`LibraryDetail.jsx`)

- Add "Recently Added" button next to "Run Now".
- Clicking opens `RecentRunModal` fixed to the current library name (read-only field), same `since_hours`.
- Keep this button available when that library has an active library scan, since the runner permits a recent run alongside it.

### 4. Backend progress and event contract

- In `main_jellyfin_recent()`: emit `run_status` events:
  - `phase="jellyfin"` before querying: `"Querying Jellyfin: {lib_names}"`
  - `phase="process"` with `files_total=N` after dedupe: `"Found {N} recent file(s)"`
  - `phase="checking"` before handling every file, including paths that later become missing, already-done, cached, or dry-run skips.
- Emit `result` exactly once for every deduped file in every terminal branch. Match scan-mode payloads for missing, already-done, cached, dry-run, OK, SKIP, and FAIL outcomes.
- When no recent files are found, emit `run_status(phase="process", files_total=0)` followed by a zero-value `summary` instead of returning without structured completion output.
- Extend `RunManager._try_parse_json()` to retain the latest `run_status` payload. Expose it from `/api/status/{run_id}` for active runs, alongside `folder_totals`.
- RunDetail must initialize and refresh `runStatus` from `/api/status` as well as WebSocket events. This prevents a fast query from losing the total before the page has subscribed to the socket.
- RunDetail progress bar: use the sum of `run_folder` totals when present; otherwise use the latest `run_status.files_total`. This shows live `done/files_total` for recent mode and works after a refresh or WebSocket reconnect.

### 5. Tests

- `src/test_convert.py`: add `build_convert_cmd` test asserting jellyfin_recent mapping:
  - `{mode:"jellyfin_recent", flags:{libraries:"Shows,Movies", since_hours:24}}` → `--jellyfin-recent --libraries Shows,Movies --since-hours 24`
  - default since_hours → 72
- Add mocked `main_jellyfin_recent()` coverage asserting:
  - query and process statuses are emitted, including `files_total` after dedupe;
  - every selected file emits one terminal `result`, including already-done/cache/missing/dry-run paths;
  - an empty query emits `files_total=0` and a zero-value summary.
- Add a `RunManager` parsing test for the latest `run_status`, including `files_total`.

### 6. Rebuild SPA

- `npm run build` in `webui/` → new hashed assets in `src/webui/static/`; update `index.html` refs via build output. Tests re-run in container after build.

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

## Verification

1. `docker exec media-convert python -m pytest src/test_convert.py -q` — all pass.
2. Rebuild SPA, recreate container (or just `docker compose restart` since static is bind-mounted via whole-repo mount).
3. Browser: Dashboard → "Recently Added" → Run → RunDetail shows status events + results + progress bar with files_total denominator.
4. Browser: Library Detail → "Recently Added" → same, scoped to that library.
5. With a duplicate run: verify 409 message appears in the modal.
6. Refresh RunDetail immediately after starting a recent run and verify the total/progress remains visible.
7. Run with no matching recent files and verify a completed zero-file history entry and RunDetail summary.
8. Verify an already-done or cached recent file increments processed progress through a terminal `SKIP` result.

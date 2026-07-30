# Run History Enhancements

## What's changing

### 1. Duration column

Add a column between Status and the View button showing `ended_at - started_at` formatted as e.g. `5m 32s`, `1h 12m`, `32s`. Blank while running.

### 2. Sort by column

Click column headers to toggle asc/desc sort. Affected columns: Date, OK, Skip, Fail, Saved, Duration. Active sort shown with a small arrow indicator (`▲`/`▼`). Default sort: Date descending (newest first — preserve whatever order the API returns).

### 3. Search bar

Text input above the table, placeholder `Filter by library`. Filters rows in real-time (case-insensitive) by library name only. That's it — status is already visible at a glance via the tag colors.

### 5. Relative time alongside absolute date

Show relative time as the primary display (`2h ago`, `Yesterday`, `3d ago`). Full absolute date on `title` attribute. During the current day, show just the relative time; after that, show `relative + date` (e.g. `3d ago — Jul 27`).

### 6. Savings trend sparkline

Tiny inline SVG sparkline above the table showing `space_saved_mb` from the last 20 runs. Placed next to the stats line or above the search bar. Gives a quick visual on whether savings are dropping off over time.

### 7. "Load more" pagination

Replace "last 100" with a "Load more" button at the bottom. Load 50 initially, append 50 on each click. Client-side pagination on the full list (API cap is 100, that's fine for now).

---

## Files to touch

| File | Change |
|---|---|
| `webui/src/components/RunHistory.jsx` | All 6 changes |
| `webui/src/api.js` | Probably nothing — `relTime` already exists |

Backend (`src/webui/main.py`) needs no changes — already returns `started_at`, `ended_at`, `summary.space_saved_mb`. Duration computed client-side.

## Not doing

- Mode column (item 4) — clutter, library name is enough to know what happened
- Bulk delete (item 8) — no destructive actions on run history
- Card view toggle (item 9) — table view is nicer, keep it

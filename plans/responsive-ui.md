# Responsive Web UI

Make the web UI usable on phones, tablets, and narrow browser windows without touching the backend.

## Scope (agreed)

- Desktop-first, pure CSS + minimal JSX. No framework, no new deps, no CSS-in-JS.
- Target widths: down to ~360px (old phones) up to desktop. Two breakpoints:
  - `900px` — stack the two-column layouts, tighten topbar.
  - `640px` — mobile nav, smaller paddings/fonts, modal fill.
- Nothing backend-side changes: no API edits, no state changes, no polling changes.
- Keep the current look on desktop exactly as-is.

## Status

Implemented and verified live (8/1/2026).

- Pure CSS + minimal JSX. No backend changes, no new deps, no CSS-in-JS.
- `styles.css`: added `.table-wrap`, `.toolbar`, `.row2`/`.col-main`/`.col-side`, `.progress-row`/`.progress-*`, `.modal-panel.wide`, `.fixed-scroll`, and the 900px/640px breakpoints.
- Components: RunDetail (header wrapper, progress-row classes, toolbar, table-wrap + fixed-scroll), LibraryForm/Settings/LibraryDetail (row2 columns + header wrap), all table pages wrapped in `.table-wrap`, Schedules modal now `.modal-panel.wide`.
- Built in the container-bind source (host node approved for the build): `index-B5lEia63.js`, `index-Cy04FQQ5.css` in `src/webui/static/`.
- Verified with browser automation (iframe viewport emulation at 1280/1440/1920/900/768/640/375px across all pages):
  - Zero page-level horizontal overflow on every page at every width.
  - Desktop (≥900px) layout byte-identical: row2 side-by-side, no nav scroll, tables don't scroll.
  - 900px: topbar wraps (stats second row), row2 stacks to column.
  - 640px: nav becomes a horizontal scroll strip, modals fill width, dash-header/actions wrap.
  - 375px: nav strip scrolls, tables scroll within `.table-wrap` (fixed-layout tables scroll via `.fixed-scroll` min-width), progress rows lay out as label/filename line + full-width right-aligned time line, Schedule modal panel is full-width.
- Live Run Detail (run `0b7098…`) confirmed: grid stacks, progress rows wrap correctly mid-run.

## What's broken today

| Area | Problem |
|---|---|
| Topbar (Layout) | `.topbar` is a single horizontal flex with title + 6 nav links + CPU/GPU/temp stats. Below ~1100px the stats and nav overflow and get clipped. `.topbar-stats` is `flex-shrink:0` and never hides. |
| Tables | Dashboard (9 cols), Run History (8), Schedules (7), LibraryDetail runs (7), Errors (5), RunDetail results (4 fixed cols). No horizontal scroll, no nowrap, so columns squash into unreadable blobs on narrow screens. |
| Two-column shells | LibraryForm, Settings, LibraryDetail, and RunDetail's `.run-detail-grid` all use inline `display:flex; flex:3` + `flex:1`. They never stack. Inline styles can't be overridden from `styles.css` without `!important`. |
| RunDetail progress rows | Progress bars use inline `minWidth` spans (50/82/140/150px) inside `display:flex` rows — the percent/time text overflows and the filename ellipsis loses its `flex:1`. |
| Modals | `.modal-overlay` has `padding:80px 20px` and `.modal-panel` is capped at 460–520px. On phones the panel is tiny and top-aligned far down. |
| Page headers | `.dash-header` puts `h2` + all actions on one line. LibraryDetail has 5 actions (Run/Live, Stop, Recent, Edit, Delete) — wraps/clips badly. |
| Dashboard stats | `.stats-grid` is one flex row, `gap:32px`, 6 blocks. Overflows below ~700px. |
| Filter inputs | `.filter-input` and `.run-filter` are fixed width (200px / auto) with `margin-left:8px` — Run History's two selects + title overflow. |
| Actions in tables | `.cell-actions` is `white-space:nowrap`; Schedules rows have 4 buttons (Enable, Run now, Edit, Delete) that eat the whole row width. |
| Fixed-layout tables | RunDetail's processed-files table and ErrorList use `style={{ tableLayout: 'fixed' }}`. With fixed layout the table never grows past the container, so a scroll wrapper alone won't scroll it — the file/error columns just squash. |
| Long paths / mono values | `.path-item` (media paths) and `.detail-row .value` (ffmpeg path, config path, long encode values) have no `word-break`/`overflow-wrap` — long paths overflow the screen on phones. |
| iOS zoom-on-focus | All inputs/selects/textareas are 13px. iOS Safari auto-zooms the page when focusing an input under 16px — every form field becomes a zoom jump on iPhone. |
| RunDetail header wrapper | RunDetail (line ~285) has the same nested inline-flex `h2 + actions` wrapper that LibraryDetail has; the plan only called out LibraryDetail. |
| Touch scrolling | `.table-wrap` and `.nav` need `-webkit-overflow-scrolling:touch` or iOS momentum scroll feels broken. |

## Approach

Desktop-first. `index.html` already has the viewport meta tag — good, nothing to add there.

Two CSS moves fix most of it:

1. **Horizontally scrollable tables.** Data-heavy tables shouldn't be redesigned into cards. Wrap content tables in `overflow-x:auto` so rows scroll sideways instead of squashing. Done with a `.table-wrap` utility class (JSX adds the wrapper), and for tables without one, a media rule that makes `th/td` nowrap so they scroll naturally.
2. **Utility classes for the flex rows that currently use inline styles.** The inline styles in RunDetail and the form pages are the only real blocker. Move the repeating ones to classes:

```css
.row2 { display:flex; gap:28px; align-items:flex-start }          /* form shell: flex:3 + flex:1 */
.row2 > .col-main { flex:3; min-width:0 }
.row2 > .col-side { flex:1; min-width:0 }
.progress-row { display:flex; align-items:center; gap:8px }        /* RunDetail progress rows */
```

Then the media queries can flip them:

```css
@media (max-width:900px){
  .row2 { flex-direction:column }           /* stack side below main */
  .run-detail-grid { flex-direction:column }
}
```

## Changes by file

### `webui/src/styles.css`

Append a responsive section (keeps desktop rules untouched):

- `@media (max-width:900px)`:
  - `.row2 { flex-direction:column }`
  - `.run-detail-grid { flex-direction:column }` (the component keeps its inline `display:flex`; column override works because it only changes direction)
  - `.topbar { flex-wrap:wrap; height:auto; padding:0 12px }`
  - `.topbar-stats { order:3; width:100%; justify-content:flex-start; padding:6px 0 }` (second row for stats, scrolls if needed)
  - `.stats-grid { flex-wrap:wrap; gap:20px }`
  - `.dash-actions { flex-wrap:wrap; gap:8px }`
  - `.filter-input { width:140px }`
  - Tables: `th,td { white-space:nowrap }` so wide tables scroll instead of squeezing. `.table-wrap { overflow-x:auto }` already applied in JSX where needed.
- `@media (max-width:640px)`:
  - `.content { padding:12px }`
  - `.modal-overlay { padding:16px 12px }`, `.modal-panel { max-width:100% }`
  - `.topbar-left { flex-wrap:wrap }`; `.nav { order:3; width:100%; overflow-x:auto; -webkit-overflow-scrolling:touch }` — nav becomes a single horizontally-scrollable strip under the title; no hamburger, no JS.
  - `.topbar-stats .stat-item { font-size:9px; padding:2px 6px }`
  - `.cell-actions { white-space:normal }` so Schedules action buttons wrap instead of forcing row width.
  - `.progress-row { flex-wrap:wrap }` and the inline `minWidth` on RunDetail spans gets relaxed via `.progress-meta { min-width:0 !important }` — see RunDetail changes; prefer the class swap so we don't need `!important`.
  - `.stat-block .num { font-size:20px }`
  - `h2 { font-size:14px }`
  - **Inputs get `font-size:16px`** (`input, select, textarea`) — iOS Safari only zooms on focus when the font is under 16px; this one rule kills the phone zoom-jump. Side effect: slightly larger inputs on mobile, which is the correct mobile pattern anyway.
  - **Fixed-layout tables**: `.libs-table[style*="table-layout"] { table-layout:auto }` is too fragile to inline styles — instead give those two tables (RunDetail processed-files, ErrorList) a `min-width:640px` inside their `.table-wrap` so the fixed layout is kept but the wrapper scrolls it. Simpler and predictable.
  - **Long values**: `.path-item, .detail-row .value { overflow-wrap:anywhere }` (word-break for the mono paths), so `/mnt/media1t/...` style paths wrap instead of overflowing.
  - `.table-wrap, .nav { -webkit-overflow-scrolling:touch }` for iOS momentum.

### `webui/src/components/Layout.jsx`

- Wrap the nav `<ul>` (or let CSS handle it — try CSS-only first: `.topbar-left{flex-wrap:wrap}` + `.nav{width:100%;overflow-x:auto}` at 640px. If the title and nav wrap cleanly, no JSX change needed).

### `webui/src/components/RunDetail.jsx`

- Replace inline `style={{display:'flex',...}}` progress rows with `className="progress-row"`.
- Replace the fixed `minWidth` spans with `.progress-meta` (still gives the time/percent a stable slot on desktop, but lets it shrink on mobile).
- Keep `flex:1`/`minWidth:0` on `.run-detail-left/.run-detail-right` — already there via the grid class, just verified by the column flip.
- The processed-files table goes inside `.table-wrap` **with `min-width:640px`** (it's `tableLayout:fixed`, so the wrapper needs the table to be wider than the screen to scroll). Same for its header filter row (`filter-input` + 3 buttons) — give it `.toolbar { display:flex; flex-wrap:wrap; gap:8px }` (reuse for Run History's header too).
- Drop the nested inline-flex `h2 + actions` wrapper (line ~285) to a plain `dash-header` so the actions wrap on mobile.

### `webui/src/components/LibraryForm.jsx` / `Settings.jsx` / `LibraryDetail.jsx`

- Swap the top-level `<form style={{display:'flex',gap:28}}>` / detail `<div style={{display:'flex',gap:28}}>` for `.row2` and give the two children `.col-main` / `.col-side`. This is the "3:1" layout (Settings and LibraryForm already pass `flex:3`/`flex:1` inline; LibraryDetail passes `flex:3`/`flex:1` too).
- LibraryDetail's actions row: `dash-actions` wrap rule handles it; also drop the inline `display:flex;align-items:center;gap:16` on the h2 wrapper to let it wrap.

### `webui/src/components/RunHistory.jsx`

- Add `.table-wrap` around the table, and move the two `.run-filter` selects into a `.toolbar` flex so they wrap under the title on mobile.

### `webui/src/components/Dashboard.jsx`, `Schedules.jsx`, `ErrorList.jsx`

- Add `.table-wrap` around each `libs-table`. No other changes — the CSS rules do the rest.
- ErrorList is `tableLayout:fixed` — same `min-width:640px` inside `.table-wrap` treatment as RunDetail's results table.

### `webui/src/components/RecentRunModal.jsx`

- No changes needed; `.modal-panel` + `.form-row` wrap rules cover it.

## Rules / conventions to follow

- Desktop appearance must not change — only add rules at/under the breakpoints.
- Prefer swapping inline styles for classes over `!important`. `!important` allowed only as a last resort for the few inline styles we can't touch (e.g. RunDetail's `minWidth`), and it must be scoped tightly (`.progress-meta`).
- No hamburger menu, no JS-based responsiveness. Horizontal scroll for nav and tables is the chosen mobile pattern — it's honest and zero-risk.
- No new dependencies, no CSS framework.
- Keep `white-space:nowrap` off `.content` text generally; only table cells get it under the media query.

## Build & test

- Backend untouched, so no pytest changes needed. Run the existing suite to confirm nothing broke:
  `docker exec jellysqueeze python -m pytest src/test_convert.py -q`
- Rebuild the SPA in the container (per project rule, no npm on host):
  `docker exec jellysqueeze sh -c "cd /app/webui && npm run build"`
- Visual check with the browser automation at widths: 1440 (desktop, must be unchanged), 1024, 900 (breakpoint edge), 768, 640 (edge), 480, 375 (phone), 360 (old phone).
  - Check each page: Dashboard, New Library, Library Detail, Run History, Schedules, Errors, Settings, and a live Run Detail if a run is active.
  - Verify: topbar wraps/scrolls without clipping, tables scroll horizontally, two-column pages stack, modals fill width, action buttons wrap, progress rows don't overflow.
- `npm run build` output goes to `src/webui/static/`; the container serves the new bundle on restart-free reload only for the static dir — confirm the static file is picked up (it is served from the bind-mounted `/app`).

## Out of scope / notes

- No layout redesign at any width (no card-ifying tables, no drawer nav). Tables scroll, columns stack.
- No print stylesheets.
- No RTL support.
- No backend/API changes; scheduler, MCP, and convert logic untouched.
- Topbar system stats stay visible (as a wrapped second row) rather than being hidden — they're useful on the dashboard. If it looks cramped at 640px we can hide the TEMP stat there; decide during the visual pass.
- Nav scroll strip is a deliberate trade-off over a hamburger: it needs no JS and no menu state.

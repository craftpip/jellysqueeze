# Settings Checkbox Layout + Panel Auth (Login/Logout) Verification

Scope agreed: fix the squished "Keep original backup" checkboxes on the Settings page, and verify the panel-auth login/logout flows with and without a password set. The panel-password.md plan already shipped auth; this plan records the UI fix and the end-to-end login/logout test work requested on 2026-09-18.

## 1. Bug & root cause

On Settings → Advanced, the two checkboxes ("Clean temp files before scan" and "Keep original backup") rendered with checkbox + label + hint all crammed onto one horizontal line in each column, and the two columns felt squished together.

Cause: `.form-row .field.checkbox` in `webui/src/styles.css:64` sets `flex-direction: row`, so the `<Hint>` block element became an inline flex item right after the label. At narrow widths the hint touched the label and the columns had no breathing room.

## 2. Fix (minimal, scoped)

- `webui/src/styles.css` — added a scoped variant for stacked checkbox fields:
  ```css
  .form-row .field.checkbox.stacked{flex-direction:column;align-items:flex-start;gap:4px}
  .form-row .field.checkbox.stacked .ck-line{display:flex;align-items:center;gap:6px}
  ```
  The existing `.form-row .field.checkbox` row layout is untouched, so the Schedules modal's `.checkbox.checkbox-input` ("Enabled") still renders input+label in a row.
- `webui/src/components/Settings.jsx` — both checkbox fields now use `className="field checkbox stacked"` with the input+label wrapped in a `.ck-line` div; the `<Hint>` sits below on its own line.

Rebuilt the SPA (`npm run build` → `src/webui/static/assets/index-CoBl1QXQ.css`, `index-CHZIfWDL.js`). The running `jellysqueeze` container serves static from the bind mount, so it picked the new build up immediately.

## 3. Layout verification (browser, live app)

Checked geometry via CDP on the Settings page (Advanced expanded) at viewport widths 1600 and 1024:

| Position | Before | After |
|---|---|---|
| Hint placement | same line as label (6px gap, cramped) | own line below the checkbox row |
| Checkbox+label alignment | inline, vertical center | aligned on `.ck-line` row, 6px gap |
| Two columns @1024 | 353px each, hint touching texts | 353px each, clean two-line layout |

No login screen involved — this instance runs with no `WEBUI_PASSWORD` (`.env` line 20 commented).

## 4. Panel auth verification — WITHOUT password (live instance at :9238)

| Check | Result |
|---|---|
| `GET /api/auth-status` (no cookie) | `{"password_set":false,"authenticated":true}` — PASS |
| `GET /api/config` (no cookie) | 200 — PASS |
| `GET /api/config` (bogus cookie) | 200 (auth ignored when disabled) — PASS |
| `POST /api/login` (any password, JSON) | 401 (no password configured, nothing matches) — PASS |
| `POST /api/logout` | 200, clears cookie — PASS |
| Browser loads `/#/settings` | App shell renders directly, no `.login-screen` — PASS |

## 5. Panel auth verification — WITH password (isolated temp instance)

Method: started a throwaway `media-auth-test` container from `jellysqueeze:nvidia` on the `navigator_default` network, mounting the current `src/` from `/www1/.tmp-media-auth-test` with `WEBUI_PASSWORD=testpass123`. Fully isolated (own config/state — no config.yml, no schedules, no shared SQLite). Removed after testing.

### 5a. API-level (20/20 PASS)

- `auth-status` no cookie → `password_set:true, authenticated:false`
- Protected endpoints (`/api/config`, `/api/env`) no cookie → 401
- Login wrong / empty password → 401
- Login correct → 200, `Set-Cookie: jellysqueeze_session=<exp>.<hmac>` with `HttpOnly`, `SameSite=Lax`, `Path=/`, 30-day Max-Age
- `auth-status` with cookie → `authenticated:true`; `/api/config` with cookie → 200
- `GET /api/env` never returns `WEBUI_PASSWORD`
- Tampered cookie signature → 401; expired cookie → 401
- `POST /api/logout` → 200; after logout, no-cookie requests → 401 and `auth-status` → `authenticated:false`
- `/` (login page, static) loads without auth → 200
- Unauthenticated `/api/ws/{run_id}` → rejected close code 1008

Note: logout is stateless (cookie-delete only). Re-sending a previously-issued token still authenticates — expected by the panel-password.md design; a browser cannot do this because logout deletes the cookie.

### 5b. Browser login/logout flow (real Chrome via CDP, 6/6 PASS)

1. Load `/#/` → login screen appears (`.login-screen`), no nav — PASS
2. Submit wrong password → stays on login, shows "Invalid password" — PASS
3. Submit `testpass123` → app shell renders (Dashboard + nav) — PASS
4. Page reload → still logged in (session cookie persisted) — PASS
5. `fetch('/api/logout', {method:'POST'})` → 200 `{logged_out:true}`, cookie cleared — PASS
6. Page reload → back at login screen — PASS

## 6. Regression

`docker exec jellysqueeze python -m pytest src/test_convert.py -q` → 65 passed (includes the auth testclient suite).

## 7. Environment artifacts

- Live app stays without a password (`.env` `WEBUI_PASSWORD` untouched).
- Temp container `media-auth-test`, temp mount dir `/www1/.tmp-media-auth-test`, and its window-session bonus: none remain.
- No logout UI button was added — per panel-password.md the sign-out control is a pending decision; the logout *process* is verified via the API.

## 8. Sign-out button (added 2026-09-18)

After a password was set (`WEBUI_PASSWORD=asdasdasd`), added a topbar "Sign out" button shown only when the panel password is configured:

- `webui/src/App.jsx` — `auth` state now tracks `passwordSet` from `GET /api/auth-status`; passed to `<Layout passwordSet={...}>`.
- `webui/src/components/Layout.jsx` — renders `Sign out` (`.link-btn.signout`) in the topbar only when `passwordSet`; `signOut()` calls `POST /api/logout` then `window.location.reload()` so the gate re-runs and shows the login page.
- `webui/src/styles.css` — `.topbar .signout` (12px, muted, red on hover).

Verified in a real browser (current build `index-CsVIxS2f.js` / `index-BhB1nyMJ.css`):
- **Password set (live app, password `asdasdasd`):** login → app shell with "Sign out" visible in topbar → click → login screen returns — PASS.
- **No password (isolated temp instance):** app loads directly, no login screen, "Sign out" NOT rendered — PASS.
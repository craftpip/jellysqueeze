# Web UI Panel Password

Add an optional password to the JellySqueeze web panel. The password lives **only** in `.env` (`WEBUI_PASSWORD`); it is never shown or edited from the UI.

## Behavior (agreed)

| `WEBUI_PASSWORD` in `.env` | Result |
|---|---|
| empty / missing | Panel is unauthenticated. No login page is ever rendered. All endpoints behave exactly as today. |
| set | A login page is shown instead of the app until the correct password is entered. All `/api/*` endpoints and the run WebSocket require a valid session cookie, otherwise they return 401 / close the socket. |

Rules:
- The password is stored in `.env` only. It is **not** returned by `GET /api/env` and **not** accepted by `POST /api/env` (not in the `accepted` key list), so the Settings page can never read or write it.
- `save_env()` preserves unknown `.env` lines, so `WEBUI_PASSWORD` survives Settings saves untouched.
- The panel password is unrelated to MCP: `/mcp/*` keeps its own `JELLYSQUEEZE_MCP_API_KEY` auth and is out of scope.

## Auth mechanism

Stateless signed cookie, no server-side session store:

- Cookie name: `jellysqueeze_session`
- Value: `<expiry_epoch>.<hmac_sha256_hex>` where the HMAC key is the panel password itself.
- On login: constant-time compare of the submitted password (`hmac.compare_digest`) against the env value; on success emit cookie with `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age=2592000` (30 days).
- On every request: recompute the HMAC from the cookie payload; accept only if signature matches **and** expiry is in the future.
- Property: because the HMAC key is the password, changing `WEBUI_PASSWORD` in `.env` immediately invalidates all existing sessions. No server state, survives container restarts.
- Password is read lazily via a helper (`_panel_password()`) so tests can toggle it via monkeypatch and no import-order surprises occur (`.env` is already loaded by convert.py's `load_dotenv()` at import time).

## Backend changes — `src/webui/main.py`

1. New auth helpers (module level):
   - `_panel_password()` → `os.getenv("WEBUI_PASSWORD", "")`
   - `_auth_enabled()` → `bool(_panel_password().strip())`
   - `_make_session_token(now)` / `_session_valid(token)` — build and verify the signed cookie.
   - `_authenticated(request)` → `True` when auth disabled, else validates the cookie.
2. New always-open endpoints:
   - `GET /api/auth-status` → `{password_set: bool, authenticated: bool}`. `authenticated` is `true` when `password_set` is false.
   - `POST /api/login` → body `{password}`. Wrong/empty → 401. Right → sets the cookie, returns `{authenticated: true}`.
   - `POST /api/logout` → deletes the cookie.
3. HTTP middleware (`@app.middleware("http")`): for every request whose path starts with `/api/` and is not `auth-status`/`login`/`logout`, and only when `_auth_enabled()`, respond 401 `{"detail": "authentication required"}` when the cookie is missing/invalid. `/mcp/*`, static assets, `/`, and the SPA fallback stay open (the login page must load without auth).
4. WebSocket `api_ws()`: when `_auth_enabled()` and `websocket.cookies.get("jellysqueeze_session")` is invalid, accept then immediately close with code `1008` (or reject before accept) instead of streaming run output.
5. `GET /api/env`: add `WEBUI_PASSWORD` to the never-returned list; `POST /api/env`: leave `WEBUI_PASSWORD` out of `accepted`.

## Config changes — `.env`

- Append a commented example (default off):
  ```
  # ── Web UI panel password (leave empty for no authentication) ──
  # WEBUI_PASSWORD=
  ```
- Real value goes in unpcommented: `WEBUI_PASSWORD=secret`.
- Applying a change requires recreating the container (compose injects `env_file` at container start): `docker compose up -d --force-recreate`.

## Frontend changes — `webui/`

1. New `webui/src/components/Login.jsx`:
   - Centered card (reuse existing theme; small CSS additions in `styles.css`).
   - Password field + submit button, inline error on 401 ("Invalid password").
   - On success calls the parent's re-auth callback.
2. `webui/src/App.jsx` — gate the whole app on `GET /api/auth-status`:
   - `loading` → rendering a spinner (no app shell yet).
   - `!password_set || authenticated` → render `<Routes>` exactly as today.
   - otherwise → render `<Login>` (no nav, no admin shell).
   - After login success, re-run the status check and render the app.
3. `webui/src/api.js` — no credential change needed: same-origin `fetch` and WebSocket already send cookies.
4. Optional (decision pending): small "Sign out" link in the topbar calling `POST /api/logout` then re-running the gate. **Status (2026-09-18): ADDED.** `Layout.jsx` renders a "Sign out" button in the topbar only when `passwordSet` is true (prop from App.jsx's `/api/auth-status`); it calls `POST /api/logout` then `window.location.reload()` so the gate re-runs and shows the login page.

## Tests — `src/test_convert.py`

Use `fastapi.testclient.TestClient` (httpx is already a dependency). Tests must monkeypatch env via `_panel_password`/`_auth_enabled` or `os.environ`:

1. No password → `GET /api/auth-status` returns `{password_set: false, authenticated: true}`; a protected endpoint (e.g. `/api/config`) returns 200 with no cookie.
2. Password set → `auth-status` returns `{password_set: true, authenticated: false}` without cookie; protected endpoint returns 401.
3. Password set → `POST /api/login` wrong password → 401; correct → 200 + session cookie; a follow-up request with the cookie returns 200 and `auth-status` reports `authenticated: true`.
4. Tampered cookie (corrupt signature) and expired cookie → 401.
5. `GET /api/env` response contains no `WEBUI_PASSWORD` key.
6. `/api/ws/{run_id}` closes with 1008 when unauthenticated and auth is enabled (TestClient websocket).

Existing 46 tests must keep passing: `docker exec jellysqueeze python -m pytest src/test_convert.py -v`.

## SPA rebuild

`Login.jsx` + gate changes require rebuilding the SPA. Per AGENTS.md, run the build inside the container (whole repo is bind-mounted, output lands in `src/webui/static/`): `docker exec jellysqueeze sh -c 'cd /app/webui && npm run build'` then restart.

## Verification

1. `pytest` all green.
2. `.env` without password → no login page; app loads directly; API untouched.
3. Add `WEBUI_PASSWORD=test123`, `docker compose up -d --force-recreate` → login page shows; `/api/config` without cookie → 401; wrong password rejected; correct password loads the app and all pages work (Dashboard, runs, run-detail live WS streaming).
4. Settings page neither shows nor overwrites the password (env endpoint contract + a Settings save round-trip).
5. Delete the password from `.env`, recreate container → login page is gone again.

## Edge cases / decisions

- **Privileged actions from already-open browser state:** cookie is HttpOnly; 401s on API force the SPA gate on the next page load even if the login page was skipped mid-session.
- **Restart:** sessions survive (stateless cookie) unless the password changed.
- **Whitespace-only password** is treated as "no password" (matching `.strip()`).
- **MCP `/mcp/*`** untouched (own API-key auth). Call this out explicitly in review.

## Out of scope

- MCP auth changes.
- Per-user accounts / roles — single shared panel password only.
- Rate-limiting / lockout on failed logins (internal-network tool; can be added later if wanted).
- Sign-out UI button — was pending; added 2026-09-18 (see "Frontend changes" §4).
# Parallel workers UI fix plan

## Problem

With `workers: 2` on the Shows R library, the run-detail page breaks:

1. Terminal output spams duplicate progress-bar lines (`[██░░...] 89/579 ...`).
2. Per-file encoding progress does not display properly for 2 files.
3. Result events are lost — files stay stuck at "Finalizing 99.5%" and never resolve.

## Evidence

From run `c2cecc9947b747e189c9eaa909cae229` (launched with `--library "Shows R" --workers 2 --json`):

- **48 unparseable stdout lines** in the first 15s. Sample:
  `{"type": "run_status", ...}{"type": "result", ...}` — two JSON objects concatenated on one line (newline lost).
- **215 progress-bar lines** to stderr in 15s; 197 in a 20s window while 2 files were encoding. Bars appear twice per completed file (same count printed twice).
- **Empty stdout lines** (`data: ""`) — byproduct of interleaved writes.
- During encode of 2 files: `progress=161, corrupt=12, empty=12` in a 20s WS capture. ~7% of events corrupted/dropped.
- **Data loss proven**: log records `FAIL: KonoSuba - S01E09.mkv :: duration_mismatch` and `FAIL: KonoSuba - S02E02.mkv :: duration_mismatch`, but **neither FAIL appears in the run's parsed results**. UI showed both files stuck at "Finalizing 99.5%".

Note: the `duration_mismatch` failures themselves are the pre-existing known issue (see AGENTS.md, Known Issues). This plan is about the UI/protocol bugs; it must ensure FAIL results are no longer lost so those show up in the UI.

## Root causes

### 1. `emit_json()` is not thread-safe — corrupted JSON lines (data loss)

`src/convert.py:422-424`

```python
def emit_json(type_: str, **data):
    if JSON_MODE:
        print(json.dumps({"type": type_, **data}, default=str), flush=True)
```

`print()` performs **two writes** (content, then newline). With parallel workers, worker threads call `emit_json` concurrently (progress events, `run_status` checking). Writes interleave:

- thread A writes `{jsonA}`, thread B writes `{jsonB}`, A writes `\n`, B writes `\n`
- result: one line `{jsonA}{jsonB}` + an empty line

Consequences:
- `RunManager._try_parse_json` (runner.py:163-180) fails to parse → `result`/`summary` events **dropped**.
- Frontend RunDetail WS handler also fails to parse → event dropped.
- The 500-line ring buffer fills with bars (root cause 2), pushing real events out of the replay buffer too.

### 2. Parallel branch renders terminal bars even in JSON mode — terminal spam

`src/convert.py` parallel branch (`workers > 1`), lines 2338-2349 and 2405-2407:

- `draw_progress_bar(...)` initial call (2338) — unconditional.
- `progress_ticker` thread (2340-2349) — starts and redraws every 0.5s whenever `progress_changed` is set, **even in `--json` mode**.
- `draw_progress_bar(...)` per completed file in the `as_completed` loop (2405-2407) — unconditional.

The sequential branch (2042-2092) correctly guards these with `if JSON_MODE:` (2076-2092). The parallel branch has no such guard.

Every bar line goes to stderr → runner broadcasts over WS and appends to both ring buffers → frontend `setLines` per line. This is the spam + buffer flood + UI churn.

The doubled bars are `draw_progress_bar` from the ticker + from the `as_completed` loop firing for the same completion.

### 3. `print_progress()` writes a bar line via `log.info` even in JSON mode

`src/convert.py:175-194` — `print_progress` calls `log.info(f"[{bar}] ...")` plus `emit_json("overall_progress")`.

- Sequential JSON mode: called **per file** (lines 2107, 2116, 2131, 2144, 2200) → one bar log line per file.
- Parallel JSON mode: called every 5s (2410-2413).

Duplicates the `draw_progress_bar` line and adds noise.

### 4. Ring/terminal buffers flooded with bar lines

`src/webui/runner.py:131-154` — every stderr line (including bar spam) is appended to `_buffer` (500) and `_terminal_buffer` (500) and broadcast. Bar spam evicts `run_status`/`result`/`progress` events from the buffer replayed to clients on WS connect.

### 5. Frontend re-renders on every stderr line

`webui/src/components/RunDetail.jsx:83-114` — every non-JSON stdout/stderr line triggers `setLines(prev => [...prev, d].slice(-200))` → new 200-element array + full terminal re-render per message. During floods this is hundreds of state updates/sec → "UI breaks".

Also `result` events are ignored on WS (RunDetail.jsx:80-127 only handles `progress`/`run_status`/`run_folder`); the processed-files table and green run-progress bar only update via the 2s HTTP poll.

## Fix plan

### Fix 1 — `convert.py`: atomic, locked `emit_json`

Add a module-level lock and write the full line in a single write call:

```python
_emit_lock = threading.Lock()

def emit_json(type_: str, **data):
    if not JSON_MODE:
        return
    line = json.dumps({"type": type_, **data}, default=str) + "\n"
    with _emit_lock:
        sys.stdout.write(line)
        sys.stdout.flush()
```

`convert.py` already imports `threading` (used at line 2044). Single write of a complete line eliminates interleaving; the lock also serializes multi-thread ordering.

- Fixes: lost `result`/`progress` events, files stuck at Finalizing, wrong summary counts.

### Fix 2 — `convert.py`: guard parallel branch bar machinery with `if not JSON_MODE`

In the parallel branch:

- Skip initial `draw_progress_bar(0, total, ...)` (2338) when JSON_MODE.
- Skip creating/starting `progress_ticker` (2340-2349) when JSON_MODE (mirror sequential branch's `if JSON_MODE: progress_done = True; ticker = None`).
- Skip `draw_progress_bar(...)` in the `as_completed` loop (2405-2407) when JSON_MODE.
- Keep the parallel final cursor-clear block (2415-2419) under `if not JSON_MODE`; it is a no-op once bars are disabled, but should remain grouped with terminal-only output.
- In the sequential branch, guard the unconditional trailing `sys.stderr.write("\n")` / flush (2208-2209) with `if not JSON_MODE`. Otherwise every JSON-mode run still broadcasts an empty stderr terminal line.
- Keep `print_progress` call (2410-2413) but see Fix 3.

### Fix 3 — `convert.py`: make `print_progress` JSON-aware

In JSON mode, skip the `log.info` bar line (the count is still visible via `emit_json("overall_progress")` and per-file `result` events). Keep the `emit_json("overall_progress")` call — it is cheap and unused-by-UI, harmless.

This removes per-file bar lines in sequential JSON mode and the periodic duplicate bar in parallel JSON mode.

### Fix 4 — `runner.py` (defensive hardening)

After Fixes 1-3, `convert.py` no longer writes bars to stderr in JSON mode, so the runner needs no structural change. Add cheap defense:

- In `read_stderr` (runner.py:141-154), skip broadcast/buffer for empty lines and terminal progress bars. Strip ANSI cursor-control sequences before detecting a line that starts with `[` and contains block chars: `draw_progress_bar()` emits an ANSI clear sequence before the bar, so checking the raw line only for `[` would miss those lines.
- This must remain stderr-only and narrowly targeted so genuine log messages are retained.

### Fix 5 — `RunDetail.jsx`: throttle + dedupe terminal lines

- Batch terminal appends: accumulate incoming lines and flush to `setLines` on a short interval (e.g. 200ms) instead of per message. This caps React re-renders during any residual flood.
- Dedupe consecutive identical lines (collapse repeats like the old bar spam into one entry).
- Keep MAX_LINES = 200.
- Flush and clear the pending-line timer/ref during effect cleanup so an old run cannot append terminal output after navigation.

### Fix 6 — `RunDetail.jsx`: handle `result` events over WS

Add a `p.type === 'result'` branch in the WS message handler (RunDetail.jsx:89-105) that upserts the result by file path in `results` (replace an existing same-file result, otherwise append). Do not blindly append: the initial status request, WebSocket replay buffer, and 2-second polling can all contain the same result.

This makes the processed-files table, OK/Skip/Fail counts, and green run-progress bar update instantly instead of waiting for the 2s poll, without temporarily inflating the counts. Remove the matching entry from `activeProgress` as part of the same terminal update as a defensive fallback if a preceding `progress(percent=null)` event was missed.

Keep the 2s poll as fallback (it also picks up state the WS may miss).

## Tests

Add to `src/test_convert.py` (keeps the current 20 green):

1. **`test_emit_json_is_thread_safe`** — set `convert.JSON_MODE = True`, monkeypatch `sys.stdout`, run N threads × M `emit_json` calls, then assert every captured line parses as valid JSON and count == N*M (no interleaving).
2. **`test_parallel_json_mode_emits_no_terminal_bars`** (requires_ffmpeg) — run `scan()` on a tmp dir with 2 tiny sample files, `workers=2`, `JSON_MODE=True`, capture stderr; assert no lines start with `[` + block-char bars and no unparseable stdout lines.
3. **`test_sequential_json_mode_emits_no_terminal_bars`** — same for `workers=1`.
4. **Frontend live-result verification** — with a real or browser-mocked WebSocket sequence, load an initial result, replay that same result, then poll it again. Assert it appears once, the counts remain correct, and a terminal result removes its active-progress entry. Also assert queued terminal lines flush once and do not update state after component cleanup.
5. Re-run full suite: `docker exec media-convert python -m pytest src/test_convert.py -v`.

## Verification

1. All tests pass.
2. Rebuild frontend if RunDetail.jsx changed: build `webui/` (`npm run build`) in the container or user's own environment (per AGENTS.md — do not run npm on host). Restart the container so static assets reload.
3. Start a 2-worker run on Shows R (or a smaller test library). Watch via WS:
   - `stderr:bar` = 0 and no empty stderr terminal events
   - corrupt/empty stdout lines = 0
   - progress events flow concurrently for 2 files (distinct file paths)
   - `result` events arrive over WS and match the log line count (no lost OK/SKIP/FAIL)
   - run summary FAIL count equals log FAIL count (KonoSuba S01E09/S02E02 style failures must show up)
   - terminal shows only real log lines, not bars
   - reconnecting the Run Detail page or the 2-second poll never duplicates processed-file rows or counts
4. Repeat a single-worker run to confirm no regression in sequential JSON mode.

## Related known issue (separate, out of scope)

`duration_mismatch` truncated outputs (reproduced again on KonoSuba S01E09/S02E02). Tracked in AGENTS.md Known Issues. Fixing the UI must not mask these; once `emit_json` is fixed, these FAILs will surface correctly in the UI.

# Live Run Investigation

This file tracks the active investigation into incorrect progress displays,
duplicate conversions, and lost completion/cache records. Update it until the
issue is resolved and verified with a controlled live run.

## Symptoms

- Some ffmpeg jobs encode normally but emit `out_time_* = N/A`, leaving the UI
  at `0:00` unless a frame-based fallback is used.
- A file that appeared completed, such as `Jurassic World Rebirth (2025).mkv`,
  can be selected for encoding again.
- Multiple conversion processes have appeared at once, including duplicate
  work against the same temporary output path.
- Before reload mode was removed, Uvicorn restarts dropped in-memory run
  managers and orphaned conversion processes.
- A progress fallback intended for Shows R briefly appeared in a Movies run
  that already had valid timestamp progress. This is a regression and confirms
  that fallback selection must not change behavior for timestamp-capable files.

## Evidence So Far

- Latest Shows R run `e6826d3f4e404bf9af5762a6e664aa7f` stopped at 440 processed files. Its only KonoSuba failure was `Season 01/KonoSuba - S01E09.mkv`: all normal, software-decode, and CPU attempts produced a decodable 1251.47s output while validation compared it against 1422.10s. The source has `format.start_time=170.629` and `format.duration=1422.097`; subtracting the positive start timestamp gives 1251.468s, so the output is complete and the validation calculation was wrong.
- `get_media_duration_seconds()` now normalizes positive container start timestamps. The focused converter suite and real-media codec suite passed together: `75 passed`.
- `To LOVE-Ru Darkness 2nd - S04E01.mkv` emits `frame=` values during NVENC
  encoding, while all `out_time_us`, `out_time_ms`, and `out_time` values are
  `N/A`.
- `Jurassic World Rebirth (2025).mkv` emits normal encoded timestamps.
- The current Movies event stream contains `position_seconds` and no frame
  count, confirming its normal timestamp progress path works.
- `To LOVE-Ru Darkness 2nd - S04E01.mkv` and `S04E12.mkv` report repeated
  unavailable output timestamps while their real `frame=` counters advance.
- `convert.py` historically saved `probe-cache.json` only after a whole scan,
  which loses skip records when a process stops before scan completion.
- The Web UI currently permits multiple runs to start without a process-wide
  ownership check; the shared progress and probe-cache files need safe
  multi-process persistence.
- Stopping a Web UI run signals only the `convert.py` parent. Its ffmpeg child
  can survive as an orphan (`PPID 1`). Starting Shows R again then launches a
  second encoder against the same `.__transcoding__.mkv` path. This is the
  primary observed duplicate-encoding cause.
- The current live evidence confirms the two progress paths are distinct:
  Movies emits advancing `position_seconds` with `frame_count: null`, while
  Shows R E12 emits advancing `frame_count` with `position_seconds: null`.
  The fallback must remain unavailable to any file that has ever emitted a
  valid timestamp.
- Controlled validation on 2026-07-30:
  - A Shows R run produced frame fallback data in the live UI:
    `Frame 20,273 / ~34,202` for timestamp-less `S04E08`.
  - A simultaneous Movies launch was rejected with HTTP `409`; only one Web UI
    conversion run can now exist at a time.
  - The existing `S04E02` cache entry remains persisted as
    `savings_too_small(0.4% < 10%)` with matching source metadata.
  - A controlled Shows R dry run reached the same file and logged
    `cache(savings_too_small(0.4% < 10%))`; it did not re-encode the file.
  - Stopping the controlled run terminated its active ffmpeg process. Docker
    `init: true` was added so stopped child processes are reaped rather than
    remaining zombies under Uvicorn PID 1.
- User reports that `Jurassic World Rebirth (2025).mkv` was converted before
  but has been selected again. Treat this as a persistence failure to verify,
  not as evidence that the media needs reconversion.

## Investigation Checklist

- [ ] Capture current run IDs, commands, process parents, and target files.
- [x] Capture current run IDs, commands, process parents, and target files.
- [x] Launch each runner subprocess in its own process group and stop the
  entire group so ffmpeg cannot survive a stopped run.
- [x] Reject a new run for a library that already has an active run.
- [ ] Audit shared writes to `var/_progress.txt` and `var/probe-cache.json`.
- [ ] Add focused tests for process-group stop behavior, duplicate run
  rejection, and locked merge persistence before relying on live media runs.
- [x] Keep timestamp progress for files that support it; use frame fallback
  only when a file has never reported a valid timestamp and repeatedly reports
  unavailable timestamps.
- [x] Run a controlled Shows R conversion and verify the frame fallback,
  duplicate-run rejection, stop behavior, and cached low-savings reuse.

## Current Constraint

Do not start further duplicate runs or stop active media work without explicit
user approval. Use the existing live runs as investigation evidence.

## SQLite Architecture

Database: `var/media-convert.sqlite3`

- Enable WAL mode, foreign keys, and a busy timeout so converter and Web UI
  processes can safely read/write concurrently.
- `completed_files`: accepted conversions keyed by `(path, option)`; replaces
  the mutable `var/_progress.txt` snapshot for done checks.
- `probe_cache`: skip decisions keyed by `(path, option)` with source size and
  mtime; replaces `var/probe-cache.json`.
- `runs`: one row per run with library, status, start/end timestamps, exit
  code, planned/processed counts, and saved bytes.
- `run_results`: ordered terminal file outcomes for each run. This supplies
  processed-file tables and exact stopped-run totals.
- `run_events`: ordered structured progress/status events for live reconnects
  and run-detail history. Raw text logs remain in dated log files.
- `schema_meta`: schema version and one-time legacy import markers.

Migration rules:

- Import existing `_progress.txt`, `probe-cache.json`, and `var/runs/*.json`
  once into SQLite.
- Do not delete or move the legacy files during migration.
- Use database rows for new writes and Web UI list/history queries after the
  migration is verified.

## SQLite Migration Results

- Combined progress is one run total across all configured paths. Shows R
  reported folder totals `165 + 17 + 579 = 761`, and the live UI rendered
  `338 / 761 (44.4%)` rather than a per-folder count.
- SQLite migration completed without deleting legacy files. Imported state:
  `929` probe-cache rows, `66` runs, `3,004` results, and `26,444` events.
- A new Movies R dry run was written and read back from SQLite with exit code
  `0`, `6` results, and `files_total: 6`.
- Library detail response: `4 MB / 808 ms` before SQLite summary queries and
  `12.5 KB / 30 ms` after.

> Create a full database architecture.

> Store the flow of the application, how the application works, all the quirks about the application. save every new thing about the application of how the progress is sent back what it uses what what logic it uses all the basic things about the application that you need to do as a developer

## User Requirements

> "Say in your investigation file exactly what I said. No sweetening here. We need to understand the graveness of the situation."

> "Save exactly what I said, word to word."

- Keep this file updated with investigation evidence and user-reported
  behavior until the issue is resolved.
- Do not regress progress behavior that already works in other libraries or
  files while fixing the Shows R timestamp-less files.
- Verify fixes against the real Web UI and a live run rather than relying only
  on code inspection or logs.
- It is acceptable to restart the container and reset active conversions to
  clear unsafe orphaned work before controlled verification.
- User reports that run history, library details, and other pages may now be
  inconsistent. Treat this as a broad regression: verify every affected UI
  page against its API data before adding more behavior changes.
- Re-read and update this investigation file before each fix and after each
  test so the active evidence and user observations remain in context.
- Record every relevant user observation here. The situation is operationally
  important: do not minimize or dismiss inconsistent run, cache, history, or
  library-detail behavior.
- Continue the investigation through evidence, minimal fixes, and verification
  without routine progress questions. Interrupt only for a destructive or
  irreversible action not already approved.

## User Messages (Verbatim)

> help me http://10.69.1.164:9238/#/run-detail/c50e2ede82d54268bbe4b8cba6ccdd59 , fix this page, please , its progress bar is not working its showing encoding and reaches 100% and disappaerars whereas teh encoding continues

> there is a aproblem in convert.py ?

> convert.py used to owrk before, it used to print progrsess for files that are being converted, now after adding to the web ui its all fucked up

> the convert.py is supposed to run convert fora library with multiple workers, when i run it with workers it shows progress for each working in percentage.

> it writable write it please using cmd

> fix it all

> To LOVE-Ru Darkness 2nd - S04E02.mkv
>  ist stuck at 99.5%

> why use vite ?

> ok do it in container

> To LOVE-Ru Darkness 2nd - S04E02.mkv
>  this file was done its doing it again ?

> there is cache issue

> http://10.69.1.164:9238/#/run-detail/9644b69fc1334e57a011e9744f1f09ca

> it had completed i swear

> http://10.69.1.164:9238/#/library-detail/Shows%20R is this stuck

> http://10.69.1.164:9238/#/run-detail/5952f86ef9dc4b52a65a2bc38e24cc7e its done

> Now if I stop this run and start again then it will be skipped right

> Check on yourself if that one is completed.

> http://10.69.1.164:9238/#/run-detail/9f42004f47f44f90a74802d85da73e0e does not show progress but http://10.69.1.164:9238/#/run-detail/9644b69fc1334e57a011e9744f1f09ca this one does why What is the difference in the files find out

> Take a screenshot with low quality and see what is happening there.

> Maybe you will need your eyes to function properly.

> http://10.69.1.164:9238/#/run-detail/2e181f4743b04f2dab0c60511f772bec This is the run I have started you can see there

> you can see with your own eyes it is encoding that same file that you just said it is finalizing and it is not showing any progress results

> Keep in mind, the progress thing works, and it works on other libraries, okay, on other files. The problem is only on this file.

> Keep in mind about the other things, don’t mess up the other things in solving this one.

> Always keep that in mind, okay? Please, I beg you.

> So now are the changes applied, you need to restart.

> http://10.69.1.164:9238/#/library-detail/Movies I am not able to start a new run. When I click on the button, nothing happens. takes me to a undefined page

> What the fuck are you doing?

> I told you to repeatedly test everything again and again, right?

> You may have messed up a lot of things also. Run history, everything is wrong. Everything is wrong. The library details, something is wrong. Something is wrong everywhere.

> Test everything, whatever you can. Over-test everything. Make sure you find the problem, investigate hard.

> You're not investigating enough.

> You are an efficient software developer. This is not the software that you have to make.

> You're not so talented, I think so.

> You don't even know how to start to solve the problem properly.

> Keep learning from your changes and keep updating the investigation file. Write it down in the investigation file to read the investigation file again. Update and also update the investigation file again and again and again. Write it in the investigation file so that the investigation file does not go out of your context.

> You don’t understand the importance of the situation here. Update this in your investigation file also. Anything I say, just update it in the investigation file. Just put it in the investigation file. You need to remember my input.

> There is always something to fix, you just keep fixing it. Just don't come back to me again. Just don't come back to me. Please keep working hard. There is no way you will come back to me. Write this down in the investigate for me also. In the agents also. Put it in your mind. Fucking.

> Say in your investigation file exactly what I said. No sweetening here. We need to understand the graveness of the situation.

> Save exactly what I said, word to word.

> In every above message, whatever I said, I saved everything word to word. All of my messages, every message that I sent above.

### Earlier Messages Omitted Above (Verbatim)

> yeah the progress is 99.% it was stuck, after long time it got skipped

> the percentage is wrong

> its not real

> is this file special ? it works on other files instantly i never had this problem

> :( hey i asked if th file is speical

> then why does it require encoding like that

> when this happens savings_too_small(0.1% < 10%)
>  its not stored in progress , every run its run

> why ?

> http://10.69.1.164:9238/#/run-detail/ac201ebdbdb04e669f3fd4f063b5f156 when i start run here i get error that bin address in use ? see its logs

> see in logs of this file http://10.69.1.164:9238/#/run-detail/ac201ebdbdb04e669f3fd4f063b5f156

> make convert. not start its own server

> remove server things from it

> .

> ewarER

> RESTART

> yss

> Jurassic World Rebirth (2025).mkv
>  this file was done its doing it again ?

> there is cache issue

> http://10.69.1.164:9238/#/run-detail/9644b69fc1334e57a011e9744f1f09ca

> it had completed i swear

> Over every research that you find.

> Restart the container if you want. Restart the container, reset to all the conversions and start the conversion again if you want.

> Test the caching also. I think it is not being cached. This Jurassic Park Reaper has been started again and again. I had already converted it. Add this in the Your Report investigation also.

> If you want, just run the code part by part. You don't have to do full code and then test. Run the main code, make a test file, bro. Do something like that. Do whatever you fucking want, just solve it motherfucker.

> I want it solved, that’s it.

> The problem is still there, it is still showing me encoding for that file. For which you just said that it is done including and finalizing. Can you do something like analyze it properly? I don't want to go in circles. When you have worked on it, go to the shows R folder and start a live run and see what it shows in the UI. And try to fix it that way. http://10.69.1.164:9238/#/run-detail/2e181f4743b04f2dab0c60511f772bec

> You are not able to figure it out.

> Can you research and save it in an MD file?

> Research what is happening, because something is really very bad and going wrong.

> Save your resource in a md file and carry that md file with you for your life. Until you solve this problem.

> What I was afraid for, that only happened. Now, what the calculation that you added is running for this run also. And this run was properly going on, it was showing the percentage perfectly, not like the other one.

> And second of all, "Jurassic World Rebirth" was already redone. Why is it going again and again?

> Now start working. Don’t come back to me. You don't deserve it.

> I think you should in organise the way you keep your run files I think this confusion is because of that. You should organize your run files in folders of the libraries.

> Do you think it is important?

## Newly Confirmed UI/History Faults

- The Movies library detail showed `Run Now` while a Shows R run was active.
  The backend correctly rejected the start with HTTP `409`, but the frontend
  looked only for `error`, ignored FastAPI's `detail`, and navigated to an
  undefined run page.
- Library detail previously considered only an active run for the current
  library. It needs to show the single global active run instead of presenting
  a start button that will be rejected.
- `RunManager` wrote run history upon every `summary` JSON event. A library
  run emits intermediate summaries per scanned root, so active runs appeared
  in history as prematurely ended records with `exit_code: null`. History must
  be written only after the converter process exits.
- Fresh-page verification after the library-detail fix: Movies shows
  `Shows R running` and `View Live` while Shows R is active; it no longer
  offers `Run Now` or navigates to an undefined run ID.
- Existing historical records are preserved, but `exit_code: null` is now
  labeled `Incomplete` and `exit_code: -15` is labeled `Stopped`, instead of
  rendering both as generic failures.
- After restarting with the revised runner, a controlled Movies R dry run
  completed with exit code `0` and appeared as a single `OK` history record.
  It did not create an intermediate active/ended history record.
- Processed-file listing defect: cached and already-done skips were counted but
  never emitted as `result` events; parallel worker completions also emitted
  no result events. Result events now cover every terminal file outcome. The
  run-detail table is newest-first and defaults to `OK` plus `FAIL`, with
  explicit Done, Failed, Skipped, and All filters. The active converter began
  before this backend change and must finish or be explicitly stopped before
  the new events can be exercised live.
- Historical run `25c223e05e574f89a692d30db69194f7` confirms the mismatch:
  terminal logging reached `[38/579]` and began encoding `S04E14`, but its
  stopped summary retained only the previous root's `17` skips. It contains
  only three recorded results (`S04E11`, `S04E07`, `S04E09`) because older
  cache skip paths did not emit result events. Future stopped summaries use
  actual terminal result events, not a per-root intermediate summary.
- Controlled interrupted-run test after the fix: `5eff5ce00c6146808a68cfd4dba9acd6`
  saved `244` emitted skip results and a stopped summary with
  `files_total: 244`, `skip: 244`. The result count and stopped summary match.

## Library Discovery Scheduling

- `--all` and multi-library `--library` runs now discover every selected
  library root before any encoding begins. Discovery emits each `run_folder`
  total and retains the resulting file list; the processing phase consumes
  those lists without walking the media trees a second time.

## Independent Library Runs

- Separate configured libraries must be runnable concurrently. A global run lock
  incorrectly made Movies display Shows R as its active run and removed Movies'
  start control. The runner now blocks only a duplicate library run; `--all`,
  Jellyfin-recent, and direct-path modes remain exclusive because their roots
  can overlap.
- The Dashboard now checks for a returned `run_id` before navigating, so a
  rejected start displays the API error instead of opening `run-detail/undefined`.
- New library runs write dated logs beneath `var/logs/library-<name>/`.
- Live verification after deployment: Shows R and Movies both run concurrently;
  Movies opens run `1bb1411c4c8b40d8907c4cbb2351b3fa` and displays only its
  own terminal output. A second Movies start returns HTTP `409` with
  `A conversion run is already active for this library`.

## Current Investigation

- User started a recent run and asked to check the error for a KonoSuba file.

### User Message (Verbatim)

> i did a recent run, check error in file konosuba

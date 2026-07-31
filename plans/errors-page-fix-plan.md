# Errors Page Fix Plan

**Status: complete (7/31/2026).** The code gap from the previous revision is now fixed: a post-encode validation failure advances to the next configured fallback instead of returning `FAIL` immediately, and confirmed-unrecoverable sources get a bounded failure cooldown. Both live-run verification items are also done — see items 5 and 7 below.

Previous status, kept for history: revised after live-run validation. The original fixes are deployed and unit-tested, but the claim that all nine files were fixed was not validated by a full re-encode. The current failures are real truncated outputs from corrupt Matroska inputs, not the earlier duration-header false positives.

## Live Validation

Validated against `http://10.69.1.164:9238/#/run-detail/c2cecc9947b747e189c9eaa909cae229`.

- Run `c2cecc9947b747e189c9eaa909cae229` was stopped after 23 seconds with `220 SKIP`, `1 FAIL`, and two active encodes terminated by the stop.
- Its terminal failure was `KonoSuba - S02E02.mkv`: `duration_mismatch(source=1421.01, output=1291.37)`.
- The immediately preceding run, `f8d7801a0cac4e2ea8ad67aa3e3d9de4`, recorded the same S02E02 result and a new failure for S01E09: `duration_mismatch(source=1422.10, output=1251.47)`.
- These output durations differ substantially from the earlier false-positive remux values (S01E09: `1375.89s`; S02E02: `1347.10s`). The packet-duration fallback correctly rejects the new outputs.
- Direct `ffprobe` of S02E02 reports repeated Matroska/EBML structural errors, including invalid EBML numbers, duplicate elements, and master-element boundary violations. This is source corruption, not a duration-header-only quirk.
- Failed temporary outputs are deleted by `convert_if_needed()` immediately after validation, so the encoder result cannot currently be inspected after a failure.

## What Is Confirmed

| Previous issue | Current state | Evidence |
|---|---|---|
| Inflated container-duration headers | Fixed for header-only disagreement | `_packet_durations_agree()` accepts matching real packet ends while the existing truncation test still rejects genuinely shorter output. |
| Header-only concat streams | Fixed as a stream-selection gate | `filter_dead_streams()` allows S01E09/S02E02 past `multiple_or_missing_video_streams`; S01E09 now reaches encode/validation. |
| Corrupt secondary AC3 tracks | Fixed as an all-or-nothing validation failure | Video decoding remains strict; copied-audio decode failures are warnings. This has not yet been verified by a completed live encode of all four Monster Musume files. |
| KonoSuba S01E09 and S02E02 | Not fixed | Both still create output that is 9-12% shorter than the source, well outside the 1% / 2-second tolerance. |

## Current Root Cause

S01E09 and S02E02 are no longer rejected because of their dead concat streams. They proceed to normal NVENC encoding, but their malformed Matroska structure causes a real loss of media timeline in the output. S02E02 has confirmed EBML parse errors; S01E09 needs the same source-level probe before treating both files as identical.

The converter's fallback attempts only cover ffmpeg process failures. `convert_if_needed()` marks the first exit-zero encode as `finished` and runs stream-signature and media validation afterward. A duration or decode validation failure therefore deletes the output and returns `FAIL`; it does not try software decode or CPU encoding. This is the remaining code-path gap.

## Remaining Work

1. ~~Add a focused regression test proving that a post-encode validation failure advances to the next configured fallback and only returns `FAIL` after every attempt is invalid.~~ **Done** — `test_validation_failure_advances_to_next_fallback`, `test_validation_failure_all_attempts_returns_fail` in `src/test_convert.py`.
2. ~~Move stream-signature and media validation inside the per-attempt loop in `convert_if_needed()`. On failure, remove that attempt's temporary output and continue to software decode, then CPU encode when available. Keep successful output replacement only after validation and savings checks pass.~~ **Done** — `validate_attempt_output()` runs inside the attempt loop via `convert_if_needed()`; on failure it deletes the temp output and tries the next attempt. Savings checks and `safe_replace()` still run only on the surviving output.
3. ~~Include the attempt name and measured source/output durations in the final error. This distinguishes a source-demux truncation from an encoder-specific failure on the Errors page.~~ **Done** — final errors read `validation_failed(cpu): duration_mismatch(source=1422.10, output=1251.47)`.
4. ~~Before deleting an invalid temporary output, record lightweight diagnostics: its stream signature, packet-end durations, and a summarized ffmpeg decode result. Do not retain the multi-gigabyte failed output by default.~~ **Done** — `record_invalid_output_diagnostics()` logs stream signature, source/output packet ends, and a decode summary before the temp file is deleted.
5. Run controlled conversions of S01E09 and S02E02 through normal, software-decode, and CPU paths. Confirm whether any path preserves the source's real video/audio packet ends. **Done** — run `df7193df0ba74ffca10576840dc290e1` (11:31 UTC, library Shows R) drove both files through all three attempts. Every attempt truncated at the same packet end (S01E09 `1251.47s`, S02E02 `1291.37s` vs source `1422.10s`/`1421.01s`) with clean decode of the truncated output (`decode: exit=0 ok`). Identical truncation across NVENC normal, software-decode, and libx264 CPU confirms source-level demux truncation, not encoder-specific failure.
6. ~~If all paths truncate, classify each source as unrecoverable and add a bounded failure cooldown keyed by source fingerprint and conversion options. This prevents repeat NVENC work until the source file changes.~~ **Done** — when every attempt fails validation, `record_failure_cooldown()` stores `(path, fingerprint, option, expires_at)` in the new `failure_cooldowns` SQLite table; repeat runs return `SKIP failure_cooldown(...)` until the TTL (`FAILURE_COOLDOWN_HOURS`, default 24) or the source fingerprint changes. Cooldown skips are never written to the probe cache so they stay bounded.
7. Complete live verification for the other seven original files: the three header-duration files and all four Monster Musume AC3 files. Mark each as `OK`, a meaningful `SKIP`, or a new explicit failure category. **Done** — the same 761-file library run returned exactly two `FAIL`s (the KonoSuba pair); all seven other files produced meaningful `SKIP`s (already converted / probe-cache hits), confirming no regression. Cooldown behavior also verified live: the 17:02 and 17:07 UTC runs logged `Failure cooldown active` for both KonoSuba files and skipped them instantly.

## Verification Criteria

- Unit suite: `docker exec media-convert python -m pytest src/test_convert.py -v` — 23 tests pass (includes the 3 new regression tests).
- A validation failure after a successful ffmpeg process invokes the next fallback instead of returning immediately. ✅ covered by `test_validation_failure_advances_to_next_fallback`.
- Genuine truncation remains a `FAIL`; header-only duration disagreement remains accepted when packet ends agree. ✅ existing `test_validate_output_media_*` tests still pass.
- Error records include the final attempted mode and measured durations. ✅ `validation_failed(<mode>): duration_mismatch(source=..., output=...)`.
- A repeat run does not repeatedly spend GPU time on an unchanged, confirmed-unrecoverable source. ✅ `failure_cooldowns` table + `FAILURE_COOLDOWN_HOURS`; cooldown skips are not probe-cached. ✅ Live-confirmed: 17:02/17:07 UTC runs skipped both KonoSuba files via active cooldown.

## Historical Notes

The earlier 61 error rows represent repeated failures across nine files, mostly before the deployed validation and dead-stream changes. They remain useful history but are not proof of the fixes. The new runs establish that the old `multiple_or_missing_video_streams` failures have transitioned into two separate, real truncation failures that need fallback-aware validation and source-corruption handling.

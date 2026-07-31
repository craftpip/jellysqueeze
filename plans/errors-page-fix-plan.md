# Errors Page Fix Plan

Merged from `failure-analysis.md` (single run `11848477a30043f288e1f97bd3d5dde0`, Shows_R, 579 files) + errors page data (checked 7/31/2026). Errors page shows **61 error rows total, but only 9 unique files across 3 error types**. The same files fail the same way on every run — each run re-encodes them and burns NVENC hours before failing again.

## Error Inventory

Library: `Shows R` — `/mnt/media3t/downloads/series-r/`

| # | File | Error | Occurrences | Type |
|---|---|---|---|---|
| 1 | KonoSuba/Season 01/S01E01.mkv | `duration_mismatch(source=1513.19, output=1479.16)` | 10 | Code |
| 2 | KonoSuba/Season 01/S01E07.mkv | `duration_mismatch(source=1422.10, output=1375.89)` | 10 | Code |
| 3 | KonoSuba/Season 01/S01E09.mkv | `multiple_or_missing_video_streams` | 8 | Code |
| 4 | KonoSuba/Season 02/S02E02.mkv | `multiple_or_missing_video_streams` | 10 | Code |
| 5 | KonoSuba/Season 02/S02E08.mkv | `duration_mismatch(source=1421.07, output=1347.10)` | 8 | Code |
| 6 | Monster Musume/Season 01/S01E01.mkv | `decode_validation_failed` (ac3 `aist#0:1`) | 3 | File + Code |
| 7 | Monster Musume/Season 01/S01E04.mkv | `decode_validation_failed` (ac3 `aist#0:2`) | 5 | File + Code |
| 8 | Monster Musume/Season 01/S01E07.mkv | `decode_validation_failed` (ac3 `aist#0:1`) | 4 | File + Code |
| 9 | Monster Musume/Season 01/S01E11.mkv | `decode_validation_failed` (ac3 `aist#0:1`) | 3 | File + Code |

All 9 files failed on every run between 7/30 6:55 AM and 1:33 PM (~7-10 runs each). Deterministic — never a one-off.

## Error Type 1: `duration_mismatch` (3 KonoSuba files)

Output is consistently **30-75s shorter** than source, with identical values on every run (e.g. E01 always 1479.16 vs 1513.19). ffmpeg exits 0, temp file exists, then `validate_output_media()` at `src/convert.py:1751` catches it and returns terminal FAIL.

Key detail: `validate_output_media()` runs **outside** the attempt loop (line 1751), so the software-decode and CPU fallbacks are never tried even though the attempts array (line 1513) supports them. A clean-exit-but-truncated output skips all fallbacks.

Root cause of the truncation itself is unknown yet — deterministic per-file values suggest ffmpeg drops frames or seeks wrong on these specific files, not random encoder failure. Same numbers every run = same output, so it's reproducible and testable.

### Fix candidates
- [ ] Move `validate_output_media()` and the savings/output-larger checks inside the attempt loop so a clean-exit but bad-duration output triggers the next fallback (software decode → CPU). Refactor: return validation outcome from the loop instead of `finished = True` at line 1707.
- [ ] Investigate one file manually (probe streams, run ffmpeg, check where output ends) to find if frames are dropped or duration metadata is wrong. Compare `ffprobe` duration of source vs sum of packet PTS.

## Error Type 2: `multiple_or_missing_video_streams` (2 KonoSuba files)

Guard at `src/convert.py:1366`:

```python
if len(vids) != 1:
    return None, "multiple_or_missing_video_streams"
```

`pick_primary_video()` at line 1369 can handle multiple video streams (picks default or first), but is never reached when `len(vids) > 1`. The guard only needs to reject `len(vids) == 0`.

### Fix candidates
- [ ] Change `len(vids) != 1` → `len(vids) == 0`. Verify with ffprobe on both S01E09 and S02E02 that stream layout is parseable.

## Error Type 3: `decode_validation_failed` AC3 (4 Monster Musume files)

Error text (addresses stripped):

```
[aist#0:1/ac3 @ ...] [dec:ac3 @ ...] Terminating thread with return code -1094995529 (Invalid data found when processing input)
```

`-1094995529` = `AVERROR_INVALIDDATA`. Happens during `validate_output_media()` decode pass (`src/convert.py:1205`):

```
ffmpeg -v error -xerror -i <output> -map 0:v? -map 0:a? -f null -
```

Audio is stream-copied from the source, so a bad AC3 frame in the source ends up in the output and the validation decode dies on it.

Notable detail: the failing stream is always a **secondary** audio track (`aist#0:1` = 2nd audio stream, `aist#0:2` = 3rd audio stream — S01E04 fails on stream 2, the rest on stream 1). Never the primary track. Suggests the source rips have one broken extra audio track (second language / commentary). Jellyfin plays the files fine because it doesn't hit that track.

### Verdict
Both. **File issue**: the source has an invalid AC3 audio track. **Code issue**: validation is all-or-nothing over every audio stream, and no fallback exists to drop the broken audio track.

### Fix candidates
- [ ] Probe each of the 4 files: `ffprobe -show_streams` — confirm the failing AC3 track is the secondary one and check if source decode of that track fails too (`ffmpeg -i file -map 0:a:N -f null -`).
- [ ] Fix A: validation only decodes streams that were re-encoded, or tolerate the known-bad track. Simplest: on decode_validation_failed, retry encode with the failing audio stream dropped (`-map` exclude it) or re-encoded instead of copied.
- [ ] Fix B (audio re-encode fallback): add an attempt variant that re-encodes audio (e.g. `-c:a aac`) instead of stream-copying. AC3 decode of invalid data then can't happen in validation... actually it still could if source track is corrupt — re-encode reads source too. So also need `-err_detect ignore_err` or drop track if re-encode fails.
- [ ] Alternative quick fix: validation decode with `-err_detect ignore_err` (or without `-xerror`) so a single bad audio frame doesn't kill the whole validation.

## Cross-Cutting Issue: repeated re-encode waste

Each run re-encodes all 9 files (KonoSuba E01 took ~1.5-2h per NVENC p4 attempt), fails, and the probe cache doesn't help because FAIL deletes the cache entry. 61 rows in ~7 hours = roughly 10+ hours of wasted GPU encodes on 7/30 alone.

- [ ] Option A: fix root causes above so fallbacks handle these files.
- [ ] Option B (defense-in-depth): cache FAIL outcomes with a cooldown (e.g. skip retry for N days) so known-bad files don't burn encode hours every run. Need a "don't retry before" marker in state DB or probe cache for FAILs.

## Verification steps

- [ ] `docker exec media-convert python -m pytest src/test_convert.py -v` after code changes
- [ ] Re-run library scan with the 9 files only, confirm they reach OK or a sensible SKIP instead of FAIL
- [ ] Check errors page after a run: expect 0 new rows
- [ ] Manual probe of one file per error type, command examples in the sections above

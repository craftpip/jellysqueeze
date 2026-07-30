# Failure Analysis — 6 Failed Files

Run `11848477a30043f288e1f97bd3d5dde0` (Shows_R library, 579 files).

## Failures

| # | File | Error | Type |
|---|---|---|---|
| 1 | KonoSuba S01E01 | `duration_mismatch(source=1513.19, output=1479.16)` | Code |
| 2 | KonoSuba S01E07 | `duration_mismatch(source=1422.10, output=1375.89)` | Code |
| 3 | KonoSuba S01E09 | `multiple_or_missing_video_streams` | Code |
| 4 | KonoSuba S02E02 | `multiple_or_missing_video_streams` | Code |
| 5 | KonoSuba S02E08 | `duration_mismatch(source=1421.07, output=1347.10)` | Code |
| 6 | Monster Musume S01E01 | `decode_validation_failed` (AC3 decoder crash) | File/ffmpeg quirk |

## Root Causes

### 1. `multiple_or_missing_video_streams` — Guard too strict

`src/convert.py:1363`:
```python
if len(vids) != 1:
    return None, "multiple_or_missing_video_streams"
```

`pick_primary_video()` at line 1366 is never reached when `len(vids) > 1`, even though it can handle multiple streams (picks default or first). The guard should only reject `len(vids) == 0`.

### 2. `duration_mismatch` — Validation outside attempt loop

The attempt loop at line 1510 tries: normal → software_decode → cpu (if `libx264` available).

If an attempt exits 0 but produces truncated output, `finished = True` is set at line 1704 and the loop breaks. Then `validate_output_media()` at line 1748 catches the mismatch and returns terminal FAIL. The CPU fallback is never tried.

The fix: move `validate_output_media()` into the attempt loop so a clean-exit but bad-duration output triggers the next fallback.

### 3. `decode_validation_failed` — AC3 stream-copy corruption

AC3 audio is stream-copied. `ffmpeg -xerror -i output -map 0:v? -map 0:a? -f null -` crashes on the AC3 decoder. Source plays fine in Jellyfin, so likely an NVENC + mkv muxing quirk with this particular AC3 stream. Harder to fix — might need `-c:a copy` validation bypass or a re-encode fallback for audio.

## Proposed Fixes

1. Change `len(vids) != 1` → `len(vids) == 0` in `build_ffmpeg_cmd()`
2. Move `validate_output_media()` and the savings/output-larger checks inside the attempt loop so fallback encoders are tried when validation fails after a clean ffmpeg exit

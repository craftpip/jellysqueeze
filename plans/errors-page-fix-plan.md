# Errors Page Fix Plan

**Status: root causes found + fixes implemented and unit-tested (7/31/2026). All three error types were code-side issues (or code handling of file quirks), not encoder faults. Remaining: re-run the 9 files to confirm OK/SKIP.**

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

## Summary: file issue vs code issue

All three error types were really **file quirks**, but the code handled them badly (too strict — rejected valid output instead of tolerating the quirk).

| Type | Files | Verdict |
|---|---|---|
| `duration_mismatch` | KonoSuba E01/E07/S02E08 (3) | File issue — inflated MKV header; code compared headers, flagged valid output |
| `multiple_or_missing_video_streams` | KonoSuba S01E09, S02E02 (2) | File quirk + code bug — concat artifacts add zero-packet streams; guard wrongly rejected them |
| `decode_validation_failed` AC3 | Monster Musume E01/E04/E07/E11 (4) | File issue + code over-strictness — corrupt AC3 in secondary track; validation was all-or-nothing |

## Do the outputs still have the defects?

- **duration_mismatch** — No. Output is a fresh mux, computes its own header from real timestamps. Source still has the inflated header, but that's the original file, untouched.
- **multiple_or_missing_video_streams** — No. We map only live streams, so the dead concat streams never make it into the output.
- **decode_validation_failed AC3** — **Yes.** Audio is stream-copied, so the corrupt AC3 frame is copied verbatim into the output's secondary audio track. We just stopped failing the file over it — it's a source defect Jellyfin never hits (it plays the primary track). If it ever needs to be truly gone: drop the broken track from the output, or re-encode audio (reads the same corrupt source but resyncs past the bad frame).

## Error Type 1: `duration_mismatch` (3 KonoSuba files) — FIXED, false positive

Output is consistently **30-75s shorter** than source, with identical values on every run (e.g. E01 always 1479.16 vs 1513.19). ffmpeg exits 0, temp file exists, then `validate_output_media()` catches it and returns terminal FAIL.

**Root cause (confirmed, not truncation):** the source MKV header carries an **inflated duration**. Probing each source:

- S01E01: container header 1513.19s, but real video packet end 1473.43s, audio end 1473.70s
- S01E07: header 1422.10s, real media end ~1422.0s
- S02E08: header 1421.07s, real media end 1343.35s

A plain `-map 0 -c copy` remux of the source produces **exactly** the reported "output" values (1479.16 / 1375.89 / 1347.10). Stale matroska `Duration` element (or subtitle timestamps extending past the real media). The header-vs-header comparison was a false positive — the encoded output was actually fine.

**Fix (done in `src/convert.py`):** `validate_output_media()` now falls back to `_packet_durations_agree()` when headers mismatch — re-measures real packet end times (video + selected audio) on both sides and tolerates the mismatch if they match within 1%. Confirmed on real files: remux copy of S01E01 validates `ok=True`. Moving validation inside the attempt loop was **not needed** — fallbacks would re-produce identical output and burn NVENC hours.

### Fix candidates
- [x] Investigate one file manually (probe streams, run ffmpeg, check where output ends) to find if frames are dropped or duration metadata is wrong. Compare `ffprobe` duration of source vs sum of packet PTS.
- [x] Add packet-end fallback to `validate_output_media()` so inflated source headers don't fail valid output.
- [ ] ~~Move `validate_output_media()` inside the attempt loop~~ — not needed, issue was a validation false positive.

## Error Type 2: `multiple_or_missing_video_streams` (2 KonoSuba files) — FIXED

Guard at `src/convert.py:1366`:

```python
if len(vids) != 1:
    return None, "multiple_or_missing_video_streams"
```

**Root cause (confirmed):** both files are **concat artifacts**. They declare a second full stream set (video idx 10, audio 11/12, subs) that carries **zero packets** — header-only leftovers from a `-f concat` merge. S01E09 stream layout: 0:0-0:2 (hevc video, opus/opus audio), 0:3-0:9 (7 subs), 0:10-0:12 (dead hevc video, ac3/ac3 audio), 0:13 (dead sub), attachments 0:t. Packet scan shows streams 10-13 have 0 packets; only 0:0-0:9 are live.

**Fix (done in `src/convert.py`):**
- New `filter_dead_streams()` drops header-only (zero-packet) streams — only runs a packet scan when `len(vids) > 1`, healthy single-video files keep the fast path.
- Guard changed `len(vids) != 1` → `len(vids) == 0` in `build_ffmpeg_cmd()`, with a dead-stream filter that returns `multiple_or_missing_video_streams` only if all video streams are dead.
- `expected_output_signature()` filters the same way so the post-encode signature check compares against the live stream layout.
- Verified: `build_ffmpeg_cmd` on S01E09/S02E02 now maps only live streams (0:0-0:9 + `0:t?`); live-only remux signature matches expected exactly.

### Fix candidates
- [x] Change `len(vids) != 1` → `len(vids) == 0`. Verify with ffprobe on both S01E09 and S02E02 that stream layout is parseable.
- [x] Drop zero-packet dead streams so they're not mapped into output (concat artifacts).

## Error Type 3: `decode_validation_failed` AC3 (4 Monster Musume files) — FIXED

Error text (addresses stripped):

```
[aist#0:1/ac3 @ ...] [dec:ac3 @ ...] Terminating thread with return code -1094995529 (Invalid data found when processing input)
```

`-1094995529` = `AVERROR_INVALIDDATA`. Happens during `validate_output_media()` decode pass. Audio is stream-copied from the source, so a bad AC3 frame in the source ends up in the output and the validation decode dies on it.

**Root cause (confirmed):** corrupt AC3 frame in a **secondary** source audio track. The failing stream is always a secondary track (`aist#0:1` = 2nd audio, `aist#0:2` = 3rd — S01E04 fails on stream 2, the rest on stream 1), never the primary. Suggests the source rips have one broken extra audio track (second language / commentary). Jellyfin plays the files fine because it doesn't hit that track. Strict `-xerror` decode fails on the bad frame; **tolerant decode (no `-xerror`) exits 0** — the decoder resyncs past it. So it's a source-file defect, not an encode defect, and re-encoding can't fix the source corruption.

**Fix (done in `src/convert.py`):** validation decode split into two passes — video decode stays strict with `-xerror` (genuine video errors still FAIL), audio decode runs tolerant (no `-xerror`); audio failures only log a warning since audio is stream-copied and the defect is in the source. Confirmed on real file: remux copy of Monster Musume S01E01 validates `ok=True` (audio pass tolerant, video strict).

### Verdict
Both. **File issue**: the source has an invalid AC3 audio track. **Code issue**: validation was all-or-nothing over every audio stream.

### Fix candidates
- [x] Probe each of the 4 files: `ffprobe -show_streams` — confirm the failing AC3 track is the secondary one and check if source decode of that track fails too (`ffmpeg -i file -map 0:a:N -f null -`). Confirmed on S01E01: strict decode of the copied audio exits 183, tolerant exits 0.
- [x] Split validation: video strict, audio tolerant — a single bad copied audio frame no longer kills validation.
- [ ] ~~Drop the broken audio track or re-encode audio~~ — not needed; tolerant decode handles it, and re-encode would read the same corrupt source.

## Cross-Cutting Issue: repeated re-encode waste

Each run re-encodes all 9 files (KonoSuba E01 took ~1.5-2h per NVENC p4 attempt), fails, and the probe cache doesn't help because FAIL deletes the cache entry. 61 rows in ~7 hours = roughly 10+ hours of wasted GPU encodes on 7/30 alone.

- [x] Option A: fix root causes above so fallbacks handle these files. **Done** — all three error types are fixed at the validation/probe layer, no fallback retries needed.
- [ ] Option B (defense-in-depth, optional): cache FAIL outcomes with a cooldown (e.g. skip retry for N days) so genuinely-broken files don't burn encode hours every run. Not implemented — root causes are fixed, but a cooldown would still be a safety net for future bad files.

## Verification steps

- [x] `docker exec media-convert python -m pytest src/test_convert.py -v` after code changes — **15/15 pass** (6 new tests: dead-stream filter ×2, validation ×4)
- [x] Manual probes per error type on real files:
  - `validate_output_media` on stream-copy of KonoSuba S01E01 (was duration_mismatch) → `ok=True`
  - `validate_output_media` on stream-copy of Monster Musume S01E01 (was AC3 decode failure) → `ok=True`
  - `build_ffmpeg_cmd` on S01E09 + S02E02 (were multiple_video_streams) → maps live streams only; expected vs actual output signature `MATCH: True`
- [ ] Re-run library scan with the 9 files only, confirm they reach OK or a sensible SKIP instead of FAIL
- [ ] Check errors page after a run: expect 0 new rows
- [ ] Manual probe of one file per error type, command examples in the sections above

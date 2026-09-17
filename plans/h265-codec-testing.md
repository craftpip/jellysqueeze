# H.264 / H.265 Codec Testing

## Goal

Prove that selecting H.264 or H.265 changes only the output video codec and
does not lose selected audio/subtitle tracks, truncate media, or incorrectly
replace the source file.

No finite fixture set can prove every driver and malformed media combination.
The test suite should be reproducible, run in the target container, and cover
the supported profiles on the hardware that is actually deployed.

## Media Sources

### Real video fixtures

Use the Jellyfin test-video catalog for public, CC BY-SA real-world video:

<https://repo.jellyfin.org/test-videos/>

Download a small checked-in manifest of URLs and SHA-256 checksums, not the
videos themselves. Initial downloads:

- `Test Jellyfin 1080p AVC 10M.mp4` - H.264 source above the normal conversion threshold.
- `Test Jellyfin 1080p HEVC 8bit 10M.mp4` - normal H.265 source.
- `Test Jellyfin 1080p HEVC 10bit 10M.mp4` - HEVC 10-bit decode/encode path.

Use MediaConch sample files only for MKV/container edge cases not reproducible
with ffmpeg:

<https://github.com/MediaArea/MediaConch_SampleFiles>

Use selected FFmpeg FATE files only for known demuxer/parser regressions, not
as the normal suite:

<https://ffmpeg.org/fate.html>

Do not commit downloaded videos into the repository. Store them under a local
ignored `tests/media/downloads/` directory and verify their checksums before a
test run.

### Generated fixtures

Generate short (3-10 second), deterministic fixtures with ffmpeg in
`tests/media/generated/`. This gives exact stream indexes, languages, default
flags, subtitles, attachments, and expected output signatures. Generated
fixtures are the normal automated suite; external files are integration tests.

## Fixture Matrix

| Fixture | Container | Video | Audio | Subtitles / extra streams | What it proves |
|---|---|---|---|---|---|
| basic | mkv, mp4, mov | H.264 1080p above threshold | AAC eng | none | H.264 and H.265 output selection, duration, replacement |
| multi-language | mkv | H.264 | AAC eng default, AAC jpn, AC3 deu | SRT eng, ASS jpn, SRT deu | language filtering and default-track fallback |
| all-audio | mkv | H.264 | AAC eng + jpn + AC3 deu | SRT eng + jpn | empty allowed-language setting keeps every audio/subtitle stream |
| no-match | mkv | H.264 | AAC deu | SRT deu | no matching configured language falls back to default then first audio; unmatched subtitles are dropped |
| image-subtitles | mkv | H.264 | AAC eng | PGS or DVD subtitle plus SRT | subtitle-copy behavior and fallback attempt that disables subtitles |
| attachments | mkv | H.264 | AAC eng | SRT eng plus font/cover attachment | attachments and cover art do not become a second video stream |
| multi-video | mkv | primary H.264 plus attached cover art | AAC eng | none | primary video selection ignores attached picture |
| HEVC input | mkv, mp4 | HEVC 8-bit and 10-bit | AAC eng | SRT eng | decoder support and H.264/H.265 target conversion |
| non-H264-container | avi, webm, ts, flv, wmv | supported video | AAC/Opus as applicable | none | documented container skip behavior |
| already-small | mkv | H.264 under max bitrate | AAC eng | none | no conversion and valid cache skip |
| corruption / truncation | mkv | truncated source or output | AAC eng | none | decode and duration validation reject bad output; source remains unchanged |
| replacement failure | mkv | H.264 | AAC eng | none | failed atomic replacement preserves source and reports failure |

## Assertions Per Conversion

For each supported target profile (`cpu`, NVIDIA, Intel QSV, VA-API):

1. Run a fixture with `codec: h264`, then separately with `codec: h265`.
2. `ffprobe` must report exactly one non-attached video stream with `h264` or
   `hevc` respectively.
3. Output duration must remain within the converter's one-percent tolerance.
4. Expected audio and subtitle stream count, codec, language, and default flag
   must match the selected language policy.
5. `ffmpeg -v error -i output -f null -` must decode successfully.
6. The output must replace the source only after all assertions pass; failures
   leave the original bytes intact.
7. H.264 and H.265 must produce different conversion-option cache keys; a
   second identical run may cache-skip, but switching codec must reprocess.

## Test Layers

- Unit: codec-to-profile encoder mapping, invalid codec fallback, API codec
  validation, raw encoder preservation, cache-key differences, CPU fallback.
- Generated-media integration: run `convert_if_needed()` on every generated
  fixture using `libx264` and `libx265`; inspect output with ffprobe.
- Hardware integration: run the basic, multi-language, HEVC 10-bit, and
  image-subtitle fixtures once for every available GPU profile in its matching
  Docker container. Skip unavailable hardware, never fake it as passing.
- Downloaded-media regression: run Jellyfin and selected MediaConch samples in
  a separate optional test target after checksum verification.

## Pass Criteria

- All unit and generated-media integration tests pass in the CPU image.
- Every available deployed hardware profile passes its hardware matrix.
- No conversion test overwrites its source before output validation succeeds.
- At least one real Jellyfin H.264 source converts to a verified `hevc` output.

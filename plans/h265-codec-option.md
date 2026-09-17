# H.264 / H.265 Output Codec

## Problem

The output codec is hardcoded to H.264. Every named hardware profile maps to an
H.264 encoder (`TRANSCODER_ENCODERS`, `src/convert.py:107-113`), and the web UI
only exposes an encoder dropdown that is hardware-oriented (NVIDIA/Intel/VAAPI/
AMD/CPU). HEVC is only reachable by hand-passing a raw ffmpeg encoder name
(`--use hevc_nvenc`, etc.), which is invisible in the config and web UI.

The user wants one explicit **Output codec** choice in each library's
"Conversion Settings": **H.264** (the current default) or **H.265**. The
selected value controls the video stream ffmpeg writes. Codec composes with
the existing hardware choice: `(codec, profile) -> encoder`.

## Design

New per-library/profile setting `codec: h264 | h265` (default `h264`), resolved
with the active hardware profile at run time:

| codec \ profile | nvidia | amdgpu | intel | cpu | vaapi |
|---|---|---|---|---|---|
| h264 | h264_nvenc | h264_amf | h264_qsv | libx264 | h264_vaapi |
| h265 | hevc_nvenc | hevc_amf | hevc_qsv | libx265 | hevc_vaapi |

H.265 is ffmpeg's HEVC codec. Backend encoder-arg construction (`build_ffmpeg_cmd`) is already
encoder-agnostic (`-preset p4`, `-b:v`, `-crf`, vaapi `-global_quality` all key
off `active_encoder`/`active_profile`), and `hevc` is already in every profile's
`HWACCEL_DECODABLE` set — no ffmpeg command changes needed.

The web UI run flow never sends `flags.use` (no SPA button passes it); encoder
comes from config.yml per-library profile via `set_profile_globals()`. So the
whole feature rides the config profile — no run-request changes.

## Changes

1. `src/convert.py`:
   - Add codec/encoder table + defaults:
     - `TRANSCODER_CODEC = os.getenv("TRANSCODER_CODEC", "h264")` (module default,
       mirrors `TRANSCODER`).
     - `CODEC_ENCODERS = {"h264": {...current TRANSCODER_ENCODERS...}, "h265": {nvidia: hevc_nvenc, amdgpu: hevc_amf, intel: hevc_qsv, cpu: libx265, vaapi: hevc_vaapi}}` replacing the flat `TRANSCODER_ENCODERS`.
    - Validate `TRANSCODER_CODEC` from `.env` and profile values against
      `CODEC_ENCODERS`; unknown values warn and use `h264`.
    - `resolve_transcoder(use_value, codec=None)`: preserve a valid raw ffmpeg
      encoder value exactly, then resolve named hardware profiles through
      `CODEC_ENCODERS[codec or TRANSCODER_CODEC][profile]`. Error messages list
      profiles as before.
   - `set_profile_globals(profile)`:
     - If `"codec" in profile`: validate against `CODEC_ENCODERS` (warn + fall
       back to `h264` on unknown), set `TRANSCODER_CODEC`.
     - If `"encoder" in profile`: resolve via `resolve_transcoder(profile["encoder"], codec=TRANSCODER_CODEC)`.
      - Else if codec != `h264`: resolve the selected codec for the current
        named hardware profile. Do not remap a custom raw encoder.
   - `_PROFILE_KEYS`: add `"codec"` (line ~518).
   - `conversion_option()` cache key: use `TRANSCODER` (the concrete encoder,
     e.g. `h264_nvenc`) instead of `TRANSCODER_PROFILE` so h264 vs h265 on the
     same profile don't share cache entries. Side effect: probe-cache keys change
     once, so all cached skips are re-probed on the first run after upgrade
     (probe cache is a skip-performance cache only, never correctness).
   - CPU fallback (`convert_if_needed`, lines ~1759-1763): replacing hardcoded
     `libx264` fallback with the codec-consistent software encoder — `libx265`
     when the active encoder is a HEVC encoder, else `libx264`. Keep the guard
     "not already the primary encoder" / "encoder available".
    - `run_library_scan()`: save and restore `TRANSCODER_CODEC` alongside the
      other per-library globals.

2. `src/webui/main.py`:
    - Library create/update key loops: add `"codec"`.
    - Validate library API input: accept only `h264` and `h265`; reject any
      other value with HTTP 422. Converter-level fallback remains for manually
      edited YAML.

3. `src/webui/mcp.py`:
   - `GET /mcp/profiles`: add `"codec": settings.get("codec", "h264")`.
   - `GET /mcp/libraries`: add `"codec"` to `inline_keys`.

4. `webui/src/components/LibraryForm.jsx`:
    - New `codec` select labelled "Output codec" in the "Conversion Settings"
      section: H.264 (default) / H.265.
   - Load `p.codec`, default `'h264'`; submit `codec: form.codec`.
    - Include codec in `cacheInvalidated`, its explanatory text, and the Summary
      sidebar.

5. `config.yml.example`: add `codec: h264` to library + profile examples.

## Scope

- `build_ffmpeg_cmd` encoder args, HW decode sets, fallback *attempt list*
  structure (normal / software_decode / cpu).
- Raw `--use <encoder>` CLI path (still works, unchanged).
- Per-run web UI ("Run" overlay) — no new fields; codec is a config.yml
  property like bitrate.
- `--all` / `--library A,B` runs: they already apply per-library profiles via
  `run_library_scan()`, so codec applies there automatically once
  `set_profile_globals` handles it; no dedicated work.
- No AV1, VP9, container, bitrate, or quality-control changes.
- H.264 remains the default, so existing libraries keep their current output
  stream codec until `codec: h265` is selected.

## Profile Resolution

- A named `profile:` supplies base settings; inline library settings override
  only the matching values. Setting only `codec: h265` on a library must not
  discard the named profile's encoder, bitrate, or language settings.
- `codec` can be placed either in a named profile or directly on a library.

## Verification

- Existing test suite passes (`docker exec jellysqueeze python -m pytest
  src/test_convert.py -v`).
- Syntax check all touched Python + a Vite build to validate the JSX.
- Unit coverage: H.264/H.265 named-profile resolution, invalid codec fallback,
  raw encoder preservation, codec-specific cache keys, and H.265 `libx265`
  CPU fallback.
- Manual (in container): a library with `codec: h265` + `encoder: intel`
  resolves to `hevc_qsv` (log line "Encoder: ..."); a converted output probes
  as `hevc`.
- Confirm cache-key change: after upgrade, first run re-probes once, then
  caching behaves as before with distinct h264/h265 keys.

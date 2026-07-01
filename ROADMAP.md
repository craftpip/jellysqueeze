# Media Convert Roadmap — ✅ ALL DONE

All features described below are now implemented. See AGENTS.md and `config.yml.example` for usage.

This file is kept for reference. Originally it described the intended direction for making the project easier to use as a Jellyfin library converter.

## Goals

1. Convert media libraries without manually running the script for each folder.
2. Keep the script simple: it starts, works, reports clearly, and exits.
3. Use Jellyfin API for normal runs so only recently added or updated media is checked.
4. Avoid daemon mode, watch mode, system services, background processes, and reserved disk space.
5. Keep decisions safe, predictable, and visible in the console.

## Main Workflow

### First Run: Full Library Backfill

Command:

```bash
python convert.py --all
```

What it does:

1. Reads `config.yml`.
2. Scans all configured libraries once.
3. Checks each video file independently.
4. Converts only files above the configured bitrate limit.
5. Skips files already small enough or already processed and unchanged.
6. Records decisions for future runs.
7. Writes a date-wise run log.
8. Exits.

Safer preview command:

```bash
python convert.py --all --dry-run
```

This shows what would happen without modifying files.

### Normal Runs: Jellyfin Recent Mode

Command:

```bash
python convert.py --jellyfin-recent --libraries Shows,Movies,Torrents --since-hours 72
```

What it does:

1. Asks Jellyfin for recently added or updated video items.
2. Gets file paths from Jellyfin.
3. Checks only those files.
4. Converts only if needed.
5. Triggers Jellyfin library refresh after conversion.
6. Exits.

Cron example:

```cron
0 */6 * * * cd /home/boniface/www/media-convert-for-jellyfin && python convert.py --jellyfin-recent --libraries Shows,Movies,Torrents --since-hours 72
```

## Config File

Add a `config.yml` file for libraries and profiles.

Example:

```yaml
libraries:
  - name: Shows
    path: /mnt/media1t/downloads/series
    profile: shows

  - name: Movies
    path: /mnt/media1t/movies
    profile: movies

profiles:
  shows:
    target_bitrate: 2500
    max_bitrate: 3500
    tolerance: 300
    encoder: nvidia
    keep_audio_langs: [eng, en, jpn, ja, hin, hi]
    keep_subtitles: true
    minimum_savings_percent: 10

  movies:
    target_bitrate: 3500
    max_bitrate: 5000
    tolerance: 500
    encoder: nvidia
    keep_audio_langs: [eng, en, hin, hi]
    keep_subtitles: true
    minimum_savings_percent: 10
```

## Commands To Add

1. Convert all configured libraries:

```bash
python convert.py --all
```

2. Convert one configured library:

```bash
python convert.py --library Shows
```

3. Check recent Jellyfin items:

```bash
python convert.py --jellyfin-recent --libraries Shows,Movies,Torrents --since-hours 72
```

4. Preview without modifying files:

```bash
python convert.py --all --dry-run
```

5. Preview recent Jellyfin items:

```bash
python convert.py --jellyfin-recent --libraries Shows,Movies --since-hours 72 --dry-run
```

## File-Level Decisions

Every media file is checked independently. A whole season should not be treated as one conversion decision because episodes can differ.

A file should be skipped if:

1. It is already processed and unchanged.
2. Its bitrate is already within the configured limit.
3. Its bitrate cannot be determined and force conversion is not enabled.
4. It is not a supported video container.
5. It no longer exists on disk.

A file should be converted if:

1. It exists.
2. It has a real video stream.
3. Its bitrate is above the profile threshold.
4. It has not already been processed with the same settings and same file metadata.

A file should be checked again if:

1. File size changed.
2. Modified time changed.
3. Conversion profile changed.
4. Jellyfin reports it as recently added or updated.

## State Tracking

The current `done.txt` should eventually be replaced or supplemented by a structured state file.

Example state entry:

```json
{
  "/media/Shows/Example/Season 01/Episode 01.mkv": {
    "profile": "shows",
    "mode": "br:2500",
    "size": 734003200,
    "mtime_ns": 1780000000000,
    "status": "converted",
    "jellyfin_item_id": "abc123"
  }
}
```

Skip as already processed only when path, profile, size, and modified time match.

## Bitrate Rules

Each profile defines:

1. `target_bitrate`: bitrate used for ffmpeg encoding.
2. `max_bitrate`: maximum acceptable source bitrate before conversion.
3. `tolerance`: buffer above max bitrate to avoid pointless conversions.

Decision rule:

```text
convert if detected_bitrate > max_bitrate + tolerance
skip if detected_bitrate <= max_bitrate + tolerance
```

Example:

```text
max_bitrate = 3500
tolerance = 300
threshold = 3800
```

So:

```text
3700 kbps -> skip
3900 kbps -> convert
```

Unknown bitrate behavior:

1. Try ffprobe format bitrate.
2. If missing, estimate from file size and duration.
3. If still unknown, skip by default and report clearly.

Replacement safety:

1. Never replace if output is larger than original.
2. Prefer requiring at least `minimum_savings_percent`, such as 10%.
3. If savings are too small, keep original and remove temp output.

## Fallback Conversion Attempts

Before marking a file failed, conversion should try practical fallbacks:

1. Normal selected encoder and hardware decode.
2. Software decode with selected encoder.
3. Software decode with selected encoder and no subtitles.
4. CPU encode with no subtitles, if `libx264` is available.

This covers common internet-release problems such as:

1. Attached cover art streams.
2. Multiple video streams.
3. Missing audio language tags.
4. Unsupported subtitle streams.
5. GPU decode failures.
6. Weird container metadata.

Some files still cannot be guaranteed, such as corrupt, incomplete, DRM/encrypted, or unsupported-codec files.

## Console Reporting

Console output should be human-friendly and explain decisions.

Startup example:

```text
Media Convert for Jellyfin

Mode: Jellyfin recent
Libraries: Shows, Movies, Torrents
Since: last 72 hours
Encoder: nvidia / h264_nvenc
Target bitrate: 3000 kbps
Max allowed bitrate: 3600 kbps
Dry run: no
Log file: logs/2026-06-04/09-00-00_jellyfin-recent.log
```

Per-file example:

```text
[1/18] Episode 01.mkv
Path: /mnt/media/Shows/Example/Season 01/Episode 01.mkv
Bitrate: 8200 kbps
Decision: convert
Reason: bitrate is above max allowed 3600 kbps
```

Skipped example:

```text
[2/18] Episode 02.mkv
Bitrate: 2200 kbps
Decision: skip
Reason: already below max allowed bitrate
```

Fallback example:

```text
Attempt 1 failed: GPU decode problem
Retrying with software decode...
Attempt 2: software decode + GPU encode + subtitles
```

Final summary example:

```text
Summary

Libraries checked: 3
Files discovered: 18
Converted: 5
Skipped: 11
Failed: 2
Space saved: 4.8 GB
Elapsed time: 38 min
```

## Date-Wise Run Logs

If `--log-file` is provided, use it exactly.

If `--log-file` is not provided, automatically create a log file using this structure:

```text
logs/YYYY-MM-DD/HH-MM-SS_MODE.log
```

Examples:

```text
logs/2026-06-04/03-00-00_all.log
logs/2026-06-04/09-00-00_jellyfin-recent.log
logs/2026-06-04/12-30-10_library-Shows.log
```

Console should print the log path at startup.

## Jellyfin API Integration

Use Jellyfin for normal runs.

Required behavior:

1. List configured Jellyfin libraries.
2. Query recently added or updated video items.
3. Extract media file paths.
4. Convert only those paths if needed.
5. Trigger Jellyfin library scan after successful conversions.

Known Jellyfin libraries currently visible:

1. Shows
2. Movies
3. Torrents
4. Music
5. Podcasts
6. Research
7. Collections

Recommended default video libraries:

1. Shows
2. Movies
3. Torrents

## Explicit Non-Goals

Do not add these unless explicitly requested later:

1. Watch mode.
2. Daemon mode.
3. Systemd service.
4. Always-running background process.
5. Disk-space reservation system.
6. Heavy database.

Cron is the intended automation method.

## Recommended Implementation Order

1. Add automatic date-wise run logs.
2. Add clearer console reporting and final summary.
3. Add `config.yml` with libraries and profiles.
4. Add `--all`, `--library`, and `--dry-run`.
5. Add stronger state tracking using path, profile, size, and modified time.
6. Add Jellyfin recent mode.
7. Add Jellyfin refresh after conversion.
8. Add minimum savings protection before replacement.

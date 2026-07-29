# Silo S3 Single-File Test

## Goal

Test conversion on one file from Silo Season 3 to verify:
- Video stream is preserved (not lost)
- All audio/subtitle tracks are retained
- Output is playable

## Command

```bash
python convert.py "/mnt/media2t/downloads/series/Silo (2023)/Season 03/" --verbose
```

## How to verify

1. **Before:** note which streams exist with `ffprobe` on the source file.
2. **After:** run `ffprobe` on the converted file and confirm all expected streams are present.
3. **Play test:** open the file in a player and check video + audio + subs work.

## If it fails

- Check the error message printed by the tool.
- A `stream_signature_mismatch` error means the safety guard caught a bad output — the original is intact.
- A `ffmpeg_failed` error means ffmpeg itself errored — check the log file in `logs/`.

## Notes

- Default profile is nvidia (`h264_nvenc`). Falls back to CPU if no GPU.
- Audio filtering is active — only `eng`/`en`/`jpn`/`ja`/`hin`/`hi` tracks are kept.
- `--verbose` shows the full ffmpeg command and output.

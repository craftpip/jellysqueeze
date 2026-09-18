# Media Fixtures

`downloads/` holds real Jellyfin test videos used by optional regression tests.
They are local test data and are intentionally ignored by git. The current
files come from <https://repo.jellyfin.org/test-videos/> and are CC BY-SA 4.0.

`generated/` is recreated by `tests/test_media_codec.py`. It contains short,
deterministic inputs with multiple audio and subtitle tracks, so tests can
assert the exact stream layout after a conversion.

Current downloaded fixtures:

- `Test Jellyfin 1080p AVC 10M.mp4`
- `Test Jellyfin 1080p HEVC 8bit 10M.mp4`
- `Test Jellyfin 1080p HEVC 10bit 10M.mp4`
- `matroska-test5-multi-audio-subtitles.mkv` - official Matroska test file with
  two audio tracks and seven embedded subtitles.

Each fixture has its upstream `.sha256sum` file beside it. Run the test module
to verify checksums and probe every downloaded stream:

```bash
docker exec jellysqueeze python -m pytest tests/test_media_codec.py -v
```

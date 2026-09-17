"""Real and generated media regression tests for H.264/H.265 output."""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import convert


MEDIA_DIR = ROOT / "tests" / "media"
DOWNLOADS_DIR = MEDIA_DIR / "downloads"

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
requires_ffmpeg = pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe not available")


def _require_encoder(name: str):
    if name not in convert.get_available_encoders():
        pytest.skip(f"ffmpeg encoder unavailable: {name}")


def _write_subtitle(path: Path, text: str):
    path.write_text(f"1\n00:00:00,000 --> 00:00:01,500\n{text}\n", encoding="utf-8")


def _make_multitrack_fixture(path: Path):
    """Build a source with predictable language and default-track metadata."""
    eng = path.with_name("eng.srt")
    jpn = path.with_name("jpn.srt")
    _write_subtitle(eng, "English subtitle")
    _write_subtitle(jpn, "Japanese subtitle")
    subprocess.run(
        [
            convert.FFMPEG_CMD, "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc2=duration=2:size=160x90:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=550:duration=2",
            "-i", str(eng), "-i", str(jpn),
            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:s", "-map", "4:s",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-c:a", "aac", "-c:s", "srt",
            "-metadata:s:a:0", "language=eng", "-disposition:a:0", "default",
            "-metadata:s:a:1", "language=jpn",
            "-metadata:s:s:0", "language=eng", "-disposition:s:0", "default",
            "-metadata:s:s:1", "language=jpn",
            str(path),
        ],
        check=True,
    )


@requires_ffmpeg
@pytest.mark.parametrize(
    ("encoder", "expected_video"),
    [("libx264", "h264"), ("libx265", "hevc")],
)
def test_generated_multitrack_conversion_keeps_selected_streams(tmp_path, monkeypatch, encoder, expected_video):
    _require_encoder(encoder)
    source = tmp_path / "multi.mkv"
    output = tmp_path / f"output-{expected_video}.mkv"
    _make_multitrack_fixture(source)

    monkeypatch.setattr(convert, "ALLOWED_AUDIO_LANGS", {"eng", "jpn"})
    monkeypatch.setattr(convert, "ALLOWED_SUBTITLE_LANGS", {"eng"})
    cmd, err = convert.build_ffmpeg_cmd(
        source, output, crf=30, disable_hwaccel=True,
        encoder=encoder, encoder_profile="cpu",
    )

    assert err is None
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    assert convert.probe_output_signature(output) == (
        (expected_video,), ("aac:eng", "aac:jpn"), ("subrip:eng",),
    )
    ok, message = convert.validate_attempt_output(source, output, encoder)
    assert ok, message


@requires_ffmpeg
def test_generated_multitrack_conversion_keeps_all_when_language_filters_empty(tmp_path, monkeypatch):
    _require_encoder("libx264")
    source = tmp_path / "multi.mkv"
    output = tmp_path / "output.mkv"
    _make_multitrack_fixture(source)

    monkeypatch.setattr(convert, "ALLOWED_AUDIO_LANGS", set())
    monkeypatch.setattr(convert, "ALLOWED_SUBTITLE_LANGS", set())
    cmd, err = convert.build_ffmpeg_cmd(
        source, output, crf=30, disable_hwaccel=True,
        encoder="libx264", encoder_profile="cpu",
    )

    assert err is None
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    assert convert.probe_output_signature(output) == (
        ("h264",), ("aac:eng", "aac:jpn"), ("subrip:eng", "subrip:jpn"),
    )


@requires_ffmpeg
@pytest.mark.parametrize(
    ("filename", "expected_video", "expected_pix_fmt"),
    [
        ("Test Jellyfin 1080p AVC 10M.mp4", "h264", None),
        ("Test Jellyfin 1080p HEVC 8bit 10M.mp4", "hevc", None),
        ("Test Jellyfin 1080p HEVC 10bit 10M.mp4", "hevc", "yuv420p10le"),
    ],
)
def test_downloaded_jellyfin_fixtures_have_verified_expected_video_stream(filename, expected_video, expected_pix_fmt):
    fixture = DOWNLOADS_DIR / filename
    checksum_file = fixture.with_name(f"{fixture.name}.sha256sum")
    if not fixture.exists() or not checksum_file.exists():
        pytest.skip(f"downloaded fixture missing: {filename}")

    expected_hash = checksum_file.read_text(encoding="utf-8").split()[0]
    actual_hash = hashlib.sha256(fixture.read_bytes()).hexdigest()
    assert actual_hash == expected_hash
    assert convert.probe_video_codec(fixture) == expected_video
    if expected_pix_fmt:
        data = convert.ffprobe_json(fixture, "stream=codec_type,pix_fmt")
        video = next(s for s in data["streams"] if s.get("codec_type") == "video")
        assert video.get("pix_fmt") == expected_pix_fmt

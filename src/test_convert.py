import asyncio
import io
import json
import shutil
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import convert
import state_db
from webui.runner import RunManager


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    """Never use operational conversion state during tests."""
    monkeypatch.setattr(state_db, "VAR_DIR", tmp_path)
    monkeypatch.setattr(state_db, "DB_PATH", tmp_path / "state.sqlite3")
    monkeypatch.setattr(state_db, "DONE_FILE", tmp_path / "_progress.txt")
    monkeypatch.setattr(state_db, "PROBE_CACHE_FILE", tmp_path / "probe-cache.json")
    monkeypatch.setattr(state_db, "RUNS_DIR", tmp_path / "runs")


def test_load_done_empty():
    assert convert.load_done() == {}


def test_save_and_load_done():
    expected = {"/media/video1.mkv": "crf:23", "/media/video2.mp4": "br:3000"}
    convert.save_done(expected)
    assert convert.load_done() == expected


def test_done_retains_options_per_file():
    convert.save_done({"/media/video.mkv": "crf:23"})
    convert.save_done({"/media/video.mkv": "br:3000"})
    assert convert.load_done()["/media/video.mkv"] == "br:3000"


def test_probe_cache_updates_without_removing_other_paths():
    state_db.save_probe_cache({
        "/media/one.mkv": {"opt": "br:3000", "size": 1, "mtime_ns": 1},
    })
    state_db.save_probe_cache({
        "/media/two.mkv": {"opt": "br:3000", "size": 2, "mtime_ns": 2},
    })
    assert set(state_db.load_probe_cache()) == {"/media/one.mkv", "/media/two.mkv"}


def test_conversion_option_changes_with_output_settings(monkeypatch):
    monkeypatch.setattr(convert, "TARGET_BR", 3000)
    monkeypatch.setattr(convert, "MAX_BR", 4000)
    monkeypatch.setattr(convert, "TRANSCODER_PROFILE", "nvidia")
    monkeypatch.setattr(convert, "ALLOWED_AUDIO_LANGS", {"eng"})
    monkeypatch.setattr(convert, "ALLOWED_SUBTITLE_LANGS", {"eng"})
    first = convert.conversion_option(None)
    monkeypatch.setattr(convert, "TRANSCODER_PROFILE", "cpu")
    assert convert.conversion_option(None) != first


def test_conversion_option_supports_crf_zero():
    assert convert.conversion_option(0).startswith("crf:0|")


def test_conversion_option_changes_with_minimum_savings():
    assert convert.conversion_option(None, 0) != convert.conversion_option(None, 10)


def test_profile_restores_bufsize(monkeypatch):
    monkeypatch.setattr(convert, "TARGET_BR", 3000)
    monkeypatch.setattr(convert, "MAX_BR", 4000)
    monkeypatch.setattr(convert, "BUFSIZE", 8000)
    profile = {"target_bitrate": 2000, "max_bitrate": 3000}
    convert.set_profile_globals(profile)
    assert convert.BUFSIZE == 6000


def test_run_manager_drains_final_result_before_saving_history():
    async def run():
        manager = RunManager()
        script = (
            "import json; "
            "print(json.dumps({'type':'result','file':'video.mkv','status':'OK','msg':'done'})); "
            "print(json.dumps({'type':'summary','ok':1,'skip':0,'fail':0}))"
        )
        run_id = await manager.start([sys.executable, "-c", script])
        await manager.wait()
        return run_id

    run_id = asyncio.run(run())
    saved = state_db.load_run(run_id)
    assert saved["results"][0]["file"] == "video.mkv"
    assert saved["summary"]["ok"] == 1


FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
requires_ffmpeg = pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe not available")


def _make_sample(path, duration):
    subprocess.run(
        [
            convert.FFMPEG_CMD, "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=128x64:rate=10",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
    )


def test_filter_dead_streams_drops_packetless_streams(monkeypatch):
    monkeypatch.setattr(convert, "stream_packet_counts", lambda f: {0: 100, 1: 50, 3: 200})
    vids = [(0, "hevc", 1), (10, "hevc", 1)]
    auds = [(1, "eng", 1), (11, "eng", 0)]
    subs = [(3, "ass", "eng"), (13, "ass", "eng")]
    fv, fa, fs = convert.filter_dead_streams(Path("/x.mkv"), vids, auds, subs)
    assert fv == [(0, "hevc", 1)]
    assert fa == [(1, "eng", 1)]
    assert fs == [(3, "ass", "eng")]


def test_filter_dead_streams_skips_single_video_scan(monkeypatch):
    calls = []
    monkeypatch.setattr(convert, "stream_packet_counts", lambda f: calls.append(f) or {})
    vids = [(0, "hevc", 1)]
    fv, fa, fs = convert.filter_dead_streams(Path("/x.mkv"), vids, [(1, "eng", 1)], [])
    assert fv == vids
    assert calls == []


@requires_ffmpeg
def test_validate_output_media_passes_healthy_file(tmp_path):
    src = tmp_path / "src.mkv"
    out = tmp_path / "out.mkv"
    _make_sample(src, 2)
    _make_sample(out, 2)
    ok, err = convert.validate_output_media(src, out)
    assert ok, err


@requires_ffmpeg
def test_validate_output_media_fails_genuine_truncation(tmp_path):
    src = tmp_path / "src.mkv"
    out = tmp_path / "out.mkv"
    _make_sample(src, 5)
    _make_sample(out, 2)
    ok, err = convert.validate_output_media(src, out)
    assert not ok
    assert "duration_mismatch" in err


@requires_ffmpeg
def test_validate_output_media_tolerates_inflated_source_header(tmp_path, monkeypatch):
    src = tmp_path / "src.mkv"
    out = tmp_path / "out.mkv"
    _make_sample(src, 3)
    _make_sample(out, 3)

    real_duration = convert.get_media_duration_seconds
    def fake_duration(file):
        if file == src:
            return (real_duration(src) or 0) + 3.0
        return real_duration(file)

    monkeypatch.setattr(convert, "get_media_duration_seconds", fake_duration)
    ok, err = convert.validate_output_media(src, out)
    assert ok, err


@requires_ffmpeg
def test_validate_output_media_tolerates_corrupt_copied_audio(tmp_path, monkeypatch):
    src = tmp_path / "src.mkv"
    out = tmp_path / "out.mkv"
    _make_sample(src, 2)
    _make_sample(out, 2)

    real_run = subprocess.run
    def fake_run(cmd, **kwargs):
        if "0:a?" in cmd:
            return types.SimpleNamespace(
                returncode=183,
                stderr="[aist#0:1/ac3 @ 0x1] Invalid data found when processing input",
            )
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, err = convert.validate_output_media(src, out)
    assert ok, err


def test_select_audio_empty_allowed_keeps_all(monkeypatch):
    monkeypatch.setattr(convert, "ALLOWED_AUDIO_LANGS", set())
    auds = [(1, "eng", True), (2, "jpn", False), (3, "fre", False)]
    assert convert.select_audio_streams(auds) == [(1, "eng"), (2, "jpn"), (3, "fre")]


def test_select_audio_filters_to_allowed(monkeypatch):
    monkeypatch.setattr(convert, "ALLOWED_AUDIO_LANGS", {"eng", "jpn"})
    auds = [(1, "eng", True), (2, "jpn", False), (3, "fre", False)]
    assert convert.select_audio_streams(auds) == [(1, "eng"), (2, "jpn")]


def test_select_subtitles_empty_allowed_keeps_all(monkeypatch):
    monkeypatch.setattr(convert, "ALLOWED_SUBTITLE_LANGS", set())
    subs = [(1, "subrip", "eng"), (2, "ass", "fre")]
    assert convert.select_subtitle_streams(subs) == [(1, "subrip", "eng"), (2, "ass", "fre")]


def test_library_run_settings_from_lib_entry(monkeypatch):
    monkeypatch.setattr(convert, "DEFAULT_EXCLUDE_DIRS", {".trickplay"})
    lib = {
        "workers": 3,
        "ignore_dirs": ["sample", "Extras"],
        "ignore_paths": ["/media/staging"],
    }
    workers, excludes, ignore = convert._library_run_settings(lib)
    assert workers == 3
    assert excludes == {".trickplay", "sample", "extras"}
    assert ignore == ["/media/staging"]


def test_library_run_settings_falls_back_to_globals(monkeypatch):
    monkeypatch.setattr(convert, "DEFAULT_EXCLUDE_DIRS", {".trickplay"})
    workers, excludes, ignore = convert._library_run_settings({}, workers=2, ignore_paths=["/cli/ignore"])
    assert workers == 2
    assert excludes == {".trickplay"}
    assert ignore == ["/cli/ignore"]


def _setup_convertible_source(tmp_path, monkeypatch):
    src = tmp_path / "src.mkv"
    src.write_bytes(b"x" * 100)
    monkeypatch.setattr(convert, "get_estimated_bitrate_kbps", lambda f: 50000)
    monkeypatch.setattr(convert, "get_media_duration_seconds", lambda f: 100.0)
    monkeypatch.setattr(convert, "TRANSCODER", "h264_nvenc")
    monkeypatch.setattr(convert, "TRANSCODER_PROFILE", "nvidia")
    monkeypatch.setattr(convert, "get_available_encoders", lambda: {"h264_nvenc", "libx264"})

    def fake_build(in_file, out_file, crf=None, verbose=False, seek_seconds=0.0, **options):
        out_file.write_bytes(b"encoded-data")
        return (["ffmpeg", "-y", str(out_file)], None)

    monkeypatch.setattr(convert, "build_ffmpeg_cmd", fake_build)
    monkeypatch.setattr(convert, "record_invalid_output_diagnostics", lambda *a, **k: "")
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kwargs: types.SimpleNamespace(returncode=0),
    )
    return src


def test_validation_failure_advances_to_next_fallback(tmp_path, monkeypatch):
    src = _setup_convertible_source(tmp_path, monkeypatch)
    attempts = []

    def fake_validate(source, output, active_encoder):
        attempts.append(active_encoder)
        if len(attempts) < 3:
            return False, "duration_mismatch(source=100.00, output=90.00)"
        return True, "ok"

    monkeypatch.setattr(convert, "validate_attempt_output", fake_validate)

    status, msg, size_row = convert.convert_if_needed(src)

    assert status == "OK"
    assert attempts == ["h264_nvenc", "h264_nvenc", "libx264"]
    assert size_row is not None


def test_validation_failure_all_attempts_returns_fail(tmp_path, monkeypatch):
    src = _setup_convertible_source(tmp_path, monkeypatch)
    monkeypatch.setattr(
        convert, "validate_attempt_output",
        lambda s, o, e: (False, "duration_mismatch(source=100.00, output=90.00)"),
    )

    status, msg, size_row = convert.convert_if_needed(src)

    assert status == "FAIL"
    assert msg.startswith("validation_failed(cpu):")
    assert "source=100.00" in msg and "output=90.00" in msg


def test_failure_cooldown_skips_repeat_work_until_fingerprint_changes(tmp_path, monkeypatch):
    src = _setup_convertible_source(tmp_path, monkeypatch)
    fp = [1, 2, 100, 3]
    monkeypatch.setattr(convert, "source_fingerprint", lambda f: tuple(fp))
    monkeypatch.setattr(
        convert, "validate_attempt_output",
        lambda s, o, e: (False, "duration_mismatch(source=100.00, output=90.00)"),
    )

    status, msg, _ = convert.convert_if_needed(src)
    assert status == "FAIL"
    assert msg.startswith("validation_failed(cpu):")

    status2, msg2, _ = convert.convert_if_needed(src)
    assert status2 == "SKIP"
    assert "failure_cooldown" in msg2

    fp[2] = 200
    status3, msg3, _ = convert.convert_if_needed(src)
    assert status3 == "FAIL"
    assert msg3.startswith("validation_failed(cpu):")


def test_emit_json_is_thread_safe(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    monkeypatch.setattr(convert, "JSON_MODE", True)

    def worker():
        for i in range(50):
            convert.emit_json("test", i=i, s="x" * 20)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = [ln for ln in buf.getvalue().splitlines() if ln]
    assert len(lines) == 400
    for ln in lines:
        data = json.loads(ln)
        assert data["type"] == "test"


def _run_json_scan(tmp_path, monkeypatch, workers):
    d = tmp_path / "media"
    d.mkdir()
    _make_sample(d / "a.mkv", 2)
    _make_sample(d / "b.mkv", 2)

    out = io.StringIO()
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    monkeypatch.setattr(convert, "JSON_MODE", True)

    ok, skip, fail, _saved = convert.main(str(d), workers=workers)
    return out.getvalue(), err.getvalue(), ok, skip, fail


def _assert_clean_json_run(stdout, stderr, ok, skip, fail):
    assert ok == 0 and fail == 0
    assert skip == 2
    assert stderr == "", f"expected no terminal/bar output on stderr, got: {stderr!r}"
    lines = [ln for ln in stdout.splitlines() if ln]
    assert lines, "expected structured JSON output on stdout"
    results = []
    for ln in lines:
        data = json.loads(ln)
        assert data.get("type") in {
            "run_status", "run_folder", "progress", "result", "summary", "overall_progress",
        }, f"unparseable/unknown event line: {ln!r}"
        if data.get("type") == "result":
            results.append(data)
    assert len(results) == 2
    assert {r["status"] for r in results} == {"SKIP"}


@requires_ffmpeg
def test_parallel_json_mode_emits_no_terminal_bars(tmp_path, monkeypatch):
    stdout, stderr, ok, skip, fail = _run_json_scan(tmp_path, monkeypatch, 2)
    _assert_clean_json_run(stdout, stderr, ok, skip, fail)


@requires_ffmpeg
def test_sequential_json_mode_emits_no_terminal_bars(tmp_path, monkeypatch):
    stdout, stderr, ok, skip, fail = _run_json_scan(tmp_path, monkeypatch, 1)
    _assert_clean_json_run(stdout, stderr, ok, skip, fail)


def test_runner_drops_ignorable_stderr_lines():
    from webui.runner import _is_ignorable_stderr

    assert _is_ignorable_stderr("")
    assert _is_ignorable_stderr("\x1b[1A\x1b[J")
    assert _is_ignorable_stderr("\x1b[1A\x1b[J[██░░░░] 1/10  OK=1")
    assert not _is_ignorable_stderr("2026-07-31 10:00:00 | INFO | Checking: /media/a.mkv")
    assert not _is_ignorable_stderr("{not json but starts with brace}")

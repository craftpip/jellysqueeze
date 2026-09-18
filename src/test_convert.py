import asyncio
import datetime as dt
import io
import json
import shutil
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import convert
import state_db
from webui.runner import RunManager, start_run, _managers


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
    monkeypatch.setattr(convert, "TRANSCODER", "h264_nvenc")
    monkeypatch.setattr(convert, "ALLOWED_AUDIO_LANGS", {"eng"})
    monkeypatch.setattr(convert, "ALLOWED_SUBTITLE_LANGS", {"eng"})
    first = convert.conversion_option(None)
    monkeypatch.setattr(convert, "TRANSCODER_PROFILE", "cpu")
    monkeypatch.setattr(convert, "TRANSCODER", "libx264")
    assert convert.conversion_option(None) != first


def test_conversion_option_changes_with_concrete_encoder(monkeypatch):
    monkeypatch.setattr(convert, "TRANSCODER", "h264_nvenc")
    first = convert.conversion_option(None)
    monkeypatch.setattr(convert, "TRANSCODER", "hevc_nvenc")
    assert convert.conversion_option(None) != first


def test_resolve_transcoder_maps_named_profile_to_selected_codec(monkeypatch):
    monkeypatch.setattr(convert, "get_available_encoders", lambda: {"h264_qsv", "hevc_qsv"})
    monkeypatch.setattr(convert, "device_available", lambda profile: profile == "intel")

    ok, err = convert.resolve_transcoder("intel", codec="h265")

    assert (ok, err) == (True, None)
    assert convert.TRANSCODER == "hevc_qsv"
    assert convert.TRANSCODER_PROFILE == "intel"


def test_resolve_transcoder_preserves_raw_encoder(monkeypatch):
    monkeypatch.setattr(convert, "get_available_encoders", lambda: {"hevc_qsv"})

    ok, err = convert.resolve_transcoder("hevc_qsv", codec="h264")

    assert (ok, err) == (True, None)
    assert convert.TRANSCODER == "hevc_qsv"
    assert convert.TRANSCODER_PROFILE == "custom"


def test_profile_codec_falls_back_to_h264(monkeypatch):
    monkeypatch.setattr(convert, "get_available_encoders", lambda: {"libx264"})
    monkeypatch.setattr(convert, "device_available", lambda profile: profile == "cpu")

    convert.set_profile_globals({"codec": "vp9", "encoder": "cpu"})

    assert convert.TRANSCODER_CODEC == "h264"
    assert convert.TRANSCODER == "libx264"


def test_inline_codec_overrides_named_profile_without_losing_settings():
    config = {
        "profiles": {"intel-default": {"encoder": "intel", "target_bitrate": 2000}},
    }

    profile = convert._extract_profile(config, {"profile": "intel-default", "codec": "h265"})

    assert profile == {"encoder": "intel", "target_bitrate": 2000, "codec": "h265"}


def test_library_api_rejects_invalid_codec(monkeypatch):
    from fastapi import HTTPException
    from webui import main as webui_main

    monkeypatch.setattr(webui_main.conv, "load_config", lambda: {"libraries": []})
    with pytest.raises(HTTPException, match="codec must be h264 or h265") as exc:
        asyncio.run(webui_main.api_create_library({"name": "Shows", "codec": "av1"}))
    assert exc.value.status_code == 422


def test_library_api_normalizes_codec(monkeypatch):
    from webui import main as webui_main

    saved = {}
    config = {"libraries": []}
    monkeypatch.setattr(webui_main.conv, "load_config", lambda: config)
    monkeypatch.setattr(webui_main.conv, "save_config", lambda value: saved.update(value) or True)

    result = asyncio.run(webui_main.api_create_library({"name": "Shows", "codec": " H265 "}))

    assert result["library"]["codec"] == "h265"
    assert saved["libraries"][0]["codec"] == "h265"


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


def test_start_run_allows_exclusive_modes_when_idle():
    async def run():
        try:
            await start_run([sys.executable, "-c", "import time; time.sleep(30)"])
            mgrs = list(_managers.values())
            assert len(mgrs) == 1
            assert mgrs[0].library is None
            assert mgrs[0].running
        finally:
            for mgr in list(_managers.values()):
                await mgr.stop()
            _managers.clear()

    asyncio.run(run())


def test_start_run_rejects_overlap_and_duplicates():
    async def run():
        try:
            await start_run([sys.executable, "-c", "import time; time.sleep(30)", "--library", "Shows"])
            with pytest.raises(RuntimeError):
                await start_run([sys.executable, "-c", "import time; time.sleep(30)", "--library", "Shows"])
            with pytest.raises(RuntimeError):
                await start_run([sys.executable, "-c", "import time; time.sleep(30)", "--all"])
            with pytest.raises(RuntimeError):
                await start_run([sys.executable, "-c", "import time; time.sleep(30)", "--jellyfin-recent"])
            await start_run([sys.executable, "-c", "import time; time.sleep(30)", "--library", "Movies"])
        finally:
            for mgr in list(_managers.values()):
                await mgr.stop()
            _managers.clear()

    asyncio.run(run())


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


def test_get_media_duration_seconds_normalizes_positive_start_time(monkeypatch):
    monkeypatch.setattr(
        convert,
        "ffprobe_json",
        lambda _file, _entries: {"format": {"duration": "1422.097", "start_time": "170.629"}},
    )
    assert convert.get_media_duration_seconds(Path("konosuba.mkv")) == pytest.approx(1251.468)


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


@pytest.mark.parametrize("subtitle_codec", ["hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle"])
def test_mkv_bitmap_subtitles_are_mapped_and_copied(monkeypatch, subtitle_codec):
    monkeypatch.setattr(convert, "probe_streams", lambda f: (
        [(0, "h264", True)], [(1, "eng", True)], [(2, subtitle_codec, "eng")],
    ))
    monkeypatch.setattr(convert, "ALLOWED_AUDIO_LANGS", {"eng"})
    monkeypatch.setattr(convert, "ALLOWED_SUBTITLE_LANGS", {"eng"})

    cmd, err = convert.build_ffmpeg_cmd(
        Path("input.mkv"), Path("output.mkv"), crf=30,
        disable_hwaccel=True, encoder="libx265", encoder_profile="cpu",
    )

    assert err is None
    assert ["-map", "0:2"] in [cmd[i:i + 2] for i in range(len(cmd) - 1)]
    assert ["-c:s", "copy"] == cmd[cmd.index("-c:s"):cmd.index("-c:s") + 2]


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


def test_hevc_validation_failure_falls_back_to_libx265(tmp_path, monkeypatch):
    src = _setup_convertible_source(tmp_path, monkeypatch)
    monkeypatch.setattr(convert, "TRANSCODER", "hevc_nvenc")
    monkeypatch.setattr(convert, "get_available_encoders", lambda: {"hevc_nvenc", "libx265"})
    attempts = []

    def fake_validate(source, output, active_encoder):
        attempts.append(active_encoder)
        return len(attempts) == 3, "duration_mismatch(source=100.00, output=90.00)"

    monkeypatch.setattr(convert, "validate_attempt_output", fake_validate)

    status, _msg, _size_row = convert.convert_if_needed(src)

    assert status == "OK"
    assert attempts == ["hevc_nvenc", "hevc_nvenc", "libx265"]


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


def test_build_convert_cmd_jellyfin_recent_mapping():
    from webui.main import build_convert_cmd

    cmd = build_convert_cmd({
        "mode": "jellyfin_recent",
        "flags": {"libraries": "Shows,Movies", "since_hours": 24},
    })
    assert "--jellyfin-recent" in cmd
    assert cmd[cmd.index("--libraries") + 1] == "Shows,Movies"
    assert cmd[cmd.index("--since-hours") + 1] == "24"


def test_build_convert_cmd_jellyfin_recent_default_since_hours():
    from webui.main import build_convert_cmd

    cmd = build_convert_cmd({"mode": "jellyfin_recent", "flags": {"libraries": "Shows"}})
    assert cmd[cmd.index("--libraries") + 1] == "Shows"
    assert cmd[cmd.index("--since-hours") + 1] == "72"


def test_run_manager_retains_latest_run_status():
    async def run():
        manager = RunManager()
        script = (
            "import json; "
            "print(json.dumps({'type':'run_status','phase':'process','message':'Found 2 recent file(s)','files_total':2}))"
        )
        run_id = await manager.start([sys.executable, "-c", script])
        await manager.wait()
        return manager, run_id

    manager, run_id = asyncio.run(run())
    assert manager.run_status["phase"] == "process"
    assert manager.run_status["files_total"] == 2
    saved = state_db.load_run(run_id)
    assert saved["run_status"]["files_total"] == 2


def test_run_manager_retains_files_total_across_run_status_events():
    async def run():
        manager = RunManager()
        script = (
            "import json; "
            "print(json.dumps({'type':'run_status','phase':'process','message':'Found 2 recent file(s)','files_total':2})); "
            "print(json.dumps({'type':'run_status','phase':'checking','message':'Checking: /x.mkv','files_total':2})); "
            "print(json.dumps({'type':'run_status','phase':'encode','message':'Encoding: /x.mkv'}))"
        )
        run_id = await manager.start([sys.executable, "-c", script])
        await manager.wait()
        return manager

    manager = asyncio.run(run())
    assert manager.run_status["phase"] == "encode"
    assert manager.run_status["files_total"] == 2


def _run_recent(monkeypatch, tmp_path, items, dry_run=False, done=None):
    d = tmp_path / "media"
    d.mkdir(exist_ok=True)
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(convert, "JSON_MODE", True)
    monkeypatch.setattr(convert, "load_config", lambda: None)
    monkeypatch.setattr(convert, "load_done", lambda: done or {})
    monkeypatch.setattr(convert, "load_probe_cache", lambda: {})
    monkeypatch.setattr(convert, "conversion_option", lambda *a, **k: "test-opt")

    class FakeClient:
        @classmethod
        def from_env(cls):
            return cls()

        def __init__(self):
            self._items = items

        def get_recent_items(self, lib, hours):
            return self._items

        def close(self):
            pass

    mod = types.ModuleType("jellyfin_client")
    mod.JellyfinClient = FakeClient
    monkeypatch.setitem(sys.modules, "jellyfin_client", mod)

    convert.main_jellyfin_recent(["Shows"], since_hours=72, dry_run=dry_run, min_savings_pct=0)
    return [json.loads(ln) for ln in out.getvalue().splitlines() if ln.startswith("{")]


def test_jellyfin_recent_emits_results_for_already_done_and_missing(monkeypatch, tmp_path):
    existing = tmp_path / "media" / "a.mkv"
    existing.parent.mkdir()
    existing.write_bytes(b"x")
    missing = tmp_path / "media" / "b.mkv"

    lines = _run_recent(
        monkeypatch, tmp_path,
        [{"path": str(existing)}, {"path": str(missing)}],
        done={str(existing.resolve().as_posix()): "test-opt"},
    )
    process = [ln for ln in lines if ln["type"] == "run_status" and ln["phase"] == "process"][0]
    assert process["files_total"] == 2

    results = [ln for ln in lines if ln["type"] == "result"]
    assert len(results) == 2
    assert {r["status"] for r in results} == {"SKIP"}
    assert sorted(r["msg"] for r in results) == ["already_done", "missing"]

    summary = [ln for ln in lines if ln["type"] == "summary"][0]
    assert summary["files_total"] == 2
    assert summary["skip"] == 2


def test_jellyfin_recent_empty_query_emits_zero_summary(monkeypatch, tmp_path):
    lines = _run_recent(monkeypatch, tmp_path, [])

    process = [ln for ln in lines if ln["type"] == "run_status" and ln["phase"] == "process"][0]
    assert process["files_total"] == 0

    summary = [ln for ln in lines if ln["type"] == "summary"][0]
    assert summary["files_total"] == 0
    assert summary["ok"] == summary["skip"] == summary["fail"] == 0


def test_jellyfin_recent_query_failure_emits_fail_result(monkeypatch, tmp_path):
    d = tmp_path / "media"
    d.mkdir(exist_ok=True)
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(convert, "JSON_MODE", True)
    monkeypatch.setattr(convert, "load_config", lambda: None)
    monkeypatch.setattr(convert, "load_done", lambda: {})
    monkeypatch.setattr(convert, "load_probe_cache", lambda: {})
    monkeypatch.setattr(convert, "conversion_option", lambda *a, **k: "test-opt")

    class FakeClient:
        @classmethod
        def from_env(cls):
            return cls()

        def get_recent_items(self, lib, hours):
            raise OSError(5, "Input/output error", f"/mnt/{lib}/bad.mkv")

        def close(self):
            pass

    mod = types.ModuleType("jellyfin_client")
    mod.JellyfinClient = FakeClient
    monkeypatch.setitem(sys.modules, "jellyfin_client", mod)

    convert.main_jellyfin_recent(["Shows"], since_hours=72, min_savings_pct=0)
    lines = [json.loads(ln) for ln in out.getvalue().splitlines() if ln.startswith("{")]

    results = [ln for ln in lines if ln["type"] == "result"]
    assert len(results) == 1
    assert results[0]["status"] == "FAIL"
    assert "Shows" in results[0]["file"]
    assert "Input/output error" in results[0]["msg"]

    summary = [ln for ln in lines if ln["type"] == "summary"][0]
    assert summary["fail"] == 1
    assert summary["ok"] == summary["skip"] == 0


def test_jellyfin_recent_dry_run_emits_terminal_results(monkeypatch, tmp_path):
    d = tmp_path / "media"
    d.mkdir()
    low = d / "a.mkv"
    high = d / "b.mkv"
    low.write_bytes(b"x")
    high.write_bytes(b"x")
    monkeypatch.setattr(
        convert, "get_estimated_bitrate_kbps",
        lambda f: 100 if str(f).endswith("a.mkv") else 10000,
    )

    lines = _run_recent(monkeypatch, tmp_path, [
        {"path": str(low)},
        {"path": str(high)},
    ], dry_run=True)

    results = [ln for ln in lines if ln["type"] == "result"]
    assert len(results) == 2
    assert sorted(r["status"] for r in results) == ["OK", "SKIP"]
    assert {r["msg"] for r in results} == {"would_skip(ok(100kbps))", "would_convert(10000kbps)"}

    checking = [ln for ln in lines if ln["type"] == "run_status" and ln["phase"] == "checking"]
    assert len(checking) == 2
    assert all(c["files_total"] == 2 for c in checking)


def test_jellyfin_recent_passes_progress_callback(monkeypatch, tmp_path):
    d = tmp_path / "media"
    d.mkdir()
    f = d / "a.mkv"
    f.write_bytes(b"x")

    captured = {}

    def fake_convert(file_path, crf=None, verbose=False, min_savings_pct=0, show_progress=False, progress_callback=None):
        captured["show_progress"] = show_progress
        captured["has_callback"] = progress_callback is not None
        if progress_callback:
            progress_callback(file_path, 42.5, position_seconds=1, duration_seconds=2, frame_count=3, total_frames=4)
        return "SKIP", "skipped_test", None

    monkeypatch.setattr(convert, "convert_if_needed", fake_convert)

    lines = _run_recent(monkeypatch, tmp_path, [{"path": str(f)}])

    assert captured["has_callback"] is True
    assert captured["show_progress"] is True

    progress = [ln for ln in lines if ln["type"] == "progress"]
    assert progress
    assert progress[0]["file"].endswith("a.mkv")
    assert progress[0]["percent"] == 42.5
    assert progress[0]["position_seconds"] == 1
    assert progress[0]["duration_seconds"] == 2
    assert progress[0]["frame_count"] == 3
    assert progress[0]["total_frames"] == 4


# ── Scheduler ───────────────────────────────────────────────────────────────

def test_next_run_daily():
    from webui.scheduler import next_run
    now = dt.datetime(2026, 8, 1, 20, 0, 0)
    assert next_run({"enabled": True, "repeat": "daily", "time": "21:00"}, now) == dt.datetime(2026, 8, 1, 21, 0, 0)
    assert next_run({"enabled": True, "repeat": "daily", "time": "19:00"}, now) == dt.datetime(2026, 8, 2, 19, 0, 0)
    assert next_run({"enabled": True, "repeat": "daily", "time": "20:00"}, now) == dt.datetime(2026, 8, 1, 20, 0, 0)


def test_next_run_daily_due_within_minute():
    from webui.scheduler import next_run
    now = dt.datetime(2026, 8, 1, 20, 0, 30)
    assert next_run({"enabled": True, "repeat": "daily", "time": "20:00"}, now) == dt.datetime(2026, 8, 1, 20, 0, 0)


def test_next_run_weekly():
    from webui.scheduler import next_run
    now = dt.datetime(2026, 8, 1, 10, 0, 0)  # Saturday
    assert next_run({"enabled": True, "repeat": "weekly", "day": 0, "time": "09:00"}, now) == dt.datetime(2026, 8, 3, 9, 0, 0)
    assert next_run({"enabled": True, "repeat": "weekly", "day": 5, "time": "09:00"}, now) == dt.datetime(2026, 8, 8, 9, 0, 0)
    assert next_run({"enabled": True, "repeat": "weekly", "day": 5, "time": "12:00"}, now) == dt.datetime(2026, 8, 1, 12, 0, 0)


def test_next_run_monthly():
    from webui.scheduler import next_run
    now = dt.datetime(2026, 8, 10, 10, 0, 0)
    assert next_run({"enabled": True, "repeat": "monthly", "day": 15, "time": "09:00"}, now) == dt.datetime(2026, 8, 15, 9, 0, 0)
    assert next_run({"enabled": True, "repeat": "monthly", "day": 15, "time": "12:00"}, now) == dt.datetime(2026, 8, 15, 12, 0, 0)
    now_sept = dt.datetime(2026, 9, 1, 10, 0, 0)
    assert next_run({"enabled": True, "repeat": "monthly", "day": 31, "time": "03:00"}, now_sept) == dt.datetime(2026, 10, 31, 3, 0, 0)


def test_next_run_disabled():
    from webui.scheduler import next_run
    now = dt.datetime(2026, 8, 1, 10, 0, 0)
    assert next_run({"enabled": False, "repeat": "daily", "time": "12:00"}, now) is None


def test_validate_schedule_rejects_bad_fields():
    from webui.scheduler import validate_schedule
    assert validate_schedule({"name": "x", "repeat": "daily", "time": "25:00", "mode": "library", "library": "S"})
    assert validate_schedule({"name": "x", "repeat": "weekly", "day": 9, "time": "03:00", "mode": "library", "library": "S"})
    assert validate_schedule({"name": "x", "repeat": "monthly", "day": 0, "time": "03:00", "mode": "library", "library": "S"})
    assert validate_schedule({"name": "x", "repeat": "daily", "time": "03:00", "mode": "library"})
    assert validate_schedule({"name": "x", "repeat": "daily", "time": "03:00", "mode": "jellyfin_recent"})
    assert validate_schedule({"name": "", "repeat": "daily", "time": "03:00", "mode": "library", "library": "S"})
    assert validate_schedule({"name": "x", "repeat": "daily", "time": "03:00", "mode": "library", "library": "S"}) is None
    assert validate_schedule({"name": "x", "repeat": "monthly", "day": 31, "time": "03:00", "mode": "library", "library": "S"}) is None


def test_schedule_to_req_maps_modes():
    from webui.scheduler import schedule_to_req
    assert schedule_to_req({"mode": "library", "library": "Shows", "flags": {}}) == \
        {"mode": "library", "library": "Shows", "flags": {}}
    assert schedule_to_req({"mode": "jellyfin_recent", "flags": {"libraries": "Shows", "since_hours": 24}}) == \
        {"mode": "jellyfin_recent", "flags": {"libraries": "Shows", "since_hours": 24}}


def test_scheduler_tick_fires_once(monkeypatch):
    import webui.main
    import webui.runner
    import webui.scheduler as sched_mod
    from webui.scheduler import Scheduler

    due_time = dt.datetime.now().strftime("%H:%M")
    sched = {"name": "test", "enabled": True, "repeat": "daily", "time": due_time,
             "mode": "library", "library": "Shows"}
    monkeypatch.setattr(sched_mod.conv, "load_config", lambda: {"schedules": [sched]})
    calls = []

    async def fake_start(cmd):
        calls.append(cmd)
        return "run123"

    monkeypatch.setattr(webui.main, "build_convert_cmd", lambda req: ["convert.py", "--library", req["library"]])
    monkeypatch.setattr(webui.runner, "start_run", fake_start)

    async def run():
        sc = Scheduler()
        await sc._tick()
        await sc._tick()
        return sc

    sc = asyncio.run(run())
    assert len(calls) == 1
    assert sc._last["test"]["run_id"] == "run123"


def test_scheduler_tick_skips_due_run_on_overlap(monkeypatch):
    import webui.main
    import webui.runner
    import webui.scheduler as sched_mod
    from webui.scheduler import Scheduler

    due_time = dt.datetime.now().strftime("%H:%M")
    sched = {"name": "test", "enabled": True, "repeat": "daily", "time": due_time,
             "mode": "library", "library": "Shows"}
    monkeypatch.setattr(sched_mod.conv, "load_config", lambda: {"schedules": [sched]})
    calls = []

    async def fake_start(cmd):
        calls.append(cmd)
        raise RuntimeError("already active for this library")

    monkeypatch.setattr(webui.main, "build_convert_cmd", lambda req: ["convert.py", "--library", req["library"]])
    monkeypatch.setattr(webui.runner, "start_run", fake_start)

    async def run():
        sc = Scheduler()
        await sc._tick()
        await sc._tick()
        return sc

    sc = asyncio.run(run())
    assert len(calls) == 1
    assert "skipped_reason" in sc._last["test"]


def test_scheduler_status_keeps_next_run_after_run_now(monkeypatch):
    import webui.main
    import webui.runner
    import webui.scheduler as sched_mod
    from webui.scheduler import Scheduler

    sched = {"name": "test", "enabled": True, "repeat": "daily", "time": "03:00",
             "mode": "library", "library": "Shows"}
    monkeypatch.setattr(sched_mod.conv, "load_config", lambda: {"schedules": [sched]})

    async def fake_start(cmd):
        return "run123"

    monkeypatch.setattr(webui.main, "build_convert_cmd", lambda req: ["convert.py", "--library", req["library"]])
    monkeypatch.setattr(webui.runner, "start_run", fake_start)

    async def run():
        sc = Scheduler()
        await sc.run_now("test")
        return sc

    sc = asyncio.run(run())
    assert sc._last["test"]["run_id"] == "run123"
    status = sc.get_status()
    assert status[0]["next_run"] is not None


# ── Panel auth ──────────────────────────────────────────────────────────────

def _auth_client():
    from fastapi.testclient import TestClient
    from webui import main as webui_main
    return webui_main, TestClient(webui_main.app)


def test_panel_auth_disabled_by_default(monkeypatch):
    monkeypatch.delenv("WEBUI_PASSWORD", raising=False)
    webui_main, client = _auth_client()
    status = client.get("/api/auth-status")
    assert status.status_code == 200
    assert status.json() == {"password_set": False, "authenticated": True}
    assert client.get("/api/config").status_code == 200


def test_panel_auth_requires_login(monkeypatch):
    monkeypatch.setenv("WEBUI_PASSWORD", "secret")
    webui_main, client = _auth_client()
    assert client.get("/api/config").status_code == 401
    assert client.get("/api/auth-status").json() == {"password_set": True, "authenticated": False}
    assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
    login = client.post("/api/login", json={"password": "secret"})
    assert login.status_code == 200
    assert login.json() == {"authenticated": True}
    assert client.get("/api/auth-status").json() == {"password_set": True, "authenticated": True}
    assert client.get("/api/config").status_code == 200
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/auth-status").json()["authenticated"] is False
    assert client.get("/api/config").status_code == 401


def test_panel_auth_rejects_tampered_and_expired_cookies(monkeypatch):
    monkeypatch.setenv("WEBUI_PASSWORD", "secret")
    webui_main, client = _auth_client()
    client.post("/api/login", json={"password": "secret"})
    valid = client.cookies.get(webui_main.SESSION_COOKIE)
    client.cookies.clear()
    payload, signature = valid.rsplit(".", 1)
    tampered = f"{payload}.{'0' * len(signature)}"
    assert client.get(
        "/api/config",
        headers={"Cookie": f"{webui_main.SESSION_COOKIE}={tampered}"},
    ).status_code == 401

    expired = webui_main._make_session_token(now=time.time() - webui_main.SESSION_TTL_SECONDS - 10)
    assert client.get(
        "/api/config",
        headers={"Cookie": f"{webui_main.SESSION_COOKIE}={expired}"},
    ).status_code == 401


def test_panel_env_never_exposes_or_accepts_password(monkeypatch):
    monkeypatch.setenv("WEBUI_PASSWORD", "secret")
    webui_main, client = _auth_client()
    saved = {}
    monkeypatch.setattr(webui_main.conv, "save_env", lambda overrides: saved.update(overrides) or True)
    client.post("/api/login", json={"password": "secret"})
    assert "WEBUI_PASSWORD" not in client.get("/api/env").json()
    assert client.post("/api/env", json={"WEBUI_PASSWORD": "hacked", "TARGET_BR": 2500}).status_code == 200
    assert "WEBUI_PASSWORD" not in saved
    assert saved["TARGET_BR"] == "2500"
    assert webui_main._panel_password() == "secret"


def test_panel_auth_rejects_websocket_without_session(monkeypatch):
    monkeypatch.setenv("WEBUI_PASSWORD", "secret")
    webui_main, client = _auth_client()
    from fastapi import WebSocketDisconnect
    with client.websocket_connect("/api/ws/nonexistent") as ws:
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()

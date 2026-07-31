import asyncio
import sys
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

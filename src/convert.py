import os
import json
import sys
import time
import errno
import shutil
import argparse
import subprocess
import logging
import threading
import typing
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from dotenv import load_dotenv
import state_db

try:
    import yaml as _yaml
except ImportError:
    _yaml = None

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TARGET_BR = int(os.getenv("TARGET_BR", 3000))
MAX_BR = int(os.getenv("MAX_BR", 3300))
BUFSIZE = int(os.getenv("BUFSIZE", 6000))
DEFAULT_CRF = int(os.getenv("DEFAULT_CRF", 23))
DEFAULT_MIN_SAVINGS_PCT = int(os.getenv("MIN_SAVINGS_PCT", 0))
TRANSCODER = "h264_nvenc"
TRANSCODER_PROFILE = "nvidia"
JSON_MODE = False
FFMPEG_CMD = "ffmpeg"
FFPROBE_CMD = "ffprobe"
AVAILABLE_ENCODERS: set[str] | None = None

DONE_FILE = PROJECT_ROOT / "var" / "_progress.txt"
SIZE_REPORT_FILE = PROJECT_ROOT / "var" / "size-report.csv"
PROBE_CACHE_FILE = PROJECT_ROOT / "var" / "probe-cache.json"
CONFIG_FILE = PROJECT_ROOT / "config.yml"
ENV_FILE = PROJECT_ROOT / ".env"
LOGS_DIR = PROJECT_ROOT / "var" / "logs"

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".webm", ".ts", ".flv", ".wmv"}
TMP_TAG = ".__transcoding__"  # temp name keeps same container (ext at end)
ORIGINAL_TAG = ".__original__"
DEFAULT_EXCLUDE_DIRS = {".git", ".trickplay"}

H264_OK_CONTAINERS = {".mkv", ".mp4", ".mov"}
TEXT_SUB_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text"}
MKV_SUB_CODECS = TEXT_SUB_CODECS | {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle"}
ALLOWED_AUDIO_LANGS = {
    "eng", "en", "english",
    "jpn", "ja", "japanese",
    "hin", "hi", "hindi",
}
ALLOWED_SUBTITLE_LANGS: set[str] | None = None  # None = use ALLOWED_AUDIO_LANGS
BACKUP_ORIGINALS = os.getenv("BACKUP_ORIGINALS", "0") == "1"
DEFAULT_WORKERS = int(os.getenv("DEFAULT_WORKERS", "1"))
DEFAULT_EXCLUDE_PATTERNS = os.getenv("DEFAULT_EXCLUDE", "")
DEFAULT_IGNORE_PATH = os.getenv("DEFAULT_IGNORE_PATH", "")
CLEANUP_TMP = os.getenv("CLEANUP_TMP", "0") == "1"
FAILURE_COOLDOWN_HOURS = float(os.getenv("FAILURE_COOLDOWN_HOURS", "24"))


# Codecs supported by each profile's hardware decoder (common codecs across most GPUs)
CUDA_DECODABLE_CODECS = {"h264", "hevc", "vp9", "mpeg1video", "mpeg2video", "vc1"}
QSV_DECODABLE_CODECS = {"h264", "hevc", "vp9", "mpeg2video", "vc1"}
VAAPI_DECODABLE_CODECS = {"h264", "hevc", "vp9", "mpeg2video", "vc1"}

HWACCEL_DECODABLE = {
    "nvidia": CUDA_DECODABLE_CODECS,
    "intel": QSV_DECODABLE_CODECS,
    "amdgpu": VAAPI_DECODABLE_CODECS,
    "vaapi": VAAPI_DECODABLE_CODECS,
}

log = logging.getLogger("transcode")

TRANSCODER_ALIASES = {
    "nvidia": "nvidia",
    "nvidiagpu": "nvidia",
    "nvenc": "nvidia",
    "h264_nvenc": "nvidia",
    "amdgpu": "amdgpu",
    "amd": "amdgpu",
    "amf": "amdgpu",
    "h264_amf": "amdgpu",
    "intel": "intel",
    "intelgpu": "intel",
    "qsv": "intel",
    "h264_qsv": "intel",
    "hevc_qsv": "intel",
    "cpu": "cpu",
    "software": "cpu",
    "x264": "cpu",
    "libx264": "cpu",
    "x265": "cpu",
    "libx265": "cpu",
    "vaapi": "vaapi",
    "h264_vaapi": "vaapi",
}

TRANSCODER_ENCODERS = {
    "nvidia": "h264_nvenc",
    "amdgpu": "h264_amf",
    "intel": "h264_qsv",
    "cpu": "libx264",
    "vaapi": "h264_vaapi",
}


_progress_lines = 0


def clear_progress_display():
    global _progress_lines
    if JSON_MODE:
        _progress_lines = 0
        return
    if _progress_lines > 0:
        sys.stderr.write(f"\033[{_progress_lines}A\033[J")
        sys.stderr.flush()
        _progress_lines = 0


class ProgressAwareStreamHandler(logging.StreamHandler):
    def emit(self, record):
        clear_progress_display()
        super().emit(record)

def draw_progress_bar(current: int, total: int, ok_cnt: int, skip_cnt: int, fail_cnt: int, start: float, per_file: dict[str, float] | None = None):
    global _progress_lines
    elapsed = time.perf_counter() - start
    done = ok_cnt + skip_cnt + fail_cnt
    in_flight = 0.0
    if per_file:
        in_flight = sum(max(0.0, min(pct_val, 99.0)) / 100.0 for pct_val in per_file.values())
    effective_done = min(float(total), done + in_flight)
    pct = effective_done / total * 100 if total > 0 else 0
    bar_len = 14
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    rate = effective_done / elapsed if elapsed > 0 and effective_done > 0 else 0
    if rate > 0 and total > effective_done:
        eta_s = (total - effective_done) / rate
        if eta_s < 60:
            eta = f"ETA {eta_s:.0f}s"
        elif eta_s < 3600:
            eta = f"ETA {eta_s/60:.0f}m"
        else:
            eta = f"ETA {eta_s/3600:.1f}h"
    else:
        eta = ""
    lines = [f"[{bar}] {done}/{total}  OK={ok_cnt}  SK={skip_cnt}  FL={fail_cnt}  {eta}"]
    if per_file:
        for path, pct_val in sorted(per_file.items(), key=lambda x: x[1], reverse=True):
            name = Path(path).stem[:40]
            shown_pct = in_progress_pct(float(pct_val))
            f2 = int(14 * shown_pct / 100)
            b2 = "█" * f2 + "░" * (14 - f2)
            if shown_pct >= 99.0:
                lines.append(f"  [{b2}] finalizing  {name}")
            else:
                lines.append(f"  [{b2}] {shown_pct:5.1f}%  {name}")

    clear_progress_display()
    sys.stderr.write("\n".join(lines) + "\n")
    sys.stderr.flush()
    _progress_lines = len(lines)


def print_progress(current: int, total: int, ok_cnt: int, skip_cnt: int, fail_cnt: int, start: float, workers: int = 1):
    elapsed = time.perf_counter() - start
    done = ok_cnt + skip_cnt + fail_cnt
    pct = done / total * 100 if total > 0 else 0
    bar_len = 12
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    rate = done / elapsed if elapsed > 0 and done > 0 else 0
    if rate > 0 and total > done:
        eta_s = (total - done) / rate
        if eta_s < 60:
            eta = f"ETA {eta_s:.0f}s"
        elif eta_s < 3600:
            eta = f"ETA {eta_s/60:.0f}m"
        else:
            eta = f"ETA {eta_s/3600:.1f}h"
    else:
        eta = ""
    if not JSON_MODE:
        log.info(f"[{bar}] {done}/{total}  OK={ok_cnt}  SK={skip_cnt}  FL={fail_cnt}  {eta}")
    emit_json("overall_progress", completed=done, total=total, ok=ok_cnt, skip=skip_cnt, fail=fail_cnt)


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _discover_binary(prefix: str, env_var: str, exact_names: tuple[str, ...]) -> str | None:
    override = os.getenv(env_var, "").strip()
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_absolute():
            return str(candidate) if _is_executable(candidate) else None
        resolved = shutil.which(override)
        if resolved:
            return resolved

    for name in exact_names:
        resolved = shutil.which(name)
        if resolved:
            return resolved

    path_dirs = [Path(p) for p in os.getenv("PATH", "").split(os.pathsep) if p]
    discovered = []
    for d in path_dirs:
        if not d.is_dir():
            continue
        try:
            for item in d.iterdir():
                low = item.name.lower()
                if not low.startswith(prefix):
                    continue
                if _is_executable(item):
                    discovered.append(item)
        except Exception:
            continue

    if not discovered:
        return None

    discovered.sort(key=lambda p: (len(p.name), p.name))
    return str(discovered[0])


def resolve_ffmpeg_tools() -> bool:
    global FFMPEG_CMD, FFPROBE_CMD

    ffmpeg = _discover_binary("ffmpeg", "FFMPEG_BIN", ("ffmpeg", "ffmpeg.exe"))
    ffprobe = _discover_binary("ffprobe", "FFPROBE_BIN", ("ffprobe", "ffprobe.exe"))
    if not ffmpeg or not ffprobe:
        return False

    FFMPEG_CMD = ffmpeg
    FFPROBE_CMD = ffprobe
    return True


def get_available_encoders() -> set[str]:
    global AVAILABLE_ENCODERS
    if AVAILABLE_ENCODERS is not None:
        return AVAILABLE_ENCODERS

    emit_json("run_status", phase="probe", message="Probing available ffmpeg encoders...")
    log.info("Probing available ffmpeg encoders...")
    cmd = [FFMPEG_CMD, "-hide_banner", "-encoders"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    encoders: set[str] = set()
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("-") or line.startswith("Encoders:"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                encoders.add(parts[1].lower())
    AVAILABLE_ENCODERS = encoders
    return AVAILABLE_ENCODERS


def device_available(profile: str) -> bool:
    if profile == "nvidia":
        try:
            r = subprocess.run(["nvidia-smi"], capture_output=True)
            return r.returncode == 0
        except FileNotFoundError:
            return False
    elif profile in ("intel", "vaapi", "amdgpu"):
        return os.path.exists("/dev/dri/renderD128")
    elif profile == "cpu":
        return True
    return False


def resolve_transcoder(use_value: str):
    global TRANSCODER, TRANSCODER_PROFILE

    requested = (use_value or "").strip().lower()
    if not requested:
        return True, None
    profile = TRANSCODER_ALIASES.get(requested)
    encoders = get_available_encoders()

    if profile:
        encoder = TRANSCODER_ENCODERS[profile]
        if encoder not in encoders:
            return False, f"encoder_not_supported({encoder})"
        if not device_available(profile):
            return False, f"device_not_available({profile})"
        TRANSCODER = encoder
        TRANSCODER_PROFILE = profile
        return True, None

    # Allow passing a raw ffmpeg encoder name directly (e.g. --use h264_nvenc).
    if requested in encoders:
        TRANSCODER = requested
        TRANSCODER_PROFILE = "custom"
        return True, None

    supported = ", ".join(sorted(TRANSCODER_ENCODERS.keys()))
    return False, f"unknown_transcoder({requested}); valid profiles: {supported}"


# ---------------------------------------------------------------------------
# Remote mode helpers
# ---------------------------------------------------------------------------

def parse_remote_target(remote: str) -> tuple[str, str]:
    """Parse 'user@host:/path' into (host, remote_dir)."""
    if ":" not in remote:
        raise ValueError("Remote must be in format user@host:/path")
    host, remote_dir = remote.split(":", 1)
    return host, remote_dir


def ssh_run(host: str, cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", host, cmd],
        capture_output=True, text=True, timeout=timeout,
    )


def scp_upload(local: Path, remote_dest: str, timeout: int = 600) -> bool:
    r = subprocess.run(
        ["scp", "-o", "ConnectTimeout=10", str(local), remote_dest],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode == 0


def scp_download(remote_src: str, local_dest: Path, timeout: int = 600) -> bool:
    r = subprocess.run(
        ["scp", "-o", "ConnectTimeout=10", remote_src, str(local_dest)],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode == 0


def ssh_mkdir(host: str, remote_dir: str) -> bool:
    r = ssh_run(host, f"mkdir -p '{remote_dir}'")
    return r.returncode == 0


def ssh_ls(host: str, remote_dir: str) -> bool:
    r = ssh_run(host, f"ls -1 '{remote_dir}'")
    return r.returncode == 0


def list_remote_videos(host: str, remote_dir: str) -> list[str]:
    """List video files on remote via SSH find."""
    ext_pattern = " -o ".join(f'-name "*{ext}"' for ext in VIDEO_EXTS)
    cmd = f"find '{remote_dir}' -type f \\( {ext_pattern} \\) | sort"
    r = ssh_run(host, cmd, timeout=120)
    if r.returncode != 0:
        return []
    files = [line.strip() for line in r.stdout.splitlines() if line.strip()]
    return [f for f in files if TMP_TAG not in f]


def remote_file_size(host: str, remote_path: str) -> int | None:
    r = ssh_run(host, f"stat -c%s '{remote_path}'")
    if r.returncode == 0:
        try:
            return int(r.stdout.strip())
        except ValueError:
            pass
    return None


def load_done() -> dict[str, str]:
    return state_db.load_done()


def save_done(done: dict[str, str]) -> None:
    state_db.save_done(done)


def append_size_report(rows: list[tuple[str, int, int]]) -> None:
    if not rows:
        return

    need_header = True
    if SIZE_REPORT_FILE.exists() and SIZE_REPORT_FILE.stat().st_size > 0:
        need_header = False

    with SIZE_REPORT_FILE.open("a", encoding="utf-8") as f:
        if need_header:
            f.write("name,before,after\n")
        for name, before, after in rows:
            f.write(f"{name},{before},{after}\n")


def write_per_run_size_report(log_path: Path) -> None:
    per_run_path = log_path.with_suffix(".size.csv")
    if SIZE_REPORT_FILE.exists() and SIZE_REPORT_FILE.stat().st_size > 0:
        per_run_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SIZE_REPORT_FILE, per_run_path)


def load_probe_cache() -> dict[str, dict]:
    emit_json("run_status", phase="cache", message=f"Loading probe cache...")
    log.info("Loading probe cache from SQLite")
    return state_db.load_probe_cache()


def save_probe_cache(cache: dict[str, dict]) -> None:
    state_db.save_probe_cache(cache)


_emit_lock = threading.Lock()


def emit_json(type_: str, **data):
    if not JSON_MODE:
        return
    line = json.dumps({"type": type_, **data}, default=str) + "\n"
    with _emit_lock:
        sys.stdout.write(line)
        sys.stdout.flush()


def load_config() -> dict | None:
    if not CONFIG_FILE.exists():
        return None
    if _yaml is None:
        log.warning("config.yml found but pyyaml is not installed; run: pip install pyyaml")
        return None
    try:
        data = _yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except Exception as e:
        log.warning(f"Failed to load config.yml: {e}")
        return None


def save_config(config: dict) -> bool:
    if _yaml is None:
        log.warning("pyyaml not installed; cannot save config.yml")
        return False
    tmp_file = CONFIG_FILE.with_name(f".{CONFIG_FILE.name}.tmp")
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tmp_file.open("w", encoding="utf-8") as f:
            _yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.replace(tmp_file, CONFIG_FILE)
        except OSError as e:
            if e.errno != errno.EBUSY:
                raise
            log.warning("config.yml is a single-file bind mount; falling back to in-place write")
            with tmp_file.open("r", encoding="utf-8") as src, CONFIG_FILE.open("w", encoding="utf-8") as dst:
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
        return True
    except Exception as e:
        log.warning(f"Failed to save config.yml: {e}")
        return False
    finally:
        if tmp_file.exists():
            tmp_file.unlink(missing_ok=True)


def save_env(overrides: dict[str, str]) -> bool:
    try:
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        seen_keys: set[str] = set()
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    lines.append(line)
                    continue
                k, _, v = stripped.partition("=")
                key = k.strip()
                if key in overrides:
                    lines.append(f"{key}={overrides[key]}")
                    seen_keys.add(key)
                else:
                    lines.append(line)
        for k, v in overrides.items():
            if k not in seen_keys:
                lines.append(f"{k}={v}")
        with ENV_FILE.open("w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return True
    except Exception as e:
        log.warning(f"Failed to save .env: {e}")
        return False


def get_profile_settings(config: dict, profile_name: str) -> dict | None:
    profiles = config.get("profiles") or {}
    return profiles.get(profile_name)


_PROFILE_KEYS = frozenset({
    "target_bitrate", "max_bitrate", "encoder",
    "keep_audio_langs", "keep_subtitle_langs",
    "minimum_savings_percent",
})


def _extract_profile(config: dict, lib: dict) -> dict | None:
    """Extract profile settings from a library entry.

    Prefers inline settings directly on the library entry.
    Falls back to old-style ``profile:`` reference for backward compat.
    """
    inline = {k: lib[k] for k in _PROFILE_KEYS if k in lib}
    if inline:
        return inline
    profile_name = lib.get("profile", "")
    if profile_name:
        return get_profile_settings(config, profile_name)
    return None


def set_profile_globals(profile: dict) -> None:
    global TARGET_BR, MAX_BR, BUFSIZE, TRANSCODER, TRANSCODER_PROFILE, ALLOWED_AUDIO_LANGS, ALLOWED_SUBTITLE_LANGS
    if "target_bitrate" in profile:
        TARGET_BR = int(profile["target_bitrate"])
    if "max_bitrate" in profile:
        MAX_BR = int(profile["max_bitrate"])
    BUFSIZE = MAX_BR * 2
    if "encoder" in profile:
        ok, err = resolve_transcoder(profile["encoder"])
        if not ok:
            log.warning(f"Profile encoder '{profile['encoder']}' not available: {err}")
    if "keep_audio_langs" in profile:
        ALLOWED_AUDIO_LANGS = set(lang.strip().lower() for lang in profile["keep_audio_langs"])
    if "keep_subtitle_langs" in profile:
        ALLOWED_SUBTITLE_LANGS = set(lang.strip().lower() for lang in profile["keep_subtitle_langs"])


def conversion_option(crf: int | None, min_savings_pct: int = 0) -> str:
    """Return a cache key for every setting that changes conversion output."""
    mode = f"crf:{crf}" if crf is not None else f"br:{TARGET_BR}"
    subtitles = ",".join(sorted(ALLOWED_SUBTITLE_LANGS or []))
    audio = ",".join(sorted(ALLOWED_AUDIO_LANGS))
    return f"{mode}|max:{MAX_BR}|encoder:{TRANSCODER_PROFILE}|audio:{audio}|subtitles:{subtitles}|savings:{min_savings_pct}"


def normalize_library_paths(lib: dict) -> list[str]:
    paths: list[str] = []

    raw_paths = lib.get("paths")
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    if isinstance(raw_paths, list):
        for path in raw_paths:
            if isinstance(path, str):
                cleaned = path.strip()
                if cleaned and cleaned not in paths:
                    paths.append(cleaned)

    legacy_path = lib.get("path")
    if isinstance(legacy_path, str):
        cleaned = legacy_path.strip()
        if cleaned and cleaned not in paths:
            paths.append(cleaned)

    return paths


def parse_name_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def find_library_config(config: dict | None, library_name: str) -> tuple[list[str], dict | None, dict] | None:
    if not config:
        return None
    libraries = config.get("libraries") or []
    needle = library_name.strip().lower()
    for lib in libraries:
        if lib.get("name", "").strip().lower() == needle:
            paths = normalize_library_paths(lib)
            profile = _extract_profile(config, lib)
            return paths, profile, lib
    return None


def _library_run_settings(
    lib: dict,
    workers: int = 1,
    ignore_paths: list[str] | None = None,
) -> tuple[int, set[str], list[str]]:
    """Per-library run settings: workers, excluded dir names, ignored path segments."""
    lib_workers = max(1, int(lib.get("workers") or workers))
    lib_ignore = list(ignore_paths or [])
    for p in lib.get("ignore_paths") or []:
        if p and p not in lib_ignore:
            lib_ignore.append(p)
    excludes = parse_exclude_dirs("")
    for d in lib.get("ignore_dirs") or []:
        if d:
            excludes.add(d.strip().lower())
    return lib_workers, excludes, lib_ignore


def run_library_scan(
    library_name: str,
    lib_paths: list[str],
    crf: int | None = None,
    verbose: bool = False,
    workers: int = 1,
    dry_run: bool = False,
    min_savings_pct: int = 0,
    profile: dict | None = None,
    ignore_paths: list[str] | None = None,
    scanned_paths: list[tuple[Path, list[Path], int, float]] | None = None,
    exclude_dirs: set[str] | None = None,
) -> tuple[int, int, int, float, bool]:
    global TARGET_BR, MAX_BR, BUFSIZE, TRANSCODER, TRANSCODER_PROFILE, ALLOWED_AUDIO_LANGS, ALLOWED_SUBTITLE_LANGS

    if profile:
        old_br = TARGET_BR
        old_max = MAX_BR
        old_bufsize = BUFSIZE
        old_encoder = TRANSCODER
        old_profile = TRANSCODER_PROFILE
        old_langs = set(ALLOWED_AUDIO_LANGS)
        old_sub_langs = set(ALLOWED_SUBTITLE_LANGS) if ALLOWED_SUBTITLE_LANGS is not None else None
        set_profile_globals(profile)
    else:
        old_br = old_max = old_bufsize = 0
        old_encoder = old_profile = ""
        old_langs = set()
        old_sub_langs = None

    total_ok = total_skip = total_fail = 0
    total_space_mb = 0.0
    scanned_any = False

    try:
        if scanned_paths is None:
            scanned_paths = scan_library_paths(library_name, lib_paths, ignore_paths, exclude_dirs)

        profile_min_savings = max(min_savings_pct, int(profile.get("minimum_savings_percent", 0)) if profile else 0)
        for path_obj, files, scanned_entries, discovery_time in scanned_paths:
            scanned_any = True
            ok, skip, fail, space_mb = main(
                str(path_obj), crf, verbose,
                exclude_dirs if exclude_dirs is not None else parse_exclude_dirs(""), False, workers,
                profile_min_savings, dry_run, ignore_paths,
                files, scanned_entries, discovery_time,
            )
            total_ok += ok
            total_skip += skip
            total_fail += fail
            total_space_mb += space_mb

        return total_ok, total_skip, total_fail, total_space_mb, scanned_any
    finally:
        if profile:
            TARGET_BR = old_br
            MAX_BR = old_max
            BUFSIZE = old_bufsize
            TRANSCODER = old_encoder
            TRANSCODER_PROFILE = old_profile
            ALLOWED_AUDIO_LANGS = old_langs
            ALLOWED_SUBTITLE_LANGS = old_sub_langs


def scan_library_paths(
    library_name: str,
    lib_paths: list[str],
    ignore_paths: list[str] | None = None,
    exclude_dirs: set[str] | None = None,
) -> list[tuple[Path, list[Path], int, float]]:
    """Discover every valid root now; process these results after all scans finish."""
    excludes = exclude_dirs if exclude_dirs is not None else parse_exclude_dirs("")
    scanned_paths: list[tuple[Path, list[Path], int, float]] = []

    for raw_path in lib_paths:
        path_obj = Path(raw_path).expanduser().resolve()
        if not path_obj.exists() or not path_obj.is_dir():
            log.warning(f"Library '{library_name}' path not found: {path_obj}, skipping")
            continue
        if ignore_paths and any(segment in str(path_obj) for segment in ignore_paths):
            log.info(f"Ignoring path (--ignore-path match): {path_obj}")
            continue

        log.info(f"Scanning: {path_obj}")
        if excludes:
            log.info(f"Excluding dirs: {', '.join(sorted(excludes))}")
        emit_json("run_status", phase="scan", message=f"Scanning: {path_obj}")
        discovery_started = time.perf_counter()
        files, deleted_tmp, scanned_entries = discover_videos_and_cleanup(path_obj, excludes)
        if ignore_paths:
            files = [path for path in files if not any(segment in str(path) for segment in ignore_paths)]
        discovery_time = time.perf_counter() - discovery_started

        if deleted_tmp:
            log.info(f"Cleanup: deleted {deleted_tmp} leftover temp file(s)")
        log.info(f"Found {len(files)} file(s)")
        log.info(f"Discovery done: scanned {scanned_entries} filesystem entries in {discovery_time:.2f}s")
        emit_json("run_folder", root=str(path_obj), total=len(files))
        scanned_paths.append((path_obj, files, scanned_entries, discovery_time))

    return scanned_paths


def make_auto_log_path(mode: str) -> Path:
    now = datetime.now(UTC)
    log_group = mode.replace("/", "_").replace("\\", "_")
    date_dir = LOGS_DIR / log_group / now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%H-%M-%S")
    return date_dir / f"{timestamp}.log"


def print_startup_banner(
    mode: str,
    libraries: list[str] | None = None,
    since_hours: int | None = None,
    encoder: str = "",
    target_br: int = 0,
    max_br: int = 0,
    dry_run: bool = False,
    log_path: str = "",
    workers: int = 1,
):
    threshold = max_br or MAX_BR
    print(f"JellySqueeze")
    print(f"  Mode:      {mode}")
    if libraries:
        print(f"  Libraries: {', '.join(libraries)}")
    if since_hours:
        print(f"  Since:     last {since_hours} hours")
    print(f"  Encoder:   {encoder or TRANSCODER} (profile: {TRANSCODER_PROFILE})")
    print(f"  Target:    {target_br or TARGET_BR} kbps  (burst max: {max_br or MAX_BR} kbps)")
    print(f"  Convert if over: {threshold} kbps")
    print(f"  Dry run:   {'yes' if dry_run else 'no'}")
    if workers > 1:
        print(f"  Workers:   {workers}")
    if log_path:
        print(f"  Log file:  {log_path}")
    print()


def print_summary(
    libraries_checked: int,
    files_found: int,
    ok: int,
    skip: int,
    fail: int,
    space_saved_mb: float,
    elapsed_seconds: float,
    log_path: str = "",
):
    hours, remainder = divmod(int(elapsed_seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        elapsed_str = f"{hours}h {minutes}m {secs}s"
    elif minutes:
        elapsed_str = f"{minutes}m {secs}s"
    else:
        elapsed_str = f"{secs}s"

    gb = space_saved_mb / 1024
    if gb >= 1.0:
        space_str = f"{gb:.2f} GB"
    else:
        space_str = f"{space_saved_mb:.0f} MB"

    print()
    print("Summary")
    print("  Libraries checked: " + str(libraries_checked))
    print(f"  Files discovered:  {files_found}")
    print(f"  Converted:         {ok}")
    print(f"  Skipped:           {skip}")
    print(f"  Failed:            {fail}")
    if space_saved_mb > 0:
        print(f"  Space saved:       {space_str}")
    print(f"  Elapsed time:      {elapsed_str}")
    if log_path:
        print(f"  Log file:          {log_path}")
    print()


def show_stats():
    if not SIZE_REPORT_FILE.exists() or SIZE_REPORT_FILE.stat().st_size == 0:
        print("No conversion history found (size-report.csv is empty or missing).")
        return

    entries: list[tuple[str, int, int]] = []
    with SIZE_REPORT_FILE.open("r", encoding="utf-8") as f:
        header = f.readline()
        if not header:
            print("No conversion history found (size-report.csv is empty).")
            return
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",", 2)
            if len(parts) < 3:
                continue
            try:
                before = int(parts[1])
                after = int(parts[2])
                entries.append((parts[0], before, after))
            except ValueError:
                continue

    if not entries:
        print("No conversion history found.")
        return

    total_before = sum(e[1] for e in entries)
    total_after = sum(e[2] for e in entries)
    saved_bytes = total_before - total_after
    saved_mb = saved_bytes / (1024 * 1024)
    saved_gb = saved_mb / 1024
    pct = (1 - total_after / total_before) * 100 if total_before > 0 else 0

    print("Conversion History")
    print(f"  Files converted:  {len(entries)}")
    print(f"  Total before:     {total_before / (1024*1024*1024):.2f} GB")
    print(f"  Total after:      {total_after / (1024*1024*1024):.2f} GB")
    if saved_gb >= 1.0:
        print(f"  Space saved:      {saved_gb:.2f} GB  ({pct:.1f}%)")
    else:
        print(f"  Space saved:      {saved_mb:.0f} MB  ({pct:.1f}%)")
    print()

    last = entries[-10:]
    print("  Last 10 converted:")
    print(f"  {'Before':>12}  {'After':>12}  {'Saved':>12}  Name")
    print(f"  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*40}")
    for name, before, after in last:
        saved = before - after
        saved_mb_val = saved / (1024 * 1024)
        before_mb = before / (1024 * 1024)
        after_mb = after / (1024 * 1024)
        short = name[:40]
        print(f"  {before_mb:>8.0f} MB  {after_mb:>8.0f} MB  {saved_mb_val:>+7.0f} MB  {short}")
    print()


def parse_exclude_dirs(exclude_value: str) -> set[str]:
    excludes = {name.lower() for name in DEFAULT_EXCLUDE_DIRS}
    for part in (exclude_value or "").split(","):
        item = part.strip().lower()
        if item:
            excludes.add(item)
    return excludes


def should_exclude_dir(name: str, excludes: set[str]) -> bool:
    low = name.lower()
    if low in excludes:
        return True
    if low.endswith(".trickplay"):
        return True
    return False


def discover_videos_and_cleanup(root: Path, excludes: set[str], progress_every: int = 5000) -> tuple[list[Path], int, int]:
    files: list[Path] = []
    deleted = 0
    scanned_entries = 0

    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    scanned_entries += 1

                    if entry.is_dir(follow_symlinks=False):
                        if should_exclude_dir(entry.name, excludes):
                            continue
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        name = entry.name
                        low_name = name.lower()
                        p = Path(entry.path)
                        ext = p.suffix.lower()

                        # Keep partial transcoding files so interrupted work can resume later.
                        if (TMP_TAG in name or ORIGINAL_TAG in name) and ext in VIDEO_EXTS:
                            continue

                        if ".trickplay" in low_name:
                            continue

                        if ext in VIDEO_EXTS and TMP_TAG not in name and ORIGINAL_TAG not in name:
                            files.append(p)

                    if progress_every > 0 and scanned_entries % progress_every == 0:
                        log.info(
                            f"Discovery progress: scanned {scanned_entries} filesystem entries, found {len(files)} candidate videos"
                        )
        except PermissionError:
            continue
        except FileNotFoundError:
            continue

    files.sort(key=lambda p: p.resolve().as_posix())
    return files, deleted, scanned_entries


def setup_logging(log_file: Path | None, verbose: bool):
    log.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")

    sh = ProgressAwareStreamHandler()
    sh.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh.setFormatter(fmt)
    log.addHandler(sh)

    if log_file:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(fmt)
            log.addHandler(fh)
        except Exception as e:
            log.warning(f"Could not create log file '{log_file}': {e}")


def run_quiet(cmd):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ffprobe_json(file, entries):
    cmd = [FFPROBE_CMD, "-v", "error", "-show_entries", entries, "-of", "json", str(file)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def get_estimated_bitrate_kbps(file):
    data = ffprobe_json(file, "format=duration,size,bit_rate")
    if not data or "format" not in data:
        return None

    fmt = data["format"]
    br = fmt.get("bit_rate")
    if br:
        try:
            return int(br) // 1000
        except Exception:
            pass

    try:
        duration = float(fmt.get("duration", 0))
        size = int(fmt.get("size", 0))
        if duration <= 0 or size <= 0:
            return None
        return int((size * 8) / duration / 1000)
    except Exception:
        return None


def is_attached_pic_stream(stream):
    disposition = stream.get("disposition") or {}
    return disposition.get("attached_pic") == 1


def is_default_stream(stream):
    disposition = stream.get("disposition") or {}
    return disposition.get("default") == 1


def probe_streams(file):
    data = ffprobe_json(
        file,
        "stream=index,codec_type,codec_name:stream_disposition=attached_pic,default:stream_tags=language",
    )
    if not data or "streams" not in data:
        return None

    vids, auds, subs = [], [], []
    for s in data["streams"]:
        st = s.get("codec_type")
        idx = s.get("index")
        codec = (s.get("codec_name") or "").lower()
        if idx is None:
            continue
        if st == "video" and not is_attached_pic_stream(s):
            vids.append((idx, codec, is_default_stream(s)))
        elif st == "audio":
            tags = s.get("tags") or {}
            lang = (tags.get("language") or "und").strip().lower()
            auds.append((idx, lang, is_default_stream(s)))
        elif st == "subtitle":
            tags = s.get("tags") or {}
            lang = (tags.get("language") or "und").strip().lower()
            subs.append((idx, codec, lang))
    return vids, auds, subs


def pick_primary_video(vids):
    for idx, codec, is_default in vids:
        if is_default:
            return idx, codec
    if vids:
        idx, codec, _is_default = vids[0]
        return idx, codec
    return None, None


def select_audio_streams(auds):
    if not ALLOWED_AUDIO_LANGS:
        return [(idx, lang) for idx, lang, _is_default in auds]
    selected = [(idx, lang) for idx, lang, _is_default in auds if lang in ALLOWED_AUDIO_LANGS or lang == "und"]
    if selected or not auds:
        return selected

    for idx, lang, is_default in auds:
        if is_default:
            log.info(f"No preferred audio language found; keeping default audio stream ({lang})")
            return [(idx, lang)]

    idx, lang, _is_default = auds[0]
    log.info(f"No preferred audio language found; keeping first audio stream ({lang})")
    return [(idx, lang)]


def select_subtitle_streams(subs: list) -> list[tuple[int, str, str]]:
    allowed = ALLOWED_SUBTITLE_LANGS if ALLOWED_SUBTITLE_LANGS is not None else ALLOWED_AUDIO_LANGS
    if not allowed:
        return [(idx, codec, lang) for idx, codec, lang in subs]
    selected = [(idx, codec, lang) for idx, codec, lang in subs if lang in allowed]
    return selected


def stream_packet_counts(file) -> dict[int, int] | None:
    """Packet count per stream index from a single full-file packet scan."""
    cmd = [
        FFPROBE_CMD, "-v", "error", "-show_packets",
        "-show_entries", "packet=stream_index", "-of", "json", str(file),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    counts: dict[int, int] = {}
    for p in data.get("packets", []):
        try:
            si = int(p.get("stream_index", -1))
        except (ValueError, TypeError):
            continue
        counts[si] = counts.get(si, 0) + 1
    return counts


def filter_dead_streams(file, vids, auds, subs):
    """Drop header-only streams that carry no packets (concat artifacts).

    Only scans when a file declares multiple video streams; healthy files keep
    their single-video fast path untouched.
    """
    if len(vids) <= 1:
        return vids, auds, subs
    counts = stream_packet_counts(file)
    if counts is None:
        return vids, auds, subs
    return (
        [(i, c, d) for i, c, d in vids if counts.get(i, 0) > 0],
        [(i, l, d) for i, l, d in auds if counts.get(i, 0) > 0],
        [(i, c, l) for i, c, l in subs if counts.get(i, 0) > 0],
    )


def probe_video_codec(file) -> str | None:
    data = ffprobe_json(file, "stream=index,codec_type,codec_name:stream_disposition=attached_pic,default")
    if not data or "streams" not in data:
        return None
    vids = []
    for s in data["streams"]:
        if s.get("codec_type") == "video" and not is_attached_pic_stream(s):
            idx = s.get("index")
            if idx is None:
                continue
            codec = (s.get("codec_name") or "").lower()
            vids.append((idx, codec, is_default_stream(s)))
    _idx, codec = pick_primary_video(vids)
    return codec or None


def tmp_name_for(file: Path) -> Path:
    return file.with_name(file.stem + TMP_TAG + file.suffix)


def original_backup_name_for(file: Path) -> Path:
    return file.with_name(file.stem + ORIGINAL_TAG + file.suffix)


def source_fingerprint(file: Path) -> tuple[int, int, int, int] | None:
    try:
        stat = file.stat()
    except OSError:
        return None
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def create_original_backup(file: Path) -> tuple[bool, str]:
    backup = original_backup_name_for(file)
    if backup.exists():
        return False, f"backup_exists({backup.name})"
    try:
        os.link(file, backup)
    except OSError:
        try:
            shutil.copy2(file, backup)
        except OSError as exc:
            return False, f"backup_failed({exc})"
    try:
        if backup.stat().st_size != file.stat().st_size:
            backup.unlink()
            return False, "backup_size_mismatch"
    except OSError as exc:
        return False, f"backup_verify_failed({exc})"
    return True, str(backup)


def cleanup_tmp_files(root: Path):
    deleted = 0
    for p in root.rglob(f"*{TMP_TAG}*"):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            try:
                p.unlink()
                deleted += 1
            except Exception:
                pass
    if deleted:
        log.info(f"Cleanup: deleted {deleted} leftover temp file(s)")


def resume_name_for(file: Path) -> Path:
    return file.with_name(file.stem + TMP_TAG + ".resume" + file.suffix)


def merge_name_for(file: Path) -> Path:
    return file.with_name(file.stem + TMP_TAG + ".merge" + file.suffix)


def expected_output_video_codec(active_encoder: str) -> str:
    low = active_encoder.lower()
    if "hevc" in low or "265" in low:
        return "hevc"
    if "av1" in low:
        return "av1"
    return "h264"


def probe_output_signature(file: Path) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None:
    data = ffprobe_json(file, "stream=codec_type,codec_name:stream_tags=language:stream_disposition=attached_pic")
    if not data or "streams" not in data:
        return None

    vids: list[str] = []
    auds: list[str] = []
    subs: list[str] = []
    for s in data["streams"]:
        st = s.get("codec_type")
        codec = (s.get("codec_name") or "").lower()
        if st == "video" and not is_attached_pic_stream(s):
            vids.append(codec)
        elif st == "audio":
            lang = ((s.get("tags") or {}).get("language") or "und").strip().lower()
            auds.append(f"{codec}:{lang}")
        elif st == "subtitle":
            lang = ((s.get("tags") or {}).get("language") or "und").strip().lower()
            subs.append(f"{codec}:{lang}")
    return tuple(vids), tuple(auds), tuple(subs)


def expected_output_signature(in_file: Path, active_encoder: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None:
    streams = probe_streams(in_file)
    if not streams:
        return None

    vids, auds, subs = streams
    if len(vids) > 1:
        vids, auds, subs = filter_dead_streams(in_file, vids, auds, subs)
    data = ffprobe_json(in_file, "stream=index,codec_type,codec_name:stream_tags=language")
    if not data or "streams" not in data:
        return None
    audio_codecs = {
        s.get("index"): (s.get("codec_name") or "").lower()
        for s in data["streams"]
        if s.get("codec_type") == "audio"
    }
    out_vids = (expected_output_video_codec(active_encoder),)
    out_auds = tuple(f"{audio_codecs.get(idx, '')}:{lang}" for idx, lang in select_audio_streams(auds))

    ext = in_file.suffix.lower()
    if ext == ".mkv":
        out_subs: tuple[str, ...] = tuple(f"{codec}:{lang}" for _idx, codec, lang in select_subtitle_streams(subs))
    elif ext in {".mp4", ".mov"}:
        out_subs = tuple(f"mov_text:{lang}" for _idx, codec, lang in select_subtitle_streams(subs) if codec in TEXT_SUB_CODECS)
    else:
        out_subs = ()
    return out_vids, out_auds, out_subs


def can_resume_partial(in_file: Path, partial: Path, active_encoder: str) -> tuple[bool, str]:
    expected = expected_output_signature(in_file, active_encoder)
    actual = probe_output_signature(partial)
    if expected is None or actual is None:
        return False, "signature_probe_failed"
    if expected != actual:
        return False, f"signature_mismatch(expected={expected}, actual={actual})"
    return True, "ok"


def get_media_duration_seconds(file: Path) -> float | None:
    probe = ffprobe_json(file, "format=duration")
    if not probe:
        return None
    try:
        return float(probe["format"]["duration"])
    except Exception:
        return None


def get_total_frames(file: Path) -> int | None:
    probe = ffprobe_json(file, "format=duration:stream=index,codec_type,nb_frames,avg_frame_rate,r_frame_rate")
    if not probe:
        return None
    streams = probe.get("streams", [])
    duration = None
    try:
        duration = float(probe["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        pass
    for s in streams:
        if s.get("codec_type") != "video":
            continue
        nb = s.get("nb_frames")
        if nb and nb != "N/A":
            try:
                return int(nb)
            except (ValueError, TypeError):
                pass
        if duration and duration > 0:
            for key in ("avg_frame_rate", "r_frame_rate"):
                fr = s.get(key, "0/1")
                if "/" in fr:
                    try:
                        num, den = fr.split("/")
                        n, d = float(num), float(den)
                        if d > 0 and n > 0:
                            return int(duration * n / d)
                    except (ValueError, ZeroDivisionError):
                        pass
            break
    return None


def packet_ends_by_stream(file) -> dict[int, float] | None:
    """Max packet end (pts+duration) per stream index from a single full-file scan."""
    cmd = [
        FFPROBE_CMD, "-v", "error", "-show_packets",
        "-show_entries", "packet=stream_index,pts_time,duration_time", "-of", "json", str(file),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    ends: dict[int, float] = {}
    for p in data.get("packets", []):
        try:
            si = int(p.get("stream_index", -1))
        except (ValueError, TypeError):
            continue
        pts = p.get("pts_time")
        dur = p.get("duration_time")
        if pts is None or dur is None or pts == "N/A" or dur == "N/A":
            continue
        try:
            end = float(pts) + float(dur)
        except (ValueError, TypeError):
            continue
        if end > ends.get(si, 0.0):
            ends[si] = end
    return ends


def _packet_durations_agree(source: Path, output: Path) -> bool:
    """Re-measure real media end times from packets when container headers disagree.

    Some rips carry an inflated container duration (stale muxer header or subtitle
    timestamps extending past the real media), so the header-only comparison in
    validate_output_media() produces false duration_mismatch results. Compare the
    actual packet end times of the mapped video and audio streams on both sides.
    """
    src_streams = probe_streams(source)
    out_streams = probe_streams(output)
    if not src_streams or not out_streams:
        return False
    src_vids, src_auds, _ = src_streams
    out_vids, out_auds, _ = out_streams
    src_v_idx, _ = pick_primary_video(src_vids)
    if src_v_idx is None:
        return False

    src_ends = packet_ends_by_stream(source)
    out_ends = packet_ends_by_stream(output)
    if src_ends is None or out_ends is None:
        return False

    src_v_end = src_ends.get(src_v_idx)
    out_v_end = max((out_ends.get(i, 0.0) for i, _c, _d in out_vids), default=None)
    if src_v_end is None or out_v_end is None:
        return False
    if abs(src_v_end - out_v_end) > max(2.0, src_v_end * 0.01):
        return False

    src_a_idx = [i for i, _l in select_audio_streams(src_auds)]
    src_a_end = max((src_ends.get(i, 0.0) for i in src_a_idx), default=None) if src_a_idx else None
    out_a_end = max((out_ends.get(i, 0.0) for i, _l, _d in out_auds), default=None) if out_auds else None
    if src_a_end is not None and out_a_end is not None:
        if abs(src_a_end - out_a_end) > max(2.0, src_a_end * 0.01):
            return False
    return True


def validate_output_media(source: Path, output: Path) -> tuple[bool, str]:
    source_duration = get_media_duration_seconds(source)
    output_duration = get_media_duration_seconds(output)
    if source_duration is None or output_duration is None:
        return False, "duration_probe_failed"
    if abs(source_duration - output_duration) > max(2.0, source_duration * 0.01):
        if not _packet_durations_agree(source, output):
            return False, f"duration_mismatch(source={source_duration:.2f}, output={output_duration:.2f})"
        log.info(
            f"Duration header mismatch tolerated for {output.name}: "
            f"source container={source_duration:.2f}s vs output={output_duration:.2f}s (packet media ends match)"
        )
    result = subprocess.run(
        [FFMPEG_CMD, "-v", "error", "-xerror", "-i", str(output), "-map", "0:v?", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, f"decode_validation_failed({summarize_ffmpeg_error(result.stderr)})"
    audio_result = subprocess.run(
        [FFMPEG_CMD, "-v", "error", "-i", str(output), "-map", "0:a?", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    if audio_result.returncode != 0:
        log.warning(
            f"Audio decode validation failed for {output.name}; audio is stream-copied, "
            f"so this reflects corrupt source audio: {summarize_ffmpeg_error(audio_result.stderr)}"
        )
    return True, "ok"


def get_last_video_packet_pts_seconds(file: Path) -> float | None:
    cmd = [
        FFPROBE_CMD,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_packets",
        "-show_entries",
        "packet=pts_time",
        "-of",
        "csv=p=0",
        str(file),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception:
        return None

    last_pts = None
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line or line == "N/A":
            continue
        if "," in line:
            line = line.split(",", 1)[0].strip()
        try:
            last_pts = float(line)
        except ValueError:
            continue
    return last_pts


def get_resume_seconds(src: Path, partial: Path) -> tuple[float | None, float | None]:
    if not partial.exists() or partial.stat().st_size == 0:
        return None, None

    src_duration = get_media_duration_seconds(src)
    partial_duration = get_last_video_packet_pts_seconds(partial)
    if src_duration is None or partial_duration is None:
        return None, src_duration

    streams = probe_streams(partial)
    if not streams or not streams[0]:
        return None, src_duration

    if partial_duration < 5:
        return None, src_duration
    if partial_duration >= src_duration - 1:
        return None, src_duration
    return partial_duration, src_duration


def concat_transcode_parts(first: Path, second: Path, out_file: Path, verbose: bool) -> tuple[bool, str]:
    list_file = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".concat.txt", delete=False) as fh:
            list_file = Path(fh.name)
            fh.write(f"file '{first.as_posix()}'\n")
            fh.write(f"file '{second.as_posix()}'\n")

        cmd = [
            FFMPEG_CMD,
            "-hide_banner",
            "-loglevel",
            "info" if verbose else "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(out_file),
        ]
        if verbose:
            subprocess.run(cmd, check=True)
        else:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, ""
    except subprocess.CalledProcessError as e:
        if hasattr(e, "stderr") and e.stderr:
            return False, e.stderr
        return False, f"exit_code={e.returncode}"
    finally:
        if list_file is not None:
            try:
                list_file.unlink()
            except Exception:
                pass


def summarize_ffmpeg_error(stderr: str) -> str:
    lines = []
    for raw in (stderr or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        lines.append(line)
    if not lines:
        return "no stderr output"

    preferred = []
    for line in lines:
        low = line.lower()
        if any(key in low for key in ("error", "failed", "invalid", "unsupported", "permission denied", "cannot", "no such", "not supported")):
            preferred.append(line)

    picked = preferred[-1] if preferred else lines[-1]
    return picked[:300]


def in_progress_pct(pct: float) -> float:
    return min(max(pct, 0.0), 100.0)


def safe_replace(src: Path, dst: Path):
    for _ in range(12):
        try:
            os.replace(str(src), str(dst))
            return True
        except PermissionError:
            time.sleep(0.25)
        except FileNotFoundError:
            return False
        except Exception:
            time.sleep(0.25)
    return False


def build_ffmpeg_cmd(
    in_file: Path,
    out_file: Path,
    crf: int | None = None,
    verbose: bool = False,
    disable_hwaccel: bool = False,
    encoder: str | None = None,
    encoder_profile: str | None = None,
    seek_seconds: float = 0.0,
):
    ext = in_file.suffix.lower()
    active_encoder = encoder or TRANSCODER
    active_profile = encoder_profile or TRANSCODER_PROFILE

    streams = probe_streams(in_file)
    if not streams:
        return None, "ffprobe_failed"

    vids, auds, subs = streams

    if len(vids) == 0:
        return None, "multiple_or_missing_video_streams"
    if len(vids) > 1:
        vids, auds, subs = filter_dead_streams(in_file, vids, auds, subs)
        if len(vids) == 0:
            return None, "multiple_or_missing_video_streams"

    video_idx, video_codec_from_streams = pick_primary_video(vids)
    if video_idx is None:
        return None, "no_video_stream"

    maps = ["-map", f"0:{video_idx}"]
    for i, _lang in select_audio_streams(auds):
        maps += ["-map", f"0:{i}"]

    filtered_subs = select_subtitle_streams(subs)
    sub_mode = "none"
    if ext == ".mkv":
        for idx, codec, _lang in filtered_subs:
            maps += ["-map", f"0:{idx}"]
        maps += ["-map", "0:t?"]
        sub_mode = "copy"
    elif ext in {".mp4", ".mov"}:
        unsupported_subtitles = [codec for _idx, codec, _lang in filtered_subs if codec not in TEXT_SUB_CODECS]
        if unsupported_subtitles:
            return None, f"unsupported_subtitle_codec({','.join(sorted(set(unsupported_subtitles)))})"
        for idx, codec, _lang in filtered_subs:
            if codec in TEXT_SUB_CODECS:
                maps += ["-map", f"0:{idx}"]
        sub_mode = "mov_text"

    loglevel = "info" if verbose else "error"

    video_codec = video_codec_from_streams or probe_video_codec(in_file)
    supported_codecs = HWACCEL_DECODABLE.get(active_profile)

    hwaccel_args: list[str] = []
    if not disable_hwaccel:
        if video_codec and supported_codecs and video_codec not in supported_codecs:
            log.info(f"Video codec '{video_codec}' not supported by {active_profile} hw decoder, using software decoding")
        elif active_profile == "nvidia":
            hwaccel_args = ["-hwaccel", "cuda"]
        elif active_profile == "intel":
            hwaccel_args = ["-hwaccel", "qsv"]
        elif active_profile == "amdgpu":
            hwaccel_args = ["-hwaccel", "vaapi"]
        elif active_profile == "vaapi" or active_encoder.endswith("_vaapi"):
            hwaccel_args = ["-hwaccel", "vaapi"]
    # cpu: no hwaccel (software decoding)

    cmd = [
        FFMPEG_CMD, "-hide_banner", "-loglevel", loglevel, "-y",
        *hwaccel_args,
        *( ["-ss", f"{seek_seconds:.3f}"] if seek_seconds > 0 else [] ),
        "-i", str(in_file),
        *maps,
    ]

    if active_profile == "nvidia":
        cmd += ["-preset", "p4", "-pix_fmt", "yuv420p"]
    elif active_profile == "amdgpu":
        cmd += ["-usage", "transcoding", "-quality", "balanced", "-pix_fmt", "yuv420p"]
    elif active_profile == "vaapi" or active_encoder.endswith("_vaapi"):
        cmd += ["-vaapi_device", "/dev/dri/renderD128", "-vf", "format=nv12,hwupload"]

    if crf is not None:
        if active_encoder.endswith("_vaapi"):
            cmd += [
                "-c:v", f"{active_encoder}",
                "-global_quality", str(crf),
                "-c:a", "copy",
                "-max_muxing_queue_size", "1024",
            ]
        else:
            cmd += [
                "-c:v", f"{active_encoder}",
                "-crf", str(crf),
                "-c:a", "copy",
                "-max_muxing_queue_size", "1024",
            ]
    else:
        if active_encoder.endswith("_vaapi"):
            # VAAPI driver only supports CQP mode, approximate bitrate via global_quality
            quality = max(18, min(30, 30 - (TARGET_BR - 1000) // 500))
            cmd += [
                "-c:v", f"{active_encoder}",
                "-global_quality", str(quality),
                "-c:a", "copy",
                "-max_muxing_queue_size", "1024",
            ]
        else:
            cmd += [
                "-c:v", f"{active_encoder}",
                "-b:v", f"{TARGET_BR}k",
                "-maxrate", f"{MAX_BR}k",
                "-bufsize", f"{BUFSIZE}k",
                "-c:a", "copy",
                "-max_muxing_queue_size", "1024",
            ]

    if sub_mode == "copy":
        cmd += ["-c:s", "copy"]
        cmd += ["-c:t", "copy"]
    elif sub_mode == "mov_text":
        cmd += ["-c:s", "mov_text"]

    cmd += [str(out_file)]
    return cmd, None


def validate_attempt_output(source: Path, output: Path, active_encoder: str) -> tuple[bool, str]:
    """Run stream-signature and media validation for one finished encode attempt."""
    expected = expected_output_signature(source, active_encoder)
    actual = probe_output_signature(output)
    if expected is None or actual is None or expected != actual:
        return False, f"stream_signature_mismatch(expected={expected}, actual={actual})"
    return validate_output_media(source, output)


def record_invalid_output_diagnostics(source: Path, output: Path, run_name: str) -> str:
    """Capture lightweight facts about a rejected encode before its temp file is deleted."""
    try:
        signature = probe_output_signature(output)
    except Exception:
        signature = None
    src_ends = packet_ends_by_stream(source)
    out_ends = packet_ends_by_stream(output)
    decode = subprocess.run(
        [FFMPEG_CMD, "-v", "error", "-xerror", "-i", str(output), "-map", "0:v?", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    decode_summary = summarize_ffmpeg_error(decode.stderr) if decode.returncode != 0 else "ok"
    return (
        f"  validation diagnostics ({run_name}):\n"
        f"    stream signature: {signature}\n"
        f"    packet ends source: {src_ends}\n"
        f"    packet ends output: {out_ends}\n"
        f"    decode: exit={decode.returncode} {decode_summary}"
    )


def _fingerprint_key(fp: tuple[int, int, int, int]) -> str:
    return f"{fp[0]}:{fp[1]}:{fp[2]}:{fp[3]}"


def get_failure_cooldown(file: Path, opt: str) -> str | None:
    """Return the active failure-cooldown message for a file, if any."""
    fp = source_fingerprint(file)
    if fp is None:
        return None
    entry = state_db.load_failure_cooldown(str(file))
    if not entry:
        return None
    if entry.get("option") != opt or entry.get("fingerprint") != _fingerprint_key(fp):
        return None
    return entry.get("message") or "cooldown_active"


def record_failure_cooldown(file: Path, opt: str, message: str) -> None:
    """Remember a confirmed-unrecoverable source so repeat runs skip it for a bounded time."""
    fp = source_fingerprint(file)
    if fp is None:
        return
    state_db.save_failure_cooldown(str(file), _fingerprint_key(fp), opt, message, FAILURE_COOLDOWN_HOURS)
    log.warning(f"Recorded failure cooldown for {file} ({FAILURE_COOLDOWN_HOURS:.1f}h): {message}")


def convert_if_needed(file: Path, crf: int | None = None, verbose: bool = False, min_savings_pct: int = 0, show_progress: bool = False, progress_callback: typing.Callable[[Path, float | None], None] | None = None):
    ext = file.suffix.lower()

    if ext not in H264_OK_CONTAINERS:
        return "SKIP", f"container_not_h264_ok({ext})", None

    br = get_estimated_bitrate_kbps(file)
    log.info(f"Bitrate: {br} kbps")
    original_fingerprint = source_fingerprint(file)
    if original_fingerprint is None:
        return "FAIL", "source_stat_failed", None

    if crf is None:
        if br is None:
            return "SKIP", "bitrate_unknown", None

        if br <= MAX_BR:
            return "SKIP", f"ok({br}kbps)", None

    current_opt = conversion_option(crf, min_savings_pct)
    cooldown_msg = get_failure_cooldown(file, current_opt)
    if cooldown_msg is not None:
        log.info(f"Failure cooldown active for {file.name}: {cooldown_msg}")
        return "SKIP", f"failure_cooldown({cooldown_msg})", None

    tmp = tmp_name_for(file)
    resume_tmp = resume_name_for(file)
    merge_tmp = merge_name_for(file)
    # Do not stitch partial encodes: stream-copy concat can produce broken timelines.
    resume_seconds = None
    src_duration = get_media_duration_seconds(file)

    for stale_tmp in (resume_tmp, merge_tmp):
        if stale_tmp.exists():
            try:
                stale_tmp.unlink()
            except Exception:
                return "FAIL", "tmp_cleanup_failed", None

    if tmp.exists() and resume_seconds is None:
        try:
            tmp.unlink()
        except Exception:
            return "FAIL", "tmp_cleanup_failed", None
    elif resume_seconds is not None:
        log.info(f"Resume: found partial temp for {file.name} at {resume_seconds:.1f}s")

    attempts = [
        ("normal", {}),
        ("software_decode", {"disable_hwaccel": True}),
    ]
    if TRANSCODER != "libx264" and "libx264" in get_available_encoders():
        attempts.append((
            "cpu",
            {"disable_hwaccel": True, "encoder": "libx264", "encoder_profile": "cpu"},
        ))

    last_error = "ffmpeg_failed"
    resumed_from = 0.0
    finished = False
    for attempt_name, options in attempts:
        attempt_encoder = options.get("encoder") or TRANSCODER
        resume_ok = False
        resume_reason = "no_partial"
        if resume_seconds is not None:
            resume_ok, resume_reason = can_resume_partial(
                file,
                tmp,
                attempt_encoder,
            )

        if resume_ok:
            run_modes = [(f"{attempt_name}_resume", resume_seconds, resume_tmp)]
        else:
            fresh_out = resume_tmp if resume_seconds is not None else tmp
            run_modes = [(attempt_name, 0.0, fresh_out)]
            if resume_seconds is not None:
                log.info(f"Resume skipped for {file.name} using {attempt_name}: {resume_reason}")

        for run_name, seek_seconds, out_file in run_modes:
            if seek_seconds == 0.0 and out_file == tmp and tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    return "FAIL", "tmp_cleanup_failed", None
            if out_file.exists():
                try:
                    out_file.unlink()
                except Exception:
                    return "FAIL", "tmp_cleanup_failed", None

            cmd, err = build_ffmpeg_cmd(file, out_file, crf, verbose, seek_seconds=seek_seconds, **options)
            if err:
                return "FAIL", err, None
            if not cmd:
                return "FAIL", "cmd_build_failed", None
            if verbose:
                log.info(f"Command ({run_name}): {' '.join(cmd)}")
            log.info(f"Encoding: {file.name} ({run_name})...")
            emit_json("run_status", phase="encode", message=f"Encoding: {file.name}")

            try:
                if verbose:
                    subprocess.run(cmd, check=True)
                elif show_progress:
                    dur = src_duration or get_media_duration_seconds(file)
                    if progress_callback:
                        progress_callback(file, 0.0, position_seconds=seek_seconds, duration_seconds=dur)
                    proc = subprocess.Popen(
                        cmd + ["-progress", "pipe:"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, bufsize=1,
                    )
                    stderr_buf: list[str] = []
                    stderr_done = threading.Event()
                    def _drain_stderr():
                        for line in proc.stderr:
                            stderr_buf.append(line)
                        stderr_done.set()
                    _t = threading.Thread(target=_drain_stderr, daemon=True)
                    _t.start()
                    last_up = 0
                    total_frames = None
                    timestamp_seen = False
                    unavailable_timestamp_updates = 0
                    for raw in proc.stdout:
                        rl = raw.strip()
                        if "=" not in rl:
                            continue
                        k, _, v = rl.partition("=")
                        pct = None
                        position_seconds = None
                        frame_count = None
                        if k == "frame":
                            try:
                                frame_count = int(v)
                            except (ValueError, TypeError):
                                pass
                            if not timestamp_seen and unavailable_timestamp_updates >= 2 and frame_count is not None:
                                if total_frames is None:
                                    total_frames = get_total_frames(file)
                                if total_frames:
                                    pct = in_progress_pct(frame_count / total_frames * 100)
                        if k in {"out_time_us", "out_time_ms"} and dur and dur > 0:
                            if v == "N/A":
                                if not timestamp_seen:
                                    unavailable_timestamp_updates += 1
                            try:
                                val = int(v)
                                position_seconds = seek_seconds + val / 1000000
                                pct = in_progress_pct(position_seconds / dur * 100)
                                timestamp_seen = True
                                unavailable_timestamp_updates = 0
                            except (ValueError, TypeError):
                                pass
                        elif k == "out_time" and dur and dur > 0:
                            if v == "N/A":
                                if not timestamp_seen:
                                    unavailable_timestamp_updates += 1
                            try:
                                hours, minutes, seconds = v.split(":")
                                position_seconds = seek_seconds + int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                                pct = in_progress_pct(position_seconds / dur * 100)
                                timestamp_seen = True
                                unavailable_timestamp_updates = 0
                            except (ValueError, TypeError):
                                pass
                        if k == "progress" and v.strip() == "end":
                            if progress_callback:
                                progress_callback(file, 99.5, finalizing=True)
                            break
                        if pct is not None:
                            now = time.time()
                            if now - last_up >= 0.5:
                                f = int(14 * pct / 100)
                                bar = "█" * f + "░" * (14 - f)
                                if progress_callback:
                                    progress_callback(
                                        file,
                                        pct,
                                        position_seconds=position_seconds,
                                        duration_seconds=dur,
                                        frame_count=frame_count,
                                        total_frames=total_frames,
                                    )
                                else:
                                    if JSON_MODE:
                                        sys.stderr.write(f"[{bar}] {pct:5.1f}%  {file.stem}\n")
                                    else:
                                        sys.stderr.write(f"\r  [{bar}] {pct:5.1f}%  {file.stem:<50.50s}")
                                    sys.stderr.flush()
                                last_up = now
                    if not progress_callback and not JSON_MODE:
                        sys.stderr.write("\r" + " " * 80 + "\r")
                        sys.stderr.flush()
                    proc.wait()
                    stderr_done.wait(timeout=5)
                    ff_stderr = "".join(stderr_buf)
                    if proc.returncode != 0:
                        raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=ff_stderr)
                else:
                    subprocess.run(cmd, capture_output=True, text=True, check=True)

                if seek_seconds > 0:
                    ok_concat, concat_err = concat_transcode_parts(tmp, resume_tmp, merge_tmp, verbose)
                    if not ok_concat:
                        last_error = f"concat_failed({run_name}): {concat_err}"
                        log.warning(f"Resume concat failed for {file} using {run_name}")
                        try:
                            if resume_tmp.exists():
                                resume_tmp.unlink()
                            if merge_tmp.exists():
                                merge_tmp.unlink()
                        except Exception:
                            pass
                        continue
                    try:
                        if resume_tmp.exists():
                            resume_tmp.unlink()
                    except Exception:
                        pass
                    if not safe_replace(merge_tmp, tmp):
                        last_error = f"merge_replace_failed({run_name})"
                        try:
                            if merge_tmp.exists():
                                merge_tmp.unlink()
                        except Exception:
                            pass
                        continue
                    resumed_from = seek_seconds
                elif out_file != tmp:
                    if not safe_replace(out_file, tmp):
                        last_error = f"scratch_replace_failed({run_name})"
                        try:
                            if out_file.exists():
                                out_file.unlink()
                        except Exception:
                            pass
                        continue

                valid, validation_error = validate_attempt_output(file, tmp, attempt_encoder)
                if not valid:
                    diagnostics = record_invalid_output_diagnostics(file, tmp, run_name)
                    log.warning(f"Validation failed for {file.name} using {run_name}: {validation_error}")
                    if diagnostics:
                        for line in diagnostics.splitlines():
                            log.warning(line)
                    last_error = f"validation_failed({run_name}): {validation_error}"
                    try:
                        if tmp.exists():
                            tmp.unlink()
                    except Exception:
                        pass
                    break

                last_error = ""
                finished = True
                break
            except subprocess.CalledProcessError as e:
                err_summary = summarize_ffmpeg_error(getattr(e, "stderr", "") or "")
                if hasattr(e, 'stderr') and e.stderr:
                    last_error = f"ffmpeg_failed({run_name}): {e.stderr}"
                else:
                    last_error = f"ffmpeg_failed({run_name}): exit_code={e.returncode}"
                if seek_seconds == 0.0 and out_file == tmp and tmp.exists():
                    updated_resume_seconds, updated_src_duration = get_resume_seconds(file, tmp)
                    if updated_resume_seconds is not None and updated_resume_seconds > (resume_seconds or 0.0):
                        resume_seconds = updated_resume_seconds
                        src_duration = updated_src_duration
                        log.info(f"Resume: retry for {file.name} will continue from {resume_seconds:.1f}s")
                elif out_file != tmp:
                    try:
                        if out_file.exists():
                            out_file.unlink()
                    except Exception:
                        pass
                log.warning(f"Retryable ffmpeg failure for {file.name} using {run_name}: {err_summary}")

        if finished:
            break

    if not finished:
        if last_error.startswith("validation_failed("):
            record_failure_cooldown(file, current_opt, last_error)
        return "FAIL", last_error, None
    if not tmp.exists() or tmp.stat().st_size == 0:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return "FAIL", "ffmpeg_failed", None

    before_size = file.stat().st_size
    after_size = tmp.stat().st_size

    if after_size >= before_size:
        try:
            tmp.unlink()
        except Exception:
            pass
        return "SKIP", f"output_larger({after_size} >= {before_size})", None
    if min_savings_pct > 0:
        savings_pct = (1 - after_size / before_size) * 100
        if savings_pct < min_savings_pct:
            try:
                tmp.unlink()
            except Exception:
                pass
            return "SKIP", f"savings_too_small({savings_pct:.1f}% < {min_savings_pct}%)", None

    if source_fingerprint(file) != original_fingerprint:
        return "FAIL", "source_changed_during_conversion", None
    if BACKUP_ORIGINALS:
        backup_ok, backup_result = create_original_backup(file)
        if not backup_ok:
            return "FAIL", backup_result, None
        log.info(f"Original backup: {backup_result}")

    if not safe_replace(tmp, file):
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return "FAIL", "replace_failed", None

    mode = f"crf({crf})" if crf is not None else f"converted({br}kbps)"
    return "OK", mode, (file.name, before_size, after_size)


def main(
    scan_dir: str,
    crf: int | None = None,
    verbose: bool = False,
    exclude_dirs: set[str] | None = None,
    cleanup_tmp: bool = False,
    workers: int = 1,
    min_savings_pct: int = 0,
    dry_run: bool = False,
    ignore_paths: list[str] | None = None,
    discovered_files: list[Path] | None = None,
    discovered_entries: int | None = None,
    discovery_time: float | None = None,
):
    if not resolve_ffmpeg_tools():
        log.error("FATAL: ffmpeg/ffprobe not found in PATH")
        return 0, 0, 0, 0.0

    root = Path(scan_dir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        log.error(f"FATAL: not a directory: {root}")
        return 0, 0, 0, 0.0
    if ignore_paths and any(seg in str(root) for seg in ignore_paths):
        log.info(f"Ignoring path (--ignore-path match): {root}")
        return 0, 0, 0, 0.0

    excludes = exclude_dirs if exclude_dirs is not None else parse_exclude_dirs("")

    if discovered_files is None:
        log.info(f"Scanning: {root}")
        if excludes:
            log.info(f"Excluding dirs: {', '.join(sorted(excludes))}")
        if cleanup_tmp:
            cleanup_tmp_files(root)
    else:
        log.info(f"Using completed discovery for: {root}")

    done = load_done()
    probe_cache = load_probe_cache()
    probe_cache_dirty = False

    if discovered_files is None:
        emit_json("run_status", phase="scan", message=f"Scanning: {root}")
        discovery_started = time.perf_counter()
        files, deleted_tmp, scanned_entries = discover_videos_and_cleanup(root, excludes)
        if ignore_paths:
            files = [path for path in files if not any(segment in str(path) for segment in ignore_paths)]
        discovery_time = time.perf_counter() - discovery_started
        emit_folder = True
    else:
        files = discovered_files
        deleted_tmp = 0
        scanned_entries = discovered_entries or 0
        discovery_time = discovery_time or 0.0
        emit_folder = False

    if deleted_tmp:
        log.info(f"Cleanup: deleted {deleted_tmp} leftover temp file(s)")

    total = len(files)
    log.info(f"Found {total} file(s)")
    log.info(f"Discovery done: scanned {scanned_entries} filesystem entries in {discovery_time:.2f}s")
    if emit_folder:
        emit_json("run_folder", root=str(root), total=total)

    workers = max(1, int(workers or 1))
    if workers > 1:
        log.info(f"Workers: {workers}")

    ok = skip = fail = 0
    probe_check_time = 0.0
    conversion_time = 0.0
    size_rows: list[tuple[str, int, int]] = []
    progress_started = time.perf_counter()
    progress_last_print = 0.0
    if workers <= 1:
        converting_progress: dict[str, float] = {}
        progress_cb_lock = threading.Lock()
        progress_changed = threading.Event()
        _last_reported_pct: dict[str, float] = {}

        def on_progress(
            file: Path,
            pct: float | None,
            finalizing: bool = False,
            position_seconds: float | None = None,
            duration_seconds: float | None = None,
            frame_count: int | None = None,
            total_frames: int | None = None,
        ):
            emit_json(
                "progress",
                file=str(file),
                percent=pct,
                finalizing=finalizing,
                position_seconds=position_seconds,
                duration_seconds=duration_seconds,
                frame_count=frame_count,
                total_frames=total_frames,
            )
            if not JSON_MODE:
                with progress_cb_lock:
                    key = file.resolve().as_posix()
                    if pct is None:
                        converting_progress.pop(key, None)
                    else:
                        converting_progress[key] = pct
                progress_changed.set()

        if JSON_MODE:
            progress_done = True
            ticker = None
        else:
            draw_progress_bar(0, total, 0, 0, 0, progress_started, {})
            progress_done = False

            def progress_ticker():
                while not progress_done:
                    progress_changed.wait(0.5)
                    progress_changed.clear()
                    with progress_cb_lock:
                        snap = dict(converting_progress)
                    draw_progress_bar(0, total, ok, skip, fail, progress_started, snap)

            ticker = threading.Thread(target=progress_ticker, daemon=True)
            ticker.start()

        emit_json("run_status", phase="process", message=f"Processing {total} file(s)...")
        log.info(f"Processing {total} file(s)...")
        for i, f in enumerate(files, 1):
            emit_json("run_status", phase="checking", message=f"Checking: {f}")
            path = f.resolve().as_posix()
            current_opt = conversion_option(crf, min_savings_pct)

            try:
                st = f.stat()
            except FileNotFoundError:
                skip += 1
                log.info(f"[{i}/{total}] SKIP: {f} :: missing")
                emit_json("result", file=str(f), status="SKIP", msg="missing")
                print_progress(i, total, ok, skip, fail, progress_started, workers)
                continue
            size = int(st.st_size)
            mtime_ns = int(st.st_mtime_ns)

            if done.get(path) == current_opt:
                skip += 1
                log.info(f"[{i}/{total}] SKIP: {f} :: already_done")
                emit_json("result", file=str(f), status="SKIP", msg="already_done")
                print_progress(i, total, ok, skip, fail, progress_started, workers)
                continue

            cache_entry = probe_cache.get(path)
            if (
                isinstance(cache_entry, dict)
                and cache_entry.get("opt") == current_opt
                and cache_entry.get("size") == size
                and cache_entry.get("mtime_ns") == mtime_ns
                and cache_entry.get("status") == "SKIP"
            ):
                skip += 1
                cached_msg = cache_entry.get("msg", "cached_skip")
                log.info(f"[{i}/{total}] SKIP: {f} :: cache({cached_msg})")
                emit_json("result", file=str(f), status="SKIP", msg=f"cache({cached_msg})")
                print_progress(i, total, ok, skip, fail, progress_started, workers)
                continue

            if dry_run:
                br = get_estimated_bitrate_kbps(f)
                if br is not None and br <= MAX_BR:
                    skip += 1
                    log.info(f"[{i}/{total}] WOULD_SKIP: {f} :: ok({br}kbps)")
                    emit_json("result", file=str(f), status="SKIP", msg=f"would_skip(ok({br}kbps))")
                else:
                    ok += 1
                    log.info(f"[{i}/{total}] WOULD_CONVERT: {f} :: {br or 'unknown'} kbps")
                    emit_json("result", file=str(f), status="OK", msg=f"would_convert({br or 'unknown'}kbps)")
                print_progress(i, total, ok, skip, fail, progress_started, workers)
                continue

            log.info(f"[{i}/{total}] Checking: {f}")
            check_started = time.perf_counter()
            status, msg, size_row = convert_if_needed(f, crf, verbose, min_savings_pct, show_progress=True, progress_callback=on_progress)
            on_progress(f, None)
            elapsed = time.perf_counter() - check_started

            with progress_cb_lock:
                converting_progress.pop(path, None)

            if status == "OK":
                conversion_time += elapsed
                ok += 1
                done[path] = current_opt
                save_done(done)
                if path in probe_cache:
                    del probe_cache[path]
                    probe_cache_dirty = True
                if size_row:
                    size_rows.append(size_row)
                log.info(f"[{i}/{total}] OK: {f} :: {msg}")
                emit_json("result", file=str(f), status="OK", msg=msg,
                          before=size_row[1] if size_row else 0,
                          after=size_row[2] if size_row else 0)
            elif status == "SKIP":
                skip += 1
                if not str(msg).startswith("failure_cooldown("):
                    probe_cache[path] = {
                        "size": size,
                        "mtime_ns": mtime_ns,
                        "opt": current_opt,
                        "status": "SKIP",
                        "msg": msg,
                    }
                    probe_check_time += elapsed
                    probe_cache_dirty = True
                    if msg.startswith(("savings_too_small(", "output_larger(")):
                        save_probe_cache(probe_cache)
                        probe_cache_dirty = False
                log.info(f"[{i}/{total}] SKIP: {f} :: {msg}")
                emit_json("result", file=str(f), status="SKIP", msg=msg)
            else:
                if str(msg).startswith("ffmpeg_failed") or str(msg).startswith("replace_failed"):
                    conversion_time += elapsed
                else:
                    probe_check_time += elapsed
                fail += 1
                if path in probe_cache:
                    del probe_cache[path]
                    probe_cache_dirty = True
                log.error(f"[{i}/{total}] FAIL: {f} :: {msg}")
                emit_json("result", file=str(f), status="FAIL", msg=msg)
            if probe_cache_dirty:
                save_probe_cache(probe_cache)
                probe_cache_dirty = False
            print_progress(i, total, ok, skip, fail, progress_started, workers)

        if not JSON_MODE:
            progress_done = True
            ticker.join(timeout=3)
            if _progress_lines > 0:
                sys.stderr.write(f"\033[{_progress_lines}A\033[J")
                sys.stderr.flush()
            sys.stderr.write("\n")
            sys.stderr.flush()
    else:
        done_lock = threading.Lock()
        probe_cache_snapshot = dict(probe_cache)

        converting_progress: dict[str, float] = {}
        progress_cb_lock = threading.Lock()
        progress_changed = threading.Event()

        def on_progress(
            file: Path,
            pct: float | None,
            finalizing: bool = False,
            position_seconds: float | None = None,
            duration_seconds: float | None = None,
            frame_count: int | None = None,
            total_frames: int | None = None,
        ):
            emit_json(
                "progress",
                file=str(file),
                percent=pct,
                finalizing=finalizing,
                position_seconds=position_seconds,
                duration_seconds=duration_seconds,
                frame_count=frame_count,
                total_frames=total_frames,
            )
            with progress_cb_lock:
                key = file.resolve().as_posix()
                if pct is None:
                    converting_progress.pop(key, None)
                else:
                    converting_progress[key] = pct
            progress_changed.set()

        def process_file(i: int, f: Path) -> dict:
            emit_json("run_status", phase="checking", message=f"Checking: {f}")
            path = f.resolve().as_posix()
            current_opt = conversion_option(crf, min_savings_pct)

            try:
                st = f.stat()
            except FileNotFoundError:
                log.info(f"[{i}/{total}] SKIP: {f} :: missing")
                return {"status": "SKIP", "msg": "missing", "file": f, "time_kind": None, "elapsed": 0.0}

            size = int(st.st_size)
            mtime_ns = int(st.st_mtime_ns)

            with done_lock:
                already_done = done.get(path) == current_opt
            if already_done:
                log.info(f"[{i}/{total}] SKIP: {f} :: already_done")
                return {"status": "SKIP", "msg": "already_done", "file": f, "time_kind": None, "elapsed": 0.0}

            cache_entry = probe_cache_snapshot.get(path)
            if (
                isinstance(cache_entry, dict)
                and cache_entry.get("opt") == current_opt
                and cache_entry.get("size") == size
                and cache_entry.get("mtime_ns") == mtime_ns
                and cache_entry.get("status") == "SKIP"
            ):
                cached_msg = cache_entry.get("msg", "cached_skip")
                log.info(f"[{i}/{total}] SKIP: {f} :: cache({cached_msg})")
                return {"status": "SKIP", "msg": f"cache({cached_msg})", "file": f, "time_kind": None, "elapsed": 0.0}

            if dry_run:
                br = get_estimated_bitrate_kbps(f)
                if br is not None and br <= MAX_BR:
                    log.info(f"[{i}/{total}] WOULD_SKIP: {f} :: ok({br}kbps)")
                    return {"status": "SKIP", "msg": f"would_skip(ok({br}kbps))", "file": f, "time_kind": None, "elapsed": 0.0}
                else:
                    log.info(f"[{i}/{total}] WOULD_CONVERT: {f} :: {br or 'unknown'} kbps")
                    return {"status": "OK", "msg": f"would_convert({br or 'unknown'}kbps)", "file": f, "time_kind": None, "elapsed": 0.0}

            log.info(f"[{i}/{total}] Checking: {f}")
            check_started = time.perf_counter()
            try:
                status, msg, size_row = convert_if_needed(f, crf, verbose, min_savings_pct, show_progress=True, progress_callback=on_progress)
            finally:
                on_progress(f, None)
                with progress_cb_lock:
                    converting_progress.pop(path, None)
            elapsed = time.perf_counter() - check_started

            result = {
                "status": status,
                "msg": msg,
                "path": path,
                "file": f,
                "size_row": size_row,
                "elapsed": elapsed,
                "time_kind": "conversion" if status == "OK" else "probe_check",
                "cache_delete": False,
                "cache_update": None,
            }

            if status == "OK":
                with done_lock:
                    done[path] = current_opt
                    save_done(done)
                result["cache_delete"] = True
                log.info(f"[{i}/{total}] OK: {f} :: {msg}")
            elif status == "SKIP":
                if not str(msg).startswith("failure_cooldown("):
                    result["cache_update"] = {
                        "size": size,
                        "mtime_ns": mtime_ns,
                        "opt": current_opt,
                        "status": "SKIP",
                        "msg": msg,
                    }
                log.info(f"[{i}/{total}] SKIP: {f} :: {msg}")
            else:
                if str(msg).startswith("ffmpeg_failed") or str(msg).startswith("replace_failed"):
                    result["time_kind"] = "conversion"
                result["cache_delete"] = True
                log.error(f"[{i}/{total}] FAIL: {f} :: {msg}")

            return result

        par_completed = 0
        par_ok = 0
        par_skip = 0
        par_fail = 0
        progress_start = time.perf_counter()
        progress_done = False

        if JSON_MODE:
            ticker = None
        else:
            draw_progress_bar(0, total, 0, 0, 0, progress_start, {})

            def progress_ticker():
                while not progress_done:
                    progress_changed.wait(0.5)
                    progress_changed.clear()
                    with progress_cb_lock:
                        snap = dict(converting_progress)
                    draw_progress_bar(par_completed, total, par_ok, par_skip, par_fail, progress_start, snap)

            ticker = threading.Thread(target=progress_ticker, daemon=True)
            ticker.start()

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(process_file, i, f): f for i, f in enumerate(files, 1)}
            for future in as_completed(futures):
                f = futures[future]
                par_completed += 1
                try:
                    result = future.result()
                except Exception as e:
                    par_fail += 1
                    log.exception(f"FAIL: {f} :: unhandled_worker_exception: {e}")
                    emit_json("result", file=str(f), status="FAIL", msg=f"unhandled_worker_exception: {e}")
                    continue

                status = result.get("status")
                if status == "OK":
                    par_ok += 1
                elif status == "SKIP":
                    par_skip += 1
                else:
                    par_fail += 1

                size_row = result.get("size_row")
                emit_json(
                    "result",
                    file=str(result.get("file") or f),
                    status=status or "FAIL",
                    msg=result.get("msg") or "",
                    before=size_row[1] if size_row else 0,
                    after=size_row[2] if size_row else 0,
                )

                elapsed = float(result.get("elapsed") or 0.0)
                if result.get("time_kind") == "conversion":
                    conversion_time += elapsed
                elif result.get("time_kind") == "probe_check":
                    probe_check_time += elapsed

                path = result.get("path")
                if path and result.get("cache_delete") and path in probe_cache:
                    del probe_cache[path]
                    probe_cache_dirty = True
                cache_update = result.get("cache_update")
                if path and cache_update:
                    probe_cache[path] = cache_update
                    probe_cache_dirty = True
                    if str(result.get("msg") or "").startswith(("savings_too_small(", "output_larger(")):
                        save_probe_cache(probe_cache)
                        probe_cache_dirty = False
                if size_row:
                    size_rows.append(size_row)
                if probe_cache_dirty:
                    save_probe_cache(probe_cache)
                    probe_cache_dirty = False

                if not JSON_MODE:
                    with progress_cb_lock:
                        snap = dict(converting_progress)
                    draw_progress_bar(par_completed, total, par_ok, par_skip, par_fail, progress_start, snap)
                    progress_changed.set()

                now = time.perf_counter()
                if now - progress_last_print >= 5 or par_completed == total:
                    print_progress(par_completed, total, par_ok, par_skip, par_fail, progress_start, workers)
                    progress_last_print = now

        progress_done = True
        if not JSON_MODE:
            ticker.join(timeout=3)
            if _progress_lines > 0:
                sys.stderr.write(f"\033[{_progress_lines}A\033[J")
                sys.stderr.flush()
        ok, skip, fail = par_ok, par_skip, par_fail

    if probe_cache_dirty:
        log.info(f"Saving probe cache ({len(probe_cache)} entries)...")
        save_probe_cache(probe_cache)

    append_size_report(size_rows)
    total_saved_mb = sum((r[1] - r[2]) / (1024 * 1024) for r in size_rows if len(r) >= 3)
    log.info(
        f"Timing: discovery={discovery_time:.2f}s, probe_check={probe_check_time:.2f}s, conversion={conversion_time:.2f}s"
    )
    log.info(f"Done. OK={ok} SKIP={skip} FAIL={fail} (saved {total_saved_mb:.1f} MB)")
    emit_json("run_status", phase="done", message=f"Done. OK={ok} SKIP={skip} FAIL={fail}")
    emit_json("summary", files_total=total, ok=ok, skip=skip, fail=fail,
              space_saved_mb=round(total_saved_mb, 2))
    return ok, skip, fail, total_saved_mb


def _cleanup_local_tmp(local_file: Path, local_tmp_conv: Path, local_tmp: Path):
    for p in [local_file, local_tmp_conv]:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


def main_remote(host: str, remote_dir: str, local_tmp: Path, crf: int | None = None, verbose: bool = False):
    """Remote overwrite mode is disabled until atomic remote replacement is implemented."""
    log.error("FATAL: remote mode is disabled for media safety; use a local mounted path instead")
    return

    """Remote mode: download each file, convert locally with GPU, upload back."""
    local_tmp.mkdir(parents=True, exist_ok=True)

    if not ssh_ls(host, remote_dir):
        log.error(f"FATAL: remote path not accessible: {host}:{remote_dir}")
        return

    done = load_done()
    files = list_remote_videos(host, remote_dir)
    total = len(files)
    log.info(f"Remote scan: {total} file(s) on {host}:{remote_dir}")

    ok = skip = fail = 0
    size_rows: list[tuple[str, int, int]] = []

    for i, remote_file in enumerate(files, 1):
        current_opt = conversion_option(crf, min_savings_pct)
        key = f"{remote_file}|{current_opt}"

        if done.get(remote_file) == current_opt:
            skip += 1
            log.info(f"[{i}/{total}] SKIP: {remote_file} :: already_done")
            continue

        local_file = local_tmp / Path(remote_file).name
        local_tmp_conv = tmp_name_for(local_file)

        log.info(f"[{i}/{total}] Downloading: {remote_file}")
        if not scp_download(f"{host}:{remote_file}", local_file):
            fail += 1
            log.error(f"[{i}/{total}] FAIL: {remote_file} :: download_failed")
            continue

        log.info(f"[{i}/{total}] Checking: {local_file}")
        status, msg, size_row = convert_if_needed(local_file, crf, verbose)

        if status == "OK":
            remote_dest_dir = str(Path(remote_file).parent)
            ssh_mkdir(host, remote_dest_dir)

            log.info(f"[{i}/{total}] Uploading converted file...")
            if scp_upload(local_file, f"{host}:{remote_file}"):
                ok += 1
                done[remote_file] = current_opt
                save_done(done)
                if size_row:
                    size_rows.append((Path(remote_file).name, size_row[1], size_row[2]))
                log.info(f"[{i}/{total}] OK: {remote_file} :: {msg}")
            else:
                fail += 1
                log.error(f"[{i}/{total}] FAIL: {remote_file} :: upload_failed")

            # cleanup local temp files
            _cleanup_local_tmp(local_file, local_tmp_conv, local_tmp)

        elif status == "SKIP":
            skip += 1
            log.info(f"[{i}/{total}] SKIP: {remote_file} :: {msg}")
            _cleanup_local_tmp(local_file, local_tmp_conv, local_tmp)
        else:
            fail += 1
            log.error(f"[{i}/{total}] FAIL: {remote_file} :: {msg}")
            _cleanup_local_tmp(local_file, local_tmp_conv, local_tmp)

    append_size_report(size_rows)
    log.info(f"Done. OK={ok} SKIP={skip} FAIL={fail}")


def main_all(crf: int | None = None, verbose: bool = False, workers: int = 1, dry_run: bool = False, min_savings_pct: int = 0, ignore_paths: list[str] | None = None):
    config = load_config()
    if not config:
        log.error("FATAL: config.yml not found or invalid")
        return

    libraries = config.get("libraries") or []
    if not libraries:
        log.error("FATAL: no libraries defined in config.yml")
        return

    total_libraries = 0
    total_found = 0
    total_ok = 0
    total_skip = 0
    total_fail = 0
    total_space_mb = 0.0
    total_started = time.perf_counter()

    queued_libraries: list[tuple[str, list[str], dict | None, int, set[str], list[str], list[tuple[Path, list[Path], int, float]]]] = []
    for lib in libraries:
        lib_name = lib.get("name", "unknown")
        profile = _extract_profile(config, lib)
        lib_paths = normalize_library_paths(lib)

        if not lib_paths:
            log.warning(f"Library '{lib_name}' has no path, skipping")
            continue

        lib_workers, lib_excludes, lib_ignore = _library_run_settings(lib, workers, ignore_paths)

        log.info(f"=== Library: {lib_name} ===")
        scanned_paths = scan_library_paths(lib_name, lib_paths, lib_ignore, lib_excludes)
        if scanned_paths:
            queued_libraries.append((lib_name, lib_paths, profile, lib_workers, lib_excludes, lib_ignore, scanned_paths))

    for lib_name, lib_paths, profile, lib_workers, lib_excludes, lib_ignore, scanned_paths in queued_libraries:
        log.info(f"=== Processing library: {lib_name} ===")
        ok, skip, fail, space_mb, scanned_any = run_library_scan(
            lib_name, lib_paths, crf, verbose, lib_workers, dry_run, min_savings_pct, profile, lib_ignore, scanned_paths, lib_excludes
        )
        if not scanned_any:
            continue

        total_libraries += 1
        total_found += ok + skip + fail
        total_ok += ok
        total_skip += skip
        total_fail += fail
        total_space_mb += space_mb

    if not total_libraries:
        log.error("FATAL: no valid library paths found in config.yml")
        return

    total_elapsed = time.perf_counter() - total_started
    print_summary(total_libraries, total_found, total_ok, total_skip, total_fail, total_space_mb, total_elapsed)
    emit_json("summary", mode="all", library_count=total_libraries, files_total=total_found,
              ok=total_ok, skip=total_skip, fail=total_fail,
              space_saved_mb=round(total_space_mb, 2), elapsed=round(total_elapsed, 2))


def main_library(
    library_names: str | list[str],
    crf: int | None = None,
    verbose: bool = False,
    workers: int = 1,
    dry_run: bool = False,
    min_savings_pct: int = 0,
    ignore_paths: list[str] | None = None,
):
    if isinstance(library_names, str):
        requested_names = parse_name_list(library_names)
    else:
        requested_names = [name.strip() for name in library_names if name.strip()]

    if not requested_names:
        log.error("FATAL: no library names provided")
        return

    config = load_config()
    if not config:
        log.error("FATAL: config.yml not found or invalid")
        return

    total_libraries = 0
    total_found = 0
    total_ok = 0
    total_skip = 0
    total_fail = 0
    total_space_mb = 0.0
    total_started = time.perf_counter()

    queued_libraries: list[tuple[str, list[str], dict | None, int, set[str], list[str], list[tuple[Path, list[Path], int, float]]]] = []
    for library_name in requested_names:
        lib_info = find_library_config(config, library_name)
        if not lib_info:
            log.error(f"FATAL: library '{library_name}' not found in config.yml")
            continue

        lib_paths, profile, lib = lib_info
        if not lib_paths:
            log.error(f"FATAL: library '{library_name}' has no paths in config.yml")
            continue

        lib_workers, lib_excludes, lib_ignore = _library_run_settings(lib, workers, ignore_paths)

        log.info(f"=== Library: {library_name} ===")
        scanned_paths = scan_library_paths(library_name, lib_paths, lib_ignore, lib_excludes)
        if scanned_paths:
            queued_libraries.append((library_name, lib_paths, profile, lib_workers, lib_excludes, lib_ignore, scanned_paths))

    for library_name, lib_paths, profile, lib_workers, lib_excludes, lib_ignore, scanned_paths in queued_libraries:
        log.info(f"=== Processing library: {library_name} ===")
        ok, skip, fail, space_mb, scanned_any = run_library_scan(
            library_name, lib_paths, crf, verbose, lib_workers, dry_run, min_savings_pct, profile, lib_ignore, scanned_paths, lib_excludes
        )
        if not scanned_any:
            log.error(f"FATAL: library '{library_name}' has no valid paths")
            continue

        total_libraries += 1
        total_found += ok + skip + fail
        total_ok += ok
        total_skip += skip
        total_fail += fail
        total_space_mb += space_mb

    if not total_libraries:
        return

    total_elapsed = time.perf_counter() - total_started
    print_summary(total_libraries, total_found, total_ok, total_skip, total_fail, total_space_mb, total_elapsed)
    emit_json("summary", mode="library", library_count=total_libraries, files_total=total_found,
              ok=total_ok, skip=total_skip, fail=total_fail,
              space_saved_mb=round(total_space_mb, 2), elapsed=round(total_elapsed, 2))


def main_jellyfin_recent(
    library_names: list[str],
    since_hours: int = 72,
    crf: int | None = None,
    verbose: bool = False,
    workers: int = 1,
    dry_run: bool = False,
    min_savings_pct: int = 0,
    ignore_paths: list[str] | None = None,
):
    global TARGET_BR, MAX_BR, BUFSIZE, TRANSCODER, TRANSCODER_PROFILE, ALLOWED_AUDIO_LANGS, ALLOWED_SUBTITLE_LANGS
    try:
        from jellyfin_client import JellyfinClient
    except ImportError:
        log.error("FATAL: jellyfin_client.py not found")
        return

    client = JellyfinClient.from_env()
    if not client:
        log.error("FATAL: Jellyfin not configured. Set JELLYFIN_API_KEY and JELLYFIN_BASE_URL in .env")
        return

    config = load_config()
    emit_json("run_status", phase="jellyfin", message=f"Querying Jellyfin: {', '.join(library_names)}")
    all_recent_files: list[tuple[Path, str]] = []
    for lib_name in library_names:
        try:
            items = client.get_recent_items(lib_name.strip(), since_hours)
            log.info(f"Jellyfin library '{lib_name}': found {len(items)} recently added/updated item(s)")
            for item in items:
                p = Path(item["path"])
                if ignore_paths and any(seg in str(p) for seg in ignore_paths):
                    log.info(f"Ignoring (--ignore-path match): {p}")
                    continue
                all_recent_files.append((p, lib_name.strip()))
        except Exception as e:
            log.warning(f"Failed to query Jellyfin library '{lib_name}': {e}")

    client.close()

    if not all_recent_files:
        log.info("No recent files found to check")
        emit_json("run_status", phase="process", message="Found 0 recent file(s)", files_total=0)
        emit_json("summary", library_count=len(library_names), files_total=0, ok=0, skip=0, fail=0, space_saved_mb=0.0, elapsed=0.0)
        return

    # Deduplicate by path
    seen = set()
    unique_files: list[tuple[Path, str]] = []
    for p, lib_name in all_recent_files:
        key = str(p)
        if key not in seen:
            seen.add(key)
            unique_files.append((p, lib_name))

    unique_files.sort(key=lambda x: x[0].resolve().as_posix())
    log.info(f"Total unique files to check: {len(unique_files)}")
    emit_json("run_status", phase="process", message=f"Found {len(unique_files)} recent file(s)", files_total=len(unique_files))

    log.info(f"Loading progress and probe cache...")
    done = load_done()
    probe_cache = load_probe_cache()
    probe_cache_dirty = False

    ok = skip = fail = 0
    space_saved_mb = 0.0
    started = time.perf_counter()
    base_settings = (
        TARGET_BR, MAX_BR, BUFSIZE, TRANSCODER, TRANSCODER_PROFILE,
        set(ALLOWED_AUDIO_LANGS),
        set(ALLOWED_SUBTITLE_LANGS) if ALLOWED_SUBTITLE_LANGS is not None else None,
    )

    def on_progress(
        file: Path,
        pct: float | None,
        finalizing: bool = False,
        position_seconds: float | None = None,
        duration_seconds: float | None = None,
        frame_count: int | None = None,
        total_frames: int | None = None,
    ):
        emit_json(
            "progress",
            file=str(file),
            percent=pct,
            finalizing=finalizing,
            position_seconds=position_seconds,
            duration_seconds=duration_seconds,
            frame_count=frame_count,
            total_frames=total_frames,
        )

    for i, (file_path, lib_name) in enumerate(unique_files, 1):
        path = file_path.resolve().as_posix()
        emit_json("run_status", phase="checking", message=f"Checking: {file_path}", files_total=len(unique_files))
        profile = None
        (TARGET_BR, MAX_BR, BUFSIZE, TRANSCODER, TRANSCODER_PROFILE,
         ALLOWED_AUDIO_LANGS, ALLOWED_SUBTITLE_LANGS) = base_settings

        # Apply profile settings for this library
        if config:
            lib_info = find_library_config(config, lib_name)
            if lib_info:
                _path, profile, _lib = lib_info
                if profile:
                    set_profile_globals(profile)

        effective_min_savings = max(
            min_savings_pct,
            int(profile.get("minimum_savings_percent", 0)) if profile else 0,
        )
        current_opt = conversion_option(crf, effective_min_savings)

        if done.get(path) == current_opt:
            skip += 1
            log.info(f"[{i}/{len(unique_files)}] SKIP: {file_path} :: already_done")
            emit_json("result", file=str(file_path), status="SKIP", msg="already_done")
            continue

        try:
            st = file_path.stat()
        except FileNotFoundError:
            skip += 1
            log.info(f"[{i}/{len(unique_files)}] SKIP: {file_path} :: missing")
            emit_json("result", file=str(file_path), status="SKIP", msg="missing")
            continue

        size = int(st.st_size)
        mtime_ns = int(st.st_mtime_ns)

        cache_entry = probe_cache.get(path)
        if (
            isinstance(cache_entry, dict)
            and cache_entry.get("opt") == current_opt
            and cache_entry.get("size") == size
            and cache_entry.get("mtime_ns") == mtime_ns
            and cache_entry.get("status") == "SKIP"
        ):
            skip += 1
            cached_msg = cache_entry.get("msg", "cached_skip")
            log.info(f"[{i}/{len(unique_files)}] SKIP: {file_path} :: cache({cached_msg})")
            emit_json("result", file=str(file_path), status="SKIP", msg=f"cache({cached_msg})")
            continue

        if dry_run:
            br = get_estimated_bitrate_kbps(file_path)
            if br is not None and br <= MAX_BR:
                skip += 1
                log.info(f"[{i}/{len(unique_files)}] WOULD_SKIP: {file_path} :: ok({br}kbps)")
                emit_json("result", file=str(file_path), status="SKIP", msg=f"would_skip(ok({br}kbps))")
            else:
                ok += 1
                log.info(f"[{i}/{len(unique_files)}] WOULD_CONVERT: {file_path} :: {br or 'unknown'} kbps")
                emit_json("result", file=str(file_path), status="OK", msg=f"would_convert({br or 'unknown'}kbps)")
            continue

        log.info(f"[{i}/{len(unique_files)}] Checking: {file_path}")
        status, msg, size_row = convert_if_needed(file_path, crf, verbose, effective_min_savings, show_progress=True, progress_callback=on_progress)
        on_progress(file_path, None)

        if status == "OK":
            ok += 1
            done[path] = current_opt
            save_done(done)
            if path in probe_cache:
                del probe_cache[path]
                probe_cache_dirty = True
            before = size_row[1] if size_row else 0
            after = size_row[2] if size_row else 0
            if size_row:
                saved_mb = (size_row[1] - size_row[2]) / (1024 * 1024)
                space_saved_mb += saved_mb
            log.info(f"[{i}/{len(unique_files)}] OK: {file_path} :: {msg}")
            emit_json("result", file=str(file_path), status="OK", msg=msg, before=before, after=after)
        elif status == "SKIP":
            skip += 1
            if not str(msg).startswith("failure_cooldown("):
                probe_cache[path] = {
                    "size": size, "mtime_ns": mtime_ns,
                    "opt": current_opt, "status": "SKIP", "msg": msg,
                }
                probe_cache_dirty = True
                if msg.startswith(("savings_too_small(", "output_larger(")):
                    save_probe_cache(probe_cache)
                    probe_cache_dirty = False
            log.info(f"[{i}/{len(unique_files)}] SKIP: {file_path} :: {msg}")
            emit_json("result", file=str(file_path), status="SKIP", msg=msg)
        else:
            fail += 1
            if path in probe_cache:
                del probe_cache[path]
                probe_cache_dirty = True
            log.error(f"[{i}/{len(unique_files)}] FAIL: {file_path} :: {msg}")
            emit_json("result", file=str(file_path), status="FAIL", msg=msg)
        if probe_cache_dirty:
            save_probe_cache(probe_cache)
            probe_cache_dirty = False

    (TARGET_BR, MAX_BR, BUFSIZE, TRANSCODER, TRANSCODER_PROFILE,
     ALLOWED_AUDIO_LANGS, ALLOWED_SUBTITLE_LANGS) = base_settings

    elapsed = time.perf_counter() - started
    print_summary(len(library_names), len(unique_files), ok, skip, fail, space_saved_mb, elapsed)
    emit_json("run_status", phase="done", message=f"Done. OK={ok} SKIP={skip} FAIL={fail}", files_total=len(unique_files))
    emit_json("summary", library_count=len(library_names), files_total=len(unique_files),
              ok=ok, skip=skip, fail=fail, space_saved_mb=round(space_saved_mb, 2),
              elapsed=round(elapsed, 2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Convert oversized video files in Jellyfin media libraries.

Modes:
  Direct path      python convert.py /path/to/media
  Config --all     python convert.py --all
  Config --library python convert.py --library Shows
  Jellyfin recent  python convert.py --jellyfin-recent --libraries Shows,Movies --since-hours 72""")
    parser.add_argument("--bitrate", type=int, help="Set target video bitrate (kbps)")
    parser.add_argument("--crf", type=int, help="Use CRF mode with this value")
    parser.add_argument("dir", nargs="?", default="", help="Directory to scan recursively")
    parser.add_argument("--remote", default="", help="Remote target: user@host:/path")
    parser.add_argument("--local-tmp", default="", help="Local temp dir for remote mode")
    parser.add_argument("--log-file", default="", help="Path to log file (optional)")
    parser.add_argument("--exclude", default=DEFAULT_EXCLUDE_PATTERNS, help="Comma-separated directory names to skip")
    parser.add_argument("--ignore-path", action="append", default=[], help="Skip paths containing this substring (repeatable, e.g. --ignore-path media1t)")
    parser.add_argument("--cleanup-tmp", action="store_true", default=CLEANUP_TMP, help="Clean temp files before discovery")
    parser.add_argument("--use", default="", help="Transcoder profile or ffmpeg encoder name")
    parser.add_argument("-j", "--workers", type=int, default=DEFAULT_WORKERS, help="Number of files to process concurrently")
    parser.add_argument("--verbose", action="store_true", help="More logs (debug)")
    parser.add_argument("--all", action="store_true", help="Convert all libraries defined in config.yml")
    parser.add_argument("--library", default="", help="Convert one library defined in config.yml")
    parser.add_argument("--jellyfin-recent", action="store_true", help="Check recently added Jellyfin items")
    parser.add_argument("--libraries", default="", help="Comma-separated Jellyfin library names (for --jellyfin-recent)")
    parser.add_argument("--since-hours", type=int, default=72, help="Hours back for recent items (default: 72)")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would be done without modifying files")
    parser.add_argument("--min-savings", type=int, default=0, help="Minimum savings percent to keep converted file (default: 0 = disabled)")
    parser.add_argument("--keep-original", action="store_true", default=BACKUP_ORIGINALS, help="Keep a backup of the original file before replacing it")
    parser.add_argument("--stats", action="store_true", help="Show conversion history from size-report.csv")
    parser.add_argument("--json", action="store_true", help="Output structured JSON lines for web UI")
    args = parser.parse_args()

    if args.json:
        JSON_MODE = True

    if args.stats:
        show_stats()
        raise SystemExit(0)

    log_path = Path(args.log_file).expanduser().resolve() if args.log_file else None
    min_savings_pct = args.min_savings if args.min_savings is not None else DEFAULT_MIN_SAVINGS_PCT
    ignore_paths: list[str] = args.ignore_path or []
    if DEFAULT_IGNORE_PATH:
        for part in DEFAULT_IGNORE_PATH.split(","):
            p = part.strip()
            if p and p not in ignore_paths:
                ignore_paths.append(p)
    BACKUP_ORIGINALS = args.keep_original

    # Determine mode for auto log path
    mode_name = "direct"
    if args.all:
        mode_name = "all"
    elif args.library:
        mode_name = f"library-{args.library.replace(',', '_').replace(' ', '_')}"
    elif args.jellyfin_recent:
        mode_name = "jellyfin-recent"
    elif args.remote:
        mode_name = "remote"

    if not log_path:
        log_path = make_auto_log_path(mode_name)

    setup_logging(log_path, args.verbose)

    if args.bitrate:
        TARGET_BR = args.bitrate
        MAX_BR = TARGET_BR + 1000
        BUFSIZE = MAX_BR * 2

    crf = args.crf if args.crf else None

    if not resolve_ffmpeg_tools():
        log.error("FATAL: ffmpeg/ffprobe not found in PATH")
        raise SystemExit(1)

    if args.use:
        ok, err = resolve_transcoder(args.use)
        if not ok:
            log.error(f"FATAL: {err}")
            raise SystemExit(1)

    startup_log_path = str(log_path)

    if args.all:
        library_names = []
        config = load_config()
        if config:
            for lib in (config.get("libraries") or []):
                n = lib.get("name", "")
                if n:
                    library_names.append(n)
        print_startup_banner("All libraries (config.yml)", library_names or None,
            encoder=TRANSCODER, target_br=TARGET_BR, max_br=MAX_BR,
            dry_run=args.dry_run, log_path=startup_log_path, workers=args.workers)
        try:
            main_all(crf, args.verbose, args.workers, args.dry_run, min_savings_pct, ignore_paths)
        except Exception:
            log.exception("Unhandled exception")
        write_per_run_size_report(log_path)
    elif args.library:
        library_names = parse_name_list(args.library)
        print_startup_banner(f"Library: {args.library}", library_names or [args.library],
            encoder=TRANSCODER, target_br=TARGET_BR, max_br=MAX_BR,
            dry_run=args.dry_run, log_path=startup_log_path, workers=args.workers)
        try:
            main_library(library_names, crf, args.verbose, args.workers, args.dry_run, min_savings_pct, ignore_paths)
        except Exception:
            log.exception("Unhandled exception")
        write_per_run_size_report(log_path)
    elif args.jellyfin_recent:
        libs = [l.strip() for l in args.libraries.split(",") if l.strip()] if args.libraries else []
        if not libs:
            log.error("FATAL: --libraries is required with --jellyfin-recent (e.g. --libraries Shows,Movies)")
            raise SystemExit(1)
        print_startup_banner("Jellyfin recent", libs, args.since_hours,
            encoder=TRANSCODER, target_br=TARGET_BR, max_br=MAX_BR,
            dry_run=args.dry_run, log_path=startup_log_path, workers=args.workers)
        try:
            main_jellyfin_recent(libs, args.since_hours, crf, args.verbose, args.workers, args.dry_run, min_savings_pct, ignore_paths)
        except Exception:
            log.exception("Unhandled exception")
        write_per_run_size_report(log_path)
    elif args.remote:
        host, remote_dir = parse_remote_target(args.remote)
        local_tmp = Path(args.local_tmp).expanduser().resolve() if args.local_tmp else Path("/tmp/convert-remote")
        print_startup_banner("Remote (SCP)", [f"{host}:{remote_dir}"],
            encoder=TRANSCODER, target_br=TARGET_BR, max_br=MAX_BR,
            dry_run=args.dry_run, log_path=startup_log_path, workers=args.workers)
        try:
            main_remote(host, remote_dir, local_tmp, crf, args.verbose)
        except KeyboardInterrupt:
            pass
        except Exception:
            log.exception("Unhandled exception")
        write_per_run_size_report(log_path)
    else:
        scan_dir = args.dir or "."
        print_startup_banner("Direct path", [str(Path(scan_dir).expanduser().resolve())],
            encoder=TRANSCODER, target_br=TARGET_BR, max_br=MAX_BR,
            dry_run=args.dry_run, log_path=startup_log_path, workers=args.workers)
        try:
            main(scan_dir, crf, args.verbose, parse_exclude_dirs(args.exclude), args.cleanup_tmp, args.workers, min_savings_pct, args.dry_run, ignore_paths)
        except KeyboardInterrupt:
            pass
        except Exception:
            log.exception("Unhandled exception")
        write_per_run_size_report(log_path)

#!/usr/bin/env python3
"""Interactive setup wizard for media-convert-for-jellyfin (venv-based)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR / "src"))
VENV_DIR = BASE_DIR / ".venv"
CONVERT_PY = BASE_DIR / "src" / "convert.py"
ENV_FILE = BASE_DIR / ".env"
CONFIG_FILE = BASE_DIR / "config.yml"
REQUIREMENTS = BASE_DIR / "requirements.txt"
WRAPPER = BASE_DIR / "scripts" / "convert.sh"


def ask(prompt: str, default: str = "") -> str:
    if default:
        val = input(f"{prompt} [{default}]: ").strip()
        return val if val else default
    return input(f"{prompt}: ").strip()


def ask_yesno(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    val = input(f"{prompt} [{hint}]: ").strip().lower()
    if not val:
        return default
    return val.startswith("y")


def step(msg: str):
    print(f"\n── {msg} ──")


def ok(msg: str = "OK"):
    print(f"  ✓ {msg}")


def fail(msg: str):
    print(f"  ✗ {msg}")


def get_venv_python() -> str:
    if os.name == "nt":
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python")


def get_venv_pip() -> list[str]:
    return [get_venv_python(), "-m", "pip"]


def create_venv():
    step("Virtual Environment")
    if VENV_DIR.exists():
        ok(f"venv already exists at {VENV_DIR}")
    else:
        r = subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            fail(f"Failed to create venv: {r.stderr}")
            sys.exit(1)
        ok(f"Created venv at {VENV_DIR}")

    python = get_venv_python()
    r = subprocess.run([python, "--version"], capture_output=True, text=True, timeout=10)
    ok(f"venv Python: {r.stdout.strip()}")


def install_deps():
    step("Dependencies")
    pip = get_venv_pip()
    r = subprocess.run(
        [*pip, "install", "-q", "-r", str(REQUIREMENTS)],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode == 0:
        ok("Python packages installed")
    else:
        fail(f"pip install failed: {r.stderr}")


def check_command(name: str) -> str | None:
    path = shutil.which(name)
    if path:
        r = subprocess.run([name, "-version"], capture_output=True, text=True, timeout=10)
        version = r.stdout.splitlines()[0] if r.stdout else "?"
        ok(f"{name} found: {path} ({version})")
        return path
    fail(f"{name} not found in PATH")
    return None


def detect_encoder() -> str:
    try:
        python = get_venv_python()
        r = subprocess.run(
            [python, str(BASE_DIR / "src" / "_detect_encoder.py")],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            fail(f"detection stderr: {r.stderr.strip()}")
            return "cpu"
        detected = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "cpu"
        ok(f"Detected: {detected}")
        return detected
    except Exception as e:
        fail(f"detection error: {e}")
        return "cpu"


def read_env_value(key: str) -> str | None:
    if not ENV_FILE.exists():
        return None
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip()
    return None


def configure_env():
    if ENV_FILE.exists():
        if not ask_yesno(f".env already exists. Keep existing settings?", True):
            if not ask_yesno("Overwrite .env with new values?", False):
                ok("Keeping existing .env")
                return
        else:
            ok("Keeping existing .env")
            return

    step("Jellyfin Server")
    existing_url = read_env_value("JELLYFIN_BASE_URL") or "http://localhost:8096"
    existing_key = read_env_value("JELLYFIN_API_KEY") or ""
    url = ask("Jellyfin server URL", existing_url)
    key = ask("Jellyfin API key (create in Dashboard > API Keys)", existing_key)

    step("Bitrate Settings")
    existing_target = read_env_value("TARGET_BR") or "3000"
    existing_max = read_env_value("MAX_BR") or "3300"
    target_br = ask("Target bitrate (kbps)", existing_target)
    max_br = ask("ffmpeg burst max (kbps)", existing_max)

    content = f"""# ── Conversion Settings ───────────────────────
TARGET_BR={target_br}
MAX_BR={max_br}
BUFSIZE={int(max_br) * 2}
DEFAULT_CRF=23

# ── Jellyfin API (for --jellyfin-recent mode) ──
JELLYFIN_BASE_URL={url}
JELLYFIN_API_KEY={key}

# ── FFmpeg overrides (optional) ───────────────
# FFMPEG_BIN=
# FFPROBE_BIN=
"""
    ENV_FILE.write_text(content)
    ok(f".env written to {ENV_FILE}")


PRESETS = {
    "1": {"label": "Maximum shrink", "target": 2000, "max": 3000, "desc": "Great for 1080p TV, saves ~60-70%"},
    "2": {"label": "Balanced",       "target": 3000, "max": 4500, "desc": "Sweet spot, most people use this"},
    "3": {"label": "Quality",        "target": 5000, "max": 7000, "desc": "Near-lossless for 1080p"},
    "4": {"label": "4K high quality","target": 10000,"max": 15000, "desc": "For 2160p content"},
    "5": {"label": "Custom",         "target": None, "max": None, "desc": "Set your own numbers"},
}


def pick_preset() -> dict:
    for key, p in PRESETS.items():
        bits = f"{p['target']}k / max {p['max']}k" if p["target"] else "custom"
        print(f"  [{key}] {p['label']:18s}  {bits:28s}  {p['desc']}")
    choice = ask("Pick a preset", "2")
    preset = PRESETS.get(choice)
    if not preset:
        preset = PRESETS["2"]
    if preset["target"] is not None:
        ok(f"Preset: {preset['label']}")
        return dict(preset)
    # Custom
    t = int(ask("Target bitrate (kbps)", "3000"))
    m = int(ask("Max bitrate / ffmpeg burst (kbps)", str(int(t * 1.5))))
    return {"target": t, "max": m, "label": "Custom"}


def discover_jellyfin_libraries() -> list[dict] | None:
    """Try to fetch library names + paths from Jellyfin API using .env credentials."""
    api_key = read_env_value("JELLYFIN_API_KEY")
    base_url = read_env_value("JELLYFIN_BASE_URL")
    if not api_key or not base_url:
        return None
    try:
        from jellyfin_client import JellyfinClient
        client = JellyfinClient(base_url, api_key)
        libs = client.list_libraries()
        # Get paths for each library
        result = []
        for lib in libs:
            paths = client.get_library_paths(lib["name"])
            result.append({
                "name": lib["name"],
                "id": lib["id"],
                "paths": paths,
            })
        client.close()
        return result
    except Exception as e:
        fail(f"Could not reach Jellyfin: {e}")
        return None


def configure_webui_mcp(config: dict) -> dict:
    step("Web UI & MCP Server")
    print("  The web UI provides a browser interface at http://localhost:8080")
    print("  The MCP server provides REST endpoints for AI tools (opencode, etc.)")
    print()
    webui_enabled = ask_yesno("Enable web UI server?", True)
    webui_host = ask("Web UI host", "0.0.0.0")
    webui_port = int(ask("Web UI port", "8080"))
    mcp_enabled = ask_yesno("Enable MCP server?", True)
    mcp_host = ask("MCP host", "0.0.0.0")
    mcp_port = int(ask("MCP port", "9090"))
    config["webui"] = {"enabled": webui_enabled, "host": webui_host, "port": webui_port}
    config["mcp"] = {"enabled": mcp_enabled, "host": mcp_host, "port": mcp_port}
    return config


def configure_config():
    if CONFIG_FILE.exists():
        if not ask_yesno(f"config.yml already exists. Keep existing libraries?", True):
            if not ask_yesno("Overwrite config.yml with new libraries?", False):
                ok("Keeping existing config.yml")
                return
        else:
            ok("Keeping existing config.yml")
            return

    step("Media Libraries")

    libraries = []
    

    # Try discovering from Jellyfin
    jellyfin_libs = discover_jellyfin_libraries()
    if jellyfin_libs:
        ok(f"Found {len(jellyfin_libs)} Jellyfin libraries")
        for i, lib in enumerate(jellyfin_libs, 1):
            paths_str = ", ".join(lib["paths"]) if lib["paths"] else "(no paths)"
            print(f"  [{i:2d}] {lib['name']:12s}  {paths_str}")
        selected = ask("\nPick libraries to add (comma-separated numbers, or 0 for none)", "0")
        if selected.strip() != "0":
            for part in selected.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(jellyfin_libs):
                        lib = jellyfin_libs[idx]
                        paths = [p for p in lib["paths"] if p]
                        if not paths:
                            fail(f"No filesystem path for '{lib['name']}', skipping")
                            continue
                        libraries.append({"name": lib["name"], "paths": paths})

    if not libraries:
        if not ask_yesno("Add a media library manually?", True):
            return
        while True:
            name = ask("Library name (e.g. Shows, Movies)")
            raw_paths = ask("Full filesystem path(s) to this library (comma-separated)")
            paths = [p.strip() for p in raw_paths.split(",") if p.strip()]
            if not paths:
                fail(f"No filesystem paths entered for '{name}', skipping")
                if not ask_yesno("Add another library?", False):
                    break
                continue
            libraries.append({"name": name, "paths": paths})
            if not ask_yesno("Add another library?", False):
                break

    # Assign encoder settings for each library
    for lib_entry in libraries:
        name = lib_entry["name"]
        print(f"\n  ── {name} ──")
        paths = lib_entry.get("paths") or []
        if paths:
            for path in paths:
                print(f"     {path}")
        else:
            print("     (no paths)")
        preset = pick_preset()

        encoders = ["nvidia", "intel", "amdgpu", "cpu", "vaapi"]
        encoder = ask(f"Encoder profile ({', '.join(encoders)})", "nvidia")
        langs = ask("Audio languages to keep (comma-separated, e.g. eng,en,jpn,ja)", "eng,en,jpn,ja,hi,hin")
        savings = ask("Minimum savings percent (0 = disabled)", "10")

        lib_entry["target_bitrate"] = preset["target"]
        lib_entry["max_bitrate"] = preset["max"]
        lib_entry["encoder"] = encoder
        lib_entry["keep_audio_langs"] = [l.strip() for l in langs.split(",")]
        lib_entry["keep_subtitles"] = True
        lib_entry["minimum_savings_percent"] = int(savings)
        ok(f"'{name}' configured ({preset['label']})")

    import yaml
    config = {"libraries": libraries}
    config = configure_webui_mcp(config)
    CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False), encoding="utf-8")
    ok(f"config.yml written to {CONFIG_FILE}")


def create_wrapper():
    step("Wrapper Script")
    python = get_venv_python()
    content = f"""#!/usr/bin/env bash
# Auto-generated wrapper — runs convert.py inside .venv
cd "$(dirname "$0")"
exec "{python}" src/convert.py "$@"
"""
    WRAPPER.write_text(content)
    WRAPPER.chmod(0o755)
    ok(f"Created {WRAPPER}")


def pick_cron_schedule() -> str:
    print()
    print("  [1] Every 2 hours")
    print("  [2] Every 4 hours")
    print("  [3] Every 6 hours")
    print("  [4] Every 12 hours")
    print("  [5] Daily at 3am")
    print("  [6] Daily at 6am")
    print("  [7] Custom (enter raw cron expression)")
    choice = ask("Pick a schedule", "3")
    presets = {
        "1": "0 */2 * * *",
        "2": "0 */4 * * *",
        "3": "0 */6 * * *",
        "4": "0 */12 * * *",
        "5": "0 3 * * *",
        "6": "0 6 * * *",
    }
    expr = presets.get(choice)
    if expr:
        return expr
    return ask("Enter cron expression (e.g. 30 */4 * * *)")


def generate_cron_line(expr: str) -> str:
    wrapper = WRAPPER.resolve()
    return f"{expr} cd {BASE_DIR.resolve()} && {wrapper} --jellyfin-recent $(python3 -c \"import yaml; d=yaml.safe_load(open('config.yml')); print('--libraries ' + ','.join(l['name'] for l in d.get('libraries',[])))\" 2>/dev/null || echo '--libraries Shows,Movies') --since-hours 72"


def get_crontab() -> list[str]:
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return r.stdout.splitlines()
        if "no crontab" in (r.stdout + r.stderr).lower():
            return []
        return []
    except Exception:
        return []


def set_crontab(lines: list[str]):
    text = "\n".join(lines) + "\n" if lines else ""
    proc = subprocess.run(["crontab", "-"], input=text, capture_output=True, text=True, timeout=10)
    if proc.returncode != 0:
        fail(f"Failed to set crontab: {proc.stderr}")
        return False
    return True


def get_project_cron_indices(lines: list[str]) -> list[int]:
    tag = str(BASE_DIR.resolve())
    indices = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if tag in stripped and "convert.py" in stripped:
            indices.append(i)
    return indices


def cron_add(expr: str | None = None):
    if not expr:
        expr = pick_cron_schedule()
    new_line = generate_cron_line(expr)
    lines = get_crontab()
    existing = get_project_cron_indices(lines)
    if existing:
        ok("Cron job already exists (line {}). Remove it first with --cron-remove if you want to replace it.".format(existing[0] + 1))
        return False
    lines.append(new_line)
    if set_crontab(lines):
        ok(f"Cron job added ({expr})")
        print(f"  {new_line}")
        return True
    return False


def cron_remove():
    lines = get_crontab()
    indices = get_project_cron_indices(lines)
    if not indices:
        ok("No project cron job found")
        return True
    for i in reversed(indices):
        removed = lines.pop(i)
        print(f"  Removed: {removed.strip()}")
    if set_crontab(lines):
        ok(f"Removed {len(indices)} cron line(s)")
        return True
    return False


def cron_show():
    lines = get_crontab()
    indices = get_project_cron_indices(lines)
    if not indices:
        ok("No project cron job found")
        return
    print()
    for i in indices:
        print(f"  [{i+1}] {lines[i].strip()}")
    print()


def cron_edit():
    lines = get_crontab()
    indices = get_project_cron_indices(lines)
    if not indices:
        ok("No existing cron job to edit. Add one first.")
        return

    print("Current project cron jobs:")
    for i in indices:
        print(f"  [{i+1}] {lines[i].strip()}")
    print()

    for idx in reversed(indices):
        lines.pop(idx)

    expr = pick_cron_schedule()
    new_line = generate_cron_line(expr)
    lines.append(new_line)

    if set_crontab(lines):
        ok(f"Cron job updated ({expr})")
        print(f"  {new_line}")


def setup_cron():
    step("Cron Job")
    if not ask_yesno("Set up an automated cron job?", False):
        return

    cron_add()


def main():
    print()
    print("╔═══════════════════════════════════════════╗")
    print("║    Media Convert for Jellyfin — Setup     ║")
    print("╚═══════════════════════════════════════════╝")
    print()

    if sys.version_info < (3, 10):
        fail("Python 3.10+ required")
        sys.exit(1)
    ok(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")

    create_venv()
    install_deps()

    step("FFmpeg / FFprobe")
    ffmpeg = check_command("ffmpeg")
    ffprobe = check_command("ffprobe")
    if not ffmpeg or not ffprobe:
        fail("ffmpeg and ffprobe are required. Install them first.")
        sys.exit(1)

    step("GPU Encoder Detection")
    encoder = detect_encoder()

    step("Configuration (.env)")
    configure_env()

    step("Library Configuration (config.yml)")
    configure_config()

    create_wrapper()

    step("Cron")
    setup_cron()

    step("Summary")
    print("  ─────────────────────────────────────")
    print(f"  Venv        {VENV_DIR}")
    print(f"  FFmpeg      {ffmpeg or 'not found'}")
    print(f"  Encoder     {encoder}")
    print(f"  Wrapper     {WRAPPER}")
    print(f"  .env        {ENV_FILE}")
    print(f"  config.yml  {CONFIG_FILE}")
    print("  ─────────────────────────────────────")
    print()
    print("  Next steps")
    print(f"    1. Test:   {WRAPPER} --all --dry-run")
    print(f"    2. Run:    {WRAPPER} --all")
    print(f"    3. Check:  {WRAPPER} --jellyfin-recent --libraries Shows,Movies --since-hours 72")
    print(f"\n  All done!")


if __name__ == "__main__":
    import argparse as _argparse
    _p = _argparse.ArgumentParser(description="Setup and manage media-convert-for-jellyfin")
    _p.add_argument("--cron", choices=["add", "remove", "show", "edit"], help="Manage cron job without full setup")
    _a = _p.parse_args()

    if _a.cron:
        create_venv()
        install_deps()
        create_wrapper()
        if _a.cron == "add":
            cron_add()
        elif _a.cron == "remove":
            cron_remove()
        elif _a.cron == "show":
            cron_show()
        elif _a.cron == "edit":
            cron_edit()
    else:
        main()

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil
import state_db

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

import convert as conv
from webui.runner import start_run, get_run, get_active_runs, cleanup_run, stop_all_runs, _load_runs, RUNS_DIR

app = FastAPI(title="Media Convert for Jellyfin — Web UI")


@app.on_event("shutdown")
async def stop_runs_on_shutdown():
    await stop_all_runs()


def _run_list_entry(run: dict) -> dict:
    return {
        "run_id": run.get("run_id"),
        "library": run.get("library"),
        "started_at": run.get("started_at"),
        "ended_at": run.get("ended_at"),
        "running": run.get("running", False),
        "exit_code": run.get("exit_code"),
        "summary": run.get("summary", {}),
    }


def _load_config_safe():
    config = conv.load_config()
    if config is None:
        return {"config_found": False}
    return {
        "config_found": True,
        "libraries": config.get("libraries", []),
        "profiles": config.get("profiles", {}),
        "webui": config.get("webui", {"enabled": True, "host": "0.0.0.0", "port": 8080}),
        "mcp": config.get("mcp", {"enabled": True, "host": "0.0.0.0", "port": 9090}),
    }


def build_convert_cmd(req: dict) -> list[str]:
    python = sys.executable
    cmd = [python, str(Path(BASE_DIR) / "src" / "convert.py")]
    mode = req.get("mode", "direct")
    flags = req.get("flags", {}) or {}

    if mode == "all":
        cmd.append("--all")
    elif mode == "library":
        cmd.append("--library")
        cmd.append(req.get("library", ""))
    elif mode == "jellyfin_recent":
        cmd.append("--jellyfin-recent")
        libs = flags.get("libraries", req.get("library", ""))
        if libs:
            cmd.extend(["--libraries", libs])
        cmd.extend(["--since-hours", str(flags.get("since_hours", 72))])
    elif mode == "remote":
        remote = flags.get("remote", "") or req.get("directory", "")
        cmd.extend(["--remote", remote])
        if flags.get("local_tmp"):
            cmd.extend(["--local-tmp", flags["local_tmp"]])
    else:
        directory = req.get("directory", "")
        if directory:
            cmd.append(directory)

    f = flags
    if f.get("bitrate"):
        cmd.extend(["--bitrate", str(f["bitrate"])])
    if f.get("crf") is not None:
        cmd.extend(["--crf", str(f["crf"])])
    if f.get("use"):
        cmd.extend(["--use", f["use"]])
    if f.get("workers", 1) > 1:
        cmd.extend(["--workers", str(f["workers"])])
    if f.get("verbose"):
        cmd.append("--verbose")
    if f.get("dry_run"):
        cmd.append("--dry-run")
    if f.get("min_savings"):
        cmd.extend(["--min-savings", str(f["min_savings"])])
    if f.get("keep_original"):
        cmd.append("--keep-original")
    if f.get("exclude"):
        cmd.extend(["--exclude", f["exclude"]])
    for ip in f.get("ignore_path", []):
        if ip:
            cmd.extend(["--ignore-path", ip])
    if f.get("cleanup_tmp"):
        cmd.append("--cleanup-tmp")
    return cmd


# ── Config ──────────────────────────────────────────────────────────────────

@app.get("/api/config")
def api_config():
    return _load_config_safe()


@app.get("/api/env")
def api_env():
    return {
        "TARGET_BR": int(os.getenv("TARGET_BR", 3000)),
        "MAX_BR": int(os.getenv("MAX_BR", 3300)),
        "BUFSIZE": int(os.getenv("BUFSIZE", 6000)),
        "DEFAULT_CRF": int(os.getenv("DEFAULT_CRF", 23)),
        "JELLYFIN_BASE_URL": os.getenv("JELLYFIN_BASE_URL", ""),
        "DEFAULT_WORKERS": int(os.getenv("DEFAULT_WORKERS", "1")),
        "DEFAULT_EXCLUDE": os.getenv("DEFAULT_EXCLUDE", ""),
        "DEFAULT_IGNORE_PATH": os.getenv("DEFAULT_IGNORE_PATH", ""),
        "CLEANUP_TMP": os.getenv("CLEANUP_TMP", "0") == "1",
        "BACKUP_ORIGINALS": os.getenv("BACKUP_ORIGINALS", "0") == "1",
        "FFMPEG_BIN": os.getenv("FFMPEG_BIN", ""),
        "FFPROBE_BIN": os.getenv("FFPROBE_BIN", ""),
    }


@app.post("/api/env")
async def api_env_update(body: dict):
    overrides = {}
    accepted = (
        "TARGET_BR", "MAX_BR", "BUFSIZE", "DEFAULT_CRF",
        "JELLYFIN_BASE_URL", "JELLYFIN_API_KEY",
        "DEFAULT_WORKERS",
        "DEFAULT_EXCLUDE", "DEFAULT_IGNORE_PATH",
        "CLEANUP_TMP", "BACKUP_ORIGINALS",
        "FFMPEG_BIN", "FFPROBE_BIN",
    )
    for key in accepted:
        if key in body:
            overrides[key] = str(body[key])
    int_keys = ("TARGET_BR", "MAX_BR", "BUFSIZE", "DEFAULT_CRF", "DEFAULT_WORKERS")
    try:
        for key in int_keys:
            if key in overrides:
                int(overrides[key])
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{key} must be an integer")
    if not conv.save_env(overrides):
        raise HTTPException(status_code=500, detail="Failed to write .env")
    return {"saved": True}


@app.post("/api/test-jellyfin")
async def api_test_jellyfin(body: dict):
    url = body.get("url", "").strip() or os.getenv("JELLYFIN_BASE_URL", "").strip()
    key = body.get("key", "").strip() or os.getenv("JELLYFIN_API_KEY", "").strip()
    if not url:
        return {"ok": False, "message": "Jellyfin URL is not set"}
    if not key:
        return {"ok": False, "message": "Jellyfin API Key is not set"}
    try:
        from jellyfin_client import JellyfinClient
        client = JellyfinClient(url, key)
        libs = client.list_libraries()
        client.close()
        return {"ok": True, "message": f"Connected — {len(libs)} libraries found"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.get("/api/system-info")
def api_system_info():
    conv.resolve_ffmpeg_tools()
    encoders = sorted(conv.get_available_encoders())
    gpu_status = {}
    for profile in ("nvidia", "intel", "amdgpu", "cpu"):
        gpu_status[profile] = conv.device_available(profile)
    config = conv.load_config()
    return {
        "ffmpeg_path": conv.FFMPEG_CMD,
        "ffprobe_path": conv.FFPROBE_CMD,
        "encoders": [e for e in encoders if any(x in e for x in ("264", "265", "av1", "vp9"))][:20],
        "gpu": gpu_status,
        "config_found": config is not None,
        "env_path": str(conv.ENV_FILE),
        "config_path": str(conv.CONFIG_FILE),
    }


# ── Libraries CRUD ──────────────────────────────────────────────────────────

@app.get("/api/libraries")
def api_list_libraries():
    config = conv.load_config()
    if not config:
        return {"libraries": []}

    runs = _load_runs()
    libraries = config.get("libraries", [])
    active = {a["library"]: a["run_id"] for a in get_active_runs()}
    result = []
    for lib in libraries:
        name = lib.get("name", "")
        lib_runs = [r for r in runs if r.get("library") == name]
        last_run = lib_runs[0] if lib_runs else None
        total_saved = sum(
            r.get("summary", {}).get("space_saved_mb", 0)
            for r in lib_runs if r.get("exit_code") == 0
        )
        result.append({
            "name": name,
            "paths": conv.normalize_library_paths(lib),
            "profile": lib,
            "last_run": last_run["ended_at"] if last_run else None,
            "last_run_id": last_run["run_id"] if last_run else None,
            "last_run_summary": last_run.get("summary") if last_run else None,
            "total_saved_mb": round(total_saved, 2),
            "run_count": len(lib_runs),
            "running": name in active,
            "active_run_id": active.get(name),
        })
    return {"libraries": result}


@app.get("/api/libraries/{name}")
def api_get_library(name: str):
    config = conv.load_config()
    if not config:
        raise HTTPException(status_code=404, detail="config not found")

    lib_info = conv.find_library_config(config, name)
    if not lib_info:
        raise HTTPException(status_code=404, detail=f"library '{name}' not found")

    paths, profile = lib_info
    runs = [_run_list_entry(r) for r in _load_runs() if r.get("library") == name]

    seen = set()
    for ar in get_active_runs():
        if ar.get("library") == name:
            mgr = get_run(ar["run_id"])
            if mgr:
                results = mgr.results
                ok_count = sum(1 for r in results if r.get("status") == "OK")
                skip_count = sum(1 for r in results if r.get("status") == "SKIP")
                fail_count = sum(1 for r in results if r.get("status") == "FAIL")
                saved_mb = sum(
                    (r.get("before", 0) - r.get("after", 0)) / (1024 * 1024)
                    for r in results if r.get("before") and r.get("after")
                )
                entry = {
                    "run_id": ar["run_id"],
                    "library": name,
                    "started_at": mgr.start_time,
                    "running": True,
                    "exit_code": None,
                    "summary": {
                        "ok": ok_count,
                        "skip": skip_count,
                        "fail": fail_count,
                        "space_saved_mb": round(saved_mb, 2),
                        "files_total": len(results),
                    },
                }
                existing = next((i for i, r in enumerate(runs) if r.get("run_id") == ar["run_id"]), None)
                if existing is not None:
                    runs[existing] = entry
                else:
                    runs.insert(0, entry)
                seen.add(ar["run_id"])
                break

    return {
        "name": name,
        "paths": paths,
        "profile": profile,
        "runs": runs[:50],
    }


@app.post("/api/libraries")
async def api_create_library(body: dict):
    config = conv.load_config()
    if config is None:
        config = {"libraries": []}

    libraries = config.get("libraries", [])
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    if any(l.get("name", "").strip().lower() == name.lower() for l in libraries):
        raise HTTPException(status_code=409, detail=f"library '{name}' already exists")

    entry = {"name": name}
    if body.get("paths"):
        entry["paths"] = body["paths"] if isinstance(body["paths"], list) else [body["paths"]]
    for key in ("encoder", "target_bitrate", "max_bitrate", "keep_audio_langs",
                "keep_subtitle_langs", "minimum_savings_percent"):
        if key in body:
            entry[key] = body[key]

    libraries.append(entry)
    config["libraries"] = libraries
    if not conv.save_config(config):
        raise HTTPException(status_code=500, detail="Failed to write config.yml, check file permissions")
    return {"saved": True, "library": entry}


@app.put("/api/libraries/{name}")
async def api_update_library(name: str, body: dict):
    config = conv.load_config()
    if not config:
        raise HTTPException(status_code=404, detail="config not found")

    libraries = config.get("libraries", [])
    for lib in libraries:
        if lib.get("name", "").strip().lower() == name.strip().lower():
            if "name" in body and body["name"].strip():
                lib["name"] = body["name"].strip()
            if "paths" in body:
                lib["paths"] = body["paths"] if isinstance(body["paths"], list) else [body["paths"]]
            for key in ("encoder", "target_bitrate", "max_bitrate", "keep_audio_langs",
                        "keep_subtitle_langs", "minimum_savings_percent"):
                if key in body:
                    lib[key] = body[key]
            config["libraries"] = libraries
            if not conv.save_config(config):
                raise HTTPException(status_code=500, detail="Failed to write config.yml, check file permissions")
            return {"saved": True, "library": lib}

    raise HTTPException(status_code=404, detail=f"library '{name}' not found")


@app.delete("/api/libraries/{name}")
async def api_delete_library(name: str):
    config = conv.load_config()
    if not config:
        raise HTTPException(status_code=404, detail="config not found")

    libraries = config.get("libraries", [])
    new_libraries = [l for l in libraries if l.get("name", "").strip().lower() != name.strip().lower()]
    if len(new_libraries) == len(libraries):
        raise HTTPException(status_code=404, detail=f"library '{name}' not found")

    config["libraries"] = new_libraries
    if not conv.save_config(config):
        raise HTTPException(status_code=500, detail="Failed to write config.yml, check file permissions")
    return {"deleted": True}


# ── Path Validation ─────────────────────────────────────────────────────────

@app.get("/api/validate-path")
def api_validate_path(path: str = ""):
    if not path:
        return {"valid": False, "error": "no path provided"}
    p = Path(path).expanduser().resolve()
    return {
        "valid": p.exists(),
        "is_dir": p.is_dir() if p.exists() else False,
        "resolved": str(p),
    }


# ── Run History ─────────────────────────────────────────────────────────────

@app.get("/api/runs")
def api_list_runs():
    saved = [_run_list_entry(r) for r in _load_runs()[:100]]
    seen = {r["run_id"] for r in saved}
    for ar in get_active_runs():
        if ar["run_id"] not in seen:
            mgr = get_run(ar["run_id"])
            if mgr:
                results = mgr.results
                ok_count = sum(1 for r in results if r.get("status") == "OK")
                skip_count = sum(1 for r in results if r.get("status") == "SKIP")
                fail_count = sum(1 for r in results if r.get("status") == "FAIL")
                saved_mb = sum(
                    (r.get("before", 0) - r.get("after", 0)) / (1024 * 1024)
                    for r in results if r.get("before") and r.get("after")
                )
                saved.insert(0, {
                    "run_id": ar["run_id"],
                    "library": ar.get("library"),
                    "started_at": mgr.start_time,
                    "running": True,
                    "exit_code": None,
                    "summary": {
                        "ok": ok_count,
                        "skip": skip_count,
                        "fail": fail_count,
                        "space_saved_mb": round(saved_mb, 2),
                        "files_total": len(results),
                    },
                })
    return {"runs": saved}


@app.get("/api/runs/{run_id}")
def api_get_run(run_id: str):
    run = state_db.load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@app.get("/api/errors")
def api_errors():
    return {"errors": state_db.list_errors()}


# ── Stats ───────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def api_stats():
    runs = _load_runs()
    total_saved_mb = 0
    total_ok = 0
    total_skip = 0
    total_fail = 0
    completed_runs = 0
    for r in runs:
        s = r.get("summary") or {}
        if r.get("exit_code") == 0:
            completed_runs += 1
            total_saved_mb += s.get("space_saved_mb", 0)
            total_ok += s.get("ok", 0)
            total_skip += s.get("skip", 0)
            total_fail += s.get("fail", 0)
    return {
        "total_runs": len(runs),
        "completed_runs": completed_runs,
        "total_saved_mb": round(total_saved_mb, 2),
        "total_ok": total_ok,
        "total_skip": total_skip,
        "total_fail": total_fail,
    }


# ── Run Control ─────────────────────────────────────────────────────────────

@app.post("/api/run")
async def api_run(req: dict):
    cmd_dict = req if isinstance(req, dict) else {}
    cmd = build_convert_cmd(cmd_dict)
    try:
        run_id = await start_run(cmd)
        return {"run_id": run_id, "command": " ".join(cmd)}
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/stop/{run_id}")
async def api_stop(run_id: str):
    mgr = get_run(run_id)
    if not mgr or not mgr.running:
        return {"stopped": False, "error": "No matching running process"}
    await mgr.stop()
    cleanup_run(run_id)
    return {"stopped": True}


@app.get("/api/status")
def api_status_list():
    return {"runs": get_active_runs()}


@app.get("/api/status/{run_id}")
def api_status(run_id: str):
    mgr = get_run(run_id)
    if mgr:
        results = mgr.results
        ok_count = sum(1 for r in results if r.get("status") == "OK")
        skip_count = sum(1 for r in results if r.get("status") == "SKIP")
        fail_count = sum(1 for r in results if r.get("status") == "FAIL")
        total_saved_mb = sum(
            (r.get("before", 0) - r.get("after", 0)) / (1024 * 1024)
            for r in results
            if r.get("before") and r.get("after")
        )
        return {
            "running": mgr.running,
            "exit_code": mgr.exit_code,
            "output": mgr.get_buffer(),
            "terminal_output": mgr.get_terminal_buffer(),
            "results": results,
            "folder_totals": mgr.folder_totals,
            "library": mgr.library,
            "started_at": mgr.start_time,
            "summary": {
                "ok": ok_count,
                "skip": skip_count,
                "fail": fail_count,
                "space_saved_mb": round(total_saved_mb, 2),
                "files_total": len(results),
            },
        }
    data = state_db.load_run(run_id)
    if data:
        return {
            "running": False,
            "exit_code": data.get("exit_code"),
            "output": data.get("output", []),
            "terminal_output": data.get("terminal_output", []),
            "results": data.get("results", []),
            "folder_totals": data.get("folder_totals", {}),
            "library": data.get("library"),
            "started_at": data.get("started_at"),
            "ended_at": data.get("ended_at"),
            "summary": data.get("summary", {}),
        }
    raise HTTPException(status_code=404, detail="run not found")


@app.get("/api/log/{run_id}")
def api_log(run_id: str):
    from fastapi.responses import PlainTextResponse
    lines: list[str] = []
    mgr = get_run(run_id)
    if mgr:
        for msg in mgr.get_buffer():
            d = msg.get("data", "")
            if isinstance(d, str):
                lines.append(d)
        text = "\n".join(lines)
        return PlainTextResponse(text, media_type="text/plain")
    data = state_db.load_run(run_id)
    if data:
        for msg in data.get("output", []):
            d = msg.get("data", "")
            if isinstance(d, str):
                lines.append(d)
        text = "\n".join(lines)
        return PlainTextResponse(text, media_type="text/plain")
    from fastapi.responses import JSONResponse
    return JSONResponse({"error": "run not found"}, status_code=404)


@app.websocket("/api/ws/{run_id}")
async def api_ws(websocket: WebSocket, run_id: str):
    await websocket.accept()
    mgr = get_run(run_id)
    if not mgr:
        await websocket.send_json({"type": "error", "data": "Unknown run_id"})
        await websocket.close()
        return

    listener_id = f"ws_{run_id}_{id(websocket)}"
    for msg in mgr.get_buffer():
        await websocket.send_json(msg)

    def send(msg: dict):
        try:
            asyncio.run_coroutine_threadsafe(websocket.send_json(msg), asyncio.get_event_loop())
        except Exception:
            pass

    mgr.subscribe(listener_id, send)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        mgr.unsubscribe(listener_id)


@app.get("/api/system-stats")
def system_stats():
    out: dict[str, Any] = {"cpu": {}, "memory": {}, "gpu": []}

    out["cpu"]["percent"] = psutil.cpu_percent(interval=0.3)
    out["cpu"]["count"] = psutil.cpu_count()

    mem = psutil.virtual_memory()
    out["memory"]["total_gb"] = round(mem.total / (1024 ** 3), 1)
    out["memory"]["used_gb"] = round(mem.used / (1024 ** 3), 1)
    out["memory"]["percent"] = mem.percent

    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,memory.total,memory.used,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 6:
                    def _f(v):
                        try:
                            return float(v)
                        except (ValueError, TypeError):
                            return None
                    out["gpu"].append({
                        "index": parts[0],
                        "name": parts[1],
                        "util_percent": _f(parts[2]),
                        "mem_total_mb": _f(parts[3]),
                        "mem_used_mb": _f(parts[4]),
                        "temp_c": _f(parts[5]),
                    })
    except Exception:
        out["gpu"] = None

    return out


# ── Frontend ────────────────────────────────────────────────────────────────

STATIC_DIR = Path(__file__).parent / "static"


def _spa_index():
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return HTMLResponse(idx.read_text(encoding="utf-8"))
    return {"error": "SPA not built — run `npm run build` in webui/"}


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return _spa_index()


@app.get("/{path:path}")
def spa_fallback(path: str):
    if path.startswith("api/"):
        return JSONResponse({"error": "not found"}, status_code=404)
    return _spa_index()


from webui.mcp import mcp_app
app.include_router(mcp_app)

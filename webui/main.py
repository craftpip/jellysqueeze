import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

import convert as conv
from webui.runner import get_manager

app = FastAPI(title="Media Convert for Jellyfin — Web UI")


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
    cmd = [python, str(Path(BASE_DIR) / "convert.py")]
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
    if f.get("no_backup_original"):
        cmd.append("--no-backup-original")
    if f.get("exclude"):
        cmd.extend(["--exclude", f["exclude"]])
    for ip in f.get("ignore_path", []):
        if ip:
            cmd.extend(["--ignore-path", ip])
    if f.get("cleanup_tmp"):
        cmd.append("--cleanup-tmp")
    return cmd


@app.get("/api/config")
def api_config():
    return _load_config_safe()


@app.get("/api/env")
def api_env():
    return {
        "TARGET_BR": int(os.getenv("TARGET_BR", 3000)),
        "MAX_BR": int(os.getenv("MAX_BR", 3300)),
        "BITRATE_TOLERANCE": int(os.getenv("BITRATE_TOLERANCE", 300)),
        "DEFAULT_CRF": int(os.getenv("DEFAULT_CRF", 23)),
        "JELLYFIN_BASE_URL": os.getenv("JELLYFIN_BASE_URL", ""),
    }


@app.post("/api/run")
async def api_run(req: dict):
    mgr = get_manager()
    if mgr.running:
        return {"error": "A run is already in progress"}, 409

    cmd_dict = req if isinstance(req, dict) else {}
    cmd = build_convert_cmd(cmd_dict)
    try:
        run_id = await mgr.start(cmd)
        asyncio.ensure_future(mgr.wait())
        return {"run_id": run_id, "command": " ".join(cmd)}
    except RuntimeError as e:
        return {"error": str(e)}, 409


@app.post("/api/stop/{run_id}")
async def api_stop(run_id: str):
    mgr = get_manager()
    if mgr.run_id != run_id or not mgr.running:
        return {"stopped": False, "error": "No matching running process"}
    await mgr.stop()
    return {"stopped": True}


@app.get("/api/status/{run_id}")
def api_status(run_id: str):
    mgr = get_manager()
    if mgr.run_id != run_id:
        return {"running": False, "exit_code": None}
    return {"running": mgr.running, "exit_code": mgr.exit_code}


@app.websocket("/api/ws/{run_id}")
async def api_ws(websocket: WebSocket, run_id: str):
    await websocket.accept()
    mgr = get_manager()
    listener_id = f"ws_{run_id}_{id(websocket)}"

    if mgr.run_id != run_id:
        await websocket.send_json({"type": "error", "data": "Unknown run_id"})
        await websocket.close()
        return

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


_index_html: str | None = None


@app.get("/")
def index():
    global _index_html
    if _index_html is None:
        tmpl = Path(__file__).parent / "templates" / "index.html"
        if tmpl.exists():
            _index_html = tmpl.read_text(encoding="utf-8")
    if _index_html:
        return HTMLResponse(_index_html)
    return {"error": "index.html not found"}

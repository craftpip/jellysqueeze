import asyncio
import os
import sys
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

import convert as conv
from webui.runner import get_run, start_run

mcp_app = APIRouter(prefix="/mcp")


@mcp_app.get("/profiles")
def mcp_profiles():
    config = conv.load_config()
    if not config:
        return {"profiles": []}
    profiles = config.get("profiles", {})
    result = []
    for name, settings in profiles.items():
        result.append({
            "name": name,
            "target_bitrate": settings.get("target_bitrate"),
            "max_bitrate": settings.get("max_bitrate"),
            "encoder": settings.get("encoder", "nvidia"),
        })
    return {"profiles": result}


@mcp_app.get("/libraries")
def mcp_libraries():
    config = conv.load_config()
    if not config:
        return {"libraries": []}
    libs = config.get("libraries", [])
    profiles = config.get("profiles", {})
    result = []
    for lib in libs:
        profile_name = lib.get("profile", "")
        entry = {
            "name": lib.get("name", ""),
            "paths": conv.normalize_library_paths(lib),
            "profile": profile_name,
        }
        inline_keys = {"target_bitrate", "max_bitrate", "encoder",
                       "keep_audio_langs", "keep_subtitle_langs",
                       "minimum_savings_percent"}
        inline = {k: lib[k] for k in inline_keys if k in lib}
        if inline:
            entry["profile_settings"] = inline
        elif profile_name and profile_name in profiles:
            entry["profile_settings"] = profiles[profile_name]
        result.append(entry)
    return {"libraries": result}


@mcp_app.post("/run")
async def mcp_run(req: dict):
    from webui.main import build_convert_cmd
    cmd = build_convert_cmd(req if isinstance(req, dict) else {})
    try:
        run_id = await start_run(cmd)
        return {"run_id": run_id, "command": " ".join(cmd)}
    except RuntimeError as e:
        return {"error": str(e)}


@mcp_app.get("/status/{run_id}")
def mcp_status(run_id: str):
    mgr = get_run(run_id)
    if not mgr:
        return {"running": False, "exit_code": None}
    return {"running": mgr.running, "exit_code": mgr.exit_code}


@mcp_app.post("/stop/{run_id}")
async def mcp_stop(run_id: str):
    mgr = get_run(run_id)
    if not mgr or not mgr.running:
        return {"stopped": False, "error": "No matching running process"}
    await mgr.stop()
    return {"stopped": True}


@mcp_app.websocket("/ws/{run_id}")
async def mcp_ws(websocket: WebSocket, run_id: str):
    await websocket.accept()
    mgr = get_run(run_id)
    listener_id = f"mcp_ws_{run_id}_{id(websocket)}"

    if not mgr:
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

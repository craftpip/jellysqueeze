import asyncio
import os
import sys
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

import convert as conv
from webui.runner import get_manager
from webui.main import build_convert_cmd

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
        if profile_name and profile_name in profiles:
            entry["profile_settings"] = profiles[profile_name]
        result.append(entry)
    return {"libraries": result}


@mcp_app.post("/run")
async def mcp_run(req: dict):
    mgr = get_manager()
    if mgr.running:
        return {"error": "A run is already in progress"}, 409

    cmd = build_convert_cmd(req if isinstance(req, dict) else {})
    try:
        run_id = await mgr.start(cmd)
        asyncio.ensure_future(mgr.wait())
        return {"run_id": run_id, "command": " ".join(cmd)}
    except RuntimeError as e:
        return {"error": str(e)}, 409


@mcp_app.get("/status/{run_id}")
def mcp_status(run_id: str):
    mgr = get_manager()
    if mgr.run_id != run_id:
        return {"running": False, "exit_code": None}
    return {"running": mgr.running, "exit_code": mgr.exit_code}


@mcp_app.post("/stop/{run_id}")
async def mcp_stop(run_id: str):
    mgr = get_manager()
    if mgr.run_id != run_id or not mgr.running:
        return {"stopped": False, "error": "No matching running process"}
    await mgr.stop()
    return {"stopped": True}


@mcp_app.websocket("/ws/{run_id}")
async def mcp_ws(websocket: WebSocket, run_id: str):
    await websocket.accept()
    mgr = get_manager()
    listener_id = f"mcp_ws_{run_id}_{id(websocket)}"

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

import asyncio
import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

import convert as conv
import state_db
from webui.runner import get_run, start_run, _managers

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
            "codec": settings.get("codec", "h264"),
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
        inline_keys = {"target_bitrate", "max_bitrate", "encoder", "codec",
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


@mcp_app.get("/runs")
def mcp_runs():
    active = [
        {
            "run_id": mgr.run_id,
            "library": mgr.library,
            "started_at": mgr.start_time,
        }
        for mgr in _managers.values()
        if mgr.running
    ]
    return {"runs": active}


@mcp_app.get("/status/{run_id}")
def mcp_status(run_id: str):
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
            "results": results,
            "folder_totals": mgr.folder_totals,
            "run_status": mgr.run_status,
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
            "results": data.get("results", []),
            "folder_totals": data.get("folder_totals", {}),
            "run_status": data.get("run_status"),
            "library": data.get("library"),
            "started_at": data.get("started_at"),
            "ended_at": data.get("ended_at"),
            "summary": data.get("summary", {}),
        }
    return {"error": "Unknown run_id"}


@mcp_app.post("/stop/{run_id}")
async def mcp_stop(run_id: str):
    mgr = get_run(run_id)
    if not mgr or not mgr.running:
        return {"stopped": False, "error": "No matching running process"}
    await mgr.stop()
    return {"stopped": True}


# ── JSON-RPC wrapper at POST /mcp (REST kept for backwards compat) ───────────

def _get_expected_mcp_key() -> str:
    return os.getenv("JELLYSQUEEZE_MCP_API_KEY", "").strip()


def _check_mcp_auth(request: Request) -> bool:
    expected = _get_expected_mcp_key()
    if not expected:
        return True
    auth = request.headers.get("authorization", "")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token == expected:
            return True
    # legacy headers
    legacy = request.headers.get("x-mcp-key", "")
    if legacy and legacy == expected:
        return True
    legacy2 = request.headers.get("x-api-key", "")
    if legacy2 and legacy2 == expected:
        return True
    return False


def _tool_definitions():
    output_format_prop = {
        "type": "string",
        "enum": ["markdown", "json"],
        "default": "markdown",
        "description": "Output format: markdown or json (default: markdown)"
    }
    return [
        {
            "name": "list_libraries",
            "description": "List JellySqueeze libraries",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "output_format": output_format_prop
                }
            }
        },
        {
            "name": "get_status",
            "description": "Get run status",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "output_format": output_format_prop
                },
                "required": ["run_id"]
            }
        },
        {
            "name": "list_runs",
            "description": "List runs",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "output_format": output_format_prop
                }
            }
        },
        {
            "name": "run",
            "description": "Start a run",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "library": {"type": "string"},
                    "output_format": output_format_prop
                }
            }
        },
        {
            "name": "stop",
            "description": "Stop a run",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "output_format": output_format_prop
                },
                "required": ["run_id"]
            }
        },
    ]


def _format_libraries_markdown(data: dict) -> str:
    if "error" in data:
        return f"# Error\n\n{data.get('error')}\n"
    libs = data.get("libraries", [])
    if not libs:
        return "# JellySqueeze Libraries\n\nNo libraries configured.\n\nlibraries: []\n"
    lines = ["# JellySqueeze Libraries", "", f"Found {len(libs)} libraries (libraries).", ""]
    for lib in libs:
        name = lib.get("name", "")
        lines.append(f"## {name}")
        paths = lib.get("paths", [])
        if paths:
            lines.append(f"- **Paths:** {', '.join(paths)}")
        profile = lib.get("profile", "")
        if profile:
            lines.append(f"- **Profile:** {profile}")
        ps = lib.get("profile_settings", {})
        if ps:
            parts = []
            if ps.get("encoder"):
                parts.append(f"Encoder: {ps.get('encoder')}")
            if ps.get("target_bitrate") is not None:
                parts.append(f"Target: {ps.get('target_bitrate')} kbps")
            if ps.get("max_bitrate") is not None:
                parts.append(f"Max: {ps.get('max_bitrate')} kbps")
            if parts:
                lines.append(f"- **Settings:** {', '.join(parts)}")
        lines.append("")
    lines.append("---")
    lines.append(f"libraries count: {len(libs)}")
    return "\n".join(lines)


def _format_runs_markdown(data: dict) -> str:
    if "error" in data:
        return f"# Error\n\n{data.get('error')}\n"
    runs = data.get("runs", [])
    if not runs:
        return "# Runs\n\nNo active runs.\n\nruns: []\n"
    lines = ["# Runs", "", f"Found {len(runs)} active run(s).", ""]
    for r in runs:
        lines.append(f"## Run {r.get('run_id','')}")
        if r.get("library"):
            lines.append(f"- **Library:** {r.get('library')}")
        if r.get("started_at"):
            lines.append(f"- **Started:** {r.get('started_at')}")
        lines.append("")
    lines.append("---")
    lines.append(f"runs count: {len(runs)}")
    return "\n".join(lines)


def _format_status_markdown(data: dict, run_id: str) -> str:
    if "error" in data:
        return f"# Run Status: {run_id}\n\n**Error:** {data.get('error')}\n\nrun_id: {run_id}\n"
    lines = [f"# Run Status: {run_id}", ""]
    lines.append(f"- **Running:** {data.get('running')}")
    if data.get("library") is not None:
        lines.append(f"- **Library:** {data.get('library')}")
    if data.get("exit_code") is not None:
        lines.append(f"- **Exit code:** {data.get('exit_code')}")
    summary = data.get("summary", {})
    if summary:
        lines.append(f"- **Summary:** OK {summary.get('ok',0)} / Skip {summary.get('skip',0)} / Fail {summary.get('fail',0)}")
        if summary.get("space_saved_mb") is not None:
            lines.append(f"- **Space saved:** {summary.get('space_saved_mb')} MB")
        if summary.get("files_total") is not None:
            lines.append(f"- **Files total:** {summary.get('files_total')}")
    results = data.get("results", [])
    if results:
        lines.append(f"- **Results:** {len(results)} file(s)")
    folder_totals = data.get("folder_totals", {})
    if folder_totals:
        lines.append(f"- **Folder totals:** {json.dumps(folder_totals)}")
    lines.append("")
    lines.append(f"run_id: {run_id}")
    lines.append(f"libraries: status for run {run_id}")
    return "\n".join(lines)


def _format_run_markdown(data: dict) -> str:
    if "error" in data:
        return f"# Run Error\n\n{data.get('error')}\n"
    lines = ["# Run Started", ""]
    if data.get("run_id"):
        lines.append(f"- **Run ID:** {data.get('run_id')}")
    if data.get("command"):
        lines.append(f"- **Command:** `{data.get('command')}`")
    lines.append("")
    lines.append(f"run_id: {data.get('run_id','')}")
    return "\n".join(lines)


def _format_stop_markdown(data: dict, run_id: str) -> str:
    if data.get("stopped"):
        return f"# Stop Run: {run_id}\n\n**Stopped:** true\n\nrun_id: {run_id}\n"
    err = data.get("error", "Failed to stop")
    return f"# Stop Run: {run_id}\n\n**Stopped:** false\n\n**Error:** {err}\n\nrun_id: {run_id}\n"


def _format_markdown(tool_name: str, data: dict, arguments: dict) -> str:
    if tool_name == "list_libraries":
        return _format_libraries_markdown(data)
    elif tool_name == "list_runs":
        return _format_runs_markdown(data)
    elif tool_name == "get_status":
        return _format_status_markdown(data, arguments.get("run_id", ""))
    elif tool_name == "run":
        return _format_run_markdown(data)
    elif tool_name == "stop":
        return _format_stop_markdown(data, arguments.get("run_id", ""))
    # fallback
    return json.dumps(data, indent=2, ensure_ascii=False)


async def _handle_tool_call(name: str, arguments: dict):
    # Extract output_format, default markdown
    output_format = arguments.get("output_format", "markdown")
    if output_format not in ("markdown", "json"):
        output_format = "markdown"
    # Remove output_format from args before dispatching to avoid polluting
    clean_args = {k: v for k, v in arguments.items() if k != "output_format"}

    if name == "list_libraries":
        data = mcp_libraries()
    elif name == "list_runs":
        data = mcp_runs()
    elif name == "get_status":
        run_id = clean_args.get("run_id")
        if not run_id or not isinstance(run_id, str):
            raise ValueError("run_id is required and must be a string")
        data = mcp_status(run_id)
    elif name == "run":
        library = clean_args.get("library")
        payload: dict = {}
        if library:
            payload = {"mode": "library", "library": library}
            # Pass through any additional flags if provided alongside library
            for k, v in clean_args.items():
                if k not in ("library",):
                    payload[k] = v
        else:
            # No library: treat args as direct payload (backwards compat)
            payload = dict(clean_args) if clean_args else {}
        data = await mcp_run(payload)
    elif name == "stop":
        run_id = clean_args.get("run_id")
        if not run_id or not isinstance(run_id, str):
            raise ValueError("run_id is required and must be a string")
        data = await mcp_stop(run_id)
    else:
        raise ValueError(f"Unknown tool: {name}")

    if output_format == "json":
        text = json.dumps(data, indent=2, ensure_ascii=False)
    else:
        text = _format_markdown(name, data, arguments)

    return {"content": [{"type": "text", "text": text}], "isError": False}


@mcp_app.post("")
@mcp_app.post("/")
async def mcp_jsonrpc(request: Request):
    # Auth check
    if not _check_mcp_auth(request):
        return JSONResponse(
            status_code=401,
            content={
                "jsonrpc": "2.0",
                "error": {"code": -32001, "message": "Unauthorized: provide a valid Bearer token or X-MCP-Key."},
                "id": None
            }
        )
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None}
        )

    # Handle batch requests (array)
    if isinstance(body, list):
        responses = []
        for item in body:
            resp = await _dispatch_single(item)
            if resp is not None:
                responses.append(resp)
        if not responses:
            return JSONResponse(status_code=204, content=None)
        return JSONResponse(content=responses)

    resp = await _dispatch_single(body)
    if resp is None:
        return JSONResponse(status_code=204, content=None)
    return JSONResponse(content=resp)


async def _dispatch_single(body: dict):
    if not isinstance(body, dict):
        return {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid Request"}, "id": None}
    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params") or {}

    # notifications have no id and should not return a body
    is_notification = req_id is None and method in ("notifications/initialized", "notifications/cancelled")

    if method == "notifications/initialized":
        return None
    if method == "notifications/cancelled":
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "jellysqueeze-mcp", "version": "1.0.0"},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": _tool_definitions()}}

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not name:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Missing tool name"}}
        # Check tool exists to give proper error
        allowed = {t["name"] for t in _tool_definitions()}
        if name not in allowed:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Tool not found: {name}"}}
        try:
            result = await _handle_tool_call(name, arguments)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except ValueError as e:
            # Missing required param etc -> invalid params
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": str(e)}}
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": str(e)}], "isError": True},
            }

    # Unknown method
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


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

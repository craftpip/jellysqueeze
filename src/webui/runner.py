import asyncio
import json
import os
import sys
import signal
import uuid
import time
from pathlib import Path
from typing import Callable
import state_db

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONVERT_PY = BASE_DIR / "src" / "convert.py"
RUNS_DIR = BASE_DIR / "var" / "runs"


def _load_runs() -> list[dict]:
    return state_db.list_runs()


def _save_run(run_data: dict):
    state_db.save_run(run_data)


class RunManager:
    def __init__(self):
        self._process: asyncio.subprocess.Process | None = None
        self._run_id: str | None = None
        self._exit_code: int | None = None
        self._buffer: list[dict] = []
        self._max_buffer = 500
        self._terminal_buffer: list[dict] = []
        self._max_terminal_buffer = 500
        self._listeners: dict[str, Callable] = {}
        self._results: list[dict] = []
        self._summary: dict | None = None
        self._folder_totals: dict[str, int] = {}
        self._library: str | None = None
        self._history_saved: bool = False
        self._start_time: float = 0.0
        self._reader_tasks: list[asyncio.Task] = []
        self._finish_lock = asyncio.Lock()
        self._stop_requested = False

    @property
    def start_time(self) -> float:
        return self._start_time

    @property
    def results(self) -> list[dict]:
        return list(self._results)

    @property
    def run_id(self) -> str | None:
        return self._run_id

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    @property
    def library(self) -> str | None:
        return self._library

    @property
    def folder_totals(self) -> dict[str, int]:
        return dict(self._folder_totals)

    def subscribe(self, listener_id: str, callback: Callable):
        self._listeners[listener_id] = callback

    def unsubscribe(self, listener_id: str):
        self._listeners.pop(listener_id, None)

    def _broadcast(self, msg: dict):
        for cb in list(self._listeners.values()):
            try:
                cb(msg)
            except Exception:
                pass

    def get_buffer(self) -> list[dict]:
        return list(self._buffer)

    def get_terminal_buffer(self) -> list[dict]:
        return list(self._terminal_buffer)

    @staticmethod
    def _extract_library(cmd: list[str]) -> str | None:
        for i, arg in enumerate(cmd):
            if arg == "--library" and i + 1 < len(cmd):
                return cmd[i + 1]
            if arg == "--all":
                return "all"
            if arg == "--jellyfin-recent":
                return "jellyfin-recent"
        return None

    async def start(self, cmd: list[str]) -> str:
        self._run_id = uuid.uuid4().hex
        self._exit_code = None
        self._buffer = []
        self._terminal_buffer = []
        self._results = []
        self._summary = None
        self._folder_totals = {}
        self._library = self._extract_library(cmd)
        self._history_saved = False
        self._stop_requested = False
        self._start_time = time.time()

        cmd_with_json = cmd + ["--json"]
        self._process = await asyncio.create_subprocess_exec(
            *cmd_with_json,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        async def read_stdout(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n\r")
                msg = {"type": "stdout", "data": text, "ts": time.time()}
                self._buffer.append(msg)
                if len(self._buffer) > self._max_buffer:
                    self._buffer = self._buffer[-self._max_buffer:]
                self._broadcast(msg)
                self._try_parse_json(text)
                if not text.startswith("{"):
                    self._terminal_buffer.append(msg)
                    if len(self._terminal_buffer) > self._max_terminal_buffer:
                        self._terminal_buffer = self._terminal_buffer[-self._max_terminal_buffer:]

        async def read_stderr(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n\r")
                msg = {"type": "stderr", "data": text, "ts": time.time()}
                self._buffer.append(msg)
                if len(self._buffer) > self._max_buffer:
                    self._buffer = self._buffer[-self._max_buffer:]
                self._broadcast(msg)
                self._terminal_buffer.append(msg)
                if len(self._terminal_buffer) > self._max_terminal_buffer:
                    self._terminal_buffer = self._terminal_buffer[-self._max_terminal_buffer:]

        self._reader_tasks = [
            asyncio.create_task(read_stdout(self._process.stdout)),
            asyncio.create_task(read_stderr(self._process.stderr)),
        ]

        return self._run_id

    def _try_parse_json(self, text: str):
        text = text.strip()
        if not text.startswith("{"):
            return
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return
        t = data.get("type")
        if t == "result":
            self._results.append(data)
        elif t == "summary":
            self._summary = data
        elif t == "run_folder" and data.get("root"):
            try:
                self._folder_totals[str(data["root"])] = int(data.get("total") or 0)
            except (TypeError, ValueError):
                pass

    def _save_run_history(self, summary: dict):
        buffer_snapshot = list(self._buffer)
        run_data = {
            "run_id": self._run_id,
            "library": self._library or summary.get("mode", "direct"),
            "started_at": buffer_snapshot[0]["ts"] if buffer_snapshot else time.time(),
            "ended_at": time.time(),
            "exit_code": self._exit_code,
            "results": self._results,
            "folder_totals": self._folder_totals,
            "summary": summary,
            "output": buffer_snapshot,
            "terminal_output": list(self._terminal_buffer),
        }
        self._history_saved = True
        _save_run(run_data)

    def _partial_summary(self, status: str) -> dict:
        return {
            "type": "summary",
            "status": status,
            "mode": self._library or "direct",
            "files_total": len(self._results),
            "ok": sum(1 for result in self._results if result.get("status") == "OK"),
            "skip": sum(1 for result in self._results if result.get("status") == "SKIP"),
            "fail": sum(1 for result in self._results if result.get("status") == "FAIL"),
            "space_saved_mb": round(sum(
                (result.get("before", 0) - result.get("after", 0)) / (1024 * 1024)
                for result in self._results
                if result.get("before") and result.get("after")
            ), 2),
        }

    async def wait(self):
        if not self._process:
            return
        async with self._finish_lock:
            if self._history_saved:
                return
            await self._process.wait()
            await asyncio.gather(*self._reader_tasks, return_exceptions=True)
            self._exit_code = self._process.returncode
            self._broadcast({"type": "exit", "code": self._exit_code})
            if self._stop_requested:
                summary_data = self._partial_summary("stopped")
            elif self._exit_code == 0:
                summary_data = dict(self._summary or self._partial_summary("completed"))
                summary_data.update({
                    "type": "summary",
                    "status": "completed",
                    "mode": summary_data.get("mode", self._library or "direct"),
                })
            else:
                summary_data = self._partial_summary("failed")
            self._save_run_history(summary_data)

    async def stop(self):
        if self._process and self._process.returncode is None:
            self._stop_requested = True
            try:
                os.killpg(self._process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                try:
                    os.killpg(self._process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await self._process.wait()
            await self.wait()


_managers: dict[str, RunManager] = {}
_run_lock = asyncio.Lock()


async def start_run(cmd: list[str]) -> str:
    async with _run_lock:
        mgr = RunManager()
        requested_library = mgr._extract_library(cmd)
        active_libraries = {active.library for active in _managers.values() if active.running}
        exclusive_modes = {None, "all", "jellyfin-recent"}
        if (
            requested_library in exclusive_modes
            or active_libraries & exclusive_modes
            or requested_library in active_libraries
        ):
            raise RuntimeError("A conversion run is already active for this library")
        run_id = await mgr.start(cmd)
        _managers[run_id] = mgr
        asyncio.ensure_future(mgr.wait())
        return run_id


def get_run(run_id: str) -> RunManager | None:
    return _managers.get(run_id)


def get_active_runs() -> list[dict]:
    return [
        {"run_id": mgr.run_id, "library": mgr.library}
        for mgr in _managers.values()
        if mgr.running
    ]


def cleanup_run(run_id: str):
    _managers.pop(run_id, None)


async def stop_all_runs():
    await asyncio.gather(
        *(mgr.stop() for mgr in list(_managers.values()) if mgr.running),
        return_exceptions=True,
    )

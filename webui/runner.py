import asyncio
import os
import sys
import signal
import uuid
import time
from pathlib import Path
from typing import Callable

BASE_DIR = Path(__file__).parent.parent
CONVERT_PY = BASE_DIR / "convert.py"


class RunManager:
    def __init__(self):
        self._process: asyncio.subprocess.Process | None = None
        self._run_id: str | None = None
        self._exit_code: int | None = None
        self._buffer: list[dict] = []
        self._max_buffer = 500
        self._listeners: dict[str, Callable] = {}

    @property
    def run_id(self) -> str | None:
        return self._run_id

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

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

    async def start(self, cmd: list[str]) -> str:
        if self._process is not None and self._process.returncode is None:
            raise RuntimeError("A run is already in progress")

        self._run_id = uuid.uuid4().hex
        self._exit_code = None
        self._buffer = []

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read_stream(stream, stream_type: str):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n\r")
                msg = {"type": stream_type, "data": text, "ts": time.time()}
                self._buffer.append(msg)
                if len(self._buffer) > self._max_buffer:
                    self._buffer = self._buffer[-self._max_buffer:]
                self._broadcast(msg)

        asyncio.ensure_future(read_stream(self._process.stdout, "stdout"))
        asyncio.ensure_future(read_stream(self._process.stderr, "stderr"))

        return self._run_id

    async def wait(self):
        if self._process:
            await self._process.wait()
            self._exit_code = self._process.returncode
            self._broadcast({"type": "exit", "code": self._exit_code})

    async def stop(self):
        if self._process and self._process.returncode is None:
            self._process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.send_signal(signal.SIGKILL)
                await self._process.wait()
            self._exit_code = self._process.returncode
            self._broadcast({"type": "exit", "code": self._exit_code})


_manager = RunManager()


def get_manager() -> RunManager:
    return _manager

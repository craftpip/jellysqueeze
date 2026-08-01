import asyncio
import datetime as dt
import time

import convert as conv

REPEATS = ("daily", "weekly", "monthly")
TICK_SECONDS = 30


def _parse_time(value) -> tuple[int, int]:
    parts = str(value).split(":")
    if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
        raise ValueError("time must be HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("time must be a valid 24h HH:MM")
    return hour, minute


def validate_schedule(s: dict) -> str | None:
    """Return an error string, or None if the schedule is valid."""
    if not s.get("name", "").strip():
        return "name is required"
    if s.get("repeat") not in REPEATS:
        return f"repeat must be one of {', '.join(REPEATS)}"
    try:
        _parse_time(s.get("time", ""))
    except ValueError as e:
        return str(e)
    if s.get("repeat") == "weekly":
        day = s.get("day")
        if not isinstance(day, int) or not 0 <= day <= 6:
            return "day must be 0-6 (Mon-Sun) for weekly"
    elif s.get("repeat") == "monthly":
        day = s.get("day")
        if not isinstance(day, int) or not 1 <= day <= 31:
            return "day must be 1-31 for monthly"
    mode = s.get("mode")
    if mode == "library":
        if not s.get("library", "").strip():
            return "library is required for mode=library"
    elif mode == "jellyfin_recent":
        if not (s.get("flags") or {}).get("libraries"):
            return "flags.libraries is required for mode=jellyfin_recent"
    else:
        return "mode must be library or jellyfin_recent"
    return None


def _next_month(d: dt.datetime) -> dt.datetime:
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1, day=1)
    return d.replace(month=d.month + 1, day=1)


def next_run(schedule: dict, now: dt.datetime) -> dt.datetime | None:
    """Next strictly-future occurrence, or None if the schedule is disabled.

    A schedule is "due" throughout its target minute, so a tick landing mid-minute
    (e.g. at 20:47:30 for a 20:47 schedule) still treats that minute as current.
    """
    if not schedule.get("enabled", True):
        return None
    try:
        hour, minute = _parse_time(schedule.get("time", ""))
    except ValueError:
        return None
    repeat = schedule.get("repeat")
    floor_now = now.replace(second=0, microsecond=0)

    if repeat == "daily":
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < floor_now:
            candidate += dt.timedelta(days=1)
        return candidate

    if repeat == "weekly":
        target = int(schedule.get("day", 0))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (target - candidate.weekday()) % 7
        candidate += dt.timedelta(days=days_ahead)
        if candidate < floor_now:
            candidate += dt.timedelta(days=7)
        return candidate

    if repeat == "monthly":
        target = int(schedule.get("day", 1))
        candidate = now.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0)
        while True:
            try:
                candidate = candidate.replace(day=target)
            except ValueError:
                candidate = _next_month(candidate)
                continue
            if candidate >= floor_now:
                return candidate
            candidate = _next_month(candidate)
    return None


def schedule_to_req(s: dict) -> dict:
    req = {"mode": s.get("mode"), "flags": dict(s.get("flags") or {})}
    if s.get("mode") == "library":
        req["library"] = s.get("library")
    return req


def _cleanup_fired(fired: dict[str, str]):
    keep = {}
    for name, occ in fired.items():
        try:
            when = dt.datetime.fromisoformat(occ)
        except ValueError:
            continue
        if when > dt.datetime.now() - dt.timedelta(days=1):
            keep[name] = occ
    return keep


class Scheduler:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._fired: dict[str, str] = {}
        self._last: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self):
        if self.running:
            return
        self._task = asyncio.ensure_future(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self):
        while True:
            try:
                await self._tick()
            except Exception:
                pass
            await asyncio.sleep(TICK_SECONDS)

    def load_schedules(self) -> list[dict]:
        config = conv.load_config()
        if not config:
            return []
        return config.get("schedules", [])

    def find_schedule(self, name: str) -> dict | None:
        lower = name.strip().lower()
        for s in self.load_schedules():
            if s.get("name", "").strip().lower() == lower:
                return s
        return None

    async def _tick(self):
        async with self._lock:
            now = dt.datetime.now()
            for s in self.load_schedules():
                if not s.get("enabled", True):
                    continue
                name = s.get("name", "")
                nxt = next_run(s, now)
                if nxt is None or nxt > now:
                    continue
                occurrence = nxt.isoformat()
                if self._fired.get(name) == occurrence:
                    continue
                await self._fire(s, occurrence)

    async def _fire(self, schedule: dict, occurrence: str):
        from webui.main import build_convert_cmd
        from webui.runner import start_run
        name = schedule.get("name", "")
        cmd = build_convert_cmd(schedule_to_req(schedule))
        try:
            run_id = await start_run(cmd)
        except RuntimeError as e:
            self._last[name] = {"skipped_reason": str(e)}
            self._fired[name] = occurrence
            return
        except Exception:
            self._last[name] = {"skipped_reason": "failed to start"}
            self._fired[name] = occurrence
            return
        self._last[name] = {"started_at": time.time(), "run_id": run_id}
        self._fired[name] = occurrence

    async def run_now(self, name: str) -> str:
        """Immediate fire (used by the Run Now button). Raises RuntimeError on overlap."""
        from webui.main import build_convert_cmd
        from webui.runner import start_run
        schedule = self.find_schedule(name)
        if not schedule:
            raise KeyError(name)
        cmd = build_convert_cmd(schedule_to_req(schedule))
        run_id = await start_run(cmd)
        self._last[name] = {"started_at": time.time(), "run_id": run_id}
        return run_id

    def get_status(self) -> list[dict]:
        now = dt.datetime.now()
        out = []
        for s in self.load_schedules():
            entry = dict(s)
            entry.update(self._last.get(s.get("name", ""), {}))
            nxt = next_run(s, now)
            entry["next_run"] = nxt.isoformat() if nxt else None
            out.append(entry)
        self._fired = _cleanup_fired(self._fired)
        return out

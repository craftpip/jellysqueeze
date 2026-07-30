import json
import sqlite3
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
VAR_DIR = BASE_DIR / "var"
DB_PATH = VAR_DIR / "media-convert.sqlite3"
DONE_FILE = VAR_DIR / "_progress.txt"
PROBE_CACHE_FILE = VAR_DIR / "probe-cache.json"
RUNS_DIR = VAR_DIR / "runs"


def _connect() -> sqlite3.Connection:
    VAR_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def initialize() -> None:
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS completed_files (
                path TEXT NOT NULL,
                option TEXT NOT NULL,
                completed_at REAL NOT NULL,
                PRIMARY KEY (path, option)
            );
            CREATE TABLE IF NOT EXISTS probe_cache (
                path TEXT PRIMARY KEY,
                option TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                library TEXT,
                status TEXT,
                started_at REAL,
                ended_at REAL,
                exit_code INTEGER,
                summary_json TEXT NOT NULL DEFAULT '{}',
                folder_totals_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS runs_library_started
                ON runs(library, started_at DESC);
            CREATE TABLE IF NOT EXISTS run_results (
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL,
                file TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                before_bytes INTEGER NOT NULL DEFAULT 0,
                after_bytes INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (run_id, sequence)
            );
            CREATE TABLE IF NOT EXISTS run_events (
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (run_id, sequence)
            );
        """)
    _import_legacy_once()


def _import_legacy_once() -> None:
    with _connect() as conn:
        imported = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'legacy_imported'"
        ).fetchone()
        if imported:
            return

        now = time.time()
        if DONE_FILE.exists():
            for line in DONE_FILE.read_text(encoding="utf-8").splitlines():
                if "|" not in line:
                    continue
                path, option = line.strip().split("|", 1)
                if path and option:
                    conn.execute(
                        "INSERT OR IGNORE INTO completed_files(path, option, completed_at) VALUES (?, ?, ?)",
                        (path, option, now),
                    )

        if PROBE_CACHE_FILE.exists():
            try:
                cache = json.loads(PROBE_CACHE_FILE.read_text(encoding="utf-8"))
            except Exception:
                cache = {}
            for path, entry in cache.items():
                if not isinstance(entry, dict):
                    continue
                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO probe_cache
                        (path, option, size, mtime_ns, status, message, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            path,
                            entry["opt"],
                            int(entry["size"]),
                            int(entry["mtime_ns"]),
                            entry.get("status", "SKIP"),
                            entry.get("msg", "cached_skip"),
                            now,
                        ),
                    )
                except (KeyError, TypeError, ValueError):
                    continue

        if RUNS_DIR.exists():
            for path in RUNS_DIR.glob("*.json"):
                try:
                    run = json.loads(path.read_text(encoding="utf-8"))
                    save_run(run, conn=conn)
                except Exception:
                    continue

        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES ('legacy_imported', ?)",
            (str(now),),
        )


def load_done() -> dict[str, str]:
    initialize()
    with _connect() as conn:
        return {
            row["path"]: row["option"]
            for row in conn.execute("SELECT path, option FROM completed_files ORDER BY completed_at DESC")
        }


def save_done(done: dict[str, str]) -> None:
    initialize()
    now = time.time()
    with _connect() as conn:
        conn.executemany("DELETE FROM completed_files WHERE path = ?", [(path,) for path in done])
        conn.executemany(
            """INSERT INTO completed_files(path, option, completed_at) VALUES (?, ?, ?)
            ON CONFLICT(path, option) DO UPDATE SET completed_at = excluded.completed_at""",
            [(path, option, now) for path, option in done.items()],
        )


def load_probe_cache() -> dict[str, dict]:
    initialize()
    with _connect() as conn:
        return {
            row["path"]: {
                "opt": row["option"], "size": row["size"],
                "mtime_ns": row["mtime_ns"], "status": row["status"],
                "msg": row["message"],
            }
            for row in conn.execute("SELECT * FROM probe_cache")
        }


def save_probe_cache(cache: dict[str, dict]) -> None:
    initialize()
    now = time.time()
    with _connect() as conn:
        conn.executemany(
            """INSERT INTO probe_cache(path, option, size, mtime_ns, status, message, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET option=excluded.option, size=excluded.size,
            mtime_ns=excluded.mtime_ns, status=excluded.status, message=excluded.message,
            updated_at=excluded.updated_at""",
            [
                (path, entry["opt"], int(entry["size"]), int(entry["mtime_ns"]),
                 entry.get("status", "SKIP"), entry.get("msg", "cached_skip"), now)
                for path, entry in cache.items()
            ],
        )


def save_run(run: dict, conn: sqlite3.Connection | None = None) -> None:
    own_connection = conn is None
    if own_connection:
        initialize()
        conn = _connect()
    assert conn is not None
    summary = run.get("summary") or {}
    folders = run.get("folder_totals") or {}
    conn.execute(
        """INSERT INTO runs(run_id, library, status, started_at, ended_at, exit_code, summary_json, folder_totals_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET library=excluded.library, status=excluded.status,
        started_at=excluded.started_at, ended_at=excluded.ended_at, exit_code=excluded.exit_code,
        summary_json=excluded.summary_json, folder_totals_json=excluded.folder_totals_json""",
        (
            run["run_id"], run.get("library"), summary.get("status"), run.get("started_at"),
            run.get("ended_at"), run.get("exit_code"), json.dumps(summary), json.dumps(folders),
        ),
    )
    conn.execute("DELETE FROM run_results WHERE run_id = ?", (run["run_id"],))
    conn.executemany(
        """INSERT INTO run_results(run_id, sequence, file, status, message, before_bytes, after_bytes)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (run["run_id"], index, result.get("file", ""), result.get("status", ""),
             result.get("msg", ""), int(result.get("before", 0) or 0), int(result.get("after", 0) or 0))
            for index, result in enumerate(run.get("results") or [])
        ],
    )
    conn.execute("DELETE FROM run_events WHERE run_id = ?", (run["run_id"],))
    conn.executemany(
        """INSERT INTO run_events(run_id, sequence, event_type, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?)""",
        [
            (run["run_id"], index, event.get("type", ""), json.dumps(event), float(event.get("ts") or 0))
            for index, event in enumerate(run.get("output") or [])
        ],
    )
    if own_connection:
        conn.commit()
        conn.close()


def list_errors(limit: int = 500) -> list[dict]:
    initialize()
    query = """
        SELECT r.run_id, r.library, r.started_at, r.ended_at,
               rr.file, rr.message, rr.before_bytes, rr.after_bytes
        FROM run_results rr
        JOIN runs r ON r.run_id = rr.run_id
        WHERE rr.status = 'FAIL'
        ORDER BY COALESCE(r.ended_at, r.started_at) DESC, rr.sequence ASC
        LIMIT ?
    """
    with _connect() as conn:
        return [
            {
                "run_id": row["run_id"],
                "library": row["library"],
                "started_at": row["started_at"],
                "file": row["file"],
                "message": row["message"],
                "before": row["before_bytes"],
                "after": row["after_bytes"],
            }
            for row in conn.execute(query, (limit,))
        ]


def _run_from_row(row: sqlite3.Row) -> dict:
    return {
        "run_id": row["run_id"],
        "library": row["library"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "exit_code": row["exit_code"],
        "summary": json.loads(row["summary_json"]),
        "folder_totals": json.loads(row["folder_totals_json"]),
    }


def list_runs(library: str | None = None, limit: int | None = None) -> list[dict]:
    initialize()
    query = "SELECT * FROM runs"
    values: list[object] = []
    if library is not None:
        query += " WHERE library = ?"
        values.append(library)
    query += " ORDER BY COALESCE(ended_at, started_at) DESC"
    if limit is not None:
        query += " LIMIT ?"
        values.append(limit)
    with _connect() as conn:
        return [_run_from_row(row) for row in conn.execute(query, values)]


def load_run(run_id: str) -> dict | None:
    initialize()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            return None
        run = _run_from_row(row)
        run["results"] = [
            {
                "type": "result", "file": result["file"], "status": result["status"],
                "msg": result["message"], "before": result["before_bytes"], "after": result["after_bytes"],
            }
            for result in conn.execute(
                "SELECT * FROM run_results WHERE run_id = ? ORDER BY sequence", (run_id,)
            )
        ]
        run["output"] = [
            json.loads(event["payload_json"])
            for event in conn.execute(
                "SELECT payload_json FROM run_events WHERE run_id = ? ORDER BY sequence", (run_id,)
            )
        ]
        return run

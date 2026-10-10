"""Bounded, idempotent, never-raising TigerData writer. `conn` is any psycopg-style connection."""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

SQL = {
    "run": "INSERT INTO runs (run_id, started_at, scenario, git_sha) VALUES (%s,%s,%s,%s) "
    "ON CONFLICT (run_id) DO NOTHING",
    "event": "INSERT INTO events (ts, run_id, node_id, event_id, kind, payload) "
    "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (run_id, event_id, ts) DO NOTHING",
    "metric": "INSERT INTO metrics (ts, run_id, node_id, name, value, unit) "
    "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (run_id, node_id, name, ts) DO NOTHING",
    "artifact": "INSERT INTO artifacts (run_id, path, sha256, bytes) VALUES (%s,%s,%s,%s) "
    "ON CONFLICT (run_id, path) DO NOTHING",
}
DROPPED = "INSERT INTO dropped_metrics (run_id, kind, dropped) VALUES (%s,%s,%s)"


def connect_from_env() -> Any:
    """TIGERDATA_URL must set sslmode (require/verify-full) unless it points at localhost."""
    url = os.environ["TIGERDATA_URL"]
    if "localhost" not in url and "127.0.0.1" not in url and "sslmode=" not in url:
        raise ValueError("non-local TIGERDATA_URL must set sslmode (require or verify-full)")
    import psycopg

    return psycopg.connect(url, connect_timeout=5)


def migrate(conn: Any) -> None:
    for f in sorted(MIGRATIONS.glob("*.sql")):
        conn.execute(f.read_text())
    conn.commit()


class Writer:
    """Queues rows in memory (max `cap`); on overflow drops the oldest and counts it.
    flush() never raises: on any DB error rows stay queued, it returns False and reconnects
    next time, so an outage cannot stop a node and memory stays bounded."""

    def __init__(self, connect: Callable[[], Any], cap: int = 10_000, batch: int = 500) -> None:
        self._connect, self._batch, self._cap = connect, batch, cap
        self._q: deque[tuple[str, str, tuple[Any, ...]]] = deque()
        self._conn: Any = None
        self.dropped: dict[tuple[str, str], int] = {}  # (run_id, kind) -> unrecorded count
        self.dropped_total = 0  # lifetime rows shed, never reset

    def put(self, kind: str, run_id: str, row: tuple[Any, ...]) -> None:
        if kind not in SQL:
            raise ValueError(kind)
        if len(self._q) >= self._cap:
            k, r, _ = self._q.popleft()
            self.dropped[(r, k)] = self.dropped.get((r, k), 0) + 1
            self.dropped_total += 1
        self._q.append((kind, run_id, row))

    def flush(self) -> bool:
        try:
            if self._conn is None:
                self._conn = self._connect()
            while self._q:
                kind = self._q[0][0]
                rows: list[tuple[Any, ...]] = []
                for k, _, row in self._q:  # leading run of one kind, preserves FK order
                    if k != kind or len(rows) >= self._batch:
                        break
                    rows.append(row)
                with self._conn.cursor() as cur:
                    cur.executemany(SQL[kind], rows)
                self._conn.commit()
                for _ in rows:
                    self._q.popleft()
            if self.dropped:
                with self._conn.cursor() as cur:
                    cur.executemany(DROPPED, [(r, k, n) for (r, k), n in self.dropped.items()])
                self._conn.commit()
                self.dropped.clear()
            return True
        except Exception:
            try:
                if self._conn is not None:
                    self._conn.rollback()
            except Exception:
                pass
            self._conn = None
            return False

    def __len__(self) -> int:
        return len(self._q)

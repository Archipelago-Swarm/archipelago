"""SQLite stand-in for the TigerData connection used by the Writer and queries (tests only).

It speaks the small psycopg subset the code uses (`execute`, `cursor().executemany`, `commit`,
`rollback`, `close`, `%s` placeholders). It is a bounded fallback for logic tests; real
TimescaleDB behavior is covered only where Docker exists
(tests/storage/test_timescale_integration.py).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

SCHEMA = """
CREATE TABLE runs (run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, scenario TEXT, git_sha TEXT);
CREATE TABLE events (ts TEXT NOT NULL, run_id TEXT NOT NULL, node_id TEXT NOT NULL,
    event_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
    UNIQUE (run_id, event_id, ts));
CREATE TABLE metrics (ts TEXT NOT NULL, run_id TEXT NOT NULL, node_id TEXT NOT NULL,
    name TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL,
    UNIQUE (run_id, node_id, name, ts));
CREATE TABLE dropped_metrics (ts TEXT DEFAULT CURRENT_TIMESTAMP, run_id TEXT NOT NULL,
    kind TEXT NOT NULL, dropped INTEGER NOT NULL);
"""


def _adapt(row: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(v.isoformat() if isinstance(v, datetime) else v for v in row)


class _Cursor:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        self.db.executemany(sql.replace("%s", "?"), [_adapt(r) for r in rows])


class SqliteConn:
    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self.db.execute(sql.replace("%s", "?"), _adapt(params))

    def cursor(self) -> _Cursor:
        return _Cursor(self.db)

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()

    def close(self) -> None:
        self.db.close()

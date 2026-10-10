"""API Persister -> Writer -> real TimescaleDB. Runs only where a Docker daemon exists (CI here)."""

import asyncio
import itertools
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from archipelago_api.persistence import Persister

psycopg = pytest.importorskip("psycopg")
from test_timescale_integration import (  # noqa: E402
    _docker_up,
    dsn,  # noqa: F401  (reuse the container fixture)
)

pytestmark = pytest.mark.skipif(not _docker_up(), reason="Docker daemon not reachable")


FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def _persister(monkeypatch: pytest.MonkeyPatch, url: str, **kw: Any) -> Persister:
    monkeypatch.setenv("TIGERDATA_URL", url)
    p = Persister.from_env()
    assert p is not None
    ticks = itertools.count()  # distinct ts per record (metrics are unique on ts), same per pass
    p._now = lambda: FIXED + timedelta(seconds=next(ticks))
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def _count(url: str, table: str, run_id: str) -> int:
    with psycopg.connect(url) as c:
        row = c.execute(f"SELECT count(*) FROM {table} WHERE run_id = %s", (run_id,)).fetchone()
    assert row is not None
    return int(row[0])


def _event(seq: int) -> dict[str, Any]:
    return {"sequence": seq, "type": "delta", "tick": seq, "snapshot": {"x": 1}}


def _record(p: Persister, run_id: str, n: int = 3) -> None:
    p.record_run(run_id, "scn")
    for i in range(1, n + 1):
        p.record_event(run_id, _event(i))


def test_fresh_db_gets_schema_and_rows_land_and_replay_is_idempotent(
    dsn: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    for _ in range(2):  # second pass = replay of identical rows (fresh persister re-migrates too)
        p = _persister(monkeypatch, dsn)
        _record(p, run_id)
        assert asyncio.run(p.flush()) is True
        assert p.migration_failures == 0 and p.dropped == 0
    assert _count(dsn, "runs", run_id) == 1
    assert _count(dsn, "events", run_id) == 3
    assert _count(dsn, "metrics", run_id) == 3  # one sim_tick per delta


def test_shed_run_row_is_quarantined_counted_and_later_rows_still_land(
    dsn: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lost, good = (f"run-{uuid.uuid4().hex[:8]}" for _ in range(2))
    p = _persister(monkeypatch, dsn, _cap=3)
    _record(p, lost, n=3)  # run row + 6 dependents into a 3-row spool: the run row is shed first
    assert p.dropped > 0
    assert asyncio.run(p.flush()) is True  # does not stall on the FK violation
    assert _count(dsn, "runs", lost) == 0 and _count(dsn, "events", lost) == 0
    _record(p, good, n=1)
    assert asyncio.run(p.flush()) is True
    assert _count(dsn, "runs", good) == 1 and _count(dsn, "events", good) == 1
    with psycopg.connect(dsn) as c:
        row = c.execute(
            "SELECT coalesce(sum(dropped), 0) FROM dropped_metrics WHERE run_id = %s", (lost,)
        ).fetchone()
    assert row is not None and row[0] > 0

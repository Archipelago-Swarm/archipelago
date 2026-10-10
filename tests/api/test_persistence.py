import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from archipelago_api.app import create_app, fixture_factory
from archipelago_api.persistence import Persister
from archipelago_api.settings import Settings
from archipelago_storage import Writer
from fastapi.testclient import TestClient

GOOD = Path(__file__).resolve().parents[2] / "packages/contracts/fixtures/good"
TOKEN = "t" * 24
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def cfg(run_id: str = "run-a", max_ticks: int = 100) -> dict[str, Any]:
    c: dict[str, Any] = json.loads((GOOD / "run_config.json").read_text())
    c["run_id"], c["budgets"]["max_ticks"] = run_id, max_ticks
    return c


class FakeSink:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.rows: list[Any] = []
        self.queue: list[Any] = []

    def put(self, kind: str, run_id: str, row: tuple[Any, ...]) -> None:
        self.queue.append((kind, run_id, row))

    def flush(self) -> bool:
        if self.fail:
            raise OSError("db down")
        self.rows += self.queue
        self.queue = []
        return True

    def __len__(self) -> int:
        return len(self.queue)


class DownConn:
    def cursor(self) -> "DownConn":
        raise OSError("db down")

    def rollback(self) -> None: ...


def ev(seq: int) -> dict[str, Any]:
    return {
        "sequence": seq,
        "type": "delta",
        "tick": seq,
        "status": "running",
        "snapshot": {"b": 1},
    }


def test_unset_url_is_a_noop(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="archipelago.persistence"):
        assert Persister.from_env({}) is None
        assert Persister.from_env({"TIGERDATA_URL": ""}) is None
    assert "persistence disabled" in caplog.text


def test_api_runs_unchanged_without_persister(tmp_path: Path) -> None:
    s = Settings(api_token=TOKEN, data_dir=tmp_path, tick_interval=None)
    with TestClient(create_app(s, fixture_factory(GOOD), None), headers=AUTH) as c:
        r = c.post("/v1/runs", json=cfg(), headers={"Idempotency-Key": "k"})
        assert r.status_code == 201


def test_rows_are_ordered_and_snapshots_stripped() -> None:
    sink = FakeSink()
    p = Persister(sink, now=lambda: datetime(2026, 1, 1, tzinfo=UTC))
    p.record_run("r1", "abc")
    p.record_event("r1", ev(1))
    assert asyncio.run(p.flush()) is True
    assert [k for k, _, _ in sink.rows] == ["run", "event", "metric"]  # run first (FK order)
    assert "snapshot" not in sink.rows[1][2][5]


def test_failing_sink_never_raises_and_recovers_without_loss() -> None:
    sink = FakeSink(fail=True)
    p = Persister(sink)
    p.record_event("r1", ev(1))
    assert asyncio.run(p.flush()) is False  # no exception
    sink.fail = False
    assert asyncio.run(p.flush()) is True
    assert len(sink.rows) == 2  # event + metric survived the outage


def test_record_never_raises_on_bad_input() -> None:
    p = Persister(FakeSink())
    p.record_event("r1", {"nonsense": True})
    assert p.queued == 0


def test_spool_is_bounded_and_counts_drops() -> None:
    p = Persister(FakeSink(fail=True), cap=5)
    for i in range(1, 51):
        p.record_event("r1", {"sequence": i, "type": "status", "tick": 0})
    assert p.queued == 5 and p.dropped == 45
    asyncio.run(p.flush())
    assert p.dropped == 45  # moving rows into the sink neither loses nor double counts


def test_real_writer_outage_stays_bounded_with_total_counter() -> None:
    p = Persister(Writer(DownConn, cap=3), cap=3)
    for i in range(1, 31):
        p.record_event("r1", {"sequence": i, "type": "status", "tick": 0})
        asyncio.run(p.flush())
    assert p.queued <= 6 and p.dropped == 30 - p.queued


def test_run_completes_with_dead_database(tmp_path: Path) -> None:
    """Whole API with a dead DB: the run finishes, shutdown returns, drops are counted."""
    p = Persister(Writer(DownConn, cap=4), cap=4, interval=0.01)
    s = Settings(api_token=TOKEN, data_dir=tmp_path, tick_interval=None)
    with TestClient(create_app(s, fixture_factory(GOOD), p), headers=AUTH) as c:
        r = c.post("/v1/runs", json=cfg(max_ticks=3), headers={"Idempotency-Key": "k"})
        assert r.status_code == 201
        rev = c.get("/v1/runs/run-a").json()["revision"]
        body = {"command": "pause", "expected_revision": rev, "command_id": "c0"}
        assert c.post("/v1/runs/run-a/commands", json=body).status_code == 200
        for i in range(3):
            rev = c.get("/v1/runs/run-a").json()["revision"]
            body = {"command": "step", "expected_revision": rev, "command_id": f"s{i}"}
            assert c.post("/v1/runs/run-a/commands", json=body).status_code == 200
        assert c.get("/v1/runs/run-a").json()["status"] == "completed"
    assert p.dropped > 0 and p.queued <= 8

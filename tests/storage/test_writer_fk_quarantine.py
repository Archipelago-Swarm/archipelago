"""A shed parent `run` row must not stall the all-or-nothing batch forever."""

from typing import Any

import pytest
from archipelago_storage import Writer, validate_url
from archipelago_storage.writer import SQL


class FkError(Exception):
    sqlstate = "23503"


class FkConn:
    """Emulates the runs FK: event/metric rows need their run row to exist first."""

    def __init__(self, store: dict[str, Any], down: dict[str, bool]) -> None:
        self.store, self.down = store, down
        self.pending: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> "FkConn":
        return self

    def __enter__(self) -> "FkConn":
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        if self.down["v"]:
            raise OSError("db down")
        kind = next((k for k, v in SQL.items() if v == sql), "dropped")
        for r in rows:
            if kind in ("event", "metric") and r[1] not in self.store["runs"]:
                raise FkError("fk")
            self.pending.append((kind, r))

    def commit(self) -> None:
        for kind, r in self.pending:
            if kind == "run":
                self.store["runs"].add(r[0])
            else:
                self.store.setdefault(kind, []).append(r)
        self.pending = []

    def rollback(self) -> None:
        self.pending = []


def test_fk_poisoned_rows_are_quarantined_not_stalled() -> None:
    store: dict[str, Any] = {"runs": set()}
    w = Writer(lambda: FkConn(store, {"v": False}))
    for i in range(3):  # run row for r1 was shed: only dependents arrive
        w.put("event", "r1", (f"t{i}", "r1", "n", f"e{i}", "x", "{}"))
    w.put("run", "r2", ("r2", "t", "s", None))
    w.put("event", "r2", ("t", "r2", "n", "e0", "x", "{}"))
    assert w.flush() is True
    assert len(w) == 0
    assert w.dropped_total == 3
    assert store["event"] == [("t", "r2", "n", "e0", "x", "{}")]  # healthy run unaffected
    assert w.dropped == {}  # the dropped counter row was recorded


def test_outage_is_not_mistaken_for_fk_poison() -> None:
    store: dict[str, Any] = {"runs": set()}
    w = Writer(lambda: FkConn(store, {"v": True}))
    w.put("run", "r1", ("r1", "t", "s", None))
    assert w.flush() is False and len(w) == 1 and w.dropped_total == 0


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u@localhost/x",
        "postgresql://u@127.0.0.1:5432/x",
        "postgresql://u:p@timescaledb:5432/x",
        "postgresql://u@db.example.com/x?sslmode=require",
    ],
)
def test_validate_url_accepts(url: str) -> None:
    validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u@db.example.com/x",
        "postgresql://localhost:p@db.example.com/x",  # 'localhost' only in userinfo
        "postgresql://u@db.example.com/x?application_name=sslmode",
    ],
)
def test_validate_url_rejects(url: str) -> None:
    with pytest.raises(ValueError):
        validate_url(url)

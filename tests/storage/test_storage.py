import json
import re
from pathlib import Path

import pytest
from archipelago_storage import Writer
from archipelago_storage.writer import MIGRATIONS, SQL, connect_from_env

ROOT = Path(__file__).resolve().parents[2]


class FakeConn:
    """Emulates ON CONFLICT DO NOTHING by keying on the row's unique tuple."""

    def __init__(self, store: dict, fail: bool = False) -> None:
        self.store, self.fail = store, fail

    def cursor(self) -> "FakeConn":
        return self

    def __enter__(self) -> "FakeConn":
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def executemany(self, sql: str, rows: list) -> None:
        if self.fail:
            raise OSError("db down")
        kind = next((k for k, v in SQL.items() if v == sql), "dropped")
        for r in rows:
            self.store.setdefault((kind, r if kind != "metric" else r[:4]), r)

    def commit(self) -> None: ...
    def rollback(self) -> None: ...


def ev(i: int) -> tuple:
    return (f"t{i}", "r1", "n1", f"e{i}", "x", "{}")


def test_retry_does_not_duplicate_and_outage_keeps_backlog() -> None:
    store: dict = {}
    state = {"fail": True}
    w = Writer(lambda: FakeConn(store, state["fail"]))
    w.put("run", "r1", ("r1", "t0", "s", "g"))
    w.put("event", "r1", ev(1))
    assert w.flush() is False and len(w) == 2 and not store
    state["fail"] = False
    assert w.flush() is True and len(w) == 0 and len(store) == 2
    w.put("event", "r1", ev(1))  # replay of the same event
    w.flush()
    assert len(store) == 2


def test_backlog_bounded_and_drops_recorded() -> None:
    store: dict = {}
    state = {"fail": True}
    w = Writer(lambda: FakeConn(store, state["fail"]), cap=3)
    for i in range(10):
        w.put("event", "r1", ev(i))
    assert len(w) == 3 and w.dropped == {("r1", "event"): 7}
    state["fail"] = False
    assert w.flush() and w.dropped == {}
    assert ("dropped", ("r1", "event", 7)) in store
    assert sum(1 for k in store if k[0] == "event") == 3


def test_connect_requires_ssl_for_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIGERDATA_URL", "postgresql://u@db.example.com:5432/x")
    with pytest.raises(ValueError):
        connect_from_env()


def test_migrations_cover_writer_tables_and_conflict_targets() -> None:
    ddl = "\n".join(p.read_text() for p in sorted(MIGRATIONS.glob("*.sql")))
    for t in re.findall(r"INSERT INTO (\w+)", " ".join(SQL.values())):
        assert re.search(rf"CREATE TABLE IF NOT EXISTS {t}\b", ddl), t
    # hypertable unique constraints must include the partition column
    for tbl in ("events", "metrics"):
        assert re.search(rf"create_hypertable\('{tbl}', 'ts'", ddl)
        uniq = re.search(rf"CREATE TABLE IF NOT EXISTS {tbl} \(.*?UNIQUE \(([^)]*)\)", ddl, re.S)
        assert uniq and "ts" in [c.strip() for c in uniq.group(1).split(",")]
    assert "PASSWORD '" not in ddl.upper()


def test_grafana_dashboard_units_and_provisioning() -> None:
    d = json.loads((ROOT / "observability/grafana/dashboards/archipelago.json").read_text())
    units = {p["title"]: p["fieldConfig"]["defaults"].get("unit") for p in d["panels"][:3]}
    assert units == {"Coverage": "percentunit", "Transfer": "bytes", "Latency": "ms"}
    for p in d["panels"]:
        assert p["datasource"]["uid"] == "tigerdata"
    ds = (ROOT / "observability/grafana/provisioning/datasources/tigerdata.yml").read_text()
    assert "uid: tigerdata" in ds and "${TIGERDATA_GRAFANA_PASSWORD}" in ds

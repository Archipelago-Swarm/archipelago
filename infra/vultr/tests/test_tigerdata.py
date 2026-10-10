import json
from typing import Any

from archipelago_ops import tigerdata

W = "postgresql://writer:Wpass-secret@db.example.tsdb.cloud:5432/tsdb?sslmode=require"
R = "postgresql://reader:Rpass-secret@db.example.tsdb.cloud:5432/tsdb?sslmode=require"
A = "postgresql://owner:Apass-secret@db.example.tsdb.cloud:5432/tsdb?sslmode=require"
PASSWORDS = ("Wpass-secret", "Rpass-secret", "Apass-secret")


class Denied(Exception):
    sqlstate = "42501"


class Fake:
    def __init__(self, allow: set[str], log: list[str]):
        self.allow, self.log, self.closed = allow, log, False

    def execute(self, sql: str, params: Any = ()) -> None:
        verb = sql.split()[0].upper()
        self.log.append(verb)
        if verb not in self.allow:
            raise Denied(f"permission denied; password=Wpass-secret url={W}")

    def commit(self) -> None:
        self.log.append("COMMIT")

    def rollback(self) -> None:
        self.log.append("ROLLBACK")

    def close(self) -> None:
        self.closed = True


def factory(roles: dict[str, set[str]], log: list[str]) -> Any:
    def connect(url: str) -> Fake:
        return Fake(roles[url], log)

    return connect


ADMIN = {"CREATE", "DO", "GRANT", "ALTER", "SELECT", "INSERT", "DROP", "--"}
GOOD = {W: {"SELECT", "INSERT"}, R: {"SELECT"}, A: ADMIN}
ENV = {"TIGERDATA_URL": W, "TIGERDATA_READER_URL": R, "TIGERDATA_ADMIN_URL": A}


def test_all_checks_pass_and_report_has_no_credentials() -> None:
    log: list[str] = []
    rep = tigerdata.run_checks(ENV, factory(GOOD, log))
    assert rep["ok"] is True, rep
    names = {c["check"] for c in rep["checks"]}
    assert {
        "tls_required",
        "migrations_idempotent",
        "writer_can_insert",
        "writer_cannot_drop",
        "reader_can_select",
        "reader_cannot_insert",
        "reader_cannot_delete",
    } <= names
    blob = json.dumps(rep)
    assert not any(p in blob for p in PASSWORDS)
    assert "db.example.tsdb.cloud" in blob
    assert log.count("COMMIT") == 2  # migrate() ran twice
    assert log.count("ROLLBACK") >= 5  # probes never persist


def test_writer_that_can_drop_fails() -> None:
    roles = {**GOOD, W: {"SELECT", "INSERT", "DROP"}}
    rep = tigerdata.run_checks(ENV, factory(roles, []))
    bad = [c for c in rep["checks"] if not c["ok"]]
    assert rep["ok"] is False and [c["check"] for c in bad] == ["writer_cannot_drop"]


def test_reader_that_can_write_fails() -> None:
    roles = {**GOOD, R: {"SELECT", "INSERT", "DELETE"}}
    rep = tigerdata.run_checks(ENV, factory(roles, []))
    assert {c["check"] for c in rep["checks"] if not c["ok"]} == {
        "reader_cannot_insert",
        "reader_cannot_delete",
    }


def test_writer_that_cannot_insert_fails() -> None:
    rep = tigerdata.run_checks(ENV, factory({**GOOD, W: {"SELECT"}}, []))
    assert [c["check"] for c in rep["checks"] if not c["ok"]] == ["writer_can_insert"]


def test_non_tls_remote_url_refused_without_connecting() -> None:
    calls: list[str] = []

    def connect(url: str) -> Any:
        calls.append(url)
        raise AssertionError("must not connect")

    bad = "postgresql://w:Wpass-secret@db.example.tsdb.cloud/tsdb"
    rep = tigerdata.run_checks({"TIGERDATA_URL": bad}, connect)
    assert rep["ok"] is False and calls == []
    assert "Wpass-secret" not in json.dumps(rep)


def test_missing_url_and_unverified_reader() -> None:
    assert tigerdata.run_checks({}, factory({}, []))["ok"] is False
    rep = tigerdata.run_checks({"TIGERDATA_URL": W}, factory({W: ADMIN | {"INSERT"}}, []))
    assert rep["ok"] is False  # writer can drop here, and reader unverified
    assert any(c["check"] == "reader_checked" and not c["ok"] for c in rep["checks"])


def test_connection_error_is_sanitised() -> None:
    def connect(url: str) -> Any:
        raise RuntimeError(f"could not connect to {url}")

    rep = tigerdata.run_checks(ENV, connect)
    assert rep["ok"] is False
    assert not any(p in json.dumps(rep) for p in PASSWORDS)

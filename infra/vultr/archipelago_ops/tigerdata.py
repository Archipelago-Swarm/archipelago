"""TigerData connectivity, migration and role checker. Reports never contain credentials.

URLs come from the environment: TIGERDATA_URL (writer login role, required), TIGERDATA_READER_URL
(reader login role), TIGERDATA_ADMIN_URL (owner, used for migrations; defaults to TIGERDATA_URL).
Probes run inside a transaction that is always rolled back, so nothing is created or dropped.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_STORAGE = Path(__file__).resolve().parents[3] / "packages" / "storage"
if str(_STORAGE) not in sys.path:
    sys.path.insert(0, str(_STORAGE))

from archipelago_storage import migrate  # noqa: E402
from archipelago_storage.writer import validate_url  # noqa: E402

Connect = Callable[[str], Any]
INSUFFICIENT_PRIVILEGE = "42501"


def default_connect(url: str) -> Any:
    import psycopg

    return psycopg.connect(url, connect_timeout=5)


def _host(url: str) -> str:
    return urlsplit(url).hostname or "unknown"


def _denied(exc: BaseException) -> bool:
    return (
        getattr(exc, "sqlstate", None) == INSUFFICIENT_PRIVILEGE
        or type(exc).__name__ == "InsufficientPrivilege"
    )


def _err(exc: BaseException) -> str:
    """Class name and sqlstate only: driver messages can echo connection details."""
    return f"{type(exc).__name__} sqlstate={getattr(exc, 'sqlstate', None)}"


def _probe(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> tuple[bool, str]:
    """Run sql in a transaction that is rolled back. Return (succeeded, detail)."""
    try:
        conn.execute(sql, params)
        return True, "ok"
    except Exception as e:
        return False, "denied" if _denied(e) else _err(e)
    finally:
        try:
            conn.rollback()
        except Exception:  # noqa: S110 - connection already unusable; result is recorded above
            pass


def _check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "ok": ok, "detail": detail}


def check_writer(conn: Any) -> list[dict[str, Any]]:
    rid = f"ops-probe-{uuid.uuid4().hex[:12]}"
    ins, d1 = _probe(
        conn,
        "INSERT INTO runs (run_id, started_at, scenario, git_sha) VALUES (%s, now(), %s, %s)",
        (rid, "ops-probe", "0" * 12),
    )
    drop, d2 = _probe(conn, "DROP TABLE runs")
    return [
        _check("writer_can_insert", ins, d1),
        _check("writer_cannot_drop", (not drop) and d2 == "denied", "dropped!" if drop else d2),
    ]


def check_reader(conn: Any) -> list[dict[str, Any]]:
    sel, d1 = _probe(conn, "SELECT 1 FROM runs LIMIT 1")
    ins, d2 = _probe(
        conn,
        "INSERT INTO runs (run_id, started_at, scenario, git_sha) VALUES (%s, now(), %s, %s)",
        (f"ops-probe-{uuid.uuid4().hex[:12]}", "ops-probe", "0" * 12),
    )
    upd, d3 = _probe(conn, "DELETE FROM runs WHERE false")
    return [
        _check("reader_can_select", sel, d1),
        _check("reader_cannot_insert", (not ins) and d2 == "denied", "inserted!" if ins else d2),
        _check("reader_cannot_delete", (not upd) and d3 == "denied", "deleted!" if upd else d3),
    ]


def run_checks(env: dict[str, str], connect: Connect = default_connect) -> dict[str, Any]:
    """Return the tigerdata-report.json content. ok is True only if every check ran and passed."""
    checks: list[dict[str, Any]] = []
    report: dict[str, Any] = {"hosts": {}, "checks": checks}
    writer_url = env.get("TIGERDATA_URL", "")
    if not writer_url:
        checks.append(_check("tigerdata_url_set", False, "TIGERDATA_URL not set"))
        report["ok"] = False
        return report
    try:
        validate_url(writer_url)
    except ValueError as e:
        checks.append(_check("tls_required", False, str(e)))
        report["ok"] = False
        return report
    checks.append(_check("tls_required", True, "validate_url accepted TIGERDATA_URL"))
    report["hosts"]["writer"] = _host(writer_url)

    admin_url = env.get("TIGERDATA_ADMIN_URL") or writer_url
    try:
        validate_url(admin_url)
        admin = connect(admin_url)
        try:
            migrate(admin)
            migrate(admin)  # second pass proves idempotence
        finally:
            admin.close()
        checks.append(_check("migrations_idempotent", True, "applied twice without error"))
    except Exception as e:
        checks.append(_check("migrations_idempotent", False, _err(e)))

    def role(name: str, url: str, fn: Callable[[Any], list[dict[str, Any]]]) -> None:
        if not url:
            checks.append(_check(f"{name}_checked", False, "URL not provided: unverified"))
            return
        try:
            validate_url(url)
            report["hosts"][name] = _host(url)
            conn = connect(url)
            try:
                checks.extend(fn(conn))
            finally:
                conn.close()
        except Exception as e:
            checks.append(_check(f"{name}_connect", False, _err(e)))

    role("writer", writer_url, check_writer)
    role("reader", env.get("TIGERDATA_READER_URL", ""), check_reader)
    report["ok"] = all(c["ok"] for c in checks)
    return report


def main(env: dict[str, str] | None = None, connect: Connect = default_connect) -> dict[str, Any]:
    return run_checks(dict(os.environ) if env is None else env, connect)

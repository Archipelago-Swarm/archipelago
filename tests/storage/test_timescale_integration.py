"""Real TimescaleDB checks. Skipped unless a Docker daemon is reachable and psycopg is installed."""

import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from archipelago_storage import Writer, migrate


def _docker_up() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.skipif(not _docker_up(), reason="Docker daemon not reachable")


@pytest.fixture(scope="module")
def dsn() -> Iterator[str]:
    name = f"arch-ts-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "-e", "POSTGRES_PASSWORD=pw",
         "-p", "127.0.0.1::5432", "timescale/timescaledb:2.17.2-pg16"],
        check=True, capture_output=True,
    )  # fmt: skip
    try:
        out = subprocess.run(["docker", "port", name, "5432"], capture_output=True, text=True)
        port = out.stdout.split(":")[-1].strip()
        url = f"postgresql://postgres:pw@127.0.0.1:{port}/postgres"
        for _ in range(60):
            try:
                psycopg.connect(url, connect_timeout=2).close()
                break
            except Exception:
                time.sleep(1)
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def test_migrate_twice_ingest_replay_and_reader_role(dsn: str) -> None:
    conn: Any = psycopg.connect(dsn)
    migrate(conn)
    migrate(conn)  # idempotent
    w = Writer(lambda: psycopg.connect(dsn))
    ts = "2026-01-01T00:00:00Z"
    for _ in range(2):  # second pass = retry/replay
        w.put("run", "r1", ("r1", ts, "s", "g"))
        w.put("event", "r1", (ts, "r1", "n1", "e1", "x", "{}"))
        w.put("metric", "r1", (ts, "r1", "n1", "latency_ms", 1.5, "ms"))
        assert w.flush()
    cur = conn.execute("SELECT (SELECT count(*) FROM events), (SELECT count(*) FROM metrics)")
    assert cur.fetchone() == (1, 1)
    conn.execute("SET ROLE archipelago_reader")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM events")

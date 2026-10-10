"""Migration 0003, the demo views and the report queries on real TimescaleDB.

CI-only: needs a reachable Docker daemon (the authoring sandbox has none), same guard as
test_timescale_integration.py. The logic of the queries is covered without Docker in
test_queries.py on a SQLite stand-in; this file proves the SQL itself on PostgreSQL.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from archipelago_storage import migrate, queries, report


def _docker_up() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


psycopg = pytest.importorskip("psycopg")
pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not _docker_up(), reason="Docker daemon not reachable"),
]


@pytest.fixture(scope="module")
def dsn() -> Iterator[str]:
    name = f"arch-views-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "-e", "POSTGRES_PASSWORD=pw",
         "-p", "127.0.0.1::5432", "timescale/timescaledb:2.17.2-pg16"],
        check=True, capture_output=True,
    )  # fmt: skip
    try:
        out = subprocess.run(["docker", "port", name, "5432"], capture_output=True, text=True)
        url = f"postgresql://postgres:pw@127.0.0.1:{out.stdout.split(':')[-1].strip()}/postgres"
        for _ in range(60):
            try:
                psycopg.connect(url, connect_timeout=2).close()
                break
            except Exception:
                time.sleep(1)
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def test_views_and_reports_on_postgres(dsn: str) -> None:
    from test_queries import persist, variant  # recorded partition run through the Persister

    conn: Any = psycopg.connect(dsn)
    migrate(conn)
    migrate(conn)  # 0003 is idempotent
    for rid, scale, cov in (("run-a", 1.0, 0.4), ("run-b", 2.0, 0.7)):
        persist(psycopg.connect(dsn), rid, variant(scale, extra_coverage=cov))  # real database
    learn = queries.learning_curves(conn, "run-a")
    assert [p["update_count"] for p in learn["nodes"]["node-02"]] == [8, 16]
    assert [s["phase"] for s in queries.phase_timeline(conn, "run-a")["segments"]] == [
        "connected", "partition", "recovery", "connected",
    ]  # fmt: skip
    cmp = queries.compare(conn, "run-a", "run-b")
    assert cmp["delta_b_minus_a"]["episode_return_eval_final"] == 3
    assert report.main(["run-a", "--compare", "run-b"], conn=conn) == 0
    # the views expose the same shapes to Grafana, readable by the reader role
    conn.execute("SET ROLE archipelago_reader")
    rows = conn.execute(
        "SELECT node_id, update_count, policy_version FROM demo_learning "
        "WHERE run_id = 'run-a' ORDER BY sim_tick, node_id"
    ).fetchall()
    assert rows[0][0] in ("node-01", "node-02") and len(rows) == 3
    assert conn.execute(
        "SELECT count(*) FROM demo_peer_decisions WHERE run_id = 'run-a'"
    ).fetchone() == (3,)
    assert [r[0] for r in conn.execute(
        "SELECT phase FROM demo_fault_phases WHERE run_id = 'run-a' ORDER BY sim_tick"
    ).fetchall()] == ["other", "partition", "recovery", "other"]  # fmt: skip
    assert conn.execute(
        "SELECT count(*) FROM demo_task_curves WHERE run_id = 'run-a' AND phase = 'eval'"
    ).fetchone() == (3,)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM events")

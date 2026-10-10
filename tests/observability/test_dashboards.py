"""Provisioning, phase behavior, and real-schema query checks without silent skips."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
GRAFANA = ROOT / "observability/grafana"
MIGRATIONS = ROOT / "packages/storage/migrations"
DASHBOARDS = [
    json.loads(path.read_text(encoding="utf-8"))
    for path in sorted((GRAFANA / "dashboards").glob("*.json"))
]
LIVE = next(dash for dash in DASHBOARDS if dash["uid"] == "archipelago-live")


def queries() -> Iterator[str]:
    for dashboard in DASHBOARDS:
        for variable in dashboard["templating"]["list"]:
            yield variable["query"]
        for panel in dashboard["panels"]:
            for target in panel["targets"]:
                yield target["rawSql"]
        for annotation in dashboard.get("annotations", {}).get("list", []):
            yield annotation["target"]["rawSql"]


def render(sql: str) -> str:
    sql = sql.replace("${run_id:sqlstring}", "'r1'")
    return re.sub(
        r"\$__timeFilter\((\w+)\)",
        r"\1 >= '2000-01-01T00:00:00Z' AND \1 <= '2100-01-01T00:00:00Z'",
        sql,
    )


def static_database() -> sqlite3.Connection:
    """Parse the migrated tables; SQLite compiles the bounded SELECT grammar."""
    conn = sqlite3.connect(":memory:")
    for path in sorted(MIGRATIONS.glob("*.sql")):
        source = path.read_text(encoding="utf-8")
        for table, body in re.findall(
            r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", source, re.S
        ):
            columns = []
            for line in body.splitlines():
                match = re.match(r"\s*(\w+)\s+(text|timestamptz|jsonb|double|bigint)\b", line)
                if match:
                    name, kind = match.groups()
                    dtype = (
                        "REAL" if kind == "double" else "INTEGER" if kind == "bigint" else "TEXT"
                    )
                    columns.append(f'"{name}" {dtype}')
            assert columns, f"Unparsed migration table: {table}"
            conn.execute(f'CREATE TABLE "{table}" ({", ".join(columns)})')
    return conn


def sqlite_sql(sql: str) -> str:
    # PostgreSQL jsonb_build_object is SQLite json_object; ->> is native in both.
    return render(sql).replace("jsonb_build_object", "json_object")


def test_provisioning_and_reader_only_configuration() -> None:
    provision = yaml.safe_load(
        (GRAFANA / "provisioning/datasources/tigerdata.yml").read_text(encoding="utf-8")
    )
    assert provision["apiVersion"] == 1
    assert len(provision["datasources"]) == 1
    datasource = provision["datasources"][0]
    assert datasource["uid"] == "tigerdata"
    assert datasource["type"] == "grafana-postgresql-datasource"
    assert datasource["access"] == "proxy"
    assert datasource["jsonData"]["timescaledb"] is True
    for value in (
        datasource["url"],
        datasource["user"],
        datasource["secureJsonData"]["password"],
        datasource["jsonData"]["sslmode"],
    ):
        assert re.fullmatch(r"\$\{[A-Z_]+\}", value), "Credentials/config must come from env"
    providers = yaml.safe_load(
        (GRAFANA / "provisioning/dashboards/dashboards.yml").read_text(encoding="utf-8")
    )
    assert providers["apiVersion"] == 1
    assert providers["providers"][0]["type"] == "file"
    assert providers["providers"][0]["options"]["path"] == "/var/lib/grafana/dashboards"

    compose = yaml.safe_load((ROOT / "observability/docker-compose.yml").read_text())
    grafana = compose["services"]["grafana"]
    assert grafana["entrypoint"] == ["/bin/sh", "/etc/grafana/require-reader.sh"]
    for key in (
        "TIGERDATA_GRAFANA_HOST",
        "TIGERDATA_GRAFANA_USER",
        "TIGERDATA_GRAFANA_PASSWORD",
        "TIGERDATA_GRAFANA_SSLMODE",
        "GF_SECURITY_ADMIN_PASSWORD",
    ):
        assert grafana["environment"][key].startswith("${")
    guard = (GRAFANA / "require-reader.sh").read_text()
    assert '!= "archipelago_reader"' in guard
    init = (GRAFANA / "init-reader.sh").read_text()
    assert "ALTER ROLE archipelago_reader LOGIN PASSWORD :'reader_password'" in init
    assert "default_transaction_read_only = on" in init
    assert "GRANT" not in init
    roles = (MIGRATIONS / "0002_roles.sql").read_text()
    assert re.search(r"GRANT SELECT ON .* TO archipelago_reader;", roles)
    assert not re.search(r"GRANT .*?(INSERT|UPDATE|DELETE).*? TO archipelago_reader;", roles)

    uids = set()
    for dashboard in DASHBOARDS:
        assert dashboard["uid"] not in uids
        uids.add(dashboard["uid"])
        ids = [panel["id"] for panel in dashboard["panels"]]
        assert len(ids) == len(set(ids))
        assert dashboard["schemaVersion"] >= 39
        variable = dashboard["templating"]["list"][0]
        assert variable["name"] == "run_id"
        assert not variable.get("multi", False)
        assert not variable.get("includeAll", False)
        assert variable["datasource"]["uid"] == datasource["uid"]
        for panel in dashboard["panels"]:
            assert panel["title"]
            assert panel["datasource"]["uid"] == datasource["uid"]
            assert panel["fieldConfig"]["defaults"]["unit"]
            assert panel["fieldConfig"]["defaults"]["noValue"] == "No data"
            assert panel["targets"]
            for target in panel["targets"]:
                assert target["rawQuery"] is True
                assert target["format"] in {"time_series", "table"}
                assert "${run_id:sqlstring}" in target["rawSql"]
                assert "$__timeFilter(ts)" in target["rawSql"]
                assert "'$run'" not in target["rawSql"]


def test_all_queries_compile_against_migration_columns_and_empty_data() -> None:
    conn = static_database()
    try:
        for sql in queries():
            statement = sqlite_sql(sql)
            assert statement.startswith("SELECT ")
            assert ";" not in statement
            assert "$" not in statement, f"Unexpanded Grafana variable: {statement}"
            conn.execute("EXPLAIN " + statement).fetchall()
            assert conn.execute(statement).fetchall() == [], sql
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("EXPLAIN SELECT imaginary_column FROM events")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("EXPLAIN SELECT value FROM nonexistent_table")
    finally:
        conn.close()


def sample(conn: sqlite3.Connection, event_id: str, kind: str, payload: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-10-10T20:00:00Z", "r1", "node-01", event_id, kind, json.dumps(payload)),
    )


def test_training_eval_decisions_and_fault_phases_are_observable() -> None:
    conn = static_database()
    try:
        for phase, value in (("train", 0.25), ("eval", 0.75)):
            for metric in ("coverage", "episode_return"):
                sample(
                    conn,
                    phase + metric,
                    "metric_sample",
                    {"phase": phase, "metric": metric, "value": value},
                )
        for index, decision in enumerate(("accepted", "rejected", "rejected", "none")):
            sample(
                conn,
                f"decision-{index}",
                "learning_event",
                {
                    "transfer": decision,
                    "reason": "margin" if decision == "rejected" else None,
                    "candidate_score": 2.0,
                    "previous_version": 3,
                    "new_version": 4,
                    "update_count": 11,
                    "loss": None,
                },
            )
        for phase in ("partition", "recovery"):
            sample(conn, phase, "metric_sample", {"metric": "fault_phase", "phase": phase})
        for panel in LIVE["panels"]:
            sql = panel["targets"][0]["rawSql"]
            rows = conn.execute(sqlite_sql(sql)).fetchall()
            if "— training" in panel["title"] or "— frozen evaluation" in panel["title"]:
                phase = "train" if "— training" in panel["title"] else "eval"
                assert f"payload->>'phase' = '{phase}'" in sql
                assert [row[2] for row in rows] == [0.25 if phase == "train" else 0.75]
            elif panel["title"] == "Peer decisions — accepted / rejected":
                assert dict(rows) == {"accepted": 1, "rejected": 2}
            elif panel["title"] == "Peer decisions — reasons and candidate scores":
                assert len(rows) == 3
                assert sum(row[3] == "margin" for row in rows) == 2
            elif panel["title"] == "Optimizer updates per node":
                assert [row[2] for row in rows] == [11, 11, 11, 11]
            elif panel["title"] == "Training loss per node":
                assert [row[2] for row in rows] == [None, None, None, None]
            elif panel["title"] == "Policy version per node":
                assert [row[2] for row in rows] == [4, 4, 4, 4]
            elif panel["type"] == "state-timeline":
                assert {row[2] for row in rows} == {"partition", "recovery"}
        conn.execute(
            "INSERT INTO dropped_metrics VALUES (?, ?, ?, ?)",
            ("2026-10-10T20:00:00Z", "r1", "metric", 7),
        )
        drop_panel = next(p for p in LIVE["panels"] if p["title"] == "Persistence dropped rows")
        assert conn.execute(sqlite_sql(drop_panel["targets"][0]["rawSql"])).fetchall()[0][2] == 7
        conn.execute("DELETE FROM dropped_metrics")
        conn.execute("DELETE FROM events")
        for panel in LIVE["panels"]:
            assert conn.execute(sqlite_sql(panel["targets"][0]["rawSql"])).fetchall() == []
    finally:
        conn.close()


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(
            ["docker", "info"], capture_output=True, timeout=20, check=False
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def test_postgresql_queries_under_reader_role_when_docker_available() -> None:
    if not docker_available():
        warnings.warn(
            "TimescaleDB EXPLAIN not run: Docker daemon unavailable. "
            "Static migrated-schema SQL validation runs unconditionally.",
            UserWarning,
            stacklevel=1,
        )
        return
    import psycopg
    from archipelago_storage import migrate

    name = f"arch-grafana-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name,
            "-e", "POSTGRES_PASSWORD=test-only", "-p", "127.0.0.1::5432",
            "timescale/timescaledb:2.17.2-pg16",
        ],
        capture_output=True,
        check=True,
    )
    try:
        port = subprocess.run(
            ["docker", "port", name, "5432"], capture_output=True, text=True, check=True
        ).stdout.strip().rsplit(":", 1)[1]
        dsn = f"postgresql://postgres:test-only@127.0.0.1:{port}/postgres"
        deadline = time.monotonic() + 60
        while True:
            try:
                conn = psycopg.connect(dsn, connect_timeout=2, autocommit=True)
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        with conn:
            migrate(conn)
            conn.execute("SET ROLE archipelago_reader")
            for sql in queries():
                conn.execute("EXPLAIN " + render(sql)).fetchall()
                assert conn.execute(render(sql)).fetchall() == []
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(
                    "INSERT INTO runs (run_id, started_at) VALUES ('denied', now())"
                )
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=True)

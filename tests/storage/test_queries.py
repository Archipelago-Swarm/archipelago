"""Report queries and Grafana panels against rows the API Persister actually writes.

The recorded sequence is apps/web/src/fixtures/partition_run.json (the shapes the dashboard
panels are built on), pushed through Persister -> Writer -> SQLite stand-in. Real TimescaleDB
(migrations, views, reader role) is exercised only where Docker exists, see
test_timescale_integration.py (CI-only on this repository's runners without a daemon).
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from archipelago_api.persistence import Persister
from archipelago_storage import Writer, queries, report
from fakedb import SqliteConn

ROOT = Path(__file__).resolve().parents[2]
RECORDED = json.loads((ROOT / "apps/web/src/fixtures/partition_run.json").read_text())
DASH = json.loads((ROOT / "observability/grafana/dashboards/live-experiment.json").read_text())
CTX = {
    "commit": "94712c5",
    "config_hash": "c" * 64,
    "seed": 7,
    "host": "node-host-1",
    "boot_id": "b0",
    "episode": 0,
}


def persist(db: SqliteConn, run_id: str, records: list[dict[str, Any]]) -> None:
    sink = Writer(lambda: db)
    p = Persister(sink, now=lambda: datetime(2026, 10, 10, tzinfo=UTC))
    p.record_run(run_id, "scenario-x", "94712c5")
    for i, rec in enumerate(records, 1):
        ev = {**rec, "run_id": run_id, "type": rec["kind"], "sequence": i, "tick": rec["sim_tick"]}
        p.record_event(run_id, ev, CTX)
    assert asyncio.run(p.flush()) is True


def variant(scale: float, *, extra_coverage: float) -> list[dict[str, Any]]:
    """The recorded run with returns scaled, plus swarm-level coverage samples."""
    out: list[dict[str, Any]] = []
    for rec in RECORDED:
        rec = dict(rec)
        if rec.get("metric") == "episode_return":
            rec["value"] = rec["value"] * scale
        out.append(rec)
    for n, (phase, tick, v) in enumerate(
        [("train", 7, extra_coverage), ("eval", 9, extra_coverage)]
    ):
        out.append(
            {
                **{k: RECORDED[1][k] for k in ("schema_version", "emitted_at_utc", "run_id")},
                "kind": "metric_sample", "event_id": f"cov-{n}", "source_node_id": None,
                "sim_tick": tick, "sequence": 100 + n, "metric": "coverage", "value": v,
                "unit": "fraction", "phase": phase,
            }
        )  # fmt: skip
    return out


@pytest.fixture
def db() -> SqliteConn:
    conn = SqliteConn()
    persist(conn, "run-a", variant(1.0, extra_coverage=0.4))
    persist(conn, "run-b", variant(2.0, extra_coverage=0.7))
    return conn


def test_persister_rows_carry_node_identity_and_context(db: SqliteConn) -> None:
    rows = db.execute(
        "SELECT node_id, event_id, kind, payload FROM events WHERE run_id = %s", ("run-a",)
    ).fetchall()
    by_id = {r[1]: r for r in rows}
    assert by_id["ev-10"][0] == "node-01" and by_id["ev-10"][2] == "learning_event"
    assert by_id["ev-2"][0] == "swarm"  # coordinator-wide record, not the API process
    assert not any(r[0] == "api" for r in rows)
    payload = json.loads(by_id["ev-10"][3])
    assert payload["context"] == CTX and payload["loss"] == 0.5
    assert "obstacles" not in json.loads(by_id["ev-1"][3])  # static map data is not persisted
    assert db.execute("SELECT git_sha FROM runs WHERE run_id = 'run-a'").fetchall() == [
        ("94712c5",)
    ]


def test_learning_curves_per_node_and_swarm(db: SqliteConn) -> None:
    c = queries.learning_curves(db, "run-a")
    n1, n2 = c["nodes"]["node-01"], c["nodes"]["node-02"]
    assert [(p["sim_tick"], p["update_count"], p["loss"], p["policy_version"]) for p in n1] == [
        (2, 10, 0.5, 2)
    ]
    assert [(p["sim_tick"], p["update_count"], p["policy_version"]) for p in n2] == [
        (2, 8, 1),
        (8, 16, 3),
    ]
    swarm = {p["sim_tick"]: p for p in c["swarm"]}
    assert swarm[2]["total_updates"] == 18 and swarm[2]["max_policy_version"] == 2
    assert swarm[8]["total_updates"] == 26 and swarm[8]["min_policy_version"] == 2
    assert swarm[8]["max_policy_version"] == 3
    assert swarm[8]["mean_loss"] == pytest.approx((0.5 + 0.25) / 2)


def test_peer_decisions_with_reasons_and_scores(db: SqliteConn) -> None:
    d = queries.peer_decisions(db, "run-a")
    got = [(x["node"], x["decision"], x["reason"], x["candidate_score"]) for x in d["decisions"]]
    assert got == [
        ("node-01", "accepted", "score_improved", 0.8),
        ("node-02", "rejected", "score_below_tolerance", -0.5),
        ("node-02", "accepted", "score_improved", 1.5),
    ]
    assert d["counts"] == {"accepted:accepted": 2, "rejected:score_below_tolerance": 1}


def test_node_runtime_decision_reason_strings_are_parsed() -> None:
    conn = SqliteConn()
    rec = {
        **{k: RECORDED[9][k] for k in ("schema_version", "emitted_at_utc", "kind")},
        "source_node_id": "node-03", "sim_tick": 50, "update_count": 5, "loss": None,
        "previous_version": 1, "new_version": 1, "transfer": "rejected", "bytes": 4400,
        "wall_seconds": 0.03, "candidate_score": 0.1,
        "reason": f"margin_below_threshold (source=node-04 v=7 sha256={'a' * 64})",
    }  # fmt: skip
    persist(conn, "run-r", [{**rec, "event_id": "d1"}])
    (dec,) = queries.peer_decisions(conn, "run-r")["decisions"]
    assert dec["reason_code"] == "margin_below_threshold"
    assert dec["sender"] == "node-04" and dec["sender_version"] == 7
    assert dec["validation_seconds"] == 0.03


def test_partition_recovery_timeline(db: SqliteConn) -> None:
    t = queries.phase_timeline(db, "run-a")
    assert [(s["phase"], s["start_tick"], s["end_tick"]) for s in t["segments"]] == [
        ("connected", 0, 4),
        ("partition", 4, 6),
        ("recovery", 6, 7),
        ("connected", 7, 9),
    ]


def test_task_curves_keep_train_and_eval_apart(db: SqliteConn) -> None:
    c = queries.task_curves(db, "run-a")
    ret = c["episode_return"]
    assert [p["value"] for p in ret["train"]["nodes"]["node-01"]] == [-3, 2]
    assert [p["value"] for p in ret["eval"]["nodes"]["node-01"]] == [1, 3]
    assert [(s["sim_tick"], s["mean"]) for s in c["coverage"]["train"]["swarm"]] == [(7, 0.4)]
    assert [(s["sim_tick"], s["mean"]) for s in c["coverage"]["eval"]["swarm"]] == [(9, 0.4)]


def test_two_run_comparison_reports_deltas(db: SqliteConn) -> None:
    cmp = queries.compare(db, "run-a", "run-b")
    assert cmp["a"]["episode_return_eval_final"] == 3 and cmp["b"]["episode_return_eval_final"] == 6
    assert cmp["delta_b_minus_a"]["episode_return_eval_final"] == 3
    assert cmp["delta_b_minus_a"]["coverage_train_final"] == pytest.approx(0.3)
    assert cmp["delta_b_minus_a"]["offers_accepted"] == 0
    assert cmp["a"]["total_updates"] == 26 and cmp["a"]["offers_rejected"] == 1


def test_cli_json_csv_compare_and_unknown_run(
    db: SqliteConn, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert report.main(["run-a"], conn=db) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["run"]["identity"]["seed"] == ["7"] and doc["run"]["git_sha"] == "94712c5"
    assert report.main(["run-a", "--compare", "run-b", "--format", "csv"], conn=db) == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    delta = {r["name"]: r["value"] for r in rows if r["section"] == "compare_delta"}
    assert float(delta["episode_return_eval_final"]) == 3.0
    out = tmp_path / "r.csv"
    assert report.main(["run-a", "--format", "csv", "--out", str(out)], conn=db) == 0
    sections = {r["section"] for r in csv.DictReader(out.open())}
    assert sections >= {"learning", "peer_decision", "phase", "task", "final"}
    assert report.main(["no-such-run"], conn=db) == 2


def _render(sql: str) -> str:
    sql = sql.replace("${run_id:sqlstring}", "'run-a'")
    return re.sub(
        r"\$__timeFilter\((\w+)\)",
        r"\1 >= '2000-01-01T00:00:00Z' AND \1 <= '2100-01-01T00:00:00Z'",
        sql,
    )


def test_grafana_live_panels_read_what_the_persister_writes(db: SqliteConn) -> None:
    """Each panel that the recorded run has data for returns rows labelled by the real node."""
    expect_rows = {
        "Episode return — training", "Episode return — frozen evaluation",
        "Coverage — training", "Coverage — frozen evaluation",
        "Optimizer updates per node", "Training loss per node", "Policy version per node",
        "Peer decisions — accepted / rejected", "Peer decisions — reasons and candidate scores",
        "Peer partition / recovery phase", "Telemetry spool backlog per node",
        "Telemetry spool dropped events per node", "Resident memory per node",
        "Unavailable nodes",
    }  # fmt: skip
    seen: set[str] = set()
    for panel in DASH["panels"]:
        rows = db.execute(_render(panel["targets"][0]["rawSql"])).fetchall()
        if rows:
            seen.add(panel["title"])
        if panel["title"].endswith("per node") or "return" in panel["title"].lower():
            labels = {r[1] for r in rows}
            assert "api" not in labels, panel["title"]
    assert expect_rows <= seen, sorted(expect_rows - seen)
    cov = db.execute(
        _render(next(p for p in DASH["panels"] if p["title"] == "Coverage — training")
                ["targets"][0]["rawSql"])
    ).fetchall()  # fmt: skip
    assert {r[1] for r in cov} == {"swarm"}
    loss = db.execute(
        _render(next(p for p in DASH["panels"] if p["title"] == "Training loss per node")
                ["targets"][0]["rawSql"])
    ).fetchall()  # fmt: skip
    assert all(r[2] is not None for r in loss)

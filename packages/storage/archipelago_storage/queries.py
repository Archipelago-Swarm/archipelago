"""Demo and analysis queries over the persisted canonical records (read-only).

All functions take a psycopg-style connection (`conn.execute(sql, params).fetchall()`) and only
SELECT from `events` / `runs`, so they run under the archipelago_reader role. Aggregation is done
in Python on purpose: the same code answers against TigerData and against the SQLite stand-in the
tests use, and the SQL views in migrations/0003_demo_views.sql expose the same shapes to Grafana.

Row shape: events.node_id is the record's source_node_id ("swarm" for coordinator-wide records),
events.payload is the canonical record plus payload.context (commit, config_hash, seed, host,
boot_id, episode).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Protocol

PHASES = ("train", "eval")  # frozen evaluation is always reported apart from training
RETURN_METRICS = ("episode_return", "coverage")
_SOURCE = re.compile(r"source=(\S+)\s+v=(\d+)")
_MARGIN = re.compile(r"margin=(-?[0-9.]+(?:e-?\d+)?)")

Json = dict[str, Any]
# A fault_phase sample marks the start of a phase; "other"/"none" mean the links are back to normal.
_FAULT_NAMES = {"other": "connected", "none": "connected"}


class Cursor(Protocol):
    def fetchall(self) -> list[Any]: ...


class Conn(Protocol):
    def execute(self, sql: str, params: tuple[Any, ...] = ..., /) -> Cursor: ...


class Row:
    __slots__ = ("ts", "node", "kind", "p")

    def __init__(self, ts: Any, node: str, kind: str, payload: Any) -> None:
        self.ts, self.node, self.kind = str(ts), node, kind
        doc = json.loads(payload) if isinstance(payload, str | bytes) else payload
        self.p: Json = doc if isinstance(doc, dict) else {}

    @property
    def tick(self) -> int:
        v = self.p.get("sim_tick")
        return v if isinstance(v, int) else 0

    @property
    def episode(self) -> int | None:
        ctx = self.p.get("context")
        e = ctx.get("episode") if isinstance(ctx, dict) else None
        return e if isinstance(e, int) else None


def fetch(conn: Conn, run_id: str, kinds: tuple[str, ...]) -> list[Row]:
    marks = ", ".join(["%s"] * len(kinds))
    cur = conn.execute(
        f"SELECT ts, node_id, kind, payload FROM events WHERE run_id = %s AND kind IN ({marks}) "
        "ORDER BY ts, event_id",
        (run_id, *kinds),
    )
    rows = [Row(*r) for r in cur.fetchall()]
    rows.sort(key=lambda r: (r.tick, r.ts))  # sim_tick is the global index (A7); ts breaks ties
    return rows


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def run_info(conn: Conn, run_id: str) -> Json:
    """The run row plus the identity (commit, config hash, seed, hosts) its events carry."""
    r = conn.execute(
        "SELECT run_id, started_at, scenario, git_sha FROM runs WHERE run_id = %s", (run_id,)
    ).fetchall()
    info: Json = {"run_id": run_id, "known": bool(r)}
    if r:
        info.update(started_at=str(r[0][1]), scenario=r[0][2], git_sha=r[0][3])
    ctx: dict[str, set[Any]] = defaultdict(set)
    counts: dict[str, int] = {}
    for kind, node, payload in conn.execute(
        "SELECT kind, node_id, payload FROM events WHERE run_id = %s", (run_id,)
    ).fetchall():
        counts[kind] = counts.get(kind, 0) + 1
        c = Row("", node, kind, payload).p.get("context")
        for k, v in (c if isinstance(c, dict) else {}).items():
            if k in ("commit", "config_hash", "seed", "host", "boot_id"):
                ctx[k].add(v)
    info["identity"] = {k: sorted(map(str, v)) for k, v in sorted(ctx.items())}
    info["event_counts"] = dict(sorted(counts.items()))
    return info


def learning_curves(conn: Conn, run_id: str) -> Json:
    """Per-node and swarm learning curves: loss, optimizer update count, policy version."""
    nodes: dict[str, list[Json]] = defaultdict(list)
    for r in fetch(conn, run_id, ("learning_event",)):
        nodes[r.node].append(
            {
                "sim_tick": r.tick,
                "ts": r.ts,
                "episode": r.episode,
                "update_count": r.p.get("update_count"),
                "loss": _num(r.p.get("loss")),
                "policy_version": r.p.get("new_version"),
                "transfer": r.p.get("transfer"),
            }
        )
    # swarm curve: at each tick, the latest value every node has reported so far
    latest: dict[str, Json] = {}
    swarm: list[Json] = []
    flat = sorted(
        ((p["sim_tick"], n, p) for n, pts in nodes.items() for p in pts), key=lambda t: t[:2]
    )
    for i, (tick, node, p) in enumerate(flat):
        latest[node] = {
            "update_count": p["update_count"] or 0,
            "policy_version": p["policy_version"] or 0,
            "loss": p["loss"] if p["loss"] is not None else latest.get(node, {}).get("loss"),
        }
        if i + 1 < len(flat) and flat[i + 1][0] == tick:
            continue
        losses = [v["loss"] for v in latest.values() if v["loss"] is not None]
        versions = [v["policy_version"] for v in latest.values()]
        swarm.append(
            {
                "sim_tick": tick,
                "nodes_reporting": len(latest),
                "total_updates": sum(v["update_count"] for v in latest.values()),
                "mean_loss": sum(losses) / len(losses) if losses else None,
                "min_policy_version": min(versions),
                "max_policy_version": max(versions),
            }
        )
    return {"nodes": dict(sorted(nodes.items())), "swarm": swarm}


def peer_decisions(conn: Conn, run_id: str) -> Json:
    """Accept/reject decisions with their reasons and scores, plus counts per reason."""
    out: list[Json] = []
    for r in fetch(conn, run_id, ("learning_event",)):
        if r.p.get("transfer") not in ("accepted", "rejected"):
            continue
        reason = str(r.p.get("reason") or "")
        src = _SOURCE.search(reason)
        margin = _MARGIN.search(reason)
        accepted = r.p["transfer"] == "accepted"
        code = "accepted" if accepted else reason.split(" (source=")[0].strip() or "unspecified"
        out.append(
            {
                "sim_tick": r.tick,
                "ts": r.ts,
                "episode": r.episode,
                "node": r.node,
                "decision": r.p["transfer"],
                "reason_code": code,
                "reason": reason,
                "sender": src.group(1) if src else None,
                "sender_version": int(src.group(2)) if src else None,
                "candidate_score": _num(r.p.get("candidate_score")),
                "margin": float(margin.group(1)) if margin else None,
                "previous_version": r.p.get("previous_version"),
                "new_version": r.p.get("new_version"),
                "bytes": r.p.get("bytes"),
                "validation_seconds": _num(r.p.get("wall_seconds")),
            }
        )
    counts: dict[str, int] = defaultdict(int)
    for d in out:
        counts[f"{d['decision']}:{d['reason_code']}"] += 1
    return {"decisions": out, "counts": dict(sorted(counts.items()))}


def phase_timeline(conn: Conn, run_id: str) -> Json:
    """Connected / partition / recovery segments from the coordinator's fault_phase samples."""
    marks = [
        r for r in fetch(conn, run_id, ("metric_sample",)) if r.p.get("metric") == "fault_phase"
    ]
    last = max(
        (r.tick for r in fetch(conn, run_id, ("metric_sample", "learning_event"))), default=0
    )
    segments: list[Json] = []
    start, phase = 0, "connected"
    for m in marks:
        if m.tick > start:  # zero-length segments carry no information
            segments.append({"phase": phase, "start_tick": start, "end_tick": m.tick})
        start, phase = m.tick, _FAULT_NAMES.get(str(m.p.get("phase")), str(m.p.get("phase")))
    segments.append({"phase": phase, "start_tick": start, "end_tick": max(last, start)})
    return {
        "transitions": [
            {
                "sim_tick": m.tick,
                "ts": m.ts,
                "phase": m.p.get("phase"),
                "links_cut": _num(m.p.get("value")),
            }
            for m in marks
        ],
        "segments": segments,
    }


def task_curves(conn: Conn, run_id: str) -> Json:
    """Coverage and episode return per node and swarm-wide, train and frozen-eval kept apart."""
    series: dict[str, dict[str, dict[str, list[Json]]]] = {
        m: {p: defaultdict(list) for p in PHASES} for m in RETURN_METRICS
    }
    for r in fetch(conn, run_id, ("metric_sample",)):
        m, ph, v = r.p.get("metric"), r.p.get("phase"), _num(r.p.get("value"))
        if m in series and ph in PHASES and v is not None:
            series[str(m)][str(ph)][r.node].append(
                {"sim_tick": r.tick, "ts": r.ts, "episode": r.episode, "value": v}
            )
    out: Json = {}
    for m, by_phase in series.items():
        out[m] = {}
        for ph, by_node in by_phase.items():
            per_tick: dict[int, list[float]] = defaultdict(list)
            for pts in by_node.values():
                for p in pts:
                    per_tick[p["sim_tick"]].append(p["value"])
            out[m][ph] = {
                "nodes": {n: pts for n, pts in sorted(by_node.items())},
                "swarm": [
                    {"sim_tick": t, "mean": sum(v) / len(v), "n": len(v)}
                    for t, v in sorted(per_tick.items())
                ],
            }
    return out


def final_metrics(conn: Conn, run_id: str) -> Json:
    """End-of-run numbers used for the two-run comparison."""
    tasks = task_curves(conn, run_id)
    learn = learning_curves(conn, run_id)
    dec = peer_decisions(conn, run_id)["decisions"]
    out: Json = {}
    for m, by_phase in tasks.items():
        for ph, d in by_phase.items():
            swarm = d["swarm"]
            out[f"{m}_{ph}_final"] = swarm[-1]["mean"] if swarm else None
            out[f"{m}_{ph}_best"] = max((s["mean"] for s in swarm), default=None)
    last = {n: pts[-1] for n, pts in learn["nodes"].items()}
    out["total_updates"] = sum(p["update_count"] or 0 for p in last.values())
    out["final_policy_version_max"] = max(
        (p["policy_version"] or 0 for p in last.values()), default=None
    )
    out["final_mean_loss"] = learn["swarm"][-1]["mean_loss"] if learn["swarm"] else None
    out["offers_accepted"] = sum(d["decision"] == "accepted" for d in dec)
    out["offers_rejected"] = sum(d["decision"] == "rejected" for d in dec)
    return out


def compare(conn: Conn, run_a: str, run_b: str) -> Json:
    """Final metrics of both runs and delta = b - a (None when either side has no data)."""
    a, b = final_metrics(conn, run_a), final_metrics(conn, run_b)
    delta = {
        k: (b[k] - a[k]) if a.get(k) is not None and b.get(k) is not None else None
        for k in sorted(a)
    }
    return {"a": {"run_id": run_a, **a}, "b": {"run_id": run_b, **b}, "delta_b_minus_a": delta}


def build_report(conn: Conn, run_id: str) -> Json:
    return {
        "run": run_info(conn, run_id),
        "learning": learning_curves(conn, run_id),
        "peer_decisions": peer_decisions(conn, run_id),
        "phase_timeline": phase_timeline(conn, run_id),
        "task_curves": task_curves(conn, run_id),
        "final_metrics": final_metrics(conn, run_id),
    }

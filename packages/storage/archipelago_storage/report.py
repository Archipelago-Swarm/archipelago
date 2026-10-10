"""CLI: python -m archipelago_storage.report <run_id> [--compare <run_id>] [--format json|csv].

Reads TIGERDATA_URL (use the archipelago_reader role) and prints a JSON document, or a tidy CSV
(section, run_id, node_id, phase, sim_tick, name, value, detail), to stdout or --out.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import queries

Json = dict[str, Any]
COLUMNS = ["section", "run_id", "node_id", "phase", "sim_tick", "name", "value", "detail"]


def _row(section: str, run_id: str, **kw: Any) -> Json:
    return {c: kw.get(c) for c in COLUMNS} | {"section": section, "run_id": run_id}


def flatten(report: Json) -> list[Json]:
    """One tidy row per data point so a spreadsheet or pandas can pivot any section."""
    rid = report["run"]["run_id"]
    rows: list[Json] = []
    for node, pts in report["learning"]["nodes"].items():
        for p in pts:
            for name in ("loss", "update_count", "policy_version"):
                if p[name] is not None:
                    rows.append(
                        _row("learning", rid, node_id=node, sim_tick=p["sim_tick"], name=name,
                             value=p[name])
                    )  # fmt: skip
    for p in report["learning"]["swarm"]:
        for name in ("total_updates", "mean_loss", "min_policy_version", "max_policy_version"):
            if p[name] is not None:
                rows.append(
                    _row("learning", rid, node_id="swarm", sim_tick=p["sim_tick"], name=name,
                         value=p[name])
                )  # fmt: skip
    for d in report["peer_decisions"]["decisions"]:
        detail = {
            k: d[k] for k in ("reason_code", "sender", "margin", "previous_version", "new_version")
        }
        rows.append(
            _row("peer_decision", rid, node_id=d["node"], sim_tick=d["sim_tick"],
                 name=d["decision"], value=d["candidate_score"], detail=json.dumps(detail))
        )  # fmt: skip
    for s in report["phase_timeline"]["segments"]:
        rows.append(
            _row("phase", rid, phase=s["phase"], sim_tick=s["start_tick"], name="segment_end_tick",
                 value=s["end_tick"])
        )  # fmt: skip
    for metric, by_phase in report["task_curves"].items():
        for phase, d in by_phase.items():
            for node, pts in d["nodes"].items():
                for p in pts:
                    rows.append(
                        _row("task", rid, node_id=node, phase=phase, sim_tick=p["sim_tick"],
                             name=metric, value=p["value"])
                    )  # fmt: skip
            for p in d["swarm"]:
                rows.append(
                    _row("task", rid, node_id="swarm_mean", phase=phase, sim_tick=p["sim_tick"],
                         name=metric, value=p["mean"])
                )  # fmt: skip
    for name, value in report["final_metrics"].items():
        rows.append(_row("final", rid, name=name, value=value))
    return rows


def render(doc: Json, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(doc, indent=2, sort_keys=True, default=str) + "\n"
    rows: list[Json] = []
    if "delta_b_minus_a" in doc:  # comparison document
        for key in ("a", "b"):
            for name, value in doc[key].items():
                if name != "run_id":
                    rows.append(_row("compare_final", doc[key]["run_id"], name=name, value=value))
        for name, value in doc["delta_b_minus_a"].items():
            rows.append(_row("compare_delta", doc["b"]["run_id"], name=name, value=value,
                             detail=doc["a"]["run_id"]))  # fmt: skip
    else:
        rows = flatten(doc)
    buf = io.StringIO()
    w = csv.DictWriter(buf, COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main(argv: Sequence[str] | None = None, conn: Any = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m archipelago_storage.report")
    ap.add_argument("run_id")
    ap.add_argument("--compare", metavar="RUN_ID", help="second run: final metrics and deltas")
    ap.add_argument("--format", choices=("json", "csv"), default="json")
    ap.add_argument("--out", type=Path, help="write here instead of stdout")
    args = ap.parse_args(argv)
    own = conn is None
    try:
        if own:
            from .writer import connect_from_env

            conn = connect_from_env()
            try:
                conn.read_only = True  # the report never writes
            except Exception:  # noqa: S110 - older drivers; the reader role is the real guard
                pass
        report = queries.build_report(conn, args.run_id)
        if not report["run"]["known"] and not report["run"]["event_counts"]:
            print(f"no data for run {args.run_id!r}", file=sys.stderr)
            return 2
        doc: Json = report
        if args.compare:
            doc = queries.compare(conn, args.run_id, args.compare)
            if args.format == "json":
                doc = {"report": report, "comparison": doc}
        text = render(doc, args.format)
    finally:
        if own and conn is not None:
            conn.close()
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

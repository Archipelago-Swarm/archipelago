"""CLI: python -m archipelago_swarm experiment --out DIR | inspect ... (see the handoff doc)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .explain import explain
from .store import Store


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="archipelago_swarm")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("experiment", help="run the deterministic 10-phase experiment")
    e.add_argument("--out", default="runs/swarm-exp")
    e.add_argument("--seed", type=int, default=0)
    i = sub.add_parser("inspect", help="query a finished run directory")
    i.add_argument(
        "what", choices=["decisions", "decision", "updates", "lineage", "events", "metrics"]
    )
    i.add_argument("--run", required=True)
    i.add_argument("--node")
    i.add_argument("--id", help="decision_id or skill_id")
    i.add_argument("--last", type=int, default=20)
    i.add_argument("--type", help="event type filter")
    i.add_argument("--explain", action="store_true", help="human-readable decision summaries")
    a = ap.parse_args(argv)
    if a.cmd == "experiment":
        from .experiment import run_experiment

        r = run_experiment(a.out, a.seed)
        print(json.dumps({"ok": r["ok"], "checks": r["checks"]}, indent=1))
        return 0 if r["ok"] else 1
    if a.what == "metrics":
        print((Path(a.run) / "metrics.json").read_text("utf-8"))
        return 0
    s = Store.load(a.run)
    if a.what == "decisions":
        out = s.get_recent_decisions(a.node, a.last)
    elif a.what == "decision":
        out = [s.get_decision(a.id)]
    elif a.what == "updates":
        out = s.get_policy_updates(a.node)[-a.last :]
    elif a.what == "lineage":
        out = s.get_skill_lineage(a.id)
    else:
        out = s.get_events(a.type, a.node)[-a.last :]
    for d in out:
        show = a.explain and a.what in ("decisions", "decision")
        print(explain(d) + "\n" if show else json.dumps(d, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

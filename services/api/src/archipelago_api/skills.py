"""Per-node skill state folded from a run's canonical events.

Nodes emit metric_samples ``skill.<name>`` (proficiency) and ``skill_version.<name>`` (version; the
unit ``source:<node>`` names where the proficiency came from) and, on a peer adoption, a
learning_event naming the skill the candidate improved. apps/web/src/live.ts folds the same events.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def skills_view(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, dict[str, dict[str, Any]]] = {}
    adoptions: list[dict[str, Any]] = []
    for e in events:
        kind, node = e.get("kind"), e.get("source_node_id")
        if kind == "learning_event" and e.get("transfer") == "accepted" and e.get("skill"):
            adoptions.append(
                {
                    "node": node,
                    "skill": e["skill"],
                    "gain": e.get("skill_gain"),
                    "sequence": e["sequence"],
                }
            )
        elif (
            kind == "metric_sample"
            and node
            and e["metric"].startswith(("skill.", "skill_version."))
        ):
            what, name = e["metric"].split(".", 1)
            s = nodes.setdefault(node, {}).setdefault(
                name, {"proficiency": None, "version": 0, "source": None}
            )
            if what == "skill":
                s["proficiency"] = e["value"]
            else:
                s["version"] = int(e["value"])
                if e["unit"].startswith("source:"):
                    s["source"] = e["unit"][len("source:") :]
    return {"nodes": nodes, "adoptions": adoptions}

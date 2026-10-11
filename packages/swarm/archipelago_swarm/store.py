"""Run store: structured events, per-node decision traces, per-node policy-update records.

In-memory lists mirrored to JSONL under ``root`` when given. This is TELEMETRY: nodes append to it
but never read from it to decide anything. ``Store.load(root)`` re-opens a finished run, so the
same query API (get_decisions, get_policy_updates, get_skill_lineage, ...) works live and offline.

Event vocabulary (EVENT_TYPES) is closed: emit() rejects unknown types so a typo cannot hide.
Per-step decisions and per-update training records are deliberately NOT events (volume); they have
their own streams (decisions/<node>.jsonl, policy_updates/<node>.jsonl).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

EVENT_TYPES = frozenset(
    """NODE_SPAWNED LOCAL_LEARNING_STARTED LOCAL_LEARNING_STOPPED NODE_MISSION_STARTED
    NODE_MISSION_COMPLETED SKILL_EVALUATED SKILL_CANDIDATE_CREATED SKILL_CREATED SKILL_ACTIVATED
    RF_LINK_UP RF_LINK_DEGRADED RF_LINK_DOWN PEER_DISCOVERED PEER_LOST
    SKILL_ADVERTISED SKILL_REQUESTED SKILL_TRANSFER_STARTED SKILL_TRANSFER_COMPLETED
    SKILL_TRANSFER_FAILED SKILL_INSTALLED SKILL_DERIVED""".split()
)


class Store:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root else None
        self.events: list[dict] = []
        self.decisions: dict[str, list[dict]] = defaultdict(list)
        self.updates: dict[str, list[dict]] = defaultdict(list)
        self.skill_meta: dict[str, dict] = {}  # telemetry mirror of skill metadata (not canonical)
        self._by_id: dict[str, dict] = {}
        self._fh: dict[str, object] = {}
        if self.root:
            for d in ("decisions", "policy_updates", "skills"):
                (self.root / d).mkdir(parents=True, exist_ok=True)
            for old in (self.root / "skills").glob("*.skill"):  # a run dir holds one run
                old.unlink()

    # --- writing ---------------------------------------------------------------------------
    def _write(self, rel: str, rec: dict) -> None:
        if not self.root:
            return
        fh = self._fh.get(rel)
        if fh is None:
            fh = self._fh[rel] = open(self.root / rel, "w", encoding="utf-8")  # noqa: SIM115
        fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")

    def emit(self, etype: str, tick: int, node: str | None = None, **fields) -> dict:
        if etype not in EVENT_TYPES:
            raise ValueError(f"unknown event type {etype!r}")
        rec = {"seq": len(self.events), "type": etype, "tick": tick, "node": node, **fields}
        self.events.append(rec)
        self._write("events.jsonl", rec)
        if etype in ("SKILL_CREATED", "SKILL_DERIVED"):
            self.skill_meta[rec["skill"]["skill_id"]] = rec["skill"]
        return rec

    def add_decision(self, rec: dict) -> None:
        self.decisions[rec["node_id"]].append(rec)
        self._by_id[rec["decision_id"]] = rec
        self._write(f"decisions/{rec['node_id']}.jsonl", rec)

    def add_update(self, rec: dict) -> None:
        self.updates[rec["node_id"]].append(rec)
        self._write(f"policy_updates/{rec['node_id']}.jsonl", rec)

    def write_json(self, rel: str, obj) -> None:
        if self.root:
            (self.root / rel).write_text(json.dumps(obj, indent=1, sort_keys=True), "utf-8")

    def close(self) -> None:
        for fh in self._fh.values():
            fh.close()  # type: ignore[attr-defined]
        self._fh.clear()

    # --- queries (the decision-history API) ------------------------------------------------
    def get_decisions(self, node_id: str) -> list[dict]:
        return list(self.decisions.get(node_id, []))

    def get_recent_decisions(self, node_id: str, n: int = 20) -> list[dict]:
        return list(self.decisions.get(node_id, [])[-n:])

    def get_decision(self, decision_id: str) -> dict | None:
        return self._by_id.get(decision_id)

    def get_policy_updates(self, node_id: str) -> list[dict]:
        return list(self.updates.get(node_id, []))

    def get_events(self, etype: str | None = None, node: str | None = None) -> list[dict]:
        return [
            e
            for e in self.events
            if (etype is None or e["type"] == etype) and (node is None or e["node"] == node)
        ]

    def get_skill_lineage(self, skill_id: str) -> list[dict]:
        """Ancestors (root first) ending at skill_id, then every descendant, with holders."""
        chain, cur = [], skill_id
        while cur and cur in self.skill_meta:
            chain.append(self.skill_meta[cur])
            cur = self.skill_meta[cur].get("parent_skill_id")
        chain.reverse()
        kids = sorted(
            (m for m in self.skill_meta.values() if m.get("parent_skill_id") == skill_id),
            key=lambda m: m["skill_id"],
        )
        holders: dict[str, list[str]] = defaultdict(list)
        for e in self.events:
            if e["type"] in ("SKILL_CREATED", "SKILL_DERIVED", "SKILL_INSTALLED"):
                holders[e["skill"]["skill_id"] if "skill" in e else e["skill_id"]].append(e["node"])
        return [{**m, "holders": holders.get(m["skill_id"], [])} for m in [*chain, *kids]]

    # --- loading ---------------------------------------------------------------------------
    @classmethod
    def load(cls, root: str | Path) -> Store:
        s = cls(None)
        root = Path(root)

        def rows(p: Path):
            return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()]

        if (root / "events.jsonl").exists():
            s.events = rows(root / "events.jsonl")
            for e in s.events:
                if e["type"] in ("SKILL_CREATED", "SKILL_DERIVED"):
                    s.skill_meta[e["skill"]["skill_id"]] = e["skill"]
        for p in sorted((root / "decisions").glob("*.jsonl")):
            for r in rows(p):
                s.decisions[r["node_id"]].append(r)
                s._by_id[r["decision_id"]] = r
        for p in sorted((root / "policy_updates").glob("*.jsonl")):
            for r in rows(p):
                s.updates[r["node_id"]].append(r)
        return s

"""Learned visibility estimate: how reliably this node re-detects a known ground marker.

Fed only by what the node itself experienced: each ``sense_log`` entry in its observation
(biome seen at the marker, drone altitude above the marker, distance in cells, detected or not).
Counts are kept per (biome, altitude band, distance band) with a Beta(1, 1) prior; nothing here
reads the simulator's terrain or detection physics.

Peer sharing is a non-model message (like the visit summary): a node sends only its OWN counts,
full state, so a repeated or lost message neither double counts nor needs repair. A receiver keeps
the latest table per sender and pools them with its own when estimating; no coordinator involved.
"""

from __future__ import annotations

import json

KIND = "vis-estimate-v1"
ALT_EDGES = (40.0, 120.0)  # metres above the marker: low / mid / high vantage
MAX_BYTES = 4096


def key(biome: int, rel_alt: float, dist: int) -> str:
    alt = sum(rel_alt >= e for e in ALT_EDGES)
    return f"{biome}|{alt}|{1 if dist <= 1 else 2}"


class VisibilityModel:
    def __init__(self, node: str):
        self.node = node
        self.own: dict[str, list[int]] = {}  # key -> [detected, attempts]
        self.peers: dict[str, dict[str, list[int]]] = {}

    def update(self, sense_log) -> None:
        for biome, rel_alt, dist, detected in sense_log:
            c = self.own.setdefault(key(biome, rel_alt, dist), [0, 0])
            c[0] += bool(detected)
            c[1] += 1

    def _pooled(self, k: str) -> tuple[int, int]:
        s = n = 0
        for table in (self.own, *self.peers.values()):
            c = table.get(k)
            if c:
                s, n = s + c[0], n + c[1]
        return s, n

    def estimate(self, biome: int, rel_alt: float, dist: int) -> float:
        s, n = self._pooled(key(biome, rel_alt, dist))
        return (s + 1) / (n + 2)  # unobserved conditions stay at the 0.5 prior, never "empty"

    def attempts(self) -> int:
        return sum(c[1] for c in self.own.values())

    def to_wire(self) -> bytes:
        return json.dumps({"kind": KIND, "node": self.node, "counts": self.own}, sort_keys=True, separators=(",", ":")).encode()

    def receive(self, payload: bytes, sender: str) -> None:
        """Validate and store a peer's table. Raises ValueError for anything malformed."""
        if len(payload) > MAX_BYTES:
            raise ValueError("vis-estimate too large")
        doc = json.loads(payload)
        if not isinstance(doc, dict) or doc.get("kind") != KIND or set(doc) != {"kind", "node", "counts"}:
            raise ValueError("bad vis-estimate")
        if doc["node"] != sender:
            raise ValueError("claimed node != sender")
        counts = doc["counts"]
        if not isinstance(counts, dict) or len(counts) > 64:
            raise ValueError("bad counts")
        for k, v in counts.items():
            ok = isinstance(v, list) and len(v) == 2 and all(type(x) is int and x >= 0 for x in v) and v[0] <= v[1]
            if not (isinstance(k, str) and len(k.split("|")) == 3 and ok):
                raise ValueError("bad counts entry")
        if sender != self.node:
            self.peers[sender] = counts

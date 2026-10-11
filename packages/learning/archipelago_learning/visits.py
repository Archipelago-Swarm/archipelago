"""Observation encoders ``grid-flat-v2-visits`` / ``grid-flat-v2-visits-shared`` (T37, T38, A6/A18).

Ids carry geometry like the v1 ids: ``grid-flat-v2-visits[-shared]-s{size}-r{radius}``.

Vector layout (float32), n = 2r+1; identical to the NumPy study harness (``experiments/
protocol_harness.py: flat``) for the same node-local state:

    [0, n*n)            crop, row-major, dy outer (-1 unknown, 0 free, 1 wall)
    n*n, n*n+1          floor(x)/size, floor(y)/size
    n*n+2               battery clipped to [0, 1]
    next n*n            this node's own stand-on count of every crop cell, min(count, 4)/4
                        (the spawn cell counts 1; staying counts)
    next 4              frontier north, east, south, west: fraction of the n cells just outside the
                        crop (row y-(r+1), column x+(r+1), row y+(r+1), column x-(r+1); offsets
                        -r..r) that are inside the map and not in this node's own buffer
    next n*n (shared)   1 if a peer reported standing on that crop cell through the non-model
                        information message, else 0

Everything beyond the plain v1 prefix comes from ``NodeMemory``: state the node builds ONLY from its
own observations (the buffer is the union of the crops it received; stand-on counts are the poses
it received) and from the summaries peers sent it. It never reads world state.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

VISIT_CAP = 4
UNKNOWN = -1
FAMILY_LOCAL = "grid-flat-v2-visits"
FAMILY_SHARED = "grid-flat-v2-visits-shared"
FAMILIES = (FAMILY_LOCAL, FAMILY_SHARED)
_ID = re.compile(r"^(grid-flat-v2-visits(?:-shared)?)-s([1-9][0-9]{0,3})-r([0-9]{1,2})$")
MAX_PEER_SOURCES = 64

Cell = tuple[int, int]


def encoder_id(family: str, size: int, radius: int) -> str:
    if family not in FAMILIES:
        raise ValueError(f"unknown v2 family {family!r}")
    return f"{family}-s{size}-r{radius}"


class NodeMemory:
    """Per-episode node-local memory behind the v2 observation (thread safe, tiny).

    ``observe(tick, ...)`` is idempotent per tick: the observation of tick t reaches a node twice
    (as the ``observation`` of act(t) and as the ``next_observation`` of feedback(t-1)) and counts
    once. Ticks that never reached the node (a missed deadline gap) leave no stand-on count.
    """

    def __init__(self, size: int, radius: int):
        self.size, self.radius = size, radius
        self._lock = threading.Lock()
        self.tick = -1
        self.known: set[Cell] = set()
        self.visits: dict[Cell, int] = {}
        self.peer_by_src: dict[str, frozenset[Cell]] = {}

    def reset(self) -> None:
        with self._lock:
            self.tick = -1
            self.known, self.visits, self.peer_by_src = set(), {}, {}

    def observe(self, tick: int, x: int, y: int, crop) -> bool:
        """Fold in the observation of ``tick``. Returns False if that tick was already applied."""
        r = self.radius
        with self._lock:
            if tick <= self.tick:
                return False
            self.tick = tick
            for dy, row in enumerate(crop):
                for dx, v in enumerate(row):
                    if v != UNKNOWN:
                        self.known.add((x + dx - r, y + dy - r))
            self.visits[(x, y)] = self.visits.get((x, y), 0) + 1
            return True

    def merge_peer(self, src: str, cells: Iterable[Cell]) -> None:
        """Replace what ``src`` reported (a summary is the sender's full state)."""
        s = frozenset((int(a), int(b)) for a, b in cells)
        with self._lock:
            if src not in self.peer_by_src and len(self.peer_by_src) >= MAX_PEER_SOURCES:
                return
            old = self.peer_by_src.get(src, frozenset())
            self.peer_by_src[src] = old | s  # a node's stood-on set only grows within an episode

    def own_cells(self) -> frozenset[Cell]:
        with self._lock:
            return frozenset(self.visits)

    def peer_sources(self) -> dict[str, int]:
        """Sender -> number of its stood-on cells this memory holds."""
        with self._lock:
            return {src: len(c) for src, c in sorted(self.peer_by_src.items())}

    def peer_cells(self) -> frozenset[Cell]:
        with self._lock:
            return (
                frozenset().union(*self.peer_by_src.values()) if self.peer_by_src else frozenset()
            )

    def features(self, x: int, y: int) -> tuple[list[int], list[float], list[bool]]:
        """(own counts crop, frontier fractions, peer flags crop), flattened row-major."""
        r, n = self.radius, 2 * self.radius + 1
        span = range(-r, r + 1)
        with self._lock:
            visits = [self.visits.get((x + dx, y + dy), 0) for dy in span for dx in span]
            peer = (
                frozenset().union(*self.peer_by_src.values()) if self.peer_by_src else frozenset()
            )
            peer_flags = [(x + dx, y + dy) in peer for dy in span for dx in span]
            known, size, k = self.known, self.size, r + 1

            def unknown(c: Cell) -> bool:
                return 0 <= c[0] < size and 0 <= c[1] < size and c not in known

            frontier = [
                sum(unknown(c) for c in cells) / n
                for cells in (
                    [(x + i, y - k) for i in span],
                    [(x + k, y + i) for i in span],
                    [(x + i, y + k) for i in span],
                    [(x - k, y + i) for i in span],
                )
            ]
        return visits, frontier, peer_flags

    # --- checkpoint state (JSON-serialisable, validated on load) -----------------------------
    def state(self) -> dict:
        with self._lock:
            return {
                "tick": self.tick,
                "known": sorted([x, y] for x, y in self.known),
                "visits": sorted([x, y, n] for (x, y), n in self.visits.items()),
                "peer": {s: sorted([x, y] for x, y in c) for s, c in self.peer_by_src.items()},
            }

    def load_state(self, d: dict) -> None:
        def cell(c) -> Cell:
            x, y = c[0], c[1]
            if type(x) is not int or type(y) is not int:
                raise ValueError("bad cell")
            if not (0 <= x < self.size and 0 <= y < self.size):
                raise ValueError("cell outside the grid")
            return (x, y)

        try:
            tick = int(d["tick"])
            known = {cell(c) for c in d["known"]}
            visits = {cell(c): int(c[2]) for c in d["visits"]}
            peer = {str(s): frozenset(cell(c) for c in cs) for s, cs in d["peer"].items()}
        except (KeyError, TypeError, IndexError, ValueError) as e:
            raise ValueError(f"bad memory state: {e}") from e
        if any(v < 1 for v in visits.values()) or len(peer) > MAX_PEER_SOURCES:
            raise ValueError("bad memory state: counts")
        with self._lock:
            self.tick, self.known, self.visits, self.peer_by_src = tick, known, visits, peer


@dataclass(frozen=True)
class GridFlatV2:
    size: int
    radius: int
    shared: bool

    stateful = True

    @property
    def family(self) -> str:
        return FAMILY_SHARED if self.shared else FAMILY_LOCAL

    @property
    def id(self) -> str:
        return encoder_id(self.family, self.size, self.radius)

    @property
    def n(self) -> int:
        return 2 * self.radius + 1

    @property
    def obs_dim(self) -> int:
        n2 = self.n * self.n
        return (3 if self.shared else 2) * n2 + 3 + 4

    @property
    def definition(self) -> str:
        n = self.n
        peer = (
            f" | {n * n} peer stood-on flags (0/1, non-model information message)"
            if self.shared
            else ""
        )
        return (
            f"{self.id}: float32[{self.obs_dim}] = "
            f"crop {n}x{n} row-major dy-outer (-1 unknown,0 free,1 wall), floor(x)/{self.size}, "
            f"floor(y)/{self.size}, battery in [0,1] | {n * n} own stand-on counts of the crop "
            f"cells min(count,{VISIT_CAP})/{VISIT_CAP} (spawn cell counts 1, staying counts) | "
            f"4 frontier fractions N,E,S,W: share of the {n} cells just outside the crop that are "
            f"inside the map and absent from the node's own buffer{peer}"
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.definition.encode()).hexdigest()

    def new_memory(self) -> NodeMemory:
        return NodeMemory(self.size, self.radius)

    def check(self, crop, x, y, battery) -> None:
        n = self.n
        if len(crop) != n or any(len(row) != n for row in crop):
            raise ValueError(f"crop must be {n}x{n} for {self.id}")
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(battery)):
            raise ValueError("pose and battery must be finite")

    def _encode(self, crop, x, y, battery, mem: NodeMemory, tick: int) -> np.ndarray:
        self.check(crop, x, y, battery)
        px, py = math.floor(x), math.floor(y)
        mem.observe(tick, px, py, crop)
        visits, frontier, peer = mem.features(px, py)
        flat = [v for row in crop for v in row]
        pose = [px / self.size, py / self.size]
        parts = [
            np.array([*flat, *pose, min(1.0, max(0.0, battery))], np.float32),
            np.minimum(np.asarray(visits, np.float32), VISIT_CAP) / VISIT_CAP,
            np.asarray(frontier, np.float32),
        ]
        if self.shared:
            parts.append(np.asarray(peer, np.float32))
        return np.concatenate(parts)

    def encode_observation(self, obs, mem: NodeMemory, tick: int) -> np.ndarray:
        """Contract Observation of simulation tick ``tick`` (pose.x/pose.y floats)."""
        return self._encode(obs.crop, obs.pose.x, obs.pose.y, obs.battery, mem, tick)

    def encode_raw(self, obs: dict, mem: NodeMemory, tick: int) -> np.ndarray:
        """Raw GridWorld observation dict (crop, pose=(x, y), battery)."""
        x, y = obs["pose"]
        return self._encode(obs["crop"], x, y, obs["battery"], mem, tick)


def parse(enc_id: str) -> GridFlatV2 | None:
    m = _ID.match(enc_id)
    if not m:
        return None
    return GridFlatV2(int(m.group(2)), int(m.group(3)), m.group(1) == FAMILY_SHARED)

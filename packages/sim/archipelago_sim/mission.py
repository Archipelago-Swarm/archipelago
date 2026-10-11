"""Missions: what the fleet is asked to do, how success is judged, and the seeded dynamics that
keep the problem from being a fixed map.

Detection stays in GridWorld._sense/_detect (sensor footprint, terrain-aware). `new_finds` only
attributes each newly FOUND target to the drone that sensed it. `MissionSpec` is the validated
description; the world owns the mutable state and calls `status()` for progress.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .env import GridWorld

MISSION_TYPES = ("search_rescue", "coverage")  # shortcut: no "relocate" yet; add a goal-zone objective
OBJECTIVE_KINDS = ("find_targets", "cover_fraction")
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
MAX_TARGETS = 200


def derive_map_seed(run_seed: int, episode: int) -> int:
    """Deterministic 31-bit map seed for (run_seed, episode_index). Terrain, obstacles, target
    placement and the dynamics schedule all derive from it, so every episode gets its own map and
    the same pair always reproduces the same one."""
    h = hashlib.sha256(f"archipelago-map:{int(run_seed)}:{int(episode)}".encode()).digest()
    return int.from_bytes(h[:4], "big") & 0x7FFFFFFF


@dataclass(frozen=True)
class Objective:
    id: str
    kind: str  # find_targets: target = count to find; cover_fraction: target = coverage in (0, 1]
    target: float


@dataclass(frozen=True)
class Dynamics:
    """All off by default. Ticks are episode ticks; the schedule is seeded by the map seed."""

    targets_move_every: int = 0  # every N ticks each undiscovered target steps to a free neighbour
    targets_appear: int = 0  # extra targets that appear at seeded ticks in the appear window
    appear_window: tuple[float, float] = (0.2, 0.7)  # fraction of the time budget
    obstacles_shift_every: int = 0  # every N ticks one obstacle shifts by one cell


@dataclass(frozen=True)
class MissionSpec:
    id: str = "mission-1"
    type: str = "search_rescue"
    n_targets: int = 5  # targets present at the start (appearing ones are extra)
    objectives: tuple[Objective, ...] = ()  # empty = the type's default objective
    time_budget_ticks: int | None = None  # None = the episode's max_ticks
    energy_budget: float | None = None  # max fraction of the fleet's battery that may be spent
    dynamics: Dynamics = field(default_factory=Dynamics)

    def __post_init__(self) -> None:
        if not _ID.match(self.id):
            raise ValueError(f"mission id {self.id!r} must match {_ID.pattern}")
        if self.type not in MISSION_TYPES:
            raise ValueError(f"unknown mission type {self.type!r}; known: {MISSION_TYPES}")
        d = self.dynamics
        if not 0 <= self.n_targets <= MAX_TARGETS or not 0 <= d.targets_appear <= MAX_TARGETS:
            raise ValueError(f"target counts must be in 0..{MAX_TARGETS}")
        if min(d.targets_move_every, d.obstacles_shift_every) < 0:
            raise ValueError("dynamics periods must be >= 0")
        lo, hi = d.appear_window
        if not 0 <= lo <= hi <= 1:
            raise ValueError("appear_window must satisfy 0 <= start <= end <= 1")
        if self.time_budget_ticks is not None and self.time_budget_ticks < 1:
            raise ValueError("time_budget_ticks must be >= 1")
        if self.energy_budget is not None and not 0 < self.energy_budget <= 1:
            raise ValueError("energy_budget must be in (0, 1]")
        if self.type == "search_rescue" and self.n_targets + d.targets_appear < 1:
            raise ValueError("search_rescue needs at least one target")
        if not self.objectives:
            default = (
                Objective("find_targets", "find_targets", self.n_targets + d.targets_appear)
                if self.type == "search_rescue"
                else Objective("cover_fraction", "cover_fraction", 0.6)
            )
            object.__setattr__(self, "objectives", (default,))
        seen = set()
        for o in self.objectives:
            if o.kind not in OBJECTIVE_KINDS or not _ID.match(o.id) or o.id in seen:
                raise ValueError(f"bad objective {o!r}")
            seen.add(o.id)
            if o.kind == "find_targets" and not 1 <= o.target <= self.n_targets + d.targets_appear:
                raise ValueError("find_targets target must be 1..(n_targets + targets_appear)")
            if o.kind == "cover_fraction" and not 0 < o.target <= 1:
                raise ValueError("cover_fraction target must be in (0, 1]")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> MissionSpec:
        """Validate a plan/config mapping. Raises ValueError on unknown keys or bad values."""
        raw = dict(raw)
        dyn = dict(raw.pop("dynamics", None) or {})
        objs = raw.pop("objectives", None) or ()
        try:
            if "appear_window" in dyn:
                dyn["appear_window"] = tuple(dyn["appear_window"])
            return cls(
                **raw,
                objectives=tuple(Objective(**o) for o in objs),
                dynamics=Dynamics(**dyn),
            )
        except TypeError as e:  # unknown or missing field
            raise ValueError(f"invalid mission: {e}") from e

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def new_finds(world: GridWorld, seen: set) -> list[tuple[tuple[int, int], str]]:
    """(target, discovering node) for targets found since the last call; `seen` is updated.
    Ties between drones sensing the same target on one tick go to the lowest node id."""
    out = []
    for t in sorted(world.found_targets - seen):
        out.append((t, min(a for a, d in world.drones.items() if t in d.found)))
        seen.add(t)
    return out

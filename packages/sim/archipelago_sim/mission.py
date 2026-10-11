"""Search-and-rescue mission feed. Detection stays in GridWorld._sense/_detect (sensor footprint,
terrain-aware); this only attributes each newly FOUND target to the drone that sensed it."""

from __future__ import annotations

from .env import GridWorld


def new_finds(world: GridWorld, seen: set) -> list[tuple[tuple[int, int], str]]:
    """(target, discovering node) for targets found since the last call; `seen` is updated.
    Ties between drones sensing the same target on one tick go to the lowest node id."""
    out = []
    for t in sorted(world.found_targets - seen):
        out.append((t, min(a for a, d in world.drones.items() if t in d.found)))
        seen.add(t)
    return out

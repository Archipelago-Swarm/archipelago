"""Seeded 2D grid coverage/search world. Pure Python, deterministic for a given seed + actions.

Exposes the PettingZoo ParallelEnv surface (reset/step/agents/possible_agents/action_spaces)
without importing pettingzoo, which is not yet a locked dependency.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field

ACTIONS = ("stay", "north", "east", "south", "west")
DELTA = {"stay": (0, 0), "north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}
UNKNOWN, FREE, WALL = -1, 0, 1
R_NEW_CELL, R_TARGET, R_STEP, R_COLLISION, R_INVALID = 1.0, 5.0, -0.01, -0.5, -0.1
MOVE_COST, STAY_COST = 0.004, 0.001


@dataclass
class Drone:
    pos: tuple[int, int]
    battery: float = 1.0
    known: dict[tuple[int, int], int] = field(default_factory=dict)  # private per-node buffer
    found: set[tuple[int, int]] = field(default_factory=set)

    @property
    def alive(self) -> bool:
        return self.battery > 1e-9


class GridWorld:
    def __init__(self, size: int = 16, n_agents: int = 4, n_targets: int = 3,
                 obstacle_density: float = 0.12, sense_radius: int = 2, max_ticks: int = 900,
                 battery_scale: float = 1.0):
        self.size, self.n_targets, self.radius = size, n_targets, sense_radius
        self.density, self.max_ticks, self.battery_scale = obstacle_density, max_ticks, battery_scale
        self.possible_agents = [f"node-{i}" for i in range(n_agents)]
        self.agents: list[str] = []
        self.action_spaces = {a: len(ACTIONS) for a in self.possible_agents}
        self.events: list[dict] = []
        self.tick = 0

    def reset(self, seed: int = 0, starts: dict[str, tuple[int, int]] | None = None):
        rng = random.Random(seed)
        n = self.size
        cells = [(x, y) for x in range(n) for y in range(n)]
        starts = starts or {}
        self.obstacles = {c for c in cells if rng.random() < self.density} - set(starts.values())
        free = [c for c in cells if c not in self.obstacles]
        rng.shuffle(free)
        picks = (c for c in free if c not in starts.values())
        self.drones: dict[str, Drone] = {
            a: Drone(starts.get(a) or next(picks), self.battery_scale) for a in self.possible_agents
        }
        taken = {d.pos for d in self.drones.values()}
        self.targets = [c for c in free if c not in taken][: self.n_targets]
        self.visited = set(taken)
        self.found_targets: set[tuple[int, int]] = set()
        self.tick, self.events = 0, []
        self.agents = list(self.possible_agents)
        for a in self.agents:
            self._sense(a)
        return {a: self.observe(a) for a in self.agents}

    def _cell(self, c):
        in_bounds = 0 <= c[0] < self.size and 0 <= c[1] < self.size
        return FREE if in_bounds and c not in self.obstacles else WALL

    def _sense(self, a: str) -> int:
        d, new = self.drones[a], 0
        for dx in range(-self.radius, self.radius + 1):
            for dy in range(-self.radius, self.radius + 1):
                c = (d.pos[0] + dx, d.pos[1] + dy)
                if not (0 <= c[0] < self.size and 0 <= c[1] < self.size):
                    continue
                d.known[c] = self._cell(c)
                if c in self.targets:
                    d.found.add(c)
                if c not in self.visited:
                    self.visited.add(c)
                    new += c not in self.obstacles
        return new

    def observe(self, a: str) -> dict:
        """Local view only: crop/mask come from this node's own buffer, never the hidden world."""
        d, r = self.drones[a], self.radius
        crop = [[d.known.get((d.pos[0] + dx, d.pos[1] + dy), UNKNOWN) for dx in range(-r, r + 1)]
                for dy in range(-r, r + 1)]
        return {"crop": crop, "known_mask": [[v != UNKNOWN for v in row] for row in crop],
                "pose": d.pos, "battery": min(1.0, max(0.0, d.battery)),
                "visible_markers": sorted(d.found)}

    def step(self, actions: dict[str, str | None]):
        if not self.agents:
            raise RuntimeError("step() on a finished episode; call reset()")
        self.tick += 1
        ev = self.events
        rewards = {a: R_STEP for a in self.agents}
        cmds: dict[str, str] = {}
        for a in self.agents:
            c = actions.get(a)
            if c not in ACTIONS:  # invalid or missing (node timeout) -> stay
                rewards[a] += R_INVALID
                ev.append({"tick": self.tick, "node": a,
                           "event": "missing_action" if c is None else "invalid_action"})
                c = "stay"
            cmds[a] = c
        pos = {a: self.drones[a].pos for a in self.agents}
        want = {a: (pos[a][0] + DELTA[c][0], pos[a][1] + DELTA[c][1]) for a, c in cmds.items()}
        for a in self.agents:
            if self._cell(want[a]) == WALL:
                want[a] = pos[a]
                rewards[a] += R_COLLISION
                ev.append({"tick": self.tick, "node": a, "event": "wall_collision"})
        # Fixpoint: shared destination, swap, or moving into a node that stays -> mover stays.
        while True:
            blocked = set()
            for a in self.agents:
                for b in self.agents:
                    if a < b and want[a] == want[b] or (a != b and want[a] == pos[b]
                                                         and want[b] == pos[a] and want[a] != pos[a]):
                        blocked |= {a, b}
                    if a != b and want[a] != pos[a] and want[a] == want[b] == pos[b]:
                        blocked.add(a)
            blocked = {a for a in blocked if want[a] != pos[a]}
            if not blocked:
                break
            for a in sorted(blocked):
                want[a] = pos[a]
                rewards[a] += R_COLLISION
                ev.append({"tick": self.tick, "node": a, "event": "agent_collision"})
        before = set(self.found_targets)
        for a in self.agents:
            d = self.drones[a]
            d.pos = want[a]
            d.battery -= (STAY_COST if cmds[a] == "stay" else MOVE_COST)
            rewards[a] += R_NEW_CELL * self._sense(a)
            self.found_targets |= d.found
        for _ in self.found_targets - before:
            for a in self.agents:
                rewards[a] += R_TARGET / len(self.agents)
        done = bool(self.targets) and len(self.found_targets) == len(self.targets)
        terms = {a: done or not self.drones[a].alive for a in self.agents}
        for a in self.agents:
            if not self.drones[a].alive:
                ev.append({"tick": self.tick, "node": a, "event": "energy_exhausted"})
        trunc = {a: self.tick >= self.max_ticks and not terms[a] for a in self.agents}
        out = ({a: self.observe(a) for a in self.agents}, rewards, terms, trunc,
               {a: {} for a in self.agents})
        self.agents = [a for a in self.agents if not (terms[a] or trunc[a])]
        return out

    @property
    def coverage(self) -> float:
        free = self.size * self.size - len(self.obstacles)
        return len(self.visited - self.obstacles) / free

    def world_state(self) -> dict:
        """Privileged snapshot (hidden cells included). Never hand to a node."""
        return {"tick": self.tick, "size": self.size, "obstacles": sorted(self.obstacles),
                "targets": self.targets, "found": sorted(self.found_targets),
                "poses": {a: d.pos for a, d in self.drones.items()},
                "battery": {a: round(d.battery, 6) for a, d in self.drones.items()},
                "coverage": self.coverage}

    def trace_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.world_state(), sort_keys=True).encode()).hexdigest()


def explorer_policy(obs: dict, visits: dict, rng: random.Random) -> str:
    """Rule-based fixture: step to the free neighbour this node has visited least (random ties)."""
    r = len(obs["crop"]) // 2
    px, py = obs["pose"]
    visits[(px, py)] = visits.get((px, py), 0) + 1
    opts = [(visits.get((px + dx, py + dy), 0), rng.random(), name)
            for name, (dx, dy) in list(DELTA.items())[1:] if obs["crop"][r + dy][r + dx] == FREE]
    return min(opts)[2] if opts else "stay"

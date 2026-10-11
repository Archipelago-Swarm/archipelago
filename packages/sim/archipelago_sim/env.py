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
REWARD_SPECS = {  # reward_id -> (new_cell, target, step, collision, invalid)
    "rew-v0": (1.0, 5.0, -0.01, -0.5, -0.1),
    # rew-v1 (T37): collisions 4x stronger, new-cell bonus halved, revisit penalty, no spawn credit.
    "rew-v1": (0.5, 5.0, -0.01, -2.0, -0.1),
}
# reward_id -> (revisit_penalty, pay_spawn_targets). rew-v0 is the frozen original (0.0, True).
REWARD_EXTRA = {"rew-v0": (0.0, True), "rew-v1": (-0.25, False)}
VISIT_CAP = 4  # visit counts are clipped to this before normalisation in observation encoders
MOVE_COST, STAY_COST = 0.004, 0.001


@dataclass
class Drone:
    pos: tuple[int, int]
    battery: float = 1.0
    known: dict[tuple[int, int], int] = field(default_factory=dict)  # private per-node buffer
    found: set[tuple[int, int]] = field(default_factory=set)
    visits: dict[tuple[int, int], int] = field(default_factory=dict)  # own ticks spent per cell
    peer_visits: set[tuple[int, int]] = field(
        default_factory=set
    )  # cells peers reported standing on

    @property
    def alive(self) -> bool:
        return self.battery > 1e-9


class GridWorld:
    def __init__(
        self,
        size: int = 16,
        n_agents: int = 4,
        n_targets: int = 3,
        obstacle_density: float = 0.12,
        sense_radius: int = 2,
        max_ticks: int = 900,
        battery_scale: float = 1.0,
        reward_id: str = "rew-v0",
    ):
        if reward_id not in REWARD_SPECS:
            raise ValueError(f"unknown reward_id {reward_id!r}")
        self.r_new_cell, self.r_target, self.r_step, self.r_collision, self.r_invalid = (
            REWARD_SPECS[reward_id]
        )
        self.reward_id = reward_id
        self.r_revisit, self.pay_spawn_targets = REWARD_EXTRA[reward_id]
        self.size, self.n_targets, self.radius = size, n_targets, sense_radius
        self.density, self.max_ticks, self.battery_scale = (
            obstacle_density,
            max_ticks,
            battery_scale,
        )
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
            self.drones[a].visits[self.drones[a].pos] = 1
        self.spawn_found = set().union(*(d.found for d in self.drones.values()))
        self.spawn_visited = len(self.visited - self.obstacles)
        if not self.pay_spawn_targets:  # targets already in sensing range at reset earn nothing
            self.found_targets |= self.spawn_found
        self.counters = dict.fromkeys(
            ("new_cells", "revisits", "wall_collisions", "agent_collisions", "agent_ticks"), 0
        )
        return {a: self.observe(a) for a in self.agents}

    def observation_space(self, agent: str) -> dict:
        r = 2 * self.radius + 1
        return {"crop": (r, r), "pose": 2, "battery": 1}

    def action_space(self, agent: str) -> int:
        return len(ACTIONS)

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
        crop = [
            [d.known.get((d.pos[0] + dx, d.pos[1] + dy), UNKNOWN) for dx in range(-r, r + 1)]
            for dy in range(-r, r + 1)
        ]
        return {
            "crop": crop,
            "known_mask": [[v != UNKNOWN for v in row] for row in crop],
            "pose": d.pos,
            "battery": min(1.0, max(0.0, d.battery)),
            "visible_markers": sorted(d.found),
        }

    def observe_memory(self, a: str) -> dict:
        """Node-local memory features (grid-flat-v2-visits). Built only from this node's own
        buffer (`known`, own `visits`) and the non-model peer summary it received (`peer_visits`).

        visits: crop of own stand-on counts; peer: crop of 0/1 cells peers reported standing on;
        frontier: per direction (north, east, south, west) the fraction of the (2r+1) cells just
        outside the crop that are inside the map and absent from this node's buffer.
        """
        d, r = self.drones[a], self.radius
        px, py = d.pos
        span = range(-r, r + 1)
        visits = [[d.visits.get((px + dx, py + dy), 0) for dx in span] for dy in span]
        peer = [[(px + dx, py + dy) in d.peer_visits for dx in span] for dy in span]

        def unknown(c):
            return 0 <= c[0] < self.size and 0 <= c[1] < self.size and c not in d.known

        k = r + 1
        frontier = [
            sum(unknown(c) for c in cells) / (2 * r + 1)
            for cells in (
                [(px + i, py - k) for i in span],
                [(px + k, py + i) for i in span],
                [(px + i, py + k) for i in span],
                [(px - k, py + i) for i in span],
            )
        ]
        return {"visits": visits, "peer": peer, "frontier": frontier}

    def step(self, actions: dict[str, str | None]):
        if not self.agents:
            raise RuntimeError("step() on a finished episode; call reset()")
        self.tick += 1
        ev = self.events
        rewards = {a: self.r_step for a in self.agents}
        cmds: dict[str, str] = {}
        for a in self.agents:
            c = actions.get(a)
            if c not in ACTIONS:  # invalid or missing (node timeout) -> stay
                rewards[a] += self.r_invalid
                ev.append(
                    {
                        "tick": self.tick,
                        "node": a,
                        "event": "missing_action" if c is None else "invalid_action",
                    }
                )
                c = "stay"
            cmds[a] = c
        pos = {a: self.drones[a].pos for a in self.agents}
        want = {a: (pos[a][0] + DELTA[c][0], pos[a][1] + DELTA[c][1]) for a, c in cmds.items()}
        dead = {d.pos for n, d in self.drones.items() if n not in self.agents}  # wrecks block
        for a in self.agents:
            if self._cell(want[a]) == WALL or want[a] in dead:
                hit = "wall_collision" if self._cell(want[a]) == WALL else "agent_collision"
                want[a] = pos[a]
                rewards[a] += self.r_collision
                self.counters[
                    "wall_collisions" if hit == "wall_collision" else "agent_collisions"
                ] += 1
                ev.append({"tick": self.tick, "node": a, "event": hit})
        # Fixpoint: shared destination, swap, or moving into a node that stays -> mover stays.
        while True:
            blocked = set()
            for a in self.agents:
                for b in self.agents:
                    if (
                        a < b
                        and want[a] == want[b]
                        or (
                            a != b and want[a] == pos[b] and want[b] == pos[a] and want[a] != pos[a]
                        )
                    ):
                        blocked |= {a, b}
                    if a != b and want[a] != pos[a] and want[a] == want[b] == pos[b]:
                        blocked.add(a)
            blocked = {a for a in blocked if want[a] != pos[a]}
            if not blocked:
                break
            for a in sorted(blocked):
                want[a] = pos[a]
                rewards[a] += self.r_collision
                self.counters["agent_collisions"] += 1
                ev.append({"tick": self.tick, "node": a, "event": "agent_collision"})
        before = set(self.found_targets)
        for a in self.agents:
            d = self.drones[a]
            d.pos = want[a]
            d.battery -= STAY_COST if cmds[a] == "stay" else MOVE_COST
            gained = self._sense(a)
            rewards[a] += self.r_new_cell * gained
            self.counters["new_cells"] += gained
            self.counters["agent_ticks"] += 1
            if d.visits.get(d.pos, 0) > 0:
                self.counters["revisits"] += 1
                if self.r_revisit:
                    rewards[a] += self.r_revisit
            d.visits[d.pos] = d.visits.get(d.pos, 0) + 1
            self.found_targets |= d.found
        for _ in self.found_targets - before:
            for a in self.agents:
                rewards[a] += self.r_target / len(self.agents)
        done = bool(self.targets) and len(self.found_targets) == len(self.targets)
        terms = {a: done or not self.drones[a].alive for a in self.agents}
        for a in self.agents:
            if not self.drones[a].alive:
                ev.append({"tick": self.tick, "node": a, "event": "energy_exhausted"})
        trunc = {a: self.tick >= self.max_ticks and not terms[a] for a in self.agents}
        out = (
            {a: self.observe(a) for a in self.agents},
            rewards,
            terms,
            trunc,
            {a: {} for a in self.agents},
        )
        self.agents = [a for a in self.agents if not (terms[a] or trunc[a])]
        return out

    @property
    def targets_after_spawn(self) -> int:
        return len(self.found_targets - self.spawn_found)

    @property
    def coverage_gain(self) -> float:
        free = self.size * self.size - len(self.obstacles)
        return (len(self.visited - self.obstacles) - self.spawn_visited) / free

    @property
    def coverage(self) -> float:
        free = self.size * self.size - len(self.obstacles)
        return len(self.visited - self.obstacles) / free

    def world_state(self) -> dict:
        """Privileged snapshot (hidden cells included). Never hand to a node."""
        return {
            "tick": self.tick,
            "size": self.size,
            "obstacles": sorted(self.obstacles),
            "targets": self.targets,
            "found": sorted(self.found_targets),
            "poses": {a: d.pos for a, d in self.drones.items()},
            "battery": {a: round(d.battery, 6) for a, d in self.drones.items()},
            "coverage": self.coverage,
        }

    def trace_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.world_state(), sort_keys=True).encode()).hexdigest()


def explorer_policy(obs: dict, visits: dict, rng: random.Random) -> str:
    """Rule-based fixture: step to the free neighbour this node has visited least (random ties)."""
    r = len(obs["crop"]) // 2
    px, py = obs["pose"]
    visits[(px, py)] = visits.get((px, py), 0) + 1
    opts = [
        (visits.get((px + dx, py + dy), 0), rng.random(), name)
        for name, (dx, dy) in list(DELTA.items())[1:]
        if obs["crop"][r + dy][r + dx] == FREE
    ]
    return min(opts)[2] if opts else "stay"

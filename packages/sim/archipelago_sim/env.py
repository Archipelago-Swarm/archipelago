"""Seeded 2D grid coverage/search world. Pure Python, deterministic for a given seed + actions.

Exposes the PettingZoo ParallelEnv surface (reset/step/agents/possible_agents/action_spaces)
without importing pettingzoo, which is not yet a locked dependency.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field

from .mission import MissionSpec
from .terrain import Terrain

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
    # Terrain-aware sensing (only populated when the world has terrain): the surface class and
    # elevation this node saw when it first detected a marker, and this tick's attempts.
    marker_info: dict[tuple[int, int], tuple[int, float]] = field(default_factory=dict)
    sense_log: list[tuple[int, float, int, bool]] = field(default_factory=list)

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
        terrain_seed: int | None = None,
        height: int | None = None,
        terrain_style: str = "classic",
        mission: MissionSpec | dict | None = None,
    ):
        if reward_id not in REWARD_SPECS:
            raise ValueError(f"unknown reward_id {reward_id!r}")
        self.r_new_cell, self.r_target, self.r_step, self.r_collision, self.r_invalid = (
            REWARD_SPECS[reward_id]
        )
        self.reward_id = reward_id
        self.terrain_seed = terrain_seed  # None = uniform world (the pre-terrain behaviour)
        self.terrain_style = terrain_style
        self.terrain: Terrain | None = None
        self.eval_p: dict[
            str, list[float]
        ] = {}  # PRIVILEGED, evaluation only: true p of each logged attempt; never in observe()
        self.r_revisit, self.pay_spawn_targets = REWARD_EXTRA[reward_id]
        if isinstance(mission, dict):
            mission = MissionSpec.from_dict(mission)
        self.mission = mission
        if mission is not None:  # the mission owns the target count
            n_targets = mission.n_targets
        self.size, self.n_targets, self.radius = size, n_targets, sense_radius
        # `size` is the width in cells; `height` defaults to a square. Height may not exceed
        # the width, so
        # pose / size stays in [0, 1] for the observation encoders (which know only the width).
        self.height = size if height is None else height
        if not 1 <= self.height <= size:
            raise ValueError(f"height {self.height} must be in 1..size ({size})")
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
        cells = [(x, y) for x in range(n) for y in range(self.height)]
        starts = starts or {}
        self.map_seed, self._keep_clear = seed, set(starts.values())
        self.obstacles = self._gen_obstacles(rng, cells, starts)
        self.terrain = (
            None
            if self.terrain_seed is None
            else Terrain.generate(
                n,
                getattr(self, "cell_m", 625.0),
                self.terrain_seed,
                height=self.height,
                style=self.terrain_style,
            )
        )
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
        self._start_mission(free)
        return {a: self.observe(a) for a in self.agents}

    # ------------------------------------------------------------------ mission + dynamics
    @property
    def time_budget(self) -> int:
        m = self.mission
        return min(self.max_ticks, m.time_budget_ticks or self.max_ticks) if m else self.max_ticks

    def _start_mission(self, free: list[tuple[int, int]]) -> None:
        self.mission_result, self.mission_end_tick, self._obj_done = "active", None, {}
        self._spawns: list[list] = []
        m = self.mission
        if m is None:
            return
        d = m.dynamics
        taken = set(self.targets) | {dr.pos for dr in self.drones.values()}
        spare = [c for c in free if c not in taken]
        lo, hi = d.appear_window
        for i in range(d.targets_appear):  # appearance ticks and fallback cells, from the map seed
            r = random.Random(f"{self.map_seed}:appear:{i}")
            tick = max(1, round(r.uniform(lo, hi) * self.time_budget))
            self._spawns.append([tick, r.sample(spare, min(8, len(spare)))])
        self._spawns.sort(key=lambda s: s[0])
        self._update_mission()

    def _near_free(self, c: tuple[int, int]) -> list[tuple[int, int]]:
        occupied = set(self.targets) | {dr.pos for dr in self.drones.values()}
        found = self.found_targets.union(*(dr.found for dr in self.drones.values()))
        out = [
            (c[0] + dx, c[1] + dy)
            for dx, dy in DELTA.values()
            if (dx or dy) and self._cell((c[0] + dx, c[1] + dy)) == FREE
        ]
        return sorted(n for n in out if n not in occupied and n not in found)

    def _apply_dynamics(self) -> None:
        """Scheduled world changes, applied at the start of a tick before anyone senses. Every
        random draw comes from the map seed and the tick, so replays reproduce them exactly."""
        m, t = self.mission, self.tick
        if m is None:
            return
        d = m.dynamics
        if d.targets_move_every and t % d.targets_move_every == 0:
            r = random.Random(f"{self.map_seed}:move:{t}")
            found = self.found_targets.union(*(dr.found for dr in self.drones.values()))
            for i, c in enumerate(self.targets):
                opts = [] if c in found else self._near_free(c)
                if opts:
                    self.targets[i] = r.choice(opts)
                    self.events.append(
                        {
                            "tick": t,
                            "event": "target_moved",
                            "from": list(c),
                            "to": list(self.targets[i]),
                        }
                    )
        for sp in [s for s in self._spawns if s[0] <= t]:
            occupied = set(self.targets) | {dr.pos for dr in self.drones.values()}
            cell = next((c for c in sp[1] if self._cell(c) == FREE and c not in occupied), None)
            if cell is not None:  # else retry next tick
                self._spawns.remove(sp)
                self.targets.append(cell)
                self.events.append({"tick": t, "event": "target_appeared", "at": list(cell)})
        if d.obstacles_shift_every and t % d.obstacles_shift_every == 0:
            ev = self._shift_obstacles(random.Random(f"{self.map_seed}:shift:{t}"))
            if ev:
                self.events.append({"tick": t, "event": "obstacle_shifted", **ev})

    def _shift_obstacles(self, r: random.Random) -> dict | None:
        """Move one obstacle cell to a free neighbour (never onto a drone, target or start)."""
        blocked = self._keep_clear | set(self.targets) | {dr.pos for dr in self.drones.values()}
        for c in r.sample(sorted(self.obstacles), min(5, len(self.obstacles))):
            opts = [n for n in self._near_free(c) if n not in blocked]
            if opts:
                new = r.choice(opts)
                self.obstacles.remove(c)
                self.obstacles.add(new)
                return {"from": list(c), "to": list(new)}
        return None

    def _update_mission(self) -> None:
        m = self.mission
        if m is None or self.mission_result != "active":
            return
        values = {"find_targets": len(self.found_targets), "cover_fraction": self.coverage}
        for o in m.objectives:
            if o.id not in self._obj_done and values[o.kind] >= o.target:
                self._obj_done[o.id] = self.tick
        if len(self._obj_done) == len(m.objectives):
            self.mission_result, self.mission_end_tick = "succeeded", self.tick
        elif (
            self.tick >= self.time_budget
            or (m.energy_budget is not None and self.energy_spent > m.energy_budget)
            or not any(dr.alive for dr in self.drones.values())
        ):
            self.mission_result, self.mission_end_tick = "failed", self.tick

    @property
    def energy_spent(self) -> float:
        """Fraction of the fleet's battery capacity consumed so far."""
        drones = self.drones.values()
        return sum(1 - dr.battery / self.battery_scale for dr in drones) / max(1, len(drones))

    def mission_status(self) -> dict | None:
        """Mission progress for telemetry (None when the world has no mission)."""
        m = self.mission
        if m is None:
            return None
        values = {"find_targets": len(self.found_targets), "cover_fraction": self.coverage}
        d = m.dynamics
        return {
            "id": m.id,
            "type": m.type,
            "map_seed": self.map_seed,
            "status": self.mission_result,
            "objectives": [
                {
                    "id": o.id,
                    "kind": o.kind,
                    "target": o.target,
                    "progress": round(min(1.0, values[o.kind] / o.target), 4),
                    "done": o.id in self._obj_done,
                }
                for o in m.objectives
            ],
            "time_budget_ticks": self.time_budget,
            "energy_budget": m.energy_budget,
            "energy_spent": round(max(0.0, self.energy_spent), 4),
            "completed_tick": self.mission_end_tick if self.mission_result == "succeeded" else None,
            "dynamics": [
                n
                for n, on in (
                    ("targets_move", d.targets_move_every),
                    ("targets_appear", d.targets_appear),
                    ("obstacles_shift", d.obstacles_shift_every),
                )
                if on
            ],
        }

    def _gen_obstacles(self, rng: random.Random, cells, starts) -> set[tuple[int, int]]:
        return {c for c in cells if rng.random() < self.density} - set(starts.values())

    def observation_space(self, agent: str) -> dict:
        r = 2 * self.radius + 1
        return {"crop": (r, r), "pose": 2, "battery": 1}

    def action_space(self, agent: str) -> int:
        return len(ACTIONS)

    def _cell(self, c):
        in_bounds = 0 <= c[0] < self.size and 0 <= c[1] < self.height
        return FREE if in_bounds and c not in self.obstacles else WALL

    def _sense(self, a: str) -> int:
        d, new, t = self.drones[a], 0, self.terrain
        d.sense_log = []
        self.eval_p[a] = []
        for dx in range(-self.radius, self.radius + 1):
            for dy in range(-self.radius, self.radius + 1):
                c = (d.pos[0] + dx, d.pos[1] + dy)
                if not (0 <= c[0] < self.size and 0 <= c[1] < self.height):
                    continue
                if t is None:
                    d.known[c] = self._cell(c)
                    if c in self.targets:
                        d.found.add(c)
                elif t.los_clear(
                    d.pos, c
                ):  # terrain between drone and cell hides it: stays unknown
                    d.known[c] = self._cell(c)
                else:
                    if c in self.targets:
                        self._detect(a, c)
                    continue
                if t is not None and c in self.targets:
                    self._detect(a, c)
                if c not in self.visited:
                    self.visited.add(c)
                    new += c not in self.obstacles
        return new

    def _detect(self, a: str, c: tuple[int, int]) -> None:
        """Terrain-aware detection of a ground entity: LOS, vegetation concealment and distance.
        A re-observation of an already-detected marker is logged: the node expected it, so a miss
        is information it legitimately has. First detections are never logged (no success bias)."""
        d, t = self.drones[a], self.terrain
        p = t.detect_p(d.pos, c, self.radius)  # type: ignore[union-attr]
        seen = random.Random(f"{self.terrain_seed}:{self.tick}:{a}:{c}").random() < p
        if c in d.found:
            biome, elev = d.marker_info[c]
            dist = max(abs(c[0] - d.pos[0]), abs(c[1] - d.pos[1]))
            self.eval_p[a].append(p)
            d.sense_log.append((biome, round(t.drone_alt(d.pos) - elev, 1), dist, seen))  # type: ignore[union-attr]
        elif seen:
            d.found.add(c)
            d.marker_info[c] = (t.biome[c[0]][c[1]], t.elev[c[0]][c[1]])  # type: ignore[union-attr]

    def observe(self, a: str) -> dict:
        """Local view only: crop/mask come from this node's own buffer, never the hidden world."""
        d, r = self.drones[a], self.radius
        crop = [
            [d.known.get((d.pos[0] + dx, d.pos[1] + dy), UNKNOWN) for dx in range(-r, r + 1)]
            for dy in range(-r, r + 1)
        ]
        obs = {
            "crop": crop,
            "known_mask": [[v != UNKNOWN for v in row] for row in crop],
            "pose": d.pos,
            "battery": min(1.0, max(0.0, d.battery)),
            "visible_markers": sorted(d.found),
        }
        if (
            self.terrain is not None
        ):  # (biome, rel_alt_m, dist_cells, detected) per known marker in range
            obs["sense_log"] = list(d.sense_log)
        return obs

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
            return 0 <= c[0] < self.size and 0 <= c[1] < self.height and c not in d.known

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
        self._apply_dynamics()
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
        self._update_mission()
        if self.mission is not None:
            done = self.mission_result != "active"
        else:
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
        free = self.size * self.height - len(self.obstacles)
        return (len(self.visited - self.obstacles) - self.spawn_visited) / free

    @property
    def coverage(self) -> float:
        free = self.size * self.height - len(self.obstacles)
        return len(self.visited - self.obstacles) / free

    def world_state(self) -> dict:
        """Privileged snapshot (hidden cells included). Never hand to a node."""
        s = {
            "tick": self.tick,
            "size": self.size,
            "height": self.height,
            "obstacles": sorted(self.obstacles),
            "targets": self.targets,
            "found": sorted(self.found_targets),
            "poses": {a: d.pos for a, d in self.drones.items()},
            "battery": {a: round(d.battery, 6) for a, d in self.drones.items()},
            "coverage": self.coverage,
        }
        if self.mission is not None:
            s["mission"] = self.mission_status()
        return s

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

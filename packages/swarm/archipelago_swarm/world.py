"""Terrain navigation task: what a node observes, what its action does, what it is rewarded for.

Physics is stateless here (positions live in each node). Terrain comes from archipelago_sim.terrain.

Observation ``nav-terrain-v1`` (13 float32, built ONLY from the node's own cell, its goal and the
terrain within 3 cells of it; the node never receives a global terrain array):
see OBS_SCHEMA. Action ``nav-act-v1``: Discrete(4) = N, E, S, W; one cell (cell_m metres) per step.
The flight safety controller REJECTS a move that leaves the map, leaves the node's assigned
geofence (its operating area; none during a transit mission) or whose |slope| > MAX_SLOPE; the
node stays put and takes the invalid-move penalty.

Reward ``rew-nav-v1`` per step (sum of RewardComponents):
  progress = +PROGRESS_W * (d_prev - d_new)   d = euclidean cell distance to the goal
  step     = -STEP_COST                        time pressure
  invalid  = -INVALID_PEN                      rejected move (steep face, map edge, geofence)
  slope    = -SLOPE_PEN * max(0, |slope|/MAX_SLOPE - SLOPE_SOFT)   executed but near-limit climb
  goal     = +GOAL_BONUS                       arrived on the goal cell (terminal)
"""

from __future__ import annotations

import hashlib
import math

import numpy as np
from archipelago_sim.terrain import Terrain

ACTIONS = ("N", "E", "S", "W")
DELTA = ((0, -1), (1, 0), (0, 1), (-1, 0))
MAX_SLOPE = 1.0  # rise/run (45 deg climb) the safety controller will fly
GOAL_NORM, DIST_NORM, ELEV_NORM = 8.0, 12.0, 50.0
PROGRESS_W, STEP_COST, INVALID_PEN = 0.5, 0.02, 0.3
SLOPE_PEN, SLOPE_SOFT, GOAL_BONUS = 0.3, 0.6, 5.0
REWARD_ID, ACTION_SCHEMA, OBS_SCHEMA_ID = "rew-nav-v1", "nav-act-v1", "nav-terrain-v1"
SRC = "packages/swarm/archipelago_swarm/world.py::observe"

OBS_SCHEMA = [
    ("goal_dx", 1, "[-1,1]", "clip((gx-x)/8)", "east(+)/west(-) offset to the goal", "goal"),
    ("goal_dy", 1, "[-1,1]", "clip((gy-y)/8)", "south(+)/north(-) offset to the goal", "goal"),
    ("goal_dist", 1, "[0,1]", "clip(euclid/12)", "cells to the goal", "goal"),
    (
        "slope_N",
        1,
        "[-2,2]",
        "clip(dz/cell_m/MAX_SLOPE)",
        "rise of the next cell north / MAX_SLOPE (>1 = move rejected, 2 = map edge)",
        "terrain",
    ),
    ("slope_E", 1, "[-2,2]", "same", "same, east", "terrain"),
    ("slope_S", 1, "[-2,2]", "same", "same, south", "terrain"),
    ("slope_W", 1, "[-2,2]", "same", "same, west", "terrain"),
    (
        "ahead_N",
        1,
        "[-2,2]",
        "clip(mean(z[+2],z[+3])-z0)/(2.5*cell_m*MAX_SLOPE))",
        "mean elevation 2-3 cells north relative to here (gradient look-ahead)",
        "terrain",
    ),
    ("ahead_E", 1, "[-2,2]", "same", "same, east", "terrain"),
    ("ahead_S", 1, "[-2,2]", "same", "same, south", "terrain"),
    ("ahead_W", 1, "[-2,2]", "same", "same, west", "terrain"),
    ("roughness", 1, "[0,1]", "clip(std(3x3 elev)/50m)", "local relief", "terrain"),
    (
        "clearance",
        1,
        "[-1,1]",
        "clip((alt - max elev 5x5)/agl)",
        "airframe height above the highest ground within 2 cells",
        "terrain",
    ),
]  # name, shape, range, normalisation, meaning, source section; every row lives in SRC
OBS_NAMES = [r[0] for r in OBS_SCHEMA]
OBS_DIM = len(OBS_SCHEMA)
OBS_DEFINITION = "|".join(f"{r[0]}:{r[3]}" for r in OBS_SCHEMA)
SCHEMA_SHA = hashlib.sha256(f"{OBS_SCHEMA_ID}:{OBS_DEFINITION}".encode()).hexdigest()


class NavWorld:
    def __init__(self, size: int = 24, cell_m: float = 100.0, seed: int = 3, agl_m: float = 80.0):
        self.size, self.cell_m, self.seed = size, cell_m, seed
        self.terrain = Terrain.generate(size, cell_m, seed, relief_m=500.0, agl_m=agl_m)
        self._bfs_cache: dict = {}

    def path_len(self, a, b) -> int | None:
        """Shortest legal path (cells) under the safety rule. TASK-GENERATION ONLY (so that sampled
        goals are feasible); never part of a node's observation."""
        d = self._bfs(tuple(a))
        return d.get(tuple(b))

    def _bfs(self, a):
        if a not in self._bfs_cache:
            dist, q = {a: 0}, [a]
            for c in q:
                for dx, dy in DELTA:
                    n = (c[0] + dx, c[1] + dy)
                    if n not in dist and self.inside(n) and abs(self.slope(c, n)) <= MAX_SLOPE:
                        dist[n] = dist[c] + 1
                        q.append(n)
            self._bfs_cache[a] = dist
        return self._bfs_cache[a]

    def route(self, a, b, spacing: int = 3):
        """Waypoints every `spacing` cells along a shortest legal path a->b (excluding a, ending
        at b). MISSION PLANNING (simulator side): the learned policy only flies leg to leg."""
        da, cur, path = self._bfs(tuple(a)), tuple(b), []
        if cur not in da:
            return []
        while cur != tuple(a):
            path.append(cur)
            cur = next(
                n
                for dx, dy in DELTA
                if da.get(n := (cur[0] + dx, cur[1] + dy)) == da[cur] - 1
                and abs(self.slope(n, cur)) <= MAX_SLOPE
            )
        path.reverse()
        return path[spacing - 1 :: spacing] + ([path[-1]] if len(path) % spacing else [])

    def feasible_goal(self, a, b, detour: int = 2, max_m: int = 7) -> bool:
        """Task generator: goal 3..max_m cells away (Manhattan) with a legal path <= m + detour."""
        m = abs(a[0] - b[0]) + abs(a[1] - b[1])
        p = self.path_len(a, b)
        return 3 <= m <= max_m and p is not None and p <= m + detour

    def inside(self, c) -> bool:
        return 0 <= c[0] < self.size and 0 <= c[1] < self.size

    def elev(self, c) -> float:
        return self.terrain.elev[c[0]][c[1]]

    def slope(self, a, b) -> float:
        return (self.elev(b) - self.elev(a)) / self.cell_m

    def observe(self, pos, goal) -> np.ndarray:
        t, (x, y), z0 = self.terrain, pos, self.elev(pos)
        gx, gy = goal[0] - x, goal[1] - y
        slopes, ahead = [], []
        for dx, dy in DELTA:
            n1 = (x + dx, y + dy)
            slopes.append(self.slope(pos, n1) / MAX_SLOPE if self.inside(n1) else 2.0)
            zs = [
                self.elev((x + k * dx, y + k * dy))
                for k in (2, 3)
                if self.inside((x + k * dx, y + k * dy))
            ]
            ahead.append(
                (sum(zs) / len(zs) - z0) / (2.5 * self.cell_m * MAX_SLOPE)
                if zs and self.inside(n1)
                else 2.0
            )
        z3 = [
            self.elev((x + i, y + j))
            for i in (-1, 0, 1)
            for j in (-1, 0, 1)
            if self.inside((x + i, y + j))
        ]
        z5 = [
            self.elev((x + i, y + j))
            for i in range(-2, 3)
            for j in range(-2, 3)
            if self.inside((x + i, y + j))
        ]
        rough = float(np.std(z3)) / ELEV_NORM
        clear = (t.drone_alt(pos) - max(z5)) / t.agl_m
        v = [
            gx / GOAL_NORM,
            gy / GOAL_NORM,
            0.0,
            *slopes,
            *ahead,
            rough,
            clear,
        ]
        v[2] = math.hypot(gx, gy) / DIST_NORM
        lo = [-1, -1, 0] + [-2] * 8 + [0, -1]
        hi = [1, 1, 1] + [2] * 8 + [1, 1]
        return np.clip(np.array(v, np.float32), lo, hi).astype(np.float32)

    def step(self, pos, goal, action: int, fence=None):
        """Returns (new_pos, reward, components, reached_goal, info). Pure function."""
        dx, dy = DELTA[action]
        nxt = (pos[0] + dx, pos[1] + dy)
        d0 = math.hypot(goal[0] - pos[0], goal[1] - pos[1])
        comp = {"step": -STEP_COST, "progress": 0.0, "invalid": 0.0, "slope": 0.0, "goal": 0.0}
        sl = None
        if not self.inside(nxt):
            reason = "map_edge"
        elif fence is not None and nxt not in fence:
            reason = "geofence"
        elif abs(sl := self.slope(pos, nxt)) > MAX_SLOPE:
            reason = "too_steep"
        else:
            reason = None
        if reason:
            comp["invalid"] = -INVALID_PEN
            nxt = pos
        else:
            comp["progress"] = PROGRESS_W * (d0 - math.hypot(goal[0] - nxt[0], goal[1] - nxt[1]))
            comp["slope"] = -SLOPE_PEN * max(0.0, abs(sl) / MAX_SLOPE - SLOPE_SOFT)
        done = nxt == tuple(goal)
        if done:
            comp["goal"] = GOAL_BONUS
        climb = max(0.0, self.elev(nxt) - self.elev(pos))
        info = {"rejected": reason, "slope": sl, "climb_m": climb}
        return nxt, sum(comp.values()), comp, done, info

"""Continuous-flight world (environment_mode "continuous_flight").

A GridWorld subclass. The hidden grid stays the perception/learning substrate (observations,
rewards, coverage and collisions are unchanged), but every drone is a fixed-wing point mass with
continuous x/y (meters), heading and speed. The policy's five actions are an adapter onto flight
dynamics: north/east/south/west set a *desired heading*, "stay" holds the current course (a fixed
wing cannot hover). Heading turns at a bounded rate and the aircraft integrates at physics_hz
between decisions, so paths are arcs. A drone's grid cell is always floor(position / cell_m), with
at most one edge step per decision, which keeps GridWorld's collision/reward bookkeeping valid.
"""

from __future__ import annotations

import math
import random

from .env import ACTIONS, DELTA, WALL, GridWorld

# y grows downward (south), like the map. east = 0, south = +90 degrees.
DESIRED_HEADING = {"east": 0.0, "south": math.pi / 2, "west": math.pi, "north": -math.pi / 2}
_NAME = {v: k for k, v in DELTA.items() if k != "stay"}


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _inside(poly: list[tuple[float, float]], x: float, y: float) -> bool:
    ins = False
    j = len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            ins = not ins
        j = i
    return ins


def _rect(cx: float, cy: float, w: float, h: float, rot: float) -> list[tuple[float, float]]:
    c, s = math.cos(rot), math.sin(rot)
    return [
        (cx + dx * c - dy * s, cy + dx * s + dy * c)
        for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))
    ]


def _blob(rng: random.Random, cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    n = rng.randint(6, 9)
    return [
        (cx + math.cos(2 * math.pi * i / n) * r * rng.uniform(0.6, 1.0),
         cy + math.sin(2 * math.pi * i / n) * r * rng.uniform(0.6, 1.0))
        for i in range(n)
    ]  # fmt: skip


class FlightWorld(GridWorld):
    def __init__(
        self,
        size: int = 32,
        cell_m: float = 625.0,
        speed_mps: float = 80.0,
        tick_s: float = 7.5,
        physics_hz: float = 10.0,
        turn_rate_dps: float = 10.0,
        n_complexes: int = 9,
        **kw,
    ):
        super().__init__(size=size, **kw)
        self.cell_m, self.speed_mps, self.tick_s = cell_m, speed_mps, tick_s
        self.substeps = max(1, round(tick_s * physics_hz))
        self.max_turn = math.radians(turn_rate_dps)
        self.n_complexes = n_complexes
        self.width_m = self.height_m = size * cell_m
        self.sensor_radius_m = self.radius * cell_m  # the real perception radius (crop half-width)
        self.shapes: dict[str, dict] = {}
        self.fs: dict[str, dict[str, float]] = {}

    def _cell_of(self, x: float, y: float) -> tuple[int, int]:
        return (math.floor(x / self.cell_m), math.floor(y / self.cell_m))

    def _gen_obstacles(self, rng, cells, starts) -> set[tuple[int, int]]:
        """Sparse large-area terrain: rotated blocks, blobs and one two-wall corridor, rasterised
        onto the hidden grid by cell centre. Start cells are kept clear."""
        W, cm = self.width_m, self.cell_m
        polys: list[list[tuple[float, float]]] = []
        centres: list[tuple[float, float]] = []

        def free_spot(r: float):
            for _ in range(30):
                c = (rng.uniform(r, W - r), rng.uniform(r, W - r))
                if all(math.dist(c, o) > 4500 for o in centres):
                    centres.append(c)
                    return c
            return None

        for i in range(self.n_complexes):
            c = free_spot(2200)
            if c is None:
                continue
            if i % 3 == 2:
                polys.append(_blob(rng, *c, rng.uniform(1100, 2000)))
            else:
                w, h, rot = rng.uniform(2200, 5000), rng.uniform(800, 1800), rng.uniform(0, math.pi)
                polys.append(_rect(*c, w, h, rot))
        c = free_spot(3500)  # corridor: two parallel walls with a ~1.9 km gap
        if c:
            rot = rng.uniform(0, math.pi)
            nx, ny = -math.sin(rot), math.cos(rot)
            for sgn in (-1, 1):
                polys.append(_rect(c[0] + nx * sgn * 1500, c[1] + ny * sgn * 1500, 4200, 1000, rot))
        start_xy = [((x + 0.5) * cm, (y + 0.5) * cm) for x, y in starts.values()]
        obstacles: set[tuple[int, int]] = set()
        self.shapes = {}
        for poly in polys:
            cs = {
                (i, j)
                for i in range(self.size)
                for j in range(self.size)
                if _inside(poly, (i + 0.5) * cm, (j + 0.5) * cm)
            }
            if not cs or any(_inside(poly, *p) for p in start_xy):
                continue
            self.shapes[f"s{len(self.shapes) + 1}"] = {"points": poly, "cells": cs}
            obstacles |= cs
        return obstacles - set(starts.values())

    def reset(self, seed: int = 0, starts=None):
        obs = super().reset(seed, starts)
        rng = random.Random(seed * 7919 + 1)
        self.fs = {
            a: {
                "x": (d.pos[0] + 0.5) * self.cell_m,
                "y": (d.pos[1] + 0.5) * self.cell_m,
                "heading": rng.uniform(-math.pi, math.pi),
                "speed": self.speed_mps,
            }
            for a, d in self.drones.items()
        }
        return obs

    def step(self, actions):
        dt = self.tick_s / self.substeps
        turn = self.max_turn * dt
        before: dict[str, tuple[float, float, float]] = {}
        cmds: dict[str, str] = {}
        for a in self.agents:
            f = self.fs[a]
            before[a] = (f["x"], f["y"], f["heading"])
            c0 = self._cell_of(f["x"], f["y"])
            want = actions.get(a)
            desired = DESIRED_HEADING.get(want) if want in ACTIONS else None
            bump = None
            for _ in range(self.substeps):
                if desired is not None:
                    f["heading"] += max(-turn, min(turn, wrap(desired - f["heading"])))
                f["heading"] = wrap(f["heading"])
                nx = f["x"] + math.cos(f["heading"]) * f["speed"] * dt
                ny = f["y"] + math.sin(f["heading"]) * f["speed"] * dt
                nc, cc = self._cell_of(nx, ny), self._cell_of(f["x"], f["y"])
                if (
                    self._cell(nc) == WALL
                ):  # terrain or map edge: hold position, deflect, report a hit
                    bump = _NAME.get((nc[0] - cc[0], nc[1] - cc[1])) or bump
                    f["heading"] = wrap(math.pi - f["heading"] if nc[0] != cc[0] else -f["heading"])
                    continue
                if (
                    abs(nc[0] - c0[0]) + abs(nc[1] - c0[1]) > 1
                ):  # at most one edge step per decision
                    continue
                f["x"], f["y"] = nx, ny
            fc = self._cell_of(f["x"], f["y"])
            cmds[a] = _NAME.get((fc[0] - c0[0], fc[1] - c0[1])) or bump or "stay"
        out = super().step(cmds)
        for (
            a,
            prev,
        ) in before.items():  # the grid refused a drone-drone clash: undo the flown distance
            d = self.drones.get(a)
            f = self.fs[a]
            if d is not None and self._cell_of(f["x"], f["y"]) != d.pos:
                f["x"], f["y"], f["heading"] = prev
        return out

    def poses_m(self) -> dict[str, dict[str, float]]:
        return {a: dict(self.fs[a]) for a in self.drones if a in self.fs}

    def world_state(self) -> dict:
        s = super().world_state()
        s["flight"] = {
            a: [round(f[k], 3) for k in ("x", "y", "heading")] for a, f in sorted(self.fs.items())
        }
        return s

    def revealed_shapes(self, discovered: set[tuple[int, int]]) -> list[dict]:
        return [
            {"id": k, "points": [(round(x, 1), round(y, 1)) for x, y in v["points"]]}
            for k, v in self.shapes.items()
            if v["cells"] & discovered
        ]

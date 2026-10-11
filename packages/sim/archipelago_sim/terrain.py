"""Deterministic procedural terrain for the grid/flight worlds: elevation, biome, vegetation.

Pure Python, seeded, no external data. Elevation is fractal value noise blended with a ridged
component (ridgelines, broad valleys, occasional steep faces). Biomes are spatially coherent
because they are thresholded from smooth moisture noise (quantile split, so every seed has
grass, forest and jungle) with valleys wetter and a treeline above which ground is open.

The hidden terrain is ground truth for the *simulator's* visibility physics only. Nodes never
receive these arrays; they get what their own sensor returned (see GridWorld._sense).
"""

from __future__ import annotations

import math

GRASS, FOREST, JUNGLE = 0, 1, 2
BIOMES = ("grass", "forest", "jungle")
BASE_VEG = (0.10, 0.55, 0.90)
CONCEALMENT = 0.9  # fraction of ground-target detectability removed at vegetation density 1.0
DIST_LOSS = 0.35  # detectability lost at the edge of the sensor footprint
TARGET_H_M = 2.0  # ground-level entity height
CANYON_FRAC = 0.6  # cells above this fraction of the map's peak are high-elevation canyon country
PROBE_CELLS = 4
PROBE_DIRS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
N_TERRAIN = len(PROBE_DIRS) + 2
# Per-zone physics: sensor reach scale, max turn-rate scale, crosswind (m/s, turbulence amplitude).
REGION_MODS = {
    "lowland": {"sensor": 1.0, "turn": 1.0, "wind": 0.0},
    "forest": {"sensor": 0.7, "turn": 1.0, "wind": 2.0},
    "canyon": {"sensor": 0.8, "turn": 0.5, "wind": 12.0},
}


def _lat(seed: int, salt: int, ix: int, iy: int) -> float:
    h = (ix * 374761393 + iy * 668265263 + seed * 2246822519 + salt * 3266489917) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF) / 65535.0


def _vnoise(seed: int, salt: int, x: float, y: float) -> float:
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _lat(seed, salt, ix, iy), _lat(seed, salt, ix + 1, iy)
    c, d = _lat(seed, salt, ix, iy + 1), _lat(seed, salt, ix + 1, iy + 1)
    return (a + (b - a) * fx) + ((c + (d - c) * fx) - (a + (b - a) * fx)) * fy


def _fbm(seed: int, salt: int, x: float, y: float, octaves: int) -> float:
    tot = norm = 0.0
    amp, f = 1.0, 1.0
    for o in range(octaves):
        tot += amp * _vnoise(seed, salt + o, x * f, y * f)
        norm += amp
        amp, f = amp * 0.5, f * 2.0
    return tot / norm


class Terrain:
    def __init__(self, size: int, cell_m: float, elev, biome, veg, agl_m: float = 80.0):
        self.size, self.height, self.cell_m, self.agl_m = (
            size,
            len(elev[0]),
            cell_m,
            agl_m,
        )  # size = width in cells
        self.elev, self.biome, self.veg = elev, biome, veg  # [x][y] arrays
        self._max_elev = max(map(max, elev)) or 1.0

    @classmethod
    def flat(
        cls, size: int, cell_m: float, agl_m: float = 80.0, height: int | None = None
    ) -> Terrain:
        h = height or size
        z = [[0.0] * h for _ in range(size)]
        return cls(
            size,
            cell_m,
            z,
            [[GRASS] * h for _ in range(size)],
            [[0.0] * h for _ in range(size)],
            agl_m,
        )

    @classmethod
    def generate(
        cls,
        size: int,
        cell_m: float,
        seed: int,
        relief_m: float = 500.0,
        agl_m: float = 80.0,
        height: int | None = None,
    ) -> Terrain:
        s = seed & 0xFFFF
        rng = range(height or size)  # y
        rx = range(size)  # x
        base = [[_fbm(s, 1, x / 9.0, y / 9.0, 4) for y in rng] for x in rx]
        ridge = [
            [(1 - abs(2 * _fbm(s, 11, x / 7.0, y / 7.0, 3) - 1)) ** 2 for y in rng] for x in rx
        ]
        raw = [
            [0.65 * base[x][y] + 0.35 * ridge[x][y] * base[x][y] ** 0.5 for y in rng] for x in rx
        ]
        lo, hi = min(map(min, raw)), max(map(max, raw))
        e01 = [[((raw[x][y] - lo) / (hi - lo + 1e-12)) ** 1.3 for y in rng] for x in rx]
        moist = [
            [_fbm(s, 21, x / 8.0, y / 8.0, 3) + 0.25 * (1 - e01[x][y]) for y in rng] for x in rx
        ]
        ranked = sorted(v for row in moist for v in row)
        t1, t2 = (
            ranked[int(0.40 * len(ranked))],
            ranked[int(0.72 * len(ranked))],
        )  # ~40% grass, 32% forest, 28% jungle
        biome = [
            [
                GRASS
                if (moist[x][y] < t1 or e01[x][y] > 0.8)
                else FOREST
                if moist[x][y] < t2
                else JUNGLE
                for y in rng
            ]
            for x in rx
        ]
        veg = [
            [
                min(
                    1.0,
                    max(
                        0.0,
                        BASE_VEG[biome[x][y]] * (1 - 0.6 * max(0.0, (e01[x][y] - 0.6) / 0.4))
                        + 0.2 * (_fbm(s, 31, x / 3.0, y / 3.0, 2) - 0.5),
                    ),
                )
                for y in rng
            ]
            for x in rx
        ]
        return cls(size, cell_m, [[e * relief_m for e in row] for row in e01], biome, veg, agl_m)

    def drone_alt(self, c: tuple[int, int]) -> float:
        return self.elev[c[0]][c[1]] + self.agl_m

    def los_clear(self, a: tuple[int, int], b: tuple[int, int]) -> bool:
        """Line of sight from a drone over cell a (agl above ground) to a ground entity in b."""
        n = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
        if n <= 1:
            return True
        h0, h1 = self.drone_alt(a), self.elev[b[0]][b[1]] + TARGET_H_M
        for k in range(1, 2 * n):
            t = k / (2 * n)
            x, y = round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t)
            if (x, y) in (a, b):
                continue
            if self.elev[x][y] > h0 + (h1 - h0) * t:
                return False
        return True

    def height_at(self, x_m: float, y_m: float) -> float:
        """Bilinear ground elevation (m) at a world position; clamped to the map."""
        gx = min(max(x_m / self.cell_m - 0.5, 0.0), self.size - 1.0)
        gy = min(max(y_m / self.cell_m - 0.5, 0.0), self.height - 1.0)
        i, j = min(int(gx), self.size - 2), min(int(gy), self.height - 2)
        fx, fy = gx - i, gy - j
        e = self.elev
        top = e[i][j] * (1 - fx) + e[i + 1][j] * fx
        bot = e[i][j + 1] * (1 - fx) + e[i + 1][j + 1] * fx
        return top * (1 - fy) + bot * fy

    def slope_at(self, x_m: float, y_m: float) -> float:
        """Terrain gradient magnitude (rise/run) by central difference over one cell."""
        d = self.cell_m
        gx = (self.height_at(x_m + d, y_m) - self.height_at(x_m - d, y_m)) / (2 * d)
        gy = (self.height_at(x_m, y_m + d) - self.height_at(x_m, y_m - d)) / (2 * d)
        return math.hypot(gx, gy)

    def probes(self, c: tuple[int, int]) -> list[float]:
        """Terrain-awareness features a flying node could get from radar/DB: 8 compass ray probes
        (fraction of PROBE_CELLS flown before ground rises to flight altitude; 1.0 = clear), own
        altitude (km, clipped) and local slope (clipped)."""
        h0 = self.drone_alt(c)
        out = []
        for dx, dy in PROBE_DIRS:
            f = 1.0
            for k in range(1, PROBE_CELLS + 1):
                x, y = c[0] + dx * k, c[1] + dy * k
                if not (0 <= x < self.size and 0 <= y < self.height):
                    f = (k - 1) / PROBE_CELLS  # map edge is a wall
                    break
                if self.elev[x][y] >= h0:
                    f = (k - 1) / PROBE_CELLS
                    break
            out.append(f)
        sl = self.slope_at((c[0] + 0.5) * self.cell_m, (c[1] + 0.5) * self.cell_m)
        return [*out, min(h0 / 1000.0, 1.0), min(sl / 0.5, 1.0)]

    def region(self, c: tuple[int, int]) -> str:
        """Zone of a cell: canyon (high ground), forest (low, wooded) or lowland (open)."""
        if self.elev[c[0]][c[1]] >= CANYON_FRAC * self._max_elev:
            return "canyon"
        return "lowland" if self.biome[c[0]][c[1]] == GRASS else "forest"

    def mods(self, c: tuple[int, int]) -> dict[str, float]:
        return REGION_MODS[self.region(c)]

    def rf_clear(self, a: tuple[int, int], b: tuple[int, int]) -> bool:
        """RF line of sight between two airborne nodes (both at agl above their own cell)."""
        n = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
        h0, h1 = self.drone_alt(a), self.drone_alt(b)
        for k in range(1, n):
            t = k / n
            x, y = round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t)
            if self.elev[x][y] > h0 + (h1 - h0) * t:
                return False
        return True

    def detect_p(self, a: tuple[int, int], b: tuple[int, int], radius: int) -> float:
        """True probability that a drone over `a` detects a ground entity in `b` this tick."""
        if not self.los_clear(a, b):
            return 0.0
        d = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
        r = radius * self.mods(a)["sensor"]  # the zone the sensor flies in shrinks its reach
        if d > r:
            return 0.0
        return (1 - CONCEALMENT * self.veg[b[0]][b[1]]) * (1 - DIST_LOSS * d / (r + 1))

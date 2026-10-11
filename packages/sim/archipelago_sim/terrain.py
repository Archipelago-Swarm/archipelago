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
        style: str = "classic",
    ) -> Terrain:
        """style "classic" is the original gentle terrain (experiments depend on it); "alpine" has
        massifs, sharp domain-warped ridge chains and broad valleys that really occlude."""
        s = seed & 0xFFFF
        rng = range(height or size)  # y
        rx = range(size)  # x
        if style == "alpine":
            raw = cls._alpine_raw(s, size, height or size)
            lo, hi = min(map(min, raw)), max(map(max, raw))
            e01 = [[((raw[x][y] - lo) / (hi - lo + 1e-12)) ** 1.6 for y in rng] for x in rx]
            relief_m *= 2.8  # tall enough that ridges rise well above the drones' 80 m AGL
        elif style == "classic":
            base = [[_fbm(s, 1, x / 9.0, y / 9.0, 4) for y in rng] for x in rx]
            ridge = [
                [(1 - abs(2 * _fbm(s, 11, x / 7.0, y / 7.0, 3) - 1)) ** 2 for y in rng] for x in rx
            ]
            raw = [
                [0.65 * base[x][y] + 0.35 * ridge[x][y] * base[x][y] ** 0.5 for y in rng]
                for x in rx
            ]
            lo, hi = min(map(min, raw)), max(map(max, raw))
            e01 = [[((raw[x][y] - lo) / (hi - lo + 1e-12)) ** 1.3 for y in rng] for x in rx]
        else:
            raise ValueError(f"unknown terrain style {style!r}")
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

    @staticmethod
    def _alpine_raw(s: int, size: int, height: int) -> list[list[float]]:
        scale = max(size, height)
        rnd = [(_lat(s, 70, i, 0), _lat(s, 71, i, 0), _lat(s, 72, i, 0)) for i in range(5)]
        peaks = [(a * size, b * height, 0.07 + 0.12 * c) for a, b, c in rnd]  # massifs
        raw = []
        for x in range(size):
            col = []
            for y in range(height):
                wx = x + 10 * (_fbm(s, 41, x / 25.0, y / 25.0, 2) - 0.5)
                wy = y + 10 * (_fbm(s, 42, x / 25.0, y / 25.0, 2) - 0.5)
                broad = _fbm(s, 1, wx / 22.0, wy / 22.0, 4)
                ridged, amp, f, w = 0.0, 1.0, 1 / 13.0, 1.0
                for o in range(5):
                    n = (1 - abs(2 * _vnoise(s, 50 + o, wx * f, wy * f) - 1)) ** 2 * w
                    ridged += n * amp
                    w, amp, f = min(1.0, n * 2), amp * 0.5, f * 2
                mass = sum(
                    math.exp(-((x - px) ** 2 + (y - py) ** 2) / (2 * (sg * scale) ** 2))
                    for px, py, sg in peaks
                )
                col.append(0.3 * broad + 0.5 * ridged / 1.94 * (0.3 + 0.7 * broad) + 0.55 * mass)
            raw.append(col)
        return raw

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

    def detect_p(self, a: tuple[int, int], b: tuple[int, int], radius: int) -> float:
        """True probability that a drone over `a` detects a ground entity in `b` this tick."""
        if not self.los_clear(a, b):
            return 0.0
        d = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
        return (1 - CONCEALMENT * self.veg[b[0]][b[1]]) * (1 - DIST_LOSS * d / (radius + 1))

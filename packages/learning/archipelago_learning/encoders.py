"""Observation encoders (live-runtime.md A6, A18).

Ids carry geometry: ``grid-flat-v1-s{size}-r{radius}`` (stateless, 28 floats for radius 2) and the
T37 ids ``grid-flat-v2-visits[-shared]-s{size}-r{radius}`` (57 / 82 floats, see ``visits.py``; they
need node-local memory).

Vector layout (float32, length (2r+1)^2 + 3): crop flattened row-major, floor(x)/size,
floor(y)/size, battery. The same vector comes out of the contract ``Observation`` entry point and
the raw GridWorld observation dict entry point. Duck-typed on purpose: this package does not
import the contracts package.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

import numpy as np

from . import visits

_ID = re.compile(r"^grid-flat-v1-s([1-9][0-9]{0,3})-r([0-9]{1,2})$")


def encoder_id(size: int, radius: int) -> str:
    return f"grid-flat-v1-s{size}-r{radius}"


def canonical_definition(size: int, radius: int) -> str:
    n = 2 * radius + 1
    return (
        f"{encoder_id(size, radius)}: float32[{n * n + 3}] = "
        f"crop {n}x{n} row-major (-1 unknown,0 free,1 wall), "
        f"floor(x)/{size}, floor(y)/{size}, battery"
    )


@dataclass(frozen=True)
class GridFlatV1:
    size: int
    radius: int

    stateful = False

    @property
    def id(self) -> str:
        return encoder_id(self.size, self.radius)

    @property
    def obs_dim(self) -> int:
        return (2 * self.radius + 1) ** 2 + 3

    @property
    def definition(self) -> str:
        return canonical_definition(self.size, self.radius)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.definition.encode()).hexdigest()

    def _encode(self, crop, x, y, battery) -> np.ndarray:
        n = 2 * self.radius + 1
        if len(crop) != n or any(len(row) != n for row in crop):
            raise ValueError(f"crop must be {n}x{n} for {self.id}")
        flat = [v for row in crop for v in row]
        pose = [math.floor(x) / self.size, math.floor(y) / self.size]
        return np.array([*flat, *pose, battery], np.float32)

    def encode_observation(self, obs) -> np.ndarray:
        """Contract Observation (pose.x/pose.y floats, crop, battery)."""
        return self._encode(obs.crop, obs.pose.x, obs.pose.y, obs.battery)

    def encode_raw(self, obs: dict) -> np.ndarray:
        """Raw GridWorld observation dict: crop, pose=(x, y), battery."""
        x, y = obs["pose"]
        return self._encode(obs["crop"], x, y, obs["battery"])


def parse(enc_id: str) -> GridFlatV1 | visits.GridFlatV2 | None:
    m = _ID.match(enc_id)
    if m:
        return GridFlatV1(int(m.group(1)), int(m.group(2)))
    return visits.parse(enc_id)


def get(enc_id: str) -> GridFlatV1 | visits.GridFlatV2:
    e = parse(enc_id)
    if e is None:
        raise ValueError(f"unknown encoder id {enc_id!r}")
    return e

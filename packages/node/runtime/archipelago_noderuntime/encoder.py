"""Observation encoder grid-flat-v1 (live-runtime.md section 3).

Contract Observation -> float32[(2r+1)^2 + 3]: crop row-major (values as emitted: -1 unknown,
0 free, 1 wall), then floor(pose.x)/size, floor(pose.y)/size, battery. For radius 2 that is 28.
This equals the NumPy baseline's grid-flat-v0 vector after its ``_norm``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from archipelago_contracts.models import Observation
from archipelago_learning.compat import encoder_sha256

ENCODER_ID = "grid-flat-v1"
ENCODER_SHA256 = encoder_sha256(ENCODER_ID)
ACTION_SPACE_VERSION = "act-v0"
ACTIONS = ("stay", "north", "east", "south", "west")


class EncodeError(ValueError):
    pass


def obs_dim(radius: int) -> int:
    return (2 * radius + 1) ** 2 + 3


def encode_fields(
    crop: Sequence[Sequence[int]], x: float, y: float, battery: float, size: int, radius: int
) -> np.ndarray:
    side = 2 * radius + 1
    if len(crop) != side or any(len(row) != side for row in crop):
        raise EncodeError(f"crop must be {side}x{side} for sense radius {radius}")
    n = side * side
    out = np.empty(n + 3, np.float32)
    out[:n] = [v for row in crop for v in row]
    out[n] = math.floor(x) / size
    out[n + 1] = math.floor(y) / size
    out[n + 2] = battery
    return out


def encode_observation(obs: Observation, size: int, radius: int) -> np.ndarray:
    return encode_fields(obs.crop, obs.pose.x, obs.pose.y, obs.battery, size, radius)

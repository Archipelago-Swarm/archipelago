"""Thin adapter over ``archipelago_learning.encoders`` (live-runtime.md A6).

The encoder itself (ids that carry geometry, the canonical definition and its sha256, the
contract-Observation and raw-GridWorld entry points) lives in ``archipelago_learning``. This module
only maps its ``ValueError`` to the runtime's ``EncodeError`` and fixes the action vocabulary.
"""

from __future__ import annotations

import numpy as np
from archipelago_contracts.models import Observation
from archipelago_learning import encoders
from archipelago_learning.encoders import GridFlatV1
from archipelago_learning.visits import GridFlatV2, NodeMemory

Encoder = GridFlatV1 | GridFlatV2

ACTION_SPACE_VERSION = "act-v0"
ACTIONS = ("stay", "north", "east", "south", "west")


class EncodeError(ValueError):
    pass


def for_world(size: int, radius: int) -> GridFlatV1:
    return encoders.get(encoders.encoder_id(size, radius))  # type: ignore[return-value]


def for_id(encoder_id: str, size: int, radius: int) -> Encoder:
    """The encoder named by ``encoder_id``; its geometry must be the world's (A6)."""
    enc = encoders.get(encoder_id)
    if (enc.size, enc.radius) != (size, radius):
        raise EncodeError(f"encoder {encoder_id!r} does not match world s{size}-r{radius}")
    return enc


def encode_observation(
    enc: Encoder, obs: Observation, mem: NodeMemory | None = None, tick: int = 0
) -> np.ndarray:
    """v1: stateless. v2: folds the observation of ``tick`` into ``mem``, appends its features."""
    try:
        if isinstance(enc, GridFlatV2):
            assert mem is not None
            return enc.encode_observation(obs, mem, tick)
        return enc.encode_observation(obs)
    except ValueError as e:
        raise EncodeError(str(e)) from e


def check_observation(enc: Encoder, obs: Observation) -> None:
    """Cheap, state-free validity check (a bad observation is refused before any state moves)."""
    if isinstance(enc, GridFlatV2):
        try:
            enc.check(obs.crop, obs.pose.x, obs.pose.y, obs.battery)
        except ValueError as e:
            raise EncodeError(str(e)) from e


def encode_raw(enc: Encoder, obs: dict, mem: NodeMemory | None = None, tick: int = 0) -> np.ndarray:
    try:
        if isinstance(enc, GridFlatV2):
            assert mem is not None
            return enc.encode_raw(obs, mem, tick)
        return enc.encode_raw(obs)
    except (ValueError, KeyError, TypeError) as e:
        raise EncodeError(str(e)) from e

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

ACTION_SPACE_VERSION = "act-v0"
ACTIONS = ("stay", "north", "east", "south", "west")


class EncodeError(ValueError):
    pass


def for_world(size: int, radius: int) -> GridFlatV1:
    return encoders.get(encoders.encoder_id(size, radius))


def encode_observation(enc: GridFlatV1, obs: Observation) -> np.ndarray:
    try:
        return enc.encode_observation(obs)
    except ValueError as e:
        raise EncodeError(str(e)) from e


def encode_raw(enc: GridFlatV1, obs: dict) -> np.ndarray:
    try:
        return enc.encode_raw(obs)
    except (ValueError, KeyError, TypeError) as e:
        raise EncodeError(str(e)) from e

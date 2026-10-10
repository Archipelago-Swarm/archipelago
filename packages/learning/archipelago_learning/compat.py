"""Shared compatibility facts for both learner backends (param-map-v1, header fields)."""

from __future__ import annotations

import hashlib

import numpy as np

from . import encoders

PARAM_MAP = "param-map-v1"
KEYS = ("w1", "b1", "w2", "b2")
REWARD_ID = "rew-v0"
ACTION_SPACE = "act-v0"

# Human-readable definitions; the SHA-256 of the text is part of every model's header so two
# nodes cannot silently exchange weights trained on differently encoded observations.
ENCODER_DEFS = {
    "grid-flat-v0": (
        "grid-flat-v0: crop row-major flatten (-1 unknown,0 free,1 wall), x/size, y/size, battery"
    ),
}


def encoder_sha256(encoder: str) -> str:
    """Hash of the canonical definition; grid-flat-v1-s{size}-r{radius} ids come from encoders."""
    enc = encoders.parse(encoder)
    text = enc.definition if enc else ENCODER_DEFS.get(encoder, f"unregistered-encoder:{encoder}")
    return hashlib.sha256(text.encode()).hexdigest()


def param_shapes(obs_dim: int, hidden: int, n_actions: int) -> dict[str, tuple[int, ...]]:
    return {
        "w1": (obs_dim, hidden),
        "b1": (hidden,),
        "w2": (hidden, n_actions),
        "b2": (n_actions,),
    }


def validate_params(d, shapes) -> dict[str, np.ndarray]:
    """Return independent float32 copies of a param-map-v1 dict or raise ValueError."""
    if not isinstance(d, dict) or set(d) != set(KEYS):
        raise ValueError(f"params must have exactly keys {KEYS}")
    out = {}
    for k in KEYS:
        a = np.asarray(d[k])
        if a.dtype != np.float32 or a.shape != shapes[k]:
            raise ValueError(f"bad tensor {k}: {a.dtype} {a.shape}, want float32 {shapes[k]}")
        if not np.isfinite(a).all():
            raise ValueError(f"nonfinite tensor {k}")
        out[k] = np.ascontiguousarray(a).copy()
    return out

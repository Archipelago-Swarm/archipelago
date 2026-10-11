"""Node checkpoint generations with the A17 fixed file names (live-runtime.md section 7 and A17).

Files of one generation, written through ``archipelago_learning.checkpoint.write_generation`` (every
file fsynced, hash-listed in MANIFEST.json, CURRENT switched atomically, last 3 generations kept):

    policy.npz  target.npz  optimizer.npz  replay.npz  rng.json  counters.json  MANIFEST.json

``policy.npz`` also carries the rollback copy (``prev_*`` keys). ``counters.json`` holds the
learner identity, its counters and the ``node`` blob (run/episode/tick, pending (obs, action) per
step key, schedule, dedupe cache, spool cursor, sequence ceilings...). ``replay.npz`` is deflated:
it stays within ``replay_max_bytes(capacity, obs_dim)`` for real observations (A17).

The learner's own ``save_generation`` predates A17 and uses other names; the node bypasses it and
drives the learner's public state (``params_numpy``, ``target_numpy``, ``replay``, RNGs) plus its
optimizer export helpers.
"""

from __future__ import annotations

import io
import json

import numpy as np
import torch
from archipelago_learning import checkpoint
from archipelago_learning.checkpoint import (
    FILE_COUNTERS,
    FILE_OPTIMIZER,
    FILE_POLICY,
    FILE_REPLAY,
    FILE_RNG,
    FILE_TARGET,
    CheckpointError,
)
from archipelago_learning.compat import KEYS, validate_params
from archipelago_learning.torch_dqn import check_identity

SCHEMA = "node-ckpt-v1"


def _npz(compressed: bool = False, **arrays) -> bytes:
    b = io.BytesIO()
    (np.savez_compressed if compressed else np.savez)(b, **arrays)
    return b.getvalue()


def _arrays(blob: bytes) -> dict[str, np.ndarray]:
    with np.load(io.BytesIO(blob), allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def _filled(learner) -> dict[str, np.ndarray]:
    """Only the rows ever written (the ring buffer's filled prefix): with a 50000-row replay an
    early checkpoint must not serialise megabytes of zeros while holding the learner lock."""
    rows = min(learner.n, learner.capacity)
    return {k: v[:rows] for k, v in learner.replay.items()}


def save(learner, root, node_state: dict, act_rng_state: dict, io_=None) -> dict:
    """Write one generation; returns its manifest. The caller serialises against the learner."""
    prev = learner.previous or {}
    counters = {
        **learner._identity(),
        "schema": SCHEMA,
        "steps": learner.steps,
        "version": learner.version,
        "n": learner.n,
        "paused": learner.paused,
        "has_previous": learner.previous is not None,
        "torch_version": torch.__version__,
        "node": node_state,
    }
    rng = {
        "learner_numpy": learner.rng.bit_generator.state,
        "learner_torch": learner.torch_gen.get_state().numpy().tobytes().hex(),
        "act": act_rng_state,
    }
    files = {
        FILE_POLICY: _npz(
            **{f"p_{k}": v for k, v in learner.params_numpy().items()},
            **{f"prev_{k}": v for k, v in prev.items()},
        ),
        FILE_TARGET: _npz(**{f"t_{k}": v for k, v in learner.target_numpy().items()}),
        FILE_OPTIMIZER: _npz(**learner._optimizer_arrays()),
        FILE_REPLAY: _npz(compressed=True, **_filled(learner)),
        FILE_RNG: json.dumps(rng, sort_keys=True).encode(),
        FILE_COUNTERS: json.dumps(counters, sort_keys=True, allow_nan=False).encode(),
    }
    return checkpoint.write_generation(root, files, io_)


def load(learner, root) -> dict:
    """Restore the newest verified generation into ``learner``; return its ``node`` blob.

    Everything is parsed and validated before any learner state is replaced. Raises
    ``CheckpointError`` when nothing is loadable or the identity (hyperparameters, encoder) differs.
    """
    manifest, files = checkpoint.read_latest(root)
    try:
        counters = json.loads(files[FILE_COUNTERS])
        if counters.get("schema") != SCHEMA:
            raise ValueError(f"unknown checkpoint schema {counters.get('schema')!r}")
        check_identity(counters, learner._identity())
        pol_all = _arrays(files[FILE_POLICY])
        pol = validate_params({k: pol_all[f"p_{k}"] for k in KEYS}, learner.shapes)
        prev = (
            validate_params({k: pol_all[f"prev_{k}"] for k in KEYS}, learner.shapes)
            if counters["has_previous"]
            else None
        )
        tgt_all = _arrays(files[FILE_TARGET])
        tgt = validate_params({k: tgt_all[f"t_{k}"] for k in KEYS}, learner.shapes)
        opt = _arrays(files[FILE_OPTIMIZER])
        replay = _arrays(files[FILE_REPLAY])
        rows = min(int(counters["n"]), learner.capacity)
        for k, v in learner.replay.items():
            got = replay[k]
            # the filled prefix (new files) or the whole ring (files written before the prefix form)
            if (
                got.dtype != v.dtype
                or got.shape[1:] != v.shape[1:]
                or got.shape[0] not in (rows, v.shape[0])
            ):
                raise ValueError(f"checkpoint replay mismatch for {k}")
        rng = json.loads(files[FILE_RNG])
        probe = np.random.default_rng()
        probe.bit_generator.state = rng["learner_numpy"]  # validates before commit
        probe.bit_generator.state = rng["act"]
        torch_state = torch.from_numpy(
            np.frombuffer(bytes.fromhex(rng["learner_torch"]), np.uint8).copy()
        )
        node = counters["node"]
    except (KeyError, ValueError, TypeError) as e:
        raise CheckpointError(f"checkpoint content invalid: {e}") from e
    learner._import(learner.policy, pol)
    learner._import(learner.target_net, tgt)
    learner._restore_optimizer(opt)
    restored = {k: np.zeros_like(v) for k, v in learner.replay.items()}
    for k, v in restored.items():
        v[: len(replay[k])] = replay[k]
    learner.replay = restored
    learner.rng.bit_generator.state = rng["learner_numpy"]
    learner.torch_gen.set_state(torch_state)
    learner.steps, learner.version, learner.n = (
        counters["steps"], counters["version"], counters["n"],
    )  # fmt: skip
    learner.paused, learner.previous, learner.events = counters["paused"], prev, []
    learner._publish()
    return {"generation": manifest["generation"], "node": node, "act_rng": rng["act"]}

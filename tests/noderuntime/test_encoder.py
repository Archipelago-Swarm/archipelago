"""A6: the node uses archipelago_learning.encoders through a thin adapter (no duplicate logic)."""

from pathlib import Path

import numpy as np
import pytest
from archipelago_contracts.models import Observation
from archipelago_learning import encoders, rollout
from archipelago_learning.compat import encoder_sha256
from archipelago_noderuntime import encoder as adapter
from archipelago_noderuntime.encoder import EncodeError, encode_observation, encode_raw, for_world
from archipelago_sim.pz import GridParallelEnv
from support import make_cfg, obs_json


def _norm(o, size):  # the NumPy baseline's normalisation (archipelago_learning.rollout._norm)
    o = o.copy()
    o[-3:-1] /= size
    return o


@pytest.mark.parametrize("size", [8, 10, 16])
def test_adapter_equals_env_flat_plus_norm_over_a_rollout(size):
    enc = for_world(size, 2)
    env = GridParallelEnv(size=size, n_agents=2, n_targets=0, max_ticks=40)
    obs, _ = env.reset(seed=3)
    rng = np.random.default_rng(0)
    checked = 0
    while env.agents:
        for a in env.agents:
            raw = env.world.observe(a)
            contract = Observation.model_validate(obs_json("run-e", a, checked, raw))
            got = encode_observation(enc, contract)
            want = _norm(obs[a], size)
            assert got.dtype == np.float32 and got.shape == (28,)
            np.testing.assert_array_equal(got, want)
            np.testing.assert_array_equal(encode_raw(enc, raw), got)  # both entry points agree
            if size == 8:  # the shipped baseline helper itself
                np.testing.assert_array_equal(got, rollout._norm(obs[a]))
            checked += 1
        obs, *_ = env.step({a: int(rng.integers(5)) for a in env.agents})
    assert checked > 20


def test_adapter_delegates_and_holds_no_encoder_logic_of_its_own():
    enc = for_world(8, 2)
    assert isinstance(enc, encoders.GridFlatV1) and enc == encoders.get("grid-flat-v1-s8-r2")
    assert not hasattr(adapter, "encode_fields") and not hasattr(adapter, "ENCODER_ID")


def test_ids_carry_geometry_and_the_hash_is_the_learner_compatibility_hash():
    cfg = make_cfg(Path("."), node_ids=("node-01",), world_size=12)
    assert cfg.encoder_id == "grid-flat-v1-s12-r2"
    enc = for_world(12, 2)
    assert enc.id == cfg.encoder_id and enc.obs_dim == cfg.obs_dim == 28
    assert enc.sha256 == encoder_sha256(enc.id)
    assert for_world(8, 2).sha256 != for_world(12, 2).sha256  # geometry is part of the identity
    assert for_world(8, 2).sha256 != encoder_sha256("grid-flat-v0")


def test_wrong_crop_shape_is_an_encode_error():
    enc = for_world(8, 2)
    bad = Observation.model_validate(
        obs_json("run-e", "n", 0, {
            "crop": [[0] * 3 for _ in range(3)], "known_mask": [[True] * 3] * 3,
            "pose": (1, 1), "battery": 1.0, "visible_markers": [],
        })
    )  # fmt: skip
    with pytest.raises(EncodeError):
        encode_observation(enc, bad)
    with pytest.raises(EncodeError):
        encode_raw(enc, {"crop": [[0] * 5 for _ in range(4)], "pose": (0, 0), "battery": 1.0})

import numpy as np
import pytest
from archipelago_contracts.models import Observation
from archipelago_learning import rollout
from archipelago_learning.compat import encoder_sha256
from archipelago_noderuntime.encoder import (
    ENCODER_ID,
    ENCODER_SHA256,
    EncodeError,
    encode_fields,
    encode_observation,
)
from archipelago_sim.pz import GridParallelEnv
from support import obs_json


def _norm(o, size):  # the NumPy baseline's normalisation (archipelago_learning.rollout._norm)
    o = o.copy()
    o[-3:-1] /= size
    return o


@pytest.mark.parametrize("size", [8, 10, 16])
def test_encoder_equals_env_flat_plus_norm_over_a_rollout(size):
    env = GridParallelEnv(size=size, n_agents=2, n_targets=0, max_ticks=40)
    obs, _ = env.reset(seed=3)
    rng = np.random.default_rng(0)
    checked = 0
    while env.agents:
        for a in env.agents:
            raw = env.world.observe(a)
            contract = Observation.model_validate(obs_json("run-e", a, checked, raw))
            got = encode_observation(contract, size, 2)
            want = _norm(obs[a], size)
            assert got.dtype == np.float32 and got.shape == (28,)
            np.testing.assert_array_equal(got, want)
            if size == 8:  # the shipped baseline helper itself
                np.testing.assert_array_equal(got, rollout._norm(obs[a]))
            checked += 1
        obs, *_ = env.step({a: int(rng.integers(5)) for a in env.agents})
    assert checked > 20


def test_encoder_floors_fractional_poses_and_orders_fields():
    crop = [[0] * 5 for _ in range(5)]
    crop[0][0], crop[4][4], crop[2][3] = -1, 1, 1
    v = encode_fields(crop, 3.9, 1.2, 0.25, size=8, radius=2)
    flat = [x for row in crop for x in row]
    assert v[:25].tolist() == flat
    assert v[25:].tolist() == [3 / 8, 1 / 8, 0.25]


def test_encoder_rejects_wrong_crop_shape():
    with pytest.raises(EncodeError):
        encode_fields([[0] * 3 for _ in range(3)], 0, 0, 1.0, size=8, radius=2)
    with pytest.raises(EncodeError):
        encode_fields([[0] * 5 for _ in range(4)], 0, 0, 1.0, size=8, radius=2)


def test_encoder_identity_is_the_learner_compatibility_hash():
    assert ENCODER_ID == "grid-flat-v1"
    assert ENCODER_SHA256 == encoder_sha256("grid-flat-v1")
    assert ENCODER_SHA256 != encoder_sha256("grid-flat-v0")

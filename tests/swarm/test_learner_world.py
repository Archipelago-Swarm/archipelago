import numpy as np
from archipelago_swarm.learner import NodeLearner
from archipelago_swarm.world import OBS_DIM, NavWorld


def _fill(lr, n=48, seed=0):
    r = np.random.default_rng(seed)
    for _ in range(n):
        lr.observe(
            r.normal(size=OBS_DIM).astype("f"),
            int(r.integers(4)),
            0.1,
            r.normal(size=OBS_DIM).astype("f"),
            False,
        )


def test_learner_state_is_independent():
    a, b = NodeLearner("a", 5, 101), NodeLearner("b", 5, 202)
    assert a.policy_hash() == b.policy_hash()  # same init_seed -> equal start
    assert a.rng.integers(10**9) != b.rng.integers(10**9)  # distinct streams
    assert a.act_rng.integers(10**9) != b.act_rng.integers(10**9)
    _fill(a)
    hb, nb = b.policy_hash(), b.n
    rec = a.train_update(batch=32)
    assert rec and a.version == 1
    assert a.policy_hash() != hb
    assert (b.policy_hash(), b.version, b.n, b.steps) == (hb, 0, nb, 0)
    assert not b.opt.state_dict()["state"]  # b's optimizer never stepped
    assert a.replay["o"] is not b.replay["o"]


def test_observation_shape_range_and_variation():
    w = NavWorld(seed=12)
    lo = np.array([-1, -1, 0] + [-2] * 8 + [0, -1], "f")
    hi = np.array([1, 1, 1] + [2] * 8 + [1, 1], "f")
    seen = []
    for pos in [(0, 0), (5, 5), (12, 7), (23, 23), (10, 20)]:
        o = w.observe(pos, (11, 11))
        assert o.shape == (OBS_DIM,)
        assert (o >= lo).all() and (o <= hi).all()
        seen.append(o)
    assert not np.allclose(seen[1], seen[2])
    # terrain part (indices 3:) differs between positions even with the same goal offset
    assert not np.allclose(w.observe((5, 5), (8, 8))[3:], w.observe((12, 7), (15, 10))[3:])
    # corner: off-map neighbours report the documented 2.0 sentinel
    o = w.observe((0, 0), (3, 3))
    assert o[3] == 2.0 and o[6] == 2.0


def test_observation_dtype_is_float32():
    assert NavWorld(seed=12).observe((5, 5), (8, 8)).dtype == np.float32

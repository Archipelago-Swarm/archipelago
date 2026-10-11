"""T38: TorchLearner under the T37 recipe (double DQN, rew-v1 / v2 observation ids, versioned ids).

* numeric parity of the Torch double-DQN update with the study's NumPy reference (``t37.VLearner``)
  on a fixed replay and identical initial weights;
* the old (single) DQN update is unchanged;
* peer candidates and checkpoints with another encoder / reward id are rejected with a named reason;
* a short deterministic training run on the real v2 observation + rew-v1 beats an untrained network
  and the idle policy on the validation seeds (thresholds from the T37 numbers, not wall clock).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

import protocol_harness as H  # noqa: E402
import t37  # noqa: E402
from archipelago_learning import PeerError, TorchLearner, decode, encode, offer  # noqa: E402
from archipelago_learning.checkpoint import CheckpointError  # noqa: E402
from archipelago_learning.dqn import Learner  # noqa: E402

SHARED = "grid-flat-v2-visits-shared-s16-r2"
LOCAL = "grid-flat-v2-visits-s16-r2"
V1 = "grid-flat-v1-s16-r2"


def fixed_replay(n=300, obs_dim=82, seed=0):
    r = np.random.default_rng(seed)
    return {
        "o": r.random((n, obs_dim), dtype=np.float32),
        "a": r.integers(0, 5, n).astype(np.int64),
        "r": (r.standard_normal(n) * 2).astype(np.float32),
        "o2": r.random((n, obs_dim), dtype=np.float32),
        "d": (r.random(n) < 0.05).astype(np.float32),
    }


def twin(double: bool, n=300):
    """A Torch learner and the NumPy reference with identical weights, replay and sampling RNG."""
    tl = TorchLearner(
        "node-01", 82, 5, hidden=32, seed=1, lr=1e-3, gamma=0.95, capacity=n, double=double,
        threads=1, encoder=SHARED, reward_id="rew-v1",
    )  # fmt: skip
    nl = t37.VLearner("node-01", 82, 5, hidden=32, seed=2, lr=1e-3, gamma=0.95, capacity=n,
                      double=double)  # fmt: skip
    nl.params = {k: v.copy() for k, v in tl.params_numpy().items()}
    nl.sync_target()
    data = fixed_replay(n)
    for k, v in data.items():
        tl.replay[k][:] = v
        nl.replay[k][:] = v
    tl.n = nl.n = n
    tl.rng, nl.rng = np.random.default_rng(5), np.random.default_rng(5)
    return tl, nl


@pytest.mark.parametrize("double", [True, False])
def test_torch_update_matches_the_numpy_reference_step_by_step(double):
    tl, nl = twin(double)
    probe = np.random.default_rng(9).random((64, 82), dtype=np.float32)
    for i in range(130):  # crosses two target syncs (every 50 steps)
        lt, ln = tl.train_step(32, 50), nl.train_step(32, 50)
        assert lt == pytest.approx(ln, rel=2e-3, abs=2e-4), (i, lt, ln)
    for k, v in tl.params_numpy().items():
        np.testing.assert_allclose(v, nl.params[k], rtol=2e-3, atol=2e-4, err_msg=k)
    q_t = np.stack([tl.snapshot().q(x) for x in probe])
    q_n = np.stack([nl.forward(nl.params, x[None])[1][0] for x in probe])
    np.testing.assert_allclose(q_t, q_n, rtol=2e-3, atol=5e-4)
    assert tl.steps == nl.steps == 130


def test_double_and_single_targets_really_differ():
    a, _ = twin(True)
    b, _ = twin(False)
    for _ in range(60):
        a.train_step(32, 50)
        b.train_step(32, 50)
    assert any(not np.allclose(a.params_numpy()[k], b.params_numpy()[k]) for k in ("w1", "w2"))


def test_default_learner_is_the_legacy_single_dqn_with_legacy_ids():
    tl = TorchLearner("n", 28, 5)
    assert (tl.double, tl.reward_id, tl.schedule_id) == (False, "rew-v0", "sched-v0")
    nl = Learner("n", 28, 5)
    assert nl.reward_id == tl.reward_id and tl.action_space == "act-v0"


# --- identity: encoder / reward id mismatches are named refusals ----------------------------------
def learner(**kw):
    kw = {"encoder": SHARED, "reward_id": "rew-v1", "double": True, "obs_dim": 82, **kw}
    return TorchLearner(
        "node-01", kw.pop("obs_dim"), 5, hidden=32, seed=3, threads=1, capacity=64, **kw
    )


def offers(sender, receiver):
    payload = encode(sender)
    ev = offer(receiver, payload, lambda p: 0.0, margin=-1.0, sender="node-01")
    return ev


def test_peer_candidate_with_another_reward_id_is_rejected_by_name():
    a, b = learner(), learner(reward_id="rew-v0")
    with pytest.raises(PeerError, match="incompatible reward_id: 'rew-v1'"):
        decode(encode(a), b)
    ev = offer(b, encode(a), lambda p: 0.0, margin=-1.0)
    assert ev["accepted"] is False and "incompatible reward_id" in ev["reason"]


@pytest.mark.parametrize("other", [LOCAL, V1, "grid-flat-v2-visits-shared-s8-r2"])
def test_peer_candidate_with_another_encoder_id_is_rejected_by_name(other):
    dims = {LOCAL: 57, V1: 28, "grid-flat-v2-visits-shared-s8-r2": 82}
    a, b = learner(), learner(encoder=other, obs_dim=dims[other])
    with pytest.raises(PeerError, match="incompatible encoder: " + repr(SHARED)):
        decode(encode(a), b)


def test_same_ids_exchange_and_the_payload_carries_the_ids():
    a, b = learner(), learner()
    a.params_numpy()  # same shapes
    meta, _ = decode(encode(a), b)
    assert meta["encoder"] == SHARED and meta["reward_id"] == "rew-v1" and meta["obs_dim"] == 82
    assert meta["learner_schedule"] == "sched-v0"  # recorded for evidence, never a match criterion
    c = learner(schedule_id="sched-t37-v1")
    assert decode(encode(c), b)[0]["learner_schedule"] == "sched-t37-v1"
    assert len(meta["encoder_sha256"]) == 64


def test_checkpoint_with_another_encoder_or_reward_id_is_refused_by_name(tmp_path):
    a = learner()
    a.save_generation(tmp_path)
    learner().load_latest(tmp_path)  # same ids: fine
    with pytest.raises(CheckpointError, match="encoder mismatch"):
        learner(encoder=LOCAL, obs_dim=57).load_latest(tmp_path)
    with pytest.raises(CheckpointError, match="reward_id mismatch"):
        learner(reward_id="rew-v0").load_latest(tmp_path)
    with pytest.raises(CheckpointError, match="learner_schedule mismatch"):
        learner(schedule_id="sched-t37-v1").load_latest(tmp_path)


# --- learning actually works on the v2 observation with rew-v1 ------------------------------------
EPISODES, SEED = 200, 0


@pytest.fixture(scope="module")
def trained():
    """Two drones, 16x16, 8 targets, 150 ticks (the T37 world); the recipe of sched-t37-v1 with an
    episode budget of 200 instead of 400. Deterministic: seeded learners, seeded worlds."""
    env = H.make_env(H.V2_SHARED, "rew-v1")
    L = {
        a: TorchLearner(
            a, H.obs_dim(H.V2_SHARED), 5, hidden=32, seed=SEED * 10 + k, lr=1e-3, gamma=0.95,
            capacity=50000, encoder=SHARED, reward_id="rew-v1", double=True,
            schedule_id="sched-t37-v1", threads=1,
        )
        for k, a in enumerate(env.possible_agents)
    }  # fmt: skip
    untrained = {a: L[a].snapshot() for a in L}
    cfg = t37.Config(
        obs=H.V2_SHARED, reward="rew-v1", eps_start=1.0, eps_end=0.05, eps_frac=0.5,
        lr=1e-3, replay=50000, double=True, episodes=EPISODES,
    )  # fmt: skip
    for i in range(EPISODES):
        eps = cfg.epsilon(i)

        def hook(obs, acts, rew, nxt, term, t):
            for a in acts:
                L[a].observe(obs[a], acts[a], rew[a], nxt[a], term[a])
                L[a].train_step(32, 50)

        H.play(env, H.SCENARIOS["connected"], H.TRAIN_BASE + SEED * EPISODES + i,
               lambda a, o, t, eps=eps: L[a].act(o, eps), hook, info=True)  # fmt: skip
    return L, untrained


def score(make_act):
    runs = t37.eval_policy(H.V2_SHARED, make_act, H.VAL, info=True)
    return {
        k: float(np.mean([r[k] for r in runs]))
        for k in ("ref_return", "coverage_gain", "targets_after_spawn")
    }


def test_trained_torch_learner_beats_untrained_and_idle_on_the_validation_seeds(trained):
    L, untrained = trained
    learned = score(lambda env, s: (lambda sn: lambda a, o, t: L[a].act(o, 0.0, sn[a]))(
        {a: L[a].snapshot() for a in L}))  # fmt: skip
    raw = score(lambda env, s: lambda a, o, t: L[a].act(o, 0.0, untrained[a]))
    idle = score(t37.idle_act)
    # T37 reference numbers (summary.md, rew-v1 re-scored): idle -39.0 / 0 coverage, untrained
    # about -180 and the 400-episode learner +35. A 200-episode run must already clear idle and
    # untrained by a wide margin (200 episodes, seeds 0-3 measured +51.7 / +7.7 / -13.0 / +45.8
    # against idle -39.0 and untrained -213..-323; coverage gain 0.65-0.71, targets 5.8-6.6).
    assert idle["ref_return"] == pytest.approx(-39.0, abs=1.5) and idle["coverage_gain"] == 0.0
    assert learned["ref_return"] > idle["ref_return"] + 15, (learned, idle)
    assert learned["ref_return"] > raw["ref_return"] + 100, (learned, raw)
    assert learned["coverage_gain"] > 0.5 and learned["targets_after_spawn"] > 3, learned
    assert raw["coverage_gain"] < 0.2, raw

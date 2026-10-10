import os
import subprocess
import sys

import numpy as np
import pytest
import torch
from archipelago_learning import Learner
from torch_support import fill, numpy_learner, score, torch_learner, trained_torch

ENV = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}


@pytest.fixture(autouse=True)
def _restore_torch_process_state():
    threads, det = torch.get_num_threads(), torch.are_deterministic_algorithms_enabled()
    yield
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(det)


def test_labels_and_surface():
    assert Learner.backend == "numpy"
    assert "REGRESSION BASELINE" in (sys.modules[Learner.__module__].__doc__ or "")
    assert torch_learner().backend == "torch-cpu"


def test_training_changes_params_and_behavior_and_paused_inference_runs():
    L = torch_learner()
    fill(L)
    before = L.params_numpy()
    s0 = score(before)
    for _ in range(300):
        L.train_step()
    assert not np.allclose(before["w1"], L.params_numpy()["w1"])
    assert s0 < 1.0 and score(L.params_numpy()) == 1.0
    assert [L.act(np.eye(3, dtype=np.float32)[i]) for i in range(3)] == [0, 1, 2]
    L.paused = True
    v, steps = L.version, L.steps
    assert L.train_step() is None and (L.version, L.steps) == (v, steps)
    assert L.act([1, 0, 0]) == 0  # acting continues while paused


def test_q_error_decreases_on_fixed_task():
    L = torch_learner()
    fill(L)
    losses = [L.train_step() for _ in range(300)]
    assert np.mean(losses[:10]) > 3 * np.mean(losses[-10:])
    q = L.snapshot().q(np.eye(3, dtype=np.float32))
    assert np.abs(np.diag(q) - 1.0).max() < 0.2  # the rewarded action's value approaches 1


def test_snapshot_is_immutable_and_unaffected_by_training():
    L = torch_learner()
    fill(L)
    snap = L.snapshot()
    frozen = {k: snap[k].copy() for k in snap.keys()}
    with pytest.raises(ValueError):
        snap["w1"][0, 0] = 1
    for _ in range(100):
        L.train_step()
    assert all(np.array_equal(snap[k], frozen[k]) for k in frozen)
    assert not np.array_equal(L.params_numpy()["w1"], frozen["w1"])
    with torch.no_grad():  # snapshot inference never builds an autograd graph
        assert not torch.from_numpy(snap.q([1, 0, 0])).requires_grad
    assert L.act([1, 0, 0], snap=snap) in (0, 1, 2)


def test_act_uses_published_snapshot_not_live_weights():
    L = torch_learner()
    fill(L)
    published = L._published
    with torch.no_grad():  # poke live weights directly: act must not see this
        L.policy[2].bias.add_(100.0)
    assert L._published is published
    assert L.act([1, 0, 0]) == int(np.argmax(published.q([1, 0, 0])))


def test_two_instances_share_no_mutable_state():
    a, b = trained_torch(0, "a"), trained_torch(1, "b")
    b_params, b_state = b.params_numpy(), b.rng.bit_generator.state
    b_replay = {k: v.copy() for k, v in b.replay.items()}
    b_opt = [s["exp_avg"].clone() for s in b.opt.state.values()]
    b_gen = b.torch_gen.get_state().clone()
    # mutate every part of a
    a.observe(np.ones(3, np.float32), 1, 5.0, np.ones(3, np.float32), False)
    for _ in range(20):
        a.train_step()
    a.act([0, 0, 1], eps=1.0)
    a.torch_gen.manual_seed(123)
    with torch.no_grad():
        for p in a.policy.parameters():
            p.add_(1.0)
        for p in a.target_net.parameters():
            p.add_(1.0)
    assert all(np.array_equal(b.params_numpy()[k], b_params[k]) for k in b_params)
    assert all(np.array_equal(b.replay[k], b_replay[k]) for k in b_replay)
    assert b.rng.bit_generator.state == b_state
    assert all(
        torch.equal(x["exp_avg"], y) for x, y in zip(b.opt.state.values(), b_opt, strict=True)
    )
    assert torch.equal(b.torch_gen.get_state(), b_gen)
    assert a.policy is not b.policy and a.opt is not b.opt and a.events is not b.events
    assert not np.allclose(trained_torch(0, "x").params_numpy()["w1"], b_params["w1"])


def test_same_seed_is_reproducible_and_different_seed_differs():
    x, y, z = trained_torch(3), trained_torch(3), trained_torch(4)
    assert all(np.array_equal(x.params_numpy()[k], y.params_numpy()[k]) for k in x.params_numpy())
    assert not np.array_equal(x.params_numpy()["w1"], z.params_numpy()["w1"])


def test_local_updates_are_logged_as_local_update_events():
    L = torch_learner()
    fill(L)
    L.train_step()
    L.train_step()
    assert [e["type"] for e in L.events] == ["local_update"] * 2
    assert [e["version"] for e in L.events] == [1, 2] and L.events[0]["loss"] >= 0


def test_param_map_layout_matches_forward_and_roundtrips():
    L = torch_learner(seed=2, hidden=7)
    p = L.params_numpy()
    assert {k: (v.dtype, v.shape) for k, v in p.items()} == {
        "w1": (np.float32, (3, 7)),
        "b1": (np.float32, (7,)),
        "w2": (np.float32, (7, 3)),
        "b2": (np.float32, (3,)),
    }
    x = np.random.default_rng(0).standard_normal((5, 3)).astype(np.float32)
    with torch.no_grad():
        want = L.policy(torch.from_numpy(x)).numpy()
    assert np.allclose(Learner.forward(p, x)[1], want, atol=1e-6)
    p["w1"][0, 0] = 99  # exported copy is independent
    assert L.params_numpy()["w1"][0, 0] != 99
    other = torch_learner(seed=9, hidden=7)
    other.load_params_numpy(L.params_numpy())
    assert np.allclose(other.snapshot().q(x), want, atol=1e-6)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(w1=p["w1"].astype(np.float64)),
        lambda p: p.update(w1=p["w1"][:2]),
        lambda p: p.update(b1=np.full_like(p["b1"], np.nan)),
        lambda p: p.pop("b2"),
    ],
)
def test_load_params_numpy_rejects_bad_input_and_leaves_policy_intact(mutate):
    L = torch_learner()
    before = L.params_numpy()
    bad = L.params_numpy()
    mutate(bad)
    with pytest.raises(ValueError):
        L.load_params_numpy(bad)
    assert all(np.array_equal(L.params_numpy()[k], before[k]) for k in before)


def test_one_step_matches_numpy_baseline_with_same_params_and_batches():
    n, t = numpy_learner(seed=5), torch_learner(seed=6)
    t.load_params_numpy(n.params_numpy())
    t.sync_target()
    for L in (n, t):
        fill(L, 200)
        L.rng = np.random.default_rng(77)
    for _ in range(25):
        ln, lt = n.train_step(target_every=10), t.train_step(target_every=10)
        assert np.isclose(ln, lt, rtol=1e-3, atol=1e-5)
    for k, v in n.params.items():
        assert np.allclose(v, t.params_numpy()[k], atol=1e-4)


def test_threads_arg_env_and_default_are_applied_and_recorded(monkeypatch):
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    assert torch_learner().runtime["threads"] == 1 and torch.get_num_threads() == 1
    monkeypatch.setenv("OMP_NUM_THREADS", "2")
    L = torch_learner()
    assert L.runtime["threads"] == 2 and torch.get_num_threads() == 2
    L = torch_learner(threads=1)  # explicit arg wins over env
    assert L.runtime["threads"] == 1 and torch.get_num_threads() == 1
    r = L.runtime
    assert r["backend"] == "torch-cpu" and r["torch_version"] == torch.__version__
    assert r["deterministic"] is True and r["deterministic_error"] is None


def test_thread_env_respected_in_fresh_process():
    code = (
        "import os; os.environ['OMP_NUM_THREADS']='3';"
        "from archipelago_learning import TorchLearner;"
        "print(TorchLearner('a',3,3).runtime['threads'])"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, env=ENV
    )
    assert out.stdout.strip() == "3"


def test_importing_package_does_not_import_torch():
    code = "import sys, archipelago_learning; print('torch' in sys.modules)"
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, env=ENV
    )
    assert out.stdout.strip() == "False"

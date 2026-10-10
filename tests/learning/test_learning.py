import numpy as np
import pytest
from archipelago_learning import Learner, PeerError, decode, encode, offer, rollback


# Controlled task: the right action is the index of the hot input.
def fill(L, n=300, seed=1):
    r = np.random.default_rng(seed)
    for _ in range(n):
        o = np.eye(3, dtype=np.float32)[r.integers(3)]
        a = int(r.integers(3))
        L.observe(o, a, 1.0 if a == int(o.argmax()) else 0.0, o, True)


def score(p):
    x = np.eye(3, dtype=np.float32)
    return float((Learner.forward(p, x)[1].argmax(1) == np.arange(3)).mean())


def trained(seed=0, node="a"):
    L = Learner(node, 3, 3, seed=seed)
    fill(L)
    for _ in range(300):
        L.train_step()
    return L


def test_training_changes_params_and_behavior_and_inference_runs_paused():
    L = Learner("a", 3, 3, seed=0)
    fill(L)
    before = L.snapshot()
    s0 = score(before)
    for _ in range(300):
        L.train_step()
    assert not np.allclose(before["w1"], L.params["w1"])
    assert score(L.params) == 1.0 and s0 < 1.0
    L.paused = True
    v = L.version
    assert L.train_step() is None and L.version == v
    snap = L.snapshot()
    assert L.act([1, 0, 0], snap=snap) == 0
    with pytest.raises(ValueError):
        snap["w1"][0, 0] = 1


def test_nodes_have_distinct_state():
    a, b = trained(0, "a"), trained(1, "b")
    assert a.params["w1"] is not b.params["w1"] and a.replay["o"] is not b.replay["o"]
    assert not np.allclose(a.params["w1"], b.params["w1"])
    a.train_step()
    assert b.opt["t"] == 300 and a.opt["t"] == 301


def test_reject_leaves_policy_unchanged_accept_records_source():
    good, fresh = trained(0, "good"), Learner("fresh", 3, 3, seed=5)
    before = {k: v.copy() for k, v in good.params.items()}
    ev = offer(good, encode(fresh), score)
    assert not ev["accepted"] and all((good.params[k] == before[k]).all() for k in before)
    ev = offer(fresh, encode(good), score)
    assert ev["accepted"] and ev["source"] == "good" and len(ev["payload_sha256"]) == 64
    assert ev["source_version"] == good.version and score(fresh.params) == 1.0
    assert rollback(fresh) and score(fresh.params) < 1.0


def test_invalid_payloads():
    a = Learner("a", 3, 3)
    with pytest.raises(PeerError, match="malformed"):
        decode(b"not an npz", a)
    with pytest.raises(PeerError, match="incompatible encoder"):
        decode(encode(Learner("b", 3, 3, encoder="other")), a)
    bad = Learner("b", 3, 3)
    bad.params["w1"][0, 0] = np.nan
    ev = offer(a, encode(bad), score)
    assert not ev["accepted"] and "nonfinite" in ev["reason"]
    assert not offer(a, encode(Learner("c", 4, 3)), score)["accepted"]


def test_information_only_and_mixing_bounds():
    good = trained(0, "g")
    info = Learner("i", 3, 3, mode="information_only")
    assert not offer(info, encode(good), score)["accepted"]
    ind = Learner("x", 3, 3)
    assert not offer(ind, encode(good), score, alpha=0.3)["accepted"]
    mix = Learner("m", 3, 3, seed=9, mode="mixing")
    assert not offer(mix, encode(good), score, alpha=0.9)["accepted"]


def test_islands_continue_and_restart_restores(tmp_path):
    a = trained(0)
    a.save(tmp_path)
    for _ in range(5):
        a.train_step()  # partitioned: no peers, still learns
    ref = [a.train_step() for _ in range(3)]
    b = Learner("a", 3, 3, seed=99)
    b.load(tmp_path)
    for _ in range(5):
        b.train_step()
    assert [b.train_step() for _ in range(3)] == ref
    assert all(np.array_equal(a.params[k], b.params[k]) for k in a.params)


def test_transfer_vs_no_transfer_control():
    # Same-seed control trains nothing; reports both scores honestly.
    teacher = trained(0, "t")
    control, treated = Learner("c", 3, 3, seed=5), Learner("t2", 3, 3, seed=5)
    offer(treated, encode(teacher), score)
    print(f"transfer-eval: control={score(control.params):.2f} treated={score(treated.params):.2f}")
    assert score(treated.params) >= score(control.params)

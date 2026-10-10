import io
import json
import zipfile

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


def test_checkpoint_restart_restores_state(tmp_path):
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


def test_checkpoint_restores_rollback_events_paused_and_checks_shape(tmp_path):
    good, fresh = trained(0, "good"), Learner("fresh", 3, 3, seed=5)
    assert offer(fresh, encode(good), score)["accepted"]
    fresh.paused = True
    fresh.save(tmp_path)
    assert not list(tmp_path.glob("*.tmp"))
    r = Learner("fresh", 3, 3, seed=1)
    r.load(tmp_path)
    assert r.paused and r.events == fresh.events and r.previous is not None
    assert rollback(r) and score(r.params) < 1.0  # rollback survives restart
    with pytest.raises(ValueError, match="shape"):
        Learner("x", 3, 3, hidden=8).load(tmp_path)


def _npz(meta: bytes, compressed=False, **extra):
    a = Learner("a", 3, 3)
    buf = io.BytesIO()
    (np.savez_compressed if compressed else np.savez)(
        buf, _meta=np.frombuffer(meta, np.uint8), **{**a.params, **extra}
    )
    return buf.getvalue()


def test_decode_rejects_nonobject_meta_and_inflation_bomb():
    a = Learner("a", 3, 3)
    for m in (b"[1]", b"null"):
        with pytest.raises(PeerError, match="malformed"):
            decode(_npz(m), a)
    bomb = _npz(json.dumps({"node": "b"}).encode(), True, junk=np.zeros(1 << 25, np.uint8))
    assert len(bomb) < (1 << 20)  # passes the compressed-size check
    with pytest.raises(PeerError, match="inflates"):
        decode(bomb, a)
    assert not offer(a, bomb, score)["accepted"]
    assert zipfile.is_zipfile(io.BytesIO(bomb))


def test_offer_rejects_spoofed_sender_unbounded_mixing_and_nonfinite_score():
    good = trained(0, "good")
    p = encode(good)
    fresh = Learner("f", 3, 3, seed=5)
    ev = offer(fresh, p, score, sender="mallory")
    assert not ev["accepted"] and "sender" in ev["reason"]
    mix = Learner("m", 3, 3, seed=5, mode="mixing")
    assert not offer(mix, p, score)["accepted"]  # alpha=None would full-replace
    ev = offer(fresh, p, lambda q: float("inf") if q is not fresh.params else 0.0)
    assert not ev["accepted"] and "nonfinite" in ev["reason"] and "candidate_score" not in ev


def test_time_limit_truncation_is_not_stored_as_terminal():
    from archipelago_learning.rollout import episode, make_env, make_learner

    env = make_env()
    ls = dict.fromkeys(env.possible_agents, make_learner("a", 0))
    episode(env, ls, 5, eps=1.0, train=False)  # seed 5 runs to the time limit, no terminal
    L = ls[env.possible_agents[0]]
    assert env.world.tick >= 60 and L.n > 0 and L.replay["d"][: L.n].sum() == 0


def test_transfer_vs_no_transfer_control():
    # Untrained control vs a student that accepted a perfect teacher: transfer must help here.
    teacher = trained(0, "t")
    control, treated = Learner("c", 3, 3, seed=5), Learner("t2", 3, 3, seed=5)
    assert offer(treated, encode(teacher), score)["accepted"]
    assert score(control.params) < 1.0 and score(treated.params) == 1.0


# --- grid sim, transport, contract events -------------------------------------------------


def test_grid_training_changes_behavior():
    from archipelago_learning.rollout import evaluate, make_learner, train

    L = make_learner("a", 0)
    before, s0 = L.snapshot(), evaluate(L.params, range(900, 903))
    train(L, 15)
    assert L.steps > 0 and not np.allclose(before["w1"], L.params["w1"])
    assert evaluate(L.params, range(900, 903)) != s0  # greedy behavior on real episodes changed


def test_grid_transfer_multiseed_reports_and_gates():
    from archipelago_learning.rollout import transfer_experiment

    rows = [transfer_experiment(s) for s in range(3)]
    for r in rows:
        print(f"grid-transfer {r}")
    print(f"mean delta={np.mean([r['delta'] for r in rows]):+.3f}")
    # Gate check: a rejected offer must leave the student exactly as the control (delta 0).
    assert all(np.isfinite(r["delta"]) for r in rows)
    assert all(r["delta"] == 0 for r in rows if not r["accepted"])


def test_mixing_accepted_is_bounded_and_changes_policy():
    teacher = Learner("t", 3, 3, seed=1)
    teacher.params["w1"] = teacher.params["w1"] + 1
    mix = Learner("m", 3, 3, seed=2, mode="mixing")
    own = {k: v.copy() for k, v in mix.params.items()}
    ev = offer(mix, encode(teacher), lambda p: float(p["w1"].sum()), alpha=0.25)
    assert ev["accepted"]
    assert np.allclose(mix.params["w1"], 0.75 * own["w1"] + 0.25 * teacher.params["w1"])
    step = np.abs(mix.params["w1"] - own["w1"]).max()
    assert 0 < step <= 0.25 * np.abs(teacher.params["w1"] - own["w1"]).max() + 1e-6  # bounded


def test_partition_islands_learn_then_heal_and_emit_contract_events():
    from archipelago_learner import LearnerNode
    from archipelago_learning.rollout import episode, make_env, make_learner
    from archipelago_transport import Network

    env = make_env()
    ls = {"node-0": make_learner("node-0", 0), "node-1": make_learner("node-1", 1)}
    net = Network(links=set())  # partitioned: every link cut
    nodes = {a: LearnerNode(ls[a], net, peers=[b for b in ls if b != a]) for a in ls}
    for i in range(6):
        episode(env, ls, i, eps=0.3)
        for n in nodes.values():
            n.broadcast()
        net.tick()
    assert all(L.steps > 0 for L in ls.values()) and net.receive("node-0") is None
    assert net.stats.rejected.get("cut", 0) > 0
    steps = {a: L.steps for a, L in ls.items()}
    net.set_links({("node-0", "node-1"), ("node-1", "node-0")})  # heal -> catch-up delivery
    net.tick()
    nodes["node-1"].poll(lambda p: 0.0, margin=-1.0)  # force accept so we see an accepted record
    nodes["node-0"].poll(lambda p: 0.0, margin=1.0)  # force reject
    recs = [r for n in nodes.values() for r in n.flush(tick=env.world.tick)]
    assert {r.transfer for r in recs} == {"none", "accepted", "rejected"}
    acc = next(r for r in recs if r.transfer == "accepted")
    assert "source=node-0" in acc.reason and acc.new_version == acc.previous_version + 1
    assert all(ls[a].steps == steps[a] for a in ls)  # healing alone does not train
    LearningEventRound = type(recs[0]).model_validate_json(recs[0].model_dump_json())
    assert LearningEventRound == recs[0]

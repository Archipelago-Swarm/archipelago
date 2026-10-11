import numpy as np
import pytest
from archipelago_swarm.explain import attribute, explain
from archipelago_swarm.node import NodeConfig
from archipelago_swarm.skills import LOCALLY_DERIVED, PEER_RECEIVED, Skill, SkillError
from archipelago_swarm.swarm import Swarm
from archipelago_swarm.world import NavWorld

CFG = NodeConfig(eval_episodes=8, eval_every=10**9)
GOOD = {"success_rate": 0.9, "mean_return": 2.0, "mean_steps": 5.0, "episodes": 8, "max_steps": 30}
BAD = {**GOOD, "success_rate": 0.0, "mean_return": -1.0}
REQUIRED = {
    "decision_id", "node_id", "step", "position", "goal", "observation_summary", "terrain_features",
    "reachable_peers", "network_context", "active_policy_id", "raw_policy_output", "action_distribution",  # noqa: E501
    "selected_action", "greedy_action", "selection_method", "epsilon", "attribution", "executed",
    "reward_after_action", "reward_components", "next_position", "experience_recorded",
    "training_update_triggered", "policy_version_before", "policy_version_after", "reason_codes",
}  # fmt: skip


def mk(homes, cfg=CFG, seed=1):
    return Swarm(NavWorld(seed=12), homes, seed=seed, node_cfg=cfg)


@pytest.fixture(scope="module")
def trained():
    sw = mk({"a": (5, 5)})  # a single node: zero reachable peers
    sw.set_learning(["a"])
    sw.run(130)
    return sw


def test_decision_trace_fields_and_greedy_consistency(trained):
    ds = trained.store.get_decisions("a")
    assert len(ds) == 130
    for d in ds:
        assert REQUIRED <= d.keys()
        assert d["selected_action"] in "NESW"
        assert set(d["raw_policy_output"]["q_values"]) == set("NESW")
        if d["selection_method"] == "greedy_argmax_q":
            q = d["raw_policy_output"]["q_values"]
            assert q[d["selected_action"]] == max(q.values())
    assert any(d["selection_method"] == "greedy_argmax_q" for d in ds)
    assert trained.store.get_decision(ds[3]["decision_id"]) is ds[3]


def test_policy_versioning_and_training_without_peers(trained):
    ds, ups = trained.store.get_decisions("a"), trained.store.get_policy_updates("a")
    trig = [d for d in ds if d["training_update_triggered"]]
    assert trig and len(trig) == len(ups)
    for d in trig:
        assert d["policy_version_after"] > d["policy_version_before"]
        assert d["training_event_id"]
    assert all(d["reachable_peers"] == [] and "ISOLATED" in d["reason_codes"] for d in ds)
    u = ups[-1]
    assert {
        "loss",
        "grad_norm",
        "policy_version_after",
        "policy_hash_after",
        "decision_id",
    } <= u.keys()
    assert np.isfinite(u["loss"])
    assert trained.nodes["a"].learner.version == len(ups)


def test_explain_only_uses_record_values(trained):
    d = trained.store.get_decisions("a")[-1]
    txt = explain(d)
    assert d["node_id"] in txt and d["selected_action"] in txt and d["active_policy_id"] in txt
    for v in d["raw_policy_output"]["q_values"].values():
        assert f"{v:+.2f}" in txt
    assert f"{d['reward_after_action']:+.2f}" in txt


def test_attribute_sums_to_first_order_difference():
    r = np.random.default_rng(0)
    p = {
        "w1": r.normal(size=(13, 16)).astype("f"), "b1": r.normal(size=16).astype("f"),
        "w2": r.normal(size=(16, 4)).astype("f"), "b2": np.zeros(4, "f"),
    }  # fmt: skip
    x = r.normal(size=13).astype("f")
    act = (x @ p["w1"] + p["b1"]) > 0
    # exact identity: sum_i x_i * dQ/dx_i = (x@W1) . (act * dW2)
    expect = float((x @ p["w1"]) @ (act * (p["w2"][:, 0] - p["w2"][:, 2])))
    got = sum(t["contribution"] for t in attribute(p, x, 0, 2, top=13))
    assert got == pytest.approx(expect, abs=0.02)
    # with zero biases that is exactly Q0 - Q2
    p["b1"] = np.zeros(16, "f")
    q = np.maximum(x @ p["w1"], 0) @ p["w2"]
    got = sum(t["contribution"] for t in attribute(p, x, 0, 2, top=13))
    assert got == pytest.approx(float(q[0] - q[2]), abs=0.02)


def _pair():
    """a holds a qualified skill; b is far away (link DOWN) and thinks it is bad."""
    sw = mk({"a": (2, 2), "b": (21, 21)})
    a, b = sw.nodes["a"], sw.nodes["b"]
    a._maybe_qualify(0, GOOD)
    b.my_eval = BAD
    return sw, a, b


def test_skill_requires_qualification():
    sw, _, _ = _pair()
    assert (
        len(sw.store.get_events("SKILL_CANDIDATE_CREATED"))
        == len(sw.store.get_events("SKILL_CREATED"))
        == 1
    )
    sw2 = mk({"a": (2, 2)})
    n = sw2.nodes["a"]
    n._maybe_qualify(1, BAD)
    n._maybe_qualify(2, {**GOOD, "success_rate": 0.4})  # below the 0.5 floor
    assert sw2.store.get_events("SKILL_CREATED") == []
    assert sw2.store.get_events("SKILL_CANDIDATE_CREATED") == []
    assert [e["passed"] for e in sw2.store.get_events("SKILL_EVALUATED")] == [False, False]
    assert n.registry.entries == {}


def test_skill_roundtrip_and_tamper(tmp_path):
    _, a, _ = _pair()
    sk = next(iter(a.registry.entries.values())).skill
    back = Skill.from_bytes(sk.to_bytes())
    assert back.content_hash == sk.content_hash and back.skill_id == sk.skill_id
    assert all(np.array_equal(back.params[k], sk.params[k]) for k in sk.params)
    f = tmp_path / "s.skill"
    sk.save(f)
    assert Skill.load(f).content_hash == sk.content_hash
    blob = bytearray(sk.to_bytes())
    blob[-5] ^= 0xFF  # corrupt weight bytes
    with pytest.raises(SkillError):
        Skill.from_bytes(bytes(blob))
    tampered = sk.to_bytes().replace(b'"success_rate": 0.9', b'"success_rate": 1.0')
    assert tampered != sk.to_bytes()
    with pytest.raises(SkillError):
        Skill.from_bytes(tampered)
    with pytest.raises(SkillError):
        Skill.from_bytes(b"junk")


def test_rf_gated_transfer_and_lineage():
    sw, a, b = _pair()
    sid = "terrain-nav-v1@a"
    sk = a.registry.entries[sid].skill
    sw.run(60)
    assert sw.net.link_of("a", "b").state == "DOWN"
    kinds = ("SKILL_REQ", "SKILL_TRANSFER", "SKILL_INSTALLED")
    assert not [e for e in sw.store.events if e["type"].startswith(kinds)]
    assert b.registry.entries == {}
    b.pos = (4, 2)  # a (2,2) <-> b (4,2): UP
    sw.run(40)
    ev = sw.store.get_events
    assert ev("SKILL_REQUESTED", "b") and ev("SKILL_TRANSFER_COMPLETED", "b")
    ent = b.registry.entries[sid]
    assert ent.local_state == PEER_RECEIVED and ent.source_peer == "a"
    assert ent.skill.content_hash == sk.content_hash
    # lineage: derive on b; a's artifact is untouched
    a_params = {k: v.copy() for k, v in sk.params.items()}
    d = b.derive_skill(ent, GOOD, sw.t)
    assert d.origin_type == LOCALLY_DERIVED and d.parent_skill_id == sid
    assert d.derived_from_node_id == "a" and d.origin_node_id == "b"
    a_sk = a.registry.entries[sid].skill
    assert a_sk.content_hash == sk.content_hash
    assert all(np.array_equal(a_params[k], a_sk.params[k]) for k in a_params)
    assert set(a.registry.entries) == {sid}
    lin = sw.store.get_skill_lineage(sid)
    assert [m["skill_id"] for m in lin] == [sid, d.skill_id]
    assert lin[0]["holders"] == ["a", "b"] and lin[1]["holders"] == ["b"]

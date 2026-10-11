"""Learning-backend guarantees (docs/LEARNING_BACKEND_HANDOFF.md section 24). Needs torch."""

from __future__ import annotations

import json

import numpy as np
import pytest

pytest.importorskip("torch")

from archipelago_sim.terrain import Terrain  # noqa: E402
from archipelago_swarm import (  # noqa: E402
    NavWorld,
    NodeConfig,
    Swarm,
    rf,  # noqa: E402
)
from archipelago_swarm.explain import attribute, explain  # noqa: E402
from archipelago_swarm.learner import SYMMETRIES, transform  # noqa: E402
from archipelago_swarm.network import Network  # noqa: E402
from archipelago_swarm.skills import (  # noqa: E402
    LOCALLY_DERIVED,
    PEER_RECEIVED,
    SELF_LEARNED,
    Skill,
    SkillError,
)
from archipelago_swarm.store import Store  # noqa: E402
from archipelago_swarm.world import ACTIONS, DELTA, OBS_DIM, OBS_NAMES, OBS_SCHEMA  # noqa: E402

DECISION_KEYS = {
    "decision_id", "sim_time_s", "step", "node_step", "episode_id", "node_id", "position",
    "battery", "observation_summary", "terrain_features", "network_context", "reachable_peers",
    "active_policy_id", "active_skill_id", "active_skill_origin", "active_skill_version",
    "raw_policy_output", "action_distribution", "selected_action", "selection_method",
    "exploration_vs_exploitation", "reward_after_action", "reward_components",
    "next_state_summary", "experience_recorded", "training_update_triggered",
    "policy_version_before", "policy_version_after", "reason_codes", "attribution",
}  # fmt: skip


def flat_world() -> NavWorld:
    w = NavWorld(seed=1)
    w.terrain = Terrain.flat(24, 100.0)
    return w


def swarm(homes, world=None, **kw) -> Swarm:
    return Swarm(world or flat_world(), homes, seed=0, **kw)


def give_skill(node, success=0.9):
    ev = {"success_rate": success, "mean_return": 5.0, "mean_steps": 8.0, "episodes": 40}
    sk = node._build_skill(f"terrain-nav-v1@{node.id}", "1", SELF_LEARNED, None, None, 0, ev)
    e = node.registry.add(sk, SELF_LEARNED, None, 0)
    e.local_eval, node.registry.active_id = ev, sk.skill_id
    node.store.emit("SKILL_CREATED", 0, node.id, skill=sk.meta())  # telemetry mirror
    return sk


# --- independence ------------------------------------------------------------------------
def test_independent_learners_do_not_share_state():
    sw = swarm({"a": (3, 10), "b": (4, 12), "c": (20, 20)})
    a, b, c = (sw.nodes[k] for k in "abc")
    assert a.policy_hash() == b.policy_hash() == c.policy_hash()  # equivalent baseline
    for x, y in ((a, b), (a, c)):
        assert x.learner.policy is not y.learner.policy
        assert x.learner.opt is not y.learner.opt
        assert x.learner.replay["o"] is not y.learner.replay["o"]
        assert x.registry is not y.registry
    hb, hc = b.policy_hash(), c.policy_hash()
    sw.set_learning(["a"])
    sw.run(250)
    assert a.learner.steps > 0 and a.policy_hash() != hb
    assert b.policy_hash() == hb and c.policy_hash() == hc  # training A did not mutate B or C
    assert b.learner.steps == 0 and b.learner.n == 0


def test_policies_diverge_on_different_experience():
    sw = swarm({"a": (3, 10), "b": (4, 12)})
    sw.set_learning(["a", "b"])
    sw.run(250)
    assert sw.nodes["a"].policy_hash() != sw.nodes["b"].policy_hash()
    assert (
        sw.store.get_decisions("a")[10]["position"] != sw.store.get_decisions("b")[10]["position"]
    )


# --- terrain observation -----------------------------------------------------------------
def test_terrain_changes_observation_and_schema_is_respected():
    w = NavWorld(seed=12)
    o1, o2 = w.observe((5, 5), (8, 8)), w.observe((9, 7), (12, 8))
    assert o1.shape == (OBS_DIM,) and len(OBS_SCHEMA) == OBS_DIM == len(OBS_NAMES)
    terrain_idx = [i for i, r in enumerate(OBS_SCHEMA) if r[5] == "terrain"]
    assert not np.allclose(o1[terrain_idx], o2[terrain_idx])
    # same goal offset, different cell: only terrain features differ
    a, b = w.observe((5, 5), (8, 8)), w.observe((9, 7), (12, 10))
    assert np.allclose(a[:3], b[:3]) and not np.allclose(a[3:], b[3:])
    # slope_E equals the physical rise of the east neighbour over the limit
    assert a[OBS_NAMES.index("slope_E")] == pytest.approx(
        np.clip(w.slope((5, 5), (6, 5)) / 1.0, -2, 2), abs=1e-5
    )
    rng = np.random.default_rng(0)
    for _ in range(100):
        p = (int(rng.integers(0, 24)), int(rng.integers(0, 24)))
        g = (int(rng.integers(0, 24)), int(rng.integers(0, 24)))
        o = w.observe(p, g)
        assert np.isfinite(o).all() and (np.abs(o) <= 2.0 + 1e-6).all()
    assert w.observe((0, 0), (3, 3))[OBS_NAMES.index("slope_N")] == 2.0  # map edge


def test_rejected_moves_follow_terrain():
    w = NavWorld(seed=12)
    steep = [
        (c, d)
        for c in ((x, y) for x in range(1, 22) for y in range(1, 22))
        for d in range(4)
        if abs(w.slope(c, (c[0] + DELTA[d][0], c[1] + DELTA[d][1]))) > 1.0
    ]
    c, d = steep[0]
    nxt, r, comp, _, info = w.step(c, (c[0] + 3, c[1]), d)
    assert nxt == c and info["rejected"] == "too_steep" and comp["invalid"] < 0


# --- RF ----------------------------------------------------------------------------------
def test_ridge_obstructs_link_and_removing_it_restores():
    t = Terrain.flat(24, 100.0)
    a, b = (6, 10), (11, 10)
    assert rf.link(t, "a", a, "b", b).state == rf.UP and rf.link(t, "a", a, "b", b).terrain_los
    t.elev[8][10] = 600.0  # ridge between the two airframes
    blocked = rf.link(t, "a", a, "b", b)
    assert not blocked.terrain_los and blocked.state == rf.DOWN and blocked.obstruction_db > 8
    t.elev[8][10] = 0.0
    assert rf.link(t, "a", a, "b", b).state == rf.UP


def test_distance_degrades_link_monotonically():
    t = Terrain.flat(24, 100.0)
    ms = [rf.link(t, "a", (2, 10), "b", (2 + d, 10)).margin_db for d in range(1, 22)]
    assert all(x > y for x, y in zip(ms, ms[1:], strict=False))
    states = [rf.link(t, "a", (2, 10), "b", (2 + d, 10)).state for d in (2, 8, 20)]
    assert states == [rf.UP, rf.DEGRADED, rf.DOWN]


def test_peer_visibility_and_send_follow_rf_graph():
    t = Terrain.flat(24, 100.0)
    store = Store()
    net = Network(store, dt_s=0.1)
    net.update(1, t, {"a": (2, 10), "b": (4, 10), "c": (21, 10)})
    pa, pb, pc = net.port("a"), net.port("b"), net.port("c")
    assert set(pa.neighbors()) == {"b"} and set(pb.neighbors()) == {"a"} and pc.neighbors() == {}
    assert pa.send("b", {"kind": "PEER_SUMMARY", "summary": {}}) is True
    assert pa.send("c", {"kind": "SKILL_ADVERT", "skills": []}) is False  # no link
    assert pa.budget_bytes("c") == 0 and pa.budget_bytes("b") > 0
    net.update(2, t, {"a": (2, 10), "b": (4, 10), "c": (21, 10)})
    assert [m["src"] for m in pb.recv()] == ["a"] and pc.recv() == []
    for t_ in range(3, 9):  # events are debounced: the state must persist 5 ticks
        net.update(t_, t, {"a": (2, 10), "b": (4, 10), "c": (21, 10)})
    assert [e["type"] for e in store.events] == ["RF_LINK_UP"]
    # a DEGRADED link carries small messages but never artifact chunks
    net.update(9, t, {"a": (2, 10), "b": (10, 10), "c": (21, 10)})
    assert net.link_of("a", "b").state == rf.DEGRADED
    assert pa.send("b", {"kind": "SKILL_REQUEST"}) and not pa.send("b", {"kind": "SKILL_CHUNK"})
    assert pa.budget_bytes("b") == 0


# --- decision trace ----------------------------------------------------------------------
def test_decision_trace_complete_and_consistent_with_policy():
    sw = swarm({"a": (3, 10), "b": (20, 20)})
    sw.set_learning(["a"])
    sw.run(150)
    for d in sw.store.get_decisions("a"):
        assert DECISION_KEYS <= set(d)
        assert sum(d["action_distribution"].values()) == pytest.approx(1.0, abs=1e-3)
        assert d["selected_action"] in ACTIONS and "ISOLATED" in d["reason_codes"]
        json.dumps(d)
    # b never learns: its weights are fixed, so the logged Q-values must be reproducible
    b = sw.nodes["b"]
    p = b.learner.params_numpy()
    for d in sw.store.get_decisions("b"):
        x = np.array(d["observation"], np.float32)
        q = np.maximum(x @ p["w1"] + p["b1"], 0) @ p["w2"] + p["b2"]
        logged = d["raw_policy_output"]["q_values"]
        assert [logged[k] for k in ACTIONS] == pytest.approx(q.tolist(), abs=1e-3)
        if d["selection_method"] == "greedy_argmax_q":
            assert d["selected_action"] == ACTIONS[int(np.argmax(q))]
        assert not d["experience_recorded"] and not d["training_update_triggered"]
    assert sw.store.get_decision("a-d000005")["node_id"] == "a"
    assert "selected" in explain(sw.store.get_decision("a-d000005"))


def test_attribution_matches_numerical_gradient():
    sw = swarm({"a": (3, 10)})
    n = sw.nodes["a"]
    p = {k: v.astype(np.float64) for k, v in n.learner.params_numpy().items()}
    x = np.array(n.plant.observe((3, 10), (6, 12)), np.float64)

    def qd(v):
        q = np.maximum(v @ p["w1"] + p["b1"], 0) @ p["w2"] + p["b2"]
        return q[0] - q[1]

    top = attribute(p, x, 0, 1, top=OBS_DIM)
    for t in top:
        i = OBS_NAMES.index(t["feature"])
        e = np.zeros(OBS_DIM)
        e[i] = 1e-6
        grad = (qd(x + e) - qd(x - e)) / 2e-6
        assert t["contribution"] == pytest.approx(x[i] * grad, abs=2e-3)


# --- policy versioning / learning trace --------------------------------------------------
def test_policy_versions_track_updates():
    sw = swarm({"a": (3, 10)})
    sw.set_learning(["a"])
    sw.run(300)
    n = sw.nodes["a"]
    ups = sw.store.get_policy_updates("a")
    assert len(ups) == n.learner.steps > 0 and n.learner.version == len(ups)
    assert [u["policy_version_after"] for u in ups] == list(range(1, len(ups) + 1))
    assert all(u["policy_version_after"] == u["policy_version_before"] + 1 for u in ups)
    assert {"loss", "grad_norm", "batch_size", "experience_count", "reward_window"} <= set(ups[0])
    byid = {d["decision_id"]: d for d in sw.store.get_decisions("a")}
    for u in ups[:20]:
        d = byid[u["decision_id"]]
        assert (
            d["training_update_triggered"]
            and d["policy_version_after"] == u["policy_version_after"]
        )
    for d in sw.store.get_decisions("a"):
        assert d["active_policy_id"] == f"a-policy-v{d['policy_version_before']:04d}"


def test_learning_continues_with_zero_reachable_peers():
    sw = swarm({"a": (3, 10), "b": (21, 21)})
    sw.set_learning(["a", "b"])
    sw.run(200)
    assert sw.groups() == [["a"], ["b"]]
    for n in sw.nodes.values():
        assert n.learner.steps > 0 and n.neighbors == {} and n.c["peer_summaries_sent"] == 0


# --- skills ------------------------------------------------------------------------------
def test_skill_not_created_without_qualification():
    sw = swarm({"a": (3, 10)}, node_cfg=NodeConfig(eval_every=100, qual_success=1.01))
    sw.set_learning(["a"])
    sw.run(600)
    assert not sw.store.get_events("SKILL_CREATED") and not sw.store.get_events(
        "SKILL_CANDIDATE_CREATED"
    )
    assert sw.store.get_events("SKILL_EVALUATED")  # it was evaluated and did not qualify
    idle = swarm(
        {"a": (3, 10)}, node_cfg=NodeConfig(eval_every=100, qual_success=0.0, qual_gain=-1)
    )
    idle.run(600)  # no learning => no evaluation window => no skill, whatever the thresholds
    assert not idle.store.get_events("SKILL_CREATED")


def test_skill_created_from_real_policy_state_and_roundtrips(tmp_path):
    cfg = NodeConfig(eval_every=100, qual_success=0.0, qual_gain=-1.0)
    sw = swarm({"a": (3, 10)}, node_cfg=cfg, out_dir=tmp_path / "run")
    sw.set_learning(["a"])
    sw.run(150)
    sw.close()
    cand, made = (
        sw.store.get_events("SKILL_CANDIDATE_CREATED"),
        sw.store.get_events("SKILL_CREATED"),
    )
    assert cand and made and cand[0]["seq"] < made[0]["seq"]
    assert cand[0]["evaluation"]["success_rate"] >= cand[0]["required_success"]
    entry = sw.nodes["a"].registry.entries[made[0]["skill"]["skill_id"]]
    sk = entry.skill
    assert sk.origin_type == SELF_LEARNED and entry.local_state == SELF_LEARNED
    assert sk.training["policy_version"] >= 1 and sk.training["updates"] > 0
    files = list((tmp_path / "run" / "skills").glob("*.skill"))
    assert files
    back = Skill.load(files[0])
    assert back.content_hash == Skill.load(files[0]).content_hash
    for k in sk.params:
        assert np.array_equal(back.params[k], Skill.from_bytes(sk.to_bytes()).params[k])
    blob = bytearray(sk.to_bytes())
    blob[-9] ^= 0xFF
    with pytest.raises(SkillError):
        Skill.from_bytes(bytes(blob))
    with pytest.raises(SkillError):
        Skill.from_bytes(sk.to_bytes()[:50])


def test_dihedral_symmetries_are_consistent():
    assert len(SYMMETRIES) == 8
    o = np.arange(OBS_DIM, dtype=np.float32) / 10
    for perm, m in SYMMETRIES:
        for a, (dx, dy) in enumerate(DELTA):  # the goal-offset map agrees with the action map
            assert (m[0][0] * dx + m[0][1] * dy, m[1][0] * dx + m[1][1] * dy) == DELTA[perm[a]]
        t = transform(o, perm, m)
        assert t[OBS_NAMES.index("slope_" + ACTIONS[perm[1]])] == o[OBS_NAMES.index("slope_E")]
    assert len({tuple(transform(o, p, m)) for p, m in SYMMETRIES}) == 8


# --- RF-gated transfer, provenance, adaptation -------------------------------------------
def two_nodes(far: bool, **rf_kw):
    sw = swarm(
        {"node-a": (2, 10), "node-b": (20, 10) if far else (5, 10)},
        rf_cfg=rf.RFConfig(**rf_kw),
    )
    for n in sw.nodes.values():
        n._act = lambda t: None  # park: positions are set explicitly by the test
    return sw, sw.nodes["node-a"], sw.nodes["node-b"]


def test_transfer_is_impossible_without_a_link_then_succeeds_when_connected():
    sw, a, b = two_nodes(far=True)
    sk = give_skill(a)
    sw.run(120)
    assert sw.groups() == [["node-a"], ["node-b"]]
    assert not b.registry.entries and a.c["skill_advertisements"] == 0
    assert not sw.store.get_events("SKILL_ADVERTISED") and not sw.store.get_events(
        "SKILL_REQUESTED"
    )
    assert sw.net.stats["node-a"].get("SKILL_ADVERT_blocked", 0) == 0  # never even attempted
    b.pos = (5, 10)  # topology change
    sw.run(60)
    assert set(sw.store.get_events("SKILL_INSTALLED")[0]["source_peer"]) == set("node-a")
    e = b.registry.entries[sk.skill_id]
    assert e.local_state == PEER_RECEIVED and e.source_peer == "node-a"
    assert e.skill.content_hash == sk.content_hash and e.skill.origin_node_id == "node-a"
    assert e.skill.origin_type == SELF_LEARNED  # lineage preserved through the transfer
    assert b.c["skill_transfers_received"] == 1 and a.c["skill_transfers_sent"] == 1
    kinds = [x["type"] for x in sw.store.events if x["type"].startswith("SKILL_")]
    order = ["SKILL_ADVERTISED", "SKILL_REQUESTED", "SKILL_TRANSFER_STARTED", "SKILL_INSTALLED"]
    assert [kinds.index(k) for k in order] == sorted(kinds.index(k) for k in order)
    done = sw.store.get_events("SKILL_TRANSFER_COMPLETED")
    assert {d["side"] for d in done} == {"sender", "receiver"}


def test_degraded_link_carries_metadata_but_not_the_artifact():
    sw, a, b = two_nodes(far=False)
    b.pos = (9, 10)  # 7 cells: DEGRADED
    give_skill(a)
    sw.run(80)
    assert sw.net.link_of("node-a", "node-b").state == rf.DEGRADED
    assert b.peers["node-a"]["adverts"]  # metadata arrived
    assert not b.registry.entries  # artifact did not
    assert sw.store.get_events("SKILL_TRANSFER_FAILED")  # stalled and gave up, not silently done


def test_link_loss_mid_transfer_fails_the_transfer():
    sw, a, b = two_nodes(far=False, max_bw_kbps=0.8)  # ~10 B/tick: many ticks per artifact
    give_skill(a)
    sw.run(40)
    assert a.out or b.inn  # transfer in flight, not instantaneous
    assert not b.registry.entries
    b.pos = (21, 21)
    sw.run(60)
    assert not b.registry.entries
    fails = sw.store.get_events("SKILL_TRANSFER_FAILED")
    assert fails and {f["side"] for f in fails} >= {"sender"}
    assert a.c["skill_transfer_failures"] >= 1 and a.c["skill_transfers_sent"] == 0


def test_received_skill_stays_learnable_and_derived_copy_is_independent():
    sw, a, b = two_nodes(far=False)
    sk = give_skill(a)
    sw.run(40)
    ha = a.policy_hash()
    ent = b.registry.entries[sk.skill_id]
    b.activate_skill(sk.skill_id, sw.t, {"test": True})
    del b.__dict__["_act"]  # un-park b so it flies and learns
    assert b.policy_hash() != ha or np.allclose(b.learner.params_numpy()["w1"], sk.params["w1"])
    a_params = {k: v.copy() for k, v in a.registry.entries[sk.skill_id].skill.params.items()}
    sw.set_learning(["node-b"])
    sw.run(300)
    assert b.learner.steps > 0 and b.policy_hash() != ent.skill.training["params_sha256"]
    acts = sw.store.get_events("SKILL_ACTIVATED", "node-b")
    assert acts[0]["source_peer"] == "node-a" and acts[0]["policy_version_after"] == 1
    ds = [d for d in sw.store.get_decisions("node-b") if d["active_skill_id"]]
    assert ds and ds[-1]["active_skill_origin"] == PEER_RECEIVED
    assert ds[-1]["policy_diverged_from_skill"] is True
    ev = {"success_rate": 0.9, "mean_return": 6.0, "mean_steps": 7.0, "episodes": 40}
    child = b.derive_skill(ent, ev, sw.t)
    assert child.origin_type == LOCALLY_DERIVED and child.parent_skill_id == sk.skill_id
    assert child.derived_from_node_id == "node-a" and child.origin_node_id == "node-b"
    assert b.registry.entries[child.skill_id].local_state == LOCALLY_DERIVED
    lin = [m["skill_id"] for m in sw.store.get_skill_lineage(child.skill_id)]
    assert lin == [sk.skill_id, child.skill_id]
    # A's artifact, registry and learner are untouched by B's training and derivation
    for k, v in a_params.items():
        assert np.array_equal(a.registry.entries[sk.skill_id].skill.params[k], v)
    assert a.policy_hash() == ha and child.skill_id not in a.registry.entries


def test_observation_and_skill_sharing_are_separate_counters():
    sw, a, b = two_nodes(far=False)
    give_skill(a)
    sw.run(60)
    assert a.c["peer_summaries_sent"] > 0 and b.c["peer_summaries_received"] > 0
    assert a.c["skill_advertisements"] > 0 and b.c["skill_transfers_received"] == 1
    assert b.peers["node-a"]["summary"]["policy_version"] == 0  # observation-style summary


# --- determinism + the full experiment ---------------------------------------------------
def test_runs_are_deterministic():
    def run():
        sw = swarm({"a": (3, 10), "b": (5, 11)})
        sw.set_learning(["a", "b"])
        sw.run(120)
        return (
            [n.policy_hash() for n in sw.nodes.values()],
            json.dumps(sw.store.get_decisions("a"), sort_keys=True),
        )

    assert run() == run()


def test_full_experiment_reproduces_every_phase(tmp_path):
    from archipelago_swarm.experiment import run_experiment

    r = run_experiment(tmp_path / "exp", seed=0, log=lambda m: None)
    assert r["ok"], r["checks"]
    s = Store.load(tmp_path / "exp")
    assert (
        s.get_events("SKILL_DERIVED")
        and s.get_decisions("node-3")
        and s.get_policy_updates("node-0")
    )
    der = s.get_events("SKILL_DERIVED")[0]
    assert [
        m["provenance"] if "provenance" in m else m["origin_type"]
        for m in s.get_skill_lineage(der["skill"]["skill_id"])
    ][-1] == LOCALLY_DERIVED

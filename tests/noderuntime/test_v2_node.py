"""T38: the live node under the T37 ids (Amendment A18): v2 observation with node-local memory,
visited-cell summaries over the peer channel (non-model, cut-gated both ways), per-episode epsilon,
ids in status/checkpoints, configure validation, restart. Old ids keep working (other test files).
"""

from __future__ import annotations

import json
import time

import numpy as np
import pytest
from archipelago_learning import checkpoint as lck
from archipelago_learning.torch_dqn import check_identity
from archipelago_noderuntime import summary
from archipelago_noderuntime.node import Node
from archipelago_noderuntime.runtime import Runtime
from archipelago_noderuntime.validation import ValidationWorld
from archipelago_peer import post
from archipelago_sim.env import GridWorld
from archipelago_transport import Envelope
from support import PEER_TOKEN, Client, Cluster, MiniCoordinator, make_cfg, obs_json, t37_over

N1, N2 = "node-01", "node-02"
ENC = "grid-flat-v2-visits-shared-s8-r2"
CUT = [{"start_tick": 0, "end_tick": 100000, "cut_links": [[N1, N2]]}]


def wait(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture()
def pair(tmp_path):
    c = Cluster(tmp_path, (N1, N2), **t37_over())
    yield c
    c.close()


def coord_for(c):
    return MiniCoordinator(c.clients, reward_id="rew-v1")


# --- ids, shapes -------------------------------------------------------------------------------
def test_node_runs_the_t37_ids_end_to_end(pair):
    coord_for(pair).run_episode(0, seed=3, ticks=40)
    for nid in (N1, N2):
        st = pair.clients[nid].status()
        assert st["encoder_id"] == ENC and st["obs_dim"] == 82
        assert st["reward_id"] == "rew-v1" and st["learner_schedule_id"] == "sched-t37-v1"
        assert st["double_dqn"] is True and len(st["encoder_sha256"]) == 64
        assert st["train_steps"] > 0 and st["replay_size"] == 40
        L = pair.node(nid).learner
        assert L.params_numpy()["w1"].shape == (82, 32)  # network input follows the obs size
        assert (L.encoder, L.reward_id, L.schedule_id, L.double) == (
            ENC, "rew-v1", "sched-t37-v1", True,
        )  # fmt: skip
        assert L.replay["o"].shape == (50000, 82)
        # the stored transitions carry the v2 features: own visit counts and a frontier
        o = L.replay["o"][: L.n]
        assert (o[:, 28:53] > 0).any() and (o[:, 53:57] > 0).any()


def test_encoder_hash_differs_between_v1_v2_and_geometry():
    from archipelago_learning import encoders

    ids = [
        "grid-flat-v1-s8-r2",
        "grid-flat-v2-visits-s8-r2",
        ENC,
        "grid-flat-v2-visits-shared-s16-r2",
    ]
    assert len({encoders.get(i).sha256 for i in ids}) == 4
    assert [encoders.get(i).obs_dim for i in ids] == [28, 57, 82, 82]


# --- summaries: information, not model transfer --------------------------------------------------
def test_summaries_flow_between_open_peers_and_are_never_a_model_transfer(pair):
    a, b = pair.node(N1), pair.node(N2)
    coord_for(pair).run_episode(0, seed=3, ticks=30)
    assert wait(lambda: a.counters["summaries_applied"] > 0 and b.counters["summaries_applied"] > 0)
    for n, other in ((a, b), (b, a)):
        c = n.counters
        assert c["summaries_sent"] > 0 and c["summaries_cut"] == 0
        # not a model offer: no offer, no inbox entry, no validation, no decision
        for k in ("offers_sent", "offers_received", "decisions_accepted", "decisions_rejected",
                  "exchanges", "received_cut", "offers_cut"):  # fmt: skip
            assert c[k] == 0, k
        assert n.peer.receive() is None
        # the flags come from what the peer reported: a subset of the peer's own visited cells
        assert wait(lambda n=n, other=other: len(n.memory.peer_cells()) > 0)
        assert n.memory.peer_cells() <= other.memory.own_cells()
        assert list(n.memory.peer_sources()) == [N2 if n is a else N1]
        s = pair.clients[n.cfg.node_id].status()["summaries"]
        assert s["peer_cells"] > 0 and s["last_reject"] is None
    # the next episode starts with empty peer flags (they belong to one episode)
    pair.clients[N1].control("reset", run_id="run-t", episode=1, mode="train")
    assert a.memory.peer_cells() == frozenset() and a.memory.own_cells() == frozenset()


def test_cut_link_carries_no_summary_in_either_direction(pair):
    a, b = pair.node(N1), pair.node(N2)
    coord_for(pair).run_episode(0, seed=3, ticks=30, schedule=CUT)
    for n in (a, b):
        assert wait(lambda n=n: n.counters["summaries_cut"] > 0)
        c = n.counters
        assert c["summaries_sent"] == 0 and c["summaries_applied"] == 0
        assert c["summaries_received"] == 0  # nothing even reached the peer endpoint
        assert n.memory.peer_cells() == frozenset()
    assert pair.clients[N1].status()["peers"] == {N2: "cut"}


def test_receiver_refuses_a_summary_across_a_cut_the_sender_does_not_know(pair):
    a, b = pair.node(N1), pair.node(N2)
    coord = coord_for(pair)
    coord.reset(0)
    pair.clients[N2].control("set_schedule", fault_schedule=CUT)  # only B knows about the cut
    coord.run_episode(0, seed=3, ticks=20)
    assert wait(lambda: a.counters["summaries_refused_by_peer"] > 0)
    assert a.counters["summaries_sent"] == 0
    assert b.counters["summaries_received_cut"] > 0 and b.counters["summaries_applied"] == 0
    assert b.memory.peer_cells() == frozenset()
    # B (which knows the cut) sends nothing to A; A therefore never applies a summary either
    assert b.counters["summaries_sent"] == 0 and a.counters["summaries_applied"] == 0


def test_sender_suppresses_a_summary_on_a_cut_the_receiver_does_not_know(pair):
    a, b = pair.node(N1), pair.node(N2)
    coord = coord_for(pair)
    coord.reset(0)
    pair.clients[N1].control("set_schedule", fault_schedule=CUT)  # only A knows
    coord.run_episode(0, seed=3, ticks=20)
    assert wait(lambda: a.counters["summaries_cut"] > 0)
    assert a.counters["summaries_sent"] == 0
    assert b.counters["summaries_applied"] == 0 and b.memory.peer_cells() == frozenset()


# --- wire-level admission ------------------------------------------------------------------------
class Wire:
    """Hand-made summaries posted to node-02's real peer endpoint."""

    def __init__(self, cluster):
        self.c, self.b = cluster, cluster.node(N2)
        self.url = cluster.runtimes[N2].peer_url
        self.seq = 1_000_000
        cluster.clients[N2].control("reset", run_id="run-t", episode=0, mode="train")

    def payload(self, cells=((1, 1), (2, 3)), **over):
        kw = dict(node=N1, run_id="run-t", episode=0, tick=3, encoder=ENC, size=8, cells=cells)
        kw.update(over)
        return summary.encode(
            kw["node"], kw["run_id"], kw["episode"], kw["tick"], kw["encoder"], kw["size"],
            kw["cells"],
        )  # fmt: skip

    def send(self, payload, src=N1, token=PEER_TOKEN, seq=None, digest=None):
        self.seq += 1
        env = Envelope.make(src, N2, self.seq if seq is None else seq, payload)
        if digest:
            env = Envelope(env.src, env.dst, env.seq, env.payload, env.version, digest)
        return post(self.url, env, 2.0, 0, token)


def test_valid_summary_is_applied_once_and_replays_are_stale(pair):
    w = Wire(pair)
    assert w.send(w.payload(), seq=5) == 200
    assert w.b.memory.peer_cells() == {(1, 1), (2, 3)}
    assert w.send(w.payload(cells=((7, 7),)), seq=5) == 202  # same seq: stale
    assert w.send(w.payload(cells=((7, 7),)), seq=4) == 202  # older seq: stale
    assert w.b.counters["summaries_stale"] == 2 and (7, 7) not in w.b.memory.peer_cells()
    assert w.send(w.payload(cells=((7, 7),)), seq=6) == 200  # newer: adds
    assert w.b.memory.peer_cells() == {(1, 1), (2, 3), (7, 7)}
    c = w.b.counters
    assert c["offers_received"] == 0 and c["decisions_accepted"] + c["decisions_rejected"] == 0
    assert w.b.peer.receive() is None and c["summaries_applied"] == 2


@pytest.mark.parametrize(
    ("kw", "status", "reason"),
    [
        ({"encoder": "grid-flat-v1-s8-r2"}, 422, "incompatible encoder"),
        ({"encoder": "grid-flat-v2-visits-s8-r2"}, 422, "incompatible encoder"),
        ({"size": 9}, 422, "incompatible size"),
        ({"node": N2}, 403, "claimed node"),  # sent by node-01, claims to be node-02
    ],
)
def test_incompatible_or_forged_summaries_are_refused_with_a_named_reason(pair, kw, status, reason):
    w = Wire(pair)
    assert w.send(w.payload(**kw)) == status
    assert reason in w.b.last_summary_reject
    assert w.b.memory.peer_cells() == frozenset() and w.b.counters["summaries_applied"] == 0


def test_malformed_oversized_and_inconsistent_summaries_are_rejected(pair):
    w = Wire(pair)
    good = json.loads(w.payload())
    bad = [
        b"{not json",
        json.dumps({**good, "kind": "model"}).encode(),
        json.dumps({**good, "n": good["n"] + 1}).encode(),
        json.dumps({**good, "cells": "!!!!"}).encode(),
        json.dumps({**good, "cells": "AAAA"}).encode(),  # wrong bitmap length
        json.dumps({**good, "extra": 1}).encode(),
        json.dumps({**good, "episode": -1}).encode(),
        b"{" + b" " * (summary.MAX_SUMMARY_BYTES + 10) + b"}",
    ]
    for p in bad:
        assert w.send(p) == 422, p[:40]
    assert w.send(w.payload(), digest="0" * 64) == 422  # digest not the payload's
    assert w.b.counters["summaries_applied"] == 0 and w.b.counters["summaries_rejected"] >= 9


def test_summary_of_another_episode_or_run_is_ignored_not_applied(pair):
    w = Wire(pair)
    assert w.send(w.payload(episode=7)) == 202
    assert w.send(w.payload(run_id="other-run")) == 202
    assert w.b.counters["summaries_ignored"] == 2 and w.b.memory.peer_cells() == frozenset()


def test_summary_endpoint_needs_the_peer_token_and_a_declared_sender(pair):
    w = Wire(pair)
    assert w.send(w.payload(), token="wrong-token-0123456789") == 401
    assert w.send(w.payload(), token=None) == 401
    assert w.send(w.payload(node="node-09"), src="node-09") == 403  # not in NODE_IDS
    assert w.b.counters["summaries_received"] == 0


def test_summary_size_is_bounded_by_the_grid_not_by_play():
    p16 = summary.encode(
        N1,
        "r",
        0,
        0,
        "grid-flat-v2-visits-shared-s16-r2",
        16,
        [(x, y) for x in range(16) for y in range(16)],
    )
    p256 = summary.encode(N1, "r", 0, 0, "x", 256, [(x, y) for x in range(256) for y in range(256)])
    assert len(p16) < 400 and len(p256) <= summary.MAX_SUMMARY_BYTES
    s = summary.decode(p16, expect_size=16, expect_encoder="grid-flat-v2-visits-shared-s16-r2")
    assert len(s.cells) == 256
    with pytest.raises(summary.SummaryError):
        summary.encode(N1, "r", 0, 0, "x", 257, [])


# --- per-episode epsilon (sched-t37-v1) -----------------------------------------------------------
def test_epsilon_decays_per_training_episode_and_eval_episodes_do_not_count(tmp_path):
    c = Cluster(tmp_path, (N1,), **t37_over(eps_decay_episodes=4, exchange_every_ticks=0))
    try:
        cl = c.clients[N1]
        w = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=40, reward_id="rew-v1")
        o = w.reset(1)["node-0"]

        def eps(ep, mode):
            cl.control("reset", run_id="run-t", episode=ep, mode=mode)
            st, out = cl.act("run-t", ep, 0, obs_json("run-t", "n", 0, o))
            assert st == 200
            return out["epsilon"]

        got = [eps(0, "train"), eps(1, "train"), eps(2, "eval"), eps(3, "train"), eps(4, "train")]
        got += [eps(5, "train"), eps(6, "train"), eps(7, "train")]
        # training-episode index 0,1,(eval),2,3,4,5,6 -> linear 1.0 -> 0.05 over 4, then constant
        want = [1.0 - 0.95 * min(1.0, i / 4) for i in (0, 1)] + [0.0]
        want += [1.0 - 0.95 * min(1.0, i / 4) for i in (2, 3, 4, 5, 6)]
        assert got == pytest.approx(want)
        # constant within an episode: a second act of the same episode keeps the same epsilon
        st, out = cl.act("run-t", 7, 1, obs_json("run-t", "n", 1, o))
        assert out["epsilon"] == pytest.approx(0.05)
        assert cl.status()["train_episode"] == 6
    finally:
        c.close()


# --- configure / restart / checkpoint identity ----------------------------------------------------
def conf(**over):
    body = {
        "hyperparameters": {"lr": 1e-3, "gamma": 0.95, "hidden": 32, "capacity": 50000,
                            "batch": 32, "target_every": 50, "train_steps_per_feedback": 1,
                            "double_dqn": True},
        "epsilon_schedule": {"start": 1.0, "end": 0.05, "decay_episodes": 3},
        "margin": 0.0,
        "world_config": {"size": 8, "n_targets": 0, "obstacle_density": 0.12, "sense_radius": 2,
                         "max_ticks": 30, "battery_scale": 4.0, "reward_id": "rew-v1"},
        "gate_seeds": [5001, 5002],
        "n_validation_agents": 2,
        "encoder_id": ENC,
        "exchange_every_ticks": 0,
        "seed": 3,
        "learner_schedule_id": "sched-t37-v1",
    }  # fmt: skip
    body.update(over)
    return body


def test_configure_selects_the_ids_and_refuses_contradictions(tmp_path):
    rt = Runtime(make_cfg(tmp_path, node_ids=(N1,))).start()
    try:
        c = Client(rt.control_url)
        for label, bad, needle in (
            ("lr", conf(hyperparameters={**conf()["hyperparameters"], "lr": 0.01}), "requires lr"),
            (
                "capacity",
                conf(hyperparameters={**conf()["hyperparameters"], "capacity": 500}),
                "capacity",
            ),
            (
                "double",
                conf(hyperparameters={**conf()["hyperparameters"], "double_dqn": False}),
                "double_dqn",
            ),
            (
                "eps",
                conf(epsilon_schedule={"start": 0.5, "end": 0.05, "decay_episodes": 3}),
                "epsilon start",
            ),
            ("unknown", conf(learner_schedule_id="sched-nope"), "unknown learner_schedule_id"),
            ("encoder", conf(encoder_id="grid-flat-v2-visits-shared-s9-r2"), "encoder_id"),
            ("encoder2", conf(encoder_id="grid-flat-v3-s8-r2"), "unknown"),
            (
                "reward",
                conf(world_config={**conf()["world_config"], "reward_id": "rew-x"}),
                "reward_id",
            ),
        ):
            st, out = c.control("configure", run_id="run-c", **bad)
            assert st == 422 and needle in json.dumps(out), (label, st, out)
        assert c.status()["configured_run"] is None  # nothing was applied
        st, out = c.control("configure", run_id="run-c", **conf())
        assert st == 200, out
        s = c.status()
        assert (s["encoder_id"], s["reward_id"], s["learner_schedule_id"]) == (
            ENC, "rew-v1", "sched-t37-v1",
        )  # fmt: skip
        assert s["obs_dim"] == 82 and s["double_dqn"] is True and s["epsilon"] == pytest.approx(1.0)
        assert rt.node.cfg.eps_decay_episodes == 3 and rt.node.cfg.capacity == 50000
        # the node-private validation world runs the same reward and encoder
        assert rt.node.validator.world.reward_id == "rew-v1" and rt.node.validator.enc.id == ENC
    finally:
        rt.stop(False)


def test_legacy_ids_still_configure_and_use_per_act_epsilon(tmp_path):
    rt = Runtime(make_cfg(tmp_path, node_ids=(N1,))).start()
    try:
        c = Client(rt.control_url)
        body = conf(
            learner_schedule_id="sched-v0", encoder_id="grid-flat-v1-s8-r2",
            hyperparameters={**conf()["hyperparameters"], "double_dqn": False, "lr": 0.01,
                             "capacity": 300},
            world_config={**conf()["world_config"], "reward_id": "rew-v0"},
        )  # fmt: skip
        st, out = c.control("configure", run_id="run-c", **body)
        assert st == 200, out
        s = c.status()
        assert (s["encoder_id"], s["reward_id"], s["learner_schedule_id"], s["obs_dim"]) == (
            "grid-flat-v1-s8-r2", "rew-v0", "sched-v0", 28,
        )  # fmt: skip
        assert rt.node.cfg.eps_decay_episodes is None and not rt.node.learner.double
        st, out = c.control("configure", run_id="run-d", **conf(
            hyperparameters={**conf()["hyperparameters"], "double_dqn": True, "lr": 0.01},
            learner_schedule_id="sched-v0"))  # fmt: skip
        assert st == 422 and "double_dqn" in json.dumps(out)
    finally:
        rt.stop(False)


def test_restart_restores_ids_checkpoint_and_node_local_memory(tmp_path):
    cfg = make_cfg(tmp_path, N1, (N1, N2), **t37_over())
    rt = Runtime(cfg).start()
    c = Client(rt.control_url)
    try:
        w = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=40, reward_id="rew-v1")
        o = w.reset(2)["node-0"]
        c.control("reset", run_id="run-c", episode=0, mode="train")
        for t in range(25):
            st, a = c.act("run-c", 0, t, obs_json("run-c", "n", t, o))
            nxt, rew, *_ = w.step({"node-0": a["action"]["command"]})
            o = nxt["node-0"]
            assert c.feedback("run-c", 0, t, rew["node-0"], obs_json("run-c", "n", t + 1, o),
                              cmd=a["action"]["command"])[0] == 200  # fmt: skip
        rt.node.memory.merge_peer(N2, [(1, 1), (2, 2)])
        before = rt.node.memory.state()
        steps, train_ep = rt.node.learner.steps, rt.node.train_ep
        assert c.control("checkpoint", run_id="run-c")[0] == 200
        assert len(before["visits"]) > 3 and before["peer"] == {N2: [[1, 1], [2, 2]]}
    finally:
        rt.stop(False)
    n2 = Node(cfg)  # same volume, same ids: restores everything
    try:
        assert n2.restore_info["restored"] is True and n2.restore_info["memory"] is True
        assert n2.learner.steps == steps and n2.train_ep == train_ep == 0
        assert n2.memory.state() == before
        assert n2.status()["encoder_id"] == ENC and n2.learner.replay["o"].shape == (50000, 82)
        assert np.count_nonzero(n2.learner.replay["o"][: n2.learner.n].any(axis=1)) == 25
    finally:
        n2.close()
    # another encoder / reward id / schedule id on the same volume is refused with the field named
    for over, field in (
        ({"encoder_family": "grid-flat-v2-visits"}, "encoder mismatch"),
        ({"encoder_family": "grid-flat-v1"}, "encoder mismatch"),
        ({"reward_id": "rew-v0"}, "reward_id mismatch"),
    ):
        with pytest.raises(lck.CheckpointError, match=field):
            Node(make_cfg(tmp_path, N1, (N1, N2), **t37_over(**over)))


def test_checkpoint_written_without_the_a18_identity_loads_only_into_the_legacy_recipe():
    legacy = {"encoder": "e", "reward_id": "rew-v0", "node_id": "n"}
    ident = {"node_id": "n", "encoder": "e", "reward_id": "rew-v0",
             "learner_schedule": "sched-v0", "double_dqn": False}  # fmt: skip
    check_identity(legacy, ident)  # an old checkpoint is the legacy recipe: accepted
    with pytest.raises(ValueError, match="learner_schedule mismatch"):
        check_identity(legacy, {**ident, "learner_schedule": "sched-t37-v1"})
    with pytest.raises(ValueError, match="double_dqn mismatch"):
        check_identity(legacy, {**ident, "double_dqn": True})
    with pytest.raises(ValueError, match="reward_id mismatch"):
        check_identity(legacy, {**ident, "reward_id": "rew-v1"})


def test_node_restarted_from_its_run_config_comes_back_under_the_same_ids(tmp_path):
    cfg = make_cfg(tmp_path, N1, (N1,))
    rt = Runtime(cfg).start()
    try:
        assert Client(rt.control_url).control("configure", run_id="run-c", **conf())[0] == 200
        assert Client(rt.control_url).control("checkpoint", run_id="run-c")[0] == 200
    finally:
        rt.stop(False)
    n2 = Node(cfg)
    try:
        s = n2.status()
        assert (s["encoder_id"], s["reward_id"], s["learner_schedule_id"]) == (
            ENC, "rew-v1", "sched-t37-v1",
        )  # fmt: skip
        assert n2.cfg.eps_decay_episodes == 3 and n2.learner.double
    finally:
        n2.close()


# --- node-private validation world under v2 -------------------------------------------------------
def test_validation_world_scores_a_v2_policy_deterministically(tmp_path):
    cfg = make_cfg(tmp_path, N1, (N1, N2), **t37_over(n_validation_agents=2, world_max_ticks=40))
    v = ValidationWorld(cfg)
    rng = np.random.default_rng(0)
    p = {
        "w1": rng.standard_normal((82, 32)).astype(np.float32) * 0.3,
        "b1": np.zeros(32, np.float32),
        "w2": rng.standard_normal((32, 5)).astype(np.float32),
        "b2": np.zeros(5, np.float32),
    }
    s1, s2 = v.evaluate(p), v.evaluate(p)
    assert np.isfinite(s1) and s1 == s2
    assert v.world.reward_id == "rew-v1" and v.episodes_run == 4


# --- the node reads no privileged world state ---------------------------------------
def test_node_side_encoding_and_memory_never_import_the_simulator():
    """The v2 observation is built from the node's own observations and received summaries only:
    the modules that build it (and the node's act/feedback path) do not import the world."""
    import ast
    from pathlib import Path

    import archipelago_learning.encoders as enc_mod
    import archipelago_learning.visits as visits_mod
    import archipelago_noderuntime.encoder as adapter_mod
    import archipelago_noderuntime.node as node_mod
    import archipelago_noderuntime.summary as summary_mod

    for mod in (enc_mod, visits_mod, adapter_mod, node_mod, summary_mod):
        tree = ast.parse(Path(mod.__file__).read_text())
        names = {
            n.module if isinstance(n, ast.ImportFrom) else a.name
            for n in ast.walk(tree)
            if isinstance(n, ast.Import | ast.ImportFrom)
            for a in (n.names if isinstance(n, ast.Import) else [None])
        }
        assert not [x for x in names if x and "archipelago_sim" in x], (mod.__name__, names)

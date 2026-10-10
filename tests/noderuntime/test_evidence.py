"""A7 telemetry semantics, A8 peer trust at the node, A1 in the in-memory LearnerNode wrapper."""

import json

import numpy as np
from archipelago_learner import LearnerNode
from archipelago_learning import TorchLearner, encode
from archipelago_noderuntime.runtime import Runtime
from archipelago_noderuntime.telemetry import MAX_EVENTS, MAX_REQUEST_BYTES, Shipper, Spool
from archipelago_peer import post
from archipelago_sim.env import GridWorld
from archipelago_transport import Envelope, Network
from support import PEER_TOKEN, Client, Cluster, FakeSink, MiniCoordinator, make_cfg, obs_json
from test_peers import N1, N2, load, mover_policy, stay_policy
from test_telemetry import line, wait_until


def spooled(cfg):
    out = []
    for p in sorted((cfg.checkpoint_dir / "telemetry").glob("seg-*.jsonl")):
        out += [json.loads(x)["record"] for x in p.read_text().splitlines()]
    return out


def test_sim_tick_is_the_global_index_episode_times_max_ticks_plus_tick(tmp_path):
    rt = Runtime(make_cfg(tmp_path, node_ids=(N1,), update_every=3)).start()  # max_ticks = 40
    try:
        c = Client(rt.control_url)
        o = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=500).reset(1)["node-0"]
        coord = MiniCoordinator({N1: c})
        coord.run_episode(0, seed=2, ticks=10)
        c.control("reset", run_id="run-t", episode=2)
        st, out = c.act("run-t", 2, 5, obs_json("run-t", "n", 5, o))
        assert st == 200 and out["action"]["sim_tick"] == 2 * 40 + 5
        n_before = len(spooled(rt.cfg))
        for t in range(6, 20):
            a = c.act("run-t", 2, t, obs_json("run-t", "n", t, o))[1]
            c.feedback("run-t", 2, t, 0.1, obs_json("run-t", "n", t + 1, o), cmd="stay")
            assert a["action"]["sim_tick"] == 80 + t
        c.episode_end(2, 20)
        later = spooled(rt.cfg)[n_before:]
        assert later and all(r["sim_tick"] >= 80 for r in later)  # not episode-local ticks
        assert max(r["sim_tick"] for r in later) <= 80 + 20
    finally:
        rt.stop(False)


def test_decision_evidence_rides_as_metric_samples_with_unit_and_phase(tmp_path):
    c = Cluster(tmp_path, (N1, N2), lr=1e-6, validation_max_ticks=40, peer_margin=0.05, hidden=32)
    try:
        load(c.node(N1), mover_policy())
        load(c.node(N2), stay_policy())
        MiniCoordinator(c.clients).reset(0)
        c.clients[N1].episode_end(0, 0)
        c.clients[N2].episode_end(0, 0)
        recs = spooled(c.node(N2).cfg)
        metrics = {r["metric"]: r for r in recs if r["kind"] == "metric_sample"}
        sec = metrics["peer_validation_seconds"]
        assert sec["unit"] == "s" and sec["value"] > 0 and sec["phase"] in ("train", "partition")
        assert metrics["peer_validation_evaluations"]["value"] == 4
        assert metrics["peer_validation_evaluations"]["unit"] == "count"
        assert metrics["peer_candidate_margin"]["value"] > 0.05
        ev = next(r for r in recs if r["kind"] == "learning_event" and r["transfer"] == "accepted")
        assert f"source={N1}" in ev["reason"] and "sha256=" in ev["reason"]  # stays in the reason
    finally:
        c.close()


def test_peer_endpoint_needs_the_token_and_a_declared_sender(tmp_path):
    c = Cluster(tmp_path, (N1, N2))
    try:
        url = c.runtimes[N2].peer_url
        donor = TorchLearner(N1, 28, 5, hidden=32, seed=3)
        env = Envelope.make(N1, N2, 1, encode(donor))
        assert post(url, env) == 401  # no bearer
        assert post(url, env, token="wrong-token-wrong-token") == 401
        assert post(url, Envelope.make("node-99", N2, 2, b"x"), token=PEER_TOKEN) == 403
        assert post(url, Envelope.make(N2, N2, 3, b"x"), token=PEER_TOKEN) == 403  # itself
        assert c.node(N2).peer.receive() is None  # none of that queued anything
        assert post(url, env, token=PEER_TOKEN) == 200
        assert c.node(N2).peer.receive().src == N1
    finally:
        c.close()


def test_shipper_respects_the_ingest_request_limits(tmp_path):
    sink = FakeSink()
    try:
        sp = Spool(tmp_path / "s", max_records=5000, seg_records=100)
        for i in range(1200):
            sp.append(line(i))
        sh = Shipper(sp, sink.url, "n", "boot0", batch=5000, interval=0.01, timeout=2.0)
        while sh.ship_once():
            pass
        assert len(sink.events) == 1200 and max(n for n, _ in sink.sizes) <= MAX_EVENTS
        # large records: the byte cap, not the count cap, decides the request size
        sp2 = Spool(tmp_path / "big", max_records=5000, seg_records=100)
        for i in range(120):
            rec = line(i)
            rec["record"]["pad"] = "x" * 6000
            sp2.append(rec)
        sink.sizes.clear()
        sh2 = Shipper(sp2, sink.url, "n", "boot0", batch=500, interval=0.01, timeout=2.0)
        while sh2.ship_once():
            pass
        assert sp2.backlog == 0 and sum(n for n, _ in sink.sizes) == 120
        assert max(b for _, b in sink.sizes) <= MAX_REQUEST_BYTES + 1024
        assert len(sink.sizes) >= 3
    finally:
        sink.close()


def test_node_ships_through_an_outage_with_the_context_on_every_request(tmp_path):
    sink = FakeSink()
    rt = Runtime(
        make_cfg(tmp_path, node_ids=(N1,), telemetry_url=sink.url, update_every=4, commit="abc123")
    ).start()
    try:
        MiniCoordinator({N1: Client(rt.control_url)}).run_episode(0, seed=3, ticks=20)
        assert wait_until(lambda: rt.node.spool.backlog == 0 and sink.batches > 0)
        for meta in sink.metas:
            assert meta["source"] == N1 and meta["boot_id"] == rt.node.boot_id
            ctx = meta["context"]
            assert ctx["commit"] == "abc123" and ctx["boot_id"] == rt.node.boot_id
            assert ctx["config_hash"] == rt.node.config_hash and ctx["host"]
            assert "seed" in ctx
    finally:
        rt.stop(False)
        sink.close()


# --- A1 in the in-memory LearnerNode wrapper -------------------------------------------------
def test_learnernode_poll_is_one_window_first_acceptance_wins():
    ids = ("node-0", "node-1", "node-2")
    net = Network({(a, b) for a in ids for b in ids if a != b})
    learners = {
        n: TorchLearner(n, 28, 5, hidden=32, seed=i, lr=1e-6) for i, n in enumerate(ids)
    }  # fmt: skip
    nodes = {n: LearnerNode(learners[n], net, peers=[p for p in ids if p != n]) for n in ids}
    learners["node-0"].load_params_numpy(stay_policy())
    nodes["node-1"].broadcast()
    nodes["node-2"].broadcast()
    net.tick()
    calls = []

    def score(p):
        calls.append(1)
        return float(np.sum(p["b2"]))  # any deterministic number: higher is "better"

    window = nodes["node-0"].poll(score, margin=-1e9)  # every candidate would pass the margin
    evs = [e for e in learners["node-0"].events if e["type"] == "peer_offer"]
    assert [e["accepted"] for e in evs] == [True, False]
    assert evs[1]["reason"] == "window_limit" and "validation_seconds" not in evs[1]
    assert window.accepted == 1 and window.offers == 2
    assert len(calls) == 2  # current + first candidate only: the second cost nothing

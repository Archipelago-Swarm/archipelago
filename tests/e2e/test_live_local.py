# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""No-Docker local smoke of the live runtime (agents/architecture/live-runtime.md section 11).

A real coordinator process and four real node-runtime processes talk over localhost HTTP, with temp checkpoint
directories, and run train / validation / test episodes with a cut window. Assertions here are the ones that
must hold with the node runtime as it exists; behaviours that depend on the pending exchange-cadence and
restart amendments (A1-A5) are in test_live_faults.py.
"""

import hashlib
import json
from collections import Counter

import numpy as np
from e2e_procs import NODE_IDS


def test_run_completes_with_every_episode_and_healthy_nodes(smoke):
    c, run_id, view = smoke
    assert view["status"] == "completed", view
    assert [e["kind"] for e in view["episodes_done"]] == ["train", "train", "validation", "test"]
    for n in NODE_IDS:
        assert view["nodes"][n]["health"] == "ready", view["nodes"][n]
        assert view["nodes"][n]["deadline_misses"] == 0


def test_act_feedback_cycle_and_optimizer_updates_ran_in_each_process(smoke):
    c, run_id, view = smoke
    for n in NODE_IDS:
        st = c.node_status(n)
        assert st["backend"] == "torch-cpu" and st["ready"]
        # acts in all 4 episodes (frozen eval included); feedback only in the two train episodes
        assert st["counters"]["acts"] >= 4 * 20, (n, st["counters"])
        assert 0 < st["counters"]["feedbacks"] <= 2 * 80
        assert st["train_steps"] > 0, f"{n} never ran the optimizer"
        assert st["replay_size"] > 0
        assert st["loss_ema"] is not None


def test_actions_come_from_the_node_processes(smoke):
    """The world applied the node's own action: every act the coordinator issued reached its node, none missed."""
    c, run_id, view = smoke
    acts = {n: c.node_status(n)["counters"]["acts"] for n in NODE_IDS}
    assert len(set(acts.values())) <= 2, (
        acts
    )  # same ticks for all (drones may only differ by early termination)
    snaps = [e for e in c.events(run_id) if e["kind"] == "world_snapshot"]
    assert snaps and {n for s in snaps for n in s["poses"]} == set(NODE_IDS)
    moved = {
        n
        for n in NODE_IDS
        if len({(s["poses"][n]["x"], s["poses"][n]["y"]) for s in snaps if n in s["poses"]}) > 1
    }
    assert moved == set(NODE_IDS), "a node's drone never moved: its actions were not applied"


def policy_digest(ckpt_dir):
    """sha256 over the model arrays of the newest checkpoint generation on a node's own volume."""
    root = ckpt_dir / "ckpt"
    cur = json.loads((root / "CURRENT").read_text())
    gen = root / f"gen-{cur['generation']}"
    assert gen.is_dir(), cur
    with np.load(gen / "policy.npz", allow_pickle=False) as z:
        h = hashlib.sha256()
        for k in sorted(z.files):
            h.update(k.encode() + np.ascontiguousarray(z[k]).tobytes())
    return h.hexdigest()


def test_policies_differ_except_where_a_validated_peer_candidate_was_adopted(smoke):
    """Each node trains its own network. After exchange windows a node that accepted a candidate holds the
    sender's weights, so every acceptance can merge at most one node into another."""
    c, run_id, view = smoke
    accepted = sum(c.node_status(n)["counters"]["decisions_accepted"] for n in NODE_IDS)
    status_hashes = {n: c.node_status(n)["policy_sha256"] for n in NODE_IDS}
    assert len(set(status_hashes.values())) >= 4 - accepted, (accepted, status_hashes)
    # same conclusion from the checkpointed arrays on each node's own volume
    for n in NODE_IDS:
        code, _ = c.checkpoint(n, "e2e-smoke")
        assert code == 200
    digests = {n: policy_digest(c.ckpt_dir(n)) for n in NODE_IDS}
    assert len(set(digests.values())) >= 4 - accepted, (accepted, digests)


def test_isolated_nodes_end_with_distinct_policies(make_cluster):
    """A16 'distinct per-node policy': same-seed init plus different data, no exchange possible (every link cut
    for the whole run), so the four parameter hashes must all differ."""
    c = make_cluster(ticks=40)
    all_pairs = [[a, b] for i, a in enumerate(NODE_IDS) for b in NODE_IDS[i + 1 :]]
    c.start_run(
        "isolated",
        episodes=[{"kind": "train", "seed": 51}],
        fault_schedule=[{"start_tick": 0, "end_tick": 40, "cut_links": all_pairs}],
        seed=7,
    )
    assert c.wait_run("isolated")["status"] == "completed"
    counters = {n: c.node_status(n)["counters"] for n in NODE_IDS}
    assert all(k["offers_sent"] == 0 and k["decisions_accepted"] == 0 for k in counters.values()), (
        counters
    )
    hashes = {n: c.node_status(n)["policy_sha256"] for n in NODE_IDS}
    assert len(set(hashes.values())) == 4, hashes
    assert all(c.node_status(n)["train_steps"] > 0 for n in NODE_IDS)
    for n in NODE_IDS:
        assert c.checkpoint(n, "isolated")[0] == 200
    assert len({policy_digest(c.ckpt_dir(n)) for n in NODE_IDS}) == 4


def test_telemetry_spool_is_written_and_shipped(smoke):
    c, run_id, view = smoke
    for n in NODE_IDS:
        segs = sorted((c.ckpt_dir(n) / "telemetry").glob("seg-*.jsonl"))
        assert segs, f"{n} wrote no telemetry spool"
        lines = [json.loads(x) for s in segs for x in s.read_text().splitlines() if x.strip()]
        assert lines and all({"event_id", "record"} <= set(x) for x in lines)
        kinds = Counter(x["record"]["kind"] for x in lines)
        assert kinds["learning_event"] > 0 and kinds["metric_sample"] > 0, (n, kinds)
        ids = [x["event_id"] for x in lines]
        assert len(ids) == len(set(ids)), "duplicate event ids in one spool"
        assert all(x["record"]["source_node_id"] == n for x in lines)
    # the shipper delivered batches to the sink with the bearer token, and nothing unauthorized got through
    assert c.sink.unauthorized == 0
    shipped = {n: c.sink.records(n) for n in NODE_IDS}
    assert all(shipped[n] for n in NODE_IDS)


def test_coordinator_stream_carries_canonical_world_and_metric_records(smoke):
    c, run_id, view = smoke
    events = c.events(run_id)
    kinds = Counter(e["kind"] for e in events)
    assert kinds["world_snapshot"] > 0 and kinds["metric_sample"] > 0
    assert {e["kind"] for e in events} <= {"world_snapshot", "metric_sample"}
    seqs = [e["sequence"] for e in events]
    assert seqs == sorted(set(seqs)), "event sequences must be unique and increasing"
    phases = {e["phase"] for e in events if e["kind"] == "metric_sample"}
    assert {"train", "eval"} <= phases
    cov = [e["coverage"] for e in events if e["kind"] == "world_snapshot"]
    assert max(cov) > 0


def test_unauthenticated_calls_are_refused_by_both_services(smoke):
    from e2e_procs import http

    c, _, _ = smoke
    assert http("GET", c.node_url("node-01") + "/v1/status", "wrong-token-0123456789")[0] == 401
    assert http("GET", c.coord_url + "/v1/runs/e2e-smoke", "wrong-token-0123456789")[0] in (
        401,
        403,
    )
    assert http("GET", c.node_url("node-01") + "/healthz")[0] == 200

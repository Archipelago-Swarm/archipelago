"""Two or three REAL runtime instances exchanging candidates over localhost HTTP."""

import numpy as np
import pytest
from archipelago_noderuntime.validation import ValidationWorld
from support import Cluster, MiniCoordinator, make_cfg

N1, N2, N3 = "node-01", "node-02", "node-03"
OVR = dict(lr=1e-6, validation_max_ticks=40, peer_margin=0.05, hidden=32)
CUT_ALL = [{"start_tick": 0, "end_tick": 100000, "cut_links": [[N1, N2]]}]


def stay_policy(obs_dim=28, hidden=32):
    """Always 'stay': a genuinely poor policy (pays step cost, discovers nothing)."""
    p = {
        "w1": np.zeros((obs_dim, hidden), np.float32),
        "b1": np.zeros(hidden, np.float32),
        "w2": np.zeros((hidden, 5), np.float32),
        "b2": np.zeros(5, np.float32),
    }
    p["b2"][0] = 1.0
    return p


def mover_policy(order=(2, 3, 1, 4), obs_dim=28, hidden=32):
    """Moves to a free neighbour (crop value 0), preferring directions in `order`.

    Hidden units relu(v), relu(-v) of each neighbour cell make Q(move)=1-|v|: free cells score 1,
    walls and out-of-bounds 0; stay scores 0.5. A genuinely better explorer than 'stay'.
    """
    cell = {1: 7, 2: 13, 3: 17, 4: 11}  # action -> crop index of that neighbour (5x5, row-major)
    p = stay_policy(obs_dim, hidden)
    p["b2"][:] = 0.0
    p["b2"][0] = 0.5
    for k, a in enumerate((1, 2, 3, 4)):
        p["w1"][cell[a], 2 * k] = 1.0
        p["w1"][cell[a], 2 * k + 1] = -1.0
        p["w2"][2 * k, a] = p["w2"][2 * k + 1, a] = -1.0
        p["b2"][a] = 1.0 + 0.01 * (len(order) - order.index(a))
    return p


def load(node, params):
    node.learner.load_params_numpy(params)
    node.learner.sync_target()


def score(tmp_path, params):
    cfg = make_cfg(tmp_path, N1, (N1, N2), **OVR)
    return ValidationWorld(cfg).evaluate(params)


@pytest.fixture()
def pair(tmp_path):
    c = Cluster(tmp_path, (N1, N2), **OVR)
    yield c
    c.close()


def test_controlled_policies_really_differ_in_quality(tmp_path):
    good, bad = score(tmp_path, mover_policy()), score(tmp_path, stay_policy())
    assert good > bad + 1.0  # the donor used below is genuinely better, measured not assumed


def test_cut_link_carries_zero_offers_then_open_link_decides_with_reasons(pair, tmp_path):
    a, b = pair.node(N1), pair.node(N2)
    load(a, mover_policy())
    load(b, stay_policy())
    coord = MiniCoordinator(pair.clients)
    seen = []
    orig = b.validator.world.reset
    b.validator.world.reset = lambda seed, *x, **k: (seen.append(seed), orig(seed, *x, **k))[1]

    # --- window 1: the link is cut for the whole episode; local training must continue -------
    steps0 = (a.learner.steps, b.learner.steps)
    coord.run_episode(0, seed=3, ticks=30, schedule=CUT_ALL, end=True)
    for n, s0 in ((a, steps0[0]), (b, steps0[1])):
        assert n.learner.steps > s0 + 15  # local updates continued while partitioned
        c = n.counters
        assert c["offers_sent"] == 0 and c["offers_cut"] == 1
        assert c["offers_received"] == 0 and c["decisions_accepted"] + c["decisions_rejected"] == 0
    assert pair.clients[N1].status()["peers"] == {N2: "cut"}
    assert b.last_exchange["cut"] == [N1] and b.last_exchange["decisions"] == []
    assert b.peer.receive() is None  # nothing was ever queued from the cut peer

    # --- window 2: the cut has ended; offers flow and decisions are recorded ----------------
    steps_before_window = b.learner.steps
    open_after_10 = [{"start_tick": 0, "end_tick": 10, "cut_links": [[N1, N2]]}]
    coord.run_episode(1, seed=4, ticks=30, schedule=open_after_10)
    pair.clients[N1].episode_end(1, 30)  # A offers its mover policy to B
    assert a.counters["offers_sent"] == 1
    mover_sha = pair.clients[N1].status()["policy_sha256"]
    steps_b = b.learner.steps
    pair.clients[N2].episode_end(1, 30)  # B validates, accepts, and offers its own
    dec = b.last_exchange["decisions"]
    assert len(dec) == 1 and dec[0]["accepted"] is True and dec[0]["source"] == N1
    assert dec[0]["candidate_score"] > dec[0]["current_score"] + 0.05
    assert dec[0]["validation_seconds"] > 0 and dec[0]["evaluations"] == 4  # 2 policies x 2 seeds
    assert b.learner.steps == steps_b  # validation ran no optimizer updates
    assert steps_b > steps_before_window
    assert pair.clients[N2].status()["policy_sha256"] == mover_sha  # B now runs A's policy
    assert b.learner.version > 0 and b.learner.previous is not None  # rollback copy kept
    assert set(seen) == {7001, 7002}  # only the configured validation seeds, ever

    # --- window 3: A now judges B's earlier (stay) offer and rejects it with a reason -------
    coord.run_episode(2, seed=5, ticks=10, schedule=[])
    pair.clients[N1].episode_end(2, 10)
    rej = [d for d in a.last_exchange["decisions"] if d["source"] == N2]
    assert len(rej) == 1 and rej[0]["accepted"] is False
    assert rej[0]["reason"] == "candidate not better than current policy"
    assert rej[0]["candidate_score"] < rej[0]["current_score"]
    assert a.counters["decisions_rejected"] == 1

    # the decisions are also canonical telemetry events with reasons
    import json

    def learning(node):
        out = []
        for p in sorted((node.cfg.checkpoint_dir / "telemetry").glob("seg-*.jsonl")):
            out += [json.loads(x)["record"] for x in p.read_text().splitlines()]
        return [r for r in out if r["kind"] == "learning_event" and r["transfer"] != "none"]

    acc, rej_ev = learning(b), learning(a)
    assert [e["transfer"] for e in acc] == ["accepted"] and N1 in acc[0]["reason"]
    assert "sha256=" in acc[0]["reason"] and acc[0]["wall_seconds"] > 0
    assert [e["transfer"] for e in rej_ev] == ["rejected"]
    assert (
        "not better" in rej_ev[0]["reason"]
        and rej_ev[0]["new_version"] == rej_ev[0]["previous_version"]
    )


def test_receiver_enforces_the_cut_even_if_the_sender_does_not(pair):
    a, b = pair.node(N1), pair.node(N2)
    load(a, mover_policy())
    coord = MiniCoordinator(pair.clients)
    coord.reset(0)
    pair.clients[N2].control("set_schedule", fault_schedule=CUT_ALL)  # only B knows about the cut
    st, _ = pair.clients[N1].episode_end(0, 0)
    assert st == 202
    assert a.last_exchange["refused"] == [[N2, 403]] and a.counters["offers_sent"] == 0
    assert b.counters["received_cut"] >= 1 and b.peer.receive() is None
    pair.clients[N2].episode_end(0, 0)
    assert b.counters["offers_received"] == 0 and b.counters["decisions_accepted"] == 0


def test_sender_enforces_the_cut_even_if_the_receiver_does_not(pair):
    a, b = pair.node(N1), pair.node(N2)
    MiniCoordinator(pair.clients).reset(0)
    pair.clients[N1].control("set_schedule", fault_schedule=CUT_ALL)  # only A knows
    pair.clients[N1].episode_end(0, 0)
    assert a.counters["offers_cut"] == 1 and a.counters["offers_sent"] == 0
    assert b.peer.receive() is None and b.counters["received_cut"] == 0  # never even arrived


def test_incompatible_candidate_is_rejected_with_a_named_reason(tmp_path):
    c = Cluster(tmp_path, (N1, N2), per_node={N2: {"hidden": 16}}, **{**OVR, "hidden": 32})
    try:
        MiniCoordinator(c.clients).reset(0)
        c.clients[N2].episode_end(0, 0)  # offers hidden=16 to N1
        c.clients[N1].episode_end(0, 0)
        (d,) = c.node(N1).last_exchange["decisions"]
        assert d["accepted"] is False and d["reason"] == "incompatible hidden: 16"
        assert d["evaluations"] == 0 and c.node(N1).learner.version == 0
        assert c.node(N1).counters["decisions_rejected"] == 1
    finally:
        c.close()


def test_window_accepts_the_first_arrival_in_order_and_the_rest_hit_window_limit(tmp_path):
    """A1: arrival order, at most one acceptance, the rest rejected as window_limit for free."""
    c = Cluster(tmp_path, (N1, N2, N3), **OVR)
    try:
        p2, p3 = mover_policy((2, 3, 1, 4)), mover_policy((4, 1, 3, 2))
        load(c.node(N1), stay_policy())
        load(c.node(N2), p2)
        load(c.node(N3), p3)
        MiniCoordinator(c.clients).reset(0)
        s2, s3 = score(tmp_path, p2), score(tmp_path, p3)
        assert s2 > 1.0 and s3 > 1.0 and s2 != s3
        c.clients[N3].episode_end(0, 0)  # node-03's offer arrives FIRST ...
        c.clients[N2].episode_end(0, 0)  # ... then node-02's
        c.clients[N1].episode_end(0, 0)
        dec = c.node(N1).last_exchange["decisions"]
        assert [d["source"] for d in dec] == [N3, N2]  # arrival order, not sorted, not best-first
        assert [d["accepted"] for d in dec] == [True, False]
        late = dec[1]
        assert late["reason"] == "window_limit"
        assert late["evaluations"] == 0 and late["validation_seconds"] == 0.0  # no cost spent
        assert dec[0]["evaluations"] == 4  # current + first candidate, 2 seeds each
        assert c.node(N1).counters["decisions_accepted"] == 1
        assert c.node(N1).counters["decisions_window_limit"] == 1
        assert c.node(N1).last_exchange["evaluations"] == 4
    finally:
        c.close()


def test_unchanged_policy_is_not_reoffered_and_duplicates_are_not_revalidated(pair):
    a, b = pair.node(N1), pair.node(N2)
    load(a, mover_policy())
    MiniCoordinator(pair.clients).reset(0)
    coord = MiniCoordinator(pair.clients)
    pair.clients[N1].episode_end(0, 0)
    coord.reset(1)
    pair.clients[N1].episode_end(1, 0)  # nothing changed since the last offer
    assert a.counters["offers_sent"] == 1 and a.counters["offers_unchanged"] == 1
    pair.clients[N2].episode_end(1, 0)
    assert b.counters["decisions_accepted"] + b.counters["decisions_rejected"] == 1
    coord.reset(2)
    pair.clients[N2].episode_end(2, 0)  # the same envelope is never re-validated
    assert b.counters["decisions_accepted"] + b.counters["decisions_rejected"] == 1


def test_eval_mode_episode_end_does_not_exchange(pair):
    a = pair.node(N1)
    load(a, mover_policy())
    MiniCoordinator(pair.clients).reset(0, mode="eval")
    st, out = pair.clients[N1].episode_end(0, 0)
    assert st == 202
    assert a.last_exchange["skipped"] == "eval_mode"
    assert a.counters["offers_sent"] == 0 and a.counters["exchanges"] == 0
    assert a.checkpoint_generation == 1  # A17: the episode_end generation is still written


def test_mixing_mode_blends_and_gates_on_the_blend(tmp_path):
    c = Cluster(tmp_path, (N1, N2), **{**OVR, "mode": "mixing", "mix_alpha": 0.5})
    try:
        donor, mine = mover_policy(), stay_policy()
        load(c.node(N1), donor)
        load(c.node(N2), mine)
        MiniCoordinator(c.clients).reset(0)
        c.clients[N1].episode_end(0, 0)
        c.clients[N2].episode_end(0, 0)
        blend = {k: ((1 - 0.5) * mine[k] + 0.5 * donor[k]).astype(np.float32) for k in mine}
        want_accept = score(tmp_path, blend) > score(tmp_path, mine) + 0.05
        (d,) = c.node(N2).last_exchange["decisions"]
        assert d["accepted"] is want_accept
        assert d["candidate_score"] == pytest.approx(score(tmp_path, blend))  # the BLEND was judged
        got = c.node(N2).learner.params_numpy()
        expect = blend if want_accept else mine
        for k in expect:
            np.testing.assert_allclose(got[k], expect[k], atol=1e-6)
    finally:
        c.close()


def test_information_only_mode_never_loads_parameters(tmp_path):
    c = Cluster(tmp_path, (N1, N2), **{**OVR, "mode": "information_only"})
    try:
        load(c.node(N1), mover_policy())
        load(c.node(N2), stay_policy())
        MiniCoordinator(c.clients).reset(0)
        c.clients[N1].episode_end(0, 0)
        before = c.clients[N2].status()["policy_sha256"]
        c.clients[N2].episode_end(0, 0)
        (d,) = c.node(N2).last_exchange["decisions"]
        assert d["accepted"] is False and "information_only" in d["reason"]
        assert c.clients[N2].status()["policy_sha256"] == before
    finally:
        c.close()

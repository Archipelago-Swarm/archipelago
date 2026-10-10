"""A1 cadence windows, A2 feedback semantics, A3 identity, A4 episode_end/reset, A5 configure.

Two or more REAL runtime instances (HTTP on localhost) in one test process. Cross-node ordering is
made deterministic by the coordinator waiting for a node's window before the next node acts; no
assertion depends on wall-clock speed except explicit lower bounds on waits.
"""

import json
import re
import threading
import time

import pytest
from archipelago_noderuntime.encoder import ACTIONS
from archipelago_noderuntime.node import ApiError, Node
from archipelago_noderuntime.protocol import ActRequest, FeedbackRequest
from archipelago_noderuntime.runtime import Runtime
from archipelago_sim.env import GridWorld
from support import Blackhole, Client, Cluster, MiniCoordinator, make_cfg, obs_json
from test_peers import N1, N2, load, mover_policy, stay_policy

CAD = dict(lr=1e-3, validation_max_ticks=30, peer_margin=0.0, hidden=32, exchange_every_ticks=10)


def windows(node):
    """Finished windows of a node in (tick, final) order."""
    rs = [r for r in node.results.values() if "tick" in r]
    return sorted(rs, key=lambda r: (r["tick"], r["final"]))


# --- A1: tick cadence + scheduled partition ----------------------------------------------------
def test_cadence_windows_follow_node_ticks_and_a_scheduled_partition_cuts_them(tmp_path):
    c = Cluster(tmp_path, (N1, N2), **CAD)
    try:
        a, b = c.node(N1), c.node(N2)
        sched = [{"start_tick": 15, "end_tick": 35, "cut_links": [[N1, N2]]}]
        n = MiniCoordinator(c.clients, max_ticks=500).run_episode(
            0, seed=3, ticks=45, schedule=sched, end=True, cadence=10
        )
        assert n == 45
        for node, other in ((a, N2), (b, N1)):
            rs = windows(node)
            # windows fire on the node's OWN tick counter at multiples of 10, plus the final one
            assert [(r["tick"], r["final"]) for r in rs] == [
                (10, False), (20, False), (30, False), (40, False), (45, True)
            ]  # fmt: skip
            by = {r["tick"]: r for r in rs}
            for t in (20, 30):  # inside the cut: the link carries zero offers, both directions
                assert by[t]["cut"] == [other] and by[t]["sent"] == [] and by[t]["decisions"] == []
            for t in (10, 40, 45):  # outside the cut the offer is sent
                assert by[t]["cut"] == [] and by[t]["sent"] == [other]
            steps = [r["train_steps"] for r in rs]
            assert steps == sorted(set(steps))  # local training continued through every window
            assert steps[3] > steps[1] + 15  # ... in particular across the cut (windows 20 -> 40)
            assert node.counters["offers_cut"] == 2 and node.counters["offers_sent"] == 3
        # receiving side: node-02 judged exactly the offers that crossed an OPEN link
        got = {r["tick"]: r["decisions"] for r in windows(b)}
        assert [t for t, d in got.items() if d] == [10, 40, 45]
        assert all(len(d) == 1 and d[0]["source"] == N1 for d in got.values() if d)
        # node-01's inbox held node-02's tick-10 offer when the cut began: it is dropped, not judged
        assert a.counters["received_cut"] == 1
        # ... and the only offer it judged is node-02's tick-40 one, in its final window
        assert [(r["tick"], len(r["decisions"])) for r in windows(a) if r["decisions"]] == [(45, 1)]
        assert b.counters["offers_received"] == 3 and a.counters["offers_received"] == 2
        # the final window (A4/A17) also wrote a generation
        assert windows(a)[-1]["checkpoint"] == a.checkpoint_generation >= 1
    finally:
        c.close()


def test_cadence_is_driven_by_acts_only_not_by_duplicates_eval_or_tick_zero(tmp_path):
    rt = Runtime(make_cfg(tmp_path, node_ids=(N1,), exchange_every_ticks=5)).start()
    try:
        node, c = rt.node, Client(rt.control_url)
        w = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=500)
        o = w.reset(1)["node-0"]
        c.control("reset", run_id="run-w", episode=0)
        for t in range(13):
            assert c.act("run-w", 0, t, obs_json("run-w", "n", t, o))[0] == 200
            assert c.wait_idle()
        assert c.act("run-w", 0, 5, obs_json("run-w", "n", 5, o))[0] == 200  # duplicate act
        assert c.wait_idle()
        assert [r["tick"] for r in windows(node)] == [5, 10]  # not 0, not twice for tick 5
        c.control("reset", run_id="run-w", episode=1, mode="eval")  # eval freezes: no windows
        for t in range(12):
            assert c.act("run-w", 1, t, obs_json("run-w", "n", t, o))[0] == 200
        assert c.wait_idle() and len(windows(node)) == 2
        c.control("reset", run_id="run-w", episode=2)
        for t in range(6):
            c.act("run-w", 2, t, obs_json("run-w", "n", t, o))
        assert c.wait_idle()
        assert [r["tick"] for r in windows(node)] == [5, 5, 10]  # a new episode counts afresh
    finally:
        rt.stop(False)


def test_cadence_window_never_runs_in_the_act_path(tmp_path):
    hole = Blackhole()
    cfg = make_cfg(tmp_path, N1, (N1, N2), exchange_every_ticks=5, peer_timeout=30.0)
    rt = Runtime(cfg)
    rt.set_peer_urls({N2: hole.url})
    rt.start()
    try:
        node, c = rt.node, Client(rt.control_url)
        w = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=500)
        o = w.reset(1)["node-0"]
        c.control("reset", run_id="run-w", episode=0)
        for t in range(6):
            assert c.act("run-w", 0, t, obs_json("run-w", "n", t, o))[0] == 200
        deadline = time.time() + 30
        while hole.accepted == 0 and time.time() < deadline:
            time.sleep(0.01)
        assert hole.accepted == 1 and node.window_state == "running"  # stuck on the peer ...
        for t in range(6, 60):  # ... while 54 further acts are answered
            assert c.act("run-w", 0, t, obs_json("run-w", "n", t, o))[0] == 200
        assert node.window_state == "running" and node.counters["acts"] == 60
        assert len(node._jobs) >= 1  # the later cadence windows queue behind the stuck one
    finally:
        rt.stop(False)
        hole.close()


# --- A4: episode_end is 202, reset cancels a window that outlives its wait --------------------
def test_episode_end_is_202_idempotent_and_checked_against_the_node_state(tmp_path):
    c = Cluster(tmp_path, (N1, N2), **CAD)
    try:
        MiniCoordinator(c.clients).reset(3)
        cl = c.clients[N1]
        st, out = cl.control("episode_end", episode=3, tick=0)
        assert st == 202 and re.fullmatch(rf"{N1}-[0-9a-f]{{8}}-e3", out["window_id"])
        cl.wait_idle()
        st2, out2 = cl.control("episode_end", episode=3, tick=0)  # a retried call
        assert st2 == 202 and out2["window_id"] == out["window_id"]
        assert c.node(N1).counters["exchanges"] == 1  # the retry did not run a second window
        assert cl.control("episode_end", episode=2, tick=0)[0] == 409  # not the node's episode
        assert cl.control("episode_end", run_id="run-other", episode=3, tick=0)[0] == 409
        st = cl.status()
        assert st["last_window_id"] == out["window_id"] and st["window"] == "idle"
        assert (
            cl.call(
                "POST",
                "/v1/control",
                {
                    "command": "episode_end",
                    "run_id": "run-t",
                    "episode": 3,
                    "tick": 0,
                    "wait": True,
                },
            )[0]
            == 422
        )
    finally:
        c.close()


def test_reset_waits_then_cancels_a_stuck_window_and_records_window_cancelled(tmp_path):
    hole = Blackhole()
    cfg = make_cfg(tmp_path, N1, (N1, N2), peer_timeout=60.0, window_cancel_wait=0.4)
    rt = Runtime(cfg)
    rt.set_peer_urls({N2: hole.url})
    rt.start()
    try:
        node, c = rt.node, Client(rt.control_url)
        coord = MiniCoordinator({N1: c})
        coord.run_episode(0, seed=2, ticks=12)
        st, out = c.control("episode_end", episode=0, tick=12)
        assert st == 202
        deadline = time.time() + 30
        while hole.accepted == 0 and time.time() < deadline:
            time.sleep(0.01)
        assert hole.accepted == 1 and node.window_state == "running"
        t0 = time.perf_counter()
        assert c.control("reset", run_id="run-t", episode=1)[0] == 200
        waited = time.perf_counter() - t0
        assert waited >= 0.4  # it did wait for the running window first (lower bound only)
        assert node.window_state == "idle"  # ... and then cancelled it
        res = node.results[out["window_id"]]
        assert res["cancelled"] is True
        assert node.counters["windows_cancelled"] == 1
        names = [
            rec["record"]["metric"]
            for p in sorted((cfg.checkpoint_dir / "telemetry").glob("seg-*.jsonl"))
            for rec in map(json.loads, p.read_text().splitlines())
            if rec["record"]["kind"] == "metric_sample"
        ]
        assert "window_cancelled" in names
        assert (
            c.act(
                "run-t",
                1,
                0,
                obs_json(
                    "run-t",
                    "n",
                    0,
                    GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=500).reset(1)["node-0"],
                ),
            )[0]
            == 200
        )
    finally:
        rt.stop(False)
        hole.close()


def test_reset_does_not_cancel_a_window_that_finishes_within_its_wait(tmp_path):
    c = Cluster(tmp_path, (N1, N2), **{**CAD, "window_cancel_wait": 30.0})
    try:
        coord = MiniCoordinator(c.clients)
        load(c.node(N1), mover_policy())
        coord.run_episode(0, seed=2, ticks=12)
        st, out = c.clients[N1].control("episode_end", episode=0, tick=12)
        assert st == 202
        coord.reset(1)  # returns only once the window is done (it was quick)
        res = c.node(N1).results[out["window_id"]]
        assert "cancelled" not in res and res["sent"] == [N2] and res["checkpoint"] >= 1
        assert c.node(N1).counters["windows_cancelled"] == 0
    finally:
        c.close()


def test_a_cancelled_window_never_applies_its_candidate(tmp_path):
    entered, release = threading.Event(), threading.Event()
    cfg = make_cfg(tmp_path, N2, (N1, N2), lr=1e-6, peer_margin=0.05, window_cancel_wait=0.2)
    rt = Runtime(cfg).start()
    try:
        node, c = rt.node, Client(rt.control_url)
        load(node, stay_policy())
        real = node.validator.evaluate

        def parked(params, cancel=None):
            entered.set()
            assert release.wait(60)
            return real(params, cancel)

        node.validator.evaluate = parked
        MiniCoordinator({N2: c}).reset(0)
        donor = Cluster(tmp_path / "donor", (N1, N2), lr=1e-6, hidden=32)
        try:
            load(donor.node(N1), mover_policy())
            donor.node(N1).peer_urls = {N2: rt.peer_url}
            MiniCoordinator(donor.clients).reset(0)
            donor.clients[N1].episode_end(0, 0)
        finally:
            donor.close()
        before = (node.learner.version, node.status()["policy_sha256"])
        st, out = c.control("episode_end", episode=0, tick=0)
        assert st == 202 and entered.wait(30)
        assert c.control("reset", run_id="run-t", episode=1)[0] == 200  # cancels after 0.2 s
        release.set()  # the parked validation now finishes: it must not apply anything
        assert node.wait_idle(60)
        assert node.results[out["window_id"]]["cancelled"] is True
        assert (node.learner.version, node.status()["policy_sha256"]) == before
        assert node.counters["decisions_accepted"] == 0
    finally:
        release.set()
        rt.stop(False)


# --- A2: feedback carries what was executed; barrier; snapshot before the response -------------
def _node(tmp_path, **over):
    return Node(make_cfg(tmp_path, node_ids=(N1,), **over))


def _areq(tick, obs, run="run-a", ep=0, deadline_ms=500):
    return ActRequest.model_validate(
        {"run_id": run, "episode": ep, "tick": tick, "deadline_ms": deadline_ms,
         "observation": obs_json(run, "n", tick, obs)}
    )  # fmt: skip


def _freq(tick, obs, cmd, run="run-a", ep=0, missed=False, idx=None):
    return FeedbackRequest.model_validate(
        {"run_id": run, "episode": ep, "tick": tick, "reward": 0.25, "terminated": False,
         "next_observation": obs_json(run, "n", tick + 1, obs), "executed_command": cmd,
         "action_index": ACTIONS.index(cmd) if idx is None else idx, "deadline_missed": missed}
    )  # fmt: skip


@pytest.fixture()
def world_obs():
    return GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=1000).reset(1)["node-0"]


def test_node_trains_on_the_executed_command_and_a_fallback_stay_is_stay(tmp_path, world_obs):
    node = _node(tmp_path, eps_start=0.0, eps_end=0.0)
    try:
        for t in range(6):
            chosen = node.act(_areq(t, world_obs))["action"]["command"]
            executed = "stay" if t % 2 else "north"  # the world did not execute what was chosen
            out = node.feedback(_freq(t, world_obs, executed, missed=bool(t % 2)))
            assert out["accepted"] is True
            i = (node.learner.n - 1) % node.learner.capacity
            assert int(node.learner.replay["a"][i]) == ACTIONS.index(executed)
            assert chosen in ACTIONS
        assert node.counters["feedback_deadline_missed"] == 3
        # a feedback whose index disagrees with its command is a client bug, not training data
        node.act(_areq(6, world_obs))
        with pytest.raises(ApiError) as e:
            node.feedback(_freq(6, world_obs, "east", idx=1))
        assert e.value.status == 422 and e.value.code == "bad_action"
        assert node.learner.n == 6
    finally:
        node.close()


def test_deadline_missed_without_an_act_is_acknowledged_but_stores_nothing(tmp_path, world_obs):
    node = _node(tmp_path)
    try:
        node.act(_areq(0, world_obs))
        out = node.feedback(_freq(1, world_obs, "stay", missed=True))  # act(1) never arrived
        assert out["accepted"] is False and node.learner.n == 0
        with pytest.raises(ApiError) as e:
            node.feedback(_freq(2, world_obs, "stay", missed=False))  # not a miss: a real error
        assert e.value.status == 409 and e.value.code == "unknown_step"
    finally:
        node.close()


def test_feedback_publishes_its_snapshot_before_answering_and_act_sees_it(tmp_path, world_obs):
    from archipelago_noderuntime.validation import params_digest

    node = _node(tmp_path, eps_start=0.0, eps_end=0.0)
    try:
        for t in range(12):  # past batch=8: every feedback now makes an optimizer step
            node.act(_areq(t, world_obs))
            out = node.feedback(_freq(t, world_obs, "stay"))
        v = out["policy_version"]
        assert v == node.learner.version > 0
        # the inference snapshot act reads IS the trained policy, not the previous step's
        assert params_digest(node.learner._published) == params_digest(node.learner.params_numpy())
        assert node.act(_areq(12, world_obs))["policy_version"] == v
    finally:
        node.close()


def _warm(node, obs, n=12):
    for t in range(n):
        node.act(_areq(t, obs))
        node.feedback(_freq(t, obs, "stay"))


def test_act_waits_for_an_in_flight_feedback_of_the_previous_tick(tmp_path, world_obs):
    """The barrier: act(t+1) must see the policy produced by feedback(t), even when the caller
    did not wait for the ack. The feedback is parked on the training lock to make it observable."""
    node = _node(tmp_path)
    try:
        _warm(node, world_obs)
        node.act(_areq(12, world_obs))
        v0 = node.learner.version
        fb_out, act_out = [], []
        node.mu.acquire()
        try:
            fb = threading.Thread(
                target=lambda: fb_out.append(node.feedback(_freq(12, world_obs, "stay")))
            )
            fb.start()
            deadline = time.time() + 30
            while node.fb_inflight is None and time.time() < deadline:
                time.sleep(0.005)
            assert node.fb_inflight == ("run-a", 0, 12)
            ac = threading.Thread(
                target=lambda: act_out.append(node.act(_areq(13, world_obs, deadline_ms=20000)))
            )
            ac.start()
            time.sleep(0.3)
            assert act_out == [] and ac.is_alive()  # parked behind the feedback, not answering
        finally:
            node.mu.release()
        fb.join(30)
        ac.join(30)
        assert not fb.is_alive() and not ac.is_alive()
        assert fb_out[0]["policy_version"] > v0
        assert act_out[0]["policy_version"] == fb_out[0]["policy_version"]  # post-feedback policy
    finally:
        node.close()


def test_the_barrier_wait_is_bounded_by_the_deadline(tmp_path, world_obs):
    node = _node(tmp_path)
    try:
        _warm(node, world_obs)
        node.act(_areq(12, world_obs))
        v0 = node.learner.version
        node.mu.acquire()
        try:
            fb = threading.Thread(target=lambda: node.feedback(_freq(12, world_obs, "stay")))
            fb.start()
            while node.fb_inflight is None:
                time.sleep(0.005)
            t0 = time.perf_counter()
            out = node.act(_areq(13, world_obs, deadline_ms=60))
            waited = time.perf_counter() - t0
        finally:
            node.mu.release()
        fb.join(30)
        assert waited >= 0.05  # lower bound only: it waited for its deadline, not forever
        assert out["policy_version"] == v0 and node.counters["act_fb_wait_timeouts"] == 1
    finally:
        node.close()


# --- A3: identity formats --------------------------------------------------------------------
def test_boot_id_event_id_and_sequence_formats(tmp_path, world_obs):
    node = _node(tmp_path)
    try:
        assert re.fullmatch(r"[0-9a-f]{8}", node.boot_id)
        acts = [node.act(_areq(t, world_obs))["action"] for t in range(5)]
        seqs = [a["sequence"] for a in acts]
        assert seqs == sorted(set(seqs))
        for a in acts:
            assert a["event_id"] == f"{N1}-{node.boot_id}-{a['sequence']}"
        assert node.status()["boot_id"] == node.boot_id
    finally:
        node.close()


def test_peer_seq_is_persisted_so_post_restart_offers_are_not_dropped_as_stale(tmp_path):
    c = Cluster(tmp_path, (N1, N2), lr=1e-6, hidden=32)
    try:
        a, b = c.node(N1), c.node(N2)
        load(a, mover_policy())
        MiniCoordinator(c.clients).reset(0)
        c.clients[N1].episode_end(0, 0)
        seq1 = b.peer.net.last_seq(N2, N1)
        assert seq1 >= 0 and a.counters["offers_sent"] == 1
        urls = {nid: rt.peer_url for nid, rt in c.runtimes.items()}
        cfg1 = c.runtimes[N1].cfg
        c.runtimes[N1].stop(checkpoint=True)
        rt1 = Runtime(cfg1)  # the sender process restarts on the same volume
        rt1.set_peer_urls(urls)
        rt1.start()
        c.runtimes[N1] = rt1
        try:
            a2, cl = rt1.node, Client(rt1.control_url)
            assert a2.restore_info["restored"] is True and a2.boot_id != a.boot_id
            load(a2, stay_policy())  # something new to offer
            cl.control("reset", run_id="run-t", episode=1)
            cl.episode_end(1, 0)
            assert a2.counters["offers_sent"] == 2 and a2.counters["offers_refused_by_peer"] == 0
            assert b.peer.net.last_seq(N2, N1) > seq1  # received and ordered after the old ones
        finally:
            rt1.stop(False)
    finally:
        for nid in (N2,):
            c.runtimes[nid].stop(checkpoint=False)


# --- A5: configure ----------------------------------------------------------------------------
def conf(**over):
    body = {
        "hyperparameters": {"lr": 0.003, "gamma": 0.9, "hidden": 16, "capacity": 256, "batch": 4,
                            "target_every": 10, "train_steps_per_feedback": 2},
        "epsilon_schedule": {"start": 0.4, "end": 0.1, "decay_episodes": 2},
        "margin": 0.25,
        "world_config": {"size": 8, "n_targets": 1, "obstacle_density": 0.05, "sense_radius": 2,
                         "max_ticks": 30, "battery_scale": 2.0, "reward_id": "rew-v0"},
        "gate_seeds": [5001, 5002, 5003],
        "n_validation_agents": 2,
        "encoder_id": "grid-flat-v1-s8-r2",
        "exchange_every_ticks": 7,
        "seed": 11,
    }  # fmt: skip
    body.update(over)
    return body


def test_configure_applies_the_run_configuration_to_a_running_node(tmp_path):
    rt = Runtime(make_cfg(tmp_path, node_ids=(N1,))).start()
    try:
        node, c = rt.node, Client(rt.control_url)
        st, out = c.control("configure", run_id="run-c", **conf())
        assert st == 200 and out["ok"] is True and len(out["config_hash"]) == 64
        s = c.status()
        assert s["config_hash"] == out["config_hash"] and s["configured_run"] == "run-c"
        assert s["exchange_every_ticks"] == 7 and s["encoder_id"] == "grid-flat-v1-s8-r2"
        cfg = node.cfg
        assert (cfg.hidden, cfg.capacity, cfg.batch, cfg.lr, cfg.gamma) == (16, 256, 4, 0.003, 0.9)
        assert cfg.peer_margin == 0.25 and cfg.seed == 11 and cfg.world_max_ticks == 30
        assert node.learner.hidden == 16 and node.learner.capacity == 256
        # the node-private validation world is built from world_config / gate_seeds
        assert node.validator.seeds == (5001, 5002, 5003)
        assert len(node.validator.world.possible_agents) == 2
        assert (node.validator.world.size, node.validator.world.max_ticks) == (8, 30)
        # epsilon schedule: decay over decay_episodes * max_ticks acts, linear start -> end
        assert s["epsilon"] == pytest.approx(0.4)
        node.act_count = 30
        assert c.status()["epsilon"] == pytest.approx(0.25)
        node.act_count = 600
        assert c.status()["epsilon"] == pytest.approx(0.1)
        node.act_count = 0
        # train_steps_per_feedback comes from the configuration
        w = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=500)
        o = w.reset(1)["node-0"]
        c.control("reset", run_id="run-c", episode=0)
        for t in range(20):
            a = c.act("run-c", 0, t, obs_json("run-c", "n", t, o))[1]
            assert c.feedback("run-c", 0, t, 0.1, obs_json("run-c", "n", t + 1, o),
                              cmd=a["action"]["command"])[0] == 200  # fmt: skip
        assert c.status()["train_steps"] == 2 * (20 - 4 + 1)
        assert node.validator.episodes_run == 0  # the live path never touched the private world
    finally:
        rt.stop(False)


def test_configure_is_idempotent_conflicts_and_validates(tmp_path):
    rt = Runtime(make_cfg(tmp_path, node_ids=(N1,))).start()
    try:
        c = Client(rt.control_url)
        st, first = c.control("configure", run_id="run-c", **conf())
        st2, again = c.control("configure", run_id="run-c", **conf())
        assert st2 == 200 and again["config_hash"] == first["config_hash"]
        st3, err = c.control("configure", run_id="run-c", **conf(margin=0.5))
        assert st3 == 409 and err["error"] == "config_conflict"
        assert c.status()["config_hash"] == first["config_hash"]  # the conflict changed nothing
        bad = {
            "encoder": conf(encoder_id="grid-flat-v1-s9-r2"),
            "reward": conf(world_config={**conf()["world_config"], "reward_id": "rew-x"}),
            "no seeds": conf(gate_seeds=[]),
            "extra field": {**conf(), "surprise": 1},
            "missing field": {k: v for k, v in conf().items() if k != "margin"},
        }
        for name, body in bad.items():
            msg = {"command": "configure", "run_id": "run-d", **body}
            code, resp = c.call("POST", "/v1/control", msg)
            assert code == 422, (name, code, resp)
        nan = b'{"command":"configure","run_id":"run-d","margin":NaN}'
        assert c.call("POST", "/v1/control", raw=nan)[0] in (400, 422)
        assert c.status()["configured_run"] == "run-c"
    finally:
        rt.stop(False)


def test_configuration_and_checkpoint_survive_a_restart_and_a_new_run_starts_fresh(tmp_path):
    cfg0 = make_cfg(tmp_path, node_ids=(N1,))  # env-style defaults: hidden=32
    rt = Runtime(cfg0).start()
    node, c = rt.node, Client(rt.control_url)
    st, out = c.control("configure", run_id="run-c", **conf())
    assert st == 200
    w = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=500)
    o = w.reset(1)["node-0"]
    c.control("reset", run_id="run-c", episode=0)
    for t in range(15):
        a = c.act("run-c", 0, t, obs_json("run-c", "n", t, o))[1]
        c.feedback("run-c", 0, t, 0.1, obs_json("run-c", "n", t + 1, o), cmd=a["action"]["command"])
    steps = node.learner.steps
    assert steps > 0
    rt.stop(checkpoint=True)
    # restart with the ORIGINAL (unconfigured) environment: the volume remembers the configure
    rt2 = Runtime(cfg0).start()
    try:
        n2, c2 = rt2.node, Client(rt2.control_url)
        assert n2.cfg.hidden == 16 and n2.restore_info["restored"] is True
        assert n2.learner.steps == steps and n2.config_hash == out["config_hash"]
        st, again = c2.control("configure", run_id="run-c", **conf())
        assert st == 200 and again["config_hash"] == out["config_hash"]  # same run, same config
        assert c2.control("configure", run_id="run-c", **conf(seed=12))[0] == 409
        # a different run id is a new run: fresh learner, previous generations kept aside
        st, new = c2.control("configure", run_id="run-d", **conf(seed=12))
        assert st == 200 and new["config_hash"] != out["config_hash"]
        assert n2.learner.steps == 0 and n2.checkpoint_generation == 0
        assert any(p.name.startswith("ckpt-before-run-d") for p in cfg0.checkpoint_dir.iterdir())
        assert c2.act("run-c", 0, 99, obs_json("run-c", "n", 99, o))[0] == 409  # wrong run now
    finally:
        rt2.stop(False)

"""Acting must not wait for training, peer I/O, validation, checkpoints or telemetry."""

import os
import sys
import threading
import time

import pytest
from archipelago_learning import TorchLearner, encode
from archipelago_noderuntime.runtime import Runtime
from archipelago_peer import post
from archipelago_sim.env import GridWorld
from archipelago_transport import Envelope
from procs import NodeProc
from support import PEER_TOKEN, Blackhole, Client, FakeSink, make_cfg, obs_json, percentile
from test_peers import N1, N2, mover_policy

P95_BOUND = 0.10  # seconds per HTTP call, p95
MAX_BOUND = 0.50
VAL_OVR = dict(lr=1e-6, peer_margin=0.05, hidden=32, validation_seeds=(7001, 7002))


class Driver:
    """Keeps acting/feeding one node, recording each call's latency."""

    def __init__(self, client, run="run-d", episode=0):
        self.c, self.run, self.ep, self.t = client, run, episode, 0
        self.w = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=100000)
        self.obs = self.w.reset(1)["node-0"]
        client.control("reset", run_id=run, episode=episode)
        self.lat_act, self.lat_fb = [], []

    def step(self):
        if not self.w.agents:  # battery ran out: start a fresh physical episode, same node episode
            self.obs = self.w.reset(self.t)["node-0"]
        t0 = time.perf_counter()
        st, a = self.c.act(self.run, self.ep, self.t, obs_json(self.run, "n", self.t, self.obs))
        t1 = time.perf_counter()
        assert st == 200, a
        nxt, rew, _, _, _ = self.w.step({"node-0": a["action"]["command"]})
        o = nxt["node-0"] if "node-0" in nxt else self.obs
        nobs = obs_json(self.run, "n", self.t + 1, o)
        st, f = self.c.feedback(
            self.run, self.ep, self.t, rew["node-0"], nobs, cmd=a["action"]["command"]
        )
        t2 = time.perf_counter()
        assert st == 200, f
        self.lat_act.append(t1 - t0)
        self.lat_fb.append(t2 - t1)
        self.obs = o
        self.t += 1

    def reset_latencies(self):
        self.lat_act.clear()
        self.lat_fb.clear()

    def assert_fast(self):
        for name, xs in (("act", self.lat_act), ("feedback", self.lat_fb)):
            assert percentile(xs, 95) < P95_BOUND, (name, percentile(xs, 95))
            assert max(xs) < MAX_BOUND, (name, max(xs))


def test_stalled_peer_does_not_delay_act_or_feedback(tmp_path):
    hole = Blackhole()
    cfg = make_cfg(tmp_path, N1, (N1, N2), peer_timeout=3.0, peer_retries=0)
    rt = Runtime(cfg)
    rt.set_peer_urls({N2: hole.url})
    rt.start()
    try:
        c = Client(rt.control_url)
        d = Driver(c)
        for _ in range(40):
            d.step()
        t0 = time.perf_counter()
        st, out = c.control("episode_end", episode=0, tick=40)  # 202: the window runs in background
        assert st == 202 and time.perf_counter() - t0 < 0.5
        deadline = time.time() + 5
        while hole.accepted == 0 and time.time() < deadline:
            time.sleep(0.01)
        assert hole.accepted >= 1 and rt.node.exchange_running  # genuinely stuck on the peer
        d.reset_latencies()
        stall_start = time.perf_counter()
        n = 0
        while rt.node.exchange_running and n < 150:
            d.step()
            n += 1
        assert n >= 100 and rt.node.exchange_running  # all of this happened during the stall
        assert time.perf_counter() - stall_start < 3.0
        d.assert_fast()
        deadline = time.time() + 10
        while rt.node.exchange_running and time.time() < deadline:
            time.sleep(0.05)
        assert rt.node.counters["offers_unreachable"] == 1
        assert c.status()["train_steps"] >= 100  # training kept going during the stall
    finally:
        rt.stop(False)
        hole.close()


def test_stalled_telemetry_sink_does_not_delay_act_or_feedback(tmp_path):
    sink = FakeSink()
    sink.mode = "stall"
    cfg = make_cfg(tmp_path, N1, (N1,), telemetry_url=sink.url, ship_timeout=5.0, update_every=2)
    rt = Runtime(cfg).start()
    try:
        c = Client(rt.control_url)
        d = Driver(c)
        for _ in range(200):
            d.step()
        assert sink.connections >= 1  # the shipper is really stuck inside a request
        st = c.status()
        assert st["telemetry_backlog"] > 50 and sink.received == 0
        d.assert_fast()
        t0 = time.perf_counter()
        assert c.episode_end(0, d.t)[0] == 202  # exchange + checkpoint, in the background
        assert time.perf_counter() - t0 < 2.0
        assert rt.node.checkpoint_generation >= 1
    finally:
        rt.stop(False)
        sink.close()


def test_act_does_not_wait_on_any_lock_held_by_training_checkpoint_or_validation(tmp_path):
    """Deterministic, timing-free proof: the node's slow work is parked in the worst possible
    place (validation blocked mid-evaluation, training/checkpoint/feedback locks all held) and
    act still answers. A hang here would fail the join, a lock dependency can not hide."""
    entered, release = threading.Event(), threading.Event()
    rt = Runtime(make_cfg(tmp_path, N2, (N1, N2), **VAL_OVR)).start()
    node = rt.node
    try:
        c = Client(rt.control_url)
        d = Driver(c)
        for _ in range(12):
            d.step()
        real_eval = node.validator.evaluate

        def blocking_eval(params, cancel=None):
            entered.set()
            assert release.wait(60)
            return real_eval(params, cancel)

        node.validator.evaluate = blocking_eval
        donor = TorchLearner(N1, 28, 5, hidden=32, seed=1)
        donor.load_params_numpy(mover_policy())
        env = Envelope.make(N1, N2, 7, encode(donor))
        assert post(rt.peer_url, env, token=PEER_TOKEN) == 200
        assert c.control("episode_end", episode=0, tick=d.t)[0] == 202
        assert entered.wait(30)  # the exchange worker is parked inside the validation
        assert node.exchange_running and node.window_state == "running"
        results: list = []

        def act_while_everything_else_is_stuck():
            for k in range(5):
                results.append(c.act(d.run, d.ep, d.t + k, obs_json(d.run, "n", d.t + k, d.obs)))

        with node.fbl, node.mu, node.ckl:  # a feedback + optimizer step + checkpoint in progress
            th = threading.Thread(target=act_while_everything_else_is_stuck)
            th.start()
            th.join(30)
            assert not th.is_alive(), "act blocked on a lock held by training/checkpoint"
        assert [st for st, _ in results] == [200] * 5
        release.set()
        assert c.wait_idle(60)
        assert node.counters["decisions_accepted"] == 1
    finally:
        release.set()
        rt.stop(False)


def test_act_latency_p99_stays_under_50ms_while_a_full_validation_runs(tmp_path):
    """A16 measured: node-side act handler latency (excludes HTTP and client scheduling noise)
    while the validation worker burns 100% CPU on the SAME single core as the act path."""
    cores = os.sched_getaffinity(0) if hasattr(os, "sched_getaffinity") else None
    switch = sys.getswitchinterval()
    sys.setswitchinterval(0.001)  # what the deployed process sets in __main__
    if cores:
        os.sched_setaffinity(0, {min(cores)})  # one core: validation and acting really compete
    seeds = tuple(range(9100, 9112))
    rt = Runtime(
        make_cfg(tmp_path, N2, (N1, N2), **{**VAL_OVR, "validation_seeds": seeds,
                                            "validation_max_ticks": 400, "world_max_ticks": 400})
    ).start()  # fmt: skip
    node = rt.node
    try:
        c = Client(rt.control_url)
        d = Driver(c)
        for _ in range(30):
            d.step()
        donor = TorchLearner(N1, 28, 5, hidden=32, seed=1)
        donor.load_params_numpy(mover_policy())
        assert post(rt.peer_url, Envelope.make(N1, N2, 7, encode(donor)), token=PEER_TOKEN) == 200
        node.act_lat.clear()
        assert c.control("episode_end", episode=0, tick=d.t)[0] == 202
        during = 0
        while node.exchange_running:  # queued -> running -> done: no race with the start
            d.step()
            during += 1
        lat = [x * 1000 for x in node.act_lat]
        assert during >= 50 and len(lat) >= 50, f"validation too short to mean anything: {during}"
        p99 = percentile(lat, 99)
        st = c.status()
        assert st["act_latency_ms"]["n"] >= 50 and st["act_latency_ms"]["p99"] == pytest.approx(p99)
        assert p99 < 50.0, f"act p99 {p99:.2f} ms over {len(lat)} acts (A16 bound 50 ms)"
        assert node.counters["decisions_accepted"] == 1 and node.checkpoint_generation >= 1
        assert node.validator.episodes_run == 2 * len(seeds)  # the full load really ran
        print(
            f"A16 act latency during validation: n={len(lat)} p99={p99:.3f} ms max={max(lat):.3f}"
        )
    finally:
        sys.setswitchinterval(switch)
        if cores:
            os.sched_setaffinity(0, cores)
        rt.stop(False)


def test_real_process_serves_acts_through_a_long_validation_and_final_checkpoint(tmp_path):
    """The previously flaky process-level test, rebuilt: no wall-clock bound on HTTP calls and no
    race with the start of the window (state 'running' covers queued -> running), the latency
    claim rests on the node's own handler measurement."""
    proc = NodeProc(
        tmp_path,
        N2,
        (N1, N2),
        VALIDATION_SEEDS=",".join(str(x) for x in range(9100, 9140)),
        WORLD_MAX_TICKS=900,
        LR="1e-6",
    ).start()
    try:
        c = proc.client
        donor = TorchLearner(N1, 28, 5, hidden=32, seed=1)
        donor.load_params_numpy(mover_policy())
        d = Driver(c, run="run-t", episode=0)
        for _ in range(30):
            d.step()
        env = Envelope.make(N1, N2, 7, encode(donor))
        assert post(proc.info["peer_url"], env, token=PEER_TOKEN) == 200
        st, out = c.control("episode_end", episode=0, tick=d.t)
        assert st == 202 and out["window_id"]
        during = 0
        while c.status()["window"] == "running" or during == 0:
            d.step()
            during += 1
        assert during >= 10  # acting went on while 40 seeds x 2 policies were being judged
        st = c.status()
        assert st["counters"]["decisions_accepted"] == 1 and st["checkpoint_generation"] >= 1
        assert st["validation_evaluations"] == 80 and st["last_window_id"] == out["window_id"]
        assert st["act_latency_ms"]["p99"] < 50.0, st["act_latency_ms"]
        assert st["rss_peak_bytes"] >= st["rss_bytes"] > 0  # peak RSS is recorded
    finally:
        proc.close()

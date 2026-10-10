"""Acting must not wait for training, peer I/O, validation, checkpoints or telemetry."""

import time

from archipelago_learning import TorchLearner, encode
from archipelago_noderuntime import ENCODER_ID
from archipelago_noderuntime.runtime import Runtime
from archipelago_peer import post
from archipelago_sim.env import GridWorld
from archipelago_transport import Envelope
from procs import NodeProc
from support import Blackhole, Client, FakeSink, make_cfg, obs_json, percentile
from test_peers import N1, N2, mover_policy

P95_BOUND = 0.10  # seconds per HTTP call, p95
MAX_BOUND = 0.50


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
        st, f = self.c.feedback(self.run, self.ep, self.t, rew["node-0"], nobs)
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
        st, out = c.control("episode_end")  # async: starts an exchange that will hang on the peer
        assert st == 200 and time.perf_counter() - t0 < 0.5
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
        assert c.control("episode_end", wait=True)[0] == 200  # exchange + checkpoint
        assert time.perf_counter() - t0 < 2.0
        assert rt.node.checkpoint_generation >= 1
    finally:
        rt.stop(False)
        sink.close()


def test_long_validation_and_checkpoint_do_not_stall_acting(tmp_path):
    """Real node process (as deployed); a candidate arrives and 40 seeds x 2 policies are judged."""
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
        donor = TorchLearner(N1, 28, 5, hidden=32, seed=1, encoder=ENCODER_ID)
        donor.load_params_numpy(mover_policy())
        d = Driver(c, run="run-t", episode=0)
        for _ in range(30):
            d.step()
        assert post(proc.info["peer_url"], Envelope.make(N1, N2, 7, encode(donor))) == 200
        d.reset_latencies()
        c.control("episode_end")  # async: validation runs on the exchange thread
        t0 = time.perf_counter()
        during = 0
        while True:  # the worker may not have picked the request up yet: wait for it to start
            st = c.status()
            if st["counters"]["exchanges"] >= 1 and not st["exchange_running"]:
                break
            d.step()
            during += 1
        busy = time.perf_counter() - t0
        assert busy > 0.5 and during >= 20  # acting went on throughout a long validation
        d.assert_fast()
        st = c.status()
        assert st["counters"]["decisions_accepted"] == 1 and st["checkpoint_generation"] >= 1
        assert st["validation_evaluations"] == 80
    finally:
        proc.close()

"""Measure one real node process: idle/training RSS and per-request latency (not a pytest test).

    uv run python tests/noderuntime/measure_node.py [--feedbacks 3000]

Starts `python -m archipelago_noderuntime` with deployment-sized defaults (28-32-5 MLP, replay
5000, 16x16 world, 900-tick validation), drives act/feedback over HTTP like the coordinator does,
and prints one JSON document. RSS comes from /proc/<pid>/status of the node process itself.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402
from archipelago_learning import TorchLearner, encode  # noqa: E402
from archipelago_noderuntime import ENCODER_ID  # noqa: E402
from archipelago_peer import post  # noqa: E402
from archipelago_sim.env import GridWorld  # noqa: E402
from archipelago_transport import Envelope  # noqa: E402
from procs import NodeProc  # noqa: E402
from support import obs_json  # noqa: E402


def proc_mem(pid: int) -> dict:
    out = {}
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        k, _, v = line.partition(":")
        if k in ("VmRSS", "VmHWM", "RssAnon", "RssFile", "RssShmem"):
            out[k] = round(int(v.split()[0]) / 1024, 1)  # MiB
    return out


def pct(xs, q):
    return round(float(np.percentile(np.asarray(xs) * 1000, q)), 3)  # ms


def summary(xs):
    return {"n": len(xs), "p50_ms": pct(xs, 50), "p95_ms": pct(xs, 95), "p99_ms": pct(xs, 99)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feedbacks", type=int, default=3000)
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="noderuntime-measure-"))
    p = NodeProc(
        tmp,
        "node-02",
        ("node-01", "node-02"),
        WORLD_SIZE=16,
        WORLD_N_TARGETS=3,
        WORLD_MAX_TICKS=900,
        VALIDATION_SEEDS="9001,9002,9003",
        REPLAY_CAPACITY=5000,
        BATCH_SIZE=32,
        LR="0.01",
    ).start()
    res: dict = {"torch_version": p.client.status()["torch_version"]}
    try:
        pid = p.proc.pid
        time.sleep(2.0)
        res["idle"] = proc_mem(pid)
        c = p.client
        w = GridWorld(size=16, n_agents=1, n_targets=3, max_ticks=10**6)
        obs = w.reset(1)["node-0"]
        c.control("reset", run_id="run-m", episode=0)
        la, lf = [], []
        for t in range(args.feedbacks):
            if not w.agents:
                obs = w.reset(t)["node-0"]
            t0 = time.perf_counter()
            st, a = c.act("run-m", 0, t, obs_json("run-m", "n", t, obs))
            t1 = time.perf_counter()
            nxt, rew, term, _, _ = w.step({"node-0": a["action"]["command"]})
            obs = nxt.get("node-0", obs)
            st, f = c.feedback("run-m", 0, t, rew["node-0"], obs_json("run-m", "n", t + 1, obs))
            t2 = time.perf_counter()
            la.append(t1 - t0)
            lf.append(t2 - t1)
        st = c.status()
        res["after_training"] = {
            **proc_mem(pid),
            "train_steps": st["train_steps"],
            "replay": st["replay_size"],
        }
        res["act_latency_while_training"] = summary(la[200:])
        res["feedback_latency_incl_1_optimizer_step"] = summary(lf[200:])
        t0 = time.perf_counter()
        c.control("checkpoint")
        res["checkpoint_seconds"] = round(time.perf_counter() - t0, 4)
        # act latency while a full-size validation (3 seeds x 900 ticks x 2 policies) runs
        donor = TorchLearner("node-01", 28, 5, hidden=32, seed=7, encoder=ENCODER_ID)
        post(p.info["peer_url"], Envelope.make("node-01", "node-02", 3, encode(donor)))
        c.control("episode_end")
        lv, n0 = [], time.perf_counter()
        t = args.feedbacks
        while c.status()["exchange_running"] or not lv:
            if not w.agents:
                obs = w.reset(t)["node-0"]
            t0 = time.perf_counter()
            st, a = c.act("run-m", 0, t, obs_json("run-m", "n", t, obs))
            lv.append(time.perf_counter() - t0)
            nxt, rew, *_ = w.step({"node-0": a["action"]["command"]})
            obs = nxt.get("node-0", obs)
            c.feedback("run-m", 0, t, rew["node-0"], obs_json("run-m", "n", t + 1, obs))
            t += 1
        res["act_latency_during_validation"] = {
            **summary(lv),
            "window_seconds": round(time.perf_counter() - n0, 3),
        }
        res["after_exchange"] = proc_mem(pid)
    finally:
        p.close()
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()

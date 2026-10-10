"""Development pilot behind idle_vs_learners.md. Uses only train and VALIDATION (dev) seeds.

    PYTHONPATH=packages/learning:packages/sim:experiments python experiments/diagnosis/pilot.py

Writes pilot_results.json next to this file. Never touches the frozen TEST seeds, so nothing here
is tuned on them. Wall time: about 2 minutes on one CPU core.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import protocol_harness as H
import run
from archipelago_sim.env import ACTIONS

EPISODES, SEEDS, SCENARIO = 40, (0, 1, 2), "connected"
OUT = Path(__file__).with_name("pilot_results.json")


def episode_stats(cell, factory, seed, trace_agent="node-0"):
    """Play one dev episode with the cell's test policy and collect reward-component statistics."""
    env, w = cell.env, cell.env.world
    act0 = factory(seed)
    trace, init = [], {}
    visits = {a: set() for a in cell.agents}
    revisit = 0

    def act(a, o, t):
        init.setdefault("cells", len(w.visited - w.obstacles))
        i = act0(a, o, t)
        trace.append((t, a, ACTIONS[i], w.drones[a].pos))
        return i

    def hook(obs, acts, rew, nxt, term, t):
        nonlocal revisit
        for a in acts:
            p = w.drones[a].pos
            revisit += p in visits[a]
            visits[a].add(p)

    rec = H.play(env, cell.scen, seed, act, hook, info=cell.info)
    ev = Counter(e["event"] for e in w.events)
    gained = len(w.visited - w.obstacles) - init["cells"]
    r = w.r_new_cell, w.r_target, w.r_step, w.r_collision, w.r_invalid
    n = len(cell.agents)
    parts = {  # mean per-agent return decomposition
        "new_cell": r[0] * gained / n,  # new-cell reward is paid to whoever senses the cell
        "target": r[1] * rec["found"] / n,
        "step": r[2] * rec["agent_steps"] / n,
        "collision": r[3] * (ev["wall_collision"] + ev["agent_collision"]) / n,
        "invalid": r[4] * (ev["invalid_action"] + ev["missing_action"]) / n,
    }
    hist = Counter(t[2] for t in trace)
    return rec, {
        "ret": rec["ret"],
        "parts": parts,
        "ticks": rec["ticks"],
        "found": rec["found"],
        "coverage": rec["coverage"],
        "wall_collisions": ev["wall_collision"],
        "agent_collisions": ev["agent_collision"],
        "action_hist": dict(hist),
        "revisit_rate": revisit / max(1, rec["agent_steps"]),
        "trace_head": [f"{t}:{a[-1]}:{x}@{p}" for t, a, x, p in trace if a == trace_agent][:40],
    }


def q_audit(cell):
    out = {}
    for a, L in cell.L.items():
        size = min(L.n, L.capacity)
        o = L.replay["o"][:size][:2000]
        q = L.forward(L.params, o)[1]
        losses = [e["loss"] for e in L.events if e["type"] == "local_update"]
        win = max(1, len(losses) // 8)
        out[a] = {
            "updates": L.steps,
            "replay_rows": size,
            "replay_capacity": L.capacity,
            "transitions_seen": L.n,
            "q_min": float(q.min()),
            "q_max": float(q.max()),
            "q_mean": float(q.mean()),
            "q_action_spread_mean": float((q.max(1) - q.min(1)).mean()),
            "greedy_hist": dict(Counter(ACTIONS[i] for i in q.argmax(1))),
            "loss_windows": [
                float(np.mean(losses[i : i + win])) for i in range(0, len(losses) - win + 1, win)
            ],
            "reward_in_replay_mean": float(L.replay["r"][:size].mean()),
            "reward_in_replay_pos_frac": float((L.replay["r"][:size] > 0.5).mean()),
        }
    return out


def main():
    t0 = time.perf_counter()
    res = {
        "episodes": EPISODES,
        "seeds": list(SEEDS),
        "scenario": SCENARIO,
        "dev_seeds": list(H.VAL),
        "env": H.ENV_KW,
        "eps": H.EPS,
        "cells": [],
    }
    for mode, obs in (
        ("idle", H.OBS_ID),
        ("rule", H.OBS_ID),
        ("independent", H.OBS_ID),
        ("independent", "grid-flat-v1-map"),
        ("info_only", "grid-flat-v1-map"),
    ):
        for s in SEEDS:
            cfg = run.CellConfig(episodes=EPISODES, val_seeds=H.VAL, test_seeds=H.TEST[:1], obs=obs)
            c = run.Cell(mode, SCENARIO, s, cfg)
            if mode not in run.NOTRAIN:
                c.train()
            factory = c.test_policy()
            eps = [episode_stats(c, factory, d)[1] for d in H.VAL]  # dev seeds, not TEST
            cell = {
                "mode": mode,
                "obs": obs,
                "seed": s,
                "episodes": eps,
                "mean_ret": float(np.mean([e["ret"] for e in eps])),
            }
            if c.L:
                cell["q_audit"] = q_audit(c)
                cell["train"] = {"transitions": c.bud.transitions, "env_ticks": c.bud.env_ticks}
            res["cells"].append(cell)
            print(mode, obs, s, round(cell["mean_ret"], 2), flush=True)
    # observation audit: how often can the 5x5 crop distinguish a visited from an unvisited cell?
    env = H.make_env()
    env.reset(seed=H.VAL[0])
    o = H.flat(env, "node-0")
    res["obs_audit"] = {
        "dim": int(o.shape[0]),
        "crop_unknown_cells_at_reset": int((o[:25] < 0).sum()),
        "crop_values": sorted({float(v) for v in o[:25]}),
    }
    res["wall_s"] = time.perf_counter() - t0
    OUT.write_text(json.dumps(res, indent=1))
    print("wall_s", round(res["wall_s"], 1))


if __name__ == "__main__":
    sys.exit(main())

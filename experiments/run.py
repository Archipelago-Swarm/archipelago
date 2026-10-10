"""T09 matched-budget comparison of six modes under four link schedules (see --help)."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
from archipelago_learning.dqn import Learner
from archipelago_learning.peer import encode, offer
from archipelago_learning.rollout import (
    _norm,
    ctde_episode,
    episode,
    evaluate,
    make_env,
    make_learner,
    reset,
)
from archipelago_sim.env import ACTIONS, explorer_policy

MODES = ("rule", "idle", "independent", "information_only", "p2p", "central_online", "ctde")
SCENARIOS = ("connected", "split", "rejoin", "node_failure")
# Experiment seed s trains on seeds s*EPISODES.. ; disjointness asserted in check_seeds.
TRAIN0, VAL, TEST = 0, range(100000, 100004), range(200000, 200006)


def check_seeds(seeds, episodes):
    train = {TRAIN0 + s * episodes + i for s in seeds for i in range(episodes)}
    assert not (train & set(VAL)) and not (train & set(TEST)) and not set(VAL) & set(TEST), (
        "seed overlap"
    )


def link_up(scenario, i, episodes):
    """Is the inter-node / node-to-controller link usable at training episode i?"""
    half = i >= episodes // 2
    return {"connected": True, "split": False, "rejoin": half, "node_failure": not half}[scenario]


def alive1(scenario, i, episodes):
    return not (scenario == "node_failure" and i >= episodes // 2)  # node-1 stops training


def share_obs(src, dst, k):
    """information_only: copy src's newest k raw transitions into dst's replay (no parameters)."""
    for i in range(src.n - min(k, src.capacity), src.n):
        j = i % src.capacity
        dst.observe(*(src.replay[f][j] for f in ("o", "a", "r", "o2", "d")))


def rollout(env, act, seed, drop=()):
    """Greedy eval episode. Returns (mean per-agent return, action-replay sha256)."""
    obs = reset(env, seed, drop)
    tot, log = dict.fromkeys(env.possible_agents, 0.0), []
    while env.agents:
        acts = {a: act(a, obs[a]) for a in env.agents}
        log.append(acts)
        obs, rew, *_ = env.step(acts)
        for a in rew:
            tot[a] += rew[a]
    h = hashlib.sha256(json.dumps(log, sort_keys=True).encode()).hexdigest()
    return float(np.mean(list(tot.values()))), h


def run_cell(mode, scenario, seed, episodes, steps):
    """Train under the schedule, then score on TEST. Same env seeds for every mode."""
    env, agents = make_env(), make_env().possible_agents
    t0, rejected, sent = time.perf_counter(), [0], [0]
    if mode == "idle":  # control: no policy at all, to expose idle-beats-learner artifacts

        def act(_a, _o):
            return 0

    elif mode == "rule":
        rngs = {a: random.Random(seed) for a in agents}
        visits = {a: {} for a in agents}
        w = env.world

        def act(a, _o):
            return ACTIONS.index(explorer_policy(w.observe(a), visits[a], rngs[a]))
    else:
        shared = mode == "central_online"
        kw = {"mode": "information_only"} if mode == "information_only" else {}
        L = {a: make_learner(a, seed * 10 + k, **kw) for k, a in enumerate(agents)}
        if shared:
            L = dict.fromkeys(agents, L[agents[0]])
        critic = None
        if mode == "ctde":  # joint-observation critic: used in training only, never at inference
            critic = Learner("critic", len(agents) * L[agents[0]].obs_dim, 1, seed=seed * 10 + 9)
        shared_n = {}
        for i in range(episodes):
            s = TRAIN0 + seed * episodes + i
            up = link_up(scenario, i, episodes)
            if shared and mode == "central_online" and not up:
                continue  # online central learner only sees data while the link is up
            gone = () if alive1(scenario, i, episodes) else (agents[1],)
            if critic:
                ctde_episode(env, L, critic, s, 0.2, gone)
            else:
                episode(env, L, s, 0.2, drop=gone)
            steps[0] += env.world.tick * len(agents)
            if (
                mode in ("p2p", "information_only")
                and up
                and alive1(scenario, i, episodes)
                and i % 5 == 4
            ):
                new = {a: L[a].n - shared_n.get(a, 0) for a in agents}  # own data since last swap
                for a, b in ((agents[0], agents[1]), (agents[1], agents[0])):
                    if mode == "information_only":
                        share_obs(L[a], L[b], new[a])
                        sent[0] += new[a] * 4 * (2 * L[a].obs_dim + 3)  # float32 bytes
                        continue
                    payload = encode(L[a])
                    sent[0] += len(payload)
                    ev = offer(L[b], payload, lambda p: evaluate(p, VAL), sender=a)
                    rejected[0] += not ev["accepted"]
                shared_n = {a: L[a].n for a in agents}  # received rows are not re-sent
        snaps = {
            a: L[a].snapshot() for a in agents
        }  # ctde/central: decentralised copies at inference
        probes = {a: copy.deepcopy(L[a]) for a in agents}

        def act(a, o):
            return probes[a].act(_norm(o), 0.0, snaps[a])

    act0 = act

    # central_online executes through the controller, so it needs the link at test time (the
    # final-episode link state); ctde runs decentralised copies and is link-independent.
    no_ctl = mode == "central_online" and not link_up(scenario, episodes - 1, episodes)

    def act(a, o):
        return 0 if no_ctl else act0(a, o)

    gone = (agents[1],) if scenario == "node_failure" else ()  # node-1 absent at test too
    res = [rollout(env, act, s, gone) for s in TEST]
    return {
        "mode": mode,
        "scenario": scenario,
        "seed": seed,
        "episodes": episodes,
        "returns": [r for r, _ in res],
        "mean": float(np.mean([r for r, _ in res])),
        "rejected_exchanges": rejected[0],
        "exchange_bytes": sent[0],
        "train_env_steps": steps[0],
        "replay_hashes": [h for _, h in res],
        "wall_s": time.perf_counter() - t0,
    }


def boot_ci(x, n=2000, seed=0):
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    m = np.sort([rng.choice(x, len(x)).mean() for _ in range(n)])
    return float(m[int(0.025 * n)]), float(m[int(0.975 * n) - 1])


def summarise(rows, baseline="independent"):
    out = []
    for sc in sorted({r["scenario"] for r in rows}):
        by = {(r["mode"], r["seed"]): r["mean"] for r in rows if r["scenario"] == sc}
        for mode in sorted({m for m, _ in by}):
            ds = [by[mode, s] - by[baseline, s] for m, s in by if m == mode and (baseline, s) in by]
            if ds and mode != baseline:
                out.append(
                    {
                        "scenario": sc,
                        "mode": mode,
                        "vs": baseline,
                        "n": len(ds),
                        "mean_diff": float(np.mean(ds)),
                        "ci95": boot_ci(ds),
                        "wins": sum(d > 0 for d in ds),
                    }
                )
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=3, help="experiment seeds (preliminary if <10)")
    p.add_argument("--episodes", type=int, default=20)
    p.add_argument("--modes", nargs="+", default=list(MODES), choices=MODES)
    p.add_argument("--scenarios", nargs="+", default=list(SCENARIOS), choices=SCENARIOS)
    p.add_argument("--out", default="experiments/out")
    a = p.parse_args(argv)
    seeds = list(range(a.seeds))
    check_seeds(seeds, a.episodes)
    steps, rows, walls = [0], [], []
    for sc in a.scenarios:
        for m in a.modes:
            for s in seeds:
                rows.append(run_cell(m, sc, s, a.episodes, steps))
                walls.append(rows[-1].pop("wall_s"))  # timing is nondeterministic: manifest only
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # write bytes: write_text emits CRLF on Windows but git stores LF, which breaks the hashes
    (out / "raw.jsonl").write_bytes("".join(json.dumps(r) + "\n" for r in rows).encode())
    summ = summarise(rows)
    cfg = {
        "args": vars(a),
        "val": list(VAL),
        "test": list(TEST),
        # shell-neutral: set env, then run argv from the repo root (sh, PowerShell, cmd)
        "rerun": {
            "env": {"PYTHONPATH": os.pathsep.join(["packages/learning", "packages/sim"])},
            "argv": [sys.executable, *sys.argv],
        },
        "train_env_steps": steps[0],
        "note": f"n={a.seeds} experiment seeds: preliminary; CIs are bootstrap over seeds, "
        "wide for small n; no superiority claims without CI excluding 0.",
    }
    (out / "summary.json").write_bytes(
        json.dumps({"config": cfg, "paired_vs_independent": summ}, indent=1).encode()
    )
    cfg["wall_s"] = sum(walls)  # unhashed: keeps reruns byte-identical
    cfg["cpu_s"] = time.process_time()  # slice 3 cap: 30 CPU-min, 2 GB evidence per sweep
    cfg["evidence_bytes"] = sum(f.stat().st_size for f in out.glob("*") if f.is_file())
    assert cfg["cpu_s"] < 30 * 60 and cfg["evidence_bytes"] < 2 * 2**30, "sweep exceeded local cap"
    cfg["sha256"] = {
        f: hashlib.sha256((out / f).read_bytes()).hexdigest() for f in ("raw.jsonl", "summary.json")
    }
    (out / "manifest.json").write_bytes(json.dumps(cfg, indent=1).encode())
    for r in summ:
        print(
            f"{r['scenario']:13} {r['mode']:17} n={r['n']} "
            f"diff={r['mean_diff']:+.3f} ci95={r['ci95']}"
        )


if __name__ == "__main__":
    main()

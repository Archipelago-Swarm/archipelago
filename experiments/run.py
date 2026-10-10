"""Offline experiment harness (protocol exp-protocol-v1): five required modes plus labeled extras.

Required comparisons: rule (explorer), idle, independent, info_only, p2p. Secondary (not validated
claims): replay_sharing, central_online, ctde. See experiments/README.md and --help.
Backend extension point: add an entry to BACKENDS (the live-runtime task registers "torch").
"""

from __future__ import annotations

import argparse
import copy
import csv
import dataclasses
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import protocol_harness as H
from archipelago_learning.dqn import Learner
from archipelago_learning.peer import encode, offer
from archipelago_sim.env import ACTIONS, explorer_policy

REQUIRED = ("rule", "idle", "independent", "info_only", "p2p")
SECONDARY = ("replay_sharing", "central_online", "ctde")
MODES = REQUIRED + SECONDARY
LABELS = {
    "rule": "required: rule-based explorer (visit memory, no learning)",
    "idle": "required: idle control (all drones stay)",
    "independent": "required: independent DQN",
    "info_only": "required: independent DQN + map/status sharing (no model transfer)",
    "p2p": "required: info_only + validated peer model candidates",
    "replay_sharing": "secondary: independent DQN + raw replay-row sharing (not in evaluation.md)",
    "central_online": "secondary: ONE shared learner stands in for a controller; not a validated "
    "central-controller comparison",
    "ctde": "secondary: per-node actors + joint-critic reward shaping; an approximation, not a "
    "validated CTDE algorithm",
}
INFO_MODES = ("info_only", "p2p")
NOTRAIN = ("rule", "idle")
SCENARIO_NAMES = tuple(H.SCENARIOS)


def _numpy_learner(node, obs_dim, seed, **kw):
    return Learner(node, obs_dim, len(ACTIONS), seed=seed, **kw)


# Extension point: the PyTorch runtime registers a factory with the same signature here.
BACKENDS = {"numpy": _numpy_learner}


@dataclasses.dataclass(frozen=True)
class CellConfig:
    episodes: int = 30
    exchange_every: int = 5  # model/replay swap window after every Nth training episode
    margin: float = 0.0  # p2p acceptance margin on validation return
    val_seeds: tuple = H.VAL
    test_seeds: tuple = H.TEST
    backend: str = "numpy"
    obs: str = H.OBS_ID  # default stays grid-flat-v0; v1-map is an opt-in proposal


class Budget:
    """Per-cell counters. A fresh instance per cell: nothing is shared across cells."""

    def __init__(self):
        self.episodes = self.env_ticks = self.agent_steps = self.transitions = 0
        self.act_calls = self.replay_rows_received = 0
        self.info_bytes = self.model_bytes = self.replay_bytes = 0
        self.validation_evals = self.validation_env_ticks = 0
        self.blocked_agent_steps = 0  # central_online: control link cut, drone forced to stay


def share_obs(src, dst, k):
    """replay_sharing: copy src's newest k raw transitions into dst's replay (no parameters)."""
    for i in range(src.n - min(k, src.capacity), src.n):
        j = i % src.capacity
        dst.observe(*(src.replay[f][j] for f in ("o", "a", "r", "o2", "d")))


class Cell:
    """One (mode, scenario, experiment seed) run: train under the schedule, score on frozen TEST."""

    def __init__(self, mode, scenario, seed, cfg=None):
        assert mode in MODES, mode
        H.check_seeds([seed], (cfg or CellConfig()).episodes)
        self.mode, self.seed, self.cfg = mode, seed, cfg or CellConfig()
        assert set(self.cfg.test_seeds) <= set(H.TEST) and set(self.cfg.val_seeds) <= set(H.VAL)
        self.scen = H.SCENARIOS[scenario]
        self.env = H.make_env(self.cfg.obs)
        self.agents = list(self.env.possible_agents)
        self.bud = Budget()
        self.decisions, self.decision_wall, self.critic, self.episode_log = [], [], None, []
        self.train_seeds = []
        self.info = mode in INFO_MODES
        self.L = {}
        if mode in NOTRAIN:
            return
        mk = BACKENDS[self.cfg.backend]
        od = H.obs_dim(self.cfg.obs)
        kw = {"mode": "information_only"} if mode in ("info_only", "replay_sharing") else {}
        base = {a: mk(a, od, seed * 10 + k, **kw) for k, a in enumerate(self.agents)}
        self.L = (
            dict.fromkeys(self.agents, base[self.agents[0]]) if mode == "central_online" else base
        )
        if mode == "ctde":  # joint-observation critic: training only, never used at inference
            self.critic = Learner("critic", len(self.agents) * od, 1, seed=seed * 10 + 9)

    # ---------------------------------------------------------------- acting
    def blocked(self, scen, tick):
        """central_online fallback: while its node<->controller link is cut a drone stays put.
        Assumption (documented): the same window as the peer cut is applied to that path."""
        return self.mode == "central_online" and bool(
            scen.cut and scen.cut[0] <= tick < scen.cut[1]
        )

    def train_act(self, scen):
        def act(a, o, t):
            if self.blocked(scen, t):
                self.bud.blocked_agent_steps += 1
                return 0
            self.bud.act_calls += 1
            return self.L[a].act(o, H.EPS)

        return act

    def hook(self, scen):
        names, bud = self.agents, self.bud
        zero = np.zeros(self.critic.obs_dim // len(names), np.float32) if self.critic else None

        def joint(o):
            return np.concatenate([o[a] if a in o else zero for a in names])

        def hook(obs, acts, rew, nxt, term, t):
            if self.blocked(scen, t):
                return  # controller never receives these transitions
            if self.critic is not None:
                c = self.critic
                done = all(term.values()) or t + 1 >= H.ENV_KW["max_ticks"]
                j, j2 = joint(obs), joint(nxt)
                c.observe(j, 0, float(np.mean(list(rew.values()))), j2, done)
                c.train_step()
                shape = c.gamma * (0.0 if done else float(c.forward(c.params, j2)[1][0]))
                shape -= float(c.forward(c.params, j)[1][0])
            else:
                shape = 0.0
            for a in acts:  # done=term only: time-limit truncation must still bootstrap
                self.L[a].observe(obs[a], acts[a], rew[a] + shape, nxt[a], term[a])
                bud.transitions += 1
                self.L[a].train_step()

        return hook

    # ---------------------------------------------------------------- validation + swaps
    def validate(self, params):
        """Mean greedy return of `params` shared by all nodes on the node-private VAL seeds."""
        probe = BACKENDS[self.cfg.backend]("eval", self.L[self.agents[0]].obs_dim, 0)
        probe.params = params
        rets = []
        for s in self.cfg.val_seeds:
            rec = H.play(
                self.env,
                H.SCENARIOS["connected"],
                s,
                lambda a, o, t: probe.act(o, 0.0),
                info=self.info,
            )
            self.bud.validation_env_ticks += rec["ticks"]
            rets.append(rec["ret"])
        return float(np.mean(rets))

    def swap(self, i):
        n = self.agents
        if self.mode == "replay_sharing":
            new = {a: self.L[a].n - self._shared_n.get(a, 0) for a in n}
            for k, a in enumerate(n):
                b = n[(k + 1) % len(n)]
                share_obs(self.L[a], self.L[b], new[a])
                self.bud.replay_rows_received += new[a]
                self.bud.replay_bytes += new[a] * 4 * (2 * self.L[a].obs_dim + 3)  # float32 rows
            self._shared_n = {a: self.L[a].n for a in n}  # received rows are not re-sent
            return
        payloads = {a: encode(self.L[a]) for a in n}  # all candidates fixed before any is applied
        for k, a in enumerate(n):
            b = n[(k + 1) % len(n)]
            calls, ticks0 = [0], self.bud.validation_env_ticks

            def eval_fn(p, calls=calls):
                calls[0] += 1
                return self.validate(p)

            t0 = time.perf_counter()
            ev = offer(self.L[b], payloads[a], eval_fn, margin=self.cfg.margin, sender=a)
            self.decision_wall.append(time.perf_counter() - t0)
            evals = calls[0] * len(self.cfg.val_seeds)
            self.bud.validation_evals += evals
            self.bud.model_bytes += len(payloads[a])
            self.decisions.append(
                {
                    "episode": i,
                    "src": a,
                    "dst": b,
                    "accepted": bool(ev["accepted"]),
                    "reason": ev.get("reason"),
                    "evaluations": evals,  # validation episodes played to reach this decision
                    "eval_env_ticks": self.bud.validation_env_ticks - ticks0,
                    "bytes": len(payloads[a]),
                    "current_score": ev.get("current_score"),
                    "candidate_score": ev.get("candidate_score"),
                }
            )

    # ---------------------------------------------------------------- run
    def train(self):
        E, s0 = self.cfg.episodes, H.TRAIN_BASE + self.seed * self.cfg.episodes
        self._shared_n = {}
        for i in range(E):
            sc = self.scen.for_episode(i, E)
            self.train_seeds.append(s0 + i)
            rec = H.play(self.env, sc, s0 + i, self.train_act(sc), self.hook(sc), info=self.info)
            b = self.bud
            b.episodes += 1
            b.env_ticks += rec["ticks"]
            b.agent_steps += rec["agent_steps"]
            b.info_bytes += rec["info_bytes"]
            self.episode_log.append((rec["ticks"], rec["agent_steps"]))
            swap_now = i % self.cfg.exchange_every == self.cfg.exchange_every - 1
            if (
                swap_now
                and self.mode in ("p2p", "replay_sharing")
                and self.scen.model_link_up(i, E)
            ):
                self.swap(i)

    def test_policy(self):
        if self.mode == "idle":
            return lambda s: lambda a, o, t: 0
        if self.mode == "rule":

            def factory(s):
                w = self.env.world
                rng = {a: random.Random(f"{s}-{a}") for a in self.agents}
                visits = {a: {} for a in self.agents}  # fresh memory every episode
                return lambda a, o, t: ACTIONS.index(
                    explorer_policy(w.observe(a), visits[a], rng[a])
                )

            return factory
        probes = {a: copy.deepcopy(self.L[a]) for a in self.agents}
        snaps = {a: probes[a].snapshot() for a in self.agents}
        scen = self.scen

        def factory(s):
            return lambda a, o, t: 0 if self.blocked(scen, t) else probes[a].act(o, 0.0, snaps[a])

        return factory

    def run(self):
        t0 = time.perf_counter()
        if self.mode not in NOTRAIN:
            self.train()
        factory = self.test_policy()
        recs = [
            H.play(self.env, self.scen, s, factory(s), info=self.info) for s in self.cfg.test_seeds
        ]
        b = self.bud
        learners = list({id(x): x for x in self.L.values()}.values())
        updates = sum(x.steps for x in learners) + (self.critic.steps if self.critic else 0)
        keys = sorted({k for r in recs for k in r["reached"]})
        budget = {
            **vars(b),
            "trains": self.mode not in NOTRAIN,
            "train_env_steps": b.env_ticks,  # per cell; world ticks of this cell's training only
            "optimizer_updates": updates,
            "update_samples": updates * 32,  # batch size 32 per Adam step
            "train_episode_ticks": [t for t, _ in self.episode_log],
            "train_episode_agent_steps": [s for _, s in self.episode_log],
        }
        steps = sum(r["agent_steps"] for r in recs)
        return {
            "protocol": H.PROTOCOL,
            "mode": self.mode,
            "label": LABELS[self.mode],
            "scenario": self.scen.name,
            "seed": self.seed,
            "backend": self.cfg.backend,
            "episodes": self.cfg.episodes,
            "returns": [r["ret"] for r in recs],
            "mean": float(np.mean([r["ret"] for r in recs])),
            "coverage": [r["coverage"] for r in recs],
            "found": [r["found"] for r in recs],
            "ticks": [r["ticks"] for r in recs],
            "collisions_per_agent_step": sum(r["collisions"] for r in recs) / max(1, steps),
            "min_battery": min(r["min_battery"] for r in recs),
            "fault_reached": {
                k: float(np.mean([r["reached"].get(k, False) for r in recs])) for k in keys
            },
            "test_info_bytes": sum(r["info_bytes"] for r in recs),
            "telemetry": recs[-1]["telemetry"],
            "budget": budget,
            "decisions": self.decisions,
            "rejected_exchanges": sum(not d["accepted"] for d in self.decisions),
            "replay_hashes": [r["actions_sha"] for r in recs],
            "wall_s": time.perf_counter() - t0,
            "decision_wall_s": self.decision_wall,
        }


def run_cell(mode, scenario, seed, cfg=None):
    return Cell(mode, scenario, seed, cfg).run()


# ---------------------------------------------------------------------------------- statistics
def boot_ci(x, n=2000, seed=0):
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    m = np.sort([rng.choice(x, len(x)).mean() for _ in range(n)])
    return float(m[int(0.025 * n)]), float(m[int(0.975 * n) - 1])


def summarise(rows, baselines=("independent", "idle")):
    out = []
    for sc in sorted({r["scenario"] for r in rows}):
        by = {(r["mode"], r["seed"]): r["mean"] for r in rows if r["scenario"] == sc}
        for base in baselines:
            for mode in sorted({m for m, _ in by}):
                ds = [by[mode, s] - by[base, s] for m, s in by if m == mode and (base, s) in by]
                if ds and mode != base:
                    out.append(
                        {
                            "scenario": sc,
                            "mode": mode,
                            "vs": base,
                            "n": len(ds),
                            "mean_diff": float(np.mean(ds)),
                            "ci95": boot_ci(ds),
                            "wins": sum(d > 0 for d in ds),
                        }
                    )
    return out


def git(*args):
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    start = datetime.now(UTC).isoformat(timespec="seconds")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seeds", type=int, default=3, help="experiment seeds (preliminary if <10)")
    p.add_argument("--episodes", type=int, default=30, help="training episodes per cell")
    p.add_argument(
        "--mode",
        "--modes",
        dest="modes",
        nargs="+",
        default=["required"],
        choices=[*MODES, "required", "secondary", "all"],
        help="modes to run; 'required' = the five required comparisons",
    )
    p.add_argument("--scenarios", nargs="+", default=list(SCENARIO_NAMES), choices=SCENARIO_NAMES)
    p.add_argument("--backend", default="numpy", choices=sorted(BACKENDS))
    p.add_argument("--obs", default=H.OBS_ID, choices=H.OBS_IDS, help="observation version")
    p.add_argument("--exchange-every", type=int, default=5)
    p.add_argument("--margin", type=float, default=0.0)
    p.add_argument("--test-seeds", type=int, default=len(H.TEST), help="first N frozen TEST seeds")
    p.add_argument("--out", default="experiments/out")
    p.add_argument("--report", action="store_true", help="also write REPORT.md via report.py")
    a = p.parse_args(argv)
    modes = []
    for m in a.modes:
        modes += {"required": REQUIRED, "secondary": SECONDARY, "all": MODES}.get(m, (m,))
    modes = list(dict.fromkeys(modes))
    cfg = CellConfig(
        a.episodes, a.exchange_every, a.margin, H.VAL, H.TEST[: a.test_seeds], a.backend, a.obs
    )
    seeds = list(range(a.seeds))
    train = H.check_seeds(seeds, a.episodes)
    rows, walls = [], []
    for sc in a.scenarios:
        for m in modes:
            for s in seeds:
                rows.append(run_cell(m, sc, s, cfg))
                walls.append((rows[-1].pop("wall_s"), rows[-1].pop("decision_wall_s")))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # bytes: write_text emits CRLF on Windows but git stores LF, which breaks the hashes
    (out / "raw.jsonl").write_bytes("".join(json.dumps(r) + "\n" for r in rows).encode())
    cols = ["scenario", "mode", "seed", "mean", "coverage", "found", "transitions", "updates"]
    with (out / "per_seed.csv").open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow(
                [
                    r["scenario"],
                    r["mode"],
                    r["seed"],
                    f"{r['mean']:.6f}",
                    f"{np.mean(r['coverage']):.6f}",
                    f"{np.mean(r['found']):.4f}",
                    r["budget"]["transitions"],
                    r["budget"]["optimizer_updates"],
                ]
            )
    summ = summarise(rows)
    (out / "summary.json").write_bytes(
        json.dumps(
            {
                "paired": summ,
                "note": f"n={a.seeds} experiment seeds"
                + (": preliminary" if a.seeds < 10 else "")
                + "; CIs are bootstrap over seeds.",
            },
            indent=1,
        ).encode()
    )
    timing = [
        {
            "scenario": r["scenario"],
            "mode": r["mode"],
            "seed": r["seed"],
            "wall_s": w,
            "decision_wall_s": d,
        }
        for r, (w, d) in zip(rows, walls, strict=True)
    ]
    (out / "timing.jsonl").write_bytes("".join(json.dumps(t) + "\n" for t in timing).encode())
    hashed = ("raw.jsonl", "per_seed.csv", "summary.json")
    commit, dirty = (
        git("rev-parse", "HEAD"),
        bool(git("status", "--porcelain", "--", "experiments", "packages")),
    )
    manifest = {
        "protocol": H.PROTOCOL,
        "commit": commit,
        "worktree_dirty": dirty,
        "start_utc": start,
        "end_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "exit_status": 0,
        "commands": {
            "env": {
                "PYTHONPATH": os.pathsep.join(["packages/learning", "packages/sim", "experiments"])
            },
            "argv": [Path(sys.executable).name, "experiments/run.py", *argv],
        },
        "args": {k: v for k, v in vars(a).items()},
        "resolved_modes": modes,
        "mode_labels": {m: LABELS[m] for m in modes},
        "backend": a.backend,
        "seeds": {
            "experiment_seeds": seeds,
            "train_world_seeds": [min(train), max(train)],
            "train_formula": f"{H.TRAIN_BASE} + seed*episodes + episode",
            "validation": list(H.VAL),
            "test": list(cfg.test_seeds),
        },
        "config_hash": H.config_hash(
            {"cell": dataclasses.asdict(cfg) | {"val_seeds": None, "test_seeds": None}}
        ),
        "reward_id": H.REWARD_ID,
        "reward_hash": H.reward_hash(),
        "observation_id": a.obs,
        "scenario_hashes": {k: H.sha(dataclasses.asdict(v)) for k, v in H.SCENARIOS.items()},
        "env": H.ENV_KW,
        "container_image": None,
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "cpus": os.cpu_count(),
        },
        "wall_s": sum(w for w, _ in walls),  # unhashed: keeps reruns byte-identical
        "cpu_s": time.process_time(),
        "evidence_bytes": sum(f.stat().st_size for f in out.glob("*") if f.is_file()),
        "unhashed_files": ["timing.jsonl", "manifest.json", "REPORT.md"],
        "sha256": {f: hashlib.sha256((out / f).read_bytes()).hexdigest() for f in hashed},
    }
    assert manifest["cpu_s"] < 30 * 60 and manifest["evidence_bytes"] < 2 * 2**30, "sweep over cap"
    (out / "manifest.json").write_bytes(json.dumps(manifest, indent=1).encode())
    if a.report:
        import report

        report.write_report(out)
    for r in summ:
        if r["vs"] == "independent":
            print(
                f"{r['scenario']:20} {r['mode']:15} n={r['n']} "
                f"diff={r['mean_diff']:+.3f} ci95={r['ci95']}"
            )


if __name__ == "__main__":
    main()

"""T37 variant study: do decentralized learners beat idle/rule once the problem is learnable?

Pre-registered in experiments/prereg/T37.yaml (committed before any comparison was run).
One command reproduces everything (seeded):

    PYTHONPATH=packages/learning:packages/sim:experiments python experiments/t37.py all

Stages (each also runnable alone): ``stageA`` (successive halving, small budget), ``stageB``
(finalists, full budget, models saved), ``select`` (freezes ONE config from stage B selection
worlds), ``test`` (one-shot on the frozen TEST seeds 200-219; refuses to run twice), ``report``.
Selection only ever sees training seeds (>= 1000), validation seeds 100-104 and held-out
training-range worlds 5000-5019 (never trained on). TEST seeds are touched by ``test`` alone.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import random
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import protocol_harness as H
import yaml
from archipelago_learning.dqn import Learner
from archipelago_sim.env import ACTIONS, REWARD_SPECS, explorer_policy

ROOT = Path(__file__).resolve().parents[1]
PREREG = ROOT / "experiments" / "prereg" / "T37.yaml"
OUT = ROOT / "experiments" / "out" / "T37"
VAL = H.VAL  # 100-104
SEL_EXTRA = tuple(range(5000, 5020))  # held-out worlds from the training range, never trained on
SEL_WORLDS = VAL + SEL_EXTRA
TRAIN_CAP = 5000  # training world seeds must stay below this (so SEL_EXTRA is held out)
REF_REWARD = "rew-v1"  # reward-independent yardstick: counters re-scored with this spec
HIDDEN, GAMMA, BATCH, TARGET_EVERY = 32, 0.95, 32, 50


# --------------------------------------------------------------------------------- configuration
@dataclasses.dataclass(frozen=True)
class Config:
    obs: str = H.OBS_ID
    reward: str = "rew-v0"
    eps_start: float = 0.2
    eps_end: float = 0.2
    eps_frac: float = 0.0  # fraction of training episodes over which epsilon decays linearly
    lr: float = 1e-2
    replay: int = 5000
    double: bool = False
    episodes: int = 100

    @property
    def id(self) -> str:
        sched = (
            f"eps{self.eps_start:g}-{self.eps_end:g}@{self.eps_frac:g}"
            if self.eps_frac
            else f"eps{self.eps_start:g}"
        )
        dq = "ddqn" if self.double else "dqn"
        return f"{self.obs}|{self.reward}|{sched}|lr{self.lr:g}|rb{self.replay}|{dq}"

    def epsilon(self, episode: int) -> float:
        if not self.eps_frac:
            return self.eps_start
        span = max(1.0, self.eps_frac * self.episodes)
        f = min(1.0, episode / span)
        return self.eps_start + (self.eps_end - self.eps_start) * f


def ref_return(rec: dict, n_agents: int) -> float:
    """Episode return per agent under REF_REWARD recomputed from env counters (spawn-free)."""
    new, tgt, step, coll, _ = REWARD_SPECS[REF_REWARD]
    from archipelago_sim.env import REWARD_EXTRA

    rev, c = REWARD_EXTRA[REF_REWARD][0], rec["counters"]
    return (
        new * c["new_cells"]
        + rev * c["revisits"]
        + coll * (c["wall_collisions"] + c["agent_collisions"])
        + step * c["agent_ticks"]
        + tgt * rec["targets_after_spawn"]
    ) / n_agents


# ------------------------------------------------------------------------------------- learner
class VLearner(Learner):
    """NumPy DQN with optional double-DQN targets (action picked by the online net)."""

    def __init__(self, *a, double: bool = False, **kw):
        super().__init__(*a, **kw)
        self.double = double

    def train_step(self, batch=BATCH, target_every=TARGET_EVERY):
        if not self.double:
            return super().train_step(batch, target_every)
        size = min(self.n, self.capacity)
        if self.paused or size < batch:
            return None
        idx = self.rng.integers(size, size=batch)
        b = {k: v[idx] for k, v in self.replay.items()}
        h, q = self.forward(self.params, b["o"])
        rows = np.arange(batch)
        best = self.forward(self.params, b["o2"])[1].argmax(1)
        nxt = self.forward(self.target, b["o2"])[1][rows, best]
        y = b["r"] + self.gamma * (1 - b["d"]) * nxt
        err = q[rows, b["a"]] - y
        gq = np.zeros_like(q)
        gq[rows, b["a"]] = err / batch
        gh = (gq @ self.params["w2"].T) * (h > 0)
        g = {"w2": h.T @ gq, "b2": gq.sum(0), "w1": b["o"].T @ gh, "b1": gh.sum(0)}
        self.opt["t"] += 1
        t = self.opt["t"]
        for k, gk in g.items():
            m = self.opt[f"m_{k}"] = 0.9 * self.opt[f"m_{k}"] + 0.1 * gk
            v = self.opt[f"v_{k}"] = 0.999 * self.opt[f"v_{k}"] + 0.001 * gk * gk
            self.params[k] -= (
                self.lr * (m / (1 - 0.9**t)) / (np.sqrt(v / (1 - 0.999**t)) + 1e-8)
            ).astype(np.float32)
        self.steps += 1
        self.version += 1
        if self.steps % target_every == 0:
            self.target = {k: v.copy() for k, v in self.params.items()}
        return float((err**2).mean())


def make_learner(cfg: Config, node: str, obs_dim: int, seed: int) -> VLearner:
    lr = VLearner(
        node,
        obs_dim,
        len(ACTIONS),
        hidden=HIDDEN,
        seed=seed,
        lr=cfg.lr,
        gamma=GAMMA,
        capacity=cfg.replay,
        double=cfg.double,
    )
    lr.events = []  # keep memory flat: per-step events are not used here
    return lr


# ------------------------------------------------------------------------------- episode runner
def run_world(env, seed, act, info=False):
    rec = H.play(env, H.SCENARIOS["connected"], seed, act, info=info)
    rec["ref_return"] = ref_return(rec, len(env.possible_agents))
    return rec


def metrics(rec: dict) -> dict:
    keep = ("ref_return", "coverage_gain", "targets_after_spawn", "ticks", "collisions")
    out = {k: float(rec[k]) for k in keep}
    c = rec["counters"]
    out["revisit_rate"] = c["revisits"] / max(1, c["agent_ticks"])
    out["wall_collisions"] = float(c["wall_collisions"])
    return out


def eval_policy(obs_id: str, make_act, worlds, info=False) -> list[dict]:
    """make_act(env, seed) -> act(agent, obs, tick). Greedy/deterministic policies only."""
    env = H.make_env(obs_id, REF_REWARD)
    return [metrics(run_world(env, s, make_act(env, s), info=info)) for s in worlds]


def idle_act(env, s):
    return lambda a, o, t: 0


def rule_act(env, s):
    rng = {a: random.Random(f"{s}-{a}") for a in env.possible_agents}
    visits = {a: {} for a in env.possible_agents}
    return lambda a, o, t: ACTIONS.index(explorer_policy(env.world.observe(a), visits[a], rng[a]))


def random_act(env, s):
    rng = random.Random(f"rand-{s}")
    return lambda a, o, t: rng.randrange(len(ACTIONS))


def policy_act(learners):
    def make(env, s):
        snaps = {a: learners[a].snapshot() for a in learners}
        return lambda a, o, t: learners[a].act(o, 0.0, snaps[a])

    return make


# ---------------------------------------------------------------------------------- training
def check_world_seeds(worlds, allow_test=False):
    ws = set(worlds)
    assert allow_test or not ws & set(H.TEST), "TEST seeds are not allowed here"
    return ws


def train_cell(cfg: Config, seed: int, checkpoints: int = 0, save_dir: str | None = None) -> dict:
    """Train one (config, experiment seed) cell; evaluate greedy on the selection worlds."""
    t0 = time.perf_counter()
    info = cfg.obs == H.V2_SHARED
    train_worlds = [H.TRAIN_BASE + seed * cfg.episodes + i for i in range(cfg.episodes)]
    assert max(train_worlds) < TRAIN_CAP and not set(train_worlds) & set(SEL_WORLDS + H.TEST)
    check_world_seeds(train_worlds)
    env = H.make_env(cfg.obs, cfg.reward)
    od = H.obs_dim(cfg.obs)
    L = {a: make_learner(cfg, a, od, seed * 10 + k) for k, a in enumerate(env.possible_agents)}
    curve, train_log = [], []
    marks = {round(cfg.episodes * j / checkpoints) for j in range(1, checkpoints + 1)}
    for i, w in enumerate(train_worlds):
        eps = cfg.epsilon(i)

        def act(a, o, t, eps=eps):
            return L[a].act(o, eps)

        def hook(obs, acts, rew, nxt, term, t):
            for a in acts:
                L[a].observe(obs[a], acts[a], rew[a], nxt[a], term[a])
                L[a].train_step()

        rec = H.play(env, H.SCENARIOS["connected"], w, act, hook, info=info)
        train_log.append(
            [round(rec["ret"], 4), rec["coverage_gain"], rec["targets_after_spawn"], rec["ticks"]]
        )
        if (i + 1) in marks:
            ev = eval_policy(cfg.obs, policy_act(L), VAL, info=info)
            curve.append(
                {"episode": i + 1}
                | {k: float(np.mean([e[k] for e in ev])) for k in ("ref_return", "coverage_gain")}
            )
    ev = eval_policy(cfg.obs, policy_act(L), SEL_WORLDS, info=info)
    if save_dir:
        d = Path(save_dir)
        d.mkdir(parents=True, exist_ok=True)
        np.savez(
            d / f"{cfg.id.replace('|', '_')}_s{seed}.npz",
            **{f"{a}_{k}": v for a, lr in L.items() for k, v in lr.params.items()},
        )
    return {
        "config": cfg.id,
        "seed": seed,
        "sel": ev,  # metrics per selection world (VAL first, then SEL_EXTRA)
        "curve": curve,
        "train_log": train_log,
        "updates": sum(lr.steps for lr in L.values()),
        "transitions": sum(lr.n for lr in L.values()),
        "wall_s": time.perf_counter() - t0,
    }


def _job(args):
    cfg, seed, ck, sd = args
    return train_cell(Config(**cfg), seed, ck, sd)


def run_cells(cfgs, seeds, checkpoints=0, save_dir=None, workers=4):
    jobs = [(dataclasses.asdict(c), s, checkpoints, save_dir) for c in cfgs for s in seeds]
    with ProcessPoolExecutor(workers) as ex:
        return list(ex.map(_job, jobs))


# ---------------------------------------------------------------------------------- statistics
def hboot(diff: np.ndarray, n: int = 4000, seed: int = 0) -> tuple[float, ...]:
    """diff[seed, world]. Returns (mean, lo, hi, lo_seed_only, hi_seed_only): two 95% CIs.

    Hierarchical: resample experiment seeds, then worlds within the draw. Seed-only: resample
    seeds and average over worlds first. Both 95 percent percentile intervals.
    """
    rng = np.random.default_rng(seed)
    s, w = diff.shape
    h, so = np.empty(n), np.empty(n)
    per_seed = diff.mean(1)
    for b in range(n):
        si = rng.integers(s, size=s)
        wi = rng.integers(w, size=w)
        h[b] = diff[np.ix_(si, wi)].mean()
        so[b] = per_seed[si].mean()
    q = lambda x: (float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5)))  # noqa: E731
    return float(diff.mean()), *q(h), *q(so)


def paired(learner, base, n=4000):
    """learner: [seed][world] metric matrix; base: [world] vector (deterministic baseline)."""
    d = np.asarray(learner, float) - np.asarray(base, float)[None, :]
    m, lo, hi, slo, shi = hboot(d, n)
    return {
        "mean_diff": m,
        "ci95": [lo, hi],
        "ci95_seed_only": [slo, shi],
        "wins": int((d.mean(1) > 0).sum()),
        "n_seeds": int(d.shape[0]),
    }


def matrix(rows, key, sl=slice(None)):
    return np.array([[w[key] for w in r["sel"][sl]] for r in rows], float)


# ------------------------------------------------------------------------------------ pipeline
def load_prereg():
    assert PREREG.exists(), "pre-registration missing: write experiments/prereg/T37.yaml first"
    return yaml.safe_load(PREREG.read_text())


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT).stdout.strip()


def prereg_provenance():
    sha = git("log", "-1", "--format=%H", "--", "experiments/prereg/T37.yaml")
    dirty = bool(git("status", "--porcelain", "--", "experiments/prereg/T37.yaml"))
    assert sha and not dirty, "T37.yaml must be committed (own commit) before any comparison"
    return {
        "commit": sha,
        "file_sha256": hashlib.sha256(PREREG.read_bytes()).hexdigest(),
        "head": git("rev-parse", "HEAD"),
    }


def configs_from(pre, key, episodes):
    return [Config(**{**c, "episodes": episodes}) for c in pre[key]]


def baselines_on(worlds):
    out = {}
    for name, f in (("idle", idle_act), ("rule", rule_act), ("random", random_act)):
        out[name] = eval_policy(H.OBS_ID, f, worlds)
    return out


def untrained_on(cfg: Config, seeds, worlds):
    """Same architecture/config, zero training (sham): greedy on random-init weights."""
    info = cfg.obs == H.V2_SHARED
    rows = []
    for s in seeds:
        L = {
            a: make_learner(cfg, a, H.obs_dim(cfg.obs), s * 10 + k)
            for k, a in enumerate(H.make_env(cfg.obs).possible_agents)
        }
        rows.append(eval_policy(cfg.obs, policy_act(L), worlds, info=info))
    return rows


def score(rows):
    return float(np.mean([w["ref_return"] for r in rows for w in r["sel"]]))


def stage_a(pre, out):
    cfgs = configs_from(pre, "stage_a_configs", pre["stage_a"]["episodes"])
    rows = run_cells(cfgs, range(pre["stage_a"]["seeds"]))
    by = {}
    for r in rows:
        by.setdefault(r["config"], []).append(r)
    ranked = sorted(by, key=lambda k: -score(by[k]))
    keep = ranked[: pre["stage_a"]["keep"]]
    res = {"ranking": [(k, score(by[k])) for k in ranked], "kept": keep, "rows": rows}
    (out / "stageA.json").write_text(json.dumps(res))
    return res


def stage_b(pre, out):
    a = json.loads((out / "stageA.json").read_text())
    ep = pre["stage_b"]["episodes"]
    kept = {c.id: c for c in configs_from(pre, "stage_a_configs", ep)}
    cfgs = [kept[k] for k in a["kept"]]
    for c in configs_from(pre, "stage_b_controls", ep):
        if c.id not in {x.id for x in cfgs}:
            cfgs.append(c)
    rows = run_cells(
        cfgs, range(pre["stage_b"]["seeds"]), pre["stage_b"]["checkpoints"], str(out / "models")
    )
    (out / "stageB.json").write_text(json.dumps({"rows": rows}))
    return rows


def select(pre, out):
    rows = json.loads((out / "stageB.json").read_text())["rows"]
    by = {}
    for r in rows:
        by.setdefault(r["config"], []).append(r)
    cand = [k for k in by if k not in {c.id for c in configs_from(pre, "stage_b_controls", 1)}]
    pool = cand or list(by)
    best = max(pool, key=lambda k: score(by[k]))
    n = len(VAL)
    base = baselines_on(SEL_WORLDS)
    table = {}
    for k, rs in by.items():
        table[k] = {
            m: {
                "val": float(matrix(rs, m, slice(0, n)).mean()),
                "sel_all": float(matrix(rs, m).mean()),
            }
            for m in ("ref_return", "coverage_gain", "targets_after_spawn", "wall_collisions")
        }
    sel = {
        "selected": best,
        "pool": pool,
        "rule": "max mean ref_return over 25 selection worlds (VAL 100-104 + 5000-5019) and seeds",
        "table": table,
        "baselines_sel": {
            b: {m: float(np.mean([w[m] for w in v])) for m in ("ref_return", "coverage_gain",
                                                              "targets_after_spawn")}
            for b, v in base.items()
        },
        "prereg": prereg_provenance(),
    }
    (out / "selection.json").write_text(json.dumps(sel, indent=1))
    return sel


def _config_by_id(pre, cid):
    for key in ("stage_a_configs", "stage_b_controls"):
        for c in configs_from(pre, key, pre["stage_b"]["episodes"]):
            if c.id == cid:
                return c
    raise KeyError(cid)


def _load_learners(cfg, seed, models):
    f = models / f"{cfg.id.replace('|', '_')}_s{seed}.npz"
    z = np.load(f)
    od = H.obs_dim(cfg.obs)
    L = {}
    for k, a in enumerate(H.make_env(cfg.obs).possible_agents):
        lr = make_learner(cfg, a, od, seed * 10 + k)
        lr.params = {p: z[f"{a}_{p}"].copy() for p in lr.params}
        L[a] = lr
    return L


def test_once(pre, out):
    """One-shot on frozen TEST worlds: selected config (stage B models) plus baselines."""
    marker = out / "TEST_DONE"
    assert not marker.exists(), "TEST seeds were already used once; refusing to run again"
    sel = json.loads((out / "selection.json").read_text())
    cfg = _config_by_id(pre, sel["selected"])
    marker.write_text(json.dumps({"config": cfg.id, "prereg": sel["prereg"]["commit"]}))
    worlds = H.TEST
    seeds = range(pre["stage_b"]["seeds"])
    info = cfg.obs == H.V2_SHARED
    mats = {m: [] for m in ("ref_return", "coverage_gain", "targets_after_spawn")}
    for s in seeds:
        ev = eval_policy(cfg.obs, policy_act(_load_learners(cfg, s, out / "models")), worlds, info)
        for m in mats:
            mats[m].append([w[m] for w in ev])
    base = baselines_on(worlds)
    sham = untrained_on(cfg, seeds, worlds)
    res = {"config": cfg.id, "worlds": list(worlds), "n_seeds": len(list(seeds)), "metrics": {}}
    for m, mat in mats.items():
        mat = np.array(mat)
        entry = {"learner_mean": float(mat.mean()), "vs": {}}
        for b, v in base.items():
            bv = np.array([w[m] for w in v])
            entry["vs"][b] = paired(mat, bv) | {"baseline_mean": float(bv.mean())}
        sm = np.array([[w[m] for w in r] for r in sham])
        entry["vs"]["untrained"] = paired(mat, sm.mean(0)) | {"baseline_mean": float(sm.mean())}
        res["metrics"][m] = entry
    (out / "test.json").write_text(json.dumps(res, indent=1))
    return res


def ci_excludes_zero_positive(p):
    return p["ci95"][0] > 0


def verdict(res, crit):
    """Pre-registered decision (see T37.yaml `decision`). Returns dict of booleans + text."""
    m = res["metrics"]
    names = ("ref_return", "coverage_gain", "targets_after_spawn")
    vs_idle = all(ci_excludes_zero_positive(m[k]["vs"]["idle"]) for k in names)
    vs_untrained = ci_excludes_zero_positive(m["ref_return"]["vs"]["untrained"])
    vs_random = ci_excludes_zero_positive(m["ref_return"]["vs"]["random"])
    helps = vs_idle and vs_untrained and vs_random
    vs_rule_ret = ci_excludes_zero_positive(m["ref_return"]["vs"]["rule"])
    rule_not_worse = all(m[k]["vs"]["rule"]["ci95"][1] >= 0 for k in names)
    return {
        "learning_helps_vs_idle_all_three_metrics": vs_idle,
        "beats_untrained_same_architecture": vs_untrained,
        "beats_random_policy_on_return": vs_random,
        "LEARNING_HELPS": helps,
        "beats_rule_on_return": vs_rule_ret,
        "BEATS_RULE": bool(helps and vs_rule_ret and rule_not_worse),
        "criteria": crit,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=["stageA", "stageB", "select", "test", "all", "report"])
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args(argv)
    pre = load_prereg()
    prov = prereg_provenance()
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    todo = {
        "all": ["stageA", "stageB", "select", "test", "report"],
    }.get(a.stage, [a.stage])
    for st in todo:
        t = time.perf_counter()
        if st == "stageA":
            stage_a(pre, OUT)
        elif st == "stageB":
            stage_b(pre, OUT)
        elif st == "select":
            select(pre, OUT)
        elif st == "test":
            res = test_once(pre, OUT)
            res["verdict"] = verdict(res, pre["decision"])
            res["prereg"] = prov
            (OUT / "test.json").write_text(json.dumps(res, indent=1))
        elif st == "report":
            import t37_report

            t37_report.write(OUT, pre)
        print(f"{st}: {time.perf_counter() - t:.0f}s", file=sys.stderr)
    print(f"total {time.perf_counter() - t0:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()

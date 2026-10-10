"""Train/evaluate Learners on the T03 grid sim and run a transfer-vs-control experiment."""

from __future__ import annotations

import copy

import numpy as np
from archipelago_sim.pz import GridParallelEnv

from .dqn import Learner
from .peer import encode, offer

ENV_KW = {"size": 8, "n_agents": 2, "n_targets": 2, "max_ticks": 60}


def make_env():
    return GridParallelEnv(**ENV_KW)


def make_learner(node_id, seed, **kw):
    env = make_env()
    return Learner(node_id, int(env.observation_space("node-0").shape[0]), 5, seed=seed, **kw)


def _norm(o):
    o = o.copy()
    o[-3:-1] /= ENV_KW["size"]
    return o


def episode(env, learners, seed, eps=0.0, train=True):
    """One episode; learners map agent -> Learner. Returns mean per-agent return."""
    obs, _ = env.reset(seed=seed)
    total = dict.fromkeys(env.possible_agents, 0.0)
    while env.agents:
        acts = {a: learners[a].act(_norm(obs[a]), eps) for a in env.agents}
        nxt, rew, term, trunc, _ = env.step(acts)
        for a in acts:  # done=term only: time-limit truncation must still bootstrap
            learners[a].observe(_norm(obs[a]), acts[a], rew[a], _norm(nxt[a]), term[a])
            total[a] += rew[a]
            if train:
                learners[a].train_step()
        obs = nxt
    return float(np.mean(list(total.values())))


def train(learner, episodes, seed0=0, eps=0.2):
    env = make_env()
    solo = {a: learner for a in env.possible_agents}  # one policy drives every agent slot
    for i in range(episodes):
        episode(env, solo, seed0 + i, eps)


def evaluate(params, seeds):
    """Greedy mean return of a parameter set over fixed seeds (no learning)."""
    env = make_env()
    probe = make_learner("eval", 0)
    probe.params = params
    return float(
        np.mean(
            [episode(env, dict.fromkeys(env.possible_agents, probe), s, 0.0, False) for s in seeds]
        )
    )


def transfer_experiment(
    seed, teacher_eps=40, student_eps=5, val=range(900, 904), test=range(950, 956)
):
    """Treated = student + gated teacher offer; control = identical student, no offer.

    The offer is gated on `val` seeds; both arms are scored on disjoint `test` seeds, so a
    regression is possible and reported (delta < 0).
    """
    teacher = make_learner("teacher", 1000 + seed)
    train(teacher, teacher_eps, seed0=seed * 100)
    control = make_learner("student", seed)
    train(control, student_eps, seed0=seed * 100 + 50)
    treated = copy.deepcopy(control)
    ev = offer(treated, encode(teacher), lambda p: evaluate(p, val))
    c, t = evaluate(control.params, test), evaluate(treated.params, test)
    return {"seed": seed, "accepted": ev["accepted"], "control": c, "treated": t, "delta": t - c}

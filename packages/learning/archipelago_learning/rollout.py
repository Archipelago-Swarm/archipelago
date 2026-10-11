"""Train/evaluate Learners on the T03 grid sim and run a transfer-vs-control experiment."""

from __future__ import annotations

import copy

import numpy as np
from archipelago_sim.pz import GridParallelEnv

from . import skills
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


def reset(env, seed, drop=()):
    """Reset; `drop`ped nodes are removed from the world entirely (no body, no wreck)."""
    obs, _ = env.reset(seed=seed)
    for a in drop:
        del env.world.drones[a]
        env.world.agents.remove(a)
        env.agents.remove(a)
        del obs[a]
    return obs


def episode(env, learners, seed, eps=0.0, train=True, drop=()):
    """One episode; learners map agent -> Learner. Returns mean per-agent return."""
    obs = reset(env, seed, drop)
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


def ctde_episode(env, actors, critic, seed, eps=0.2, drop=()):
    """CTDE: per-node actors act on local obs only; a joint-observation critic (training only)
    adds potential-based shaping gamma*V(s')-V(s) to each actor's reward. Dropped/finished
    nodes contribute zeros to the joint observation."""
    names = env.possible_agents
    obs = reset(env, seed, drop)
    zero = np.zeros(critic.obs_dim // len(names), np.float32)

    def joint(o):
        return np.concatenate([_norm(o[a]) if a in o else zero for a in names])

    def value(j):
        return float(critic.forward(critic.params, j)[1][0])

    while env.agents:
        j = joint(obs)
        acts = {a: actors[a].act(_norm(obs[a]), eps) for a in env.agents}
        nxt, rew, term, _, _ = env.step(acts)
        j2, done = joint(nxt), not env.agents
        critic.observe(j, 0, float(np.mean(list(rew.values()))), j2, done)
        critic.train_step()
        shape = critic.gamma * (0.0 if done else value(j2)) - value(j)
        for a in acts:  # done=term only: time-limit truncation must still bootstrap
            actors[a].observe(_norm(obs[a]), acts[a], rew[a] + shape, _norm(nxt[a]), term[a])
            actors[a].train_step()
        obs = nxt


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


def eval_skills(params, seeds):
    """Greedy per-skill proficiency of a parameter set over fixed seeds (no learning)."""
    env, runs = make_env(), []
    for s in seeds:
        obs = reset(env, s)
        while env.agents:
            acts = {
                a: int(np.argmax(Learner.forward(params, _norm(obs[a]))[1])) for a in env.agents
            }
            obs = env.step(acts)[0]
        runs.append(skills.world_skills(env.world))
    return skills.mean_skills(runs)


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

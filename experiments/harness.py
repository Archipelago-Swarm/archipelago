"""Offline experiment protocol (v1): config, seeds, fault scenarios, info sharing, episode loop.

Everything here is shared by every mode, so modes differ only in who acts and what they learn from.
The simulator and the NumPy learner (packages/sim, packages/learning) are used read-only.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass

import numpy as np
from archipelago_sim.env import MOVE_COST, REWARD_SPECS
from archipelago_sim.pz import GridParallelEnv

PROTOCOL = "exp-protocol-v1"
# 16x16 / 8 targets / 150 ticks: episodes end early once every target is found, so the world must
# be big enough that fault ticks (<= tick 25) are reached by essentially every rule-based episode.
# The T09 config (8x8, 2 targets, 60 ticks) ended in a median of ~7 ticks: faults never fired.
ENV_KW = {"size": 16, "n_agents": 2, "n_targets": 8, "max_ticks": 150}
REWARD_ID, OBS_ID = "rew-v0", "grid-flat-v0"
EPS = (
    0.2  # constant epsilon-greedy during training (no schedule); diagnosed in experiments/diagnosis
)

# Seed splits (evaluation.md: train 0-9 experiments, validation/smoke 100-104, final 200-219).
TRAIN_BASE = 1000  # world seed of experiment seed s, training episode i: TRAIN_BASE + s*E + i
VAL = tuple(range(100, 105))  # node-private candidate gating only
TEST = tuple(range(200, 220))  # final reporting only, never used for gating or tuning


def check_seeds(seeds, episodes, base=TRAIN_BASE, val=VAL, test=TEST):
    train = {base + s * episodes + i for s in seeds for i in range(episodes)}
    assert not (train & set(val)), "train/validation seed overlap"
    assert not (train & set(test)), "train/test seed overlap"
    assert not (set(val) & set(test)), "validation/test seed overlap"
    return train


@dataclass(frozen=True)
class Scenario:
    """Immutable fault schedule. Tick windows are within every episode (train, validation, test)."""

    name: str
    cut: tuple[int, int] | None = None  # peer links cut for world ticks [a, b)
    kill: tuple[str, int] | None = None  # node removed from the world before step `tick`
    kill_from: float = 0.5  # training: kill applies from this fraction of episodes (always at test)
    outage: tuple[int, int] | None = None  # telemetry sink blocked for ticks [a, b)
    model_cut: tuple[float, float] | None = None  # training episodes (fractions) with no model swap

    def for_episode(self, i, episodes):
        """The schedule seen by training episode i (kill only after kill_from)."""
        if self.kill and i < int(episodes * self.kill_from):
            return dataclasses.replace(self, kill=None)
        return self

    def peer_up(self, tick):
        return not (self.cut and self.cut[0] <= tick < self.cut[1])

    def model_link_up(self, i, episodes):
        """Is the episode-boundary model-exchange window open after training episode i?"""
        if self.model_cut and int(episodes * self.model_cut[0]) <= i < int(
            episodes * self.model_cut[1]
        ):
            return False
        return not (self.kill and i >= int(episodes * self.kill_from))

    def fault_ticks(self):
        out = {}
        if self.cut:
            out |= {"cut": self.cut[0], "rejoin": self.cut[1]}
        if self.kill:
            out["kill"] = self.kill[1] + 1  # needs `kill_tick + 1` completed ticks to act on it
        if self.outage:
            out |= {"outage_start": self.outage[0], "outage_end": self.outage[1]}
        return out


SCENARIOS = {
    s.name: s
    for s in (
        Scenario("connected"),
        Scenario("partition_reconnect", cut=(10, 25), model_cut=(1 / 3, 2 / 3)),
        Scenario("node_failure", kill=("node-1", 20)),
        Scenario("telemetry_outage", outage=(10, 25)),
    )
}


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=list).encode()).hexdigest()


def reward_hash():
    return sha({"id": REWARD_ID, "spec": REWARD_SPECS[REWARD_ID]})


def config_hash(extra=None):
    return sha(
        {
            "protocol": PROTOCOL,
            "env": ENV_KW,
            "reward": reward_hash(),
            "obs": OBS_ID,
            "eps": EPS,
            "train_base": TRAIN_BASE,
            "val": VAL,
            "test": TEST,
            "scenarios": {k: dataclasses.asdict(v) for k, v in SCENARIOS.items()},
            **(extra or {}),
        }
    )


def battery_reaches(ticks):
    """Does a full battery last `ticks` ticks even if every tick is a (costliest) move?"""
    return ENV_KW.get("battery_scale", 1.0) / MOVE_COST > ticks


OBS_IDS = (
    OBS_ID,
    "grid-flat-v1-map",
)  # v1 is an opt-in PROPOSAL, never the default (see diagnosis)
MAP_BLOCK = 4


def obs_dim(obs_id=OBS_ID):
    r = 2 * 2 + 1  # sense radius 2 crop
    return r * r + 3 + ((ENV_KW["size"] // MAP_BLOCK) ** 2 if obs_id == OBS_IDS[1] else 0)


def make_env(obs_id=OBS_ID):
    assert obs_id in OBS_IDS, obs_id
    env = GridParallelEnv(**ENV_KW)
    env.obs_id = obs_id
    return env


def flat(env, agent):
    """Normalised flat observation (same vector the learners train on).

    grid-flat-v0: 5x5 crop of the node's own buffer + pose/size + battery.
    grid-flat-v1-map (opt-in proposal): v0 + fraction of each 4x4 block of the map present in the
    node's buffer, which is where shared map summaries become visible to a policy.
    """
    d = env.world.drones[agent]
    o = env._flat(env.world.observe(agent))
    o[-3:-1] /= ENV_KW["size"]
    if getattr(env, "obs_id", OBS_ID) == OBS_IDS[1]:
        n = ENV_KW["size"] // MAP_BLOCK
        m = np.zeros((n, n), np.float32)
        for x, y in d.known:
            m[y // MAP_BLOCK, x // MAP_BLOCK] += 1.0 / MAP_BLOCK**2
        o = np.concatenate([o, m.ravel()])
    return o


def remove_node(env, name):
    """Node loss: the drone leaves the world entirely (no body, no wreck), as in reset(drop)."""
    del env.world.drones[name]
    env.world.agents.remove(name)
    env.agents.remove(name)


# ---------------------------------------------------------------- non-model information sharing
class InfoBus:
    """Deterministic map/status summaries shared between living nodes while the peer link is up.

    Message src->dst (per tick): header (node id, tick, battery; 4 bytes) + every cell src knows
    that it has not yet sent to dst and did not learn from dst (3 bytes: x, y, free/wall) +
    newly found markers (2 bytes each). dst merges cells it does not already know into its private
    `known` buffer (so they appear in its observation crop) and markers into `found`. Cells
    accumulate while the link is cut and are delivered after reconnection. No parameters, replay
    rows or policy outputs ever travel on this channel; modes info_only and p2p use it identically.
    """

    def __init__(self):
        self.sent = {}  # (src, dst) -> cells dst already has from/for src
        self.marker_sent = {}
        self.msgs = 0
        self.bytes = 0

    def exchange(self, world, link_up):
        if not link_up:
            return
        names = sorted(world.agents)
        plan = []
        for src in names:
            for dst in names:
                if src == dst:
                    continue
                s = world.drones[src]
                done = self.sent.setdefault((src, dst), set())
                cells = sorted((c, v) for c, v in s.known.items() if c not in done)
                marks = sorted(s.found - self.marker_sent.setdefault((src, dst), set()))
                plan.append((src, dst, cells, marks))
        for src, dst, cells, marks in plan:  # compute all messages first: order independent
            d = world.drones[dst]
            for c, v in cells:
                d.known.setdefault(c, v)
            d.found |= set(marks)
            self.sent[src, dst] |= {c for c, _ in cells}
            self.sent.setdefault((dst, src), set()).update(c for c, _ in cells)
            self.marker_sent[src, dst] |= set(marks)
            self.marker_sent.setdefault((dst, src), set()).update(marks)
            self.msgs += 1
            self.bytes += 4 + 3 * len(cells) + 2 * len(marks)


class Spool:
    """Telemetry sink model: samples queue while the sink is blocked and never delay anything."""

    def __init__(self, cap=64):
        self.cap, self.queue, self.delivered, self.dropped, self.peak = cap, 0, 0, 0, 0

    def push(self, blocked):
        if blocked:
            self.queue += 1
            if self.queue > self.cap:
                self.queue -= 1
                self.dropped += 1  # drop-oldest: count only
            self.peak = max(self.peak, self.queue)
        else:
            self.delivered += self.queue + 1
            self.queue = 0

    def summary(self):
        return {
            "delivered": self.delivered,
            "dropped": self.dropped,
            "peak": self.peak,
            "undelivered": self.queue,
        }


# --------------------------------------------------------------------------------- episode loop
def play(env, scen, seed, act, hook=None, info=False):
    """One episode. act(agent, normalised_obs, tick) -> action index.

    hook(obs, acts, rew, nxt, term, tick) is called after every step with dicts keyed by the agents
    that actually acted (killed nodes are absent), so any learning is done by the caller.
    Returns an episode record (deterministic given the inputs).
    """
    env.reset(seed=seed)
    w = env.world
    bus, spool = (InfoBus() if info else None), Spool()
    if bus:
        bus.exchange(w, scen.peer_up(0))
    obs = {a: flat(env, a) for a in env.agents}
    tot, log, agent_steps, colls = dict.fromkeys(env.possible_agents, 0.0), [], 0, 0
    killed_at = None
    while env.agents:
        t = w.tick
        if scen.kill and t == scen.kill[1] and scen.kill[0] in env.agents:
            remove_node(env, scen.kill[0])
            obs.pop(scen.kill[0], None)
            killed_at = t
            if not env.agents:
                break
        acts = {a: act(a, obs[a], t) for a in env.agents}
        log.append(acts)
        n_ev = len(w.events)
        _, rew, term, trunc, _ = env.step(acts)
        colls += sum("collision" in e["event"] for e in w.events[n_ev:])
        if bus:
            bus.exchange(w, scen.peer_up(w.tick))
        nxt = {a: flat(env, a) for a in acts}
        spool.push(bool(scen.outage and scen.outage[0] <= w.tick < scen.outage[1]))
        agent_steps += len(acts)
        for a in acts:
            tot[a] += rew[a]
        if hook:
            hook(obs, acts, rew, nxt, term, t)
        obs = {a: nxt[a] for a in env.agents}
    ticks = w.tick
    reached = {k: ticks >= v for k, v in scen.fault_ticks().items()}
    if scen.kill:
        reached["kill"] = killed_at is not None
    return {
        "ret": float(np.mean(list(tot.values()))),
        "ticks": ticks,
        "agent_steps": agent_steps,
        "coverage": float(w.coverage),
        "found": len(w.found_targets),
        "collisions": colls,
        "min_battery": float(min(d.battery for d in w.drones.values())),
        "reached": reached,
        "actions_sha": sha(log),
        "info_bytes": bus.bytes if bus else 0,
        "info_msgs": bus.msgs if bus else 0,
        "telemetry": spool.summary(),
    }

"""Node-private validation world (live-runtime.md section 5).

A private GridWorld with the node's own world config and ``n_validation_agents`` drones that all
follow the policy under test. It never touches the live world, receives no live-world state, runs
no optimizer updates, and uses only the configured gate seeds: a labeled simulated-oracle
model-selection step (A5).
"""

from __future__ import annotations

import hashlib
import time

import numpy as np
from archipelago_sim.env import ACTIONS, GridWorld

from .config import Config
from .encoder import encode_raw, for_world

KEYS = ("w1", "b1", "w2", "b2")


class WindowCancelled(Exception):
    """Raised inside a validation when its exchange window was cancelled (A4)."""


def params_digest(params: dict[str, np.ndarray]) -> str:
    h = hashlib.sha256()
    for k in KEYS:
        h.update(np.ascontiguousarray(params[k], np.float32).tobytes())
    return h.hexdigest()


class ValidationWorld:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.world = GridWorld(
            size=cfg.world_size,
            n_agents=cfg.n_validation_agents,
            n_targets=cfg.world_n_targets,
            obstacle_density=cfg.world_obstacle_density,
            sense_radius=cfg.world_sense_radius,
            max_ticks=cfg.val_ticks,
            battery_scale=cfg.world_battery_scale,
            reward_id=cfg.reward_id,
        )
        self.enc = for_world(cfg.world_size, cfg.world_sense_radius)
        self.seeds = tuple(cfg.validation_seeds)
        self.episodes_run = 0  # evaluations performed over the node's lifetime

    def evaluate(self, params: dict[str, np.ndarray], cancel=None) -> float:
        """Mean undiscounted per-drone return of the greedy policy over the gate seeds.

        ``cancel`` (a threading.Event) aborts between world steps with WindowCancelled.
        """
        w1, b1, w2, b2 = (np.asarray(params[k], np.float32) for k in KEYS)
        n = len(self.world.possible_agents)
        total = 0.0
        for seed in self.seeds:
            obs = self.world.reset(seed)
            ret = 0.0
            while self.world.agents:
                if cancel is not None and cancel.is_set():
                    raise WindowCancelled
                acts = {}
                for a in self.world.agents:
                    x = encode_raw(self.enc, obs[a])
                    q = np.maximum(x @ w1 + b1, 0) @ w2 + b2
                    acts[a] = ACTIONS[int(np.argmax(q))]
                obs, rew, _, _, _ = self.world.step(acts)
                ret += sum(rew.values())
                time.sleep(0)  # yield the GIL: act/feedback handlers must never queue behind us
            total += ret / n
            self.episodes_run += 1
        return total / len(self.seeds)

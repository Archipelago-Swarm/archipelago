"""Node-private validation world (live-runtime.md section 5).

A private GridWorld with the node's own world config and a single drone. It never touches the
live world, runs no optimizer updates, and uses only the configured validation seeds.
"""

from __future__ import annotations

import hashlib
import time

import numpy as np
from archipelago_sim.env import ACTIONS, GridWorld

from .config import Config
from .encoder import encode_fields

KEYS = ("w1", "b1", "w2", "b2")


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
            n_agents=1,
            n_targets=cfg.world_n_targets,
            obstacle_density=cfg.world_obstacle_density,
            sense_radius=cfg.world_sense_radius,
            max_ticks=cfg.val_ticks,
            battery_scale=cfg.world_battery_scale,
            reward_id=cfg.reward_id,
        )
        self.agent = self.world.possible_agents[0]
        self.seeds = tuple(cfg.validation_seeds)
        self.episodes_run = 0  # evaluations performed over the node's lifetime

    def evaluate(self, params: dict[str, np.ndarray]) -> float:
        """Mean undiscounted return of the greedy policy over the validation seeds."""
        w1, b1, w2, b2 = (np.asarray(params[k], np.float32) for k in KEYS)
        c = self.cfg
        total = 0.0
        for seed in self.seeds:
            obs = self.world.reset(seed)
            ret = 0.0
            while self.world.agents:
                o = obs[self.agent]
                x = encode_fields(
                    o["crop"],
                    o["pose"][0],
                    o["pose"][1],
                    o["battery"],
                    c.world_size,
                    c.world_sense_radius,
                )
                q = np.maximum(x @ w1 + b1, 0) @ w2 + b2
                obs, rew, _, _, _ = self.world.step({self.agent: ACTIONS[int(np.argmax(q))]})
                ret += rew[self.agent]
                time.sleep(0)  # yield the GIL: act/feedback handlers must never queue behind us
            total += ret
            self.episodes_run += 1
        return total / len(self.seeds)

"""PettingZoo ParallelEnv wrapper over GridWorld (flat Box obs, Discrete actions)."""

from __future__ import annotations

from functools import cache

import numpy as np
from gymnasium import spaces
from pettingzoo import ParallelEnv

from .env import ACTIONS, GridWorld


class GridParallelEnv(ParallelEnv):
    metadata = {"name": "archipelago_grid_v0", "render_modes": []}

    def __init__(self, **kw):
        self.world = GridWorld(**kw)
        self.possible_agents = list(self.world.possible_agents)
        self.agents: list[str] = []
        self.render_mode = None
        r = 2 * self.world.radius + 1
        hi = float(self.world.size)
        self._obs_space = spaces.Box(
            np.array([-1.0] * (r * r) + [0.0] * 3, np.float32),
            np.array([1.0] * (r * r) + [hi, hi, 1.0], np.float32),
        )

    @cache  # noqa: B019 - env lives for the process
    def observation_space(self, agent):
        return self._obs_space

    @cache  # noqa: B019
    def action_space(self, agent):
        return spaces.Discrete(len(ACTIONS))

    def _flat(self, o: dict) -> np.ndarray:
        return np.array(
            [v for row in o["crop"] for v in row] + [*o["pose"], o["battery"]], np.float32
        )

    def reset(self, seed=None, options=None):
        obs = self.world.reset(seed or 0, (options or {}).get("starts"))
        self.agents = list(self.world.agents)
        return {a: self._flat(o) for a, o in obs.items()}, {a: {} for a in self.agents}

    def step(self, actions):
        obs, rew, term, trunc, info = self.world.step({a: ACTIONS[i] for a, i in actions.items()})
        self.agents = list(self.world.agents)
        return {a: self._flat(o) for a, o in obs.items()}, rew, term, trunc, info

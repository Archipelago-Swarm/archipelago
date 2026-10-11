"""Per-node DQN learner: a thin subclass of archipelago_learning.torch_dqn.TorchLearner.

Reused unchanged: the 2-layer MLP (13 -> 64 -> 4, ReLU), Adam, replay ring buffer, target net,
param-map-v1 export, ``version`` counter. Added here: (a) identical-init / distinct-stream
construction, (b) a train step that reports loss / grad-norm / Q stats and uses Huber loss with
gradient clipping, (c) ``install_params`` (load a skill's weights as a versioned policy change),
(d) a node-local exploration RNG. Every instance owns its nets, optimizer, replay and RNGs.
"""

from __future__ import annotations

import numpy as np
import torch
from archipelago_learning.peer import params_sha256
from archipelago_learning.torch_dqn import TorchLearner

from .world import ACTION_SCHEMA, ACTIONS, OBS_DIM, REWARD_ID, SCHEMA_SHA

HIDDEN, LR, GAMMA, CAPACITY = 64, 2e-3, 0.95, 40000
BATCH, TARGET_EVERY, GRAD_CLIP = 32, 200, 10.0


def _symmetries():
    """The 8 dihedral maps of the compass (rotations x east-west reflection) as (dir_perm, 2x2 on
    the goal offset). Reward and dynamics are invariant: each real transition is stored 8 times."""
    rot = ([1, 2, 3, 0], ((0, -1), (1, 0)))  # N->E->S->W->N; (dx,dy)->(-dy,dx)
    ref = ([0, 3, 2, 1], ((-1, 0), (0, 1)))  # swap E and W; dx->-dx
    out = []
    for f in (0, 1):
        for k in range(4):
            perm, m = list(range(4)), ((1, 0), (0, 1))
            for p, mm in ([ref] if f else []) + [rot] * k:
                perm = [p[i] for i in perm]
                m = tuple(
                    tuple(sum(mm[i][t] * m[t][j] for t in range(2)) for j in range(2))
                    for i in range(2)
                )
            out.append((perm, m))
    return out


SYMMETRIES = _symmetries()


def transform(o: np.ndarray, perm, m) -> np.ndarray:
    v = o.copy()
    v[0] = m[0][0] * o[0] + m[0][1] * o[1]
    v[1] = m[1][0] * o[0] + m[1][1] * o[1]
    for d in range(4):
        v[3 + perm[d]], v[7 + perm[d]] = o[3 + d], o[7 + d]
    return v


class NodeLearner(TorchLearner):
    def __init__(self, node_id: str, init_seed: int, node_seed: int):
        """init_seed fixes the initial weights (shared => equivalent baseline); node_seed fixes
        this node's replay-sampling and exploration streams (distinct per node)."""
        super().__init__(
            node_id,
            OBS_DIM,
            len(ACTIONS),
            hidden=HIDDEN,
            seed=init_seed,
            lr=LR,
            gamma=GAMMA,
            capacity=CAPACITY,
            encoder="nav-terrain-v1",
            reward_id=REWARD_ID,
            double=True,
        )
        self.encoder_sha256, self.action_space = SCHEMA_SHA, ACTION_SCHEMA
        self.rng = np.random.default_rng(node_seed)
        self.torch_gen = torch.Generator().manual_seed(node_seed)
        self.act_rng = np.random.default_rng([node_seed, 7])

    @property
    def policy_id(self) -> str:
        return f"{self.node_id}-policy-v{self.version:04d}"

    def policy_hash(self) -> str:
        return params_sha256(self.params_numpy())

    def q_values(self, obs) -> np.ndarray:
        return self._published.q(obs)

    def observe_aug(self, o, a, r, o2, done) -> None:
        """Store the real transition under all 8 compass symmetries (see _symmetries)."""
        for perm, m in SYMMETRIES:
            self.observe(transform(o, perm, m), perm[a], r, transform(o2, perm, m), done)

    def train_update(self, batch: int | None = None) -> dict | None:
        batch = batch or BATCH
        size = min(self.n, self.capacity)
        if self.paused or size < batch:
            return None
        v0 = self.version
        idx = self.rng.integers(size, size=batch)
        o, a, r, o2, d = (torch.from_numpy(self.replay[k][idx]) for k in ("o", "a", "r", "o2", "d"))
        with torch.no_grad():
            best = self.policy(o2).argmax(1, keepdim=True)
            y = r + self.gamma * (1 - d) * self.target_net(o2).gather(1, best).squeeze(1)
        q = self.policy(o).gather(1, a[:, None]).squeeze(1)
        loss_t = torch.nn.functional.smooth_l1_loss(q, y)
        self.opt.zero_grad(set_to_none=True)
        loss_t.backward()
        gnorm = float(torch.nn.utils.clip_grad_norm_(self.policy.parameters(), GRAD_CLIP))
        self.opt.step()
        self.steps += 1
        self.version += 1
        synced = self.steps % TARGET_EVERY == 0
        if synced:
            self.sync_target()
        self._publish()
        return {
            "batch_size": batch,
            "replay_size": min(int(self.n), self.capacity),
            "loss": float(loss_t.detach()),
            "grad_norm": gnorm,
            "q_mean": float(q.detach().mean()),
            "td_abs_mean": float((q.detach() - y).abs().mean()),
            "target_synced": synced,
            "policy_version_before": v0,
            "policy_version_after": self.version,
        }

    def install_params(self, params: dict[str, np.ndarray]) -> tuple[int, int]:
        """Load a skill's weights as a versioned policy change; optimizer state resets."""
        v0 = self.version
        self.load_params_numpy(params)
        self.sync_target()
        self._reset_optimizer()
        self.version += 1
        return v0, self.version

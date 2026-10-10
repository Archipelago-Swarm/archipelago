"""Per-node numpy DQN. Each Learner owns its policy, target, optimizer, replay and RNG."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ENCODER = "grid-flat-v0"


class Learner:
    def __init__(
        self,
        node_id,
        obs_dim,
        n_actions,
        hidden=32,
        seed=0,
        lr=1e-2,
        gamma=0.95,
        capacity=5000,
        mode="independent",
        encoder=ENCODER,
    ):
        assert mode in ("independent", "information_only", "mixing")
        self.node_id, self.mode, self.encoder = node_id, mode, encoder
        self.obs_dim, self.n_actions, self.hidden = obs_dim, n_actions, hidden
        self.lr, self.gamma, self.capacity = lr, gamma, capacity
        self.rng = np.random.default_rng(seed)
        r = self.rng
        self.params = {
            "w1": (r.standard_normal((obs_dim, hidden)) / np.sqrt(obs_dim)).astype(np.float32),
            "b1": np.zeros(hidden, np.float32),
            "w2": (r.standard_normal((hidden, n_actions)) / np.sqrt(hidden)).astype(np.float32),
            "b2": np.zeros(n_actions, np.float32),
        }
        self.target = {k: v.copy() for k, v in self.params.items()}
        self._reset_optimizer()
        self.replay = {
            "o": np.zeros((capacity, obs_dim), np.float32),
            "a": np.zeros(capacity, np.int64),
            "r": np.zeros(capacity, np.float32),
            "o2": np.zeros((capacity, obs_dim), np.float32),
            "d": np.zeros(capacity, np.float32),
        }
        self.n = 0  # total transitions ever stored
        self.steps = 0
        self.version = 0  # bumped on every parameter change (train, accept, rollback)
        self.paused = False
        self.events: list[dict] = []
        self.previous: dict | None = None  # params before last accepted peer candidate

    def _reset_optimizer(self):
        self.opt = {
            "t": 0,
            **{f"{s}_{k}": np.zeros_like(v) for k, v in self.params.items() for s in "mv"},
        }

    @staticmethod
    def forward(p, x):
        h = np.maximum(x @ p["w1"] + p["b1"], 0)
        return h, h @ p["w2"] + p["b2"]

    def snapshot(self):
        """Immutable inference copy: read-only arrays, unaffected by later training."""
        snap = {k: v.copy() for k, v in self.params.items()}
        for v in snap.values():
            v.flags.writeable = False
        return snap

    def act(self, obs, eps=0.0, snap=None):
        if self.rng.random() < eps:
            return int(self.rng.integers(self.n_actions))
        return int(np.argmax(self.forward(snap or self.params, np.asarray(obs, np.float32))[1]))

    def observe(self, o, a, r, o2, done):
        i = self.n % self.capacity
        for k, v in zip(("o", "a", "r", "o2", "d"), (o, a, r, o2, float(done)), strict=True):
            self.replay[k][i] = v
        self.n += 1

    def train_step(self, batch=32, target_every=50):
        """One Adam step on TD error. No-op while paused or with too little data."""
        size = min(self.n, self.capacity)
        if self.paused or size < batch:
            return None
        idx = self.rng.integers(size, size=batch)
        b = {k: v[idx] for k, v in self.replay.items()}
        h, q = self.forward(self.params, b["o"])
        y = b["r"] + self.gamma * (1 - b["d"]) * self.forward(self.target, b["o2"])[1].max(1)
        rows = np.arange(batch)
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
        self.events.append({"type": "local_update", "step": self.steps, "version": self.version})
        return float((err**2).mean())

    # Checkpoints: model/optimizer, replay and RNG are separate files so each can be restored alone.
    def save(self, d):
        d = Path(d)
        d.mkdir(parents=True, exist_ok=True)
        meta = {"steps": self.steps, "version": self.version, "n": self.n}
        np.savez(
            d / "model.npz",
            **{f"p_{k}": v for k, v in self.params.items()},
            **{f"t_{k}": v for k, v in self.target.items()},
            **{f"o_{k}": v for k, v in self.opt.items()},
        )
        np.savez(d / "replay.npz", **self.replay)
        (d / "rng.json").write_text(json.dumps(self.rng.bit_generator.state))
        (d / "meta.json").write_text(json.dumps(meta))

    def load(self, d):
        d = Path(d)
        m = np.load(d / "model.npz", allow_pickle=False)
        self.params = {k: m[f"p_{k}"].copy() for k in self.params}
        self.target = {k: m[f"t_{k}"].copy() for k in self.params}
        self.opt = {k: m[f"o_{k}"].copy() for k in self.opt}
        self.opt["t"] = int(self.opt["t"])
        r = np.load(d / "replay.npz", allow_pickle=False)
        self.replay = {k: r[k].copy() for k in self.replay}
        self.rng.bit_generator.state = json.loads((d / "rng.json").read_text())
        meta = json.loads((d / "meta.json").read_text())
        self.steps, self.version, self.n = meta["steps"], meta["version"], meta["n"]

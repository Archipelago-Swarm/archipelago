"""PyTorch CPU DQN learner (live-runtime.md sections 4 and 7).

Peer of the NumPy baseline (dqn.Learner): same public surface, same param-map-v1 exchange format.
Every instance owns its nets, Adam optimizer, replay, numpy Generator and torch.Generator; there
is no module-level mutable state. torch.set_num_threads / use_deterministic_algorithms are
process-wide torch switches; they are applied (and recorded in ``runtime``) at construction.

Never pickle/torch.load untrusted data: checkpoints are npz read with allow_pickle=False after
sha256 verification; peer payloads go through peer.decode.
"""

from __future__ import annotations

import io
import json
import os

import numpy as np
import torch
from torch import nn

from . import checkpoint, schedules
from .compat import (
    ACTION_SPACE,
    KEYS,
    PARAM_MAP,
    REWARD_ID,
    encoder_sha256,
    param_shapes,
    validate_params,
)

ENCODER = "grid-flat-v1-s8-r2"
CKPT_SCHEMA = "torch-ckpt-v1"
_PREFIX = "extra."
MAX_CKPT_EVENTS = 1000  # newest events kept in a checkpoint; bounds size and write time


# Identity keys added after the first checkpoints existed: a checkpoint without them was written by
# the legacy recipe, so it only loads into a learner that is configured the legacy way.
LEGACY_IDENTITY = {"double_dqn": False, "learner_schedule": schedules.LEGACY}


def check_identity(counters: dict, identity: dict) -> None:
    """Raise ValueError naming the first identity field (encoder, reward id, ...) that differs."""
    for k, v in identity.items():
        if k == "node_id":
            continue
        have = counters.get(k, LEGACY_IDENTITY.get(k)) if k in LEGACY_IDENTITY else counters.get(k)
        if have != v:
            raise ValueError(f"checkpoint {k} mismatch: {have!r} != {v!r}")


class InferenceSnapshot:
    """Immutable inference copy (read-only NumPy arrays, no autograd). Safe while training."""

    __slots__ = ("_p",)

    def __init__(self, params: dict[str, np.ndarray]):
        self._p = {k: v.copy() for k, v in params.items()}
        for v in self._p.values():
            v.flags.writeable = False

    def __getitem__(self, k):
        return self._p[k]

    def keys(self):
        return self._p.keys()

    def q(self, obs) -> np.ndarray:
        x = np.asarray(obs, np.float32)
        h = np.maximum(x @ self._p["w1"] + self._p["b1"], 0)
        return h @ self._p["w2"] + self._p["b2"]


def _arrays(blob: bytes) -> dict[str, np.ndarray]:
    with np.load(io.BytesIO(blob), allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def _npz(**arrays) -> bytes:
    b = io.BytesIO()
    np.savez(b, **arrays)
    return b.getvalue()


class TorchLearner:
    backend = "torch-cpu"
    action_space = ACTION_SPACE

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
        threads=None,
        reward_id=REWARD_ID,
        double=False,
        schedule_id=schedules.LEGACY,
    ):
        """threads=None -> env OMP_NUM_THREADS if set, else 1.

        reward_id / schedule_id are identity (checkpoint and peer headers, A18); ``double`` selects
        double-DQN targets (action chosen by the online net, valued by the target net).

        Thread count and deterministic mode are process-wide. runtime['threads'] is the value at
        construction; a learner built later in the same process with a different count makes it
        stale (last constructor wins). Read torch.get_num_threads() for the live value.
        """
        assert mode in ("independent", "information_only", "mixing")
        if threads is None:
            threads = int(os.environ.get("OMP_NUM_THREADS", "1") or 1)
        threads = max(1, int(threads))
        torch.set_num_threads(threads)
        det_error = None
        try:
            torch.use_deterministic_algorithms(True)
        except Exception as e:  # recorded, never hidden
            det_error = repr(e)
        self.runtime = {
            "backend": self.backend,
            "torch_version": torch.__version__,
            "threads": torch.get_num_threads(),
            "deterministic": torch.are_deterministic_algorithms_enabled(),
            "deterministic_error": det_error,
            "param_map": PARAM_MAP,
        }
        self.node_id, self.mode, self.encoder = node_id, mode, encoder
        self.reward_id, self.double, self.schedule_id = reward_id, bool(double), schedule_id
        self.encoder_sha256 = encoder_sha256(encoder)
        self.obs_dim, self.n_actions, self.hidden = obs_dim, n_actions, hidden
        self.lr, self.gamma, self.capacity = lr, gamma, capacity
        self.rng = np.random.default_rng(seed)
        self.torch_gen = torch.Generator().manual_seed(seed)
        self.policy = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.ReLU(), nn.Linear(hidden, n_actions)
        )
        self.target_net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.ReLU(), nn.Linear(hidden, n_actions)
        )
        with torch.no_grad():
            self.policy[0].weight.copy_(
                torch.randn(hidden, obs_dim, generator=self.torch_gen) / np.sqrt(obs_dim)
            )
            self.policy[0].bias.zero_()
            self.policy[2].weight.copy_(
                torch.randn(n_actions, hidden, generator=self.torch_gen) / np.sqrt(hidden)
            )
            self.policy[2].bias.zero_()
        for p in self.target_net.parameters():
            p.requires_grad_(False)
        self.sync_target()
        self._reset_optimizer()
        self.replay = {
            "o": np.zeros((capacity, obs_dim), np.float32),
            "a": np.zeros(capacity, np.int64),
            "r": np.zeros(capacity, np.float32),
            "o2": np.zeros((capacity, obs_dim), np.float32),
            "d": np.zeros(capacity, np.float32),
        }
        self.n = 0
        self.steps = 0
        self.version = 0  # bumped on every parameter change (train, accept, rollback)
        self.paused = False
        self.events: list[dict] = []
        self.previous: dict | None = None
        self._publish()

    # --- state helpers ---------------------------------------------------------------------
    def _reset_optimizer(self):
        self.opt = torch.optim.Adam(
            self.policy.parameters(), lr=self.lr, betas=(0.9, 0.999), eps=1e-8
        )

    def sync_target(self):
        self.target_net.load_state_dict(self.policy.state_dict())

    @staticmethod
    def _export(net) -> dict[str, np.ndarray]:
        l1, l2 = net[0], net[2]
        t = lambda x: np.ascontiguousarray(x.detach().cpu().numpy())  # noqa: E731
        return {
            "w1": t(l1.weight).T.copy(),
            "b1": t(l1.bias).copy(),
            "w2": t(l2.weight).T.copy(),
            "b2": t(l2.bias).copy(),
        }

    @staticmethod
    def _import(net, d) -> None:
        with torch.no_grad():
            net[0].weight.copy_(torch.from_numpy(np.ascontiguousarray(d["w1"].T)))
            net[0].bias.copy_(torch.from_numpy(d["b1"].copy()))
            net[2].weight.copy_(torch.from_numpy(np.ascontiguousarray(d["w2"].T)))
            net[2].bias.copy_(torch.from_numpy(d["b2"].copy()))

    @property
    def shapes(self):
        return param_shapes(self.obs_dim, self.hidden, self.n_actions)

    def params_numpy(self) -> dict[str, np.ndarray]:
        """param-map-v1 export (float32, NumPy layout; torch weights transposed)."""
        return self._export(self.policy)

    def load_params_numpy(self, d) -> None:
        """Replace the policy weights only; peer.offer/rollback/checkpoint handle the rest."""
        self._import(self.policy, validate_params(d, self.shapes))
        self._publish()

    def target_numpy(self) -> dict[str, np.ndarray]:
        return self._export(self.target_net)

    def _publish(self) -> None:
        self._published = InferenceSnapshot(self.params_numpy())

    # --- NumPy-Learner-compatible surface --------------------------------------------------
    def snapshot(self) -> InferenceSnapshot:
        return InferenceSnapshot(self.params_numpy())

    def act(self, obs, eps=0.0, snap=None):
        if self.rng.random() < eps:
            return int(self.rng.integers(self.n_actions))
        return int(np.argmax((snap or self._published).q(obs)))

    def observe(self, o, a, r, o2, done):
        i = self.n % self.capacity
        for k, v in zip(("o", "a", "r", "o2", "d"), (o, a, r, o2, float(done)), strict=True):
            self.replay[k][i] = v
        self.n += 1

    def train_step(self, batch=32, target_every=50):
        """One Adam step on the TD error. No-op while paused or with too little data."""
        size = min(self.n, self.capacity)
        if self.paused or size < batch:
            return None
        idx = self.rng.integers(size, size=batch)
        o, a, r, o2, d = (torch.from_numpy(self.replay[k][idx]) for k in ("o", "a", "r", "o2", "d"))
        with torch.no_grad():
            if self.double:  # y = r + g (1-d) Q_target(s2, argmax_a Q_online(s2, a))
                best = self.policy(o2).argmax(1, keepdim=True)
                nxt = self.target_net(o2).gather(1, best).squeeze(1)
            else:
                nxt = self.target_net(o2).max(1).values
            y = r + self.gamma * (1 - d) * nxt
        q = self.policy(o).gather(1, a[:, None]).squeeze(1)
        err = q - y
        loss_t = 0.5 * (err**2).mean()  # same gradient scale as the NumPy baseline
        self.opt.zero_grad(set_to_none=True)
        loss_t.backward()
        self.opt.step()
        self.steps += 1
        self.version += 1
        loss = float((err.detach() ** 2).mean())
        if self.steps % target_every == 0:
            self.sync_target()
        self._publish()
        self.events.append(
            {"type": "local_update", "step": self.steps, "version": self.version, "loss": loss}
        )
        return loss

    # --- checkpoint generations (section 7) ------------------------------------------------
    def _optimizer_arrays(self) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        params = list(self.policy.parameters())
        st = [self.opt.state.get(p) for p in params]
        step = float(st[0]["step"]) if st[0] else 0.0
        out["step"] = np.array(step, np.float64)
        names = [("w1", True), ("b1", False), ("w2", True), ("b2", False)]
        for (k, tr), p, s in zip(names, params, st, strict=True):
            for tag, key in (("m", "exp_avg"), ("v", "exp_avg_sq")):
                a = s[key].numpy() if s else np.zeros(tuple(p.shape), np.float32)
                out[f"{tag}_{k}"] = (a.T if tr else a).astype(np.float32).copy()
        return out

    def _restore_optimizer(self, o: dict[str, np.ndarray]) -> None:
        self._reset_optimizer()
        step = float(o["step"])
        if step <= 0:
            return
        sd = self.opt.state_dict()
        state = {}
        for i, (k, tr) in enumerate([("w1", True), ("b1", False), ("w2", True), ("b2", False)]):
            m, v = o[f"m_{k}"], o[f"v_{k}"]
            if tr:
                m, v = m.T, v.T
            state[i] = {
                "step": torch.tensor(step, dtype=torch.float32),
                "exp_avg": torch.from_numpy(np.ascontiguousarray(m)),
                "exp_avg_sq": torch.from_numpy(np.ascontiguousarray(v)),
            }
        sd["state"] = state
        self.opt.load_state_dict(sd)

    def _identity(self) -> dict:
        # order matters: the first differing field names the refusal, and the versioned ids
        # (encoder, reward, schedule) are the clearest reasons, so they come before sizes
        return {
            "node_id": self.node_id,
            "encoder": self.encoder,
            "encoder_sha256": self.encoder_sha256,
            "reward_id": self.reward_id,
            "learner_schedule": self.schedule_id,
            "obs_dim": self.obs_dim,
            "hidden": self.hidden,
            "n_actions": self.n_actions,
            "capacity": self.capacity,
            "action_space": self.action_space,
            "param_map": PARAM_MAP,
            "double_dqn": self.double,
        }

    def save_generation(self, root, extra: dict | None = None, _io=None) -> dict:
        """Write a new checkpoint generation under root and switch CURRENT. Returns the manifest.

        extra: name -> JSON-serialisable blob (node-runtime state: sequence, schedule, dedupe...).
        """
        extra = extra or {}
        counters = {
            **self._identity(),
            "schema": CKPT_SCHEMA,
            "steps": self.steps,
            "version": self.version,
            "n": self.n,
            "paused": self.paused,
            "has_previous": self.previous is not None,
            "torch_version": torch.__version__,
            "events_dropped": max(0, len(self.events) - MAX_CKPT_EVENTS),
        }
        policy_arrays = {f"p_{k}": v for k, v in self.params_numpy().items()}
        policy_arrays.update({f"t_{k}": v for k, v in self.target_numpy().items()})
        files = {
            "model.npz": _npz(**policy_arrays),
            "optimizer.npz": _npz(**self._optimizer_arrays()),
            "replay.npz": _npz(**self.replay),
            "rng.npz": _npz(
                numpy_state=np.frombuffer(
                    json.dumps(self.rng.bit_generator.state).encode(), np.uint8
                ),
                torch_state=self.torch_gen.get_state().numpy(),
            ),
            "previous.npz": _npz(**{k: v for k, v in (self.previous or {}).items()}),
            "counters.json": json.dumps(counters, sort_keys=True).encode(),
            "events.json": json.dumps(self.events[-MAX_CKPT_EVENTS:], allow_nan=False).encode(),
        }
        for name, blob in extra.items():
            files[f"{_PREFIX}{name}.json"] = json.dumps(
                blob, sort_keys=True, allow_nan=False
            ).encode()
        return checkpoint.write_generation(root, files, _io)

    def load_latest(self, root) -> dict:
        """Restore from the newest verified generation; returns manifest + 'extra' blobs.

        All data is parsed and validated before any state is replaced.
        """
        manifest, files = checkpoint.read_latest(root)
        try:
            counters = json.loads(files["counters.json"])
            if counters.get("schema") != CKPT_SCHEMA:
                raise ValueError(f"unknown checkpoint schema {counters.get('schema')!r}")
            check_identity(counters, self._identity())
            model, opt = _arrays(files["model.npz"]), _arrays(files["optimizer.npz"])
            replay, rng = _arrays(files["replay.npz"]), _arrays(files["rng.npz"])
            prev = _arrays(files["previous.npz"])
            pol = validate_params({k: model[f"p_{k}"] for k in KEYS}, self.shapes)
            tgt = validate_params({k: model[f"t_{k}"] for k in KEYS}, self.shapes)
            previous = validate_params(prev, self.shapes) if counters["has_previous"] else None
            for k, v in self.replay.items():
                if replay[k].shape != v.shape or replay[k].dtype != v.dtype:
                    raise ValueError(f"checkpoint replay mismatch for {k}")
            np_state = json.loads(bytes(rng["numpy_state"]))
            events = json.loads(files["events.json"])
            extra = {
                n[len(_PREFIX) : -len(".json")]: json.loads(b)
                for n, b in files.items()
                if n.startswith(_PREFIX)
            }
            probe = np.random.default_rng()
            probe.bit_generator.state = np_state  # validates before commit
        except (KeyError, ValueError) as e:
            raise checkpoint.CheckpointError(f"checkpoint content invalid: {e}") from e
        self._import(self.policy, pol)
        self._import(self.target_net, tgt)
        self._restore_optimizer(opt)
        self.replay = {k: replay[k].copy() for k in self.replay}
        self.rng.bit_generator.state = np_state
        self.torch_gen.set_state(torch.from_numpy(rng["torch_state"].copy()))
        self.steps, self.version, self.n = counters["steps"], counters["version"], counters["n"]
        self.paused, self.events, self.previous = counters["paused"], events, previous
        self._publish()
        return {**manifest, "counters": counters, "extra": extra}

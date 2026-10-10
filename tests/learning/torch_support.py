"""Shared helpers for the TorchLearner tests (controlled one-hot task)."""

import numpy as np
from archipelago_learning import Learner, TorchLearner

ENC = "grid-flat-v1-s8-r2"


def numpy_learner(node="n", seed=0, **kw):
    return Learner(node, 3, 3, seed=seed, encoder=ENC, **kw)


def torch_learner(node="t", seed=0, **kw):
    return TorchLearner(node, 3, 3, seed=seed, encoder=ENC, **kw)


def fill(L, n=300, seed=1):
    """The right action is the index of the hot input (reward 1), else 0."""
    r = np.random.default_rng(seed)
    for _ in range(n):
        o = np.eye(3, dtype=np.float32)[r.integers(3)]
        a = int(r.integers(3))
        L.observe(o, a, 1.0 if a == int(o.argmax()) else 0.0, o, True)


def score(p):
    """Greedy accuracy of a param-map-v1 dict on the one-hot task."""
    x = np.eye(3, dtype=np.float32)
    return float((Learner.forward(p, x)[1].argmax(1) == np.arange(3)).mean())


def trained_torch(seed=0, node="t", steps=300):
    L = torch_learner(node, seed)
    fill(L)
    for _ in range(steps):
        L.train_step()
    return L


def optimizer_is_fresh(L):
    """True when no Adam moments / step count exist (works for both backends)."""
    if L.backend == "numpy":
        return L.opt["t"] == 0 and all(not v.any() for k, v in L.opt.items() if k != "t")
    return len(L.opt.state) == 0


def target_params(L):
    return L.target if L.backend == "numpy" else L.target_numpy()

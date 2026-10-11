"""Versioned learner schedules (T37 selection, T38 adoption; live-runtime.md Amendment A18).

A learner schedule id names the whole training recipe, so a manifest, telemetry record or checkpoint
that carries the id is unambiguous. ``sched-v0`` is the legacy free-form recipe (whatever the
configure message says, epsilon decaying per act). ``sched-t37-v1`` is the T37-selected recipe and is
FIXED: a configure message that names it but disagrees on any value is refused with a clear reason.

``sched-t37-v1``: epsilon 1.0 -> 0.05 linearly over the first 50% of the TRAINING episodes (evaluated
once at each training episode start, then constant), Adam lr 1e-3, gamma 0.95, batch 32, hidden 32,
target sync every 50 optimizer steps, one optimizer step per recorded transition, replay 50000
transitions per node, double DQN, MSE (Huber-free) TD loss, no gradient clipping, done = termination
only. The coordinator mirrors ``SCHEDULES`` in ``archipelago_coordinator.models``; a test keeps the
two in sync (the coordinator image does not ship this package).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

LEGACY = "sched-v0"
T37 = "sched-t37-v1"


@dataclass(frozen=True)
class Schedule:
    id: str
    lr: float
    gamma: float
    hidden: int
    capacity: int
    batch: int
    target_every: int
    train_steps_per_feedback: int
    double_dqn: bool
    eps_start: float
    eps_end: float
    eps_decay_fraction: float  # of the training episodes

    def decay_episodes(self, n_train_episodes: int) -> int:
        """Whole episodes of the decay span (ceil of the fraction; the study used 200 of 400)."""
        return max(1, math.ceil(self.eps_decay_fraction * n_train_episodes))


SCHEDULES: dict[str, Schedule] = {
    T37: Schedule(
        id=T37,
        lr=1e-3,
        gamma=0.95,
        hidden=32,
        capacity=50000,
        batch=32,
        target_every=50,
        train_steps_per_feedback=1,
        double_dqn=True,
        eps_start=1.0,
        eps_end=0.05,
        eps_decay_fraction=0.5,
    )
}


def known(schedule_id: str) -> bool:
    return schedule_id == LEGACY or schedule_id in SCHEDULES


def epsilon_at(episode: int, start: float, end: float, decay_episodes: float) -> float:
    """Linear decay by training-episode index, constant after ``decay_episodes`` (T37 ``epsilon``)."""
    f = min(1.0, max(0, episode) / max(1.0, decay_episodes))
    return start + (end - start) * f


def check(schedule_id: str, hyper: dict, eps: dict, double_dqn: bool) -> None:
    """Raise ValueError unless a configure message agrees with the registered schedule.

    ``hyper``: lr, gamma, hidden, capacity, batch, target_every, train_steps_per_feedback;
    ``eps``: start, end. ``decay_episodes`` is derived from the plan (fraction of its training
    episodes) and is not compared.
    """
    if schedule_id == LEGACY:
        if double_dqn:
            raise ValueError("double_dqn requires a registered learner schedule, not sched-v0")
        return
    s = SCHEDULES.get(schedule_id)
    if s is None:
        raise ValueError(f"unknown learner_schedule_id {schedule_id!r}")
    want = {k: v for k, v in asdict(s).items() if k in hyper}
    for k, v in want.items():
        if hyper[k] != v:
            raise ValueError(f"{schedule_id} requires {k}={v!r}, configure says {hyper[k]!r}")
    for k, want_v in (("start", s.eps_start), ("end", s.eps_end)):
        if eps[k] != want_v:
            raise ValueError(f"{schedule_id} requires epsilon {k}={want_v!r}, got {eps[k]!r}")
    if double_dqn != s.double_dqn:
        raise ValueError(f"{schedule_id} requires double_dqn={s.double_dqn}")

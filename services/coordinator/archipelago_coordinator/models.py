"""Plan and request bodies (coordinator-internal; embedded run_config is the contract RunConfig)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from archipelago_contracts.models import FaultWindow, Finite, Id, RunConfig, Strict, Tick
from pydantic import Field, ValidationError

MAX_EPISODES = 10_000
MAX_RUN_ID = 56  # event ids embed run_id + boot id + sequence, episode ids add "-e<index>"
MAX_PLAN_BYTES = 256 * 1024
DEFAULT_PLAN = "default"


# Versioned learner recipes (A18). Mirror of archipelago_learning.schedules.SCHEDULES, which the
# coordinator image does not ship; tests/coordinator keeps the two equal.
LEGACY_SCHEDULE = "sched-v0"
LEARNER_SCHEDULES: dict[str, dict[str, Any]] = {
    "sched-t37-v1": {
        "lr": 1e-3, "gamma": 0.95, "hidden": 32, "capacity": 50000, "batch": 32,
        "target_every": 50, "train_steps_per_feedback": 1, "double_dqn": True,
        "eps_start": 1.0, "eps_end": 0.05, "eps_decay_fraction": 0.5,
    }
}  # fmt: skip
ENCODER_FAMILIES = (
    "grid-flat-v1",
    "grid-flat-v2-visits",
    "grid-flat-v2-visits-shared",
    "grid-flat-v3-terrain",
)
_ENCODER_ID = re.compile(
    r"^(grid-flat-v1|grid-flat-v3-terrain|grid-flat-v2-visits(?:-shared)?)-s([0-9]+)-r([0-9]+)$"
)


class Hyperparameters(Strict):
    lr: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 1e-2
    gamma: Annotated[float, Field(ge=0, le=1)] = 0.95
    hidden: Annotated[int, Field(ge=1)] = 32
    capacity: Annotated[int, Field(ge=1)] = 5000
    batch: Annotated[int, Field(ge=1)] = 32
    target_every: Annotated[int, Field(ge=1)] = 50
    train_steps_per_feedback: Annotated[int, Field(ge=0)] = 1
    double_dqn: bool = False  # needs a registered learner_schedule_id (A18)


class EpsilonSchedule(Strict):
    start: Annotated[float, Field(ge=0, le=1)] = 0.5
    end: Annotated[float, Field(ge=0, le=1)] = 0.05
    decay_episodes: Annotated[int, Field(ge=1)] = 20
    # A18: span as a fraction of the plan's TRAINING episodes (overrides decay_episodes)
    decay_fraction: Annotated[float, Field(gt=0, le=1)] | None = None


class NodeConfig(Strict):
    """What every node is told once per run (`configure`, section 14). World geometry, tick budget,
    battery scale and reward id are taken from the run itself so they cannot disagree with it."""

    hyperparameters: Hyperparameters = Hyperparameters()
    epsilon_schedule: EpsilonSchedule = EpsilonSchedule()
    margin: Finite = 0.0
    gate_seeds: Annotated[list[int], Field(min_length=1)] = [9001, 9002, 9003]
    n_validation_agents: Annotated[int, Field(ge=1)] = 1
    # A family (grid-flat-v1 | grid-flat-v2-visits | grid-flat-v2-visits-shared; geometry is taken
    # from the live world) or a full id with geometry. Default grid-flat-v1.
    encoder_id: str | None = None
    learner_schedule_id: str = LEGACY_SCHEDULE  # A18
    exchange_every_ticks: Annotated[int, Field(ge=1)] = 50
    seed: int = 0


class EpisodeSpec(Strict):
    kind: Literal["train", "validation", "test"]
    seed: int
    count: Annotated[int, Field(ge=1, le=MAX_EPISODES)] = 1


class KillNode(Strict):
    node_id: Id
    tick: Tick


class Outage(Strict):
    start_tick: Tick
    end_tick: Tick


class Plan(Strict):
    node_urls: dict[Id, str]
    deadline_ms: Annotated[int, Field(ge=1, le=60_000)] = 500
    battery_scale: Annotated[float, Field(gt=0, le=1000, allow_inf_nan=False)] = 1.0
    # A18: versioned reward id the world runs. When set it is authoritative over
    # run_config.reward_id (a run request naming a different non-default id is refused).
    reward_id: str | None = None
    node_config: NodeConfig = NodeConfig()
    episodes: Annotated[list[EpisodeSpec], Field(min_length=1)]
    eval_every: Annotated[int, Field(ge=0)] = 0  # recorded only; `episodes` is authoritative
    fault_schedule: list[FaultWindow] = []
    kill_node: KillNode | None = None
    telemetry_outage: Outage | None = None


class CreateRun(Strict):
    """A run request carries no plan and no node URLs: the plan is a server-side file (A9)."""

    run_config: RunConfig
    plan_name: Id | None = None


@dataclass(frozen=True)
class LoadedPlan:
    name: str
    plan: Plan
    file_sha256: str


class PlanError(ValueError):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status  # 503 when the server's plan file is unusable, 422 for a bad request


def load_plan(path: Path | None, name: str | None) -> LoadedPlan:
    """Read the server-side plan file fresh (so an operator edit applies to the next run).

    The file is either one Plan object (name "default") or `{"plans": {name: Plan, ...}}`.
    """
    if path is None:
        raise PlanError("no COORDINATOR_PLAN_FILE configured", 503)
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise PlanError(f"plan file unreadable: {e.strerror or e}", 503) from e
    if len(raw) > MAX_PLAN_BYTES:
        raise PlanError("plan file too large", 503)
    try:
        doc = json.loads(raw)
    except ValueError as e:
        raise PlanError(f"plan file is not JSON: {e}", 503) from e
    if not isinstance(doc, dict):
        raise PlanError("plan file must be a JSON object", 503)
    plans = doc["plans"] if set(doc) == {"plans"} and isinstance(doc["plans"], dict) else None
    book: dict[str, Any] = plans if plans is not None else {DEFAULT_PLAN: doc}
    chosen = name or (DEFAULT_PLAN if DEFAULT_PLAN in book else None)
    if chosen is None and len(book) == 1:
        chosen = next(iter(book))
    if chosen is None or chosen not in book:
        raise PlanError(f"unknown plan {name!r}; available: {sorted(book)}")
    try:
        plan = Plan.model_validate(book[chosen])
    except ValidationError as e:
        raise PlanError(f"plan {chosen!r} is invalid: {e.error_count()} error(s)", 503) from e
    return LoadedPlan(chosen, plan, hashlib.sha256(raw).hexdigest())


class CommandBody(Strict):
    command_id: Id
    command: Literal["pause", "resume", "step", "stop", "checkpoint"]
    expected_revision: int | None = None


@dataclass(frozen=True)
class Episode:
    index: int
    kind: str
    seed: int

    @property
    def mode(self) -> str:
        return "train" if self.kind == "train" else "eval"


def expand_episodes(plan: Plan) -> list[Episode]:
    """Explicit order; `count` > 1 repeats the entry with seeds seed, seed+1, ..."""
    out: list[Episode] = []
    for spec in plan.episodes:
        for i in range(spec.count):
            out.append(Episode(len(out), spec.kind, spec.seed + i))
    return out


def canonical_hash(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def schedule_json(plan: Plan) -> list[dict[str, Any]]:
    return [w.model_dump(mode="json") for w in plan.fault_schedule]


def resolve_encoder_id(requested: str | None, size: int, radius: int) -> str:
    """Full encoder id (with geometry, A6) for a family name, a full id or the default."""
    geometry = f"-s{size}-r{radius}"
    if requested is None:
        return "grid-flat-v1" + geometry
    return requested + geometry if requested in ENCODER_FAMILIES else requested


def check_encoder_id(full: str, size: int, radius: int) -> str | None:
    m = _ENCODER_ID.match(full)
    if m is None:
        return f"unknown encoder_id {full!r}"
    if (int(m.group(2)), int(m.group(3))) != (size, radius):
        return f"encoder_id {full!r} does not match the live world (s{size}-r{radius})"
    return None


def resolve_schedule(nc: NodeConfig, n_train: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """(hyperparameters, epsilon_schedule) as sent in `configure`. A registered learner schedule
    fills what the plan leaves out and refuses what contradicts it. Raises ValueError."""
    sid, hp, ep = nc.learner_schedule_id, nc.hyperparameters.model_dump(), nc.epsilon_schedule
    eps = {"start": ep.start, "end": ep.end, "decay_episodes": ep.decay_episodes}
    reg = LEARNER_SCHEDULES.get(sid)
    if reg is None:
        if sid != LEGACY_SCHEDULE:
            raise ValueError(f"unknown learner_schedule_id {sid!r}")
        if hp["double_dqn"]:
            raise ValueError("double_dqn needs a registered learner_schedule_id")
        if ep.decay_fraction is not None:
            eps["decay_episodes"] = max(1, math.ceil(ep.decay_fraction * n_train))
        return hp, eps
    given = nc.hyperparameters.model_fields_set
    for k in hp:
        if k in given and hp[k] != reg[k]:
            raise ValueError(f"{sid} requires {k}={reg[k]!r}, plan says {hp[k]!r}")
        hp[k] = reg[k]
    got = ep.model_fields_set
    for k, rk in (("start", "eps_start"), ("end", "eps_end")):
        if k in got and eps[k] != reg[rk]:
            raise ValueError(f"{sid} requires epsilon {k}={reg[rk]!r}, plan says {eps[k]!r}")
        eps[k] = reg[rk]
    if "decay_fraction" in got and ep.decay_fraction != reg["eps_decay_fraction"]:
        raise ValueError(f"{sid} requires decay_fraction={reg['eps_decay_fraction']!r}")
    eps["decay_episodes"] = max(1, math.ceil(reg["eps_decay_fraction"] * n_train))
    return hp, eps

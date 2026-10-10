"""Plan and request bodies (coordinator-internal; embedded run_config is the contract RunConfig)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from archipelago_contracts.models import FaultWindow, Id, RunConfig, Strict, Tick
from pydantic import Field

MAX_EPISODES = 10_000
MAX_RUN_ID = 64  # event ids embed run_id + boot id + sequence and must fit the Id limit


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
    episodes: Annotated[list[EpisodeSpec], Field(min_length=1)]
    eval_every: Annotated[int, Field(ge=0)] = 0  # recorded only; `episodes` is authoritative
    fault_schedule: list[FaultWindow] = []
    kill_node: KillNode | None = None
    telemetry_outage: Outage | None = None


class CreateRun(Strict):
    run_config: RunConfig
    plan: Plan


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

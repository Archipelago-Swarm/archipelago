"""Internal coordinator<->node protocol (live-runtime.md section 3).

Internal runtime protocol, not part of the frozen v0.1 public contracts. The embedded
``observation`` / ``next_observation`` / ``action`` are canonical contract records.
"""

from __future__ import annotations

from typing import Annotated, Literal

from archipelago_contracts.models import (
    Action,
    FaultWindow,
    Finite,
    Id,
    Observation,
    Tick,
)
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActRequest(Msg):
    run_id: Id
    episode: Annotated[int, Field(ge=0)]
    tick: Tick
    deadline_ms: Annotated[int, Field(gt=0, le=600_000)] = 500
    observation: Observation


class ActResponse(Msg):
    node_id: Id
    tick: Tick
    action: Action
    policy_version: Annotated[int, Field(ge=0)]
    epsilon: Annotated[float, Field(ge=0, le=1)]


class FeedbackRequest(Msg):
    run_id: Id
    episode: Annotated[int, Field(ge=0)]
    tick: Tick
    reward: Finite
    next_observation: Observation
    terminated: bool
    truncated: bool = False


class FeedbackResponse(Msg):
    accepted: bool
    replay_size: int
    train_steps: int
    duplicate: bool = False


class Reset(Msg):
    command: Literal["reset"]
    run_id: Id
    episode: Annotated[int, Field(ge=0)]
    mode: Literal["train", "eval"] = "train"
    fault_schedule: list[FaultWindow] | None = None


class Pause(Msg):
    command: Literal["pause"]


class Resume(Msg):
    command: Literal["resume"]


class Checkpoint(Msg):
    command: Literal["checkpoint"]


class SetSchedule(Msg):
    command: Literal["set_schedule"]
    fault_schedule: list[FaultWindow]


class EpisodeEnd(Msg):
    command: Literal["episode_end"]
    tick: Tick | None = None  # default: the node's own tick counter
    wait: bool = False  # block until the exchange window finished (bounded)


class Stop(Msg):
    command: Literal["stop"]


ControlRequest = Annotated[
    Reset | Pause | Resume | Checkpoint | SetSchedule | EpisodeEnd | Stop,
    Field(discriminator="command"),
]
CONTROL = TypeAdapter(ControlRequest)

MAX_BODY = 256 * 1024

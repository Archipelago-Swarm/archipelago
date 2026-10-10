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


Command = Literal["stay", "north", "east", "south", "west"]


class FeedbackRequest(Msg):
    """Feedback carries what was actually executed (A2): a fallback ``stay`` trains as ``stay``."""

    run_id: Id
    episode: Annotated[int, Field(ge=0)]
    tick: Tick
    reward: Finite
    next_observation: Observation
    terminated: bool
    truncated: bool = False
    executed_command: Command
    action_index: Annotated[int, Field(ge=0, le=4)]
    deadline_missed: bool = False


class FeedbackResponse(Msg):
    accepted: bool
    replay_size: int
    train_steps: int
    policy_version: int
    duplicate: bool = False


class Reset(Msg):
    command: Literal["reset"]
    run_id: Id
    episode: Annotated[int, Field(ge=0)]
    mode: Literal["train", "eval"] = "train"
    fault_schedule: list[FaultWindow] | None = None


class Hyperparameters(Msg):
    lr: Annotated[float, Field(gt=0, le=1)]
    gamma: Annotated[float, Field(ge=0, le=1)]
    hidden: Annotated[int, Field(ge=1, le=1024)]
    capacity: Annotated[int, Field(ge=1, le=1_000_000)]
    batch: Annotated[int, Field(ge=1, le=4096)]
    target_every: Annotated[int, Field(ge=1)]
    train_steps_per_feedback: Annotated[int, Field(ge=0, le=64)]


class EpsilonSchedule(Msg):
    start: Annotated[float, Field(ge=0, le=1)]
    end: Annotated[float, Field(ge=0, le=1)]
    decay_episodes: Annotated[int, Field(ge=1)]


class WorldConfig(Msg):
    size: Annotated[int, Field(ge=4, le=256)]
    n_targets: Annotated[int, Field(ge=0, le=1000)]
    obstacle_density: Annotated[float, Field(ge=0, lt=0.6)]
    sense_radius: Annotated[int, Field(ge=1, le=8)]
    max_ticks: Annotated[int, Field(ge=1, le=1_000_000)]
    battery_scale: Annotated[float, Field(gt=0, le=1000)]
    reward_id: str


class Configure(Msg):
    """Once per run, before the first reset (live-runtime.md section 14)."""

    command: Literal["configure"]
    run_id: Id
    hyperparameters: Hyperparameters
    epsilon_schedule: EpsilonSchedule
    margin: Finite
    world_config: WorldConfig
    gate_seeds: Annotated[list[int], Field(min_length=1, max_length=256)]
    n_validation_agents: Annotated[int, Field(ge=1, le=16)]
    encoder_id: str
    exchange_every_ticks: Annotated[int, Field(ge=0)]
    seed: int

    def canonical(self) -> dict:
        """The run configuration without the command and run id (what the hash covers)."""
        return self.model_dump(mode="json", exclude={"command", "run_id"})


class Pause(Msg):
    command: Literal["pause"]
    run_id: Id


class Resume(Msg):
    command: Literal["resume"]
    run_id: Id


class Checkpoint(Msg):
    command: Literal["checkpoint"]
    run_id: Id


class SetSchedule(Msg):
    command: Literal["set_schedule"]
    run_id: Id
    fault_schedule: list[FaultWindow]


class EpisodeEnd(Msg):
    command: Literal["episode_end"]
    run_id: Id
    episode: Annotated[int, Field(ge=0)]
    tick: Tick


class Stop(Msg):
    command: Literal["stop"]
    run_id: Id


ControlRequest = Annotated[
    Configure | Reset | Pause | Resume | Checkpoint | SetSchedule | EpisodeEnd | Stop,
    Field(discriminator="command"),
]
CONTROL = TypeAdapter(ControlRequest)

MAX_BODY = 256 * 1024

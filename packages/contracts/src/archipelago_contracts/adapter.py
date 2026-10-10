"""SimulatorAdapter protocol plus a replay-only fixture implementation.

FixtureAdapter replays recorded contract fixtures. It performs NO physics or mission logic and is
not the simulator (T03). It exists so UI/transport/node work can develop against a stable interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .models import Action, Observation, RunConfig, WorldSnapshot


@dataclass(frozen=True)
class SimulatorCapabilities:
    simulator: str
    dimensionality: str  # "2d" | "3d"
    action_space_version: str
    supports_substeps: bool = False


@dataclass(frozen=True)
class StepResult:
    observations: dict[str, Observation]
    rewards: dict[str, float]
    terminations: dict[str, bool]
    truncations: dict[str, bool]
    infos: dict[str, dict[str, str]] = field(default_factory=dict)


class SimulatorAdapter(Protocol):
    def capabilities(self) -> SimulatorCapabilities: ...
    def reset(self, config: RunConfig) -> dict[str, Observation]: ...
    def step(self, actions: dict[str, Action]) -> StepResult: ...
    def snapshot(self) -> WorldSnapshot: ...
    def close(self) -> None: ...


class FixtureAdapter:
    """Replays a fixed observation/snapshot; missing actions are ignored deterministically."""

    def __init__(self, observation: Observation, snapshot: WorldSnapshot) -> None:
        self._obs, self._snap = observation, snapshot
        self._nodes: list[str] = []
        self.steps = 0

    def capabilities(self) -> SimulatorCapabilities:
        return SimulatorCapabilities("fixture-replay", "2d", "act-v0")

    def reset(self, config: RunConfig) -> dict[str, Observation]:
        self._nodes = sorted(n.node_id for n in config.nodes)
        self.steps = 0
        return {n: self._obs.model_copy(update={"source_node_id": n}) for n in self._nodes}

    def step(self, actions: dict[str, Action]) -> StepResult:
        self.steps += 1
        obs = {n: self._obs.model_copy(update={"source_node_id": n}) for n in self._nodes}
        return StepResult(
            obs,
            {n: 0.0 for n in self._nodes},
            {n: False for n in self._nodes},
            {n: False for n in self._nodes},
        )

    def snapshot(self) -> WorldSnapshot:
        return self._snap

    def close(self) -> None:
        self._nodes = []

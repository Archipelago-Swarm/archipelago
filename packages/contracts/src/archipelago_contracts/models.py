"""Canonical v0 shared records. JSON Schema and TypeScript types are generated from here."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

SCHEMA_MAJOR = 0
SCHEMA_VERSION = "0.1.0"
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024  # provisional cap from interfaces.md

SchemaVersion = Annotated[str, Field(pattern=rf"^{SCHEMA_MAJOR}\.\d+\.\d+$")]
Id = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Finite = Annotated[float, Field(allow_inf_nan=False)]
Unit01 = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
Tick = Annotated[int, Field(ge=0)]


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(None):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value


UTC_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]00:00)$"
UtcTime = Annotated[
    datetime, AfterValidator(_require_utc), Field(json_schema_extra={"pattern": UTC_PATTERN})
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Pose(Strict):
    """ENU meters; 2D worlds fix z to 0."""

    x: Finite
    y: Finite
    z: Annotated[float, Field(ge=0, le=0)] = 0.0
    heading_rad: Finite = 0.0  # continuous flight: atan2(dy, dx) in the y-down map frame
    speed_mps: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.0


class Event(Strict):
    schema_version: SchemaVersion
    event_id: Id
    run_id: Id
    source_node_id: Id | None
    sim_tick: Tick
    emitted_at_utc: UtcTime
    sequence: Annotated[int, Field(ge=0)]


class Budgets(Strict):
    max_ticks: Annotated[int, Field(gt=0)]
    max_wall_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)]


class FaultWindow(Strict):
    start_tick: Tick
    end_tick: Tick
    cut_links: list[tuple[Id, Id]]


class NodeSpec(Strict):
    node_id: Id
    start_pose: Pose


class RunConfig(Strict):
    kind: Literal["run_config"] = "run_config"
    schema_version: SchemaVersion
    run_id: Id
    simulator: Id
    simulator_version: str
    scenario_hash: Sha256
    seeds: dict[Literal["env", "topology", "learner", "exploration"], int]
    nodes: Annotated[list[NodeSpec], Field(min_length=1)]
    observation_id: Id
    action_id: Id
    reward_id: Id
    mode: Literal["lockstep", "distributed"]
    learner: Literal["none", "independent_dqn", "peer_dqn"]
    budgets: Budgets
    fault_schedule: list[FaultWindow] = []


class Observation(Event):
    kind: Literal["observation"] = "observation"
    crop: list[list[int]]
    known_mask: list[list[bool]]
    pose: Pose
    battery: Unit01
    visible_markers: list[tuple[Finite, Finite]]
    neighbor_summaries: list[dict[str, Finite]] = []


class Action(Event):
    kind: Literal["action"] = "action"
    action_space_version: Id
    command: Literal["stay", "north", "east", "south", "west"]
    policy_version: Annotated[int, Field(ge=0)]


class Topology(Strict):
    links: list[tuple[Id, Id]]


class Shape(Strict):
    """Obstacle polygon in world meters (a publicly revealed one: some node has sensed it)."""

    id: Id
    points: Annotated[list[tuple[Finite, Finite]], Field(min_length=3)]


class Marker(Strict):
    x: Finite
    y: Finite
    radius: Finite


class TerrainGrid(Strict):
    """Whole-map terrain for display, row-major (index = y * size + x, size columns, height rows). `observed` marks the cells the
    fleet has actually sensed, so a viewer can draw unobserved terrain dimmed. Display only: nodes never get it."""

    size: Annotated[int, Field(ge=1, le=256)]  # width in cells
    height: Annotated[int, Field(ge=1, le=256)]
    biome: str  # one digit per cell: 0 grass, 1 forest, 2 jungle
    observed: str  # one char per cell: "1" observed by some node, "0" not
    elev_m: list[Finite]
    veg_pct: list[Annotated[int, Field(ge=0, le=100)]]


class WorldGeometry(Strict):
    """Continuous-flight world description (meters). Absent for the legacy grid world."""

    width_m: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    height_m: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    cell_m: Annotated[float, Field(gt=0, allow_inf_nan=False)]  # hidden perception/learning grid
    sensor_radius_m: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    shapes: list[Shape] = []
    targets_found: list[Marker] = []
    terrain: TerrainGrid | None = None  # absent for uniform worlds


class WorldSnapshot(Event):
    kind: Literal["world_snapshot"] = "world_snapshot"
    run_status: Literal[
        "created", "starting", "running", "paused", "stopping", "completed", "failed", "interrupted"
    ]
    poses: dict[Id, Pose]
    obstacles: list[tuple[int, int]]
    coverage: Unit01
    topology: Topology
    world: WorldGeometry | None = None


class PeerEnvelope(Event):
    kind: Literal["peer_envelope"] = "peer_envelope"
    type: Literal["hello", "model_offer", "model_request", "model_payload", "ack"]
    sender: Id
    recipient: Id
    message_id: Id
    model_version: Annotated[int, Field(ge=0)]
    architecture_hash: Sha256
    encoder_hash: Sha256
    reward_hash: Sha256
    payload_length: Annotated[int, Field(ge=0, le=MAX_PAYLOAD_BYTES)]
    payload_sha256: Sha256 | None
    ttl_ticks: Annotated[int, Field(gt=0)]


class LearningEvent(Event):
    kind: Literal["learning_event"] = "learning_event"
    update_count: Annotated[int, Field(ge=0)]
    loss: Finite | None
    previous_version: Annotated[int, Field(ge=0)]
    new_version: Annotated[int, Field(ge=0)]
    transfer: Literal["none", "accepted", "rejected"]
    reason: str | None = None
    candidate_score: Finite | None = None
    bytes: Annotated[int, Field(ge=0)] = 0
    wall_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.0


class MetricSample(Event):
    kind: Literal["metric_sample"] = "metric_sample"
    metric: Id
    value: Finite
    unit: Id
    phase: Literal["train", "eval", "partition", "recovery", "other"]


class ArtifactManifest(Strict):
    kind: Literal["artifact_manifest"] = "artifact_manifest"
    schema_version: SchemaVersion
    run_id: Id
    node_id: Id | None
    sim_tick: Tick
    path: Annotated[
        str,
        Field(
            min_length=1, pattern=r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*(/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*$"
        ),
    ]
    sha256: Sha256
    format: Id
    format_version: Id
    size_bytes: Annotated[int, Field(ge=0)]
    commit: Annotated[str, Field(pattern=r"^[0-9a-f]{7,40}$")]
    config_hash: Sha256


RECORDS: dict[str, type[BaseModel]] = {
    "run_config": RunConfig,
    "observation": Observation,
    "action": Action,
    "world_snapshot": WorldSnapshot,
    "peer_envelope": PeerEnvelope,
    "learning_event": LearningEvent,
    "metric_sample": MetricSample,
    "artifact_manifest": ArtifactManifest,
}

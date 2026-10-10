"""Environment-variable configuration for the node runtime (live-runtime.md section 3/8/10)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
MIN_TOKEN = 16


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    node_id: str
    node_ids: tuple[str, ...]
    control_token: str
    checkpoint_dir: Path
    peer_urls: dict[str, str] = field(default_factory=dict)
    bind_host: str = "127.0.0.1"
    peer_port: int = 9000
    control_port: int = 8000
    telemetry_url: str | None = None
    telemetry_token: str | None = None
    torch_threads: int = 1
    seed: int = 0
    # learner
    hidden: int = 32
    lr: float = 1e-2
    gamma: float = 0.95
    capacity: int = 5000
    batch: int = 32
    target_every: int = 50
    train_steps_per_feedback: int = 1
    eps_start: float = 0.5
    eps_end: float = 0.05
    eps_decay_acts: int = 5000
    mode: str = "independent"
    mix_alpha: float | None = None
    # peer exchange
    peer_margin: float = 0.0
    peer_timeout: float = 1.0
    peer_retries: int = 1
    exchange_wait_max: float = 30.0
    # private validation world (same world config as the live world, one drone)
    world_size: int = 16
    world_n_targets: int = 3
    world_obstacle_density: float = 0.12
    world_sense_radius: int = 2
    world_max_ticks: int = 900
    world_battery_scale: float = 1.0
    reward_id: str = "rew-v0"
    validation_seeds: tuple[int, ...] = (9001, 9002, 9003)
    test_seeds: tuple[int, ...] = ()  # only used to refuse overlap with validation seeds
    validation_max_ticks: int | None = None  # default: world_max_ticks
    # telemetry
    spool_max_records: int = 20000
    spool_segment_records: int = 500
    ship_batch: int = 200
    ship_interval: float = 0.5
    ship_timeout: float = 2.0
    update_every: int = 25
    # misc
    act_cache: int = 1024
    commit: str = "unknown"
    host: str = field(default_factory=socket.gethostname)

    def __post_init__(self) -> None:
        if not _ID.match(self.node_id):
            raise ConfigError(f"bad NODE_ID {self.node_id!r}")
        if self.node_id not in self.node_ids:
            raise ConfigError("NODE_ID must be listed in NODE_IDS")
        for n in self.node_ids:
            if not _ID.match(n):
                raise ConfigError(f"bad node id {n!r} in NODE_IDS")
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ConfigError("NODE_IDS has duplicates")
        if len(self.control_token) < MIN_TOKEN:
            raise ConfigError(f"NODE_CONTROL_TOKEN must be at least {MIN_TOKEN} characters")
        if self.mode not in ("independent", "information_only", "mixing"):
            raise ConfigError(f"bad LEARNER_MODE {self.mode!r}")
        if self.mode == "mixing" and not (self.mix_alpha and 0 < self.mix_alpha <= 0.5):
            raise ConfigError("mixing mode needs 0 < MIX_ALPHA <= 0.5")
        if not self.validation_seeds:
            raise ConfigError("VALIDATION_SEEDS must not be empty")
        if set(self.validation_seeds) & set(self.test_seeds):
            raise ConfigError("VALIDATION_SEEDS overlap TEST_SEEDS: test seeds never gate")
        for k in ("hidden", "capacity", "batch", "target_every", "spool_max_records"):
            if getattr(self, k) < 1:
                raise ConfigError(f"{k} must be >= 1")
        if self.train_steps_per_feedback < 0 or self.torch_threads < 1:
            raise ConfigError("bad train_steps_per_feedback / torch_threads")
        if self.eps_decay_acts < 1:
            raise ConfigError("eps_decay_acts must be >= 1")

    @property
    def obs_dim(self) -> int:
        return (2 * self.world_sense_radius + 1) ** 2 + 3

    @property
    def learner_seed(self) -> int:
        """Distinct per node (index in the sorted manifest), so nodes never share an init."""
        return self.seed * 1000 + sorted(self.node_ids).index(self.node_id)

    @property
    def val_ticks(self) -> int:
        return self.validation_max_ticks or self.world_max_ticks

    @property
    def config_hash(self) -> str:
        d = asdict(self)
        for k in ("control_token", "telemetry_token", "checkpoint_dir", "host", "node_id"):
            d.pop(k, None)  # secrets and per-node/host values are not part of the run config
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()

    def with_(self, **kw) -> Config:
        return replace(self, **kw)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        e = os.environ if env is None else env

        def get(k: str, default=None):
            v = e.get(k)
            return default if v is None or v == "" else v

        def num(k: str, default, cast):
            v = get(k)
            if v is None:
                return default
            try:
                return cast(v)
            except ValueError as ex:
                raise ConfigError(f"{k}={v!r} is not a valid {cast.__name__}") from ex

        def ints(k: str, default: tuple[int, ...]) -> tuple[int, ...]:
            v = get(k)
            if v is None:
                return default
            try:
                return tuple(int(x) for x in v.split(",") if x.strip())
            except ValueError as ex:
                raise ConfigError(f"{k} must be comma separated integers") from ex

        node_id = get("NODE_ID")
        if node_id is None:
            raise ConfigError("NODE_ID is required")
        ids = tuple(x.strip() for x in (get("NODE_IDS") or node_id).split(",") if x.strip())
        urls: dict[str, str] = {}
        for part in (get("PEER_URLS") or "").split(","):
            if part.strip():
                k, sep, u = part.strip().partition("=")
                if not sep or not u:
                    raise ConfigError("PEER_URLS entries look like node-01=http://host:9000")
                urls[k] = u
        token = get("NODE_CONTROL_TOKEN")
        if token is None:
            raise ConfigError("NODE_CONTROL_TOKEN is required")
        ckpt = get("NODE_CHECKPOINT_DIR")
        if ckpt is None:
            raise ConfigError("NODE_CHECKPOINT_DIR is required")
        vmt = get("VALIDATION_MAX_TICKS")
        mix = get("MIX_ALPHA")
        return cls(
            node_id=node_id,
            node_ids=ids,
            control_token=token,
            checkpoint_dir=Path(ckpt),
            peer_urls=urls,
            bind_host=get("BIND_HOST", "127.0.0.1"),
            peer_port=num("PEER_PORT", 9000, int),
            control_port=num("CONTROL_PORT", 8000, int),
            telemetry_url=get("TELEMETRY_URL"),
            telemetry_token=get("TELEMETRY_TOKEN"),
            torch_threads=num("TORCH_THREADS", 1, int),
            seed=num("SEED", 0, int),
            hidden=num("HIDDEN", 32, int),
            lr=num("LR", 1e-2, float),
            gamma=num("GAMMA", 0.95, float),
            capacity=num("REPLAY_CAPACITY", 5000, int),
            batch=num("BATCH_SIZE", 32, int),
            target_every=num("TARGET_EVERY", 50, int),
            train_steps_per_feedback=num("TRAIN_STEPS_PER_FEEDBACK", 1, int),
            eps_start=num("EPS_START", 0.5, float),
            eps_end=num("EPS_END", 0.05, float),
            eps_decay_acts=num("EPS_DECAY_ACTS", 5000, int),
            mode=get("LEARNER_MODE", "independent"),
            mix_alpha=float(mix) if mix else None,
            peer_margin=num("PEER_MARGIN", 0.0, float),
            peer_timeout=num("PEER_TIMEOUT", 1.0, float),
            peer_retries=num("PEER_RETRIES", 1, int),
            world_size=num("WORLD_SIZE", 16, int),
            world_n_targets=num("WORLD_N_TARGETS", 3, int),
            world_obstacle_density=num("WORLD_OBSTACLE_DENSITY", 0.12, float),
            world_sense_radius=num("WORLD_SENSE_RADIUS", 2, int),
            world_max_ticks=num("WORLD_MAX_TICKS", 900, int),
            world_battery_scale=num("WORLD_BATTERY_SCALE", 1.0, float),
            reward_id=get("REWARD_ID", "rew-v0"),
            validation_seeds=ints("VALIDATION_SEEDS", (9001, 9002, 9003)),
            test_seeds=ints("TEST_SEEDS", ()),
            validation_max_ticks=int(vmt) if vmt else None,
            spool_max_records=num("TELEMETRY_SPOOL_MAX_RECORDS", 20000, int),
            spool_segment_records=num("TELEMETRY_SPOOL_SEGMENT_RECORDS", 500, int),
            ship_batch=num("TELEMETRY_BATCH", 200, int),
            ship_interval=num("TELEMETRY_INTERVAL", 0.5, float),
            ship_timeout=num("TELEMETRY_TIMEOUT", 2.0, float),
            update_every=num("TELEMETRY_UPDATE_EVERY", 25, int),
            commit=get("GIT_COMMIT", "unknown"),
            host=get("HOSTNAME") or socket.gethostname(),
        )

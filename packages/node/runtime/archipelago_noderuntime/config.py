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

from archipelago_learning import encoders, schedules
from archipelago_sim.env import REWARD_SPECS

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
    peer_token: str = ""
    peer_urls: dict[str, str] = field(default_factory=dict)
    bind_host: str = "127.0.0.1"
    peer_port: int = 9000
    control_port: int = 8080
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
    # A18: versioned recipe. sched-v0 = legacy (epsilon per act); a registered id (sched-t37-v1)
    # fixes the values above, switches epsilon to per training episode and enables double DQN.
    learner_schedule_id: str = schedules.LEGACY
    double_dqn: bool = False
    eps_decay_episodes: int | None = None  # per-episode epsilon span (None: legacy per-act decay)
    encoder_family: str = "grid-flat-v1"
    mode: str = "independent"
    mix_alpha: float | None = None
    # peer exchange
    peer_margin: float = 0.0
    peer_timeout: float = 1.0
    peer_retries: int = 1
    exchange_every_ticks: int = 50  # A1: windows on the node's own tick cadence (0 = off)
    window_cancel_wait: float = 5.0  # A4: reset waits this long for a running window, then cancels
    # private validation world (same world config as the live world, one drone)
    world_size: int = 16
    world_n_targets: int = 3
    world_obstacle_density: float = 0.12
    world_sense_radius: int = 2
    world_max_ticks: int = 900
    world_battery_scale: float = 1.0
    reward_id: str = "rew-v0"
    n_validation_agents: int = 1
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
    # A18 visited-cell summaries (non-model peer message)
    summary_timeout: float = 0.5
    summary_trace: bool = False  # status lists the ticks at which each peer's summary was applied
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
        if len(self.peer_token) < MIN_TOKEN:
            raise ConfigError(f"PEER_TOKEN must be at least {MIN_TOKEN} characters")
        for k, u in self.peer_urls.items():
            if k not in self.node_ids or not u.startswith(("http://", "https://")):
                raise ConfigError(f"bad PEER_URLS entry {k}={u!r}: node-01=http://host:9000")
        if self.exchange_every_ticks < 0 or self.window_cancel_wait < 0:
            raise ConfigError("exchange_every_ticks and window_cancel_wait must be >= 0")
        if not 1 <= self.n_validation_agents <= 16:
            raise ConfigError("n_validation_agents must be in 1..16")
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
        if self.eps_decay_episodes is not None and self.eps_decay_episodes < 1:
            raise ConfigError("eps_decay_episodes must be >= 1")
        if self.reward_id not in REWARD_SPECS:
            raise ConfigError(f"unknown reward_id {self.reward_id!r}")
        if encoders.parse(self.encoder_id) is None:
            raise ConfigError(f"unknown encoder {self.encoder_id!r}")
        try:
            schedules.check(
                self.learner_schedule_id,
                {
                    k: getattr(self, k)
                    for k in (
                        "lr", "gamma", "hidden", "capacity", "batch", "target_every",
                        "train_steps_per_feedback",
                    )
                },  # fmt: skip
                {"start": self.eps_start, "end": self.eps_end},
                self.double_dqn,
            )
        except ValueError as e:
            raise ConfigError(str(e)) from e
        if self.learner_schedule_id != schedules.LEGACY and self.eps_decay_episodes is None:
            raise ConfigError(f"{self.learner_schedule_id} needs eps_decay_episodes")

    @property
    def obs_dim(self) -> int:
        return encoders.get(self.encoder_id).obs_dim

    @property
    def encoder_id(self) -> str:
        """A6: geometry is part of the id (``{family}-s{size}-r{radius}``)."""
        return f"{self.encoder_family}-s{self.world_size}-r{self.world_sense_radius}"

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
        for k in (
            "control_token",
            "peer_token",
            "telemetry_token",
            "checkpoint_dir",
            "host",
            "node_id",
        ):
            d.pop(k, None)  # secrets and per-node/host values are not part of the run config
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()

    def with_(self, **kw) -> Config:
        return replace(self, **kw)

    def with_run(self, c) -> Config:
        """Apply a ``configure`` command (section 14). Raises ConfigError on inconsistent input."""
        h, e, w = c.hyperparameters, c.epsilon_schedule, c.world_config
        geometry = f"-s{w.size}-r{w.sense_radius}"
        enc = encoders.parse(c.encoder_id)
        if enc is None or not c.encoder_id.endswith(geometry):
            raise ConfigError(
                f"encoder_id {c.encoder_id!r} is unknown or does not match the world "
                f"(geometry {geometry[1:]})"
            )
        if w.reward_id not in REWARD_SPECS:
            raise ConfigError(f"unknown reward_id {w.reward_id!r}")
        sid = c.learner_schedule_id
        try:
            schedules.check(sid, h.model_dump(), e.model_dump(), h.double_dqn)
        except ValueError as ex:
            raise ConfigError(str(ex)) from ex
        return self.with_(
            encoder_family=c.encoder_id[: -len(geometry)], reward_id=w.reward_id,
            learner_schedule_id=sid, double_dqn=h.double_dqn,
            eps_decay_episodes=e.decay_episodes if sid != schedules.LEGACY else None,
            hidden=h.hidden, lr=h.lr, gamma=h.gamma, capacity=h.capacity, batch=h.batch,
            target_every=h.target_every, train_steps_per_feedback=h.train_steps_per_feedback,
            eps_start=e.start, eps_end=e.end, eps_decay_acts=e.decay_episodes * w.max_ticks,
            peer_margin=c.margin, world_size=w.size, world_n_targets=w.n_targets,
            world_obstacle_density=w.obstacle_density, world_sense_radius=w.sense_radius,
            world_max_ticks=w.max_ticks, world_battery_scale=w.battery_scale,
            validation_seeds=tuple(c.gate_seeds), n_validation_agents=c.n_validation_agents,
            exchange_every_ticks=c.exchange_every_ticks, seed=c.seed,
        )  # fmt: skip

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
        peer_token = get("PEER_TOKEN")
        if peer_token is None:
            raise ConfigError("PEER_TOKEN is required")
        ckpt = get("NODE_CHECKPOINT_DIR")
        if ckpt is None:
            raise ConfigError("NODE_CHECKPOINT_DIR is required")
        vmt = get("VALIDATION_MAX_TICKS")
        mix = get("MIX_ALPHA")
        sid = get("LEARNER_SCHEDULE_ID", schedules.LEGACY)
        reg = schedules.SCHEDULES.get(sid)  # a registered recipe supplies the defaults
        return cls(
            node_id=node_id,
            node_ids=ids,
            control_token=token,
            checkpoint_dir=Path(ckpt),
            peer_token=peer_token,
            peer_urls=urls,
            bind_host=get("BIND_HOST", "127.0.0.1"),
            peer_port=num("PEER_PORT", 9000, int),
            control_port=num("CONTROL_PORT", 8080, int),
            telemetry_url=get("TELEMETRY_URL"),
            telemetry_token=get("TELEMETRY_TOKEN"),
            torch_threads=num("TORCH_THREADS", 1, int),
            seed=num("SEED", 0, int),
            hidden=num("HIDDEN", 32, int),
            lr=num("LR", reg.lr if reg else 1e-2, float),
            gamma=num("GAMMA", 0.95, float),
            capacity=num("REPLAY_CAPACITY", reg.capacity if reg else 5000, int),
            batch=num("BATCH_SIZE", 32, int),
            target_every=num("TARGET_EVERY", 50, int),
            train_steps_per_feedback=num("TRAIN_STEPS_PER_FEEDBACK", 1, int),
            eps_start=num("EPS_START", reg.eps_start if reg else 0.5, float),
            eps_end=num("EPS_END", 0.05, float),
            eps_decay_acts=num("EPS_DECAY_ACTS", 5000, int),
            learner_schedule_id=sid,
            double_dqn=get("DOUBLE_DQN", "1" if reg and reg.double_dqn else "0") in ("1", "true"),
            eps_decay_episodes=num("EPS_DECAY_EPISODES", 200, int) if reg else None,
            encoder_family=get("ENCODER_FAMILY", "grid-flat-v1"),
            summary_timeout=num("SUMMARY_TIMEOUT", 0.5, float),
            summary_trace=get("SUMMARY_TRACE", "0") in ("1", "true"),
            mode=get("LEARNER_MODE", "independent"),
            mix_alpha=float(mix) if mix else None,
            exchange_every_ticks=num("EXCHANGE_EVERY_TICKS", 50, int),
            window_cancel_wait=num("WINDOW_CANCEL_WAIT", 5.0, float),
            n_validation_agents=num("N_VALIDATION_AGENTS", 1, int),
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

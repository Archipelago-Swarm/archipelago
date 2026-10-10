"""Node core: owns a TorchLearner and everything around it (live-runtime.md sections 3, 5, 7, 8,
13 amendments A1-A7, A16, A17, and the normative message shapes of section 14).

Concurrency design (justified, and tested with a stalled peer, a stalled sink and a held lock):

* ``act`` takes only ``amu`` (a few microseconds: idempotency map, exploration RNG, sequence) and
  reads the immutable published inference snapshot. It never takes ``mu`` and never does peer or
  telemetry I/O, so it cannot wait for an optimizer step, a checkpoint, a validation, a peer call
  or the sink. The one bounded exception is the feedback barrier (A2): if the feedback of an
  EARLIER tick of the same episode is being processed right now, ``act`` waits for it (at most
  ``deadline_ms``, capped at 1 s) so that act(t+1) deterministically sees the post-feedback(t)
  policy. A coordinator that honours the barrier never triggers this wait.
* ``feedback`` trains INLINE under ``mu`` with a bounded number of optimizer steps per call
  (``train_steps_per_feedback``, default 1, about 1 ms): N feedbacks -> N steps, reproducibly. The
  new inference snapshot is published inside ``train_step``, i.e. before the response is sent.
* Everything slow runs on ONE background worker thread: exchange windows (cadence windows from the
  node's own tick counter and the final window at ``episode_end``, including validation in the
  private world) and periodic checkpoints. Telemetry shipping runs on the shipper thread. While a
  validation is in progress optimizer steps are deferred (transitions are still stored) so the
  parameters being judged are the parameters being replaced.
* Lock order: fbl -> mu -> amu. ``act`` and ``reset`` only ever take amu. The worker's queue lock
  (``_xcv``) is a leaf: it is never held while taking another lock or doing work.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from archipelago_contracts import SCHEMA_VERSION
from archipelago_contracts.models import Action, LearningEvent, MetricSample
from archipelago_learning import OfferWindow, PeerError, TorchLearner, decode, encode, offer
from archipelago_learning.checkpoint import CheckpointError, SequenceAllocator, checkpoint_due
from archipelago_peer import post
from archipelago_transport import Envelope

from . import ckpt
from .config import Config, ConfigError
from .encoder import (
    ACTION_SPACE_VERSION,
    ACTIONS,
    EncodeError,
    encode_observation,
    for_world,
)
from .peering import Schedule
from .protocol import ActRequest, ActResponse, Configure, FeedbackRequest, FeedbackResponse
from .telemetry import Spool
from .validation import ValidationWorld, WindowCancelled, params_digest

KEYS = ("w1", "b1", "w2", "b2")
MAX_FB_WAIT = 1.0  # cap of the feedback-barrier wait in act (seconds)
MAX_QUEUED_WINDOWS = 8
MAX_PERSISTED_PENDING = 64
RUN_CONF = "run_config.json"


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str = ""):
        super().__init__(f"{status} {code} {detail}")
        self.status, self.code, self.detail = status, code, detail


def rss_bytes() -> int:
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return rss_peak_bytes()


def rss_peak_bytes() -> int:
    """Peak resident set size of this process so far (kernel high-water mark)."""
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024  # KiB on Linux


@dataclass(eq=False)
class Job:
    """One unit of background work: an exchange window or a periodic checkpoint."""

    kind: str  # "window" | "checkpoint"
    id: str
    tick: int = 0
    episode: int = 0
    final: bool = False
    skip_exchange: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None


def _pct(xs: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(xs), q)) if xs else 0.0


class Node:
    def __init__(self, cfg: Config, ckpt_io=None):
        self.boot_id = uuid.uuid4().hex[:8]  # A3: 8 hex characters per process start
        self.ckpt_io = ckpt_io  # fault-injection seam for the checkpoint writer (tests)
        cfg.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.run_conf = self._load_run_conf(cfg.checkpoint_dir)  # last configure this volume took
        if self.run_conf is not None:
            try:
                saved = {**self.run_conf["body"], "command": "configure"}
                cfg = cfg.with_run(
                    Configure.model_validate({**saved, "run_id": self.run_conf["run_id"]})
                )
            except (ValueError, KeyError, TypeError) as e:  # ValidationError is a ValueError
                raise ConfigError(f"unreadable {RUN_CONF} in {cfg.checkpoint_dir}: {e}") from e
        self.cfg = cfg
        self.ckpt_dir = cfg.checkpoint_dir / "ckpt"
        self._build()
        self.seq = SequenceAllocator(cfg.checkpoint_dir / "sequence.json")  # A3 event sequence
        self.peer_seq = SequenceAllocator(cfg.checkpoint_dir / "peer_seq.json")  # peer client seq
        self.spool = Spool(
            cfg.checkpoint_dir / "telemetry", cfg.spool_max_records, cfg.spool_segment_records
        )
        self.mu, self.amu, self.fbl = threading.Lock(), threading.Lock(), threading.Lock()
        self.ckl = threading.Lock()
        self.acv = threading.Condition(self.amu)  # signals "a feedback finished" to act
        # episode / step state (guarded by amu)
        self.run_id: str | None = None
        self.episode = -1
        self.tick = -1
        self.fed_tick = -1
        self.fb_inflight: tuple | None = None
        self.mode = "train"
        self.train_paused = False
        self.act_count = 0
        self.schedule = Schedule()
        self.act_cache: OrderedDict[tuple, dict] = OrderedDict()
        self.pending: OrderedDict[tuple, tuple[np.ndarray, int]] = OrderedDict()
        self.fb_cache: OrderedDict[tuple, dict] = OrderedDict()
        self.counters: dict[str, int] = {
            k: 0
            for k in (
                "acts", "act_duplicates", "act_stale", "act_fb_wait_timeouts", "feedbacks",
                "feedback_duplicates", "feedback_stale", "feedback_no_pending",
                "feedback_executed_differs", "feedback_deadline_missed", "train_deferred",
                "offers_sent", "offers_cut", "offers_unchanged", "offers_unreachable",
                "offers_refused_by_peer", "offers_received", "received_cut",
                "received_superseded", "received_duplicate", "decisions_accepted",
                "decisions_rejected", "decisions_window_limit", "exchanges",
                "windows_cancelled", "windows_dropped", "checkpoints", "spool_errors",
                "implicit_episode_advances",
            )
        }  # fmt: skip
        self.act_lat: deque[float] = deque(maxlen=4096)
        self.loss_ema: float | None = None
        self.checkpoint_generation = 0
        self.restore_info: dict = {"restored": False}
        # run configuration (configure command)
        self.cfgl = threading.Lock()
        self.configured_run: str | None = None
        self.run_hash: str | None = None
        if self.run_conf is not None:
            self.configured_run = self.run_conf["run_id"]
            self.run_hash = self.run_conf["config_hash"]
        # peer / exchange state
        self.peer_urls: dict[str, str] = dict(cfg.peer_urls)
        self.peer = None  # GatedPeerServer, attached by the runtime
        self.ready = False
        self.exchange_active = False
        self.last_exchange: dict | None = None
        self.last_window_id: str | None = None
        self.results: OrderedDict[str, dict] = OrderedDict()  # window id -> result (bounded)
        self.dedupe: OrderedDict[str, None] = OrderedDict()
        self.last_sent: dict[str, tuple[int, str]] = {}
        self._xcv = threading.Condition()
        self._jobs: deque[Job] = deque()
        self._cur: Job | None = None
        self._jseq = 0
        self._ends: OrderedDict[tuple, str] = OrderedDict()  # (run, episode) -> final window id
        self._xthread: threading.Thread | None = None
        self._closing = False
        self.stop_event = threading.Event()
        # local-update telemetry aggregation (guarded by mu)
        self._lu_losses: list[float] = []
        self._lu_first_version = 0
        self._restore()

    # --- construction helpers --------------------------------------------------------------
    def _build(self) -> None:
        """(Re)create the learner, encoder, exploration RNG and validation world from self.cfg."""
        cfg = self.cfg
        self.enc = for_world(cfg.world_size, cfg.world_sense_radius)  # A6
        self.learner = TorchLearner(
            cfg.node_id,
            self.enc.obs_dim,
            len(ACTIONS),
            hidden=cfg.hidden,
            seed=cfg.learner_seed,
            lr=cfg.lr,
            gamma=cfg.gamma,
            capacity=cfg.capacity,
            mode=cfg.mode,
            encoder=self.enc.id,
            threads=cfg.torch_threads,
        )
        assert self.learner.encoder_sha256 == self.enc.sha256
        self.act_rng = np.random.default_rng([cfg.learner_seed, 7919])
        self.validator = ValidationWorld(cfg)

    @staticmethod
    def _load_run_conf(directory: Path) -> dict | None:
        try:
            return json.loads((directory / RUN_CONF).read_bytes())
        except (OSError, ValueError):
            return None

    def _save_run_conf(self, run_id: str, h: str, body: dict) -> None:
        path = self.cfg.checkpoint_dir / RUN_CONF
        tmp = path.with_name(RUN_CONF + ".tmp")
        with open(tmp, "wb") as f:
            f.write(json.dumps({"run_id": run_id, "config_hash": h, "body": body}).encode())
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        self.run_conf = {"run_id": run_id, "config_hash": h, "body": body}

    # --- helpers ---------------------------------------------------------------------------
    @property
    def eff_tick(self) -> int:
        return max(self.tick, 0)

    @property
    def config_hash(self) -> str:
        return self.run_hash or self.cfg.config_hash

    def gtick(self, tick: int, episode: int | None = None) -> int:
        """A7: simulation time of a record = episode * max_ticks + tick (global index)."""
        ep = self.episode if episode is None else episode
        return max(ep, 0) * self.cfg.world_max_ticks + max(tick, 0)

    def link_cut(self, other: str) -> bool:
        return self.schedule.cut(self.cfg.node_id, other, self.eff_tick)

    def _alloc_locked(self) -> tuple[int, str]:
        seq = self.seq.next()  # block-reserved: persisted ceiling is ahead of every issued number
        return seq, f"{self.cfg.node_id}-{self.boot_id}-{seq}"

    def _phase(self) -> str:
        if self.mode == "eval":
            return "eval"
        if any(self.link_cut(p) for p in self.cfg.node_ids if p != self.cfg.node_id):
            return "partition"
        return "train"

    def _emit(self, cls, phase: str | None = None, tick: int | None = None, **fields) -> None:
        """Build a canonical record and append it to the durable spool (no network, no raise)."""
        with self.amu:
            seq, eid = self._alloc_locked()
            run_id = self.run_id or "run-none"
            sim_tick = self.gtick(self.eff_tick if tick is None else tick)
            phase = phase or self._phase()
        if cls is MetricSample:
            fields["phase"] = phase
        rec = cls(
            schema_version=SCHEMA_VERSION,
            event_id=eid,
            run_id=run_id,
            source_node_id=self.cfg.node_id,
            sim_tick=sim_tick,
            emitted_at_utc=datetime.now(UTC),
            sequence=seq,
            **fields,
        )
        try:
            self.spool.append(
                {"event_id": eid, "phase": phase, "record": rec.model_dump(mode="json")}
            )
        except OSError:
            self.counters["spool_errors"] += 1

    def _metric(self, name: str, value: float, unit: str, phase: str | None = None) -> None:
        if math.isfinite(value):
            self._emit(MetricSample, phase, metric=name, value=float(value), unit=unit)

    def telemetry_context(self) -> dict:
        """A7 request-level context stored beside the events (records cannot carry it)."""
        ctx = {
            "commit": self.cfg.commit,
            "config_hash": self.config_hash,
            "seed": self.cfg.seed,
            "host": self.cfg.host,
            "boot_id": self.boot_id,
        }
        if self.episode >= 0:
            ctx["episode"] = self.episode
        return ctx

    # --- run configuration (A5) --------------------------------------------------------------
    def control_configure(self, c: Configure) -> dict:
        h = hashlib.sha256(json.dumps(c.canonical(), sort_keys=True).encode()).hexdigest()
        with self.cfgl:
            if self.configured_run == c.run_id:
                if h == self.run_hash:
                    return {"ok": True, "config_hash": h, "duplicate": True}
                raise ApiError(409, "config_conflict", "run already configured differently")
            try:
                new = self.cfg.with_run(c)
            except (ConfigError, ValueError) as e:
                raise ApiError(422, "bad_config", str(e)) from e
            self._settle_windows()
            with self.fbl, self.mu, self.amu:
                # A new run starts from a fresh learner; the previous run's generations are kept
                # aside (never deleted) so a restart can not mix them into this run.
                if self.ckpt_dir.exists():
                    self.ckpt_dir.rename(
                        self.cfg.checkpoint_dir / f"ckpt-before-{c.run_id}-{self.boot_id}"
                    )
                self.cfg = new
                self._build()
                self.run_id, self.episode, self.tick, self.fed_tick = None, -1, -1, -1
                self.act_count, self.loss_ema, self.train_paused = 0, None, False
                self.mode, self.schedule = "train", Schedule()
                self.act_cache.clear()
                self.pending.clear()
                self.fb_cache.clear()
                self.dedupe.clear()
                self.last_sent.clear()
                self.checkpoint_generation = 0
                self._lu_losses = []
                self.configured_run, self.run_hash = c.run_id, h
                self._save_run_conf(c.run_id, h, c.canonical())
        return {"ok": True, "config_hash": h}

    # --- episode control -------------------------------------------------------------------
    def _new_episode(self, run_id: str, episode: int, mode: str | None = None) -> None:
        self.run_id, self.episode, self.tick, self.fed_tick = run_id, episode, -1, -1
        if mode is not None:
            self.mode = mode
        self.act_cache.clear()
        self.pending.clear()
        self.fb_cache.clear()

    def _check_run(self, run_id: str, episode: int, advance: bool) -> None:
        """Caller holds amu. Raises 409 for a foreign run or an episode in the past (A2/A3: the
        stale rule is lexicographic on (episode, tick); the tick half is checked by the caller)."""
        if self.run_id is None:
            if self.configured_run is not None and run_id != self.configured_run:
                raise ApiError(
                    409, "wrong_run", f"node is configured for run {self.configured_run}"
                )
            self._new_episode(run_id, episode)
        elif run_id != self.run_id:
            raise ApiError(409, "wrong_run", f"node is in run {self.run_id}")
        elif episode < self.episode:
            raise ApiError(409, "stale", f"episode {episode} < {self.episode}")
        elif episode > self.episode:
            if not advance:
                raise ApiError(409, "episode_not_acted", f"episode {episode} has no act yet")
            self.counters["implicit_episode_advances"] += 1
            self._new_episode(run_id, episode)

    def _check_command_run(self, run_id: str) -> None:
        """Commands other than configure/reset must name the run the node is in."""
        known = self.run_id or self.configured_run
        if known is not None and run_id != known:
            raise ApiError(409, "wrong_run", f"node is in run {known}")

    def control_reset(self, c) -> dict:
        if self.configured_run is not None and c.run_id != self.configured_run:
            raise ApiError(409, "wrong_run", f"node is configured for run {self.configured_run}")
        self._settle_windows()  # A4: wait <= window_cancel_wait for a running window, then cancel
        with self.amu:
            if self.run_id == c.run_id:
                if c.episode < self.episode:
                    raise ApiError(409, "stale", f"episode {c.episode} < {self.episode}")
                dup = c.episode == self.episode and c.mode == self.mode  # retry: keep caches
            else:
                dup = False
            if not dup:
                self._new_episode(c.run_id, c.episode, c.mode)
            if c.fault_schedule is not None:
                self.schedule = Schedule(c.fault_schedule)
            version = self.learner.version
        return {"ok": True, "policy_version": version, "duplicate": dup}

    def control_set_schedule(self, c) -> dict:
        self._check_command_run(c.run_id)
        with self.amu:
            self.schedule = Schedule(c.fault_schedule)
        return {"ok": True, "schedule_sha256": self.schedule.sha256}

    def control_pause(self, run_id: str, paused: bool) -> dict:
        self._check_command_run(run_id)
        with self.amu:
            self.train_paused = paused
        return {"ok": True, "train_paused": paused}

    # --- acting ----------------------------------------------------------------------------
    def epsilon(self) -> float:
        if self.mode == "eval":
            return 0.0
        c = self.cfg
        frac = min(1.0, self.act_count / c.eps_decay_acts)
        return c.eps_start + (c.eps_end - c.eps_start) * frac

    def _await_feedback_locked(self, req: ActRequest) -> None:
        """Caller holds amu (the condition's lock). Bounded wait for an in-flight earlier fb."""
        end = time.monotonic() + min(req.deadline_ms / 1000.0, MAX_FB_WAIT)
        while True:
            fk = self.fb_inflight
            if fk is None or fk[0] != req.run_id or fk[1] != req.episode or fk[2] >= req.tick:
                return
            left = end - time.monotonic()
            if left <= 0:
                self.counters["act_fb_wait_timeouts"] += 1
                return
            self.acv.wait(left)

    def act(self, req: ActRequest) -> dict:
        t0 = time.perf_counter()
        try:
            vec = encode_observation(self.enc, req.observation)
        except EncodeError as e:
            raise ApiError(422, "bad_observation", str(e)) from e
        key = (req.run_id, req.episode, req.tick)
        window_tick = None
        with self.amu:
            self._check_run(req.run_id, req.episode, advance=True)
            hit = self.act_cache.get(key)
            if hit is not None:
                self.counters["act_duplicates"] += 1
                return hit
            if self.mode == "train":
                self._await_feedback_locked(req)
                self._check_run(req.run_id, req.episode, advance=True)  # state may have moved
                hit = self.act_cache.get(key)
                if hit is not None:
                    self.counters["act_duplicates"] += 1
                    return hit
            if req.tick <= self.tick:
                self.counters["act_stale"] += 1
                raise ApiError(409, "stale", f"tick {req.tick} <= last acted {self.tick}")
            eps = self.epsilon()
            snap = self.learner._published  # immutable; replaced atomically by the trainer
            if eps > 0 and self.act_rng.random() < eps:
                a = int(self.act_rng.integers(len(ACTIONS)))
            else:
                a = int(np.argmax(snap.q(vec)))
            if self.mode == "train":
                self.act_count += 1
            seq, eid = self._alloc_locked()
            version = self.learner.version
            action = Action(
                schema_version=SCHEMA_VERSION,
                event_id=eid,
                run_id=req.run_id,
                source_node_id=self.cfg.node_id,
                sim_tick=self.gtick(req.tick, req.episode),
                emitted_at_utc=datetime.now(UTC),
                sequence=seq,
                action_space_version=ACTION_SPACE_VERSION,
                command=ACTIONS[a],
                policy_version=version,
            )
            out = ActResponse(
                node_id=self.cfg.node_id,
                tick=req.tick,
                action=action,
                policy_version=version,
                epsilon=eps,
            ).model_dump(mode="json")
            self.tick = req.tick
            self.counters["acts"] += 1
            self.act_cache[key] = out
            while len(self.act_cache) > self.cfg.act_cache:
                self.act_cache.popitem(last=False)
            if self.mode == "train":
                self.pending[key] = (vec, a)
                while len(self.pending) > self.cfg.act_cache:
                    self.pending.popitem(last=False)
                n = self.cfg.exchange_every_ticks
                if n and req.tick > 0 and req.tick % n == 0:
                    window_tick = req.tick  # A1: the node's own tick counter triggers a window
            self.act_lat.append(time.perf_counter() - t0)
        if window_tick is not None:
            self._enqueue(Job("window", self._next_id("w"), window_tick, req.episode))
        return out

    # --- feedback + inline training ----------------------------------------------------------
    def feedback(self, req: FeedbackRequest) -> dict:
        try:
            nxt = encode_observation(self.enc, req.next_observation)
        except EncodeError as e:
            raise ApiError(422, "bad_observation", str(e)) from e
        if ACTIONS[req.action_index] != req.executed_command:
            raise ApiError(422, "bad_action", "action_index does not match executed_command")
        key = (req.run_id, req.episode, req.tick)
        with self.fbl:
            with self.amu:
                if self.mode == "eval":
                    raise ApiError(409, "eval_mode", "feedback is not valid in eval mode")
                self._check_run(req.run_id, req.episode, advance=False)
                hit = self.fb_cache.get(key)
                if hit is not None:
                    self.counters["feedback_duplicates"] += 1
                    return {**hit, "duplicate": True}
                if req.tick <= self.fed_tick:
                    self.counters["feedback_stale"] += 1
                    raise ApiError(
                        409, "stale", f"tick {req.tick} <= last feedback {self.fed_tick}"
                    )
                pend = self.pending.pop(key, None)
                if req.deadline_missed:
                    self.counters["feedback_deadline_missed"] += 1
                if pend is None:
                    if not req.deadline_missed:
                        raise ApiError(409, "unknown_step", "no act recorded for this step key")
                    # the node never saw (or lost) the act: there is no observation to train on
                    self.fed_tick = req.tick
                    self.counters["feedback_no_pending"] += 1
                    out = FeedbackResponse(
                        accepted=False,
                        replay_size=min(self.learner.n, self.learner.capacity),
                        train_steps=self.learner.steps,
                        policy_version=self.learner.version,
                    ).model_dump()
                    self.fb_cache[key] = out
                    return out
                self.fed_tick = req.tick
                self.counters["feedbacks"] += 1
                self.fb_inflight = key
                paused = self.train_paused
            try:
                vec, chosen = pend
                if req.action_index != chosen:
                    self.counters["feedback_executed_differs"] += 1
                L, cfg = self.learner, self.cfg
                with self.mu:
                    # A2: train on what was EXECUTED. done = terminated only: time-limit
                    # truncation still bootstraps.
                    L.observe(vec, req.action_index, req.reward, nxt, req.terminated)
                    if paused or self.exchange_active:
                        self.counters["train_deferred"] += cfg.train_steps_per_feedback
                    else:
                        for _ in range(cfg.train_steps_per_feedback):
                            loss = L.train_step(cfg.batch, cfg.target_every)  # publishes snapshot
                            if loss is not None:
                                self.loss_ema = (
                                    loss
                                    if self.loss_ema is None
                                    else 0.98 * self.loss_ema + 0.02 * loss
                                )
                    self._drain_events_locked(req.tick)
                    out = FeedbackResponse(
                        accepted=True,
                        replay_size=min(L.n, L.capacity),
                        train_steps=L.steps,
                        policy_version=L.version,
                    ).model_dump()
                due = checkpoint_due(self.counters["feedbacks"])  # A17: every 200 feedback steps
            finally:
                with self.amu:
                    self.fb_inflight = None
                    self.acv.notify_all()
            with self.amu:
                self.fb_cache[key] = out
                while len(self.fb_cache) > cfg.act_cache:
                    self.fb_cache.popitem(last=False)
        if due:
            self._enqueue(Job("checkpoint", self._next_id("c")))
        return out

    def _drain_events_locked(self, tick: int, flush_window: bool = False) -> None:
        """Convert learner events to canonical LearningEvents (caller holds mu); clear the list."""
        L = self.learner
        for ev in L.events:
            t = ev["type"]
            if t == "local_update":
                if not self._lu_losses:
                    self._lu_first_version = ev["version"] - 1
                if math.isfinite(ev["loss"]):
                    self._lu_losses.append(ev["loss"])
                if len(self._lu_losses) >= self.cfg.update_every:
                    self._flush_window_locked(ev["step"], ev["version"], tick)
            elif t == "peer_offer":
                self._emit_decision(ev, tick)
            elif t == "rollback":
                self._emit(
                    LearningEvent, tick=tick, update_count=L.steps, loss=None,
                    previous_version=ev["pre_version"], new_version=ev["post_version"],
                    transfer="none", reason="rollback",
                )  # fmt: skip
        L.events.clear()
        if flush_window and self._lu_losses:
            self._flush_window_locked(L.steps, L.version, tick)

    def _flush_window_locked(self, step: int, version: int, tick: int) -> None:
        n = len(self._lu_losses)
        mean = sum(self._lu_losses) / n
        self._lu_losses = []
        self._emit(
            LearningEvent, tick=tick, update_count=step, loss=mean,
            previous_version=max(0, self._lu_first_version), new_version=version,
            transfer="none", reason=f"local_update window={n} mean_loss",
        )  # fmt: skip

    def _emit_decision(self, ev: dict, tick: int) -> None:
        ok = bool(ev["accepted"])
        self.counters["decisions_accepted" if ok else "decisions_rejected"] += 1
        if ev.get("reason") == "window_limit":
            self.counters["decisions_window_limit"] += 1
        src = f"source={ev.get('source')} v={ev.get('source_version')}"
        sha = f"sha256={ev['payload_sha256']}"
        if ok:
            reason = (
                f"{src} {sha} margin={ev['margin']:.4f} required={ev['margin_required']} "
                f"cur={ev['current_score']:.4f} cand={ev['candidate_score']:.4f}"
            )
            new_v = ev["new_version"]
        else:
            reason = f"{ev['reason']} ({src} {sha})"
            new_v = ev["local_version"]
        cand = ev.get("candidate_score")
        self._emit(
            LearningEvent, tick=tick, update_count=self.learner.steps, loss=None,
            previous_version=ev["pre_version"], new_version=new_v,
            transfer="accepted" if ok else "rejected", reason=reason,
            candidate_score=cand if cand is not None and math.isfinite(cand) else None,
            bytes=ev["bytes"], wall_seconds=float(ev.get("validation_seconds", 0.0)),
        )  # fmt: skip
        # A7: decision evidence that LearningEvent has no field for rides as MetricSamples
        phase = self._phase()
        self._emit(MetricSample, phase, tick=tick, metric="peer_validation_seconds",
                   value=float(ev.get("validation_seconds", 0.0)), unit="s")  # fmt: skip
        self._emit(MetricSample, phase, tick=tick, metric="peer_validation_evaluations",
                   value=float(ev.get("evaluations", 0)), unit="count")  # fmt: skip
        if math.isfinite(ev.get("margin", math.nan)):
            self._emit(MetricSample, phase, tick=tick, metric="peer_candidate_margin",
                       value=float(ev["margin"]), unit="score")  # fmt: skip

    # --- background worker: exchange windows and periodic checkpoints ------------------------
    def _next_id(self, kind: str) -> str:
        with self._xcv:
            self._jseq += 1
            return f"{self.cfg.node_id}-{self.boot_id}-{kind}{self._jseq}"

    def _enqueue(self, job: Job) -> Job:
        """Queue background work. Never blocks on the work itself and never runs it inline."""
        with self._xcv:
            if job.kind == "checkpoint" and any(j.kind == "checkpoint" for j in self._jobs):
                job.done.set()  # one queued checkpoint already covers this request
                return job
            if len(self._jobs) >= MAX_QUEUED_WINDOWS:
                for old in self._jobs:  # bounded: drop the oldest non-final job, counted
                    if not old.final:
                        self._jobs.remove(old)
                        old.cancel.set()
                        old.result = {"cancelled": True, "dropped": True}
                        old.done.set()
                        self.counters["windows_dropped"] += 1
                        break
            self._jobs.append(job)
            if self._xthread is None:
                self._xthread = threading.Thread(target=self._xloop, name="exchange", daemon=True)
                self._xthread.start()
            self._xcv.notify_all()
        return job

    def _xloop(self) -> None:
        while True:
            with self._xcv:
                while not self._jobs and not self._closing:
                    self._xcv.wait()
                if self._closing:
                    return
                job = self._jobs.popleft()
                self._cur = job
            try:
                if job.kind == "checkpoint":
                    job.result = self.checkpoint()
                else:
                    job.result = self._run_window(job)
            except Exception as e:  # keep the worker alive; the failure is visible in status
                job.result = {"error": repr(e), "tick": job.tick}
            finally:
                with self._xcv:
                    self._cur = None
                    if job.kind == "window":
                        self.last_window_id = job.id
                        self.last_exchange = job.result
                        self.results[job.id] = job.result or {}
                        while len(self.results) > 64:
                            self.results.popitem(last=False)
                    job.done.set()
                    self._xcv.notify_all()

    @property
    def window_state(self) -> str:
        with self._xcv:
            busy = (self._cur is not None and self._cur.kind == "window") or any(
                j.kind == "window" for j in self._jobs
            )
        return "running" if busy else "idle"

    @property
    def exchange_running(self) -> bool:
        return self.window_state == "running"

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until the worker has nothing queued or running (tests, shutdown, reset)."""
        with self._xcv:
            return self._xcv.wait_for(lambda: self._cur is None and not self._jobs, timeout)

    def wait_window(self, window_id: str, timeout: float = 30.0) -> dict | None:
        """Block until the named window finished; returns its result (None on timeout)."""
        with self._xcv:
            ok = self._xcv.wait_for(lambda: window_id in self.results, timeout)
            return self.results[window_id] if ok else None

    def _settle_windows(self) -> None:
        """A4: let a running window finish for up to ``window_cancel_wait``, then cancel it."""
        if self.wait_idle(self.cfg.window_cancel_wait):
            return
        with self._xcv:
            victims = list(self._jobs) + ([self._cur] if self._cur is not None else [])
            for j in victims:
                j.cancel.set()
        for j in victims:
            if j.kind == "window":
                self.counters["windows_cancelled"] += 1
                self._metric("window_cancelled", 1.0, "count", "other")
        self.wait_idle(max(1.0, 2 * self.cfg.peer_timeout))  # cooperative: next cancel point

    def request_episode_end(self, c) -> tuple[int, dict]:
        """A4: 202 {window_id}; the final window and the end-of-episode checkpoint run in the
        background. Idempotent per (run, episode)."""
        self._check_command_run(c.run_id)
        with self.amu:
            if self.run_id != c.run_id or c.episode != self.episode:
                raise ApiError(
                    409, "wrong_episode", f"node is in episode {self.episode} of {self.run_id}"
                )
            wid = self._ends.get((c.run_id, c.episode))
            if wid is not None:
                return 202, {"window_id": wid, "duplicate": True}
            wid = f"{self.cfg.node_id}-{self.boot_id}-e{c.episode}"
            self._ends[(c.run_id, c.episode)] = wid
            while len(self._ends) > 64:
                self._ends.popitem(last=False)
            skip = self.mode == "eval"  # eval freezes: no exchange, the checkpoint still happens
        self._enqueue(Job("window", wid, c.tick, c.episode, final=True, skip_exchange=skip))
        return 202, {"window_id": wid}

    def _run_window(self, w: Job) -> dict:
        t0 = time.perf_counter()
        try:
            res = self._exchange(w)
        except WindowCancelled:
            res = {"window_id": w.id, "tick": w.tick, "final": w.final, "cancelled": True}
        res["seconds"] = time.perf_counter() - t0
        return res

    def _check_cancel(self, w: Job) -> None:
        if w.cancel.is_set():
            raise WindowCancelled

    def _send_offer(self, peer: str, url: str, env: Envelope, out: dict) -> None:
        out[peer] = post(
            url, env, self.cfg.peer_timeout, self.cfg.peer_retries, self.cfg.peer_token
        )

    def _count_send(self, peer: str, status: int, version: int, digest: str, res: dict) -> None:
        if status in (200, 202):
            self.counters["offers_sent"] += 1
            self.last_sent[peer] = (version, digest)
            res["sent"].append(peer)
        elif status == 0:
            self.counters["offers_unreachable"] += 1
            res["unreachable"].append(peer)
        else:
            self.counters["offers_refused_by_peer"] += 1
            res["refused"].append([peer, status])

    def _exchange(self, w: Job) -> dict:
        """One exchange window (A1). Fault decisions use the window's tick (the node's own tick
        counter when it was triggered), so a window inside a cut sees the cut."""
        self._check_cancel(w)
        tick = w.tick
        sched = self.schedule
        res: dict = {"window_id": w.id, "tick": tick, "episode": w.episode, "final": w.final,
                     "sent": [], "cut": [], "unchanged": [], "unreachable": [], "refused": [],
                     "no_url": [], "decisions": [], "validation_seconds": 0.0,
                     "evaluations": 0}  # fmt: skip
        res["train_steps"] = self.learner.steps  # at window start: shows training goes on
        if not w.skip_exchange:
            self.counters["exchanges"] += 1
            self._offer_phase(w, sched, res)
            self._check_cancel(w)
            cands = self._collect(sched, tick)
            if cands:
                res["decisions"] = self._decide(cands, w, res)
            self._flush_window(tick)
        else:
            res["skipped"] = "eval_mode"
        if w.final:  # A17: a generation at each episode_end
            res["checkpoint"] = self.checkpoint()["generation"]
        return res

    def _offer_phase(self, w: Job, sched: Schedule, res: dict) -> None:
        cfg, me, tick = self.cfg, self.cfg.node_id, w.tick
        with self.mu:
            payload, version = encode(self.learner), self.learner.version
        digest = hashlib.sha256(payload).hexdigest()
        threads, statuses = [], {}
        for p in sorted(cfg.node_ids):
            if p == me:
                continue
            if sched.cut(me, p, tick):
                self.counters["offers_cut"] += 1
                res["cut"].append(p)
            elif p not in self.peer_urls:
                res["no_url"].append(p)
            elif self.last_sent.get(p) == (version, digest):
                self.counters["offers_unchanged"] += 1
                res["unchanged"].append(p)
            else:
                env = Envelope.make(me, p, self.peer_seq.next(), payload)  # persisted, monotonic
                th = threading.Thread(
                    target=self._send_offer, args=(p, self.peer_urls[p], env, statuses),
                    daemon=True,
                )  # fmt: skip
                th.start()
                threads.append(th)
        for th in threads:
            while th.is_alive():
                th.join(0.05)
                self._check_cancel(w)  # a cancelled window abandons a stuck send (daemon thread)
        for p in sorted(statuses):
            self._count_send(p, statuses[p], version, digest, res)

    def _collect(self, sched: Schedule, tick: int) -> list[Envelope]:
        """Drain received candidates in ARRIVAL order: cut links dropped, latest per sender only,
        dedupe by (sender, payload sha256)."""
        me = self.cfg.node_id
        arrived: list[Envelope] = []
        while self.peer is not None and (env := self.peer.receive()) is not None:
            self.counters["offers_received"] += 1
            if sched.cut(env.src, me, tick):
                self.counters["received_cut"] += 1
                continue
            arrived.append(env)
        last = {env.src: i for i, env in enumerate(arrived)}
        cands = []
        for i, env in enumerate(arrived):
            if last[env.src] != i:
                self.counters["received_superseded"] += 1
                continue
            k = f"{env.src}|{env.digest}"
            if k in self.dedupe:
                self.counters["received_duplicate"] += 1
                continue
            self.dedupe[k] = None
            while len(self.dedupe) > 256:
                self.dedupe.popitem(last=False)
            cands.append(env)
        return cands

    def _decide(self, cands: list[Envelope], w: Job, res: dict) -> list[dict]:
        """Validate candidates in arrival order; at most one acceptance per window. Everything
        after the first acceptance is rejected as ``window_limit`` without validation cost."""
        cfg, L = self.cfg, self.learner
        alpha = cfg.mix_alpha if cfg.mode == "mixing" else None
        window = OfferWindow()
        with self.mu:
            self.exchange_active = True  # defer optimizer steps: judged params == replaced params
            own = L.params_numpy()
        decisions: list[dict] = []
        try:
            cache: dict[str, float] = {}
            spent = {"seconds": 0.0}

            def timed(p) -> float:
                t = time.perf_counter()
                s = self.validator.evaluate(p, w.cancel)
                spent["seconds"] += time.perf_counter() - t
                cache[params_digest(p)] = s
                return s

            def eval_fn(p):
                s = cache.get(params_digest(p))
                return s if s is not None else timed(p)

            for env in cands:
                self._check_cancel(w)
                seconds0, eps0 = spent["seconds"], self.validator.episodes_run
                scorable = L.mode != "information_only" and not window.accepted
                if scorable:
                    try:
                        _, cand = decode(env.payload, L)
                        if alpha is not None:
                            cand = {k: ((1 - alpha) * own[k] + alpha * cand[k]).astype(np.float32)
                                    for k in KEYS}  # fmt: skip
                        if params_digest(own) not in cache:
                            timed(own)  # current policy: once per window
                        eval_fn(cand)
                    except PeerError:
                        pass  # offer() below records the named reject reason
                self._check_cancel(w)
                with self.mu:
                    self._check_cancel(w)  # never apply a candidate after the window was cancelled
                    ev = offer(L, env.payload, eval_fn, cfg.peer_margin, alpha, sender=env.src,
                               window=window)  # fmt: skip
                    ev.setdefault("source", env.src)
                    ev.setdefault("source_version", env.seq)
                    ev["validation_seconds"] = spent["seconds"] - seconds0
                    ev["evaluations"] = self.validator.episodes_run - eps0
                    res["validation_seconds"] += ev["validation_seconds"]
                    res["evaluations"] += ev["evaluations"]
                    decisions.append({k: v for k, v in ev.items() if k != "type"})
                    self._drain_events_locked(w.tick)
        finally:
            with self.mu:
                self.exchange_active = False
        return decisions

    def _flush_window(self, tick: int) -> None:
        with self.mu:
            self._drain_events_locked(tick, flush_window=True)
        L, c = self.learner, self.counters
        phase = self._phase()
        lat = [x * 1000 for x in list(self.act_lat)]
        for name, val, unit in (
            ("train_steps", L.steps, "count"),
            ("replay_size", min(L.n, L.capacity), "count"),
            ("policy_version", L.version, "count"),
            ("epsilon", self.epsilon(), "ratio"),
            ("loss_ema", self.loss_ema if self.loss_ema is not None else math.nan, "loss"),
            ("rss_bytes", rss_bytes(), "bytes"),
            ("rss_peak_bytes", rss_peak_bytes(), "bytes"),
            ("act_latency_p99_ms", _pct(lat, 99), "ms"),
            ("telemetry_backlog", self.spool.backlog, "count"),
            ("telemetry_dropped", self.spool.dropped, "count"),
            ("peer_offers_sent", c["offers_sent"], "count"),
            ("peer_offers_cut", c["offers_cut"], "count"),
            ("peer_decisions_accepted", c["decisions_accepted"], "count"),
            ("peer_decisions_rejected", c["decisions_rejected"], "count"),
        ):
            self._metric(name, val, unit, phase)

    # --- checkpoints (A17) -------------------------------------------------------------------
    def _node_state(self) -> dict:
        """Everything the learner library does not own (caller holds mu and amu)."""
        pend = list(self.pending.items())[-MAX_PERSISTED_PENDING:]
        return {
            "boot_id": self.boot_id, "run_id": self.run_id, "episode": self.episode,
            "tick": self.tick, "fed_tick": self.fed_tick, "mode": self.mode,
            "train_paused": self.train_paused, "act_count": self.act_count,
            "loss_ema": self.loss_ema, "counters": dict(self.counters),
            "schedule": self.schedule.as_json(),
            "last_sent": {p: list(v) for p, v in self.last_sent.items()},
            "dedupe": list(self.dedupe),
            "pending": [[k[0], k[1], k[2], v[0].tolist(), v[1]] for k, v in pend],
            "sequence_ceiling": self.seq.ceiling, "peer_seq_ceiling": self.peer_seq.ceiling,
            "config_hash": self.config_hash, "configured_run": self.configured_run,
            "spool": self.spool.state(),
        }  # fmt: skip

    def checkpoint(self) -> dict:
        with self.ckl:
            with self.mu:
                with self.amu:
                    state, act_rng = self._node_state(), self.act_rng.bit_generator.state
                self.spool.sync()
                manifest = ckpt.save(self.learner, self.ckpt_dir, state, act_rng, self.ckpt_io)
            self.checkpoint_generation = manifest["generation"]
            self.counters["checkpoints"] += 1
        return {"ok": True, "generation": manifest["generation"]}

    def _restore(self) -> None:
        if not self.ckpt_dir.exists():
            self._boot_event()
            return
        try:
            info = ckpt.load(self.learner, self.ckpt_dir)
        except CheckpointError as e:
            if "no loadable" in str(e):  # nothing complete on disk: start fresh, visibly
                self.restore_info = {"restored": False, "error": str(e)}
                self._boot_event()
                return
            raise  # identity mismatch (changed hyperparameters): operator decision
        n = info["node"]
        self.checkpoint_generation = info["generation"]
        self.run_id, self.episode = n.get("run_id"), int(n.get("episode", -1))
        self.tick, self.fed_tick = int(n.get("tick", -1)), int(n.get("fed_tick", -1))
        self.mode = n.get("mode", "train")
        self.train_paused = bool(n.get("train_paused", False))
        self.act_count = int(n.get("act_count", 0))
        self.loss_ema = n.get("loss_ema")
        for k, v in n.get("counters", {}).items():
            if k in self.counters:
                self.counters[k] = int(v)
        self.schedule = Schedule.from_json(n.get("schedule", []))
        self.last_sent = {p: (int(v[0]), v[1]) for p, v in n.get("last_sent", {}).items()}
        self.act_rng.bit_generator.state = info["act_rng"]
        for k in n.get("dedupe", []):
            self.dedupe[k] = None
        for run, ep, tick, vec, a in n.get("pending", []):  # A3: pending (obs, action) per key
            self.pending[(run, int(ep), int(tick))] = (np.asarray(vec, np.float32), int(a))
        self.restore_info = {
            "restored": True, "generation": info["generation"],
            "prev_boot_id": n.get("boot_id"), "train_steps": self.learner.steps,
            "pending": len(self.pending),
        }  # fmt: skip
        self._boot_event()

    def _boot_event(self) -> None:
        self._metric("node_boot", float(self.checkpoint_generation), "generation", "other")

    # --- status ------------------------------------------------------------------------------
    def status(self) -> dict:
        L = self.learner
        lat = [x * 1000 for x in list(self.act_lat)]
        with self.amu:
            peers = {p: ("cut" if self.link_cut(p) else "up") for p in self.cfg.node_ids
                     if p != self.cfg.node_id}  # fmt: skip
            st = {
                "ready": self.ready, "node_id": self.cfg.node_id, "boot_id": self.boot_id,
                "run_id": self.run_id, "episode": self.episode, "tick": self.tick,
                "mode": self.mode, "train_paused": self.train_paused, "backend": L.backend,
                "torch_version": L.runtime["torch_version"], "policy_version": L.version,
                "policy_sha256": params_digest(L._published), "train_steps": L.steps,
                "replay_size": min(L.n, L.capacity), "loss_ema": self.loss_ema,
                "epsilon": self.epsilon(), "checkpoint_generation": self.checkpoint_generation,
                "peers": peers, "rss_bytes": rss_bytes(), "rss_peak_bytes": rss_peak_bytes(),
                "sequence_ceiling": self.seq.ceiling,
                "telemetry_backlog": self.spool.backlog, "dropped_events": self.spool.dropped,
                "telemetry_dropped": self.spool.dropped,
                "window": self.window_state, "last_window_id": self.last_window_id,
                "exchange_every_ticks": self.cfg.exchange_every_ticks,
                "config_hash": self.config_hash, "configured_run": self.configured_run,
                "exchange_running": self.exchange_running,
                "schedule_sha256": self.schedule.sha256, "encoder_id": self.enc.id,
                "counters": dict(self.counters), "restore": self.restore_info,
                "validation_evaluations": self.validator.episodes_run,
                "act_latency_ms": {"n": len(lat), "p50": _pct(lat, 50), "p99": _pct(lat, 99),
                                   "max": max(lat, default=0.0)},
            }  # fmt: skip
        return st

    def close(self) -> None:
        with self._xcv:
            self._closing = True
            for j in [*self._jobs, *([self._cur] if self._cur is not None else [])]:
                j.cancel.set()
            self._xcv.notify_all()
        if self._xthread is not None:
            self._xthread.join(timeout=5)
        self.spool.close()

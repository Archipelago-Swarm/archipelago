"""Node core: owns a TorchLearner and everything around it (live-runtime.md sections 3, 5, 7, 8).

Concurrency design (justified, and tested with a stalled peer and a stalled sink):

* ``act`` takes only ``amu`` (a few microseconds: idempotency map, exploration RNG, sequence) and
  reads the immutable published inference snapshot. It never takes ``mu`` and never does I/O, so it
  cannot wait for an optimizer step, a checkpoint, a peer call or telemetry.
* ``feedback`` trains INLINE under ``mu`` with a bounded number of optimizer steps per call
  (``TRAIN_STEPS_PER_FEEDBACK``, default 1, about 1 ms). Inline keeps step counts exactly
  reproducible (N feedbacks -> N steps) and needs no queue; acting is unaffected because it only
  reads the snapshot. A dedicated training thread would only add nondeterminism here.
* Everything slow runs on other threads: peer exchange (including validation in the private
  world) on one worker thread, telemetry shipping on the shipper thread. While a validation is in
  progress optimizer steps are deferred (transitions are still stored) so the parameters being
  judged are the parameters being replaced.
* Lock order: fbl -> mu -> amu. ``act`` and ``reset`` only ever take amu.
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime

import numpy as np
from archipelago_contracts import SCHEMA_VERSION
from archipelago_contracts.models import Action, LearningEvent, MetricSample
from archipelago_learning import PeerError, TorchLearner, decode, encode, offer
from archipelago_learning.checkpoint import CheckpointError
from archipelago_peer import post
from archipelago_transport import Envelope

from .config import Config
from .encoder import (
    ACTION_SPACE_VERSION,
    ACTIONS,
    ENCODER_ID,
    ENCODER_SHA256,
    EncodeError,
    encode_observation,
)
from .peering import Schedule
from .protocol import ActRequest, ActResponse, FeedbackRequest, FeedbackResponse
from .telemetry import Spool
from .validation import ValidationWorld, params_digest

KEYS = ("w1", "b1", "w2", "b2")


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str = ""):
        super().__init__(f"{status} {code} {detail}")
        self.status, self.code, self.detail = status, code, detail


def rss_bytes() -> int:
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


class Node:
    def __init__(self, cfg: Config, ckpt_io=None):
        self.cfg = cfg
        self.boot_id = uuid.uuid4().hex[:8]
        self.ckpt_io = ckpt_io  # fault-injection seam for the checkpoint writer (tests)
        self.ckpt_dir = cfg.checkpoint_dir / "ckpt"
        self.learner = TorchLearner(
            cfg.node_id,
            cfg.obs_dim,
            len(ACTIONS),
            hidden=cfg.hidden,
            seed=cfg.learner_seed,
            lr=cfg.lr,
            gamma=cfg.gamma,
            capacity=cfg.capacity,
            mode=cfg.mode,
            encoder=ENCODER_ID,
            threads=cfg.torch_threads,
        )
        assert self.learner.encoder_sha256 == ENCODER_SHA256
        self.act_rng = np.random.default_rng([cfg.learner_seed, 7919])
        self.validator = ValidationWorld(cfg)
        self.spool = Spool(
            cfg.checkpoint_dir / "telemetry", cfg.spool_max_records, cfg.spool_segment_records
        )
        self.mu, self.amu, self.fbl = threading.Lock(), threading.Lock(), threading.Lock()
        self.ckl = threading.Lock()
        # episode / step state (guarded by amu)
        self.run_id: str | None = None
        self.episode = -1
        self.tick = -1
        self.fed_tick = -1
        self.mode = "train"
        self.train_paused = False
        self.act_count = 0
        self.sequence = 0
        self.schedule = Schedule()
        self.act_cache: OrderedDict[tuple, dict] = OrderedDict()
        self.pending: OrderedDict[tuple, tuple[np.ndarray, int]] = OrderedDict()
        self.fb_cache: OrderedDict[tuple, dict] = OrderedDict()
        self.counters: dict[str, int] = {
            k: 0
            for k in (
                "acts", "act_duplicates", "act_stale", "feedbacks", "feedback_duplicates",
                "feedback_stale", "train_deferred", "offers_sent", "offers_cut",
                "offers_unchanged", "offers_unreachable", "offers_refused_by_peer",
                "offers_received", "received_cut", "received_superseded", "received_duplicate",
                "decisions_accepted", "decisions_rejected", "exchanges", "exchanges_coalesced",
                "checkpoints", "spool_errors", "implicit_episode_advances",
            )
        }  # fmt: skip
        self.loss_ema: float | None = None
        self.checkpoint_generation = 0
        self.restore_info: dict = {"restored": False}
        # peer / exchange state
        self.peer_urls: dict[str, str] = dict(cfg.peer_urls)
        self.peer = None  # GatedPeerServer, attached by the runtime
        self.ready = False
        self.exchange_active = False
        self.exchange_running = False
        self.last_exchange: dict | None = None
        self.dedupe: OrderedDict[str, None] = OrderedDict()
        self.last_sent: dict[str, tuple[int, str]] = {}
        self._xcv = threading.Condition()
        self._xpending: tuple[int, threading.Event] | None = None
        self._xthread: threading.Thread | None = None
        self._closing = False
        self.stop_event = threading.Event()
        # local-update telemetry aggregation (guarded by mu)
        self._lu_losses: list[float] = []
        self._lu_first_version = 0
        self._restore()

    # --- helpers ---------------------------------------------------------------------------
    @property
    def eff_tick(self) -> int:
        return max(self.tick, 0)

    def link_cut(self, other: str) -> bool:
        return self.schedule.cut(self.cfg.node_id, other, self.eff_tick)

    def _alloc_locked(self) -> tuple[int, str]:
        seq = self.sequence
        self.sequence += 1
        return seq, f"{self.cfg.node_id}-{self.boot_id}-{seq}"

    def _phase(self) -> str:
        if self.mode == "eval":
            return "eval"
        if any(self.link_cut(p) for p in self.cfg.node_ids if p != self.cfg.node_id):
            return "partition"
        return "train"

    def _emit(self, cls, phase: str | None = None, sim_tick: int | None = None, **fields) -> None:
        """Build a canonical record and append it to the durable spool (no network, no raise)."""
        with self.amu:
            seq, eid = self._alloc_locked()
            run_id = self.run_id or "run-none"
            tick = self.eff_tick if sim_tick is None else sim_tick
            phase = phase or self._phase()
        if cls is MetricSample:
            fields["phase"] = phase
        rec = cls(
            schema_version=SCHEMA_VERSION,
            event_id=eid,
            run_id=run_id,
            source_node_id=self.cfg.node_id,
            sim_tick=max(0, tick),
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

    # --- episode control -------------------------------------------------------------------
    def _new_episode(self, run_id: str, episode: int, mode: str | None = None) -> None:
        self.run_id, self.episode, self.tick, self.fed_tick = run_id, episode, -1, -1
        if mode is not None:
            self.mode = mode
        self.act_cache.clear()
        self.pending.clear()
        self.fb_cache.clear()

    def _check_run(self, run_id: str, episode: int, advance: bool) -> None:
        """Caller holds amu. Raises 409 for a foreign run or an episode in the past."""
        if self.run_id is None:
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

    def control_reset(self, c) -> dict:
        with self.amu:
            if self.run_id == c.run_id:
                if c.episode < self.episode:
                    raise ApiError(409, "stale", f"episode {c.episode} < {self.episode}")
                if c.episode == self.episode and c.mode == self.mode:
                    dup = True  # retry of the same reset: keep caches, idempotent
                else:
                    dup = False
            else:
                dup = False
            if not dup:
                self._new_episode(c.run_id, c.episode, c.mode)
            if c.fault_schedule is not None:
                self.schedule = Schedule(c.fault_schedule)
        return {"ok": True, "duplicate": dup, "status": self.status()}

    def control_set_schedule(self, c) -> dict:
        with self.amu:
            self.schedule = Schedule(c.fault_schedule)
        return {"ok": True, "status": self.status()}

    def control_pause(self, paused: bool) -> dict:
        with self.amu:
            self.train_paused = paused
        return {"ok": True, "status": self.status()}

    # --- acting ----------------------------------------------------------------------------
    def epsilon(self) -> float:
        if self.mode == "eval":
            return 0.0
        c = self.cfg
        frac = min(1.0, self.act_count / c.eps_decay_acts)
        return c.eps_start + (c.eps_end - c.eps_start) * frac

    def act(self, req: ActRequest) -> dict:
        try:
            vec = encode_observation(
                req.observation, self.cfg.world_size, self.cfg.world_sense_radius
            )
        except EncodeError as e:
            raise ApiError(422, "bad_observation", str(e)) from e
        key = (req.run_id, req.episode, req.tick)
        with self.amu:
            self._check_run(req.run_id, req.episode, advance=True)
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
            action = Action(
                schema_version=SCHEMA_VERSION,
                event_id=eid,
                run_id=req.run_id,
                source_node_id=self.cfg.node_id,
                sim_tick=req.tick,
                emitted_at_utc=datetime.now(UTC),
                sequence=seq,
                action_space_version=ACTION_SPACE_VERSION,
                command=ACTIONS[a],
                policy_version=self.learner.version,
            )
            out = ActResponse(
                node_id=self.cfg.node_id,
                tick=req.tick,
                action=action,
                policy_version=self.learner.version,
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
            return out

    # --- feedback + inline training ----------------------------------------------------------
    def feedback(self, req: FeedbackRequest) -> dict:
        try:
            nxt = encode_observation(
                req.next_observation, self.cfg.world_size, self.cfg.world_sense_radius
            )
        except EncodeError as e:
            raise ApiError(422, "bad_observation", str(e)) from e
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
                if pend is None:
                    raise ApiError(409, "unknown_step", "no act recorded for this step key")
                self.fed_tick = req.tick
                self.counters["feedbacks"] += 1
                paused = self.train_paused
            vec, a = pend
            L, cfg = self.learner, self.cfg
            with self.mu:
                # done = terminated only: time-limit truncation still bootstraps
                L.observe(vec, a, req.reward, nxt, req.terminated)
                if paused or self.exchange_active:
                    deferred = cfg.train_steps_per_feedback
                    self.counters["train_deferred"] += deferred
                else:
                    for _ in range(cfg.train_steps_per_feedback):
                        loss = L.train_step(cfg.batch, cfg.target_every)
                        if loss is not None:
                            self.loss_ema = (
                                loss
                                if self.loss_ema is None
                                else 0.98 * self.loss_ema + 0.02 * loss
                            )
                self._drain_events_locked(req.tick)
                out = FeedbackResponse(
                    accepted=True, replay_size=min(L.n, L.capacity), train_steps=L.steps
                ).model_dump()
            with self.amu:
                self.fb_cache[key] = out
                while len(self.fb_cache) > cfg.act_cache:
                    self.fb_cache.popitem(last=False)
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
                    LearningEvent, sim_tick=tick, update_count=L.steps, loss=None,
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
            LearningEvent, sim_tick=tick, update_count=step, loss=mean,
            previous_version=max(0, self._lu_first_version), new_version=version,
            transfer="none", reason=f"local_update window={n} mean_loss",
        )  # fmt: skip

    def _emit_decision(self, ev: dict, tick: int) -> None:
        ok = bool(ev["accepted"])
        self.counters["decisions_accepted" if ok else "decisions_rejected"] += 1
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
            LearningEvent, sim_tick=tick, update_count=self.learner.steps, loss=None,
            previous_version=ev["pre_version"], new_version=new_v,
            transfer="accepted" if ok else "rejected", reason=reason,
            candidate_score=cand if cand is not None and math.isfinite(cand) else None,
            bytes=ev["bytes"], wall_seconds=float(ev.get("validation_seconds", 0.0)),
        )  # fmt: skip

    # --- peer exchange -----------------------------------------------------------------------
    def request_episode_end(self, tick: int | None, wait: bool) -> dict:
        with self.amu:
            if self.mode == "eval":
                return {"ok": True, "skipped": "eval_mode"}
            t = self.eff_tick if tick is None else tick
        done = threading.Event()
        with self._xcv:
            if self._xthread is None:
                self._xthread = threading.Thread(target=self._xloop, name="exchange", daemon=True)
                self._xthread.start()
            if self._xpending is not None:
                self.counters["exchanges_coalesced"] += 1
                self._xpending[1].set()  # superseded; its waiter just returns
            self._xpending = (t, done)
            self._xcv.notify()
        if wait:
            done.wait(self.cfg.exchange_wait_max)
        return {"ok": True, "queued": True, "waited": wait, "done": done.is_set(),
                "last_exchange": self.last_exchange}  # fmt: skip

    def _xloop(self) -> None:
        while True:
            with self._xcv:
                while self._xpending is None and not self._closing:
                    self._xcv.wait()
                if self._closing:
                    return
                tick, done = self._xpending  # type: ignore[misc]
                self._xpending = None
                self.exchange_running = True
            try:
                self.last_exchange = self._exchange(tick)
            except Exception as e:  # keep the worker alive; the failure is visible in status
                self.last_exchange = {"error": repr(e), "tick": tick}
            finally:
                self.exchange_running = False
                done.set()

    def _send_offer(self, peer: str, url: str, payload: bytes, version: int, out: dict) -> None:
        out[peer] = post(
            url, Envelope.make(self.cfg.node_id, peer, version, payload),
            self.cfg.peer_timeout, self.cfg.peer_retries,
        )  # fmt: skip

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

    def _exchange(self, tick: int) -> dict:
        cfg, me = self.cfg, self.cfg.node_id
        t0 = time.perf_counter()
        sched = self.schedule
        res: dict = {"tick": tick, "sent": [], "cut": [], "unchanged": [], "unreachable": [],
                     "refused": [], "no_url": [], "decisions": []}  # fmt: skip
        self.counters["exchanges"] += 1
        # (1) one candidate offer (latest published policy) to each allowed neighbour, in parallel
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
                th = threading.Thread(
                    target=self._send_offer,
                    args=(p, self.peer_urls[p], payload, version, statuses),
                    daemon=True,
                )
                th.start()
                threads.append(th)
        for th in threads:
            th.join()
        for p in sorted(statuses):
            self._count_send(p, statuses[p], version, digest, res)
        # (2) drain received candidates: latest per sender, dedupe, re-check the schedule
        latest: dict[str, Envelope] = {}
        while self.peer is not None and (env := self.peer.receive()) is not None:
            self.counters["offers_received"] += 1
            if sched.cut(env.src, me, tick):
                self.counters["received_cut"] += 1
                continue
            prev = latest.get(env.src)
            if prev is not None:
                self.counters["received_superseded"] += 1
            if prev is None or env.seq >= prev.seq:
                latest[env.src] = env
        cands = []
        for src in sorted(latest):
            env = latest[src]
            k = f"{src}|{env.seq}|{env.digest}"
            if k in self.dedupe:
                self.counters["received_duplicate"] += 1
                continue
            self.dedupe[k] = None
            while len(self.dedupe) > 256:
                self.dedupe.popitem(last=False)
            cands.append(env)
        if cands:
            res["decisions"] = self._validate_and_apply(cands, tick)
        self._flush_window(tick)
        res["checkpoint"] = self.checkpoint()["generation"]
        res["seconds"] = time.perf_counter() - t0
        return res

    def _validate_and_apply(self, cands: list[Envelope], tick: int) -> list[dict]:
        cfg, L = self.cfg, self.learner
        alpha = cfg.mix_alpha if cfg.mode == "mixing" else None
        n_eval = len(self.validator.seeds)
        with self.mu:
            self.exchange_active = True  # defer optimizer steps: judged params == replaced params
            own = L.params_numpy()
        decisions: list[dict] = []
        try:
            cache: dict[str, float] = {}

            def timed(p):
                t = time.perf_counter()
                s = self.validator.evaluate(p)
                cache[params_digest(p)] = s
                return s, time.perf_counter() - t

            rows = []
            if L.mode != "information_only":
                _, cur_secs = timed(own)
            else:
                cur_secs = 0.0
            for env in cands:
                score, secs = None, 0.0
                if L.mode != "information_only":
                    try:
                        _, cand = decode(env.payload, L)
                        if alpha is not None:
                            cand = {k: ((1 - alpha) * own[k] + alpha * cand[k]).astype(np.float32)
                                    for k in KEYS}  # fmt: skip
                        score, secs = timed(cand)
                    except PeerError:
                        score = None  # offer() below records the named reject reason
                rows.append((env, score, secs))
            rows.sort(key=lambda r: (r[1] is None, -(r[1] or 0.0), r[0].src))

            def eval_fn(p):
                s = cache.get(params_digest(p))
                return s if s is not None else self.validator.evaluate(p)

            accepted = False
            for env, score, secs in rows:
                with self.mu:
                    if accepted:
                        ev = {
                            "type": "peer_offer", "accepted": False, "source": env.src,
                            "source_version": env.seq, "payload_sha256": env.digest,
                            "local_version": L.version, "pre_version": L.version,
                            "bytes": len(env.payload), "margin_required": cfg.peer_margin,
                            "reason": "window limit: one accepted candidate per exchange window",
                            "candidate_score": score,
                        }  # fmt: skip
                        L.events.append(ev)
                    else:
                        ev = offer(L, env.payload, eval_fn, cfg.peer_margin, alpha, sender=env.src)
                        accepted = bool(ev["accepted"])
                    scored = score is not None
                    ev["validation_seconds"] = (cur_secs + secs) if scored else 0.0
                    ev["evaluations"] = 2 * n_eval if scored else 0
                    decisions.append({k: v for k, v in ev.items() if k != "type"})
                    self._drain_events_locked(tick)
        finally:
            with self.mu:
                self.exchange_active = False
        return decisions

    def _flush_window(self, tick: int) -> None:
        with self.mu:
            self._drain_events_locked(tick, flush_window=True)
        L, c = self.learner, self.counters
        phase = self._phase()
        for name, val, unit in (
            ("train_steps", L.steps, "count"),
            ("replay_size", min(L.n, L.capacity), "count"),
            ("policy_version", L.version, "count"),
            ("epsilon", self.epsilon(), "ratio"),
            ("loss_ema", self.loss_ema if self.loss_ema is not None else math.nan, "loss"),
            ("rss_bytes", rss_bytes(), "bytes"),
            ("telemetry_backlog", self.spool.backlog, "count"),
            ("telemetry_dropped", self.spool.dropped, "count"),
            ("peer_offers_sent", c["offers_sent"], "count"),
            ("peer_offers_cut", c["offers_cut"], "count"),
            ("peer_decisions_accepted", c["decisions_accepted"], "count"),
            ("peer_decisions_rejected", c["decisions_rejected"], "count"),
        ):
            self._metric(name, val, unit, phase)

    # --- checkpoints -------------------------------------------------------------------------
    def _extra(self) -> dict:
        return {
            "node": {
                "sequence": self.sequence, "boot_id": self.boot_id, "run_id": self.run_id,
                "episode": self.episode, "mode": self.mode, "train_paused": self.train_paused,
                "act_count": self.act_count, "loss_ema": self.loss_ema,
                "counters": dict(self.counters), "schedule": self.schedule.as_json(),
                "last_sent": {p: list(v) for p, v in self.last_sent.items()},
                "act_rng": self.act_rng.bit_generator.state,
            },
            "peer": {"dedupe": list(self.dedupe)},
            "telemetry": self.spool.state(),
        }  # fmt: skip

    def checkpoint(self) -> dict:
        with self.ckl:
            with self.mu:
                with self.amu:
                    extra = self._extra()
                self.spool.sync()
                manifest = self.learner.save_generation(self.ckpt_dir, extra, self.ckpt_io)
            self.checkpoint_generation = manifest["generation"]
            self.counters["checkpoints"] += 1
        return {"ok": True, "generation": manifest["generation"]}

    def _restore(self) -> None:
        # event sequence must continue past anything already spooled, even past the checkpoint
        self.sequence = self.spool.max_sequence + 1
        if not self.ckpt_dir.exists():
            self._boot_event()
            return
        try:
            info = self.learner.load_latest(self.ckpt_dir)
        except CheckpointError as e:
            if "no loadable" in str(e):  # nothing complete on disk: start fresh, visibly
                self.restore_info = {"restored": False, "error": str(e)}
                self._boot_event()
                return
            raise  # identity mismatch (changed hyperparameters): operator decision
        ex = info["extra"]
        n = ex.get("node", {})
        self.checkpoint_generation = info["generation"]
        self.sequence = max(self.sequence, int(n.get("sequence", 0)))
        self.run_id, self.episode = n.get("run_id"), int(n.get("episode", -1))
        self.mode = n.get("mode", "train")
        self.train_paused = bool(n.get("train_paused", False))
        self.act_count = int(n.get("act_count", 0))
        self.loss_ema = n.get("loss_ema")
        for k, v in n.get("counters", {}).items():
            if k in self.counters:
                self.counters[k] = int(v)
        self.schedule = Schedule.from_json(n.get("schedule", []))
        self.last_sent = {p: (int(v[0]), v[1]) for p, v in n.get("last_sent", {}).items()}
        if "act_rng" in n:
            self.act_rng.bit_generator.state = n["act_rng"]
        for k in ex.get("peer", {}).get("dedupe", []):
            self.dedupe[k] = None
        self.learner.events.clear()  # restored events were emitted before the checkpoint
        self.restore_info = {
            "restored": True, "generation": info["generation"],
            "prev_boot_id": n.get("boot_id"), "train_steps": self.learner.steps,
        }  # fmt: skip
        self._boot_event()

    def _boot_event(self) -> None:
        self._metric("node_boot", float(self.checkpoint_generation), "generation", "other")

    # --- status ------------------------------------------------------------------------------
    def status(self) -> dict:
        L = self.learner
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
                "peers": peers, "rss_bytes": rss_bytes(), "sequence": self.sequence,
                "telemetry_backlog": self.spool.backlog, "telemetry_dropped": self.spool.dropped,
                "exchange_running": self.exchange_running, "schedule_sha256": self.schedule.sha256,
                "counters": dict(self.counters), "restore": self.restore_info,
                "validation_evaluations": self.validator.episodes_run,
            }  # fmt: skip
        return st

    def close(self) -> None:
        with self._xcv:
            self._closing = True
            self._xcv.notify_all()
        if self._xthread is not None:
            self._xthread.join(timeout=5)
        self.spool.close()

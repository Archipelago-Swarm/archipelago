"""One run: episode plan, tick loop with action deadlines, fault schedule, kill_node, replay.

Privacy: a node is only ever sent its own contract Observation (built by the adapter from that
node's private buffer). The privileged snapshot is never put in a node request.

Decisions (see README):
- Feedback (A2) goes to every node that was asked to act this tick and carries what was executed:
  a node that missed the deadline had `stay` applied, so its feedback says `stay`,
  `action_index` 0 and `deadline_missed: true`. All acknowledgements are awaited (bounded by
  2 * deadline) before the next tick's act round. Never sent in eval episodes (nodes answer 409).
- `configure` (A5) is sent once per run to each node before its first `reset`; `reset` carries
  the fault schedule; `episode_end` (A4) goes to every non-killed node and is acknowledged with
  202 while the node runs its exchange window in the background.
- Every record the coordinator emits carries the global simulation tick
  `episode * max_ticks + tick` (A7); each episode runs under its own derived RunConfig (A14).
- A node marked unavailable is not called again within the episode; it is retried at the next
  episode reset and returns to `ready` if its reset succeeds.
- The coordinator's pause/resume gate the tick loop; they are not forwarded to nodes (node
  pause/resume only stops node training, a separate concept) and `stop` is never sent to nodes
  (it would shut a node process down).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from itertools import combinations
from pathlib import Path
from typing import Any

from archipelago_contracts.adapter import StepResult
from archipelago_contracts.models import (
    SCHEMA_VERSION,
    Action,
    MetricSample,
    RunConfig,
    Topology,
    WorldSnapshot,
)

from .models import (
    Episode,
    Plan,
    canonical_hash,
    expand_episodes,
    resolve_encoder_id,
    resolve_schedule,
    schedule_json,
)
from .nodeclient import NodeClient, Reply
from .settings import Settings
from .spool import EventSpool, safe_name

log = logging.getLogger("archipelago.coordinator")

MAX_CONSECUTIVE_MISSES = 5
CHECKPOINT_TIMEOUT_S = 10.0  # a node checkpoint writes a generation to disk
RESET_TIMEOUT_S = 8.0  # a node's reset may wait up to 5 s for a running exchange window (A4)
ACTION_INDEX = {name: i for i, name in enumerate(("stay", "north", "east", "south", "west"))}
ACTIVE = frozenset({"created", "starting", "running", "paused", "stopping"})
TERMINAL = frozenset({"completed", "failed", "interrupted"})


def _no_radar(o):
    return None if o.radar else {"radar"}  # keep the wire format unchanged for terrain-less worlds


SYNC_TICKS = 3  # ticks a reconnected link is shown (and handshaken) as syncing


class _Stop(Exception):
    pass


class _Crash(Exception):
    pass


@dataclass
class NodeHealth:
    state: str = "ready"  # ready | unavailable | killed
    consecutive_misses: int = 0
    deadline_misses: int = 0
    feedback_failures: int = 0


def adapter_kwargs(settings: Settings, plan: Plan) -> dict[str, Any]:
    """World parameters for the adapter: operator kwargs plus the plan's battery scale (A13)."""
    return {**settings.world_kwargs, "battery_scale": plan.battery_scale}


def _stay(node: str, run_id: str, tick: int) -> Action:
    return Action(
        schema_version=SCHEMA_VERSION,
        event_id=f"coord-stay-{node}-{tick}",
        run_id=run_id,
        source_node_id=node,
        sim_tick=tick,
        emitted_at_utc=datetime.now(UTC),
        sequence=tick,
        action_space_version="act-v0",
        command="stay",
        policy_version=0,
    )


class Run:
    def __init__(
        self,
        *,
        cfg: RunConfig,
        plan: Plan,
        settings: Settings,
        spool: EventSpool,
        client: NodeClient,
        adapter_factory: Callable[[dict[str, Any]], Any],
        on_state: Callable[[Run], None],
        plan_name: str = "default",
        plan_file_sha256: str = "",
    ) -> None:
        self.cfg, self.plan, self.settings = cfg, plan, settings
        self.plan_name, self.plan_file_sha256 = plan_name, plan_file_sha256
        self.spool, self.client, self.adapter_factory = spool, client, adapter_factory
        self.on_state = on_state
        self.run_id = cfg.run_id
        self.nodes = sorted(n.node_id for n in cfg.nodes)
        self.episodes = expand_episodes(plan)
        self.config_hash = canonical_hash(
            {"run_config": cfg.model_dump(mode="json"), "plan": plan.model_dump(mode="json")}
        )
        self.max_ticks = cfg.budgets.max_ticks
        self.schedule = schedule_json(plan)
        self.schedule_hash = canonical_hash(self.schedule)
        self.cond = threading.Condition(threading.RLock())
        self.world_lock = threading.Lock()
        self._blocked: list[tuple[str, str]] = []
        self._was_down: set[frozenset[str]] = set()
        self._sync_until: dict[frozenset[str], int] = {}
        self.status = "created"
        self.revision = 0
        self.stop_reason: str | None = None
        self.error: str | None = None
        self.episode_index = -1
        self.episode_kind: str | None = None
        self.tick = 0
        self.phase = "other"
        self.fault_phase = "none"
        self.health = {n: NodeHealth() for n in self.nodes}
        self.commands: dict[str, tuple[dict[str, Any], int, dict[str, Any]]] = {}
        self.step_tokens = 0
        self.stop_requested = False
        self.crashed = False
        self.adapter: Any = None
        self.configured: dict[str, str] = {}  # node -> config_hash it acknowledged
        self.configure_body: dict[str, Any] | None = None
        self.ids: dict[str, Any] = {  # versioned ids recorded in the manifest (A18)
            "reward_id": cfg.reward_id,
            "reward_source": "plan" if plan.reward_id else "run_config",
            "encoder_id": None,  # resolved against the live world at the first episode
            "learner_schedule_id": plan.node_config.learner_schedule_id,
        }
        self.priv_seq = 0
        self.summaries: list[dict[str, Any]] = []
        self.max_tick_ms = 0.0
        self.last_tick_ms = 0.0
        self.thread = threading.Thread(target=self._main, name=f"run-{self.run_id}", daemon=True)
        self.out_dir = settings.data_dir / "replays" / safe_name(self.run_id)

    # ------------------------------------------------------------------ state
    def set_status(self, new: str) -> None:
        with self.cond:
            self.status = new
            self.revision += 1
            self.cond.notify_all()
        self.on_state(self)

    def status_dict(self) -> dict[str, Any]:
        with self.cond:
            return {
                "run_id": self.run_id,
                "status": self.status,
                "revision": self.revision,
                "episode": max(self.episode_index, 0),
                "episode_kind": self.episode_kind,
                "episodes_total": len(self.episodes),
                "tick": self.tick,
                "phase": self.phase,
                "fault_phase": self.fault_phase,
                "nodes": {
                    n: {
                        "health": h.state,
                        "consecutive_misses": h.consecutive_misses,
                        "deadline_misses": h.deadline_misses,
                        "feedback_failures": h.feedback_failures,
                    }
                    for n, h in self.health.items()
                },
                "config_hash": self.config_hash,
                "ids": dict(self.ids),
                "plan_name": self.plan_name,
                "plan_file_sha256": self.plan_file_sha256,
                "node_config_hashes": dict(self.configured),
                "fault_schedule_hash": self.schedule_hash,
                "commit": self.settings.commit,
                "events_dropped": self.spool.dropped(self.run_id),
                "latest_sequence": self.spool.latest_sequence(self.run_id),
                "timing": {"last_tick_ms": self.last_tick_ms, "max_tick_ms": self.max_tick_ms},
                "stop_reason": self.stop_reason,
                "error": self.error,
                "episodes_done": list(self.summaries),
            }

    def apply_command(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """Validated lifecycle transitions; idempotent per command_id."""
        cid, cmd, expected = body["command_id"], body["command"], body.get("expected_revision")
        identity = {"command": cmd, "expected_revision": expected}
        with self.cond:
            if cid in self.commands:
                prev_id, prev_rev, prev_resp = self.commands[cid]
                if prev_id != identity:
                    return 409, {"error": "command_id_reused"}
                return 200, {**prev_resp, "duplicate": True}
            if expected is not None and expected != self.revision:
                return 409, {"error": "stale_revision", "revision": self.revision}
            st = self.status
            if cmd == "pause" and st in ("starting", "running"):
                self.set_status("paused")
            elif cmd == "resume" and st == "paused":
                self.set_status("running")
            elif cmd == "step" and st == "paused":
                self.step_tokens += 1
                self.revision += 1
                self.cond.notify_all()
                self.on_state(self)
            elif cmd == "stop" and st in ("starting", "running", "paused"):
                self.stop_requested = True
                self.set_status("stopping")
            elif cmd == "checkpoint" and st in ("running", "paused"):
                pass  # no lifecycle change; forwarded to the nodes below, once per command_id
            else:
                return 409, {"error": "invalid_transition", "status": st, "command": cmd}
            resp = {
                "run_id": self.run_id,
                "command_id": cid,
                "status": self.status,
                "revision": self.revision,
                "duplicate": False,
            }
            self.commands[cid] = (identity, self.revision, resp)
            if len(self.commands) > 2000:
                self.commands.pop(next(iter(self.commands)))
            targets = [n for n in self.nodes if self.health[n].state != "killed"]
        if cmd != "checkpoint":
            return 200, resp
        # Network I/O stays outside the lock. A duplicate command_id replays the stored response
        # and never re-sends the checkpoint request to the nodes.
        res = self.client.fanout(
            {
                n: partial(
                    self._ctl,
                    n,
                    {"command": "checkpoint", "run_id": self.run_id},
                    CHECKPOINT_TIMEOUT_S,
                )
                for n in targets
            },
            CHECKPOINT_TIMEOUT_S,
        )
        resp["checkpoint"] = {
            "requested": targets,
            "failed": sorted(n for n, r in res.items() if r is None or not r.ok),
        }
        return 200, resp

    def start(self) -> None:
        self.thread.start()

    def abort(self) -> None:
        """Crash simulation / shutdown: stop the thread without recording a terminal state."""
        with self.cond:
            self.crashed = True
            self.cond.notify_all()
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=10)

    # ------------------------------------------------------------------ events
    def _metric(
        self,
        name: str,
        value: float,
        unit: str,
        phase: str,
        tick: int,
        node: str | None = None,
    ) -> None:
        self.spool.emit(
            self.run_id,
            self._global_tick(tick),
            node,
            lambda b: MetricSample(**b, metric=name, value=value, unit=unit, phase=phase),
        )

    def _global_tick(self, tick: int) -> int:
        """A7: simulation time across the run is `episode * max_ticks + tick`."""
        return max(self.episode_index, 0) * self.max_ticks + tick

    def _link_state(self, tick: int):
        """(up, blocked): fault-schedule cuts and terrain RF occlusion both take a link down.
        Caller holds world_lock (reads the live world)."""
        cut: set[frozenset[str]] = set()
        for w in self.plan.fault_schedule:
            if w.start_tick <= tick < w.end_tick:
                cut |= {frozenset(link) for link in w.cut_links}
        alive = [n for n in self.nodes if self.health[n].state != "killed"]
        world = self.adapter.world if self.adapter else None
        rf_down = {frozenset(p) for p in world.rf_links()[1]} if hasattr(world, "rf_links") else set()
        pairs = list(combinations(alive, 2))
        up = [p for p in pairs if frozenset(p) not in cut | rf_down]
        return up, [p for p in pairs if frozenset(p) in rf_down]

    def _allowed_links(self, tick: int) -> list[tuple[str, str]]:
        return self._link_state(tick)[0]

    def _emit_snapshot(self, tick: int) -> None:
        with self.world_lock:
            links, blocked = self._link_state(tick)
            # a link that was down last snapshot and is up now is mid-handshake for SYNC_TICKS
            now = {frozenset(p) for p in links}
            for p in self._was_down & now:
                self._sync_until[p] = tick + SYNC_TICKS
            self._was_down = {frozenset(p) for p in combinations(self.nodes, 2)} - now
            syncing = [p for p in links if self._sync_until.get(frozenset(p), -1) > tick]
            self._blocked = blocked
            snap = self.adapter.public_snapshot(links, blocked, syncing)  # A10: only discovered obstacles
        self.spool.emit(
            self.run_id,
            self._global_tick(tick),
            None,
            lambda b: WorldSnapshot(
                **b,
                run_status=self.status,
                poses=snap.poses,
                obstacles=snap.obstacles,
                coverage=snap.coverage,
                topology=snap.topology,
                world=snap.world,
            ),
        )

    def privileged_snapshot(self) -> dict[str, Any] | None:
        """Admin view (A10): full obstacles plus targets, found targets and battery."""
        with self.world_lock:
            if self.adapter is None or self.adapter.world is None:
                return None
            links = self._allowed_links(self.adapter.world.tick)
            snap: WorldSnapshot = self.adapter.snapshot(links)
            extras = self.adapter.privileged_extras()
        with self.cond:
            self.priv_seq += 1
            n = self.priv_seq
        stamped = snap.model_copy(
            update={
                "run_id": self.run_id,
                "run_status": self.status,
                "event_id": f"{self.run_id}-priv-{self.spool.boot_id}-{n}",
                "sequence": n,
            }
        )
        return {**stamped.model_dump(mode="json"), "privileged": extras}

    def _fault_phase_at(self, tick: int) -> tuple[str, int]:
        sched = self.plan.fault_schedule
        active = [w for w in sched if w.start_tick <= tick < w.end_tick]
        if active:
            return "partition", sum(len(w.cut_links) for w in active)
        if any(w.end_tick <= tick for w in sched):
            return "recovery", 0
        return "none", 0

    # ------------------------------------------------------------------ main
    def _main(self) -> None:
        try:
            self.set_status("starting")
            for ep in self.episodes:
                if self._episode(ep):
                    break
            if self.crashed:
                return
            self.stop_reason = "stopped" if self.stop_requested else "plan_complete"
            self.set_status("completed")
        except _Crash:
            return
        except Exception as e:  # visible failure, never a silent fallback
            log.exception("run %s failed", self.run_id)
            self.error = f"{type(e).__name__}: {e}"
            if not self.crashed:
                self.set_status("failed")

    def _gate(self) -> None:
        with self.cond:
            while True:
                if self.crashed:
                    raise _Crash
                if self.stop_requested:
                    raise _Stop
                if self.status == "paused":
                    if self.step_tokens > 0:
                        self.step_tokens -= 1
                        return
                    self.cond.wait(0.05)
                    continue
                break
            if self.status == "starting":
                self.status = "running"
                self.revision += 1
                self.on_state(self)

    def _ctl(self, node: str, body: dict[str, Any], timeout: float) -> Reply:
        return self.client.call(self.plan.node_urls[node], "POST", "/v1/control", body, timeout)

    def _configure_body(self, adapter: Any) -> dict[str, Any]:
        """The per-run configure message (section 14), from the plan and the live world."""
        w, nc = adapter.world, self.plan.node_config
        n_train = sum(1 for e in self.episodes if e.kind == "train")
        hyper, eps = resolve_schedule(nc, n_train)  # A18: a registered schedule fills/refuses
        encoder_id = resolve_encoder_id(nc.encoder_id, w.size, w.radius)
        self.ids = {
            "reward_id": self.cfg.reward_id,
            "reward_source": "plan" if self.plan.reward_id else "run_config",
            "encoder_id": encoder_id,
            "learner_schedule_id": nc.learner_schedule_id,
        }
        return {
            "command": "configure",
            "run_id": self.run_id,
            "hyperparameters": hyper,
            "epsilon_schedule": eps,
            "learner_schedule_id": nc.learner_schedule_id,
            "margin": nc.margin,
            "world_config": {
                "size": w.size,
                "n_targets": w.n_targets,
                "obstacle_density": w.density,
                "sense_radius": w.radius,
                "max_ticks": self.max_ticks,
                "battery_scale": self.plan.battery_scale,
                "reward_id": self.cfg.reward_id,
            },
            "gate_seeds": list(nc.gate_seeds),
            "n_validation_agents": nc.n_validation_agents,
            "encoder_id": encoder_id,
            "exchange_every_ticks": nc.exchange_every_ticks,
            "seed": nc.seed,
        }

    def _reset_nodes(self, ep: Episode, timeout: float) -> None:
        def one(node: str) -> Reply:
            if node not in self.configured:  # once per run (retried only if it never succeeded)
                body = self.configure_body or {}
                r = self._ctl(node, body, timeout)
                if not r.ok:
                    return r
                self.configured[node] = str(r.body.get("config_hash", ""))
            return self._ctl(
                node,
                {
                    "command": "reset",
                    "run_id": self.run_id,
                    "episode": ep.index,
                    "mode": ep.mode,
                    "fault_schedule": self.schedule,
                },
                max(timeout, RESET_TIMEOUT_S),
            )

        res = self.client.fanout(
            {n: partial(one, n) for n in self.nodes}, max(timeout, RESET_TIMEOUT_S) + 2
        )
        reachable = 0
        for n in self.nodes:
            h, r = self.health[n], res[n]
            h.consecutive_misses = 0
            if r is not None and r.ok:
                h.state = "ready"
                reachable += 1
            else:
                h.state = "unavailable"
                self._metric("node_unavailable", 1.0, "count", ep.mode, 0, n)
        if reachable == 0:
            raise RuntimeError("no node reachable at episode reset")

    def _parse_action(self, reply: Reply | None, node: str, tick: int) -> Action | None:
        if reply is None or not reply.ok:
            return None
        b = reply.body
        if b.get("node_id") != node or b.get("tick") != tick:
            return None
        try:
            a = Action.model_validate(b.get("action"))
        except ValueError:
            return None
        if a.source_node_id != node or a.action_space_version != "act-v0":
            return None
        return a

    def _episode(self, ep: Episode) -> bool:
        """Run one episode. Returns True if the run was stopped."""
        mode, plan = ep.mode, self.plan
        deadline_s = plan.deadline_ms / 1000
        ctl_timeout = max(2.0, deadline_s)
        # A14: a derived RunConfig per episode (own env seed and run id), so ids never repeat
        cfg = self.cfg.model_copy(
            update={
                "run_id": f"{self.run_id}-e{ep.index}",
                "seeds": {**self.cfg.seeds, "env": ep.seed},
            }
        )
        adapter = self.adapter_factory(adapter_kwargs(self.settings, plan))
        with self.cond:
            self.episode_index, self.episode_kind, self.tick = ep.index, ep.kind, 0
            self.phase, self.fault_phase = mode, "none"
        with self.world_lock:
            obs = adapter.reset(cfg, episode=ep.index)
            old, self.adapter = self.adapter, adapter
        if old is not None:
            old.close()
        if self.configure_body is None:
            self.configure_body = self._configure_body(adapter)
        self.spool.set_outage(self.run_id, False)
        for h in self.health.values():
            h.state = "ready"
        self._reset_nodes(ep, ctl_timeout)
        self._emit_snapshot(0)
        if self.settings.start_paused and ep.index == 0:
            with self.cond:
                if self.status == "starting":
                    self.set_status("paused")
        returns = dict.fromkeys(self.nodes, 0.0)
        stopped = False
        t = 0
        try:
            while True:
                with self.world_lock:
                    live_world = list(adapter.world.agents)
                if not live_world:
                    break
                self._gate()
                t0 = time.monotonic()
                k = plan.kill_node
                if (
                    k is not None
                    and k.tick == t
                    and k.node_id in live_world
                    and self.health[k.node_id].state != "killed"
                ):
                    with self.world_lock:
                        adapter.kill(k.node_id)
                        live_world = list(adapter.world.agents)
                    self.health[k.node_id].state = "killed"
                    obs.pop(k.node_id, None)
                    self._metric("node_killed", 1.0, "count", mode, t, k.node_id)
                    if not live_world:
                        break
                o = plan.telemetry_outage
                self.spool.set_outage(self.run_id, bool(o and o.start_tick <= t < o.end_tick))
                fp, ncut = self._fault_phase_at(t)
                if fp != self.fault_phase:
                    self.fault_phase = fp
                    if fp != "none":
                        self._metric("fault_phase", float(ncut), "links", fp, t)
                actions, called, missed = self._act(ep, t, live_world, obs, deadline_s)
                with self.world_lock:
                    result: StepResult = adapter.step(actions)
                self._record_tick(ep, t, result, missed, returns)
                if mode == "train":
                    self._feedback(ep, t, result, actions, called, missed, deadline_s)
                with self.world_lock:
                    still = set(adapter.world.agents)
                obs = {n: o2 for n, o2 in result.observations.items() if n in still}
                t += 1
                with self.cond:
                    self.tick = t
                    self.last_tick_ms = (time.monotonic() - t0) * 1000
                    self.max_tick_ms = max(self.max_tick_ms, self.last_tick_ms)
                if self.settings.tick_interval_s:
                    time.sleep(self.settings.tick_interval_s)
        except _Stop:
            stopped = True
        self._finish_episode(ep, t, returns, ctl_timeout)
        return stopped

    def _act(
        self,
        ep: Episode,
        t: int,
        live_world: list[str],
        obs: dict[str, Any],
        deadline_s: float,
    ) -> tuple[dict[str, Action], list[str], list[str]]:
        """Returns (actions to apply, nodes that were asked, nodes that missed the deadline)."""
        called = [n for n in live_world if self.health[n].state == "ready" and n in obs]
        ms = int(deadline_s * 1000)

        def mk(n: str) -> Callable[[], Reply]:
            body = {
                "run_id": self.run_id,
                "episode": ep.index,
                "tick": t,
                "deadline_ms": ms,
                "observation": obs[n].model_dump(mode="json", exclude=_no_radar(obs[n])),
            }
            if blocked := sorted({q for p in self._blocked if n in p for q in p} - {n}):
                body["rf_blocked"] = blocked  # only when terrain occludes a peer
            url = self.plan.node_urls[n]
            return lambda: self.client.call(url, "POST", "/v1/act", body, deadline_s + 0.05)

        replies = self.client.fanout({n: mk(n) for n in called}, deadline_s)
        actions: dict[str, Action] = {}
        missed: list[str] = []
        for n in live_world:
            a = self._parse_action(replies.get(n), n, t) if n in called else None
            h = self.health[n]
            if a is not None:
                actions[n] = a
                h.consecutive_misses = 0
                continue
            actions[n] = _stay(n, self.run_id, t)
            if n in called:
                missed.append(n)
                h.deadline_misses += 1
                h.consecutive_misses += 1
                self._metric("deadline_missed", 1.0, "count", ep.mode, t, n)
                if h.consecutive_misses >= MAX_CONSECUTIVE_MISSES:
                    h.state = "unavailable"
                    self._metric("node_unavailable", 1.0, "count", ep.mode, t, n)
        return actions, called, missed

    def _record_tick(
        self,
        ep: Episode,
        t: int,
        result: StepResult,
        missed: list[str],
        returns: dict[str, float],
    ) -> None:
        for n, r in result.rewards.items():
            returns[n] += r
        with self.world_lock:
            cov = self.adapter.world.coverage
        self._metric("coverage", cov, "fraction", ep.mode, t + 1)
        self._emit_snapshot(t + 1)

    def _feedback(
        self,
        ep: Episode,
        t: int,
        result: StepResult,
        actions: dict[str, Action],
        called: list[str],
        missed: list[str],
        deadline_s: float,
    ) -> None:
        """A2: tell every asked node what was executed; wait for all acks (<= 2 * deadline)."""
        timeout = 2 * deadline_s

        def mk(n: str) -> Callable[[], Reply]:
            cmd = actions[n].command
            body = {
                "run_id": self.run_id,
                "episode": ep.index,
                "tick": t,
                "reward": result.rewards[n],
                "next_observation": result.observations[n].model_dump(
                    mode="json", exclude=_no_radar(result.observations[n])
                ),
                "terminated": result.terminations[n],
                "truncated": result.truncations[n],
                "executed_command": cmd,
                "action_index": ACTION_INDEX[cmd],
                "deadline_missed": n in missed,
            }
            url = self.plan.node_urls[n]
            return lambda: self.client.call(url, "POST", "/v1/feedback", body, timeout)

        targets = [n for n in called if n in result.rewards]
        replies = self.client.fanout({n: mk(n) for n in targets}, timeout)
        for n, r in replies.items():
            if r is None or not r.ok:  # late responses are discarded, never retried
                self.health[n].feedback_failures += 1
                self._metric("feedback_failed", 1.0, "count", ep.mode, t, n)

    def _finish_episode(
        self, ep: Episode, ticks: int, returns: dict[str, float], ctl_timeout: float
    ) -> None:
        with self.world_lock:
            adapter = self.adapter
            manifest = adapter.write_replay(self.out_dir / f"ep-{ep.index:04d}")
            cov = adapter.world.coverage
            state_hash = adapter.world.trace_hash()
        for n, r in returns.items():
            self._metric("episode_return", r, "reward", ep.mode, ticks, n)
        self._metric("coverage", cov, "fraction", ep.mode, ticks)
        # A4: every node still in the world (terminated and unavailable ones too, not killed ones)
        # gets episode_end; the 202 comes back at once while the node's final exchange window runs
        # in the background, so nothing here waits for the window itself.
        targets = [n for n in self.nodes if self.health[n].state != "killed"]
        body = {"command": "episode_end", "run_id": self.run_id, "episode": ep.index, "tick": ticks}
        ends = self.client.fanout(
            {n: partial(self._ctl, n, body, ctl_timeout) for n in targets}, ctl_timeout
        )
        with self.cond:
            self.summaries.append(
                {
                    "episode": ep.index,
                    "kind": ep.kind,
                    "seed": ep.seed,
                    "ticks": ticks,
                    "final_state_hash": state_hash,
                    "coverage": cov,
                    "returns": returns,
                    "replay_manifest": str(Path(manifest)),
                    "episode_end_sent": targets,
                    "episode_end_failed": sorted(
                        n for n, r in ends.items() if r is None or not r.ok
                    ),
                    "window_ids": {
                        n: r.body.get("window_id")
                        for n, r in ends.items()
                        if r is not None and r.ok
                    },
                }
            )
        self.on_state(self)

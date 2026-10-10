"""One run: episode plan, tick loop with action deadlines, fault schedule, kill_node, replay.

Privacy: a node is only ever sent its own contract Observation (built by the adapter from that
node's private buffer). The privileged snapshot is never put in a node request.

Decisions (see README):
- Feedback is only sent to nodes whose action was actually applied this tick (a node that missed
  the deadline had `stay` applied, so pairing its cached action with the reward would be wrong)
  and never in eval episodes (nodes answer 409 there).
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

from .models import Episode, Plan, canonical_hash, expand_episodes, schedule_json
from .nodeclient import NodeClient, Reply
from .settings import Settings
from .spool import EventSpool, safe_name

log = logging.getLogger("archipelago.coordinator")

MAX_CONSECUTIVE_MISSES = 5
ACTIVE = frozenset({"created", "starting", "running", "paused", "stopping"})
TERMINAL = frozenset({"completed", "failed", "interrupted"})


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
    ) -> None:
        self.cfg, self.plan, self.settings = cfg, plan, settings
        self.spool, self.client, self.adapter_factory = spool, client, adapter_factory
        self.on_state = on_state
        self.run_id = cfg.run_id
        self.nodes = sorted(n.node_id for n in cfg.nodes)
        self.episodes = expand_episodes(plan)
        self.config_hash = canonical_hash(
            {"run_config": cfg.model_dump(mode="json"), "plan": plan.model_dump(mode="json")}
        )
        self.schedule = schedule_json(plan)
        self.schedule_hash = canonical_hash(self.schedule)
        self.cond = threading.Condition(threading.RLock())
        self.world_lock = threading.Lock()
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
            tick,
            node,
            lambda b: MetricSample(**b, metric=name, value=value, unit=unit, phase=phase),  # type: ignore[arg-type]
        )

    def _allowed_links(self, tick: int) -> list[tuple[str, str]]:
        cut: set[frozenset[str]] = set()
        for w in self.plan.fault_schedule:
            if w.start_tick <= tick < w.end_tick:
                cut |= {frozenset(link) for link in w.cut_links}
        alive = [n for n in self.nodes if self.health[n].state != "killed"]
        return [(a, b) for a, b in combinations(alive, 2) if frozenset((a, b)) not in cut]

    def _emit_snapshot(self, tick: int) -> None:
        with self.world_lock:
            snap = self.adapter.snapshot()
        links = self._allowed_links(tick)
        self.spool.emit(
            self.run_id,
            tick,
            None,
            lambda b: WorldSnapshot(
                **b,
                run_status=self.status,  # type: ignore[arg-type]
                poses=snap.poses,
                obstacles=snap.obstacles,
                coverage=snap.coverage,
                topology=Topology(links=links),
            ),
        )

    def privileged_snapshot(self) -> WorldSnapshot | None:
        with self.world_lock:
            if self.adapter is None or self.adapter.world is None:
                return None
            snap: WorldSnapshot = self.adapter.snapshot()
        return snap.model_copy(
            update={
                "run_id": self.run_id,
                "run_status": self.status,
                "topology": Topology(links=self._allowed_links(snap.sim_tick)),
            }
        )

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

    def _reset_nodes(self, ep: Episode, timeout: float) -> None:
        def one(node: str) -> Reply:
            r = self._ctl(
                node,
                {
                    "command": "reset",
                    "run_id": self.run_id,
                    "episode": ep.index,
                    "mode": ep.mode,
                    "seed": ep.seed,
                    "episode_kind": ep.kind,
                },
                timeout,
            )
            if not r.ok:
                return r
            # schedule is sent after reset so a reset cannot clear it
            return self._ctl(
                node,
                {
                    "command": "set_schedule",
                    "run_id": self.run_id,
                    "episode": ep.index,
                    "schedule": self.schedule,
                    "schedule_sha256": self.schedule_hash,
                },
                timeout,
            )

        res = self.client.fanout({n: (lambda n=n: one(n)) for n in self.nodes}, timeout)
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
        cfg = self.cfg.model_copy(update={"seeds": {**self.cfg.seeds, "env": ep.seed}})
        adapter = self.adapter_factory(self.settings.world_kwargs)
        with self.world_lock:
            obs = adapter.reset(cfg)
            old, self.adapter = self.adapter, adapter
        if old is not None:
            old.close()
        with self.cond:
            self.episode_index, self.episode_kind, self.tick = ep.index, ep.kind, 0
            self.phase, self.fault_phase = mode, "none"
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
                        adapter.remove_node(k.node_id)
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
                actions, applied, missed = self._act(ep, t, live_world, obs, deadline_s)
                with self.world_lock:
                    result: StepResult = adapter.step(actions)
                self._record_tick(ep, t, result, missed, returns)
                if mode == "train":
                    self._feedback(ep, t, result, applied, deadline_s)
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
        called = [n for n in live_world if self.health[n].state == "ready" and n in obs]
        ms = int(deadline_s * 1000)

        def mk(n: str) -> Callable[[], Reply]:
            body = {
                "run_id": self.run_id,
                "episode": ep.index,
                "tick": t,
                "deadline_ms": ms,
                "observation": obs[n].model_dump(mode="json"),
            }
            url = self.plan.node_urls[n]
            return lambda: self.client.call(url, "POST", "/v1/act", body, deadline_s + 0.05)

        replies = self.client.fanout({n: mk(n) for n in called}, deadline_s)
        actions: dict[str, Action] = {}
        applied: list[str] = []
        missed: list[str] = []
        for n in live_world:
            a = self._parse_action(replies.get(n), n, t) if n in called else None
            h = self.health[n]
            if a is not None:
                actions[n] = a
                applied.append(n)
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
        return actions, applied, missed

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
        self, ep: Episode, t: int, result: StepResult, applied: list[str], deadline_s: float
    ) -> None:
        def mk(n: str) -> Callable[[], Reply]:
            body = {
                "run_id": self.run_id,
                "episode": ep.index,
                "tick": t,
                "reward": result.rewards[n],
                "next_observation": result.observations[n].model_dump(mode="json"),
                "terminated": result.terminations[n],
                "truncated": result.truncations[n],
            }
            url = self.plan.node_urls[n]
            return lambda: self.client.call(url, "POST", "/v1/feedback", body, deadline_s + 0.05)

        targets = [n for n in applied if n in result.rewards and self.health[n].state == "ready"]
        replies = self.client.fanout({n: mk(n) for n in targets}, deadline_s)
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
        ends = self.client.fanout(
            {
                n: (
                    lambda n=n: self._ctl(
                        n,
                        {"command": "episode_end", "run_id": self.run_id, "episode": ep.index},
                        ctl_timeout,
                    )
                )
                for n in self.nodes
            },
            ctl_timeout,
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
                    "episode_end_failed": sorted(
                        n for n, r in ends.items() if r is None or not r.ok
                    ),
                }
            )
        self.on_state(self)

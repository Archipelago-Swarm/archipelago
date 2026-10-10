"""Tick loop, deadlines, node health, episode replay and the event spool.

The coordinator is a centralized world service (live-runtime.md section 1). It hands each node only
its own contract Observation, turns a missing or late action into "stay", and never trains or
aggregates anything.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Protocol

from archipelago_contracts.models import (
    SCHEMA_VERSION,
    Action,
    MetricSample,
    Observation,
    RunConfig,
)

MISS_LIMIT = 5  # consecutive deadline misses before a node is marked unavailable
STATES = ("created", "running", "paused", "stopping", "completed", "failed")


class SimulatorUnavailable(RuntimeError):
    """The real simulator cannot be imported. There is deliberately no fixture fallback."""


class CommandError(ValueError):
    pass


class NodeClient(Protocol):
    def act(self, payload: dict[str, Any], deadline_ms: int) -> dict[str, Any] | None: ...
    def feedback(self, payload: dict[str, Any]) -> None: ...
    def control(self, payload: dict[str, Any]) -> None: ...


def default_adapter_factory() -> Any:
    try:
        from archipelago_sim2d.adapter import Sim2DAdapter
    except ImportError as error:  # production must fail visibly, not degrade
        raise SimulatorUnavailable(f"real simulator unavailable: {error}") from error
    return Sim2DAdapter()


class Spool:
    """Append-only JSONL of canonical events. Sequence numbers continue across restarts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.next_sequence = 1
        self.oldest = 1
        if path.is_file():
            lines = [line for line in path.read_text().splitlines() if line.strip()]
            if lines:
                self.oldest = json.loads(lines[0])["sequence"]
                self.next_sequence = json.loads(lines[-1])["sequence"] + 1

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            record = {**record, "sequence": self.next_sequence}
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            self.next_sequence += 1
            return record

    def read(self, after: int = 0, limit: int = 500) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        if self.path.is_file():
            for line in self.path.read_text().splitlines():
                if line.strip() and (rec := json.loads(line))["sequence"] > after:
                    events.append(rec)
                    if len(events) >= limit:
                        break
        return {
            "events": events,
            "latest_sequence": self.next_sequence - 1,
            "oldest_sequence": self.oldest,
        }


class Coordinator:
    def __init__(
        self,
        data_dir: Path,
        nodes: dict[str, NodeClient],
        adapter_factory: Callable[[], Any] = default_adapter_factory,
        deadline_ms: int = 500,
        miss_limit: int = MISS_LIMIT,
    ) -> None:
        self.adapter = adapter_factory()  # raises SimulatorUnavailable in production if missing
        self.data_dir, self.nodes, self.deadline_ms = data_dir, nodes, deadline_ms
        self.miss_limit = miss_limit
        self.spool = Spool(data_dir / "events.jsonl")
        self.pool = ThreadPoolExecutor(max_workers=max(4, 2 * len(nodes)))
        self.run_id: str | None = None
        self.status = "created"
        self.revision = 0
        self.episode = 0
        self.tick = 0
        self.config: RunConfig | None = None
        self.health: dict[str, str] = {}
        self.misses: dict[str, int] = {}
        self.miss_total: dict[str, int] = {}
        self._commands: dict[str, dict[str, Any]] = {}
        self._obs: dict[str, Observation] = {}
        self._lock = threading.RLock()
        self.final_hashes: dict[int, str] = {}

    # ------------------------------------------------------------ run lifecycle
    def start_run(self, config: RunConfig) -> str:
        with self._lock:
            if self.status in {"running", "paused"}:
                raise CommandError("a run is already active")
            missing = [n.node_id for n in config.nodes if n.node_id not in self.nodes]
            if missing:
                raise CommandError(f"no node client for {missing}")
            self.config, self.run_id, self.episode = config, config.run_id, 0
            self.health = {n.node_id: "ready" for n in config.nodes}
            self.misses = {n: 0 for n in self.health}
            self.miss_total = {n: 0 for n in self.health}
            self._begin_episode()
            self.status = "running"
            self.revision += 1
            return config.run_id

    def _begin_episode(self) -> None:
        assert self.config is not None
        self._obs = self.adapter.reset(self.config)
        self.tick = 0
        for node, client in self.nodes.items():
            if node in self.health:
                self._safe(
                    client.control,
                    {
                        "command": "reset",
                        "run_id": self.run_id,
                        "episode": self.episode,
                        "mode": "train",
                    },
                )
        self._emit_snapshot()

    @staticmethod
    def _safe(call: Callable[[dict[str, Any]], Any], payload: dict[str, Any]) -> Any:
        try:
            return call(payload)
        except Exception:  # a failing node must never stop the world
            return None

    # --------------------------------------------------------------- one tick
    def step_tick(self) -> bool:
        """Advance one tick. Returns False once the episode is over."""
        with self._lock:
            w = self.adapter.world
            if w is None or not w.agents:
                return False
            assert self.config is not None and self.run_id is not None
            self.tick += 1
            actions = self._collect_actions()
            result = self.adapter.step(actions)
            self._send_feedback(result)
            self._obs = result.observations or self._obs
            self._emit_snapshot()
            self._metric("coverage", self.adapter.world.coverage, "ratio", "train")
            return bool(self.adapter.world.agents)

    def _collect_actions(self) -> dict[str, Action]:
        active = [n for n in self.adapter.world.agents if self.health.get(n) == "ready"]
        futures = {
            n: self.pool.submit(
                self.nodes[n].act,
                {
                    "run_id": self.run_id,
                    "episode": self.episode,
                    "tick": self.tick,
                    "deadline_ms": self.deadline_ms,
                    "observation": self._obs[n].model_dump(
                        mode="json"
                    ),  # this node's own view only
                },
                self.deadline_ms,
            )
            for n in active
            if n in self._obs
        }
        stop = time.monotonic() + self.deadline_ms / 1000
        actions: dict[str, Action] = {}
        for node, future in futures.items():
            try:
                raw = future.result(timeout=max(0.0, stop - time.monotonic()))
                action = Action.model_validate(raw["action"]) if raw else None
            except (FutureTimeout, Exception):
                future.cancel()
                action = None
            if action is None or action.source_node_id != node:
                self._miss(node)
            else:
                self.misses[node] = 0
                actions[node] = action
        return actions

    def _miss(self, node: str) -> None:
        self.misses[node] += 1
        self.miss_total[node] += 1
        self._metric("deadline_missed", 1.0, "count", "train", node)
        if self.misses[node] >= self.miss_limit:
            self.health[node] = "unavailable"  # stays in the world, no longer asked
            self._metric("node_unavailable", 1.0, "flag", "train", node)

    def _send_feedback(self, result: Any) -> None:
        for node, obs in result.observations.items():
            if self.health.get(node) != "ready":
                continue
            payload = {
                "run_id": self.run_id,
                "episode": self.episode,
                "tick": self.tick,
                "reward": result.rewards[node],
                "next_observation": obs.model_dump(mode="json"),
                "terminated": result.terminations[node],
                "truncated": result.truncations[node],
            }
            self.pool.submit(self._safe, self.nodes[node].feedback, payload)

    # ------------------------------------------------------------ faults, commands
    def kill_node(self, node: str) -> None:
        with self._lock:
            self.adapter.kill_node(node)
            self.health[node] = "killed"
            self._metric("node_killed", 1.0, "flag", "partition", node)
            self._emit_snapshot()

    def command(
        self, command_id: str, command: str, expected_revision: int | None = None
    ) -> dict[str, Any]:
        with self._lock:
            if command_id in self._commands:
                return self._commands[command_id]  # idempotent replay of the same command id
            if expected_revision is not None and expected_revision != self.revision:
                raise CommandError(f"stale revision {expected_revision}, current {self.revision}")
            allowed = {
                "pause": {"running"},
                "resume": {"paused"},
                "step": {"paused"},
                "stop": {"running", "paused"},
            }
            if command not in allowed:
                raise CommandError(f"unknown command {command!r}")
            if self.status not in allowed[command]:
                raise CommandError(f"cannot {command} while {self.status}")
            if command == "pause":
                self.status = "paused"
            elif command == "resume":
                self.status = "running"
            elif command == "stop":
                self.status = "stopping"
            else:
                self.step_tick()
            self.revision += 1
            reply = {"command_id": command_id, "status": self.status, "revision": self.revision}
            self._commands[command_id] = reply
            return reply

    def finish_episode(self, out_dir: Path | None = None) -> str:
        """Write the replay, check it reproduces the final hash, tell nodes the episode ended."""
        from archipelago_sim2d.adapter import replay_final_hash

        assert self.config is not None
        out = out_dir or self.data_dir / "replays" / f"episode-{self.episode}"
        manifest = self.adapter.write_replay(out)
        final = json.loads(manifest.read_text())["final_state_hash"]
        records = [json.loads(line) for line in (out / "replay.jsonl").read_text().splitlines()]
        again = replay_final_hash(self.config, records, **self.adapter.kw)
        if again != final:
            self.status = "failed"
            raise RuntimeError(f"replay mismatch: {again} != {final}")
        self.final_hashes[self.episode] = final
        for node, client in self.nodes.items():
            if node in self.health:
                self._safe(
                    client.control,
                    {"command": "episode_end", "run_id": self.run_id, "episode": self.episode},
                )
        return final

    def run_to_end(self) -> str:
        """Drive the episode until it ends or a stop is requested; honors pause."""
        while True:
            with self._lock:
                status = self.status
            if status == "stopping":
                break
            if status == "paused":
                time.sleep(0.01)
                continue
            if not self.step_tick():
                break
        final = self.finish_episode()
        with self._lock:
            self.status = "completed" if self.status != "failed" else "failed"
            self.revision += 1
        return final

    # -------------------------------------------------------------------- events
    def _event_meta(self, kind: str, node: str | None) -> dict[str, Any]:
        seq = self.spool.next_sequence
        return {
            "event_id": f"{self.run_id}-e{self.episode}-{kind}-{seq}",
            "sequence": seq,
            "run_id": self.run_id,
            "source_node_id": node,
            "sim_tick": self.tick,
        }

    def _emit_snapshot(self) -> None:
        snap = self.adapter.snapshot().model_copy(update=self._event_meta("snap", None))
        snap = snap.model_copy(
            update={"run_status": "running" if self.status != "completed" else "completed"}
        )
        self.spool.append(snap.model_dump(mode="json"))

    def _metric(
        self, metric: str, value: float, unit: str, phase: str, node: str | None = None
    ) -> None:
        from datetime import UTC, datetime

        sample = MetricSample(
            schema_version=SCHEMA_VERSION,
            emitted_at_utc=datetime.now(UTC),
            metric=metric,
            value=value,
            unit=unit,
            phase=phase,  # type: ignore[arg-type]
            **self._event_meta("m", node),
        )
        self.spool.append(sample.model_dump(mode="json"))

    def privileged_snapshot(self) -> dict[str, Any]:
        return dict(self.adapter.world.world_state())  # admin only; never sent to nodes

    def run_view(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "revision": self.revision,
            "episode": self.episode,
            "tick": self.tick,
            "nodes": {
                n: {"health": h, "deadline_misses": self.miss_total[n]}
                for n, h in self.health.items()
            },
        }

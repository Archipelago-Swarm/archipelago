"""In-memory run registry with a small JSON file so restarts mark orphaned runs interrupted."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from archipelago_contracts.adapter import SimulatorAdapter
from archipelago_contracts.models import RunConfig

from .settings import Settings

Status = Literal[
    "created", "starting", "running", "paused", "stopping", "completed", "failed", "interrupted"
]
ACTIVE = {"created", "starting", "running", "paused", "stopping"}
Command = Literal["pause", "resume", "step", "stop"]
AdapterFactory = Callable[[RunConfig], SimulatorAdapter]


class Conflict(Exception):
    pass


class NotFound(Exception):
    pass


class Subscriber:
    def __init__(self, size: int) -> None:
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(size)
        self.lagged = False


@dataclass
class Run:
    config: RunConfig
    config_hash: str
    adapter: SimulatorAdapter | None = None
    status: Status = "created"
    revision: int = 0
    reason: str | None = None
    tick: int = 0
    seq: int = 0
    started: float = field(default_factory=time.monotonic)
    events: deque[dict[str, Any]] = field(default_factory=deque)
    subs: set[Subscriber] = field(default_factory=set)
    commands: dict[str, dict[str, Any]] = field(default_factory=dict)
    task: asyncio.Task[None] | None = None
    final: dict[str, Any] | None = None  # last snapshot, kept because close() clears the adapter world

    def view(self) -> dict[str, Any]:
        return {
            "run_id": self.config.run_id,
            "status": self.status,
            "revision": self.revision,
            "completion_reason": self.reason,
            "tick": self.tick,
            "config": self.config.model_dump(mode="json"),
            "artifacts": [],  # T08 fills the artifact manifest
        }


class RunManager:
    def __init__(self, settings: Settings, factory: AdapterFactory) -> None:
        self.s, self.factory = settings, factory
        self.runs: dict[str, Run] = {}
        self.keys: dict[str, tuple[str, str]] = {}  # idempotency key -> (config hash, run id)
        self._file = settings.data_dir / "runs.json"
        self._recover()

    # persistence: metadata only; events and checkpoints are not recovered (marked interrupted)
    def _recover(self) -> None:
        self.s.data_dir.mkdir(parents=True, exist_ok=True)
        if not self._file.exists():
            return
        for d in json.loads(self._file.read_text())["runs"]:
            run = Run(RunConfig.model_validate(d["config"]), d["config_hash"])
            run.status, run.revision, run.reason, run.tick = (
                d["status"],
                d["revision"],
                d["reason"],
                d["tick"],
            )
            if run.status in ACTIVE:
                run.status, run.reason = "interrupted", "process_restart"
                run.revision += 1
            self.runs[run.config.run_id] = run
            if d["key"]:
                self.keys[d["key"]] = (run.config_hash, run.config.run_id)
        self._save()

    def _save(self) -> None:
        by_id = {rid: k for k, (_, rid) in self.keys.items()}
        doc = {
            "runs": [
                {
                    "config": r.config.model_dump(mode="json"),
                    "config_hash": r.config_hash,
                    "status": r.status,
                    "revision": r.revision,
                    "reason": r.reason,
                    "tick": r.tick,
                    "key": by_id.get(rid),
                }
                for rid, r in self.runs.items()
            ]
        }
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc))
        os.replace(tmp, self._file)

    def active_count(self) -> int:
        return sum(r.status in ACTIVE for r in self.runs.values())

    def get(self, run_id: str) -> Run:
        try:
            return self.runs[run_id]
        except KeyError:
            raise NotFound(run_id) from None

    def _emit(self, run: Run, kind: str, **extra: Any) -> None:
        run.seq += 1
        ev = {"sequence": run.seq, "type": kind, "tick": run.tick, "status": run.status, **extra}
        run.events.append(ev)
        while len(run.events) > self.s.event_log_size:
            run.events.popleft()
        for sub in run.subs:
            try:
                sub.queue.put_nowait(ev)
            except asyncio.QueueFull:  # never block the simulation on a slow viewer
                sub.lagged = True
                while not sub.queue.empty():
                    sub.queue.get_nowait()
                sub.queue.put_nowait(ev)  # wake the sender so it emits the resnapshot

    def snapshot_event(self, run: Run) -> dict[str, Any]:
        snap: dict[str, Any] = run.final or {}
        if run.final is None and run.adapter is not None:
            snap = (
                run.adapter.snapshot()
                .model_copy(
                    update={"sim_tick": run.tick, "sequence": run.seq, "run_status": run.status}
                )
                .model_dump(mode="json")
            )
        return {
            "sequence": run.seq,
            "type": "snapshot",
            "tick": run.tick,
            "status": run.status,
            "snapshot": snap,
        }

    def _set(self, run: Run, status: Status, reason: str | None = None) -> None:
        run.status, run.reason = status, reason or run.reason
        run.revision += 1
        self._emit(run, "status", reason=run.reason)
        self._save()

    def create(self, key: str, config: RunConfig) -> tuple[Run, bool]:
        chash = config.model_dump_json()
        if key in self.keys:
            old_hash, rid = self.keys[key]
            if old_hash != chash:
                raise Conflict("idempotency key reused with a different config")
            return self.runs[rid], False
        if config.run_id in self.runs:
            raise Conflict("run_id already exists")
        if self.active_count() >= self.s.max_active_runs:
            raise Conflict("run capacity reached")
        run = Run(config, chash)
        self.runs[config.run_id], self.keys[key] = run, (chash, config.run_id)
        self._set(run, "starting")
        try:
            run.adapter = self.factory(config)
            run.adapter.reset(config)
        except Exception as e:
            self._set(run, "failed", f"adapter_error:{type(e).__name__}")
            raise Conflict("adapter failed to start") from e
        self._set(run, "running")
        if self.s.tick_interval is not None:
            run.task = asyncio.get_running_loop().create_task(self._loop(run))
        return run, True

    def _advance(self, run: Run) -> None:
        assert run.adapter is not None
        run.adapter.step({})
        run.tick += 1
        # shortcut: each delta carries a full snapshot; switch to diffs if bandwidth matters
        self._emit(run, "delta", snapshot=self.snapshot_event(run)["snapshot"])
        if run.tick >= run.config.budgets.max_ticks:
            self._finish(run, "completed", "max_ticks")
        elif time.monotonic() - run.started > run.config.budgets.max_wall_seconds:
            self._finish(run, "completed", "max_wall_seconds")

    def _finish(self, run: Run, status: Status, reason: str) -> None:
        if run.adapter is not None:
            if run.final is None:
                try:
                    run.final = self.snapshot_event(run)["snapshot"]
                except Exception:  # adapter already unusable: the stream reports status only
                    pass
            run.adapter.close()
        self._set(run, status, reason)

    async def _loop(self, run: Run) -> None:
        assert self.s.tick_interval is not None
        try:
            while run.status in ("running", "paused"):
                if run.status == "running":
                    self._advance(run)
                await asyncio.sleep(self.s.tick_interval)
        except Exception as e:
            self._finish(run, "failed", f"sim_error:{type(e).__name__}")

    def command(
        self, run: Run, command: Command, command_id: str, expected_revision: int
    ) -> dict[str, Any]:
        if command_id in run.commands:
            return run.commands[command_id]
        if expected_revision != run.revision:
            raise Conflict(f"stale revision: run is at {run.revision}")
        allowed = {
            "pause": {"running"},
            "resume": {"paused"},
            "step": {"paused"},
            "stop": {"running", "paused"},
        }[command]
        if run.status not in allowed:
            raise Conflict(f"cannot {command} a run that is {run.status}")
        if command == "pause":
            self._set(run, "paused")
        elif command == "resume":
            self._set(run, "running")
        elif command == "step":
            run.revision += 1
            self._advance(run)
        else:
            self._set(run, "stopping")
            self._finish(run, "completed", "stopped")
        result = run.view()
        run.commands[command_id] = result
        return result

    async def shutdown(self) -> None:
        for run in self.runs.values():
            if run.task:
                run.task.cancel()
            if run.status in ACTIVE:
                self._finish(run, "interrupted", "process_shutdown")

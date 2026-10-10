"""Optional TigerData persistence for runs, events and metrics (via archipelago_storage).

Contract (agents/architecture/core.md): a telemetry outage never blocks or crashes a run.
- record_* are synchronous, O(1), in-memory and never raise.
- The pending spool is bounded; on overflow the oldest row is shed and counted in `dropped`.
- All database I/O happens in a worker thread, serialized by one lock, in batches.
- Retries are idempotent: rows carry a fixed ts/event_id and the writer uses ON CONFLICT DO NOTHING.
- With TIGERDATA_URL unset, `Persister.from_env` returns None and the API runs unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

log = logging.getLogger("archipelago.persistence")

NODE_ID = "api"
SWARM = "swarm"  # canonical records with no source node (coordinator-wide)


def _parse_utc(value: Any, default: datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return default
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class Sink(Protocol):
    def put(self, kind: str, run_id: str, row: tuple[Any, ...]) -> None: ...
    def flush(self) -> bool: ...
    def __len__(self) -> int: ...


class Persister:
    def __init__(
        self,
        sink: Sink,
        cap: int = 10_000,
        interval: float = 1.0,
        now: Callable[[], datetime] | None = None,
        migrate: Callable[[], None] | None = None,
    ) -> None:
        self._sink, self._cap, self._interval = sink, cap, interval
        self._now = now or (lambda: datetime.now(UTC))
        self._pending: deque[tuple[str, str, tuple[Any, ...]]] = deque()
        self._shed = 0
        self._lock: asyncio.Lock | None = None
        self._stop: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None
        self._healthy = True
        self._migrate = migrate  # applied once, in the worker thread, before the first write
        self._migrated = migrate is None
        self.migration_failures = 0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Persister | None:
        env = os.environ if env is None else env
        if not env.get("TIGERDATA_URL"):
            log.info("TIGERDATA_URL is not set: TigerData persistence disabled")
            return None
        try:
            from archipelago_storage import Writer, connect_from_env, migrate, validate_url
        except ImportError:  # image built without the storage package or psycopg
            log.error("TIGERDATA_URL is set but archipelago_storage is not importable: disabled")
            return None
        try:
            validate_url(env["TIGERDATA_URL"])
        except ValueError as exc:
            log.error("TIGERDATA_URL rejected, TigerData persistence disabled: %s", exc)
            return None

        def connect() -> Any:
            return connect_from_env()

        def apply_migrations() -> None:
            conn = connect()
            try:
                migrate(conn)
            finally:
                conn.close()

        log.info("TigerData persistence enabled")
        return cls(Writer(connect), migrate=apply_migrations)

    @property
    def dropped(self) -> int:
        """Rows lost to backpressure: this spool plus the writer's own bounded queue."""
        return self._shed + int(getattr(self._sink, "dropped_total", 0))

    @property
    def queued(self) -> int:
        return len(self._pending) + len(self._sink)

    def _enqueue(self, kind: str, run_id: str, row: tuple[Any, ...]) -> None:
        if len(self._pending) >= self._cap:
            self._pending.popleft()
            self._shed += 1
        self._pending.append((kind, run_id, row))

    def record_run(
        self, run_id: str, scenario: str | None = None, git_sha: str | None = None
    ) -> None:
        try:
            self._enqueue("run", run_id, (run_id, self._now(), scenario, git_sha))
        except Exception:  # telemetry must never reach the run loop
            log.exception("persistence record failed")

    def record_event(
        self,
        run_id: str,
        event: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> None:
        """Queue one API event or canonical record.

        Canonical records (they carry `kind` and `event_id`) are stored under their own node,
        event id and emission time so a retry or an API restart is idempotent and per-node
        queries (Grafana, archipelago_storage.queries) see the real node, not "api". The
        request-level context (A7: commit, config_hash, seed, host, boot_id, episode) is stored
        in payload.context next to the record's own fields (phase, sim_tick, ...).
        """
        try:
            seq, kind = event["sequence"], str(event["type"])
            canonical = isinstance(event.get("kind"), str) and isinstance(
                event.get("event_id"), str
            )
            ts, node, eid = self._now(), NODE_ID, str(seq)
            if canonical:
                kind, node = str(event["kind"]), str(event.get("source_node_id") or SWARM)
                eid, ts = str(event["event_id"]), _parse_utc(event.get("emitted_at_utc"), ts)
            # deltas embed a full snapshot; keep rows small and store the headline fields only
            body = {k: v for k, v in event.items() if k not in ("snapshot", "context")}
            if kind == "world_snapshot":
                body.pop("obstacles", None)  # static map data, large and repeated every tick
            ctx = context if context is not None else event.get("context")
            if ctx:
                body["context"] = dict(ctx)
            self._enqueue("event", run_id, (ts, run_id, node, eid, kind, json.dumps(body)))
            if kind == "delta":
                tick = float(event["tick"])
                self._enqueue("metric", run_id, (ts, run_id, NODE_ID, "sim_tick", tick, "count"))
        except Exception:
            log.exception("persistence record failed")

    async def flush(self) -> bool:
        """Move spooled rows to the sink and write them in a worker thread. Never raises."""
        try:
            self._lock = self._lock or asyncio.Lock()
            async with self._lock:
                while self._pending:
                    self._sink.put(*self._pending.popleft())
                ok = await self._ensure_migrated() and await asyncio.to_thread(self._sink.flush)
        except Exception:
            log.exception("persistence flush crashed")
            ok = False
        if ok != self._healthy:
            self._healthy = ok
            if ok:
                log.info("TigerData recovered; dropped so far: %d", self.dropped)
            else:
                log.warning(
                    "TigerData write failed; spooling (queued=%d dropped=%d)",
                    self.queued,
                    self.dropped,
                )
        return ok

    async def _ensure_migrated(self) -> bool:
        if self._migrated:
            return True
        assert self._migrate is not None
        try:
            await asyncio.to_thread(self._migrate)
        except Exception:
            self.migration_failures += 1
            log.exception(
                "TigerData migration failed (attempt %d); will retry", self.migration_failures
            )
            return False
        self._migrated = True
        log.info("TigerData migrations applied")
        return True

    async def _run(self) -> None:
        assert self._stop is not None
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), self._interval)
            except TimeoutError:
                pass
            await self.flush()

    def start(self) -> None:
        if self._task is None:
            self._stop = asyncio.Event()
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self, timeout: float = 10.0) -> None:
        if self._task is None or self._stop is None:
            return
        self._stop.set()  # the loop does one last flush, then exits
        try:
            await asyncio.wait_for(self._task, timeout)
        except Exception:
            self._task.cancel()
            log.warning("persistence shutdown timed out; %d rows unwritten", self.queued)
        self._task = None

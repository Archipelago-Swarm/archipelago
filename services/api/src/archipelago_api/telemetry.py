"""Bounded, authenticated admission of canonical telemetry records.

Include make_router(manager) before serving requests. Its lifespan drains accepted
writes; the shared log adapter serializes simulator and telemetry writes off-loop.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from archipelago_contracts.models import Action, Id, LearningEvent, MetricSample, WorldSnapshot
from fastapi import APIRouter, HTTPException, Request
from pydantic import TypeAdapter, ValidationError

from .eventlog import EventLog
from .runs import Run, RunManager

MAX_BYTES = 256 * 1024
MAX_EVENTS = 500
_MODELS = {
    "action": Action,
    "learning_event": LearningEvent,
    "metric_sample": MetricSample,
    "world_snapshot": WorldSnapshot,
}
_ID = TypeAdapter(Id)
log = logging.getLogger("archipelago.telemetry")


class TelemetryIngest:
    """One instance per manager; capacity includes writes currently in progress."""

    def __init__(self, manager: RunManager, token: str, capacity: int = 2000) -> None:
        if len(token) < 16 or hmac.compare_digest(token.encode(), manager.s.api_token.encode()):
            raise ValueError("TELEMETRY_TOKEN must be separate from login and >=16 chars")
        if capacity < 1:
            raise ValueError("telemetry capacity must be positive")
        if isinstance(manager.log, _QueuedLog):
            raise ValueError("telemetry is already installed on this manager")
        self.manager, self._token, self.capacity = manager, token, capacity
        self.queue: asyncio.Queue[tuple[str, dict[str, Any], bool]] = asyncio.Queue(capacity)
        self.pending = 0
        self.dropped = 0
        self.accepting = True
        self._task: asyncio.Task[None] | None = None
        self._original_log = manager.log
        self.seen: set[tuple[str, str]] = {
            (rid, str(ev["event_id"]))
            for rid, run in manager.runs.items()
            for ev in run.events
            if "event_id" in ev
        }
        # Both paths must use the same writer or later simulation writes can overtake
        # telemetry on disk, and EventLog.load would discard the late lower sequence.
        manager.log = _QueuedLog(self)

    def restore_dedupe(self) -> None:
        """Recover all durable IDs, including events outside the in-memory replay tail."""
        for run_id in self.manager.runs:
            path = self._original_log.path(run_id)
            if not path.exists():
                continue
            try:
                with path.open(encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(event, dict) and isinstance(event.get("event_id"), str):
                            self.seen.add((run_id, event["event_id"]))
            except OSError:
                log.warning("telemetry dedupe recovery failed")

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._write())

    def enqueue(self, run_id: str, event: dict[str, Any], sync: bool = False) -> None:
        """Best effort for existing simulation events, matching EventLog's contract."""
        if not self.accepting or self.pending >= self.capacity:
            self.dropped += 1
            log.warning("event log queue full or closed; event dropped")
            return
        self.start()
        self.queue.put_nowait((run_id, event, sync))
        self.pending += 1

    async def _write(self) -> None:
        while True:
            run_id, event, sync = await self.queue.get()
            try:
                await asyncio.to_thread(self._original_log.append, run_id, event, sync)
            except Exception:
                # Never log payloads, authorization, or exception strings.
                self.dropped += 1
                log.warning("event log write failed")
            finally:
                self.pending -= 1
                self.queue.task_done()

    async def drain(self) -> None:
        await self.queue.join()

    async def stop(self, timeout: float = 5.0) -> None:
        self.accepting = False
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self.drain(), timeout)
        except TimeoutError:
            log.warning("telemetry shutdown timed out; pending=%d", self.pending)
        finally:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # A timed-out worker thread cannot be killed safely. Keep the adapter closed
        # so no new writer can interleave with the outstanding append.

    def authorize(self, request: Request) -> None:
        authorization = request.headers.get("authorization", "")
        candidate = authorization[7:] if authorization.startswith("Bearer ") else ""
        if not candidate or not hmac.compare_digest(candidate.encode(), self._token.encode()):
            raise HTTPException(401, "authentication required")

    def _event_id(self, item: Any) -> str | None:
        value = item.get("event_id") if isinstance(item, dict) else None
        if not isinstance(value, str):
            return None
        return "[redacted]" if self._token in value else value

    def admit(self, items: list[Any]) -> dict[str, Any]:
        accepted: list[tuple[Run, dict[str, Any]]] = []
        rejected: list[dict[str, Any]] = []
        duplicates = 0
        batch_seen: set[tuple[str, str]] = set()
        for item in items:
            event_id = self._event_id(item)
            if not isinstance(item, dict) or not isinstance(item.get("kind"), str):
                rejected.append({"event_id": event_id, "reason": "invalid record"})
                continue
            model = _MODELS.get(item["kind"])
            if model is None:
                rejected.append({"event_id": event_id, "reason": "unsupported record kind"})
                continue
            try:
                record = model.model_validate(item)
            except ValidationError:
                rejected.append({"event_id": event_id, "reason": "contract validation failed"})
                continue
            run = self.manager.runs.get(record.run_id)
            if run is None:
                rejected.append({"event_id": event_id, "reason": "unknown run id"})
                continue
            key = (record.run_id, record.event_id)
            if key in self.seen or key in batch_seen:
                duplicates += 1
                continue
            batch_seen.add(key)
            accepted.append((run, record.model_dump(mode="json")))
        if not self.accepting or self.pending + len(accepted) > self.capacity:
            raise HTTPException(503, "telemetry overloaded", headers={"Retry-After": "1"})
        # No await between preflight and mutation: atomic on the manager's event loop.
        for run, event in accepted:
            run.seq += 1
            event["source_sequence"] = event["sequence"]
            event["sequence"] = run.seq
            event["type"] = event["kind"]
            event["tick"] = event["sim_tick"]
            event["status"] = run.status
            run.events.append(event)
            while len(run.events) > self.manager.s.event_log_size:
                run.events.popleft()
            self.enqueue(run.config.run_id, event)
            self.seen.add((run.config.run_id, event["event_id"]))
            if self.manager.sink is not None:
                try:
                    # Persister.record_event only enqueues; database I/O is in its worker.
                    self.manager.sink.record_event(run.config.run_id, event)
                except Exception:
                    log.warning("telemetry persistence enqueue failed")
            for sub in run.subs:
                try:
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:
                    sub.lagged = True
                    while not sub.queue.empty():
                        sub.queue.get_nowait()
                    sub.queue.put_nowait(event)
        return {"accepted": len(accepted), "duplicates": duplicates, "rejected": rejected}


class _QueuedLog(EventLog):
    """EventLog-compatible adapter used by RunManager._emit and ingest alike."""

    def __init__(self, ingest: TelemetryIngest) -> None:
        self.ingest = ingest
        self.dir = ingest._original_log.dir

    def append(self, run_id: str, event: dict[str, Any], sync: bool = False) -> None:
        self.ingest.enqueue(run_id, event, sync)

    def load(self, run_id: str, keep: int) -> tuple[deque[dict[str, Any]], int]:
        return self.ingest._original_log.load(run_id, keep)


def make_router(
    manager: RunManager, *, token: str | None = None, capacity: int = 2000
) -> APIRouter:
    """Use TELEMETRY_TOKEN by default; fail closed for missing/short/shared tokens."""
    ingest = TelemetryIngest(
        manager, os.environ.get("TELEMETRY_TOKEN", "") if token is None else token, capacity
    )

    @asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[None]:
        await asyncio.to_thread(ingest.restore_dedupe)
        ingest.start()
        try:
            yield
        finally:
            # Nested router lifespans close before the parent app; preserve final status
            # events before closing the shared writer. RunManager.shutdown is idempotent.
            await manager.shutdown()
            await ingest.stop()

    router = APIRouter(lifespan=lifespan)

    @router.post("/v1/telemetry")
    async def telemetry(request: Request) -> dict[str, Any]:
        ingest.authorize(request)
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                raise HTTPException(400, "invalid content length") from None
            if size < 0:
                raise HTTPException(400, "invalid content length")
            if size > MAX_BYTES:
                raise HTTPException(413, "telemetry request too large")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BYTES:
                raise HTTPException(413, "telemetry request too large")
            body.extend(chunk)
        try:
            doc = json.loads(body, parse_constant=_bad_constant)
            if not isinstance(doc, dict) or set(doc) != {"source", "boot_id", "events"}:
                raise ValueError("invalid envelope")
            _ID.validate_python(doc["source"])
            _ID.validate_python(doc["boot_id"])
            if not isinstance(doc["events"], list):
                raise ValueError("invalid events")
        except (ValueError, UnicodeDecodeError, ValidationError, RecursionError):
            raise HTTPException(400, "malformed telemetry JSON or envelope") from None
        if len(doc["events"]) > MAX_EVENTS:
            raise HTTPException(413, "too many telemetry events")
        return ingest.admit(doc["events"])

    return router


def _bad_constant(_: str) -> Any:
    raise ValueError("non-finite JSON number")

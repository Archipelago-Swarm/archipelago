"""Persistent event spool: per-run JSONL, sequences continue across restarts."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from bisect import bisect_right
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from archipelago_contracts.models import SCHEMA_VERSION
from pydantic import BaseModel

_SAFE = re.compile(r"[A-Za-z0-9_-]")


def safe_name(run_id: str) -> str:
    """Filesystem-safe, injective encoding of a run id."""
    return "".join(c if _SAFE.fullmatch(c) else f"%{ord(c):02X}" for c in run_id)


FSYNC_INTERVAL_S = 1.0  # durability bound: at most this much wall time of events can be lost
DEFAULT_MAX_FILE_BYTES = 64 << 20  # per segment; a run keeps the live file plus one rotated one


class _RunLog:
    """In-memory window (at most ~keep + slack events, ascending by sequence) plus a bounded file.

    The JSONL is rotated when it exceeds `max_file_bytes`: `<run>.jsonl` becomes
    `<run>.jsonl.1` (replacing any older segment) and a new live file starts with the record
    being written, so the live file is never empty after a rotation and the sequence survives a
    restart. Disk use per run is therefore bounded by about 2 * max_file_bytes; older events are
    only retained by the API's own persistence.
    """

    def __init__(self, path: Path, keep: int, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> None:
        self.path = path
        self.keep, self.max_file_bytes = keep, max_file_bytes
        self.lock = threading.Lock()
        self.events: list[dict[str, Any]] = []
        self.last_sync = 0.0
        self.seq = 0
        self.dropped = 0
        self.outage = False
        self.fh: IO[str] | None = None
        self._load()

    def _load(self) -> None:
        for path in (self.path.with_name(self.path.name + ".1"), self.path):
            if not path.exists():
                continue
            with path.open("rb") as f:
                for raw in f:
                    try:
                        ev = json.loads(raw)
                    except ValueError:
                        continue  # torn write
                    if isinstance(ev, dict) and isinstance(ev.get("sequence"), int):
                        if ev["sequence"] > self.seq:
                            self.seq = ev["sequence"]
                            self.events.append(ev)
        self._trim(force=True)

    def _trim(self, force: bool = False) -> None:
        if len(self.events) > self.keep + (0 if force else max(1, self.keep // 10)):
            del self.events[: len(self.events) - self.keep]

    def _rotate(self) -> None:
        if self.fh is not None:
            self.fh.flush()
            os.fsync(self.fh.fileno())
            self.fh.close()
            self.fh = None
        os.replace(self.path, self.path.with_name(self.path.name + ".1"))

    def write(self, rec: dict[str, Any]) -> None:
        if self.path.exists() and self.path.stat().st_size >= self.max_file_bytes:
            self._rotate()
        if self.fh is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            needs_nl = self.path.exists() and self.path.stat().st_size > 0
            if needs_nl:
                with self.path.open("rb") as f:
                    f.seek(-1, os.SEEK_END)
                    needs_nl = f.read(1) != b"\n"
            self.fh = self.path.open("a", encoding="utf-8")
            if needs_nl:
                self.fh.write("\n")  # isolate a torn last line
        self.fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        self.fh.flush()
        now = time.monotonic()
        if now - self.last_sync >= FSYNC_INTERVAL_S:
            os.fsync(self.fh.fileno())
            self.last_sync = now

    def append(self, rec: dict[str, Any]) -> None:
        self.events.append(rec)
        self._trim()


class EventSpool:
    def __init__(
        self,
        root: Path,
        boot_id: str,
        keep: int = 100_000,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> None:
        self.root, self.boot_id, self.keep = root, boot_id, keep
        self.max_file_bytes = max_file_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        self._logs: dict[str, _RunLog] = {}
        self._lock = threading.Lock()

    def _path(self, run_id: str) -> Path:
        return self.root / f"{safe_name(run_id)}.jsonl"

    def known(self, run_id: str) -> bool:
        return run_id in self._logs or self._path(run_id).exists()

    def _log(self, run_id: str) -> _RunLog:
        with self._lock:
            lg = self._logs.get(run_id)
            if lg is None:
                lg = self._logs[run_id] = _RunLog(
                    self._path(run_id), self.keep, self.max_file_bytes
                )
            return lg

    def set_outage(self, run_id: str, on: bool) -> None:
        self._log(run_id).outage = on

    def dropped(self, run_id: str) -> int:
        return self._log(run_id).dropped

    def latest_sequence(self, run_id: str) -> int:
        return self._log(run_id).seq

    def emit(
        self,
        run_id: str,
        sim_tick: int,
        node: str | None,
        factory: Callable[[dict[str, Any]], BaseModel],
    ) -> dict[str, Any] | None:
        """Build a canonical record, assign the next sequence, persist. None if the sink is out."""
        lg = self._log(run_id)
        with lg.lock:
            if lg.outage:  # telemetry_outage test hook: only this sink drops
                lg.dropped += 1
                return None
            seq = lg.seq + 1
            base = {
                "schema_version": SCHEMA_VERSION,
                "event_id": f"{run_id}-{self.boot_id}-{seq}",
                "run_id": run_id,
                "source_node_id": node,
                "sim_tick": sim_tick,
                "emitted_at_utc": datetime.now(UTC),
                "sequence": seq,
            }
            rec = factory(base).model_dump(mode="json")
            lg.write(rec)
            lg.seq = seq
            lg.append(rec)
            return rec

    def page(self, run_id: str, after: int, limit: int) -> dict[str, Any] | None:
        if not self.known(run_id):
            return None
        lg = self._log(run_id)
        with lg.lock:
            start = bisect_right(lg.events, after, key=lambda e: e["sequence"])
            evs = lg.events[start : start + limit]
            return {
                "events": evs,
                "latest_sequence": lg.seq,
                "oldest_sequence": lg.events[0]["sequence"] if lg.events else 0,
            }

    def close(self) -> None:
        for lg in self._logs.values():
            with lg.lock:
                if lg.fh is not None:
                    lg.fh.flush()
                    os.fsync(lg.fh.fileno())
                    lg.fh.close()
                    lg.fh = None

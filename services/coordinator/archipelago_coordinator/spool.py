"""Persistent event spool: per-run JSONL, sequences continue across restarts."""

from __future__ import annotations

import json
import os
import re
import threading
from collections import deque
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


class _RunLog:
    def __init__(self, path: Path, keep: int) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.events: deque[dict[str, Any]] = deque(maxlen=keep)
        self.seq = 0
        self.dropped = 0
        self.outage = False
        self.fh: IO[str] | None = None
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("rb") as f:
            for raw in f:
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue  # torn write
                if isinstance(ev, dict) and isinstance(ev.get("sequence"), int):
                    if ev["sequence"] > self.seq:
                        self.seq = ev["sequence"]
                        self.events.append(ev)

    def write(self, rec: dict[str, Any]) -> None:
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


class EventSpool:
    def __init__(self, root: Path, boot_id: str, keep: int = 100_000) -> None:
        self.root, self.boot_id, self.keep = root, boot_id, keep
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
                lg = self._logs[run_id] = _RunLog(self._path(run_id), self.keep)
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
            lg.events.append(rec)
            return rec

    def page(self, run_id: str, after: int, limit: int) -> dict[str, Any] | None:
        if not self.known(run_id):
            return None
        lg = self._log(run_id)
        with lg.lock:
            evs = [e for e in lg.events if e["sequence"] > after][:limit]
            return {
                "events": evs,
                "latest_sequence": lg.seq,
                "oldest_sequence": lg.events[0]["sequence"] if lg.events else 0,
            }

    def close(self) -> None:
        for lg in self._logs.values():
            with lg.lock:
                if lg.fh is not None:
                    lg.fh.close()
                    lg.fh = None

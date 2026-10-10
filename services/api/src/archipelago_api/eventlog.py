"""Durable per-run event log: append-only JSON Lines, one file per run under the data dir."""

from __future__ import annotations

import json
import logging
import os
import re
from collections import deque
from pathlib import Path
from typing import Any

log = logging.getLogger("archipelago.eventlog")
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE = re.compile(r"[A-Za-z0-9_-]")


class InvalidRunId(ValueError):
    pass


class EventLog:
    def __init__(self, data_dir: Path) -> None:
        self.dir = data_dir / "events"

    def path(self, run_id: str) -> Path:
        """File for a run. Unsafe ids are rejected; every non-alphanumeric char is %-encoded."""
        if not isinstance(run_id, str) or not _ID.fullmatch(run_id):
            raise InvalidRunId(f"unsafe run id: {run_id!r}")
        name = "".join(c if _SAFE.fullmatch(c) else f"%{ord(c):02X}" for c in run_id)
        p = self.dir / f"{name}.jsonl"
        if p.resolve().parent != self.dir.resolve():  # defence in depth
            raise InvalidRunId(f"unsafe run id: {run_id!r}")
        return p

    def append(self, run_id: str, event: dict[str, Any], sync: bool = False) -> None:
        """Best effort: durability problems are logged, never raised into the simulation."""
        try:
            p = self.path(run_id)
            p.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(event, separators=(",", ":")) + "\n"
            with p.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                if sync:
                    try:
                        os.fsync(f.fileno())
                    except OSError:  # filesystems without fsync support
                        pass
        except (OSError, ValueError, TypeError) as e:
            log.warning("event not persisted for %r: %s", run_id, e)

    def load(self, run_id: str, keep: int) -> tuple[deque[dict[str, Any]], int]:
        """Return (last `keep` events, highest sequence ever stored).

        Invalid lines (torn write, garbage) and out-of-order sequences are ignored; if any were
        found the file is rewritten with only the good lines so later appends start clean.
        """
        events: deque[dict[str, Any]] = deque(maxlen=max(keep, 1))
        last = 0
        try:
            p = self.path(run_id)
            if not p.exists():
                return events, 0
            good: list[str] = []
            dirty = False
            with p.open("rb") as f:
                for raw in f:
                    ev = _parse(raw, last)
                    if ev is None:
                        dirty = True
                        continue
                    last = ev["sequence"]
                    events.append(ev)
                    good.append(raw.decode("utf-8").rstrip("\n"))
            if dirty:
                tmp = p.with_suffix(".tmp")
                tmp.write_text("".join(g + "\n" for g in good), encoding="utf-8")
                os.replace(tmp, p)
        except (OSError, ValueError) as e:
            log.warning("event log unreadable for %r: %s", run_id, e)
        return events, last


def _parse(raw: bytes, last: int) -> dict[str, Any] | None:
    if not raw.endswith(b"\n"):  # torn final write
        return None
    try:
        ev = json.loads(raw)
    except ValueError:
        return None
    seq = ev.get("sequence") if isinstance(ev, dict) else None
    if not isinstance(seq, int) or isinstance(seq, bool) or seq <= last:
        return None
    return ev  # type: ignore[no-any-return]

"""Bounded durable telemetry spool and background shipper (live-runtime.md section 8). Stdlib only.

Spool layout (own volume): seg-<first_index>.jsonl files of one JSON line per record, plus
state.json {shipped, dropped, max_sequence}. Records have a spool-global index; ``shipped`` is the
count of leading indexes already acknowledged by the sink. When retained records exceed the cap the
oldest segment is deleted and its unshipped records are added to ``dropped``. Appends are flushed
to the OS (survives a process kill); fsync happens on ``sync()`` (checkpoints, shutdown).
The sink is idempotent by ``event_id``; after a crash between POST and state write a batch is
re-sent, never lost.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

_SEG = re.compile(r"^seg-(\d+)\.jsonl$")


class Spool:
    def __init__(self, directory, max_records: int = 20000, seg_records: int = 500):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.max_records = max(1, max_records)
        self.seg_records = max(1, min(seg_records, self.max_records))
        self._lock = threading.Lock()
        self._segs: list[list[int]] = []  # [first_index, count], ascending
        self._fh = None
        self.shipped = 0
        self.dropped = 0
        self.max_sequence = -1
        self._load()

    # --- recovery --------------------------------------------------------------------------
    def _load(self) -> None:
        try:
            st = json.loads((self.dir / "state.json").read_bytes())
            self.shipped, self.dropped = int(st["shipped"]), int(st["dropped"])
            self.max_sequence = int(st.get("max_sequence", -1))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        starts = sorted(int(m.group(1)) for p in self.dir.iterdir() if (m := _SEG.match(p.name)))
        for s in starts:
            path = self._path(s)
            good = 0
            keep = 0
            with open(path, "rb") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        break  # torn tail from a kill mid-append: truncate below
                    if not line.endswith(b"\n"):
                        break
                    good += 1
                    keep += len(line)
                    self.max_sequence = max(self.max_sequence, rec["record"].get("sequence", -1))
            if keep != path.stat().st_size:
                with open(path, "r+b") as f:
                    f.truncate(keep)
            if good:
                self._segs.append([s, good])
            else:
                path.unlink(missing_ok=True)
        self.next_index = self._segs[-1][0] + self._segs[-1][1] if self._segs else self.shipped
        self.shipped = min(
            max(self.shipped, self._segs[0][0] if self._segs else 0), self.next_index
        )

    def _path(self, start: int) -> Path:
        return self.dir / f"seg-{start}.jsonl"

    # --- write side ------------------------------------------------------------------------
    def append(self, line: dict) -> None:
        data = (json.dumps(line, separators=(",", ":"), allow_nan=False) + "\n").encode()
        with self._lock:
            if not self._segs or self._segs[-1][1] >= self.seg_records:
                self._close_fh()
                self._segs.append([self.next_index, 0])
            seg = self._segs[-1]
            if self._fh is None:
                self._fh = open(self._path(seg[0]), "ab")
            self._fh.write(data)
            self._fh.flush()
            seg[1] += 1
            self.next_index += 1
            self.max_sequence = max(self.max_sequence, line["record"].get("sequence", -1))
            self._enforce_cap()

    def _enforce_cap(self) -> None:
        while self.next_index - self._segs[0][0] > self.max_records and len(self._segs) > 1:
            first, count = self._segs.pop(0)
            self._path(first).unlink(missing_ok=True)
            end = first + count
            if self.shipped < end:
                self.dropped += end - max(self.shipped, first)
                self.shipped = end

    def _close_fh(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def sync(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.flush()
                os.fsync(self._fh.fileno())
            self._write_state()

    def close(self) -> None:
        with self._lock:
            self._close_fh()
            self._write_state()

    def _write_state(self) -> None:
        tmp = self.dir / "state.json.tmp"
        body = json.dumps(
            {"shipped": self.shipped, "dropped": self.dropped, "max_sequence": self.max_sequence}
        ).encode()
        with open(tmp, "wb") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.dir / "state.json")

    # --- read side -------------------------------------------------------------------------
    @property
    def backlog(self) -> int:
        with self._lock:
            return self.next_index - self.shipped

    def state(self) -> dict:
        with self._lock:
            return {
                "shipped": self.shipped,
                "next_index": self.next_index,
                "dropped": self.dropped,
                "max_sequence": self.max_sequence,
            }

    def peek(self, n: int) -> tuple[list[dict], int]:
        """Up to n oldest unshipped records and the ``shipped`` value to commit after the POST."""
        out: list[dict] = []
        with self._lock:
            idx = self.shipped
            for first, count in self._segs:
                if first + count <= idx:
                    continue
                if self._fh is not None:
                    self._fh.flush()
                with open(self._path(first), "rb") as f:
                    for i, line in enumerate(f):
                        if first + i < idx:
                            continue
                        out.append(json.loads(line))
                        idx += 1
                        if len(out) >= n:
                            return out, idx
        return out, idx

    def commit(self, shipped: int) -> None:
        with self._lock:
            if shipped <= self.shipped:
                return
            self.shipped = min(shipped, self.next_index)
            while len(self._segs) > 1 and self._segs[0][0] + self._segs[0][1] <= self.shipped:
                self._path(self._segs.pop(0)[0]).unlink(missing_ok=True)
            self._write_state()


class Shipper(threading.Thread):
    """Background batch POSTer. Failures back off; nothing here is awaited by act/feedback."""

    # 4xx verdicts that mean "this batch will never be accepted" (everything else is retried)
    POISON = frozenset({400, 413, 422})

    def __init__(
        self, spool: Spool, url: str, meta: dict, token=None, batch=200, interval=0.5, timeout=2.0
    ):
        super().__init__(name="telemetry-shipper", daemon=True)
        self.spool, self.url, self.meta, self.token = spool, url, meta, token
        self.batch, self.interval, self.timeout = batch, interval, timeout
        self._stop_evt = threading.Event()
        self.stats = {"batches_ok": 0, "batches_failed": 0, "records_shipped": 0, "poison": 0}
        self.last_error: str | None = None

    def post(self, records: list[dict]) -> int:
        body = json.dumps({**self.meta, "records": records}).encode()
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.url, body, headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except (OSError, ValueError) as e:
            self.last_error = repr(e)
            return 0

    def ship_once(self) -> bool:
        recs, upto = self.spool.peek(self.batch)
        if not recs:
            return False
        status = self.post(recs)
        if 200 <= status < 300:
            self.spool.commit(upto)
            self.stats["batches_ok"] += 1
            self.stats["records_shipped"] += len(recs)
            return True
        if status in self.POISON:
            self.stats["poison"] += len(recs)
            self.spool.commit(upto)  # unprocessable batch: skipped and counted, not retried
            return True
        self.stats["batches_failed"] += 1
        raise ConnectionError(f"sink status {status}")

    def run(self) -> None:
        backoff = 0.0
        while not self._stop_evt.is_set():
            try:
                busy = self.ship_once()
                backoff = 0.0
                if busy and self.spool.backlog > 0:
                    continue  # more to send right away
                self._stop_evt.wait(self.interval)
            except ConnectionError:
                backoff = min(5.0, max(0.2, backoff * 2))
                self._stop_evt.wait(backoff)

    def stop(self) -> None:
        self._stop_evt.set()

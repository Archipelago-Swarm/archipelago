"""In-memory peer transport with directed link gates and seeded faults (T05 slice 1-4, memory only)."""
from __future__ import annotations

import hashlib
import random
from collections import deque
from dataclasses import dataclass, field

VERSION = 1
MAX_PAYLOAD = 64 * 1024
MAX_QUEUE = 32


@dataclass(frozen=True)
class Envelope:
    src: str
    dst: str
    seq: int  # per-source monotonically increasing model version
    payload: bytes
    version: int = VERSION
    digest: str = ""

    @staticmethod
    def make(src: str, dst: str, seq: int, payload: bytes) -> "Envelope":
        return Envelope(src, dst, seq, payload, VERSION, hashlib.sha256(payload).hexdigest())


@dataclass
class Stats:
    sent_bytes: int = 0
    dropped_bytes: int = 0
    received_bytes: int = 0
    rejected: dict = field(default_factory=dict)


class Network:
    """Deterministic memory network. links: set of allowed directed (src, dst) pairs.

    Delivery is by tick(); send() never blocks, so acting is unaffected by partitions.
    Telemetry is not routed here (separate channel).
    """

    def __init__(self, links, seed: int = 0, loss: float = 0.0, delay: int = 0, bandwidth: int | None = None):
        self.links = set(links)
        self.rng = random.Random(seed)
        self.loss, self.delay, self.bandwidth = loss, delay, bandwidth
        self.now = 0
        self.stats = Stats()
        self.inbox: dict[str, deque] = {}  # learning consumer queue per node, bounded
        self._flight: list[tuple[int, Envelope]] = []
        self._seen: dict[tuple[str, str], int] = {}  # (dst, src) -> latest accepted seq
        self._latest: dict[str, Envelope] = {}  # src -> newest sent, for catch-up

    def _reject(self, why: str, n: int):
        self.stats.rejected[why] = self.stats.rejected.get(why, 0) + 1
        self.stats.dropped_bytes += n

    def set_links(self, links):
        """Change the partition; newly opened links trigger a bounded catch-up (latest only)."""
        opened = set(links) - self.links
        self.links = set(links)
        for src, dst in sorted(opened):
            if src in self._latest:
                self.send(Envelope.make(src, dst, self._latest[src].seq, self._latest[src].payload))

    def send(self, env: Envelope) -> bool:
        n = len(env.payload)
        if env.src not in self._latest or env.seq >= self._latest[env.src].seq:
            self._latest[env.src] = env
        if (env.src, env.dst) not in self.links:
            self._reject("cut", n)
            return False
        if n > MAX_PAYLOAD:
            self._reject("oversized", n)
            return False
        if self.rng.random() < self.loss:
            self._reject("lost", n)
            return False
        self.stats.sent_bytes += n
        self._flight.append((self.now + self.delay, env))
        return True

    def tick(self):
        self.now += 1
        due = [e for t, e in self._flight if t <= self.now]
        self._flight = [(t, e) for t, e in self._flight if t > self.now]
        budget = self.bandwidth
        for e in due:
            n = len(e.payload)
            if budget is not None:
                if n > budget:
                    self._flight.append((self.now + 1, e))  # defer to next tick
                    continue
                budget -= n
            self._deliver(e)

    def _deliver(self, e: Envelope):
        n = len(e.payload)
        if (e.src, e.dst) not in self.links:  # link cut while in flight
            return self._reject("cut", n)
        if e.version != VERSION:
            return self._reject("version", n)
        if hashlib.sha256(e.payload).hexdigest() != e.digest:
            return self._reject("hash", n)
        if e.seq <= self._seen.get((e.dst, e.src), -1):
            return self._reject("duplicate_or_stale", n)
        q = self.inbox.setdefault(e.dst, deque())
        if len(q) >= MAX_QUEUE:
            q.popleft()  # drop oldest, keep newest
            self._reject("queue_full", 0)
        self._seen[(e.dst, e.src)] = e.seq
        q.append(e)
        self.stats.received_bytes += n

    def receive(self, node: str):
        q = self.inbox.get(node)
        return q.popleft() if q else None

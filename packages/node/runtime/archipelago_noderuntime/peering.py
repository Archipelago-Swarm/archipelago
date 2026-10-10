"""Peer fault schedule and the receive-side gate over archipelago_peer.PeerServer."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable

from archipelago_contracts.models import FaultWindow
from archipelago_peer import PeerServer


class Schedule:
    """Immutable peer fault schedule. A window is active for start_tick <= tick < end_tick.

    Each listed pair cuts the link in both directions (a partition is symmetric).
    """

    def __init__(self, windows: Iterable[FaultWindow] = ()):
        self.windows = tuple(
            (w.start_tick, w.end_tick, frozenset(frozenset(p) for p in w.cut_links))
            for w in windows
        )

    def cut(self, a: str, b: str, tick: int) -> bool:
        pair = frozenset((a, b))
        return any(s <= tick < e and pair in cut for s, e, cut in self.windows)

    def as_json(self) -> list[dict]:
        return [
            {"start_tick": s, "end_tick": e, "cut_links": sorted(sorted(p) for p in cut)}
            for s, e, cut in self.windows
        ]

    @classmethod
    def from_json(cls, data: list[dict]) -> Schedule:
        return cls(FaultWindow.model_validate(w) for w in data)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.as_json(), sort_keys=True).encode()).hexdigest()


class GatedPeerServer(PeerServer):
    """PeerServer whose receive side refuses envelopes on links the node's own schedule cuts."""

    def __init__(self, *args, gate: Callable[[str], bool], on_cut: Callable[[str], None], **kw):
        self.gate, self.on_cut = gate, on_cut  # must exist before the server thread starts
        super().__init__(*args, **kw)

    def accept(self, env) -> int:
        if self.gate(env.src):
            self.on_cut(env.src)
            return 403
        return super().accept(env)

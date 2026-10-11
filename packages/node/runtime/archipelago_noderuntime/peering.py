"""Peer fault schedule and the receive-side gate over archipelago_peer.PeerServer."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable

from archipelago_contracts.models import FaultWindow
from archipelago_peer import PeerServer
from archipelago_transport import Envelope

from .summary import is_summary


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
    """PeerServer whose receive side refuses envelopes on links the node's own schedule cuts.

    Two message classes share the authenticated envelope path (bearer token and ``allowed_src``
    are enforced by PeerServer before ``accept``): model offers (npz payloads, queued for the
    exchange window) and non-model information messages (JSON payloads, A18). Information
    messages never enter the model inbox; ``on_info(env) -> status`` handles them. Both classes
    pass the same cut gate first.
    """

    def __init__(
        self,
        *args,
        gate: Callable[[str], bool],
        on_cut: Callable[[str], None],
        on_info: Callable[[Envelope], int] | None = None,
        on_info_cut: Callable[[str], None] | None = None,
        **kw,
    ):
        # must exist before the server thread starts
        self.gate, self.on_cut = gate, on_cut
        self.on_info, self.on_info_cut = on_info, on_info_cut
        super().__init__(*args, **kw)

    def accept(self, env) -> int:
        info = is_summary(env.payload)
        if self.gate(env.src):
            cb = self.on_info_cut if info and self.on_info_cut else self.on_cut
            cb(env.src)
            return 403
        if info:
            return self.on_info(env) if self.on_info is not None else 404
        return super().accept(env)

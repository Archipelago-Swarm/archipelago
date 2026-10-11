"""RF-gated message layer: the ONLY channel between nodes.

``Network`` (simulator bookkeeping) recomputes the RF link table from node positions + terrain each
tick and emits RF_LINK_* events on state changes. Nodes never see it: each gets a ``NetPort``
exposing only (a) its direct neighbours (links not DOWN) with their link quality, (b) ``send`` that
is refused unless the link to that neighbour allows the message kind, (c) its own inbox.

Gating by link state:
    UP        everything (summaries, adverts, requests, acks, artifact chunks)
    DEGRADED  small messages only (summary, advert, request, ack); NO artifact chunks
    DOWN      nothing
There is no multi-hop routing: a skill crosses several hops only by being installed (and then
advertised) by each intermediate node. Messages sent in tick t arrive in tick t+1.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from . import rf
from .store import Store

ALLOWED = {
    "PEER_SUMMARY": {rf.UP, rf.DEGRADED},
    "SKILL_ADVERT": {rf.UP, rf.DEGRADED},
    "SKILL_REQUEST": {rf.UP, rf.DEGRADED},
    "SKILL_ACK": {rf.UP, rf.DEGRADED},
    "SKILL_CHUNK": {rf.UP},
}
EVENT_DEBOUNCE_TICKS = 5  # a state must persist this long to be announced (links table is instant)
EVENT_FOR_STATE = {rf.UP: "RF_LINK_UP", rf.DEGRADED: "RF_LINK_DEGRADED", rf.DOWN: "RF_LINK_DOWN"}


class NetPort:
    def __init__(self, net: Network, node_id: str):
        self._net, self.node_id = net, node_id

    def neighbors(self) -> dict[str, dict]:
        """Directly reachable peers only: {peer: {state, quality, bandwidth_kbps, distance_m}}."""
        return self._net.neighbors_of(self.node_id)

    def send(self, dst: str, msg: dict) -> bool:
        return self._net.deliver(self.node_id, dst, msg)

    def budget_bytes(self, dst: str) -> int:
        """Artifact bytes this link can carry this tick (0 unless the link is UP)."""
        return self._net.budget(self.node_id, dst)

    def recv(self) -> list[dict]:
        return self._net.drain(self.node_id)


class Network:
    def __init__(self, store: Store, rf_cfg: rf.RFConfig | None = None, dt_s: float = 0.1):
        self.store, self.cfg, self.dt = store, rf_cfg or rf.RFConfig(), dt_s
        self.links: dict[tuple[str, str], rf.Link] = {}
        self._state: dict[tuple[str, str], str] = {}  # last state seen (drives hysteresis)
        self._emitted: dict[tuple[str, str], str] = {}  # last state announced as an event
        self._since: dict[tuple[str, str], int] = {}
        self._staged: dict[str, list[dict]] = defaultdict(list)
        self._inbox: dict[str, list[dict]] = defaultdict(list)
        self.tick = 0
        self.stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def update(self, tick: int, terrain, positions: dict[str, tuple[int, int]]) -> None:
        self.tick = tick
        for k, msgs in self._staged.items():
            self._inbox[k].extend(msgs)
        self._staged = defaultdict(list)
        for a, b in combinations(sorted(positions), 2):
            old = self._state.get((a, b), rf.DOWN)
            lk = rf.with_hysteresis(
                rf.link(terrain, a, positions[a], b, positions[b], self.cfg), old, self.cfg
            )
            self.links[(a, b)] = lk
            self._state[(a, b)] = lk.state
            if lk.state == self._emitted.get((a, b), rf.DOWN):
                self._since.pop((a, b), None)
            elif tick - self._since.setdefault((a, b), tick) >= EVENT_DEBOUNCE_TICKS:
                self._since.pop((a, b))
                old = self._emitted.get((a, b), rf.DOWN)
                self._emitted[(a, b)] = lk.state
                self.store.emit(
                    EVENT_FOR_STATE[lk.state],
                    tick,
                    None,
                    node_a=a,
                    node_b=b,
                    previous=old,
                    **{
                        k: lk.as_dict()[k]
                        for k in (
                            "distance_m",
                            "terrain_los",
                            "obstruction_db",
                            "margin_db",
                            "link_quality",
                            "bandwidth_kbps",
                        )
                    },
                )

    def link_of(self, a: str, b: str) -> rf.Link | None:
        return self.links.get(rf.sorted_pair(a, b))

    def port(self, node_id: str) -> NetPort:
        return NetPort(self, node_id)

    def neighbors_of(self, node_id: str) -> dict[str, dict]:
        out = {}
        for (a, b), lk in self.links.items():
            if lk.state != rf.DOWN and node_id in (a, b):
                out[b if a == node_id else a] = {
                    "state": lk.state,
                    "quality": lk.link_quality,
                    "bandwidth_kbps": lk.bandwidth_kbps,
                    "distance_m": lk.distance_m,
                }
        return out

    def deliver(self, src: str, dst: str, msg: dict) -> bool:
        lk = self.link_of(src, dst)
        kind = msg["kind"]
        ok = lk is not None and lk.state in ALLOWED[kind]
        self.stats[src][f"{kind}_{'sent' if ok else 'blocked'}"] += 1
        if ok:
            self._staged[dst].append({**msg, "src": src})
        return ok

    def budget(self, src: str, dst: str) -> int:
        lk = self.link_of(src, dst)
        if lk is None or lk.state != rf.UP:
            return 0
        return int(lk.bandwidth_kbps * 1000 / 8 * self.dt)

    def drain(self, node_id: str) -> list[dict]:
        msgs, self._inbox[node_id] = self._inbox[node_id], []
        return msgs

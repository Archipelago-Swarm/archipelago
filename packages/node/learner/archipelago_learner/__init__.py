"""Node wrapper: ships Learner candidates over the T05 transport and emits contract events."""

from __future__ import annotations

from datetime import UTC, datetime

from archipelago_contracts import SCHEMA_VERSION
from archipelago_contracts.models import LearningEvent
from archipelago_learning import OfferWindow, encode, offer
from archipelago_transport import Envelope


class LearnerNode:
    def __init__(self, learner, net, run_id="run-0", peers=()):
        self.learner, self.net, self.run_id, self.peers = learner, net, run_id, tuple(peers)
        self.records: list[LearningEvent] = []
        self._emitted = 0  # index into learner.events

    def broadcast(self, keep=1.0):
        """Non-blocking send of the current policy (a delta if learner.base_params is set); cut
        links just count as dropped."""
        payload = encode(self.learner, keep)
        for p in self.peers:
            self.net.send(Envelope.make(self.learner.node_id, p, self.learner.version, payload))

    def poll(self, eval_fn, margin=0.0, alpha=None, window=None, safety_fn=None, max_drop=None):
        """Offer every delivered candidate, in arrival order, as ONE exchange window (A1): at most
        one is accepted, the rest are rejected as ``window_limit`` without validation cost."""
        window = OfferWindow() if window is None else window
        while (env := self.net.receive(self.learner.node_id)) is not None:
            offer(
                self.learner,
                env.payload,
                eval_fn,
                margin,
                alpha,
                env.src,
                window,
                safety_fn,
                max_drop,
            )
        return window

    def flush(self, tick=0):
        """Convert new learner events to contract LearningEvent records."""
        L = self.learner
        for ev in L.events[self._emitted :]:
            self._emitted += 1
            self.records.append(self._record(ev, tick, self._emitted - 1))
        return self.records

    def _record(self, ev, tick, seq):
        t = ev["type"]
        base = {
            "schema_version": SCHEMA_VERSION,
            "event_id": f"{self.learner.node_id}-{seq}",
            "run_id": self.run_id,
            "source_node_id": self.learner.node_id,
            "sim_tick": tick,
            "emitted_at_utc": datetime.now(UTC),
            "sequence": seq,
        }
        if t == "local_update":
            f = dict(update_count=ev["step"], loss=ev["loss"], previous_version=ev["version"] - 1)
            f.update(new_version=ev["version"], transfer="none")
        elif t == "peer_offer":
            ok = ev["accepted"]
            # Source/hash are not contract fields; they ride in `reason` for accepted candidates.
            reason = (
                f"source={ev['source']} v={ev['source_version']} sha256={ev['payload_sha256']}"
                if ok
                else ev["reason"]
            )
            f = dict(update_count=self.learner.steps, loss=None, bytes=ev["bytes"], reason=reason)
            f.update(
                previous_version=ev["local_version"], candidate_score=ev.get("candidate_score")
            )
            f.update(new_version=ev["new_version"] if ok else ev["local_version"])
            lin = ev.get("lineage") or {}
            f.update(policy_id=lin.get("policy_id"), parent_ids=lin.get("parent_ids", []))
            f.update(origin_node=lin.get("origin_node"), flagged_peer=ev.get("flagged"))
            f.update(generation_count=lin.get("generation_count", 0))
            f.update(transfer="accepted" if ok else "rejected")
        else:  # rollback
            f = dict(update_count=self.learner.steps, loss=None, reason="rollback")
            f.update(previous_version=ev["version"] - 1, new_version=ev["version"], transfer="none")
        return LearningEvent(**base, **f)


__all__ = ["LearnerNode"]

"""Peer candidate exchange: tensor-only payloads, validation, measured accept/reject, rollback."""

from __future__ import annotations

import hashlib
import io
import json

import numpy as np

MAX_BYTES = 1 << 20
KEYS = ("w1", "b1", "w2", "b2")


class PeerError(ValueError):
    pass


def encode(learner) -> bytes:
    meta = {
        "encoder": learner.encoder,
        "obs_dim": learner.obs_dim,
        "hidden": learner.hidden,
        "n_actions": learner.n_actions,
        "node": learner.node_id,
        "version": learner.version,
    }
    buf = io.BytesIO()
    np.savez(buf, _meta=np.frombuffer(json.dumps(meta).encode(), np.uint8), **learner.params)
    return buf.getvalue()


def decode(payload: bytes, learner):
    """Return (meta, tensors) or raise PeerError. Never unpickles; checks shape/dtype/finite."""
    if len(payload) > MAX_BYTES:
        raise PeerError("payload too large")
    try:
        z = np.load(io.BytesIO(payload), allow_pickle=False)
        meta = json.loads(bytes(z["_meta"]))
        tensors = {k: z[k] for k in KEYS}
    except Exception as e:
        raise PeerError(f"malformed payload: {e}") from e
    for f in ("encoder", "obs_dim", "hidden", "n_actions"):
        if meta.get(f) != getattr(learner, f):
            raise PeerError(f"incompatible {f}: {meta.get(f)!r}")
    for k, t in tensors.items():
        if t.dtype != np.float32 or t.shape != learner.params[k].shape:
            raise PeerError(f"bad tensor {k}: {t.dtype} {t.shape}")
        if not np.isfinite(t).all():
            raise PeerError(f"nonfinite tensor {k}")
    return meta, tensors


def offer(learner, payload: bytes, eval_fn, margin=0.0, alpha=None):
    """Accept the candidate only if eval_fn(params) beats the current policy by > margin.

    alpha (mixing mode only, <=0.5) blends instead of replacing. Returns the logged event.
    """
    ev = {
        "type": "peer_offer",
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "local_version": learner.version,
    }
    try:
        if learner.mode == "information_only":
            raise PeerError("information_only mode never loads parameters")
        meta, cand = decode(payload, learner)
        ev.update(source=meta.get("node"), source_version=meta.get("version"))
        if alpha is not None:
            if learner.mode != "mixing" or not 0 < alpha <= 0.5:
                raise PeerError("mixing needs mode=mixing and 0<alpha<=0.5")
            cand = {
                k: ((1 - alpha) * learner.params[k] + alpha * cand[k]).astype(np.float32)
                for k in KEYS
            }
        cur, new = eval_fn(learner.params), eval_fn(cand)
        ev.update(current_score=cur, candidate_score=new)
        if not new > cur + margin:
            raise PeerError("candidate not better than current policy")
    except PeerError as e:
        ev.update(accepted=False, reason=str(e))
    else:
        learner.previous = {k: v.copy() for k, v in learner.params.items()}
        learner.params = {k: cand[k].copy() for k in KEYS}
        learner.target = {k: v.copy() for k, v in learner.params.items()}
        learner._reset_optimizer()  # peer optimizer state is never imported; stale moments dropped
        learner.version += 1
        ev.update(accepted=True, new_version=learner.version)
    learner.events.append(ev)
    return ev


def rollback(learner):
    if learner.previous is None:
        return False
    learner.params, learner.previous = learner.previous, None
    learner.target = {k: v.copy() for k, v in learner.params.items()}
    learner._reset_optimizer()
    learner.version += 1
    learner.events.append({"type": "rollback", "version": learner.version})
    return True

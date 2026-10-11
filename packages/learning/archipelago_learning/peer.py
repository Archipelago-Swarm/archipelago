"""Peer candidate exchange: tensor-only payloads, validation, measured accept/reject, rollback.

Works for any learner exposing the duck-typed interface used by both backends:
params_numpy() / load_params_numpy() (param-map-v1), sync_target(), _reset_optimizer(), plus
the attributes version, mode, events, previous and the compatibility header fields
(encoder, encoder_sha256, obs_dim, hidden, n_actions, reward_id, action_space, backend, node_id).

Payload versioning (explicit choice): payloads carry ``format = "archipelago-peer-v2"`` and the
header fields param_map/backend/reward_id/action_space/encoder_sha256 (and, recorded but not
matched, learner_schedule: a network trained under another recipe is still a valid candidate).
Payloads produced by the pre-T26 encoder have no ``format`` and are REJECTED ("incompatible
format"): they cannot prove encoder/reward/action-space identity, and no persisted payloads
exist. ``backend`` is recorded for evidence but is not a compatibility criterion (NumPy <-> Torch
exchange is the point).
"""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile

import numpy as np

from .compat import KEYS, PARAM_MAP, param_shapes

MAX_BYTES = 1 << 20
FORMAT = "archipelago-peer-v2"
# Header fields that must equal the receiver's; checked in this order, first mismatch named.
_MUST_MATCH = (
    "param_map",
    "encoder",
    "encoder_sha256",
    "obs_dim",
    "hidden",
    "n_actions",
    "reward_id",
    "action_space",
)


class PeerError(ValueError):
    pass


def _expected(learner, field):
    return PARAM_MAP if field == "param_map" else getattr(learner, field)


def encode(learner) -> bytes:
    meta = {
        "format": FORMAT,
        "param_map": PARAM_MAP,
        "backend": learner.backend,
        "encoder": learner.encoder,
        "encoder_sha256": learner.encoder_sha256,
        "reward_id": learner.reward_id,
        "action_space": learner.action_space,
        "obs_dim": learner.obs_dim,
        "hidden": learner.hidden,
        "n_actions": learner.n_actions,
        "learner_schedule": getattr(learner, "schedule_id", "sched-v0"),  # recorded, not matched
        "node": learner.node_id,
        "version": learner.version,
    }
    buf = io.BytesIO()
    np.savez(
        buf, _meta=np.frombuffer(json.dumps(meta).encode(), np.uint8), **learner.params_numpy()
    )
    return buf.getvalue()


def decode(payload: bytes, learner):
    """Return (meta, tensors) or raise PeerError. Never unpickles; checks shape/dtype/finite."""
    if len(payload) > MAX_BYTES:
        raise PeerError("payload too large")
    try:
        # Bound inflated size from zip headers before any member is materialised.
        if sum(i.file_size for i in zipfile.ZipFile(io.BytesIO(payload)).infolist()) > MAX_BYTES:
            raise ValueError("payload inflates too large")
        z = np.load(io.BytesIO(payload), allow_pickle=False)
        if set(z.files) != {"_meta", *KEYS}:
            raise ValueError(f"unexpected members {sorted(z.files)}")
        raw = z["_meta"]
        if raw.dtype != np.uint8 or raw.ndim != 1:
            raise ValueError("meta is not a uint8 vector")
        meta = json.loads(bytes(raw))
        if not isinstance(meta, dict):
            raise ValueError("meta is not an object")
        tensors = {k: z[k] for k in KEYS}
    except Exception as e:
        raise PeerError(f"malformed payload: {e}") from e
    if meta.get("format") != FORMAT:
        raise PeerError(f"incompatible format: {meta.get('format')!r}")
    for f in _MUST_MATCH:
        if meta.get(f) != _expected(learner, f):
            raise PeerError(f"incompatible {f}: {meta.get(f)!r}")
    shapes = param_shapes(learner.obs_dim, learner.hidden, learner.n_actions)
    for k, t in tensors.items():
        if t.dtype != np.float32 or t.shape != shapes[k]:
            raise PeerError(f"bad tensor {k}: {t.dtype} {t.shape}")
        if not np.isfinite(t).all():
            raise PeerError(f"nonfinite tensor {k}")
    return meta, tensors


class OfferWindow:
    """One exchange window (A1): at most one acceptance; candidates after it are not evaluated.

    Also memoises the current-policy score (keyed on learner.version) so it is evaluated at most
    once per window; ``evaluations`` counts every eval_fn call made through this window.
    """

    def __init__(self):
        self.accepted = 0
        self.evaluations = 0
        self.offers = 0
        self._cur: tuple[int, float] | None = None

    def current_score(self, learner, eval_fn, own):
        if self._cur is None or self._cur[0] != learner.version:
            self.evaluations += 1
            self._cur = (learner.version, eval_fn(own))
        return self._cur[1]

    def candidate_score(self, eval_fn, cand):
        self.evaluations += 1
        return eval_fn(cand)


WINDOW_LIMIT = "window_limit"


def offer(learner, payload: bytes, eval_fn, margin=0.0, alpha=None, sender=None, window=None):
    """Accept the candidate only if eval_fn(params) beats the current policy by > margin.

    eval_fn receives a param-map-v1 dict of float32 NumPy arrays.
    alpha (mixing mode only, <=0.5) blends instead of replacing; mixing mode requires it.
    sender (transport source), if given, must match the node id the payload claims.
    window (OfferWindow, optional): after the window's first acceptance every further candidate is
    rejected with reason "window_limit" before decoding or evaluation (no validation cost).
    Returns the logged event.
    """
    ev = {
        "type": "peer_offer",
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "local_version": learner.version,
        "pre_version": learner.version,
        "bytes": len(payload),
        "margin_required": margin,
    }
    try:
        if window is not None:
            window.offers += 1
            if window.accepted:
                raise PeerError(WINDOW_LIMIT)
        if learner.mode == "information_only":
            raise PeerError("information_only mode never loads parameters")
        meta, cand = decode(payload, learner)
        ev.update(
            source=meta.get("node"),
            source_version=meta.get("version"),
            source_backend=meta.get("backend"),
        )
        if sender is not None and meta.get("node") != sender:
            raise PeerError(f"claimed node {meta.get('node')!r} != sender {sender!r}")
        if learner.mode == "mixing" and alpha is None:
            raise PeerError("mixing mode needs 0<alpha<=0.5")
        own = learner.params_numpy()
        if alpha is not None:
            if learner.mode != "mixing" or not 0 < alpha <= 0.5:
                raise PeerError("mixing needs mode=mixing and 0<alpha<=0.5")
            cand = {k: ((1 - alpha) * own[k] + alpha * cand[k]).astype(np.float32) for k in KEYS}
        t0 = time.perf_counter()
        if window is None:
            cur, new = eval_fn(own), eval_fn(cand)
        else:
            cur = window.current_score(learner, eval_fn, own)
            new = window.candidate_score(eval_fn, cand)
        ev["validation_seconds"] = time.perf_counter() - t0
        if not (np.isfinite(cur) and np.isfinite(new)):
            raise PeerError("nonfinite eval score")
        ev.update(current_score=cur, candidate_score=new, margin=new - cur)
        if not new > cur + margin:
            raise PeerError("candidate not better than current policy")
    except PeerError as e:
        ev.update(accepted=False, reason=str(e))
    else:
        if window is not None:
            window.accepted += 1
        learner.previous = own
        learner.load_params_numpy(cand)
        learner.sync_target()
        learner._reset_optimizer()  # peer optimizer state is never imported; stale moments dropped
        learner.version += 1
        ev.update(accepted=True, new_version=learner.version, post_version=learner.version)
    learner.events.append(ev)
    return ev


def rollback(learner):
    if learner.previous is None:
        return False
    pre = learner.version
    prev, learner.previous = learner.previous, None
    learner.load_params_numpy(prev)
    learner.sync_target()
    learner._reset_optimizer()
    learner.version += 1
    learner.events.append(
        {
            "type": "rollback",
            "version": learner.version,
            "pre_version": pre,
            "post_version": learner.version,
        }
    )
    return True

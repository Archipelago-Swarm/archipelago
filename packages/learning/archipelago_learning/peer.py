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

from . import skills as skills_mod
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


def params_sha256(params) -> str:
    h = hashlib.sha256()
    for k in KEYS:
        h.update(np.ascontiguousarray(params[k], np.float32).tobytes())
    return h.hexdigest()


def head(learner, params=None):
    """Lineage record (DAG node) of the learner's current params; local training mints a child."""
    params = learner.params_numpy() if params is None else params
    pid = params_sha256(params)[:16]
    cur = getattr(learner, "lineage", None)
    if cur is None or cur["policy_id"] != pid:
        rec = {
            "policy_id": pid,
            "parent_ids": [cur["policy_id"]] if cur else [],
            "origin_node": cur["origin_node"] if cur else learner.node_id,
            "generation_count": cur["generation_count"] + 1 if cur else 0,
            "validation_score": None,
        }
        learner.lineage = cur = rec
        learner.dag = {**getattr(learner, "dag", {}), pid: rec}
    return cur


def _check_lineage(lin, pid):
    ok = (
        isinstance(lin, dict)
        and isinstance(lin.get("policy_id"), str)
        and (pid is None or lin["policy_id"] == pid)  # content hash: a forged id cannot match
        and isinstance(lin.get("parent_ids"), list)
        and all(isinstance(p, str) for p in lin["parent_ids"])
        and pid not in lin["parent_ids"]
        and isinstance(lin.get("origin_node"), str)
        and isinstance(lin.get("generation_count"), int)
        and lin["generation_count"] >= (1 if lin["parent_ids"] else 0)
    )
    if not ok:
        raise PeerError("bad lineage")


def encode(learner, keep=1.0) -> bytes:
    """keep<1 sends only the largest-magnitude fraction of delta entries (rest zero, compresses)."""
    params = learner.params_numpy()
    base = getattr(learner, "base_params", None)  # shared base checkpoint: send only the delta
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
        "lineage": dict(head(learner, params)),
    }
    if base is not None:
        meta["base_sha256"] = params_sha256(base)
        params = {k: (params[k] - base[k]).astype(np.float32) for k in KEYS}
        if keep < 1:
            meta["lossy"] = (
                True  # receiver rebuilds approximate params, so the id hash cannot be checked
            )
            allv = np.concatenate([np.abs(params[k]).ravel() for k in KEYS])
            cut = np.partition(allv, int(len(allv) * (1 - keep)))[int(len(allv) * (1 - keep))]
            params = {
                k: np.where(np.abs(params[k]) >= cut, params[k], 0).astype(np.float32) for k in KEYS
            }
    buf = io.BytesIO()
    np.savez_compressed(buf, _meta=np.frombuffer(json.dumps(meta).encode(), np.uint8), **params)
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
    if "base_sha256" in meta:  # delta payload: reconstruct against our copy of the shared base
        base = getattr(learner, "base_params", None)
        if base is None or params_sha256(base) != meta["base_sha256"]:
            raise PeerError("unknown base checkpoint")
        tensors = {k: (base[k] + tensors[k]).astype(np.float32) for k in KEYS}
    for k, t in tensors.items():
        if t.dtype != np.float32 or t.shape != shapes[k]:
            raise PeerError(f"bad tensor {k}: {t.dtype} {t.shape}")
        if not np.isfinite(t).all():
            raise PeerError(f"nonfinite tensor {k}")
    _check_lineage(meta.get("lineage"), None if meta.get("lossy") else params_sha256(tensors)[:16])
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


class Unsafe(PeerError):
    """Candidate is dangerous (not merely worse): the offering peer gets flagged."""


def q_envelope(probes, q_limit=100.0):
    """Safety filter: on probe observations the candidate's outputs must be finite and within
    +-q_limit (the actuator/value bound). Returns a fn(params) -> reason | None."""

    def check(p):
        h = np.maximum(probes @ p["w1"] + p["b1"], 0)
        q = h @ p["w2"] + p["b2"]
        if not np.isfinite(q).all() or np.abs(q).max() > q_limit:
            return f"output outside safety envelope (|q|<={q_limit})"

    return check


def offer(
    learner,
    payload: bytes,
    eval_fn,
    margin=0.0,
    alpha=None,
    sender=None,
    window=None,
    safety_fn=None,
    max_drop=None,
    skills_fn=None,
    skill_margin=0.0,
):
    """Accept the candidate only if eval_fn(params) beats the current policy by > margin.

    eval_fn receives a param-map-v1 dict of float32 NumPy arrays.
    alpha (mixing mode only, <=0.5) blends instead of replacing; mixing mode requires it.
    sender (transport source), if given, must match the node id the payload claims.
    window (OfferWindow, optional): after the window's first acceptance every further candidate is
    rejected with reason "window_limit" before decoding or evaluation (no validation cost).
    safety_fn (params -> reason | None) runs before any evaluation; a reason rejects the candidate.
    max_drop: a candidate scoring more than this below the current policy is rejected as a severe
    drop. Safety failures and severe drops flag the peer (learner.flagged); a flagged peer's later
    offers are rejected before decoding.
    skills_fn (params -> {skill: proficiency}): the event records the skill the candidate improved
    most (``skill``, ``skill_gain``) and acceptance also needs that gain > skill_margin; on adoption
    the receiver's learner.skills take the candidate's measured proficiencies (source = sender).
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
    flagged = None
    try:
        if sender in getattr(learner, "flagged", {}):
            raise PeerError("peer flagged")
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
        ev["lineage"] = meta["lineage"]
        own = learner.params_numpy()
        if alpha is not None:
            if learner.mode != "mixing" or not 0 < alpha <= 0.5:
                raise PeerError("mixing needs mode=mixing and 0<alpha<=0.5")
            cand = {k: ((1 - alpha) * own[k] + alpha * cand[k]).astype(np.float32) for k in KEYS}
        if safety_fn is not None and (why := safety_fn(cand)):
            flagged = meta.get("node")
            raise Unsafe(why)
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
        if max_drop is not None and new < cur - max_drop:
            flagged = meta.get("node")
            raise Unsafe("severe performance drop")
        if not new > cur + margin:
            raise PeerError("candidate not better than current policy")
        if skills_fn is not None:
            before, ev["skills_after"] = skills_fn(own), skills_fn(cand)
            ev["skill"], ev["skill_gain"] = skills_mod.best_gain(before, ev["skills_after"])
            if not ev["skill_gain"] > skill_margin:
                raise PeerError("no skill improved")
    except PeerError as e:
        ev.update(accepted=False, reason=str(e))
        if flagged is not None:
            ev["flagged"] = flagged
            learner.flagged = {**getattr(learner, "flagged", {}), flagged: str(e)}
    else:
        if window is not None:
            window.accepted += 1
        learner.previous = own
        learner.load_params_numpy(cand)
        learner.sync_target()
        learner._reset_optimizer()  # peer optimizer state is never imported; stale moments dropped
        learner.version += 1
        mine = head(learner, own)  # our pre-adoption policy is a parent too (a merge in the DAG)
        cl = meta["lineage"]
        learner.lineage = None
        rec = head(learner)  # new node for the adopted params ...
        rec.update(
            parent_ids=sorted({cl["policy_id"], mine["policy_id"]}),
            origin_node=cl["origin_node"],
            generation_count=max(cl["generation_count"], mine["generation_count"]) + 1,
            validation_score=float(new),
        )
        learner.dag[rec["policy_id"]] = rec
        learner.dag.setdefault(cl["policy_id"], cl)
        if skills_fn is not None:
            skills_mod.record(learner, ev["skills_after"], source=meta["node"])
        ev.update(accepted=True, new_version=learner.version, post_version=learner.version)
        ev["lineage"] = dict(rec)
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

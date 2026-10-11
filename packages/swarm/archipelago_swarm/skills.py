"""Skill artifact, node-local registry, evaluation.

A skill is a frozen snapshot of a node's learned policy weights (param-map-v1: w1,b1,w2,b2) plus
the evidence that earned it: the evaluation (greedy rollouts on the creator's own held-out
start/goal set) and the training state it came from. Artifacts are immutable; a receiver's copy
is a new registry entry that points at the same content hash. Wire/disk format: 4-byte big-endian
manifest length, manifest JSON, npz weights (allow_pickle=False). ``content_hash`` = sha256 over
the canonical manifest (without the hash) + weight bytes; install refuses a mismatch.

Provenance (``origin_type`` on the artifact; ``local_state`` on each holder's registry entry):
  SELF_LEARNED    qualified from this node's own training
  PEER_RECEIVED   installed from a peer over an RF link (local_state only)
  LOCALLY_DERIVED adapted from a held skill by local training and re-qualified (new artifact)
"""

from __future__ import annotations

import hashlib
import io
import json
import struct
from dataclasses import dataclass, field

import numpy as np
from archipelago_learning.torch_dqn import InferenceSnapshot

from .world import ACTION_SCHEMA, ACTIONS, OBS_DIM, OBS_SCHEMA_ID, REWARD_ID, SCHEMA_SHA

KEYS = ("w1", "b1", "w2", "b2")
SELF_LEARNED, PEER_RECEIVED, LOCALLY_DERIVED = "SELF_LEARNED", "PEER_RECEIVED", "LOCALLY_DERIVED"
SKILL_TYPE = "terrain-nav"
MAX_ARTIFACT_BYTES = 1 << 20
_FIXED = ("skill_type", "observation_schema", "action_schema", "action_names")


class SkillError(ValueError):
    pass


@dataclass(frozen=True)
class Skill:
    skill_id: str
    version: str  # "1", "2", derived "1.1", "1.1.1"
    origin_node_id: str  # node that created THIS artifact
    origin_type: str  # SELF_LEARNED | LOCALLY_DERIVED
    parent_skill_id: str | None
    derived_from_node_id: str | None  # node the parent was obtained from / learned on
    created_step: int
    params: dict[str, np.ndarray] = field(repr=False, compare=False)
    evaluation: dict
    training: dict
    compat: dict
    content_hash: str = ""

    def manifest(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "skill_type": SKILL_TYPE,
            "version": self.version,
            "origin_node_id": self.origin_node_id,
            "origin_type": self.origin_type,
            "parent_skill_id": self.parent_skill_id,
            "derived_from_node_id": self.derived_from_node_id,
            "created_step": self.created_step,
            "evaluation": self.evaluation,
            "training": self.training,
            "compat": self.compat,
            "observation_schema": OBS_SCHEMA_ID,
            "action_schema": ACTION_SCHEMA,
            "action_names": list(ACTIONS),
        }

    @property
    def confidence(self) -> float:
        return round(self.evaluation["success_rate"], 3)

    def meta(self) -> dict:
        """JSON metadata (what is mirrored to telemetry); no weights."""
        return {**self.manifest(), "content_hash": self.content_hash, "confidence": self.confidence}

    def to_bytes(self) -> bytes:
        man = json.dumps({**self.manifest(), "content_hash": self.content_hash}, sort_keys=True)
        buf = io.BytesIO()
        np.savez(buf, **{k: np.ascontiguousarray(self.params[k], np.float32) for k in KEYS})
        return struct.pack(">I", len(man)) + man.encode() + buf.getvalue()

    @property
    def size_bytes(self) -> int:
        return len(self.to_bytes())

    @staticmethod
    def hash_of(manifest: dict, params: dict[str, np.ndarray]) -> str:
        h = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode())
        for k in KEYS:
            h.update(np.ascontiguousarray(params[k], np.float32).tobytes())
        return h.hexdigest()

    @classmethod
    def build(cls, params: dict[str, np.ndarray], **kw) -> Skill:
        p = {k: np.ascontiguousarray(params[k], np.float32).copy() for k in KEYS}
        s = cls(params=p, **kw)
        return cls(**{**s.__dict__, "content_hash": cls.hash_of(s.manifest(), p)})

    @classmethod
    def from_bytes(cls, blob: bytes) -> Skill:
        """Parse + verify an artifact. Raises SkillError on any structural or hash problem."""
        try:
            if len(blob) > MAX_ARTIFACT_BYTES:
                raise SkillError("artifact too large")
            (n,) = struct.unpack(">I", blob[:4])
            man = json.loads(blob[4 : 4 + n])
            with np.load(io.BytesIO(blob[4 + n :]), allow_pickle=False) as z:
                params = {k: z[k] for k in z.files}
            if set(params) != set(KEYS) or any(not np.isfinite(v).all() for v in params.values()):
                raise SkillError("bad weights")
            claimed = man.pop("content_hash")
            if cls.hash_of(man, params) != claimed:
                raise SkillError("content hash mismatch")
            for k in _FIXED:
                man.pop(k)
            return cls(params=params, content_hash=claimed, **man)
        except SkillError:
            raise
        except Exception as e:  # malformed bytes from a peer must never crash the node
            raise SkillError(f"unreadable artifact: {e!r}") from e

    def save(self, path) -> None:
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    @classmethod
    def load(cls, path) -> Skill:
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())


def compat_header(hidden: int) -> dict:
    return {
        "obs_dim": OBS_DIM,
        "hidden": hidden,
        "n_actions": len(ACTIONS),
        "schema_sha256": SCHEMA_SHA,
        "reward_id": REWARD_ID,
        "param_map": "param-map-v1",
    }


def check_compat(skill: Skill, mine: dict) -> None:
    for k, v in mine.items():
        if skill.compat.get(k) != v:
            raise SkillError(f"incompatible {k}: {skill.compat.get(k)!r} != {v!r}")
    shapes = {
        "w1": (mine["obs_dim"], mine["hidden"]),
        "b1": (mine["hidden"],),
        "w2": (mine["hidden"], mine["n_actions"]),
        "b2": (mine["n_actions"],),
    }
    for k, shp in shapes.items():
        if skill.params[k].shape != shp:
            raise SkillError(f"bad shape for {k}")


@dataclass
class RegistryEntry:
    skill: Skill
    local_state: str  # SELF_LEARNED | PEER_RECEIVED | LOCALLY_DERIVED
    source_peer: str | None
    installed_step: int
    local_eval: dict | None = None  # evaluation on THIS node's own eval set


class SkillRegistry:
    """Node-local. Holds only what this node created, received or derived."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.entries: dict[str, RegistryEntry] = {}
        self.active_id: str | None = None

    def list_local_skills(self) -> list[RegistryEntry]:
        return list(self.entries.values())

    def has(self, content_hash: str) -> bool:
        return any(e.skill.content_hash == content_hash for e in self.entries.values())

    def add(
        self, skill: Skill, local_state: str, source_peer: str | None, step: int
    ) -> RegistryEntry:
        if skill.skill_id in self.entries:
            raise SkillError("already held")
        e = self.entries[skill.skill_id] = RegistryEntry(skill, local_state, source_peer, step)
        return e

    def advertisement(self) -> list[dict]:
        """Metadata only (no weights) of every held skill."""
        keys = (
            "skill_id",
            "version",
            "content_hash",
            "origin_node_id",
            "origin_type",
            "parent_skill_id",
            "evaluation",
            "confidence",
            "compat",
        )
        out = []
        for e in self.entries.values():
            m = e.skill.meta()
            out.append({k: m[k] for k in keys} | {"size_bytes": e.skill.size_bytes})
        return out

    def counts(self) -> dict[str, int]:
        c = dict.fromkeys((SELF_LEARNED, PEER_RECEIVED, LOCALLY_DERIVED), 0)
        for e in self.entries.values():
            c[e.local_state] += 1
        return {
            "self_learned_skills": c[SELF_LEARNED],
            "received_skills": c[PEER_RECEIVED],
            "derived_skills": c[LOCALLY_DERIVED],
        }


def evaluate_params(world, params, episodes, max_steps: int = 40) -> dict:
    """Greedy rollouts of ``params`` on (start, goal) pairs. Private to the evaluating node: it
    never touches that node's physical state, replay or optimizer."""
    snap = InferenceSnapshot(params)
    wins = steps = 0
    ret = 0.0
    for start, goal in episodes:
        pos, ep_ret = start, 0.0
        for t in range(max_steps):  # noqa: B007
            a = int(np.argmax(snap.q(world.observe(pos, goal))))
            pos, r, _, done, _ = world.step(pos, goal, a)
            ep_ret += r
            if done:
                wins += 1
                break
        steps += t + 1
        ret += ep_ret
    n = len(episodes)
    return {
        "success_rate": round(wins / n, 4),
        "mean_return": round(ret / n, 4),
        "mean_steps": round(steps / n, 2),
        "episodes": n,
        "max_steps": max_steps,
    }

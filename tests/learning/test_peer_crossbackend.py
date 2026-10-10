import io
import json
import zipfile

import numpy as np
import pytest
from archipelago_learning import Learner, PeerError, decode, encode, offer, rollback
from archipelago_learning.peer import MAX_BYTES
from torch_support import (
    fill,
    numpy_learner,
    optimizer_is_fresh,
    score,
    target_params,
    torch_learner,
    trained_torch,
)

MAKERS = {"numpy": numpy_learner, "torch": torch_learner}


def trained_numpy(seed=0, node="n"):
    L = numpy_learner(node, seed)
    fill(L)
    for _ in range(300):
        L.train_step()
    return L


def _trained(kind, node):
    return trained_numpy(0, node) if kind == "numpy" else trained_torch(0, node)


def same(a, b):
    return all(np.array_equal(a[k], b[k]) for k in a)


@pytest.mark.parametrize("src,dst", [("numpy", "torch"), ("torch", "numpy"), ("torch", "torch")])
def test_cross_backend_accept_replaces_policy_target_optimizer_and_logs(src, dst):
    teacher = _trained(src, "teacher")
    student = MAKERS[dst]("student", 5)
    fill(student)
    for _ in range(2):  # give the student optimizer moments that must be dropped
        student.train_step()
    own = student.params_numpy()
    v0 = student.version
    assert score(own) < 1.0
    ev = offer(student, encode(teacher), score)
    assert ev["accepted"] and ev["source"] == "teacher" and ev["source_backend"] == teacher.backend
    assert ev["source_version"] == teacher.version and len(ev["payload_sha256"]) == 64
    assert (ev["pre_version"], ev["post_version"], ev["new_version"]) == (v0, v0 + 1, v0 + 1)
    assert ev["current_score"] < ev["candidate_score"] == 1.0
    assert ev["margin"] == pytest.approx(ev["candidate_score"] - ev["current_score"])
    assert ev["validation_seconds"] >= 0
    assert student.version == v0 + 1
    assert same(student.params_numpy(), teacher.params_numpy())
    assert same(target_params(student), student.params_numpy())  # target = copy of new policy
    assert optimizer_is_fresh(student)  # moments dropped, teacher's never imported
    assert same(student.previous, own)
    # peer imports are a separate event type from local updates
    assert ev["type"] == "peer_offer" and {e["type"] for e in student.events} == {
        "local_update",
        "peer_offer",
    }
    # the student keeps learning from the imported weights
    assert student.train_step() is not None and student.opt is not None


@pytest.mark.parametrize("dst", ["numpy", "torch"])
def test_rollback_restores_previous_params_target_and_optimizer(dst):
    teacher = trained_torch(0, "teacher")
    student = MAKERS[dst]("student", 5)
    fill(student)
    for _ in range(2):
        student.train_step()
    own = student.params_numpy()
    assert offer(student, encode(teacher), score)["accepted"]
    v = student.version
    assert rollback(student)
    assert same(student.params_numpy(), own) and same(target_params(student), own)
    assert optimizer_is_fresh(student) and student.version == v + 1
    assert student.events[-1]["type"] == "rollback" and student.events[-1]["pre_version"] == v
    assert not rollback(student)  # only one level kept
    assert score(student.params_numpy()) < 1.0


@pytest.mark.parametrize("dst", ["numpy", "torch"])
def test_reject_leaves_everything_unchanged(dst):
    good, fresh = trained_torch(0, "good"), MAKERS[dst]("fresh", 5)
    mine = _trained(dst, "me")
    before, v, t = mine.params_numpy(), mine.version, target_params(mine)
    t = {k: x.copy() for k, x in t.items()}
    ev = offer(mine, encode(fresh), score)
    assert not ev["accepted"] and "not better" in ev["reason"]
    assert same(mine.params_numpy(), before) and mine.version == v and same(target_params(mine), t)
    assert mine.previous is None and good.version > 0


# --- rejection of unsafe or incompatible payloads -------------------------------------------


def craft(learner, meta=None, tensors=None, drop=(), extra=None, compressed=False):
    """Re-encode learner's payload with modified header/tensors (to forge bad payloads)."""
    z = np.load(io.BytesIO(encode(learner)), allow_pickle=False)
    m = json.loads(bytes(z["_meta"]))
    m.update(meta or {})
    for k in drop:
        m.pop(k)
    arrays = {k: z[k] for k in ("w1", "b1", "w2", "b2")}
    arrays.update(tensors or {})
    arrays.update(extra or {})
    buf = io.BytesIO()
    (np.savez_compressed if compressed else np.savez)(
        buf, _meta=np.frombuffer(json.dumps(m).encode(), np.uint8), **arrays
    )
    return buf.getvalue()


@pytest.fixture(params=["numpy", "torch"])
def receiver(request):
    return MAKERS[request.param]("rx", 1)


@pytest.fixture(params=["numpy", "torch"])
def sender(request):
    return MAKERS[request.param]("tx", 2)


@pytest.mark.parametrize(
    "meta,reason",
    [
        ({"encoder": "other"}, "incompatible encoder"),
        ({"encoder_sha256": "0" * 64}, "incompatible encoder_sha256"),
        ({"param_map": "param-map-v2"}, "incompatible param_map"),
        ({"obs_dim": 4}, "incompatible obs_dim"),
        ({"hidden": 8}, "incompatible hidden"),
        ({"n_actions": 4}, "incompatible n_actions"),
        ({"reward_id": "rew-v9"}, "incompatible reward_id"),
        ({"action_space": "act-v9"}, "incompatible action_space"),
        ({"format": "archipelago-peer-v1"}, "incompatible format"),
    ],
)
def test_header_mismatches_rejected_with_named_reason(receiver, sender, meta, reason):
    p = craft(sender, meta)
    with pytest.raises(PeerError, match=reason):
        decode(p, receiver)
    before = receiver.params_numpy()
    ev = offer(receiver, p, score)
    assert not ev["accepted"] and reason in ev["reason"] and same(receiver.params_numpy(), before)


def test_legacy_payload_without_compat_header_is_rejected(receiver, sender):
    p = craft(sender, drop=("format", "param_map", "backend", "reward_id", "action_space"))
    with pytest.raises(PeerError, match="incompatible format"):
        decode(p, receiver)


def test_different_encoder_definition_hash_blocks_exchange_even_with_same_id(receiver):
    other = numpy_learner("o")
    other.encoder_sha256 = "f" * 64
    assert not offer(receiver, encode(other), score)["accepted"]


def test_bad_tensor_payloads_rejected(receiver, sender):
    own = sender.params_numpy()
    bad = {
        "nonfinite": ({"w2": np.where(own["w2"] >= 0, np.nan, 0).astype(np.float32)}, "nonfinite"),
        "inf": ({"b1": np.full_like(own["b1"], np.inf)}, "nonfinite"),
        "dtype": ({"w1": own["w1"].astype(np.float64)}, "bad tensor w1"),
        "int": ({"b2": own["b2"].astype(np.int32)}, "bad tensor b2"),
        "shape": ({"w1": own["w1"][:2]}, "bad tensor w1"),
        "transposed": ({"w1": np.ascontiguousarray(own["w1"].T)}, "bad tensor w1"),
    }
    for name, (tensors, reason) in bad.items():
        p = craft(sender, tensors=tensors)
        before = receiver.params_numpy()
        ev = offer(receiver, p, score)
        assert not ev["accepted"] and reason in ev["reason"], name
        assert same(receiver.params_numpy(), before) and receiver.previous is None


def test_extra_or_missing_members_rejected(receiver, sender):
    with pytest.raises(PeerError, match="malformed"):
        decode(craft(sender, extra={"optimizer_m": np.zeros(3, np.float32)}), receiver)
    buf = io.BytesIO()
    np.savez(buf, _meta=np.frombuffer(b"{}", np.uint8), w1=sender.params_numpy()["w1"])
    with pytest.raises(PeerError, match="malformed"):
        decode(buf.getvalue(), receiver)


def test_oversize_payload_rejected(receiver):
    with pytest.raises(PeerError, match="too large"):
        decode(b"\0" * (MAX_BYTES + 1), receiver)
    assert not offer(receiver, b"\0" * (MAX_BYTES + 1), score)["accepted"]


def test_zip_bomb_rejected_before_materialising(receiver, sender):
    bomb = craft(sender, extra={"junk": np.zeros(1 << 25, np.uint8)}, compressed=True)
    assert len(bomb) < MAX_BYTES and zipfile.is_zipfile(io.BytesIO(bomb))
    with pytest.raises(PeerError, match="inflates"):
        decode(bomb, receiver)
    assert not offer(receiver, bomb, score)["accepted"]


def test_pickled_object_npz_is_never_loaded(receiver, sender):
    class Boom:
        def __reduce__(self):
            return (pytest.fail, ("payload was unpickled",))

    for member in ("w1", "_meta"):
        buf = io.BytesIO()
        arrays = {k: v for k, v in sender.params_numpy().items()}
        meta = np.frombuffer(json.dumps({"format": "x"}).encode(), np.uint8)
        np.savez(buf, **{"_meta": meta, **arrays, member: np.array([Boom()], dtype=object)})
        with pytest.raises(PeerError, match="malformed"):
            decode(buf.getvalue(), receiver)
        assert not offer(receiver, buf.getvalue(), score)["accepted"]
    with pytest.raises(PeerError, match="malformed"):
        decode(b"not an npz at all", receiver)


def test_sender_must_match_claimed_node(receiver, sender):
    ev = offer(receiver, encode(sender), score, sender="mallory")
    assert not ev["accepted"] and "sender" in ev["reason"]


@pytest.mark.parametrize("dst", ["numpy", "torch"])
def test_information_only_never_loads_and_mixing_is_bounded(dst):
    good = trained_torch(0, "g")
    info = MAKERS[dst]("i", 3, mode="information_only")
    assert "never loads" in offer(info, encode(good), score)["reason"]
    ind = MAKERS[dst]("x", 3)
    assert not offer(ind, encode(good), score, alpha=0.3)["accepted"]
    mix = MAKERS[dst]("m", 9, mode="mixing")
    assert not offer(mix, encode(good), score, alpha=0.9)["accepted"]
    assert not offer(mix, encode(good), score)["accepted"]  # no alpha would full-replace
    own = mix.params_numpy()
    ev = offer(
        mix,
        encode(good),
        lambda p: float(p["w1"].sum() * 0 + p["b1"].sum() + p["w2"].sum()),
        margin=-1e9,
        alpha=0.25,
    )
    assert ev["accepted"]
    want = 0.75 * own["w1"] + 0.25 * good.params_numpy()["w1"]
    assert np.allclose(mix.params_numpy()["w1"], want, atol=1e-6)
    assert optimizer_is_fresh(mix) and same(target_params(mix), mix.params_numpy())


def test_nonfinite_score_rejected(receiver, sender):
    ev = offer(receiver, encode(sender), lambda p: float("nan"))
    assert not ev["accepted"] and "nonfinite" in ev["reason"] and "candidate_score" not in ev


def test_roundtrip_payload_is_exactly_param_map_v1(receiver, sender):
    meta, tensors = decode(encode(sender), receiver)
    assert meta["param_map"] == "param-map-v1" and meta["backend"] == sender.backend
    assert same(tensors, sender.params_numpy())
    assert {k: v.dtype for k, v in tensors.items()} == dict.fromkeys(tensors, np.float32)
    assert Learner.forward(tensors, np.eye(3, dtype=np.float32))[1].shape == (3, 3)

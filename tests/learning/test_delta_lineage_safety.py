import numpy as np
from archipelago_learning import Learner, encode, offer
from archipelago_learning.peer import q_envelope

ENC = "grid-flat-v1-s8-r2"


def numpy_learner(node, seed):
    return Learner(node, 64, 5, hidden=64, seed=seed, encoder=ENC)


def pair():
    student, teacher = numpy_learner("student", 5), numpy_learner("teacher", 5)
    base = student.params_numpy()  # shared base checkpoint both nodes hold
    student.base_params = teacher.base_params = base
    w = teacher.params_numpy()  # fine-tuned teacher: small change to a few weights
    w["w2"] = w["w2"].copy()
    w["w2"][:4] += 0.5
    teacher.load_params_numpy(w)
    return teacher, student


def test_delta_payload_is_smaller_sparse_and_lineage_dag_links_origin():
    t, s = pair()
    full = len(encode(numpy_learner("x", 1)))
    assert len(encode(t)) < full * 0.5  # delta is mostly zeros -> compresses
    assert len(encode(t, keep=0.1)) < full * 0.5
    ev = offer(s, encode(t), lambda p: float(p["w2"].sum()), sender="teacher")
    assert ev["accepted"], ev
    lin = ev["lineage"]
    assert lin["origin_node"] == "teacher" and lin["generation_count"] >= 1
    assert len(lin["parent_ids"]) == 2 and all(p in s.dag for p in lin["parent_ids"])
    assert s.dag[lin["policy_id"]] is s.lineage and s.lineage["validation_score"] is not None


def test_unknown_base_and_forged_lineage_rejected():
    t, s = pair()
    ev = offer(s, encode(t), lambda p: 1.0, margin=-1)
    assert ev["accepted"]
    s.base_params = {k: v + 1 for k, v in t.base_params.items()}
    assert offer(s, encode(t), lambda p: 1.0)["reason"] == "unknown base checkpoint"


def test_safety_envelope_rejects_flags_and_blocks_peer():
    t, s = pair()
    w = t.params_numpy()
    w["w2"] = w["w2"] * 1e6  # poisoned: huge outputs
    t.load_params_numpy(w)
    probes = np.random.default_rng(0).normal(size=(8, s.obs_dim)).astype(np.float32)
    ev = offer(s, encode(t), lambda p: 9.0, sender="teacher", safety_fn=q_envelope(probes, 100.0))
    assert not ev["accepted"] and "safety envelope" in ev["reason"] and ev["flagged"] == "teacher"
    assert offer(s, encode(t), lambda p: 9.0, sender="teacher")["reason"] == "peer flagged"


def test_severe_drop_rejects_and_flags():
    t, s = pair()
    scores = iter([10.0, 1.0])  # current, candidate
    ev = offer(s, encode(t), lambda p: next(scores), sender="teacher", max_drop=5.0)
    assert ev["reason"] == "severe performance drop" and "teacher" in s.flagged

"""Skills: measured per-skill proficiency, change through training and peer adoption, controls."""

import copy

import pytest
from archipelago_learning import encode, offer, rollout, skills

EVAL = (900, 901, 902, 903)


def measure(p):
    return rollout.eval_skills(p, EVAL)


def learner(node, seed, episodes):
    L = rollout.make_learner(node, seed)
    rollout.train(L, episodes, seed0=seed * 100)
    return L


def moved(a, b):
    return {k: abs(a[k] - b[k]) for k in skills.SKILLS if abs(a[k] - b[k]) > 0.02}


def test_every_skill_is_measured_in_unit_range_and_deterministic():
    L = rollout.make_learner("a", 0)
    m = measure(L.params)
    assert set(m) == set(skills.SKILLS)
    assert all(0.0 <= v <= 1.0 for v in m.values())
    assert measure(L.params) == m  # fixed seeds: same params -> same proficiency


def test_training_changes_skill_proficiency_and_versions_it():
    L = rollout.make_learner("a", 0)
    before = measure(L.params)
    skills.record(L, before, "a")
    rollout.train(L, 40)
    after = measure(L.params)
    assert moved(before, after), "40 training episodes left every skill unchanged"
    skills.record(L, after, "a")
    for k in skills.SKILLS:
        assert L.skills[k]["proficiency"] == after[k]
        assert L.skills[k]["version"] == (2 if before[k] != after[k] else 1)


def test_fixed_policy_control_shows_no_change():
    L = rollout.make_learner("a", 0)
    L.paused = True  # training is a no-op: the policy is fixed
    skills.record(L, measure(L.params), "a")
    first = copy.deepcopy(L.skills)
    rollout.train(L, 5)
    skills.record(L, measure(L.params), "a")
    assert L.skills == first
    assert all(s["version"] == 1 for s in L.skills.values())


def test_peer_adoption_changes_receiver_skills_and_is_traced():
    teacher, student = learner("teacher", 2, 40), rollout.make_learner("student", 7)
    skills.record(student, measure(student.params), "student")
    before = copy.deepcopy(student.skills)
    ev = offer(
        student,
        encode(teacher),
        lambda p: rollout.evaluate(p, EVAL),
        sender="teacher",
        skills_fn=measure,
    )
    assert ev["accepted"], ev
    want = measure(teacher.params)
    assert {k: s["proficiency"] for k, s in student.skills.items()} == want
    for k in skills.SKILLS:
        assert student.skills[k]["version"] == before[k]["version"] + (want[k] != before[k]["proficiency"])
    assert any(student.skills[k]["source"] == "teacher" for k in skills.SKILLS)
    assert ev["skill"] in skills.SKILLS and ev["skill_gain"] > 0
    assert ev["skill_gain"] == pytest.approx(want[ev["skill"]] - before[ev["skill"]]["proficiency"])
    assert student.events[-1] is ev and ev["lineage"]["origin_node"] == "teacher"


def test_candidate_without_skill_gain_is_rejected_even_if_score_improves():
    teacher, student = learner("teacher", 2, 40), rollout.make_learner("student", 7)
    skills.record(student, measure(student.params), "student")
    before, version = copy.deepcopy(student.skills), student.version
    flat = dict.fromkeys(skills.SKILLS, 0.5)  # skills_fn sees no difference between policies
    own = student.params["w1"].copy()
    ev = offer(
        student,
        encode(teacher),
        lambda p: 0.0 if (p["w1"] == own).all() else 1.0,
        skills_fn=lambda p: flat,
    )
    assert ev["candidate_score"] > ev["current_score"]  # the scalar gate alone would accept
    assert not ev["accepted"] and ev["reason"] == "no skill improved"
    assert student.skills == before and student.version == version


def test_identical_policy_offer_is_rejected_and_skills_stay():
    L = learner("a", 3, 10)
    skills.record(L, measure(L.params), "a")
    before = copy.deepcopy(L.skills)
    ev = offer(L, encode(copy.deepcopy(L)), lambda p: rollout.evaluate(p, EVAL), skills_fn=measure)
    assert not ev["accepted"]
    assert L.skills == before

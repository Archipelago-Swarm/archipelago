"""Node skills, driven in-process (no subprocess): measured, versioned, persisted, transferred."""

import copy

from archipelago_learning import encode
from archipelago_noderuntime.node import Job, Node
from archipelago_transport import Envelope
from support import make_cfg
from test_checkpoint import drive, spooled

SKILLS = {"explore", "avoid", "acquire", "energy"}


def node(tmp, nid, **over):
    return Node(make_cfg(tmp, nid, update_every=5, **over))


def measure(n):
    n._measure_own_skills(Job("window", "w"))
    return copy.deepcopy(n.learner.skills)


def prof(skills):
    return {k: v["proficiency"] for k, v in skills.items()}


def test_training_moves_node_skills_and_fixed_policy_does_not(tmp_path):
    n = node(tmp_path, "node-01")
    first = measure(n)
    assert set(first) == SKILLS and all(v["version"] == 1 and v["source"] == "node-01" for v in first.values())
    assert prof(measure(n)) == prof(first)  # control: nothing trained, nothing moved
    assert {k: v["version"] for k, v in n.learner.skills.items()} == dict.fromkeys(SKILLS, 1)
    drive(n, 120)
    after = measure(n)
    moved = {k for k in SKILLS if after[k]["proficiency"] != first[k]["proficiency"]}
    assert moved
    assert all(after[k]["version"] == 2 for k in moved)


def test_peer_adoption_changes_receiver_skills_and_emits_trace(tmp_path):
    teacher, student = node(tmp_path, "node-02", seed=1), node(tmp_path, "node-01")
    drive(teacher, 200)
    before = measure(student)
    want = measure(teacher)
    res = {"validation_seconds": 0.0, "evaluations": 0}
    env = Envelope.make("node-02", "node-01", 1, encode(teacher.learner))
    (d,) = student._decide([env], Job("window", "w2", tick=5), res)
    assert d["accepted"], d
    got = student.learner.skills
    assert prof(got) == prof(want)
    assert d["skill"] in SKILLS and d["skill_gain"] > 0
    assert any(v["source"] == "node-02" and v["version"] == before[k]["version"] + 1 for k, v in got.items())
    student._emit_skills(5)
    recs = [r["record"] for r in spooled(student.cfg)]
    learn = [r for r in recs if r["kind"] == "learning_event" and r["transfer"] == "accepted"]
    assert learn and learn[-1]["skill"] == d["skill"] and learn[-1]["skill_gain"] == d["skill_gain"]
    metrics = {r["metric"]: r["value"] for r in recs if r["kind"] == "metric_sample"}
    assert metrics["skill.explore"] == got["explore"]["proficiency"]
    assert metrics["skill_version.explore"] == got["explore"]["version"]
    units = {r["metric"]: r["unit"] for r in recs if r["kind"] == "metric_sample"}
    assert units["skill_version." + d["skill"]] == "source:node-02"


def test_skills_survive_checkpoint_restore(tmp_path):
    n = node(tmp_path, "node-01")
    drive(n, 60)
    measure(n)
    n.checkpoint()
    again = Node(n.cfg)
    assert again.learner.skills == n.learner.skills

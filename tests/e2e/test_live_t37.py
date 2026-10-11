# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""T38 / Amendment A18 on real processes: the T37 ids (reward rew-v1, observation
grid-flat-v2-visits-shared, learner schedule sched-t37-v1) reach every layer, visited-cell summaries
flow between open peers and never across a cut, and the old ids keep working.

The shared fixtures (``smoke``, ``make_cluster``) already select the T37 ids in their plans.
"""

import json

import e2e_procs
import pytest
from e2e_procs import NODE_IDS

IDS = {
    "reward_id": "rew-v1",
    "learner_schedule_id": "sched-t37-v1",
    "encoder_id": "grid-flat-v2-visits-shared-s8-r2",
}
HALF = {"node-01": 0, "node-02": 0, "node-03": 1, "node-04": 1}
CUT_WINDOW = (15, 45)  # conftest.SMOKE_CUT


def spool_records(c, n):
    out = []
    for seg in sorted((c.ckpt_dir(n) / "telemetry").glob("seg-*.jsonl")):
        out += [json.loads(x)["record"] for x in seg.read_text().splitlines() if x.strip()]
    return out


def test_the_plan_selected_ids_are_what_the_world_and_the_nodes_run(smoke):
    c, run_id, view = smoke
    assert view["status"] == "completed", view
    assert view["ids"] == {**IDS, "reward_source": "plan"}
    doc = json.loads((c.tmp / "coordinator" / "runs" / run_id / "manifest.json").read_text())
    assert doc["ids"] == view["ids"] and doc["run_config"]["reward_id"] == "rew-v1"
    # the coordinator's world (the one that produced the rewards) ran rew-v1
    for ep in view["episodes_done"]:
        rep = json.loads(open(ep["replay_manifest"]).read())
        assert rep["run_config"]["reward_id"] == "rew-v1"
    for n in NODE_IDS:
        st = c.node_status(n)
        assert {k: st[k] for k in IDS} == IDS
        assert st["obs_dim"] == 82 and st["double_dqn"] is True and len(st["encoder_sha256"]) == 64
        assert (
            st["train_episode"] == 1
        )  # two training episodes ran (index 0, 1); eval does not count
        assert st["epsilon"] == 0.0  # the last episode is a frozen test episode


def test_checkpoints_and_telemetry_record_the_ids(smoke):
    c, run_id, _ = smoke
    for n in NODE_IDS:
        assert c.checkpoint(n, run_id)[0] == 200
        root = c.ckpt_dir(n) / "ckpt"
        cur = json.loads((root / "CURRENT").read_text())
        counters = json.loads((root / f"gen-{cur['generation']}" / "counters.json").read_text())
        assert counters["encoder"] == IDS["encoder_id"] and counters["reward_id"] == "rew-v1"
        assert counters["learner_schedule"] == "sched-t37-v1" and counters["double_dqn"] is True
        assert counters["obs_dim"] == 82 and counters["capacity"] == 50000
        assert counters["node"]["ids"]["encoder_id"] == IDS["encoder_id"]
        assert counters["node"]["memory"]["visits"], "node-local memory is part of the checkpoint"
        names = {r["metric"] for r in spool_records(c, n) if r["kind"] == "metric_sample"}
        want = f"ids:{IDS['encoder_id']}:rew-v1:sched-t37-v1"
        assert want in names, sorted(x for x in names if x.startswith("ids"))


def test_summaries_flow_between_open_peers_and_none_crosses_the_cut(smoke):
    c, _, _ = smoke
    lo, hi = CUT_WINDOW
    for n in NODE_IDS:
        st = c.node_status(n)
        k = st["counters"]
        assert k["summaries_applied"] > 0 and k["summaries_sent"] > 0, (n, k)
        assert k["summaries_cut"] > 0, f"{n} never saw the cut"
        assert k["summaries_rejected"] == 0 and st["summaries"]["last_reject"] is None
        rx = st["summaries"]["rx_ticks"]
        assert set(rx) == {"2", "3"}, (
            rx
        )  # the last two episodes (validation, test), both with the cut
        for ep, per_src in rx.items():
            for src, ticks in per_src.items():
                inside = [t for t in ticks if lo <= t < hi]
                if HALF[src] != HALF[n]:  # the positive control (paced run) is in test_live_faults
                    assert inside == [], (
                        f"{n} applied a summary from {src} inside the cut (ep {ep}): {inside}"
                    )


def test_old_ids_still_work_on_real_processes(make_cluster):
    c = make_cluster(ticks=40, ids="legacy")
    c.start_run(
        "legacy",
        episodes=[{"kind": "train", "seed": 61}, {"kind": "validation", "seed": 62}],
        seed=9,
    )
    view = c.wait_run("legacy")
    assert view["status"] == "completed", view
    assert view["ids"] == {"reward_id": "rew-v0", "reward_source": "run_config",
                           "encoder_id": "grid-flat-v1-s8-r2", "learner_schedule_id": "sched-v0"}  # fmt: skip
    for n in NODE_IDS:
        st = c.node_status(n)
        assert {k: st[k] for k in IDS} == c.expected_ids
        assert st["obs_dim"] == 28 and st["double_dqn"] is False and st["train_steps"] > 0
        k = st["counters"]
        assert (
            k["summaries_sent"] == 0 and k["summaries_applied"] == 0
        )  # v1 has no information message


def test_a_wrong_encoder_family_in_the_plan_is_refused_before_anything_runs(make_cluster):
    c = make_cluster(ticks=20)
    req = c.run_body("bad-enc", [{"kind": "train", "seed": 71}], seed=3,
                     node_config={"encoder_id": "grid-flat-v2-visits-shared-s9-r2",
                                  "learner_schedule_id": "sched-t37-v1"})  # fmt: skip
    c.plans["bad-enc"] = req["plan"]
    c._write_plans()
    code, body = c.coord_call(
        "POST", "/v1/runs", {"run_config": req["run_config"], "plan_name": "bad-enc"}
    )
    assert code == 422 and "does not match the live world" in json.dumps(body), (code, body)
    assert all(c.node_status(n)["configured_run"] is None for n in NODE_IDS)


@pytest.mark.parametrize("ids", ["t37", "legacy"])
def test_cluster_helper_exposes_the_expected_ids(tmp_path, ids):
    cl = e2e_procs.Cluster(tmp_path, ticks=10, ids=ids)
    try:
        plan = cl.run_body("x", [{"kind": "train", "seed": 1}])["plan"]
        assert (plan.get("reward_id") == "rew-v1") == (ids == "t37")
        assert cl.expected_ids["reward_id"] == ("rew-v1" if ids == "t37" else "rew-v0")
    finally:
        cl.close()

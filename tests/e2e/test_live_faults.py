# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""Fault and restart behaviour of the live runtime on real processes (no Docker).

These depend on the node-runtime amendments (agents/architecture/live-runtime.md A1 tick-cadence exchange
windows, A3 restart-safe identity). Where the runtime does not yet behave as amended the assertion fails with
the evidence; nothing here is skipped or loosened.
"""

import re
import sys
import threading
import time
from collections import Counter

import e2e_procs
import pytest
from e2e_procs import HALVES_CUT, NODE_IDS

HALF = {"node-01": 0, "node-02": 0, "node-03": 1, "node-04": 1}
TICKS = 120
CUT = [{"start_tick": 30, "end_tick": 100, "cut_links": HALVES_CUT}]
TRAIN = [{"kind": "train", "seed": 41}]


def poll_while_running(c, run_id, sample, period=0.1, timeout=120):
    """Call ``sample(c)`` repeatedly until the run reaches a terminal state; returns the samples."""
    out, end = [], time.monotonic() + timeout
    while time.monotonic() < end:
        view = c.run_status(run_id)
        out.append((view["status"], view.get("tick"), sample(c)))
        if view["status"] in ("completed", "failed", "interrupted"):
            return out
        time.sleep(period)
    raise AssertionError("run did not finish")


def decisions(records):
    return [
        r
        for r in records
        if r["kind"] == "learning_event" and r["transfer"] in ("accepted", "rejected")
    ]


def source_of(decision):
    m = re.search(r"source=(node-\d+)", decision.get("reason") or "")
    return m.group(1) if m else None


@pytest.fixture(scope="module")
def cut_run(tmp_path_factory, request):
    """One 120-tick episode, paced, with a 30..100 cut between the halves; node status sampled throughout."""
    c = e2e_procs.Cluster(tmp_path_factory.mktemp("live-cut"), ticks=TICKS)
    failed_before = request.session.testsfailed
    try:
        c.start(tick_interval_s=0.03)
        c.start_run("cut", episodes=TRAIN, fault_schedule=CUT, seed=2)
        samples = poll_while_running(c, "cut", lambda cl: {n: cl.node_status(n) for n in NODE_IDS})
        yield c, samples
    finally:
        if request.session.testsfailed > failed_before:
            print(c.logs_text(), file=sys.stderr)
        c.close()


def test_local_updates_continue_during_the_cut_and_no_candidate_crosses_it(cut_run):
    c, samples = cut_run
    inside = [
        s for st, tick, s in samples if tick is not None and 40 <= tick <= 90 and st == "running"
    ]
    assert len(inside) >= 5, "run was too fast to observe the cut window"
    # local learning is unaffected by the cut: optimizer steps keep increasing inside the window
    for n in NODE_IDS:
        steps = [s[n]["train_steps"] for s in inside]
        assert steps[-1] > steps[0], (
            f"{n} stopped training during the cut: {steps[0]} -> {steps[-1]}"
        )
    # every node reports its cross-half links as cut inside the window
    for n in NODE_IDS:
        peers = inside[-1][n]["peers"]
        assert {p: v for p, v in peers.items() if HALF[p] != HALF[n]} == {
            p: "cut" for p in peers if HALF[p] != HALF[n]
        }, (n, peers)
        assert all(v == "up" for p, v in peers.items() if HALF[p] == HALF[n]), (n, peers)
    # No decision made inside the window was on a candidate that crossed the cut.
    crossing = [
        (r["source_node_id"], source_of(r), r["sim_tick"])
        for r in decisions(c.sink.records())
        if 30 <= r["sim_tick"] < 100
        and source_of(r)
        and HALF[source_of(r)] != HALF[r["source_node_id"]]
    ]
    assert crossing == [], f"candidates crossed the cut: {crossing}"


def test_exchange_windows_run_on_a_tick_cadence_and_see_the_cut(cut_run):
    """A1: windows fire inside the episode, so some fall inside the cut and find the cross-half links closed.
    With exchange only at episode_end (tick 119, after the cut ends at 100) no exchange can ever see the cut."""
    c, _ = cut_run
    final = {n: c.node_status(n)["counters"] for n in NODE_IDS}
    assert sum(f["exchanges"] for f in final.values()) >= 2 * len(NODE_IDS), {
        n: f["exchanges"] for n, f in final.items()
    }
    assert sum(f["offers_cut"] for f in final.values()) > 0, (
        f"no exchange saw the cut: exchanges={ {n: f['exchanges'] for n, f in final.items()} } "
        f"offers_cut={ {n: f['offers_cut'] for n, f in final.items()} }"
    )


def test_an_offer_decision_is_logged_inside_an_episode_not_only_at_its_end(make_cluster):
    c = make_cluster(ticks=TICKS, tick_interval_s=0.03, EXCHANGE_EVERY_TICKS="30")
    c.start_run("windows", episodes=TRAIN, seed=3)
    seen = []

    def sample(cl):
        return sum(
            (s["counters"]["decisions_accepted"] + s["counters"]["decisions_rejected"])
            for s in (cl.node_status(n) for n in NODE_IDS)
        )

    for status, tick, total in poll_while_running(c, "windows", sample):
        if status == "running" and tick is not None and tick < TICKS - 5:
            seen.append((tick, total))
    assert seen and max(t for _, t in seen) > 0, (
        "no peer decision was logged before the last ticks of the episode; "
        f"exchange only runs at episode_end (A1 not implemented): {seen[-3:]}"
    )


def test_restarted_node_resumes_with_continued_sequence_numbers(make_cluster):
    c = make_cluster(ticks=60)
    c.start_run("before", episodes=TRAIN, seed=4)
    assert c.wait_run("before")["status"] == "completed"
    victim = "node-03"
    code, _ = c.node_control(victim, command="checkpoint")
    assert code == 200
    time.sleep(0.8)  # let the shipper deliver
    old = c.sink.records(victim)
    assert old, "node shipped nothing before the kill"
    old_max, old_boot = max(r["sequence"] for r in old), c.node_status(victim)["boot_id"]
    old_ids = {r["event_id"] for r in old}

    c.restart_node(victim, kill=True)  # SIGKILL, then start again on the same volume
    st = c.node_status(victim)
    assert st["boot_id"] != old_boot and st["restore"]["restored"] is True, st["restore"]
    assert st["train_steps"] > 0, "restart lost the learner state"

    c.start_run("after", episodes=[{"kind": "train", "seed": 5}], seed=5)
    assert c.wait_run("after")["status"] == "completed"
    time.sleep(0.8)
    new = [r for r in c.sink.records(victim) if r["event_id"] not in old_ids]
    assert new, "restarted node emitted nothing"
    assert min(r["sequence"] for r in new) > old_max, (
        f"sequence restarted at {min(r['sequence'] for r in new)} after {old_max} (A3: must continue)"
    )
    ids = [r["event_id"] for r in c.sink.records(victim)]
    assert len(ids) == len(set(ids)), "event ids repeated across restart"
    boots = Counter(i.rsplit("-", 2)[1] for i in ids)
    assert len(boots) == 2 and old_boot in boots


def test_a_killed_node_does_not_stop_the_others(make_cluster):
    """A node process dying mid-run costs only that node (deadline fallback), the run completes."""
    c = make_cluster(ticks=TICKS, tick_interval_s=0.03)
    c.start_run("kill", episodes=TRAIN, seed=6)
    threading.Timer(1.0, lambda: c.nodes["node-02"].kill()).start()
    view = c.wait_run("kill", timeout=180)
    assert view["status"] == "completed", view
    assert view["nodes"]["node-02"]["health"] == "unavailable"
    for n in ("node-01", "node-03", "node-04"):
        assert view["nodes"][n]["health"] == "ready" and view["nodes"][n]["deadline_misses"] == 0
        assert c.node_status(n)["train_steps"] > 0

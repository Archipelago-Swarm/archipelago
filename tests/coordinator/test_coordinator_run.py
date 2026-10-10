"""Tick loop behavior against in-process fake nodes."""

from __future__ import annotations

import json
from pathlib import Path

from archipelago_sim2d.adapter import replay_final_hash_from_dir
from harness import default_policy, run_body


def metrics(events, name):
    return [e for e in events if e["kind"] == "metric_sample" and e["metric"] == name]


def replay_records(live, run_id, ep=0):
    d = live.settings.data_dir / "replays" / run_id / f"ep-{ep:04d}"
    return d, [json.loads(x) for x in (d / "replay.jsonl").read_text().splitlines()]


def test_privacy_each_node_gets_only_its_own_observation(live, nodes):
    lv, ns = live(), nodes()
    lv.start_run(run_body("priv", ns, ticks=15))
    lv.wait_done("priv")
    for n, node in ns.items():
        assert node.violations == [], (n, node.violations)
        assert [a["tick"] for a in node.acts] == list(range(15))
        assert {a["observation"]["source_node_id"] for a in node.acts} == {n}
        assert all(a["run_id"] == "priv" and a["deadline_ms"] == 500 for a in node.acts)


def test_run_applies_node_actions_and_sends_feedback(live, nodes):
    lv, ns = live(), nodes()
    lv.start_run(run_body("fb", ns, ticks=10))
    lv.wait_done("fb")
    _, recs = replay_records(lv, "fb")
    for r in recs:
        for n in ns:
            assert r["actions"][n] == default_policy(n, 0, r["tick"] - 1, {})
    for node in ns.values():
        assert [f["tick"] for f in node.feedback] == list(range(10))
        last = node.feedback[-1]
        assert last["truncated"] is True and last["terminated"] is False
        assert last["next_observation"]["source_node_id"] == node.node_id
        assert isinstance(last["reward"], float)


def test_stalled_node_falls_back_to_stay_and_does_not_delay_others(live, nodes):
    lv = live()
    ns = nodes(**{"node-2": {"stall": lambda ep, tick: 2.0}})
    lv.start_run(run_body("stall", ns, ticks=12, deadline_ms=200))
    s = lv.wait_done("stall", timeout=60)
    n2 = s["nodes"]["node-2"]
    assert n2["deadline_misses"] == 5 and n2["health"] == "unavailable"
    assert all(s["nodes"][n]["deadline_misses"] == 0 for n in ("node-0", "node-1", "node-3"))
    # misses cost at most the deadline (plus scheduling slack), not the 2 s stall
    assert s["timing"]["max_tick_ms"] < 200 + 400
    events = lv.events("stall")
    miss = metrics(events, "deadline_missed")
    assert [e["source_node_id"] for e in miss] == ["node-2"] * 5
    assert [e["sim_tick"] for e in miss] == [0, 1, 2, 3, 4]
    assert [e["source_node_id"] for e in metrics(events, "node_unavailable")] == ["node-2"]
    # unavailable nodes are not called again; healthy nodes acted on all 12 ticks
    assert len(ns["node-2"].acts) == 5
    for n in ("node-0", "node-1", "node-3"):
        assert [a["tick"] for a in ns[n].acts] == list(range(12))
        assert len(ns[n].feedback) == 12
    assert ns["node-2"].feedback == []  # a stayed tick is never paired with the node's own action
    d, recs = replay_records(lv, "stall")
    assert all(r["actions"]["node-2"] == "stay" for r in recs)
    assert all(e["event"] != "missing_action" for r in recs for e in r["events"])
    assert any(r["actions"]["node-0"] != "stay" for r in recs)
    assert replay_final_hash_from_dir(d) == s["episodes_done"][0]["final_state_hash"]


def test_invalid_and_mismatched_responses_count_as_misses(live, nodes):
    lv = live()
    ns = nodes(
        **{
            "node-1": {"corrupt": lambda ep, t: "garbage" if t == 2 else None},
            "node-3": {"corrupt": lambda ep, t: "wrong_tick" if t == 3 else None},
        }
    )
    lv.start_run(run_body("bad", ns, ticks=8))
    s = lv.wait_done("bad")
    assert s["nodes"]["node-1"]["deadline_misses"] == 1
    assert s["nodes"]["node-3"]["deadline_misses"] == 1
    assert s["nodes"]["node-1"]["health"] == "ready"  # a single miss does not make it unavailable
    _, recs = replay_records(lv, "bad")
    by_tick = {r["tick"]: r["actions"] for r in recs}
    assert by_tick[3]["node-1"] == "stay"  # executed tick index 2 -> record tick 3
    assert by_tick[4]["node-3"] == "stay"
    assert by_tick[3]["node-0"] == default_policy("node-0", 0, 2, {})


def test_consecutive_miss_counter_resets_after_a_good_action(live, nodes):
    lv = live()
    ns = nodes(
        **{
            "node-0": {
                "corrupt": lambda ep, t: "garbage" if t in (0, 1, 2, 3, 5, 6, 7, 8) else None
            }
        }
    )
    lv.start_run(run_body("reset", ns, ticks=10))
    s = lv.wait_done("reset")
    assert s["nodes"]["node-0"]["deadline_misses"] == 8
    assert s["nodes"]["node-0"]["health"] == "ready"  # never 5 in a row


def test_duplicate_node_responses_are_not_reapplied(live, nodes):
    """A node that answers with a cached/older tick (duplicate or stale) gets stay, not replay."""
    lv = live()
    ns = nodes(**{"node-2": {"corrupt": lambda ep, t: "wrong_tick" if t >= 1 else None}})
    lv.start_run(run_body("dup", ns, ticks=6))
    s = lv.wait_done("dup")
    assert s["nodes"]["node-2"]["deadline_misses"] == 5
    assert s["nodes"]["node-2"]["health"] == "unavailable"


def test_kill_node_removes_drone_and_survivors_continue(live, nodes):
    lv, ns = live(), nodes()
    lv.start_run(run_body("kill", ns, ticks=20, kill_node={"node_id": "node-1", "tick": 5}))
    s = lv.wait_done("kill")
    assert s["nodes"]["node-1"]["health"] == "killed"
    assert [a["tick"] for a in ns["node-1"].acts] == list(range(5))
    for n in ("node-0", "node-2", "node-3"):
        assert [a["tick"] for a in ns[n].acts] == list(range(20))
        assert ns[n].violations == []
    events = lv.events("kill")
    snaps = [e for e in events if e["kind"] == "world_snapshot"]
    assert "node-1" in snaps[5]["poses"] and "node-1" not in snaps[6]["poses"]
    assert all(
        "node-1" not in {x for link in e["topology"]["links"] for x in link} for e in snaps[6:]
    )
    assert [e["sim_tick"] for e in metrics(events, "node_killed")] == [5]
    d, recs = replay_records(lv, "kill")
    m = json.loads((d / "manifest.json").read_text())
    assert m["removed_nodes"] == ["node-1"] and m["ticks"] == 20
    assert replay_final_hash_from_dir(d) == m["final_state_hash"]
    # the killed node got no feedback after the kill and episode_end still reached it
    assert [f["tick"] for f in ns["node-1"].feedback] == list(range(5))
    assert ns["node-1"].timeline[-1] == "control:episode_end"


def test_replay_reexecution_matches_final_hash_for_every_episode(live, nodes):
    lv, ns = live(), nodes()
    eps = [
        {"kind": "train", "seed": 3},
        {"kind": "validation", "seed": 4},
        {"kind": "test", "seed": 5},
    ]
    lv.start_run(run_body("rep", ns, ticks=14, episodes=eps))
    s = lv.wait_done("rep")
    assert len(s["episodes_done"]) == 3
    hashes = set()
    for i, ep in enumerate(s["episodes_done"]):
        d = Path(ep["replay_manifest"]).parent
        m = json.loads((d / "manifest.json").read_text())
        assert m["ticks"] == 14 and m["seed"] == eps[i]["seed"]
        assert replay_final_hash_from_dir(d) == m["final_state_hash"] == ep["final_state_hash"]
        hashes.add(m["final_state_hash"])
    assert len(hashes) == 3


def test_same_seed_and_policy_give_same_final_state_hash(live, nodes):
    lv, ns = live(), nodes()
    for rid, seed in (("det-a", 7), ("det-b", 7), ("det-c", 8)):
        lv.start_run(run_body(rid, ns, ticks=20, seed=seed))
        lv.wait_done(rid)
    h = {
        r: lv.status(r)["episodes_done"][0]["final_state_hash"] for r in ("det-a", "det-b", "det-c")
    }
    assert h["det-a"] == h["det-b"] != h["det-c"]


def test_node_unavailable_in_one_episode_recovers_at_next_reset(live, nodes):
    lv = live()
    ns = nodes(**{"node-2": {"stall": lambda ep, t: 1.5 if ep == 0 else 0.0}})
    eps = [{"kind": "train", "seed": 1}, {"kind": "train", "seed": 2}]
    lv.start_run(run_body("recover", ns, ticks=8, episodes=eps, deadline_ms=150))
    s = lv.wait_done("recover", timeout=60)
    assert s["nodes"]["node-2"]["health"] == "ready"
    assert [a["tick"] for a in ns["node-2"].acts if a["episode"] == 1] == list(range(8))


def test_telemetry_outage_drops_only_the_event_sink(live, nodes):
    lv, ns = live(), nodes()
    lv.start_run(
        run_body("outage", ns, ticks=16, telemetry_outage={"start_tick": 5, "end_tick": 10})
    )
    s = lv.wait_done("outage")
    events = lv.events("outage")
    ticks = {e["sim_tick"] for e in events}
    assert ticks.isdisjoint(range(6, 11)) and {5, 11, 16} <= ticks
    assert s["events_dropped"] > 0
    seqs = [e["sequence"] for e in events]
    assert seqs == list(range(1, len(seqs) + 1))  # sink gap leaves no sequence hole
    for n in ns.values():  # the world and node links were unaffected
        assert [a["tick"] for a in n.acts] == list(range(16))
        assert len(n.feedback) == 16

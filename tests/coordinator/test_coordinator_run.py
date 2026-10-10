"""Tick loop behavior against in-process fake nodes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archipelago_sim2d.adapter import replay_final_hash_from_dir
from coord_harness import default_policy, run_body


def metrics(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [e for e in events if e["kind"] == "metric_sample" and e["metric"] == name]


def replay_records(live: Any, run_id: str, ep: int = 0) -> tuple[Path, list[dict[str, Any]]]:
    d = live.settings.data_dir / "replays" / run_id / f"ep-{ep:04d}"
    return d, [json.loads(x) for x in (d / "replay.jsonl").read_text().splitlines()]


def test_privacy_each_node_gets_only_its_own_observation(live: Any, nodes: Any) -> None:
    lv, ns = live(), nodes()
    lv.start_run(run_body("priv", ns, ticks=15))
    lv.wait_done("priv")
    for n, node in ns.items():
        assert node.violations == [], (n, node.violations)
        assert [a["tick"] for a in node.acts] == list(range(15))
        assert {a["observation"]["source_node_id"] for a in node.acts} == {n}
        assert all(a["run_id"] == "priv" and a["deadline_ms"] == 500 for a in node.acts)


def test_run_applies_node_actions_and_sends_feedback(live: Any, nodes: Any) -> None:
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


def test_stalled_node_falls_back_to_stay_and_does_not_delay_others(live: Any, nodes: Any) -> None:
    lv = live()
    ns = nodes(**{"node-2": {"stall": lambda ep, tick: 3.0}})
    lv.start_run(run_body("stall", ns, ticks=12, deadline_ms=200))
    s = lv.wait_done("stall", timeout=60)
    n2 = s["nodes"]["node-2"]
    assert n2["deadline_misses"] == 5 and n2["health"] == "unavailable"
    assert all(s["nodes"][n]["deadline_misses"] == 0 for n in ("node-0", "node-1", "node-3"))
    # Misses cost about the 200 ms deadline, not the 3 s stall. The bound is deliberately generous
    # (half the stall) so scheduler jitter on a loaded CI host cannot flip it; a coordinator that
    # waited for the stalled node would take >= 3000 ms per tick.
    assert s["timing"]["max_tick_ms"] < 1500
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


def test_invalid_and_mismatched_responses_count_as_misses(live: Any, nodes: Any) -> None:
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


def test_consecutive_miss_counter_resets_after_a_good_action(live: Any, nodes: Any) -> None:
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


def test_wrong_tick_replies_are_misses_not_applied(live: Any, nodes: Any) -> None:
    """A node answering with an older tick (a cached/stale reply) gets stay and a miss."""
    lv = live()
    ns = nodes(**{"node-2": {"corrupt": lambda ep, t: "wrong_tick" if t >= 1 else None}})
    lv.start_run(run_body("wrong", ns, ticks=6))
    s = lv.wait_done("wrong")
    assert s["nodes"]["node-2"]["deadline_misses"] == 5
    assert s["nodes"]["node-2"]["health"] == "unavailable"


def east_policy(node: str, episode: int, tick: int, obs: Any) -> str:
    return "east"


def stay_policy(node: str, episode: int, tick: int, obs: Any) -> str:
    return "stay"


def step_keys(records: list[dict[str, Any]]) -> list[tuple[int, int]]:
    return [(r["episode"], r["tick"]) for r in records]


def test_coordinator_sends_each_step_key_once_and_discards_late_replies(
    live: Any, nodes: Any
) -> None:
    """Guarantee: one act and one feedback per (episode, tick) per node, never replayed or
    retried; a reply that arrives after its tick was decided is dropped, not applied later."""
    lv = live()
    ns = nodes(
        **{
            "node-2": {
                "policy": east_policy,
                "stall": lambda ep, t: 0.6 if t == 1 else 0.0,
                "feedback_stall": lambda ep, t: 0.6 if t == 3 else 0.0,
            }
        }
    )
    lv.start_run(run_body("late", ns, ticks=8, deadline_ms=150))
    s = lv.wait_done("late")
    assert s["nodes"]["node-2"]["deadline_misses"] == 1  # only tick 1
    assert s["nodes"]["node-2"]["feedback_failures"] == 1  # only tick 3
    for n, node in ns.items():
        assert len(set(step_keys(node.acts))) == len(node.acts) == 8, n
        assert len(set(step_keys(node.feedback))) == len(node.feedback), n
    # tick 1: the late "east" never lands and no feedback is sent for the stayed tick;
    # the feedback that timed out at tick 3 is not retried
    assert [f["tick"] for f in ns["node-2"].feedback] == [0, 2, 3, 4, 5, 6, 7]
    _, recs = replay_records(lv, "late")
    by_tick = {r["tick"]: r["actions"]["node-2"] for r in recs}
    assert by_tick[2] == "stay"  # executed tick index 1
    assert by_tick[1] == by_tick[3] == by_tick[4] == "east"
    events = lv.events("late")
    assert [e["sim_tick"] for e in metrics(events, "deadline_missed")] == [1]
    assert [e["sim_tick"] for e in metrics(events, "feedback_failed")] == [3]


def test_kill_node_removes_drone_and_survivors_continue(live: Any, nodes: Any) -> None:
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


def test_replay_reexecution_matches_final_hash_for_every_episode(live: Any, nodes: Any) -> None:
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


def test_same_seed_and_policy_give_same_final_state_hash(live: Any, nodes: Any) -> None:
    lv, ns = live(), nodes()
    for rid, seed in (("det-a", 7), ("det-b", 7), ("det-c", 8)):
        lv.start_run(run_body(rid, ns, ticks=20, seed=seed))
        lv.wait_done(rid)
    h = {
        r: lv.status(r)["episodes_done"][0]["final_state_hash"] for r in ("det-a", "det-b", "det-c")
    }
    assert h["det-a"] == h["det-b"] != h["det-c"]


def test_node_unavailable_in_one_episode_recovers_at_next_reset(live: Any, nodes: Any) -> None:
    lv = live()
    ns = nodes(**{"node-2": {"stall": lambda ep, t: 1.5 if ep == 0 else 0.0}})
    eps = [{"kind": "train", "seed": 1}, {"kind": "train", "seed": 2}]
    lv.start_run(run_body("recover", ns, ticks=8, episodes=eps, deadline_ms=150))
    s = lv.wait_done("recover", timeout=60)
    assert s["nodes"]["node-2"]["health"] == "ready"
    assert [a["tick"] for a in ns["node-2"].acts if a["episode"] == 1] == list(range(8))


def test_telemetry_outage_drops_only_the_event_sink(live: Any, nodes: Any) -> None:
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


def terminated_flags(node: Any, episode: int = 0) -> list[tuple[int, bool, bool]]:
    return [
        (f["tick"], f["terminated"], f["truncated"])
        for f in node.feedback
        if f["episode"] == episode
    ]


def test_battery_termination_ends_one_drone_and_the_others_continue(live: Any, nodes: Any) -> None:
    # node-0 moves every tick (0.004 each) and runs out at its 5th step; the others stay
    # (0.001 each) and survive the 12-tick episode.
    lv = live(world_kwargs={"n_targets": 0, "battery_scale": 0.02})
    ns = nodes(
        **{
            "node-0": {"policy": lambda n, e, t, o: ("north", "south")[t % 2]},
            "node-1": {"policy": stay_policy},
            "node-2": {"policy": stay_policy},
            "node-3": {"policy": stay_policy},
        }
    )
    lv.start_run(run_body("dead", ns, ticks=12))
    s = lv.wait_done("dead")
    assert terminated_flags(ns["node-0"]) == [(i, i == 4, False) for i in range(5)]
    assert [a["tick"] for a in ns["node-0"].acts] == list(range(5))
    for n in ("node-1", "node-2", "node-3"):
        assert [a["tick"] for a in ns[n].acts] == list(range(12))
        assert terminated_flags(ns[n]) == [(i, False, i == 11) for i in range(12)]
        assert ns[n].violations == []
    assert ns["node-0"].timeline[-1] == "control:episode_end"
    assert s["nodes"]["node-0"]["deadline_misses"] == 0
    d, recs = replay_records(lv, "dead")
    assert any(
        e["event"] == "energy_exhausted" and e["node"] == "node-0"
        for r in recs
        for e in r["events"]
    )
    ep = s["episodes_done"][0]
    assert ep["ticks"] == 12
    assert replay_final_hash_from_dir(d) == ep["final_state_hash"]


def test_episode_ends_when_every_drone_has_terminated_and_next_episode_starts(
    live: Any, nodes: Any
) -> None:
    # all drones stay (0.001 each) with battery for 20 ticks; the plan allows 60
    lv = live(world_kwargs={"n_targets": 0, "battery_scale": 0.02})
    ns = nodes(**{f"node-{i}": {"policy": stay_policy} for i in range(4)})
    eps = [{"kind": "train", "seed": 1}, {"kind": "validation", "seed": 2}]
    lv.start_run(run_body("gone", ns, ticks=60, episodes=eps))
    s = lv.wait_done("gone")
    first, second = s["episodes_done"]
    assert first["ticks"] == 20 and second["ticks"] == 20  # loop exit on an empty live set
    for node in ns.values():
        train_fb = terminated_flags(node, 0)
        assert [t for t, _, _ in train_fb] == list(range(20))
        assert [term for _, term, _ in train_fb] == [False] * 19 + [True]
        assert [a["tick"] for a in node.acts if a["episode"] == 1] == list(range(20))
        assert node.violations == []
    for ep in (first, second):
        d = Path(ep["replay_manifest"]).parent
        m = json.loads((d / "manifest.json").read_text())
        assert m["ticks"] == 20
        assert replay_final_hash_from_dir(d) == m["final_state_hash"] == ep["final_state_hash"]

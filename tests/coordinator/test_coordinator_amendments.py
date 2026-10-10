"""Coordinator side of live-runtime.md sections 13-14: A2, A4, A5, A7, A9, A10, A13, A14.

Holds in the fake nodes are released by the test after it has observed the coordinator's reaction,
so no assertion depends on how loaded the machine is.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from archipelago_coordinator.sim import min_survival_ticks
from archipelago_sim.env import GridWorld
from coord_harness import ACTIONS, ADMIN_TOKEN, BATTERY_SCALE, run_body


def wait_for(pred: Callable[[], bool], timeout: float = 60.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def fixed(cmd: str) -> Callable[[str, int, int, Any], str]:
    return lambda node, ep, tick, obs: cmd


def metrics(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [e for e in events if e["kind"] == "metric_sample" and e["metric"] == name]


# ---------------------------------------------------------------- A2: feedback and the barrier


def test_feedback_reports_the_executed_action_and_acks_precede_the_next_act_round(
    live: Any, nodes: Any
) -> None:
    lv = live()
    ns = nodes(
        **{
            "node-0": {"policy": fixed("east")},
            "node-1": {"policy": fixed("north")},
            "node-2": {"policy": fixed("stay")},
            "node-3": {"policy": fixed("west")},
        }
    )
    lv.start_run(run_body("barrier", ns, ticks=6))
    lv.wait_done("barrier")
    want = {"node-0": "east", "node-1": "north", "node-2": "stay", "node-3": "west"}
    for n, node in ns.items():
        assert node.violations == [], n
        assert len(node.feedback) == 6
        for f in node.feedback:
            assert f["executed_command"] == want[n]
            assert f["action_index"] == ACTIONS.index(want[n])
            assert f["deadline_missed"] is False
    journal = ns["node-0"].journal.snapshot()
    pos = {(n, k, ep, t, ph): i for i, (n, k, ep, t, ph) in enumerate(journal)}
    for t in range(5):  # every feedback(t) ack is back before any act(t+1) is even sent
        last_ack = max(pos[(n, "feedback", 0, t, "end")] for n in ns)
        first_act = min(pos[(n, "act", 0, t + 1, "start")] for n in ns)
        assert last_ack < first_act, t


def test_a_slow_feedback_ack_holds_back_the_next_act_round(live: Any, nodes: Any) -> None:
    lv = live()
    slow = threading.Event()
    ns = nodes(**{"node-1": {"feedback_stall": lambda ep, t: slow if t == 2 else None}})
    try:
        # the bound is 2 * deadline_ms (6 s here); the test releases the ack long before that
        lv.start_run(run_body("slowack", ns, ticks=5, deadline_ms=3000))
        wait_for(lambda: ("feedback", 0, 2) in ns["node-1"].held)
        assert not any(t == 3 for node in ns.values() for t in (a["tick"] for a in node.acts))
        slow.set()
        s = lv.wait_done("slowack")
    finally:
        slow.set()
    assert s["nodes"]["node-1"]["feedback_failures"] == 0
    journal = ns["node-1"].journal.snapshot()
    ack = journal.index(("node-1", "feedback", 0, 2, "end"))
    for n in ns:
        assert journal.index((n, "act", 0, 3, "start")) > ack


# ---------------------------------------------------------------- A5: configure


def test_configure_is_sent_once_per_run_before_the_first_reset_with_the_plans_values(
    live: Any, nodes: Any
) -> None:
    lv, ns = live(), nodes()
    cfg = {
        "hyperparameters": {"lr": 0.005, "hidden": 16},
        "epsilon_schedule": {"start": 0.9, "end": 0.1, "decay_episodes": 7},
        "margin": 0.25,
        "gate_seeds": [777, 778],
        "n_validation_agents": 2,
        "exchange_every_ticks": 25,
        "seed": 42,
    }
    eps = [{"kind": "train", "seed": s} for s in (1, 2, 3)]
    lv.start_run(run_body("cfg", ns, ticks=10, episodes=eps, battery_scale=8.0, node_config=cfg))
    s = lv.wait_done("cfg")
    expected = {
        "command": "configure",
        "run_id": "cfg",
        "hyperparameters": {
            "lr": 0.005,
            "gamma": 0.95,
            "hidden": 16,
            "capacity": 5000,
            "batch": 32,
            "target_every": 50,
            "train_steps_per_feedback": 1,
        },  # fmt: skip
        "epsilon_schedule": {"start": 0.9, "end": 0.1, "decay_episodes": 7},
        "margin": 0.25,
        "world_config": {
            "size": 16,
            "n_targets": 0,
            "obstacle_density": 0.12,
            "sense_radius": 2,
            "max_ticks": 10,
            "battery_scale": 8.0,
            "reward_id": "rew-v0",
        },  # fmt: skip
        "gate_seeds": [777, 778],
        "n_validation_agents": 2,
        "encoder_id": "grid-flat-v1-s16-r2",
        "exchange_every_ticks": 25,
        "seed": 42,
    }
    for n, node in ns.items():
        assert node.violations == [], n
        configures = [c for c in node.controls if c["command"] == "configure"]
        assert configures == [expected]
        assert node.timeline.index("control:configure") < node.timeline.index("control:reset")
        assert [c["command"] for c in node.controls].count("reset") == 3
    assert s["node_config_hashes"] == dict.fromkeys(ns, "c" * 16)


def test_a_node_that_refuses_configure_is_not_driven_but_still_gets_episode_end(
    live: Any, nodes: Any
) -> None:
    lv, ns = live(), nodes(**{"node-3": {"configure_status": 409}})
    lv.start_run(run_body("refuse", ns, ticks=5))
    s = lv.wait_done("refuse")
    assert s["nodes"]["node-3"]["health"] == "unavailable"
    assert ns["node-3"].acts == [] and "control:reset" not in ns["node-3"].timeline
    assert [e["source_node_id"] for e in metrics(lv.events("refuse"), "node_unavailable")] == [
        "node-3"
    ]
    for n in ("node-0", "node-1", "node-2"):
        assert [a["tick"] for a in ns[n].acts] == list(range(5))
    assert ns["node-3"].timeline[-1] == "control:episode_end"  # unavailable is not killed (A4)


# ---------------------------------------------------------------- A4: episode_end


def test_episode_end_reaches_every_live_node_and_a_stuck_ack_never_stalls_the_run(
    live: Any, nodes: Any
) -> None:
    lv = live()
    stuck = threading.Event()
    ns = nodes(
        **{
            "node-0": {"policy": lambda n, e, t, o: ("north", "south")[t % 2]},
            "node-1": {
                "policy": fixed("stay"),
                "episode_end_stall": lambda ep: stuck if ep == 0 else None,
            },
            "node-2": {"policy": fixed("stay")},
            "node-3": {"policy": fixed("stay")},
        }
    )
    eps = [{"kind": "train", "seed": 1}, {"kind": "train", "seed": 2}]
    try:
        # node-0 runs out of battery in episode 0 (terminated, but still part of the world);
        # node-1 never acknowledges episode_end of episode 0 until the test lets go
        lv.start_run(run_body("end", ns, ticks=12, episodes=eps, battery_scale=0.02))
        s = lv.wait_done("end", timeout=120)
    finally:
        stuck.set()
    first, second = s["episodes_done"]
    assert first["ticks"] == 12 and first["episode_end_failed"] == ["node-1"]
    assert second["episode_end_failed"] == []
    # the run went on: every surviving node played the whole of episode 1
    for n in ("node-1", "node-2", "node-3"):
        assert [a["tick"] for a in ns[n].acts if a["episode"] == 1] == list(range(12)), n
    for n, node in ns.items():
        ends = [c for c in node.controls if c["command"] == "episode_end"]
        assert [(c["episode"], c["tick"]) for c in ends] == [(0, 12), (1, 12)], n
        assert node.violations == [], n
    assert first["episode_end_sent"] == list(ns)  # the terminated node-0 is included
    assert {n: w for n, w in first["window_ids"].items() if n != "node-1"} == {
        "node-0": "w1", "node-2": "w1", "node-3": "w1",
    }  # fmt: skip
    assert set(second["window_ids"]) == set(ns)  # every ack, node-1's included, is recorded
    assert {n: w for n, w in second["window_ids"].items() if n != "node-1"} == {
        "node-0": "w2", "node-2": "w2", "node-3": "w2",
    }  # fmt: skip


def test_reset_waits_longer_than_a_control_call_for_a_node_closing_its_window(
    live: Any, nodes: Any
) -> None:
    """A node's reset may wait up to 5 s for its exchange window (A4); the coordinator must not
    declare it unavailable after the ordinary 2 s control timeout."""
    lv = live()
    closing = threading.Event()
    ns = nodes(**{"node-2": {"reset_stall": lambda ep: closing if ep == 1 else None}})
    eps = [{"kind": "train", "seed": 1}, {"kind": "train", "seed": 2}]
    try:
        lv.start_run(run_body("slowreset", ns, ticks=4, episodes=eps))
        wait_for(lambda: ("reset", 1, 0) in ns["node-2"].held)
        time.sleep(2.5)  # longer than the 2 s control timeout, shorter than the 5 s window wait
        closing.set()
        s = lv.wait_done("slowreset")
    finally:
        closing.set()
    assert s["nodes"]["node-2"]["health"] == "ready"
    assert [a["tick"] for a in ns["node-2"].acts if a["episode"] == 1] == list(range(4))


# ---------------------------------------------------------------- A9: server-side plan


def test_a_request_cannot_supply_a_plan_or_node_urls(live: Any, nodes: Any) -> None:
    lv, ns = live(), nodes()
    req = run_body("sneaky", ns, ticks=5)
    code, out = lv.call("POST", "/v1/runs", {**req.wire(), "plan": req.plan})
    assert code == 422 and "node_urls" in out["detail"]
    other = nodes(1)
    code, out = lv.call("POST", "/v1/runs", {**req.wire(), "node_urls": {"node-0": "http://x"}})
    assert code == 422 and out["error"] == "invalid_request"
    assert lv.call("GET", "/v1/runs/sneaky")[0] == 404
    assert all(n.controls == [] and n.acts == [] for n in [*ns.values(), *other.values()])


def test_plan_file_hash_and_name_are_recorded_in_the_run_manifest(live: Any, nodes: Any) -> None:
    lv, ns = live(), nodes()
    short = run_body("m", ns, ticks=4, episodes=[{"kind": "train", "seed": 1}]).plan
    longer = run_body("m", ns, ticks=4, episodes=[{"kind": "train", "seed": s} for s in (5, 6)])
    raw = json.dumps({"plans": {"short": short, "longer": longer.plan}}).encode()
    lv.plan_file.write_bytes(raw)
    body = {**longer.wire(), "plan_name": "longer"}
    body["run_config"] = {**body["run_config"], "run_id": "named"}
    assert lv.call("POST", "/v1/runs", body)[0] == 201
    s = lv.wait_done("named")
    digest = hashlib.sha256(raw).hexdigest()
    assert s["plan_name"] == "longer" and s["plan_file_sha256"] == digest
    assert [e["seed"] for e in s["episodes_done"]] == [5, 6]
    manifest = json.loads((lv.settings.data_dir / "runs" / "named" / "manifest.json").read_text())
    assert manifest["plan_file_sha256"] == digest and manifest["plan_name"] == "longer"
    assert manifest["plan"]["node_urls"] == {n: ns[n].url for n in ns}
    # with two plans and no "default", a request must name one
    code, out = lv.call(
        "POST", "/v1/runs", {**longer.wire(), "run_config": {**body["run_config"], "run_id": "n2"}}
    )
    assert code == 422 and "available" in out["detail"]


def test_missing_plan_file_is_a_visible_503(live: Any, nodes: Any, tmp_path: Path) -> None:
    lv, ns = live(plan_file=tmp_path / "absent.json"), nodes()
    code, out = lv.call("POST", "/v1/runs", run_body("noplan", ns, ticks=3).wire())
    assert code == 503 and out["error"] == "plan_unavailable"
    assert lv.call("GET", "/v1/runs/noplan")[0] == 404


# ---------------------------------------------------------------- A10: snapshots


def test_public_stream_hides_undiscovered_obstacles_and_the_admin_view_shows_everything(
    live: Any, nodes: Any
) -> None:
    lv, ns = live(start_paused=True, world_kwargs={"n_targets": 2}), nodes()
    lv.start_run(run_body("vis", ns, ticks=30, battery_scale=BATTERY_SCALE))
    lv.wait("vis", lambda s: s["status"] == "paused")
    code, priv = lv.call("GET", "/v1/runs/vis/snapshot", token=ADMIN_TOKEN)
    assert code == 200
    hidden = priv["privileged"]
    assert len(hidden["targets"]) == 2 and hidden["found"] == []
    assert set(hidden["battery"]) == set(ns)
    assert all(abs(b - BATTERY_SCALE) < 1e-6 for b in hidden["battery"].values())
    all_obstacles = {tuple(o) for o in priv["obstacles"]}
    for i in range(4):
        assert lv.command("vis", f"s{i}", "step")[0] == 200
        lv.wait("vis", lambda s, i=i: s["tick"] == i + 1)
    public = [e for e in lv.events("vis") if e["kind"] == "world_snapshot"]
    assert len(public) == 5
    assert all("privileged" not in e and "targets" not in e and "battery" not in e for e in public)
    seen: list[set[tuple[int, int]]] = [{tuple(o) for o in e["obstacles"]} for e in public]
    assert seen[0] < all_obstacles  # strictly fewer: the rest is undiscovered
    assert all(a <= b for a, b in zip(seen, seen[1:], strict=False))  # discovery only grows
    assert seen[-1] <= all_obstacles
    visited = {(int(p["x"]), int(p["y"])) for e in public for p in e["poses"].values()}
    for ox, oy in seen[-1]:  # every published obstacle was within sensing range of some drone
        assert any(max(abs(ox - x), abs(oy - y)) <= 2 for x, y in visited), (ox, oy)
    lv.command("vis", "stop", "stop")
    lv.wait_done("vis")


def test_privileged_snapshots_carry_fresh_ids(live: Any, nodes: Any) -> None:
    lv, ns = live(start_paused=True), nodes()
    lv.start_run(run_body("ids", ns, ticks=5))
    lv.wait("ids", lambda s: s["status"] == "paused")
    a = lv.call("GET", "/v1/runs/ids/snapshot", token=ADMIN_TOKEN)[1]
    b = lv.call("GET", "/v1/runs/ids/snapshot", token=ADMIN_TOKEN)[1]
    assert a["run_id"] == b["run_id"] == "ids"
    assert a["event_id"] != b["event_id"] and a["sequence"] != b["sequence"]
    lv.command("ids", "stop", "stop")
    lv.wait_done("ids")


# ---------------------------------------------------------------- A13: battery and schedules


def window(start: int, end: int) -> dict[str, Any]:
    return {"start_tick": start, "end_tick": end, "cut_links": [["node-0", "node-1"]]}


@pytest.mark.parametrize("scale", [0.02, 1.0, 4.0])
def test_min_survival_ticks_is_what_the_world_does_to_a_drone_that_always_moves(
    scale: float,
) -> None:
    w = GridWorld(
        n_agents=1, n_targets=0, obstacle_density=0.0, battery_scale=scale, max_ticks=9999
    )
    w.reset(seed=0, starts={"node-0": (8, 8)})
    while w.agents:
        w.step({"node-0": ("east", "west")[w.tick % 2]})
    assert w.tick == min_survival_ticks(scale)


@pytest.mark.parametrize(
    ("scale", "ticks", "win"),
    [
        (1.0, 900, (300, 600)),  # drones are dead by tick ~250: the cut can never be lived through
        (4.0, 1100, (900, 1001)),  # just past the 1000 ticks a moving drone survives
        (4.0, 500, (300, 600)),  # battery would do, but the episode ends at 500
    ],
)
def test_unreachable_fault_schedules_are_rejected_before_anything_starts(
    live: Any, nodes: Any, scale: float, ticks: int, win: tuple[int, int]
) -> None:
    lv, ns = live(), nodes()
    req = run_body("far", ns, ticks=ticks, battery_scale=scale, fault_schedule=[window(*win)])
    code, out = lv.call("POST", "/v1/runs", req)
    assert code == 422 and "fault window" in out["detail"], out
    assert lv.call("GET", "/v1/runs/far")[0] == 404
    assert all(n.controls == [] and n.acts == [] for n in ns.values())


def test_the_demonstration_schedule_is_accepted_at_battery_scale_four(
    live: Any, nodes: Any
) -> None:
    lv, ns = live(start_paused=True), nodes()
    req = run_body("demo", ns, ticks=900, battery_scale=4.0, fault_schedule=[window(300, 600)])
    lv.start_run(req)
    lv.wait("demo", lambda s: s["status"] == "paused")
    priv = lv.call("GET", "/v1/runs/demo/snapshot", token=ADMIN_TOKEN)[1]
    assert all(abs(b - 4.0) < 1e-6 for b in priv["privileged"]["battery"].values())
    for node in ns.values():
        cfg = next(c for c in node.controls if c["command"] == "configure")
        assert cfg["world_config"]["battery_scale"] == 4.0
        assert cfg["world_config"]["max_ticks"] == 900
    lv.command("demo", "stop", "stop")
    lv.wait_done("demo")


# ---------------------------------------------------------------- A7 and A14: ids and time


def test_each_episode_has_its_own_config_and_every_record_carries_global_time(
    live: Any, nodes: Any
) -> None:
    lv, ns = live(), nodes()
    t_start = datetime.now(UTC)
    eps = [{"kind": "train", "seed": s} for s in (3, 4, 5)]
    lv.start_run(run_body("glob", ns, ticks=6, episodes=eps))
    s = lv.wait_done("glob")
    t_end = datetime.now(UTC)
    # per-episode RunConfig: own run id suffix and env seed, recorded in the replay manifests
    for k, ep in enumerate(s["episodes_done"]):
        m = json.loads(Path(ep["replay_manifest"]).read_text())
        assert m["run_id"] == m["run_config"]["run_id"] == f"glob-e{k}"
        assert m["seed"] == m["run_config"]["seeds"]["env"] == (3, 4, 5)[k]
    # observations: distinct (run_id, event_id) across episodes, global sim_tick, wall-clock stamps
    for n, node in ns.items():
        keys = [(a["observation"]["run_id"], a["observation"]["event_id"]) for a in node.acts]
        assert len(set(keys)) == len(keys) == 18, n
        for a in node.acts:
            o = a["observation"]
            assert o["run_id"] == f"glob-e{a['episode']}"
            assert o["sim_tick"] == a["episode"] * 6 + a["tick"]
            stamp = datetime.fromisoformat(o["emitted_at_utc"])
            assert t_start <= stamp <= t_end, o["emitted_at_utc"]
    # the coordinator's own stream: global sim_tick, unique ids, contiguous sequences
    events = lv.events("glob")
    assert len({e["event_id"] for e in events}) == len(events)
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    snaps = [e for e in events if e["kind"] == "world_snapshot"]
    assert [e["sim_tick"] for e in snaps] == [k * 6 + t for k in range(3) for t in range(7)]
    returns = metrics(events, "episode_return")
    assert sorted({e["sim_tick"] for e in returns}) == [6, 12, 18]
    sim_ticks = [e["sim_tick"] for e in events]
    assert sim_ticks == sorted(sim_ticks)  # simulation time never runs backwards
    assert all(t_start <= datetime.fromisoformat(e["emitted_at_utc"]) <= t_end for e in events)


def test_fault_and_kill_ticks_stay_episode_local_while_records_are_global(
    live: Any, nodes: Any
) -> None:
    lv, ns = live(), nodes()
    eps = [{"kind": "train", "seed": 1}, {"kind": "train", "seed": 2}]
    lv.start_run(
        run_body(
            "local",
            ns,
            ticks=10,
            episodes=eps,
            kill_node={"node_id": "node-1", "tick": 4},
            fault_schedule=[window(2, 6)],
        )  # fmt: skip
    )
    lv.wait_done("local")
    events = lv.events("local")
    assert [e["sim_tick"] for e in metrics(events, "node_killed")] == [4, 14]
    phases = [(e["sim_tick"], e["phase"]) for e in metrics(events, "fault_phase")]
    assert phases == [(2, "partition"), (6, "recovery"), (12, "partition"), (16, "recovery")]
    assert [a["tick"] for a in ns["node-1"].acts] == [0, 1, 2, 3, 0, 1, 2, 3]

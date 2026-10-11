"""Missions through the coordinator: plan selection, per-episode maps, telemetry, validation."""

from __future__ import annotations

from typing import Any

from coord_harness import run_body

MISSION = {
    "id": "sr-live",
    "type": "search_rescue",
    "n_targets": 3,
    "dynamics": {"targets_move_every": 4, "targets_appear": 1, "obstacles_shift_every": 6},
}


def metrics(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [e for e in events if e["kind"] == "metric_sample" and e["metric"] == name]


def test_every_episode_has_its_own_map_seed_in_events_and_summary(live: Any, nodes: Any) -> None:
    lv, ns = live(), nodes()
    body = run_body(
        "mp",
        ns,
        ticks=8,
        episodes=[{"kind": "train", "seed": 1, "count": 3}],
        mission=MISSION,
    )
    lv.start_run(body)
    s = lv.wait_done("mp")
    seeds = [m["value"] for m in metrics(lv.events("mp"), "map_seed")]
    assert len(seeds) == 3 and len(set(seeds)) == 3  # one per episode, all different
    assert [e["map_seed"] for e in s["episodes_done"]] == [int(v) for v in seeds]
    assert all(e["mission"]["id"] == "sr-live" for e in s["episodes_done"])


def test_snapshots_carry_mission_status_and_it_is_deterministic(live: Any, nodes: Any) -> None:
    def run(rid: str) -> list[dict[str, Any]]:
        lv, ns = live(), nodes()
        lv.start_run(run_body(rid, ns, ticks=10, mission=MISSION))
        lv.wait_done(rid)
        return [e for e in lv.events(rid) if e["kind"] == "world_snapshot"]

    snaps = run("ms1")
    m = snaps[0]["mission"]  # tick 0: the mission has just started
    assert snaps[-1]["mission"]["status"] in ("failed", "succeeded")  # budget = the 10 ticks
    assert (m["id"], m["type"], m["status"]) == ("sr-live", "search_rescue", "active")
    assert m["objectives"][0]["kind"] == "find_targets" and m["objectives"][0]["target"] == 4
    assert m["dynamics"] == ["targets_move", "targets_appear", "obstacles_shift"]
    assert m["time_budget_ticks"] == 10
    again = run("ms2")  # same seed and episode, different run id: same map
    assert again[-1]["mission"]["map_seed"] == m["map_seed"]


def test_run_without_a_mission_reports_none(live: Any, nodes: Any) -> None:
    lv, ns = live(), nodes()
    lv.start_run(run_body("nm", ns, ticks=5))
    lv.wait_done("nm")
    snaps = [e for e in lv.events("nm") if e["kind"] == "world_snapshot"]
    assert snaps and all(s.get("mission") is None for s in snaps)


def test_mission_failure_is_reported_once_when_the_budget_runs_out(live: Any, nodes: Any) -> None:
    lv, ns = live(), nodes()
    mission = {"type": "search_rescue", "n_targets": 1, "time_budget_ticks": 3}
    lv.start_run(run_body("mf", ns, ticks=10, mission=mission, battery_scale=10.0))
    lv.wait_done("mf")
    ev = lv.events("mf")
    assert len(metrics(ev, "mission_failed")) + len(metrics(ev, "mission_complete")) == 1
    last = [e for e in ev if e["kind"] == "world_snapshot"][-1]["mission"]
    assert last["status"] in ("failed", "succeeded")


def test_request_mission_overrides_the_plan_and_is_validated(live: Any, nodes: Any) -> None:
    lv, ns = live(), nodes()
    body = run_body("ov", ns, ticks=5, mission=MISSION)
    body["mission"] = {"type": "coverage", "n_targets": 0, "id": "cov-1"}
    lv.start_run(body)
    lv.wait_done("ov")
    last = [e for e in lv.events("ov") if e["kind"] == "world_snapshot"][-1]["mission"]
    assert (last["id"], last["type"]) == ("cov-1", "coverage")
    for bad in (
        {"type": "teleport"},  # unknown type: pydantic
        {"n_targets": 0},  # search_rescue with nothing to find: sim-side rule
        {"dynamics": {"targets_move_every": -2}},
        {"objectives": [{"id": "x", "kind": "find_targets", "target": 50}]},
    ):
        b = run_body("bad", ns, ticks=5)
        b["mission"] = bad
        code, out = lv.call("POST", "/v1/runs", b)
        assert code == 422, (bad, code, out)

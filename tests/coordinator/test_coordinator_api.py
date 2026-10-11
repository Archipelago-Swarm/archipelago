"""HTTP API: auth, lifecycle commands, episodes/schedules, events, restart, readiness."""

from __future__ import annotations

from typing import Any

import pytest
from archipelago_coordinator import Coordinator, Settings
from archipelago_coordinator.settings import ConfigError
from archipelago_coordinator.sim import SimulatorUnavailable
from coord_harness import ADMIN_TOKEN, COORD_TOKEN, NODE_TOKEN, run_body


def _window(start: int, end: int) -> dict[str, Any]:
    return {"start_tick": start, "end_tick": end, "cut_links": [["node-0", "node-1"]]}


def test_every_route_but_healthz_requires_the_right_token(live: Any, nodes: Any) -> None:
    lv, ns = live(), nodes()
    lv.start_run(run_body("auth", ns, ticks=5))
    lv.wait_done("auth")
    assert lv.call("GET", "/healthz", token=None)[0] == 200
    routes = [
        ("GET", "/readyz"),
        ("GET", "/v1/runs/auth"),
        ("GET", "/v1/runs/auth/events"),
        ("GET", "/v1/runs/auth/snapshot"),
        ("POST", "/v1/runs"),
        ("POST", "/v1/runs/auth/commands"),
    ]
    for m, p in routes:
        assert lv.call(m, p, {}, token=None)[0] == 401, p
        assert lv.call(m, p, {}, token="wrong-token-wrong-token-1")[0] == 401, p
    assert lv.call("GET", "/v1/runs/auth/events", token=ADMIN_TOKEN)[0] == 403
    assert lv.call("GET", "/v1/runs/auth/snapshot", token=COORD_TOKEN)[0] == 403
    assert lv.call("GET", "/v1/runs/auth/events", token=COORD_TOKEN)[0] == 200
    assert lv.call("GET", "/v1/nope", token=COORD_TOKEN)[0] == 404


def test_privileged_snapshot_is_admin_only_and_never_reaches_nodes(live: Any, nodes: Any) -> None:
    lv, ns = live(start_paused=True), nodes()
    lv.start_run(run_body("snap", ns, ticks=9))
    lv.wait("snap", lambda s: s["status"] == "paused")
    code, snap = lv.call("GET", "/v1/runs/snap/snapshot", token=ADMIN_TOKEN)
    assert code == 200 and snap["kind"] == "world_snapshot"
    assert set(snap["poses"]) == set(ns) and snap["sim_tick"] == 0
    lv.command("snap", "c1", "step")
    lv.wait("snap", lambda s: s["tick"] == 1)
    assert lv.call("GET", "/v1/runs/snap/snapshot", token=ADMIN_TOKEN)[1]["sim_tick"] == 1
    lv.command("snap", "c2", "resume")
    lv.wait_done("snap")
    assert all(n.violations == [] for n in ns.values())


def test_commands_are_idempotent_validated_and_revisioned(live: Any, nodes: Any) -> None:
    lv, ns = live(start_paused=True), nodes()
    lv.start_run(run_body("cmd", ns, ticks=12))
    s = lv.wait("cmd", lambda s: s["status"] == "paused")
    rev = s["revision"]
    assert s["tick"] == 0
    code, r1 = lv.command("cmd", "step-1", "step", rev)
    assert code == 200 and r1["revision"] == rev + 1 and r1["duplicate"] is False
    lv.wait("cmd", lambda s: s["tick"] == 1)
    # the same command_id again: no second step, same answer, revision unchanged
    code, again = lv.command("cmd", "step-1", "step", rev)
    assert code == 200 and again["duplicate"] is True and again["revision"] == r1["revision"]
    assert lv.status("cmd")["tick"] == 1 and lv.status("cmd")["revision"] == rev + 1
    # reusing the id for a different command is refused
    assert lv.command("cmd", "step-1", "stop", rev)[0] == 409
    # stale revision is refused
    assert lv.command("cmd", "step-2", "step", rev)[0] == 409
    assert lv.status("cmd")["tick"] == 1
    # invalid transitions: pause while paused
    assert lv.command("cmd", "p1", "pause")[0] == 409
    code, res = lv.command("cmd", "r1", "resume", rev + 1)
    assert code == 200 and res["status"] == "running"
    s = lv.wait_done("cmd")
    assert s["tick"] == 12 and s["stop_reason"] == "plan_complete"
    assert lv.command("cmd", "late", "pause")[0] == 409  # run is no longer active


def test_stop_ends_run_and_still_writes_the_partial_replay(live: Any, nodes: Any) -> None:
    lv, ns = live(start_paused=True), nodes()
    lv.start_run(run_body("stop", ns, ticks=50))
    lv.wait("stop", lambda s: s["status"] == "paused")
    for i in range(3):
        lv.command("stop", f"s{i}", "step")
        lv.wait("stop", lambda s, i=i: s["tick"] == i + 1)
    assert lv.command("stop", "halt", "stop")[0] == 200
    s = lv.wait("stop", lambda s: s["status"] == "completed")
    assert s["stop_reason"] == "stopped" and s["tick"] == 3
    assert s["episodes_done"][0]["ticks"] == 3
    assert lv.command("stop", "again", "resume")[0] == 409


def test_pause_halts_ticks_and_step_advances_exactly_one_tick(live: Any, nodes: Any) -> None:
    lv, ns = live(start_paused=True), nodes()
    lv.start_run(run_body("pause", ns, ticks=200))
    lv.wait("pause", lambda s: s["status"] == "paused")
    for want in (1, 2):  # each step releases exactly one tick, then the run is paused again
        assert lv.command("pause", f"s{want}", "step")[0] == 200
        lv.wait("pause", lambda s, w=want: s["tick"] == w)
    assert lv.status("pause")["status"] == "paused"
    for node in ns.values():
        assert [a["tick"] for a in node.acts] == [0, 1]
    assert lv.command("pause", "r", "resume")[0] == 200
    lv.wait("pause", lambda s: s["tick"] > 5)
    assert lv.command("pause", "p", "pause")[0] == 200
    lv.wait("pause", lambda s: s["status"] == "paused")
    assert lv.command("pause", "x", "stop")[0] == 200
    lv.wait("pause", lambda s: s["status"] == "completed")


def test_checkpoint_is_forwarded_once_per_command_to_live_nodes(live: Any, nodes: Any) -> None:
    lv, ns = live(start_paused=True), nodes()
    lv.start_run(run_body("ckpt", ns, ticks=10, kill_node={"node_id": "node-3", "tick": 0}))
    lv.wait("ckpt", lambda s: s["status"] == "paused")
    code, out = lv.command("ckpt", "c1", "checkpoint")
    assert code == 200 and out["checkpoint"]["failed"] == []
    assert out["checkpoint"]["requested"] == ["node-0", "node-1", "node-2", "node-3"]
    code, dup = lv.command("ckpt", "c1", "checkpoint")
    assert code == 200 and dup["duplicate"] is True
    for n, node in ns.items():
        assert [c["command"] for c in node.controls].count("checkpoint") == 1, n
    assert lv.command("ckpt", "c1", "pause")[0] == 409  # command_id reused for another command
    lv.command("ckpt", "go", "resume")
    lv.wait_done("ckpt")
    # a finished run rejects further transitions
    assert lv.command("ckpt", "c2", "checkpoint")[0] == 409
    assert lv.command("ckpt", "c3", "resume")[0] == 409


def test_unexpected_adapter_failure_is_a_rejected_request(live: Any, nodes: Any) -> None:
    lv, ns = live(), nodes()

    def boom(kwargs: Any) -> Any:
        raise KeyError("adapter exploded")

    lv.svc.adapter_factory = boom
    code, out = lv.call("POST", "/v1/runs", run_body("boom", ns, ticks=3))
    assert code == 422 and "KeyError" in out["detail"]
    assert lv.call("GET", "/v1/runs/boom")[0] == 404  # nothing was registered


def test_unhandled_handler_error_returns_500_and_the_server_keeps_serving(live: Any) -> None:
    lv = live()

    def broken(run_id: str) -> Any:
        raise RuntimeError("internal detail must not leak")

    lv.svc.get_run = broken
    code, out = lv.call("GET", "/v1/runs/any")
    assert code == 500 and out == {"error": "internal_error"}
    assert lv.call("GET", "/healthz", token=None)[0] == 200


def test_only_one_active_run_and_run_ids_are_not_reused(live: Any, nodes: Any) -> None:
    lv, ns = live(start_paused=True), nodes()
    lv.start_run(run_body("one", ns, ticks=5))
    code, out = lv.call("POST", "/v1/runs", run_body("two", ns, ticks=5))
    assert code == 409 and out["error"] == "run_active"
    lv.wait("one", lambda s: s["status"] == "paused")
    lv.command("one", "go", "resume")
    lv.wait_done("one")
    assert lv.call("POST", "/v1/runs", run_body("one", ns, ticks=5))[0] == 409
    assert lv.call("POST", "/v1/runs", run_body("two", ns, ticks=5))[0] == 201
    lv.wait("two", lambda s: s["status"] == "paused")
    lv.command("two", "go", "resume")
    lv.wait_done("two")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["run_config"].update(reward_id="rew-nope"),
        lambda b: b["plan"]["node_urls"].pop("node-3"),
        lambda b: b["plan"]["node_urls"].update({"node-9": "http://127.0.0.1:1"}),
        lambda b: b["plan"]["node_urls"].update({"node-0": "ftp://x"}),
        lambda b: b["run_config"]["nodes"][1].update(start_pose={"x": 0, "y": 0}),
        lambda b: b["run_config"]["nodes"][1].update(start_pose={"x": 99, "y": 0}),
        lambda b: b["plan"].update(kill_node={"node_id": "node-8", "tick": 1}),
        lambda b: b["plan"].update(
            fault_schedule=[{"start_tick": 5, "end_tick": 5, "cut_links": []}]
        ),
        lambda b: b["plan"].update(
            fault_schedule=[{"start_tick": 1, "end_tick": 5, "cut_links": [["node-0", "node-7"]]}]
        ),
        lambda b: b["plan"].update(fault_schedule=[_window(0, 300)]),  # A13: past the battery
        lambda b: b["plan"].update(node_config={"gate_seeds": [1]}),  # overlaps episode seed 1
        lambda b: b.update(plan_name="nope"),
    ],
)
def test_invalid_run_requests_are_rejected_without_starting(
    live: Any, nodes: Any, mutate: Any
) -> None:
    lv, ns = live(), nodes()
    body = run_body("bad", ns, ticks=5)
    mutate(body)
    code, out = lv.call("POST", "/v1/runs", body)
    assert code == 422 and out["error"] == "invalid_request", out
    assert lv.call("GET", "/v1/runs/bad")[0] == 404
    assert lv.call("POST", "/v1/runs", run_body("ok", ns, ticks=3))[0] == 201  # no stuck run


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["plan"].update(episodes=[]),
        lambda b: b["plan"].update(surprise=1),
        lambda b: b["plan"].update(battery_scale=0),
    ],
)
def test_a_broken_server_side_plan_is_a_503_not_a_client_error(
    live: Any, nodes: Any, mutate: Any
) -> None:
    lv, ns = live(), nodes()
    body = run_body("badplan", ns, ticks=5)
    mutate(body)
    code, out = lv.call("POST", "/v1/runs", body)
    assert code == 503 and out["error"] == "plan_unavailable", out
    assert lv.call("GET", "/v1/runs/badplan")[0] == 404


def test_episode_order_modes_and_fault_schedule_distribution(live: Any, nodes: Any) -> None:
    lv, ns = live(), nodes()
    sched = [
        {"start_tick": 5, "end_tick": 10, "cut_links": [["node-0", "node-1"], ["node-2", "node-3"]]}
    ]
    eps = [
        {"kind": "train", "seed": 11},
        {"kind": "validation", "seed": 12},
        {"kind": "train", "seed": 13, "count": 2},
        {"kind": "test", "seed": 100},
    ]
    lv.start_run(run_body("plan", ns, ticks=14, episodes=eps, fault_schedule=sched, eval_every=2))
    s = lv.wait_done("plan")
    expected = [("train", 11), ("validation", 12), ("train", 13), ("train", 14), ("test", 100)]
    assert [(e["kind"], e["seed"]) for e in s["episodes_done"]] == expected
    for node in ns.values():
        resets = [c for c in node.controls if c["command"] == "reset"]
        assert [(c["episode"], c["mode"]) for c in resets] == [
            (0, "train"), (1, "eval"), (2, "train"), (3, "train"), (4, "eval"),
        ]  # fmt: skip
        # per episode: configure (first only) -> reset -> acts -> episode_end, no interleaving
        runs = []
        cur: list[str] = []
        for item in node.timeline:
            if item == "control:reset" and cur and cur != ["control:configure"]:
                runs.append(cur)
                cur = []
            cur.append(item)
        runs.append(cur)
        assert len(runs) == 5
        assert runs[0][:2] == ["control:configure", "control:reset"]
        runs[0] = runs[0][1:]
        for i, seq in enumerate(runs):
            assert seq[0] == "control:reset" and seq[-1] == "control:episode_end"
            body = seq[1:-1]
            assert body.count("act") == 14
            # eval episodes (validation, test) never train: no feedback
            assert body.count("feedback") == (0 if i in (1, 4) else 14)
        assert [c["fault_schedule"] for c in resets] == [sched] * 5  # same schedule every reset
        assert node.violations == []
        assert [a["episode"] for a in node.acts] == sorted(a["episode"] for a in node.acts)
    # frozen test/validation episodes use mode eval; mode is the only difference in control
    events = lv.events("plan")
    ep0 = [e for e in events if e["kind"] == "world_snapshot"][:15]
    links_at = {e["sim_tick"]: {tuple(x) for x in e["topology"]["links"]} for e in ep0}
    assert len(links_at[4]) == 6 and len(links_at[7]) == 4 and len(links_at[10]) == 6
    assert ("node-0", "node-1") not in links_at[7] and ("node-0", "node-2") in links_at[7]
    fp = [e for e in events if e["kind"] == "metric_sample" and e["metric"] == "fault_phase"]
    assert [(e["sim_tick"], e["phase"]) for e in fp[:2]] == [(5, "partition"), (10, "recovery")]


def test_event_ids_are_unique_and_sequences_page_contiguously(live: Any, nodes: Any) -> None:
    lv, ns = live(), nodes()
    for rid in ("ev-a", "ev-b"):
        lv.start_run(run_body(rid, ns, ticks=6))
        lv.wait_done(rid)
    a, b = lv.events("ev-a"), lv.events("ev-b")
    ids = [e["event_id"] for e in a + b]
    assert len(ids) == len(set(ids))
    assert [e["sequence"] for e in a] == list(range(1, len(a) + 1))
    kinds = {e["kind"] for e in a}
    assert kinds == {"world_snapshot", "metric_sample"}
    code, page = lv.call("GET", "/v1/runs/ev-a/events?after_sequence=3&limit=4")
    assert [e["sequence"] for e in page["events"]] == [4, 5, 6, 7]
    assert page["latest_sequence"] == len(a) and page["oldest_sequence"] == 1
    assert lv.call("GET", "/v1/runs/ev-a/events?after_sequence=x")[0] == 400
    assert lv.call("GET", "/v1/runs/missing/events")[0] == 404


def test_sequences_and_event_ids_continue_after_coordinator_restart(live: Any, nodes: Any) -> None:
    lv, ns = live(start_paused=True), nodes()
    lv.start_run(run_body("rs", ns, ticks=30))
    lv.wait("rs", lambda s: s["status"] == "paused")
    for i in range(4):
        lv.command("rs", f"s{i}", "step")
        lv.wait("rs", lambda s, i=i: s["tick"] == i + 1)
    before = lv.events("rs")
    boot1 = lv.svc.boot_id
    lv.close()  # crash: the run is left active on disk
    lv2 = live()
    assert lv2.svc.boot_id != boot1
    s = lv2.status("rs")
    assert s["status"] == "interrupted" and s["tick"] == 4
    after = lv2.events("rs")
    assert after[: len(before)] == before
    new = after[len(before) :]
    assert [e["sequence"] for e in after] == list(range(1, len(after) + 1))
    assert new and all(e["event_id"].startswith(f"rs-{lv2.svc.boot_id}-") for e in new)
    assert len({e["event_id"] for e in after}) == len(after)
    assert new[-1]["metric"] == "run_interrupted"
    # a new run on the restarted coordinator is allowed and paging old events still works
    assert lv2.call("POST", "/v1/runs", run_body("rs2", ns, ticks=3))[0] == 201
    lv2.wait_done("rs2")
    assert (
        lv2.call("GET", "/v1/runs/rs/events?after_sequence=2&limit=2")[1]["events"][0]["sequence"]
        == 3
    )
    assert lv2.call("POST", "/v1/runs", run_body("rs", ns, ticks=3))[0] == 409


def test_readyz_needs_simulator_and_a_reachable_node(live: Any, nodes: Any, tmp_path: Any) -> None:
    ns = nodes(2)
    lv = live()
    code, body = lv.call("GET", "/readyz")
    assert code == 503 and body["ready"] is False and body["nodes"] == {}
    up = live(node_urls={"node-0": ns["node-0"].url, "node-1": "http://127.0.0.1:9"})
    code, body = up.call("GET", "/readyz")
    assert code == 200 and body["ready"] is True
    assert body["nodes"] == {"node-0": True, "node-1": False}
    ns["node-0"].stop()
    assert up.call("GET", "/readyz")[0] == 503
    # a node with the wrong control token is not "reachable"
    ns2 = nodes(1)
    ns2["node-0"].token = "someone-elses-token-0123456"
    bad = live(node_urls={"node-0": ns2["node-0"].url})
    assert bad.call("GET", "/readyz")[0] == 503


def test_simulator_missing_is_a_visible_failure_without_fixture_fallback(
    tmp_path: Any, nodes: Any
) -> None:
    cfg = {
        "coordinator_token": COORD_TOKEN,
        "admin_token": ADMIN_TOKEN,
        "node_token": NODE_TOKEN,
        "data_dir": tmp_path / "d",
        "plan_file": tmp_path / "plan.json",
    }

    def broken() -> Any:
        return False, "ImportError: no module named archipelago_sim2d"

    with pytest.raises(SimulatorUnavailable, match="archipelago_sim2d"):
        Coordinator(Settings(production=True, **cfg), sim_check=broken)
    # non-production still boots, but reports not ready and refuses runs; nothing is simulated
    import threading

    from archipelago_coordinator.httpd import make_server
    from coord_harness import http, run_body

    svc = Coordinator(Settings(production=False, **cfg), sim_check=broken)
    srv = make_server(svc)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    ns = nodes(4)
    try:
        code, body = http("GET", base + "/readyz", COORD_TOKEN)
        assert code == 503 and body["simulator"]["available"] is False
        code, body = http("POST", base + "/v1/runs", COORD_TOKEN, run_body("x", ns, ticks=3).wire())
        assert code == 503 and body["error"] == "simulator_unavailable"
        assert svc.current is None
    finally:
        srv.shutdown()
        srv.server_close()
        svc.close()


def test_settings_reject_weak_or_shared_tokens(tmp_path: Any) -> None:
    base = {"data_dir": tmp_path}
    with pytest.raises(ConfigError):
        Settings("short", ADMIN_TOKEN, NODE_TOKEN, **base).validate()
    with pytest.raises(ConfigError):
        Settings(COORD_TOKEN, COORD_TOKEN, NODE_TOKEN, **base).validate()
    env = {
        "COORDINATOR_TOKEN": COORD_TOKEN,
        "NODE_CONTROL_TOKEN": NODE_TOKEN,
        "COORDINATOR_DATA_DIR": str(tmp_path),
        "ARCHIPELAGO_COMMIT": "abc1234",
        "COORDINATOR_NODE_URLS": "node-01=http://n1:8000,node-02=http://n2:8000",
    }
    with pytest.raises(ConfigError, match="COORDINATOR_ADMIN_TOKEN"):
        Settings.from_env(env)
    env["COORDINATOR_ADMIN_TOKEN"] = ADMIN_TOKEN
    with pytest.raises(ConfigError, match="COORDINATOR_PLAN_FILE"):
        Settings.from_env({**env, "ARCHIPELAGO_ENV": "production"})
    with pytest.raises(ConfigError, match="battery_scale"):
        Settings.from_env({**env, "COORDINATOR_WORLD_KWARGS": '{"battery_scale": 4}'})
    s = Settings.from_env(
        {**env, "ARCHIPELAGO_ENV": "production", "COORDINATOR_PLAN_FILE": str(tmp_path / "p.json")}
    )
    assert s.plan_file == tmp_path / "p.json"
    assert s.production and s.node_urls == {
        "node-01": "http://n1:8000",
        "node-02": "http://n2:8000",
    }


def test_map_offset_shifts_episode_seeds_before_the_gate_check(live: Any, nodes: Any) -> None:
    lv, ns = live(), nodes()
    body = run_body("off", ns, ticks=5)
    body["plan"].update(node_config={"gate_seeds": [6]})  # ok at seed 1, collides at +5
    assert lv.call("POST", "/v1/runs", body)[0] == 201
    shifted = run_body("off2", ns, ticks=5)
    shifted["plan"].update(node_config={"gate_seeds": [6]})
    shifted["map_offset"] = 5
    code, out = lv.call("POST", "/v1/runs", shifted)
    assert code == 422 and "gate_seeds" in out["detail"], out
    neg = run_body("off3", ns, ticks=5)
    neg["map_offset"] = -1
    assert lv.call("POST", "/v1/runs", neg)[0] == 422

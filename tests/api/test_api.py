import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from archipelago_api.app import create_app, fixture_factory
from archipelago_api.runs import RunManager, Subscriber
from archipelago_api.settings import Settings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def mgr(c: TestClient) -> RunManager:
    return cast(RunManager, cast(FastAPI, c.app).state.manager)


GOOD = Path(__file__).resolve().parents[2] / "packages/contracts/fixtures/good"
TOKEN = "t" * 24
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def cfg(run_id: str = "run-a", max_ticks: int = 100) -> dict[str, Any]:
    c: dict[str, Any] = json.loads((GOOD / "run_config.json").read_text())
    c["run_id"], c["budgets"]["max_ticks"] = run_id, max_ticks
    return c


def make(tmp_path: Path, **kw: Any) -> TestClient:
    s = Settings(api_token=TOKEN, data_dir=tmp_path, tick_interval=None, **kw)
    return TestClient(create_app(s, fixture_factory(GOOD)), headers=AUTH)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with make(tmp_path) as c:
        yield c


def start(c: TestClient, key: str = "k1", **kw: Any) -> dict[str, Any]:
    r = c.post("/v1/runs", json=cfg(**kw), headers={**AUTH, "Idempotency-Key": key})
    assert r.status_code in (200, 201), r.text
    return cast(dict[str, Any], r.json())


def cmd(c: TestClient, run: dict[str, Any], command: str, cid: str, rev: int | None = None) -> Any:
    body = {
        "command_id": cid,
        "command": command,
        "expected_revision": run["revision"] if rev is None else rev,
    }
    return c.post(f"/v1/runs/{run['run_id']}/commands", json=body)


def test_duplicate_start_is_idempotent_and_conflicts_are_rejected(client: TestClient) -> None:
    first = client.post("/v1/runs", json=cfg(), headers={"Idempotency-Key": "k1"})
    again = client.post("/v1/runs", json=cfg(), headers={"Idempotency-Key": "k1"})
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json() == again.json()
    assert (
        client.post("/v1/runs", json=cfg("run-b"), headers={"Idempotency-Key": "k1"}).status_code
        == 409
    )
    # different key while a run is active: admission cap
    assert (
        client.post("/v1/runs", json=cfg("run-b"), headers={"Idempotency-Key": "k2"}).status_code
        == 409
    )
    assert client.post("/v1/runs", json=cfg()).status_code == 400  # key required
    assert client.get("/readyz").status_code == 503


def test_lifecycle_transitions_and_invalid_ones(client: TestClient) -> None:
    run = start(client)
    assert run["status"] == "running"
    assert cmd(client, run, "resume", "c0").status_code == 409  # not paused
    assert cmd(client, run, "step", "c1").status_code == 409  # not paused
    run = cmd(client, run, "pause", "c2").json()
    assert run["status"] == "paused"
    tick = run["tick"]
    run = cmd(client, run, "step", "c3").json()
    assert (run["status"], run["tick"]) == ("paused", tick + 1)
    run = cmd(client, run, "resume", "c4").json()
    assert run["status"] == "running"
    run = cmd(client, run, "stop", "c5").json()
    assert (run["status"], run["completion_reason"]) == ("completed", "stopped")
    assert cmd(client, run, "pause", "c6").status_code == 409
    assert client.get("/readyz").status_code == 200  # capacity released


def test_duplicate_and_stale_commands(client: TestClient) -> None:
    run = start(client)
    first = cmd(client, run, "pause", "same")
    assert cmd(client, run, "pause", "same").json() == first.json()  # replay, not a new change
    assert client.get(f"/v1/runs/{run['run_id']}").json()["revision"] == first.json()["revision"]
    assert cmd(client, run, "resume", "other").status_code == 409  # stale revision
    assert cmd(client, run, "bogus", "x").status_code == 422


def test_budget_completes_run_and_events_page(client: TestClient) -> None:
    run = start(client, max_ticks=3)
    run = cmd(client, run, "pause", "p").json()
    for i in range(3):
        run = cmd(client, run, "step", f"s{i}").json()
    assert (run["status"], run["completion_reason"]) == ("completed", "max_ticks")
    page = client.get(f"/v1/runs/{run['run_id']}/events", params={"limit": 2}).json()
    assert len(page["events"]) == 2
    rest = client.get(
        f"/v1/runs/{run['run_id']}/events",
        params={"after_sequence": page["events"][-1]["sequence"], "limit": 500},
    ).json()
    seqs = [e["sequence"] for e in page["events"] + rest["events"]]
    assert seqs == sorted(seqs) and seqs == list(range(seqs[0], seqs[0] + len(seqs)))
    assert seqs[-1] == rest["latest_sequence"]


def test_auth_required_for_routes_and_stream(client: TestClient) -> None:
    anon = TestClient(client.app)
    assert anon.post("/v1/runs", json=cfg(), headers={"Idempotency-Key": "k"}).status_code == 401
    assert anon.get("/v1/runs/run-a").status_code == 401
    assert anon.get("/healthz").status_code == 200
    assert anon.post("/v1/login", json={"token": "wrong"}).status_code == 401
    start(client)
    with pytest.raises(WebSocketDisconnect), anon.websocket_connect("/v1/runs/run-a/stream"):
        pass
    bad = {**AUTH, "Origin": "http://evil.example"}
    with (
        pytest.raises(WebSocketDisconnect),
        anon.websocket_connect("/v1/runs/run-a/stream", headers=bad),
    ):
        pass
    assert anon.post("/v1/login", json={"token": TOKEN}).status_code == 200
    with anon.websocket_connect("/v1/runs/run-a/stream") as ws:  # cookie session works
        assert ws.receive_json()["type"] == "snapshot"


def test_slow_subscriber_never_blocks_simulation(tmp_path: Path) -> None:
    with make(tmp_path, subscriber_queue=2) as c:
        run = start(c)
        run = cmd(c, run, "pause", "p").json()
        stalled = Subscriber(2)  # a viewer that never reads
        mgr(c).get(run["run_id"]).subs.add(stalled)
        t0 = time.monotonic()
        for i in range(10):
            run = cmd(c, run, "step", f"s{i}").json()
        assert time.monotonic() - t0 < 5 and run["tick"] == 10
        assert stalled.lagged and stalled.queue.qsize() <= 2


def test_stream_snapshot_deltas_then_resnapshot_on_lag(client: TestClient) -> None:
    run = start(client)
    run = cmd(client, run, "pause", "p").json()
    with client.websocket_connect(f"/v1/runs/{run['run_id']}/stream") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot" and first["snapshot"]["run_status"] == "paused"
        run = cmd(client, run, "step", "s1").json()
        delta = ws.receive_json()
        assert delta["type"] == "delta" and delta["sequence"] > first["sequence"]
        (sub,) = mgr(client).get(run["run_id"]).subs
        sub.lagged = True  # as set by the manager when this viewer's queue overflowed
        cmd(client, run, "resume", "r")
        assert ws.receive_json()["type"] == "resnapshot"
        assert ws.receive_json()["type"] == "snapshot"


def test_disconnect_does_not_stop_run_and_reconnect_resnapshots(client: TestClient) -> None:
    run = start(client)
    with client.websocket_connect(f"/v1/runs/{run['run_id']}/stream") as ws:
        assert ws.receive_json()["type"] == "snapshot"
    assert mgr(client).get(run["run_id"]).subs == set()
    run = cmd(client, run, "pause", "p").json()
    with client.websocket_connect(f"/v1/runs/{run['run_id']}/stream") as ws:
        assert ws.receive_json()["status"] == "paused"


def test_auto_ticking_runs_to_budget(tmp_path: Path) -> None:
    s = Settings(api_token=TOKEN, data_dir=tmp_path, tick_interval=0.001)
    with TestClient(create_app(s, fixture_factory(GOOD)), headers=AUTH) as c:
        start(c, max_ticks=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            r = c.get("/v1/runs/run-a").json()
            if r["status"] == "completed":
                break
            time.sleep(0.01)
        assert (r["status"], r["tick"]) == ("completed", 5)


def test_restart_marks_active_runs_interrupted(tmp_path: Path) -> None:
    c = make(tmp_path)  # no lifespan exit: simulates a hard kill
    run = start(c)
    c2 = make(tmp_path)
    got = c2.get(f"/v1/runs/{run['run_id']}").json()
    assert (got["status"], got["completion_reason"]) == ("interrupted", "process_restart")
    assert got["revision"] > run["revision"]
    # restarted store keeps idempotency: same key returns the interrupted run, no new start
    again = c2.post("/v1/runs", json=cfg(), headers={"Idempotency-Key": "k1"})
    assert again.status_code == 200 and again.json()["status"] == "interrupted"
    assert c2.get("/readyz").status_code == 200


def test_recovered_run_streams_status_without_fake_snapshot(tmp_path: Path) -> None:
    run = start(make(tmp_path))
    c2 = make(tmp_path)
    with c2.websocket_connect(f"/v1/runs/{run['run_id']}/stream") as ws:
        first = ws.receive_json()
    assert first["status"] == "interrupted" and not first.get("snapshot")


def test_clean_shutdown_marks_interrupted(tmp_path: Path) -> None:
    with make(tmp_path) as c:
        start(c)
    with make(tmp_path) as c2:
        assert c2.get("/v1/runs/run-a").json()["status"] == "interrupted"


def test_real_sim2d_run_streams_and_completes(tmp_path: Path) -> None:
    pytest.importorskip("archipelago_sim2d")
    from archipelago_api.app import sim2d_factory
    from archipelago_sim2d.smoke import make_config  # type: ignore[import-not-found,import-untyped,unused-ignore]

    s = Settings(api_token=TOKEN, data_dir=tmp_path, tick_interval=None)
    with TestClient(create_app(s, sim2d_factory()), headers=AUTH) as c:
        body = make_config(7, 3).model_dump(mode="json")
        r = c.post("/v1/runs", json=body, headers={"Idempotency-Key": "real"})
        assert r.status_code == 201, r.text
        run = cmd(c, r.json(), "pause", "p").json()
        with c.websocket_connect(f"/v1/runs/{run['run_id']}/stream") as ws:
            assert ws.receive_json()["snapshot"]["poses"]
            for i in range(3):
                run = cmd(c, run, "step", f"s{i}").json()
            assert ws.receive_json()["type"] == "delta"
        assert (run["status"], run["completion_reason"]) == ("completed", "max_ticks")


def test_stopped_sim2d_run_still_streams_final_snapshot(tmp_path: Path) -> None:
    pytest.importorskip("archipelago_sim2d")
    from archipelago_api.app import sim2d_factory
    from archipelago_sim2d.smoke import make_config  # type: ignore[import-not-found,unused-ignore]

    s = Settings(api_token=TOKEN, data_dir=tmp_path, tick_interval=None)
    with TestClient(create_app(s, sim2d_factory()), headers=AUTH) as c:
        body = make_config(7, 3).model_dump(mode="json")
        r = c.post("/v1/runs", json=body, headers={"Idempotency-Key": "k"})
        run = cmd(c, cmd(c, r.json(), "pause", "p").json(), "stop", "x").json()
        assert run["status"] == "completed"
        with c.websocket_connect(f"/v1/runs/{run['run_id']}/stream") as ws:
            m = ws.receive_json()
        assert m["status"] == "completed" and m["snapshot"]["poses"]

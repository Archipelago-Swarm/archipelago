"""ARCHIPELAGO_ADAPTER=live end to end: API -> real archipelago_coordinator -> fake HTTP nodes.

The coordinator runs in-process (its stdlib HTTP server on localhost) with fake nodes that
implement /v1/act, /v1/feedback, /v1/control and /v1/status (tests/coordinator/coord_harness.py, not
edited here). Real TimescaleDB is CI-only; persistence is checked through the Persister with a
recording sink and through the report queries on a SQLite stand-in (tests/storage/fakedb.py).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from archipelago_api.app import create_app, create_app_from_env, fixture_factory
from archipelago_api.live import LiveConfigError
from archipelago_api.persistence import Persister
from archipelago_api.settings import Settings
from archipelago_storage import Writer, queries
from coord_harness import (  # type: ignore[import-not-found,unused-ignore]
    ADMIN_TOKEN,
    COORD_TOKEN,
    FakeNode,
    Live,
    make_nodes,
    run_body,
)
from fakedb import SqliteConn  # type: ignore[import-not-found,unused-ignore]
from fastapi.testclient import TestClient

LOGIN = "login-test-only-credential"
TELEMETRY = "telemetry-test-only-credential"
AUTH = {"Authorization": f"Bearer {LOGIN}"}
TAUTH = {"Authorization": f"Bearer {TELEMETRY}"}
GOOD = Path(__file__).resolve().parents[2] / "packages/contracts/fixtures/good"
CUT = [{"start_tick": 6, "end_tick": 12, "cut_links": [["node-0", "node-1"]]}]


class TeeSink:
    """Records every row handed to the Persister's sink and forwards it to a real Writer."""

    def __init__(self, inner: Writer) -> None:
        self.inner = inner
        self.recorded: list[tuple[str, str, tuple[Any, ...]]] = []

    def put(self, kind: str, run_id: str, row: tuple[Any, ...]) -> None:
        self.recorded.append((kind, run_id, row))
        self.inner.put(kind, run_id, row)

    def flush(self) -> bool:
        return self.inner.flush()

    def __len__(self) -> int:
        return len(self.inner)


class Stack:
    def __init__(self, tmp: Path, persister: Persister | None, **settings: Any) -> None:
        self.nodes: dict[str, FakeNode] = make_nodes(4)
        self.coordinator = Live(
            tmp / "coordinator",
            start_paused=True,
            commit="94712c5",
            node_urls={k: v.url for k, v in self.nodes.items()},  # COORDINATOR_NODE_URLS probes
        )
        body = run_body("live-1", self.nodes, ticks=25, fault_schedule=CUT)
        self.run_config: dict[str, Any] = body["run_config"]
        plan_file = tmp / "plans.json"
        plan_file.write_text(json.dumps({"demo": body["plan"]}))
        self.settings = Settings(
            api_token=LOGIN,
            data_dir=tmp / "api",
            tick_interval=None,
            subscriber_queue=5000,
            telemetry_token=TELEMETRY,
            adapter="live",
            coordinator_url=self.coordinator.url,
            coordinator_token=COORD_TOKEN,
            coordinator_admin_token=ADMIN_TOKEN,
            coordinator_plan_file=plan_file,
            live_poll_interval=0.02,
            **settings,
        )
        # the caller-supplied fixture factory must be ignored in live mode
        self.app = create_app(self.settings, fixture_factory(GOOD), persister)

    def post_run(self, client: TestClient, key: str = "k1", **extra: Any) -> Any:
        body = {**self.run_config, **extra}
        return client.post("/v1/runs", json=body, headers={**AUTH, "Idempotency-Key": key})

    def close(self) -> None:
        self.coordinator.close()
        for n in self.nodes.values():
            n.stop()


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Callable[..., Stack]]:
    made: list[Stack] = []

    def build(persister: Persister | None = None, **settings: Any) -> Stack:
        s = Stack(tmp_path, persister, **settings)
        made.append(s)
        return s

    yield build
    for s in made:
        s.close()


def wait_for(pred: Callable[[], bool], what: str, timeout: float = 30) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.02)
    raise AssertionError(f"timeout waiting for {what}")


def telemetry(run_id: str, event_id: str, tick: int, kind: str, **fields: Any) -> dict[str, Any]:
    return {
        "kind": kind, "schema_version": "0.1.0", "event_id": event_id, "run_id": run_id,
        "source_node_id": "node-0", "sim_tick": tick, "sequence": tick,
        "emitted_at_utc": f"2026-10-10T12:00:{tick:02d}Z", **fields,
    }  # fmt: skip


def learning(run_id: str, eid: str, tick: int, upd: int, loss: float | None, **kw: Any) -> Any:
    base = {"update_count": upd, "loss": loss, "previous_version": upd - 1, "new_version": upd,
            "transfer": "none"}  # fmt: skip
    return telemetry(run_id, eid, tick, "learning_event", **{**base, **kw})


CONTEXT = {"commit": "94712c5", "config_hash": "d" * 64, "seed": 3, "host": "node-host-0",
           "boot_id": "ab12cd34", "episode": 0}  # fmt: skip


def test_readyz_tracks_coordinator_and_nodes_not_run_activity(
    stack: Callable[..., Stack],
) -> None:
    s = stack()
    with TestClient(s.app) as c:
        ready = c.get("/readyz")
        assert ready.status_code == 200
        body = ready.json()
        assert body["mode"] == "live" and body["dependencies"]["nodes_ready"] == 4
        # an active run does not change readiness (it is not capacity based in live mode)
        assert s.post_run(c).status_code == 201
        assert c.get("/readyz").status_code == 200
        # no node reachable -> not ready, even though the coordinator itself answers
        for n in s.nodes.values():
            n.stop()
        down = c.get("/readyz")
        assert down.status_code == 503 and down.json()["dependencies"]["nodes_ready"] == 0
    s.coordinator.close()
    with TestClient(create_app(s.settings, fixture_factory(GOOD))) as c:  # coordinator gone
        gone = c.get("/readyz")
        assert gone.status_code == 503
        assert gone.json()["dependencies"]["coordinator"] == "unreachable"


def test_live_requested_but_unusable_fails_at_startup_never_falls_back(
    stack: Callable[..., Stack], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = stack()
    base = s.settings
    from dataclasses import replace

    for bad in (
        replace(base, coordinator_url=None),
        replace(base, coordinator_url="ftp://coordinator"),
        replace(base, coordinator_token="short"),
        replace(base, coordinator_plan_file=None),
        replace(base, coordinator_plan_file=tmp_path / "missing.json"),
    ):
        with pytest.raises(LiveConfigError):
            create_app(bad, fixture_factory(GOOD))
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"demo": {"node_urls": {}, "episodes": []}}))
    with pytest.raises(LiveConfigError):
        create_app(replace(base, coordinator_plan_file=broken), fixture_factory(GOOD))
    with pytest.raises(LiveConfigError):
        create_app(replace(base, adapter="fixtrue"), fixture_factory(GOOD))  # typo is not fixture
    # the coordinator package missing is a startup error too
    import importlib

    real = importlib.import_module

    def no_coordinator(name: str, *a: Any) -> Any:
        if name.startswith("archipelago_coordinator"):
            raise ImportError(name)
        return real(name, *a)

    monkeypatch.setattr(importlib, "import_module", no_coordinator)
    with pytest.raises(LiveConfigError, match="not importable"):
        create_app(base, fixture_factory(GOOD))
    monkeypatch.undo()
    # environment path: live without a coordinator URL must not quietly serve fixtures
    for k, v in {
        "ARCHIPELAGO_API_TOKEN": LOGIN, "ARCHIPELAGO_ADAPTER": "live",
        "ARCHIPELAGO_DATA_DIR": str(tmp_path / "env"),
    }.items():  # fmt: skip
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("COORDINATOR_URL", raising=False)
    with pytest.raises(LiveConfigError):
        create_app_from_env()


def test_requests_cannot_supply_node_urls_or_plans(stack: Callable[..., Stack]) -> None:
    s = stack()
    with TestClient(s.app) as c:
        assert s.post_run(c, node_urls={"node-0": "http://169.254.169.254"}).status_code == 422
        assert s.post_run(c, plan={"node_urls": {"node-0": "http://evil"}}).status_code == 422
        r = s.post_run(c, plan="not-in-allowlist")
        assert r.status_code == 422 and r.json()["detail"]["allowed"] == ["demo"]
        # nothing reached the coordinator: it is still idle and the API holds no run
        assert s.coordinator.call("GET", "/v1/runs/live-1")[0] == 404
        assert c.get("/v1/runs/live-1", headers=AUTH).status_code == 404
        ok = s.post_run(c, plan="demo", key="k2")
        assert ok.status_code == 201 and ok.json()["plan"] == "demo"


def test_end_to_end_scenario_stream_replay_persistence_and_reports(
    stack: Callable[..., Stack],
) -> None:
    db = SqliteConn()
    recorder = TeeSink(Writer(lambda: db))  # records every row, then writes it to the database
    s = stack(Persister(recorder, interval=0.05))
    with TestClient(s.app) as c:
        created = s.post_run(c)
        assert created.status_code == 201
        rid = created.json()["run_id"]
        assert s.post_run(c).status_code == 200  # same key + body replays the same run
        mgr = s.app.state.manager
        run = mgr.runs[rid]
        assert run.adapter is None  # no local simulator, no FixtureAdapter
        wait_for(
            lambda: c.get(f"/v1/runs/{rid}", headers=AUTH).json()["status"] == "paused", "pause"
        )
        view = c.get(f"/v1/runs/{rid}", headers=AUTH).json()
        with c.websocket_connect(f"/v1/runs/{rid}/stream", headers=AUTH) as ws:
            first = ws.receive_json()
            assert first["type"] == "snapshot"
            # idempotent command ids and revisions are the coordinator's
            step = {
                "command_id": "step-1",
                "command": "step",
                "expected_revision": view["revision"],
            }
            r1 = c.post(f"/v1/runs/{rid}/commands", json=step, headers=AUTH)
            assert r1.status_code == 200 and r1.json()["revision"] == view["revision"] + 1
            assert c.post(f"/v1/runs/{rid}/commands", json=step, headers=AUTH).json() == r1.json()
            stale = {**step, "command_id": "step-2"}
            assert c.post(f"/v1/runs/{rid}/commands", json=stale, headers=AUTH).status_code == 409
            wait_for(lambda: run.tick >= 1, "first tick mirrored")
            rev = c.get(f"/v1/runs/{rid}", headers=AUTH).json()["revision"]
            pause_while_paused = {"command_id": "p", "command": "pause", "expected_revision": rev}
            assert c.post(f"/v1/runs/{rid}/commands", json=pause_while_paused,
                          headers=AUTH).status_code == 409  # fmt: skip
            resume = {"command_id": "go", "command": "resume", "expected_revision": rev}
            assert c.post(f"/v1/runs/{rid}/commands", json=resume, headers=AUTH).status_code == 200
            # node telemetry through the mounted T36 route, with request-level context (A7)
            batch = {
                "source": "node-0", "boot_id": "ab12cd34", "context": CONTEXT,
                "events": [
                    learning(rid, "n0-1", 3, 4, 0.9),
                    learning(rid, "n0-2", 9, 12, 0.4),
                    learning(rid, "n0-3", 9, 12, None, transfer="rejected", candidate_score=0.1,
                             reason=f"window_limit (source=node-1 v=3 sha256={'a' * 64})"),
                    learning(rid, "n0-4", 10, 13, None, transfer="accepted", candidate_score=0.9,
                             new_version=14, previous_version=13,
                             reason=f"source=node-1 v=14 sha256={'b' * 64} margin=0.2000"),
                ],
            }  # fmt: skip
            assert c.post("/v1/telemetry", json=batch).status_code == 401
            res = c.post("/v1/telemetry", json=batch, headers=TAUTH)
            assert res.status_code == 200 and res.json()["accepted"] == 4
            assert c.post("/v1/telemetry", json=batch, headers=TAUTH).json()["duplicates"] == 4
            streamed: list[dict[str, Any]] = []
            while True:
                msg = ws.receive_json()
                streamed.append(msg)
                if msg.get("type") == "status" and msg.get("status") == "completed":
                    break
        final = c.get(f"/v1/runs/{rid}", headers=AUTH).json()
        assert final["status"] == "completed" and final["completion_reason"] == "plan_complete"

        # replay endpoint and stream carry the same canonical records
        page = c.get(f"/v1/runs/{rid}/events?limit=500", headers=AUTH).json()
        events, after = page["events"], page["events"][-1]["sequence"]
        while True:
            more = c.get(f"/v1/runs/{rid}/events?after_sequence={after}&limit=500", headers=AUTH)
            if not more.json()["events"]:
                break
            events += more.json()["events"]
            after = events[-1]["sequence"]
        assert [e["sequence"] for e in events] == sorted({e["sequence"] for e in events})
        canonical = [e for e in events if "kind" in e]
        kinds = {e["kind"] for e in canonical}
        assert {"world_snapshot", "metric_sample", "learning_event"} <= kinds
        assert all(e["type"] == e["kind"] and e["run_id"] == rid for e in canonical)
        from_coordinator = [e for e in canonical if e["context"]["host"] == "coordinator"]
        assert from_coordinator and all(
            e["context"]["episode"] == 0 and e["context"]["commit"] for e in from_coordinator
        )
        from_node = [e for e in canonical if e["event_id"].startswith("n0-")]
        assert len(from_node) == 4 and all(e["context"] == CONTEXT for e in from_node)
        streamed_ids = {m["event_id"] for m in streamed if "event_id" in m}
        assert streamed_ids <= {e["event_id"] for e in canonical}
        assert {"world_snapshot", "metric_sample"} <= {m["kind"] for m in streamed if "kind" in m}
        assert len({e["event_id"] for e in canonical}) == len(canonical)  # nothing twice
        # nodes did the acting; the API never held a world
        assert all(n.acts and n.violations == [] for n in s.nodes.values())
        snap = mgr.snapshot_event(run)["snapshot"]
        assert set(snap["poses"]) == set(s.nodes) and snap["kind"] == "world_snapshot"

    # persistence: run row carries the commit; node identity is the record's source node
    assert db.execute("SELECT git_sha FROM runs").fetchall() == [("94712c5",)]
    nodes = {r[0] for r in db.execute("SELECT DISTINCT node_id FROM events").fetchall()}
    assert {"node-0", "node-1", "swarm"} <= nodes and "api" in nodes  # api = status events only
    by_kind = {k for k, _, _ in recorder.recorded}
    assert by_kind == {"run", "event"}
    recorded_nodes = {r[2] for k, _, r in recorder.recorded if k == "event"}
    assert {"node-0", "swarm", "api"} <= recorded_nodes
    assert all(run == "live-1" for _, run, _ in recorder.recorded)

    # report queries answer from what was persisted
    learn = queries.learning_curves(db, "live-1")
    assert [p["update_count"] for p in learn["nodes"]["node-0"]] == [4, 12, 12, 13]
    assert learn["swarm"][-1]["total_updates"] == 13
    decisions = queries.peer_decisions(db, "live-1")["decisions"]
    assert [(d["decision"], d["reason_code"], d["sender"]) for d in decisions] == [
        ("rejected", "window_limit", "node-1"),
        ("accepted", "accepted", "node-1"),
    ]
    assert decisions[1]["margin"] == pytest.approx(0.2) and decisions[1]["candidate_score"] == 0.9
    timeline = queries.phase_timeline(db, "live-1")
    assert [x["phase"] for x in timeline["segments"]] == [
        "connected", "partition", "recovery",
    ]  # fmt: skip
    assert (
        timeline["segments"][1]["start_tick"] == 6 and timeline["segments"][2]["start_tick"] == 12
    )
    tasks = queries.task_curves(db, "live-1")
    assert tasks["coverage"]["train"]["swarm"] and not tasks["coverage"]["eval"]["swarm"]
    assert set(tasks["episode_return"]["train"]["nodes"]) == set(s.nodes)
    ident = queries.run_info(db, "live-1")["identity"]
    assert ident["host"] == ["coordinator", "node-host-0"] and ident["seed"] == ["1", "3"]


def test_sink_outage_never_blocks_ingest_or_the_event_log(stack: Callable[..., Stack]) -> None:
    db, outage = SqliteConn(), {"down": True}
    attempts = {"n": 0}

    def connect() -> SqliteConn:
        attempts["n"] += 1
        if outage["down"]:
            raise OSError("database unreachable")
        return db

    sink = Writer(connect, cap=50)  # the real bounded writer; connect fails during the outage
    persister = Persister(sink, cap=50, interval=0.02, now=lambda: datetime(2026, 1, 1, tzinfo=UTC))
    s = stack(persister)
    with TestClient(s.app) as c:
        rid = s.post_run(c).json()["run_id"]
        wait_for(
            lambda: c.get(f"/v1/runs/{rid}", headers=AUTH).json()["status"] == "paused", "pause"
        )
        t0 = time.monotonic()
        for i in range(20):  # more rows than the spool cap: oldest are shed, nothing blocks
            batch = {"source": "node-0", "boot_id": "ab12cd34", "context": CONTEXT,
                     "events": [learning(rid, f"o{i}-{j}", 1 + j, 1 + i * 10 + j, 0.5)
                                for j in range(10)]}  # fmt: skip
            assert c.post("/v1/telemetry", json=batch, headers=TAUTH).status_code == 200
        assert time.monotonic() - t0 < 10
        events = c.get(f"/v1/runs/{rid}/events?limit=500", headers=AUTH).json()["events"]
        assert sum(e.get("event_id", "").startswith("o") for e in events) == 200
        assert attempts["n"] >= 1 and persister.dropped > 0 and persister.queued <= 100
        # the run itself is untouched by the outage
        assert c.get("/healthz").status_code == 200
        rev = c.get(f"/v1/runs/{rid}", headers=AUTH).json()["revision"]
        step = {"command_id": "s", "command": "resume", "expected_revision": rev}
        assert c.post(f"/v1/runs/{rid}/commands", json=step, headers=AUTH).status_code == 200
        wait_for(
            lambda: c.get(f"/v1/runs/{rid}", headers=AUTH).json()["status"] == "completed",
            "completion under sink outage",
        )
        outage["down"] = False  # recovery: the bounded backlog is written, the rest was counted
        wait_for(
            lambda: db.execute("SELECT count(*) FROM events").fetchall()[0][0] > 0, "recovery flush"
        )

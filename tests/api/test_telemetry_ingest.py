"""Behavioral tests for the T36 router mounted on the existing FastAPI runtime."""

import asyncio
import json
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest
from archipelago_api.app import create_app, fixture_factory
from archipelago_api.eventlog import EventLog
from archipelago_api.persistence import Persister
from archipelago_api.settings import Settings
from archipelago_api.telemetry import MAX_BYTES, make_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

GOOD = Path(__file__).resolve().parents[2] / "packages/contracts/fixtures/good"
LOGIN = "login-test-only-credential"
TELEMETRY = "telemetry-test-only-credential"
AUTH = {"Authorization": f"Bearer {TELEMETRY}"}


def record(event_id: str = "e1", kind: str = "metric_sample") -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": kind,
        "schema_version": "0.1.0",
        "event_id": event_id,
        "run_id": "run-a",
        "source_node_id": "node-01",
        "sim_tick": 5,
        "emitted_at_utc": "2026-10-10T19:00:00Z",
        "sequence": 12,
    }
    fields: dict[str, Any] = {
        "metric_sample": {"metric": "loss", "value": 0.5, "unit": "count", "phase": "train"},
        "learning_event": {
            "update_count": 2,
            "loss": 0.5,
            "previous_version": 0,
            "new_version": 1,
            "transfer": "none",
        },
        "action": {"action_space_version": "act-v0", "command": "stay", "policy_version": 1},
        "world_snapshot": {
            "run_status": "running",
            "poses": {"node-01": {"x": 1.0, "y": 1.0}},
            "obstacles": [],
            "coverage": 0.2,
            "topology": {"links": []},
        },
    }
    body.update(fields[kind])
    return body


def batch(*events: Any) -> dict[str, Any]:
    return {"source": "node-01", "boot_id": "boot-a", "events": list(events)}


def runtime(
    tmp_path: Path,
    *,
    capacity: int = 2000,
    persister: Persister | None = None,
    event_log_size: int = 5000,
) -> TestClient:
    settings = Settings(
        api_token=LOGIN, data_dir=tmp_path, tick_interval=None, event_log_size=event_log_size
    )
    app = create_app(settings, fixture_factory(GOOD), persister)
    app.include_router(make_router(app.state.manager, token=TELEMETRY, capacity=capacity))
    return TestClient(app)


def manager(client: TestClient) -> Any:
    return cast(FastAPI, client.app).state.manager


def ingest(client: TestClient) -> Any:
    return manager(client).log.ingest


def drain(client: TestClient) -> None:
    cast(Any, client.portal).call(ingest(client).drain)


def create_run(client: TestClient) -> None:
    config = json.loads((GOOD / "run_config.json").read_text())
    config["run_id"] = "run-a"
    response = client.post(
        "/v1/runs",
        json=config,
        headers={"Authorization": f"Bearer {LOGIN}", "Idempotency-Key": "k1"},
    )
    assert response.status_code == 201, response.text
    drain(client)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with runtime(tmp_path) as c:
        create_run(c)
        yield c


def test_auth_is_separate_and_never_echoed(client: TestClient, caplog: Any) -> None:
    for authorization in (None, f"Bearer {LOGIN}", f"Basic {TELEMETRY}", "Bearer wrong"):
        headers = {} if authorization is None else {"Authorization": authorization}
        response = client.post("/v1/telemetry", json=batch(record()), headers=headers)
        assert response.status_code == 401
        assert TELEMETRY not in response.text
    response = client.post("/v1/telemetry", json=batch(record()), headers=AUTH)
    assert response.status_code == 200
    assert TELEMETRY not in response.text + caplog.text


@pytest.mark.parametrize("token", ["", "short", LOGIN])
def test_bad_server_token_fails_closed(tmp_path: Path, token: str) -> None:
    app = create_app(Settings(api_token=LOGIN, data_dir=tmp_path), fixture_factory(GOOD))
    with pytest.raises(ValueError, match="TELEMETRY_TOKEN"):
        make_router(app.state.manager, token=token)


def test_malformed_json_envelope_and_limits_apply_nothing(client: TestClient) -> None:
    before = manager(client).get("run-a").seq
    for body in (b"{", b"[]", b'{"source":"node-01"}', b"NaN", b"\xff"):
        assert client.post("/v1/telemetry", content=body, headers=AUTH).status_code == 400
    assert (
        client.post("/v1/telemetry", content=b" " * (MAX_BYTES + 1), headers=AUTH).status_code
        == 413
    )
    assert client.post("/v1/telemetry", json=batch(*([{}] * 501)), headers=AUTH).status_code == 413
    # A streaming request has no Content-Length, so actual bytes must be limited too.
    assert (
        client.post(
            "/v1/telemetry", content=iter([b" " * MAX_BYTES, b"x"]), headers=AUTH
        ).status_code
        == 413
    )
    assert manager(client).get("run-a").seq == before


def test_per_item_validation_unknown_run_and_dedupe(client: TestClient) -> None:
    bad = record("bad")
    bad["value"] = "not-a-number"
    unknown = record("unknown")
    unknown["run_id"] = "not-known"
    unsupported = record("unsupported")
    unsupported["kind"] = "observation"
    response = client.post(
        "/v1/telemetry", json=batch(record(), bad, unknown, unsupported, 42), headers=AUTH
    )
    assert response.status_code == 200
    result = response.json()
    assert result["accepted"] == 1
    assert result["duplicates"] == 0
    assert len(result["rejected"]) == 4
    assert {r["reason"] for r in result["rejected"]} == {
        "contract validation failed",
        "unknown run id",
        "unsupported record kind",
        "invalid record",
    }
    before = manager(client).get("run-a").seq
    second = client.post("/v1/telemetry", json=batch(record(), record()), headers=AUTH)
    assert second.json() == {"accepted": 0, "duplicates": 2, "rejected": []}
    assert manager(client).get("run-a").seq == before


def test_all_four_contracts_in_order_paging_and_durable_replay(client: TestClient) -> None:
    events = [
        record(f"e{i}", kind)
        for i, kind in enumerate(("action", "learning_event", "metric_sample", "world_snapshot"))
    ]
    before = manager(client).get("run-a").seq
    assert client.post("/v1/telemetry", json=batch(*events), headers=AUTH).json()["accepted"] == 4
    # Interleave an ordinary runtime event before the asynchronous log drains.
    cast(Any, client.portal).call(
        lambda: manager(client)._emit(manager(client).get("run-a"), "status", reason="test")
    )
    drain(client)
    response = client.get(
        f"/v1/runs/run-a/events?after_sequence={before}",
        headers={"Authorization": f"Bearer {LOGIN}"},
    )
    replay = response.json()["events"]
    assert [ev["sequence"] for ev in replay] == list(range(before + 1, before + 6))
    assert [ev["event_id"] for ev in replay[:4]] == [ev["event_id"] for ev in events]
    assert all(ev["source_sequence"] == 12 for ev in replay[:4])
    stored, highest = EventLog(manager(client).s.data_dir).load("run-a", 100)
    assert highest == before + 5
    assert [ev["sequence"] for ev in stored] == sorted(ev["sequence"] for ev in stored)
    assert [ev["event_id"] for ev in stored if "event_id" in ev] == [
        ev["event_id"] for ev in events
    ]


def test_queue_overload_has_no_partial_admission(tmp_path: Path, monkeypatch: Any) -> None:
    entered, release = threading.Event(), threading.Event()
    with runtime(tmp_path, capacity=2) as c:
        create_run(c)
        state = ingest(c)
        original = state._original_log.append

        def stalled(*args: Any, **kwargs: Any) -> None:
            entered.set()
            assert release.wait(3)
            original(*args, **kwargs)

        monkeypatch.setattr(state._original_log, "append", stalled)
        try:
            response = c.post("/v1/telemetry", json=batch(record("a"), record("b")), headers=AUTH)
            assert response.json()["accepted"] == 2
            assert entered.wait(1)
            before = manager(c).get("run-a").seq
            response = c.post("/v1/telemetry", json=batch(record("c"), record("d")), headers=AUTH)
            assert response.status_code == 503
            assert response.headers["Retry-After"] == "1"
            assert manager(c).get("run-a").seq == before
            assert ("run-a", "c") not in state.seen
        finally:
            release.set()
            drain(c)
        response = c.post("/v1/telemetry", json=batch(record("c"), record("d")), headers=AUTH)
        assert response.json()["accepted"] == 2


class StalledSink:
    def __init__(self) -> None:
        self.entered, self.release = threading.Event(), threading.Event()
        self.rows: list[tuple[Any, ...]] = []

    def put(self, *row: Any) -> None:
        self.rows.append(row)

    def flush(self) -> bool:
        self.entered.set()
        assert self.release.wait(3)
        return True

    def __len__(self) -> int:
        return len(self.rows)


def test_stalled_persister_does_not_block_response_or_run_loop(tmp_path: Path) -> None:
    sink = StalledSink()
    persister = Persister(sink, interval=0.01)
    with runtime(tmp_path, persister=persister) as c:
        create_run(c)
        assert sink.entered.wait(1)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                response = pool.submit(
                    c.post, "/v1/telemetry", json=batch(record()), headers=AUTH
                ).result(timeout=1)
                assert response.json()["accepted"] == 1

            async def step() -> int:
                await asyncio.sleep(0)
                run = manager(c).get("run-a")
                manager(c)._advance(run)
                return int(run.tick)

            assert cast(Any, c.portal).call(step) == 1
            assert persister.queued >= 1
        finally:
            sink.release.set()
            drain(c)
    assert any(
        row[0] == "event" and '"event_id":"e1"' in str(row[-1]).replace(" ", "")
        for row in sink.rows
    )


def test_shutdown_drains_the_accepted_batch(tmp_path: Path) -> None:
    with runtime(tmp_path) as c:
        create_run(c)
        assert c.post("/v1/telemetry", json=batch(record()), headers=AUTH).json()["accepted"] == 1
    events, _ = EventLog(tmp_path).load("run-a", 100)
    assert any(ev.get("event_id") == "e1" for ev in events)


def test_dedupe_recovers_ids_outside_replay_tail_after_restart(tmp_path: Path) -> None:
    with runtime(tmp_path, event_log_size=1) as first:
        create_run(first)
        response = first.post("/v1/telemetry", json=batch(record()), headers=AUTH)
        assert response.json()["accepted"] == 1
    with runtime(tmp_path, event_log_size=1) as restarted:
        # Only the final status event remains in memory; full durable IDs are recovered.
        before = manager(restarted).get("run-a").seq
        response = restarted.post("/v1/telemetry", json=batch(record()), headers=AUTH)
        assert response.json() == {"accepted": 0, "duplicates": 1, "rejected": []}
        assert manager(restarted).get("run-a").seq == before

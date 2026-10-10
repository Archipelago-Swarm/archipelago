"""The stream and replay endpoints carry the canonical records apps/web panels render.

Uses the recorded partition run the web panels are built on
(apps/web/src/fixtures/partition_run.json), posted through the mounted telemetry route
(TELEMETRY_TOKEN), then read back from the WebSocket and the replay endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archipelago_api.app import create_app, fixture_factory
from archipelago_api.settings import Settings
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
GOOD = ROOT / "packages/contracts/fixtures/good"
RECORDED: list[dict[str, Any]] = json.loads(
    (ROOT / "apps/web/src/fixtures/partition_run.json").read_text()
)
LOGIN, TELEMETRY = "login-test-only-credential", "telemetry-test-only-credential"
AUTH = {"Authorization": f"Bearer {LOGIN}"}
CONTEXT = {
    "commit": "94712c5",
    "config_hash": "e" * 64,
    "seed": 1,
    "host": "host-a",
    "boot_id": "boot-a",
}


def test_recorded_run_reaches_stream_and_replay_with_kinds_in_order(tmp_path: Path) -> None:
    settings = Settings(
        api_token=LOGIN,
        data_dir=tmp_path,
        tick_interval=None,
        telemetry_token=TELEMETRY,
        subscriber_queue=500,
    )
    cfg = json.loads((GOOD / "run_config.json").read_text())
    run_id = RECORDED[0]["run_id"]
    cfg["run_id"] = run_id
    with TestClient(create_app(settings, fixture_factory(GOOD))) as client:
        created = client.post("/v1/runs", json=cfg, headers={**AUTH, "Idempotency-Key": "k"})
        assert created.status_code == 201
        with client.websocket_connect(f"/v1/runs/{run_id}/stream", headers=AUTH) as ws:
            assert ws.receive_json()["type"] == "snapshot"
            for start in range(0, len(RECORDED), 9):  # node-sized batches
                batch = {
                    "source": "node-01",
                    "boot_id": "boot-a",
                    "context": CONTEXT,
                    "events": RECORDED[start : start + 9],
                }
                res = client.post(
                    "/v1/telemetry", json=batch, headers={"Authorization": f"Bearer {TELEMETRY}"}
                )
                assert res.status_code == 200 and res.json()["rejected"] == [], res.json()
            streamed = [ws.receive_json() for _ in RECORDED]
        replay = client.get(f"/v1/runs/{run_id}/events?limit=500", headers=AUTH).json()["events"]

    telemetry = [e for e in replay if "kind" in e]
    assert [e["kind"] for e in telemetry] == [r["kind"] for r in RECORDED]
    assert [e["event_id"] for e in telemetry] == [r["event_id"] for r in RECORDED]
    assert [m["event_id"] for m in streamed] == [r["event_id"] for r in RECORDED]
    assert [m["kind"] for m in streamed] == [r["kind"] for r in RECORDED]
    # what the panels read: node ids, ticks, metric names/phases, decisions, envelopes
    deciders = {e["source_node_id"] for e in telemetry if e["kind"] == "learning_event"}
    assert deciders == {"node-01", "node-02"}
    phases = {e["phase"] for e in telemetry if e["kind"] == "metric_sample"}
    assert phases >= {"train", "eval", "partition", "recovery"}
    assert any(e["kind"] == "peer_envelope" and e["sender"] == "node-02" for e in telemetry)
    assert all(e["context"]["commit"] == "94712c5" for e in telemetry)
    assert [e["sequence"] for e in replay] == sorted(e["sequence"] for e in replay)

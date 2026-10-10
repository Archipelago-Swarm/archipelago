"""Coordinator behaviour against in-process fake nodes (the node runtime is T27)."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from archipelago_contracts.models import Observation
from archipelago_coordinator import core
from archipelago_coordinator.core import Coordinator, SimulatorUnavailable
from archipelago_coordinator.server import make_server
from archipelago_sim2d.adapter import Sim2DAdapter
from archipelago_sim2d.smoke import make_action, make_config

NODES = [f"node-{i}" for i in range(4)]


class FakeNode:
    def __init__(self, node: str, delay: float = 0.0, fail: bool = False) -> None:
        self.node, self.delay, self.fail = node, delay, fail
        self.seen: list[dict[str, Any]] = []
        self.feedback_calls = 0
        self.controls: list[str] = []

    def act(self, payload: dict[str, Any], deadline_ms: int) -> dict[str, Any] | None:
        self.seen.append(payload)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            return None
        command = ["east", "south", "west", "north"][payload["tick"] % 4]
        return {"action": make_action(self.node, payload["tick"], command).model_dump(mode="json")}

    def feedback(self, payload: dict[str, Any]) -> None:
        self.feedback_calls += 1

    def control(self, payload: dict[str, Any]) -> None:
        self.controls.append(payload["command"])


def build(
    tmp_path: Path, ticks: int = 30, **node_kwargs: Any
) -> tuple[Coordinator, dict[str, FakeNode]]:
    fakes = {n: FakeNode(n, **node_kwargs.get(n, {})) for n in NODES}
    return Coordinator(tmp_path, fakes, lambda: Sim2DAdapter(), deadline_ms=150), fakes  # type: ignore[arg-type]


def test_each_node_gets_only_its_own_observation(tmp_path: Path) -> None:
    coord, fakes = build(tmp_path)
    coord.start_run(make_config(1, 20))
    coord.step_tick()
    for node, fake in fakes.items():
        payload = fake.seen[0]
        assert set(payload) == {"run_id", "episode", "tick", "deadline_ms", "observation"}
        obs = Observation.model_validate(payload["observation"])
        assert obs.source_node_id == node
        text = json.dumps(payload)
        assert "obstacles" not in text and "poses" not in text and "targets" not in text


def test_missing_late_and_stalled_nodes_do_not_delay_the_others(tmp_path: Path) -> None:
    coord, _ = build(tmp_path, **{"node-1": {"fail": True}, "node-2": {"delay": 1.0}})
    coord.start_run(make_config(2, 20))
    started = time.monotonic()
    coord.step_tick()
    assert time.monotonic() - started < 0.6  # bounded by the deadline, not by the 1 s stall
    events = coord.spool.read()["events"]
    missed = {e["source_node_id"] for e in events if e.get("metric") == "deadline_missed"}
    assert missed == {"node-1", "node-2"}
    assert any(e["event"] == "missing_action" for e in coord.adapter.world.events)


def test_five_consecutive_misses_mark_unavailable_but_world_continues(tmp_path: Path) -> None:
    coord, fakes = build(tmp_path, **{"node-3": {"fail": True}})
    coord.start_run(make_config(3, 40))
    for _ in range(6):
        coord.step_tick()
    assert coord.health["node-3"] == "unavailable"
    assert len(fakes["node-3"].seen) == core.MISS_LIMIT  # no longer asked after the fifth miss
    assert coord.health["node-0"] == "ready" and coord.tick == 6
    assert "node-3" in coord.adapter.world.agents  # still in the world, staying


def test_commands_are_validated_and_idempotent(tmp_path: Path) -> None:
    coord, _ = build(tmp_path)
    coord.start_run(make_config(4, 20))
    with pytest.raises(core.CommandError):
        coord.command("c0", "resume")  # not paused
    first = coord.command("c1", "pause")
    assert coord.command("c1", "pause") == first  # duplicate id returns the same reply
    revision = coord.revision
    coord.command("c2", "step", expected_revision=revision)
    assert coord.tick == 1
    with pytest.raises(core.CommandError):
        coord.command("c3", "step", expected_revision=revision)  # stale
    with pytest.raises(core.CommandError):
        coord.start_run(make_config(4, 20))  # one active run
    coord.command("c4", "stop")
    assert coord.status == "stopping"


def test_kill_node_removes_the_drone_and_the_rest_continue(tmp_path: Path) -> None:
    coord, fakes = build(tmp_path)
    coord.start_run(make_config(5, 25))
    coord.step_tick()
    coord.kill_node("node-2")
    coord.step_tick()
    assert "node-2" not in coord.adapter.world.agents
    assert coord.health["node-2"] == "killed" and len(fakes["node-2"].seen) == 1
    assert len(fakes["node-0"].seen) == 2


def test_replay_reproduces_final_hash_including_a_kill(tmp_path: Path) -> None:
    coord, _ = build(tmp_path)
    coord.start_run(make_config(6, 20))
    coord.step_tick()
    coord.kill_node("node-1")
    final = coord.run_to_end()
    assert coord.status == "completed" and coord.final_hashes[0] == final
    manifest = json.loads((tmp_path / "replays" / "episode-0" / "manifest.json").read_text())
    assert manifest["final_state_hash"] == final


def test_sequences_continue_across_restart_and_ids_are_unique_across_runs(tmp_path: Path) -> None:
    coord, _ = build(tmp_path)
    coord.start_run(make_config(7, 10))
    coord.run_to_end()
    last = coord.spool.read()["latest_sequence"]
    restarted, _ = build(tmp_path)
    assert restarted.spool.next_sequence == last + 1
    restarted.start_run(make_config(8, 10))
    restarted.run_to_end()
    events = restarted.spool.read(limit=10_000)["events"]
    assert len({e["event_id"] for e in events}) == len(events)
    assert [e["sequence"] for e in events] == sorted({e["sequence"] for e in events})


def test_production_config_fails_visibly_without_the_simulator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(__import__("sys").modules, "archipelago_sim2d.adapter", None)
    with pytest.raises(SimulatorUnavailable):
        Coordinator(tmp_path, {})


def test_http_requires_tokens_and_serves_events(tmp_path: Path) -> None:
    coord, _ = build(tmp_path)
    server = make_server(coord, "t" * 16, "a" * 16, "127.0.0.1", 0)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def call(method: str, path: str, token: str | None, body: Any = None) -> tuple[int, Any]:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        data = json.dumps(body).encode() if body is not None else None
        try:
            with urllib.request.urlopen(req, data=data, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    try:
        assert call("GET", "/healthz", None)[0] == 200
        assert call("GET", "/readyz", None)[0] == 200
        assert call("POST", "/v1/runs", "wrong", {})[0] == 401
        cfg = make_config(9, 8).model_dump(mode="json")
        code, body = call("POST", "/v1/runs", "t" * 16, {"run_config": cfg})
        assert code == 201, body
        assert call("POST", "/v1/runs", "t" * 16, {"run_config": cfg})[0] in {409, 201}
        deadline = time.monotonic() + 10
        while coord.status != "completed" and time.monotonic() < deadline:
            time.sleep(0.05)
        code, events = call("GET", f"/v1/runs/{body['run_id']}/events?after_sequence=0", "t" * 16)
        assert code == 200 and events["events"]
        assert call("GET", f"/v1/runs/{body['run_id']}/snapshot", "t" * 16)[0] == 401  # admin only
        assert call("GET", f"/v1/runs/{body['run_id']}/snapshot", "a" * 16)[0] == 200
    finally:
        server.shutdown()

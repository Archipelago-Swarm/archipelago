"""Durable replay: events survive an api restart over the same data dir."""

import json
from pathlib import Path
from typing import Any

import pytest
from archipelago_api.eventlog import EventLog, InvalidRunId
from fastapi.testclient import TestClient
from test_api import cmd, make, mgr, start


def drive(c: TestClient, max_ticks: int = 4) -> dict[str, Any]:
    run: dict[str, Any] = start(c, max_ticks=max_ticks)
    run = cmd(c, run, "pause", "p").json()
    for i in range(max_ticks):
        run = cmd(c, run, "step", f"s{i}").json()
    assert run["status"] == "completed"
    return run


def events(c: TestClient, rid: str = "run-a", **q: int) -> dict[str, Any]:
    params = "&".join(f"{k}={v}" for k, v in q.items())
    r = c.get(f"/v1/runs/{rid}/events?{params}")
    assert r.status_code == 200
    body: dict[str, Any] = r.json()
    return body


def test_finished_run_replay_equals_pre_restart(tmp_path: Path) -> None:
    with make(tmp_path) as c:
        drive(c)
        before = events(c, limit=500)
    assert before["events"] and before["latest_sequence"] > 0
    with make(tmp_path) as c2:
        after = events(c2, limit=500)
        assert after == before
        seqs = [e["sequence"] for e in after["events"]]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
        paged = events(c2, after_sequence=seqs[2], limit=2)
        assert [e["sequence"] for e in paged["events"]] == seqs[3:5]
        assert paged["latest_sequence"] == before["latest_sequence"]
        assert paged["oldest_sequence"] == seqs[0]


def test_active_run_keeps_events_and_is_interrupted(tmp_path: Path) -> None:
    c = make(tmp_path)  # no lifespan exit: hard kill
    run = start(c)
    cmd(c, run, "pause", "p")
    before = events(c, limit=500)
    c2 = make(tmp_path)
    got = c2.get("/v1/runs/run-a").json()
    assert (got["status"], got["completion_reason"]) == ("interrupted", "process_restart")
    assert events(c2, limit=500) == before


def test_sequences_continue_after_restart_without_reuse(tmp_path: Path) -> None:
    with make(tmp_path) as c:
        drive(c)
        latest = events(c)["latest_sequence"]
    c2 = make(tmp_path)
    m = mgr(c2)
    m._emit(m.get("run-a"), "status")
    assert events(c2, limit=500)["latest_sequence"] == latest + 1
    c3 = make(tmp_path)
    assert events(c3, limit=500)["events"][-1]["sequence"] == latest + 1


def test_corrupt_tail_is_ignored_and_earlier_events_kept(tmp_path: Path) -> None:
    with make(tmp_path) as c:
        drive(c)
        before = events(c, limit=500)
    f = EventLog(tmp_path).path("run-a")
    with f.open("ab") as fh:
        fh.write(b'{"sequence": 999, "type": "del')  # torn write, no newline
    c2 = make(tmp_path)
    assert events(c2, limit=500) == before
    assert f.read_bytes().endswith(b"\n")  # healed: later appends start on a clean line
    m = mgr(c2)
    m._emit(m.get("run-a"), "status")
    assert events(make(tmp_path), limit=500)["latest_sequence"] == before["latest_sequence"] + 1


def test_garbage_and_out_of_order_lines_are_skipped(tmp_path: Path) -> None:
    log = EventLog(tmp_path)
    f = log.path("r1")
    f.parent.mkdir(parents=True)
    ok = [{"sequence": 1, "type": "status"}, {"sequence": 2, "type": "delta"}]
    lines = [json.dumps(ok[0]), "not json", json.dumps(ok[1]), '{"sequence": 1}', "[1]"]
    f.write_text("\n".join(lines) + "\n")
    got, last = log.load("r1", 100)
    assert list(got) == ok and last == 2


def test_run_ids_cannot_escape_the_directory(tmp_path: Path) -> None:
    log = EventLog(tmp_path)
    for bad in ["../x", "a/b", "..\\x", "/etc/passwd", "", "a\0b", "x" * 129, "a b"]:
        with pytest.raises(InvalidRunId):
            log.path(bad)
    for odd in ["..", ".", "a:b.c"]:  # legal run ids stay inside the dir
        assert log.path(odd).parent == log.dir
        assert log.path(odd).name not in ("..", ".")
    log.append("../evil", {"sequence": 1})  # ignored, not written anywhere
    assert not (tmp_path / "evil.jsonl").exists()
    assert not (tmp_path.parent / "evil.jsonl").exists()
    assert log.load("../evil", 10)[1] == 0


def test_serving_is_bounded_by_event_log_size_but_latest_is_true(tmp_path: Path) -> None:
    with make(tmp_path, event_log_size=3) as c:
        drive(c, max_ticks=5)
        before = events(c, limit=500)
    assert len(before["events"]) == 3
    c2 = make(tmp_path, event_log_size=3)
    after = events(c2, limit=500)
    assert after == before
    assert after["oldest_sequence"] == after["latest_sequence"] - 2
    assert len(EventLog(tmp_path).path("run-a").read_text().splitlines()) > 3  # file keeps all


def test_recovered_stream_does_not_invent_live_data(tmp_path: Path) -> None:
    with make(tmp_path) as c:
        drive(c)
    c2 = make(tmp_path)
    with c2.websocket_connect("/v1/runs/run-a/stream") as ws:
        first = ws.receive_json()
    assert first["status"] == "completed" and not first.get("snapshot")


def test_list_runs_returns_stored_runs_newest_first(tmp_path: Path) -> None:
    with make(tmp_path) as c:
        drive(c)
        runs = c.get("/v1/runs").json()["runs"]
    assert [r["run_id"] for r in runs] == ["run-a"] and runs[0]["status"] == "completed"

"""Launcher: shared-ledger claims, role selection, ticks, detached start/status/stop."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

AGENTS = Path(__file__).resolve().parents[2] / "agents"
sys.path.insert(0, str(AGENTS))
import controller as c  # noqa: E402
import launch as lch  # noqa: E402
from test_controller import make_task  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, **GIT_ENV}
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def clone(origin: Path, dest: Path) -> Path:
    git(dest.parent, "clone", "-q", str(origin), str(dest))
    return dest


@pytest.fixture
def origin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    (seed / "agents").mkdir()
    (seed / "agents" / "OWNERSHIP.yaml").write_text(
        yaml.safe_dump(
            {"roles": {"orchestrator": "A", "integrator": "A", "verifier": "B", "reviewer": "B"}}
        )
    )
    c.save_ledger(
        {
            "version": 1,
            "events": [],
            "tasks": [make_task("T01"), make_task("T02", dependencies=["T01"])],
        },
        seed / "agents" / "TASKS.yaml",
    )
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "seed")
    git(seed, "remote", "add", "origin", str(bare))
    git(seed, "push", "-q", "origin", "main")
    return bare


def use(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    monkeypatch.setattr(c, "ROOT", repo)
    monkeypatch.setattr(c, "LEDGER", repo / "agents" / "TASKS.yaml")
    monkeypatch.setattr(c, "OWNERSHIP", repo / "agents" / "OWNERSHIP.yaml")
    monkeypatch.setattr(lch, "ROOT", repo)
    monkeypatch.setattr(lch, "RUNTIME", repo / ".agent-runtime")


def remote_task(repo: Path, tid: str) -> dict[str, Any]:
    git(repo, "fetch", "-q", "origin")
    data = yaml.safe_load(git(repo, "show", "origin/main:agents/TASKS.yaml"))
    return {t["id"]: t for t in data["tasks"]}[tid]


def test_two_machines_cannot_claim_the_same_task(
    origin: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a, b = clone(origin, tmp_path / "a"), clone(origin, tmp_path / "b")
    use(monkeypatch, a)
    assert c.main(["--remote", "claim", "T01", "--owner", "A/w", "--machine", "A"]) == 0
    use(monkeypatch, b)  # --remote fetches first, so B sees A's claim
    assert c.main(["--remote", "claim", "T01", "--owner", "B/w", "--machine", "B"]) == 1
    assert "not runnable" in capsys.readouterr().err
    task = remote_task(a, "T01")
    assert (task["state"], task["owner"]) == ("CLAIMED", "A/w")
    assert "worktree" not in git(a, "worktree", "list").replace(
        str(a), ""
    )  # temp ledger worktrees are removed


def test_lost_push_race_refetches_and_reapplies(
    origin: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = clone(origin, tmp_path / "a"), clone(origin, tmp_path / "b")
    use(monkeypatch, b)
    real = c.git_out
    state = {"raced": False}

    def racing(*args: str, **kw: Any) -> Any:
        if (
            args[:1] == ("push",) and not state["raced"]
        ):  # another writer lands between our fetch and push
            state["raced"] = True
            use(monkeypatch, a)
            c.REMOTE = "main"
            assert c.main(["--remote", "claim", "T01", "--owner", "A/w", "--machine", "A"]) == 0
            use(monkeypatch, b)
        return real(*args, **kw)

    monkeypatch.setattr(c, "git_out", racing)
    assert c.main(["--remote", "log-event", "--kind", "human_intervention", "--note", "x"]) == 0
    task = remote_task(b, "T01")
    assert task["state"] == "CLAIMED"  # A's claim survived; B's event was re-applied on top
    data = yaml.safe_load(git(b, "show", "origin/main:agents/TASKS.yaml"))
    assert len(data["events"]) == 1


def test_pick_work_orders_roles_by_machine() -> None:
    def d(*tasks: dict[str, Any]) -> dict[str, Any]:
        return {"tasks": list(tasks)}

    inflight = {"owner": "x", "branch": "agent/x", "handoff_file": "h"}
    review = make_task("T01", state="REVIEW", machine="B", **inflight)
    integ = make_task("T02", state="INTEGRATION", machine="B", owned_paths=["other/**"], **inflight)
    queued = make_task("T03", owned_paths=["third/**"])
    roles = {"roles": {"orchestrator": "A", "integrator": "A", "verifier": "B"}}
    orig = c.load_ownership
    c.load_ownership = lambda: roles  # type: ignore[assignment]
    try:
        assert lch.pick_work(d(review, integ, queued), "A")[0] == "integrator"  # type: ignore[index]
        assert lch.pick_work(d(review, queued), "A")[0] == "claim"  # type: ignore[index]
        assert lch.pick_work(d(review, integ, queued), "B")[0] == "verifier"  # type: ignore[index]
        assert lch.pick_work(d(queued), "B") is None  # only the orchestrator claims
        mine = make_task("T04", state="ACTIVE", machine="B", owned_paths=["fourth/**"], **inflight)
        assert lch.pick_work(d(review, mine), "B")[1]["id"] == "T04"  # type: ignore[index]
    finally:
        c.load_ownership = orig  # type: ignore[method-assign]


def fake_claude(bin_dir: Path, log: Path, body: str = "") -> None:
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "claude"
    script.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {log}\n{body}\necho '{{\"ok\":true}}'\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def test_tick_claims_then_runs_a_bounded_session_without_bypass_flags(
    origin: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = clone(origin, tmp_path / "a")
    use(monkeypatch, a)
    log = tmp_path / "claude.log"
    fake_claude(tmp_path / "bin", log)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    assert lch.tick("A", "main", 1, []) == ("claimed", "T01 -> machine A")
    status, detail = lch.tick("A", "main", 1, [])
    assert status == "no_progress" and "worker T01" in detail  # fake session changed nothing
    argv = log.read_text()
    assert "--permission-mode auto" in argv and "dangerously" not in argv
    assert "git push --force" in argv  # denied-tools list passed
    assert "WORKER for T01" in argv


def test_tick_reports_provider_limit_and_stop_file(
    origin: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = clone(origin, tmp_path / "a")
    use(monkeypatch, a)
    fake_claude(tmp_path / "bin", tmp_path / "l", body="echo 'Claude usage limit reached'")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    assert lch.tick("A", "main", 1, [])[0] == "claimed"
    assert lch.tick("A", "main", 1, [])[0] == "limit"
    lch.cmd_stop(type("N", (), {"machine": "A"})())  # type: ignore[arg-type]
    assert lch.tick("A", "main", 1, [])[0] == "stop"


def test_tick_idle_when_nothing_for_this_machine(
    origin: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = clone(origin, tmp_path / "b")
    use(monkeypatch, b)
    status, detail = lch.tick("B", "main", 1, [])
    assert status == "idle" and "no runnable" in detail


def test_start_detaches_reports_status_and_stops_on_no_progress(
    origin: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a = clone(origin, tmp_path / "a")
    use(monkeypatch, a)
    fake_claude(tmp_path / "bin", tmp_path / "l", body="sleep 2")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("ARCHIPELAGO_ROOT", str(a))  # the detached child operates on this clone
    assert lch.main(["status", "--machine", "A"]) == 1
    assert "NOT_STARTED" in capsys.readouterr().out
    assert lch.main(["start", "--machine", "A", "--dry-run"]) == 0
    assert lch.main(["start", "--machine", "A", "--slice-minutes", "1"]) == 0
    assert "ALIVE" in capsys.readouterr().out
    assert lch.main(["start", "--machine", "A"]) == 1  # single instance
    for _ in range(100):  # claim, two no-progress sessions, then the loop gives up by itself
        state = lch.read_state("A") or {}
        if state.get("stop_reason"):
            break
        time.sleep(0.2)
    assert "no progress twice" in state["stop_reason"]
    for _ in range(50):  # the stop reason is written just before the process exits
        if lch.liveness("A")[0] == "DEAD":
            break
        time.sleep(0.1)
    capsys.readouterr()
    assert lch.main(["status", "--machine", "A"]) == 1
    assert "DEAD" in capsys.readouterr().out
    assert remote_task(a, "T01")["state"] == "CLAIMED"  # the loop's claim is published, not local


def test_start_refuses_stop_file_and_invalid_ledger(
    origin: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = clone(origin, tmp_path / "a")
    use(monkeypatch, a)
    lch.cmd_stop(type("N", (), {"machine": "A"})())  # type: ignore[arg-type]
    assert lch.main(["start", "--machine", "A", "--dry-run"]) == 1


def test_stalled_heartbeat_is_not_reported_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lch, "RUNTIME", tmp_path)
    lch.write_state(
        "A",
        pid=os.getpid(),
        pid_identity=lch.pid_identity(os.getpid()),
        runner="loop",
        heartbeat_at="2020-01-01T00:00:00Z",
        slice_minutes=1,
    )
    assert lch.liveness("A")[0] == "STALLED"
    lch.write_state("A", pid=2**22 + 12345)
    assert lch.liveness("A")[0] == "DEAD"


def test_slots_run_two_workers_and_leave_review_to_the_slotless_tick() -> None:
    inflight = {"branch": "agent/x", "handoff_file": "h"}
    w1 = make_task(
        "T01", state="ACTIVE", machine="A", owner="A/w1", owned_paths=["a/**"], **inflight
    )
    review = make_task(
        "T02", state="REVIEW", machine="A", owner="A/w2", owned_paths=["b/**"], **inflight
    )
    queued = make_task("T03", owned_paths=["c/**"])
    roles = {"roles": {"orchestrator": "A", "integrator": "A", "verifier": ["B", "A"]}}
    orig = c.load_ownership
    c.load_ownership = lambda: roles  # type: ignore[assignment]
    try:
        data = {"tasks": [w1, review, queued]}
        assert lch.pick_work(data, "A", "w1")[1]["id"] == "T01"  # type: ignore[index]
        assert lch.pick_work(data, "A", "w2")[0] == "claim"  # a free slot claims new work
        assert lch.pick_work(data, "A")[0] == "verifier"  # type: ignore[index]  # A may verify
        w2 = make_task(
            "T04", state="CLAIMED", machine="A", owner="A/w2", owned_paths=["d/**"], **inflight
        )
        full = {"tasks": [w1, w2, queued]}
        assert lch.pick_work(full, "A", "w1")[1]["id"] == "T01"  # type: ignore[index]
        assert lch.pick_work(full, "A") is None  # slot-owned work is not stolen; machine is full
    finally:
        c.load_ownership = orig  # type: ignore[method-assign]

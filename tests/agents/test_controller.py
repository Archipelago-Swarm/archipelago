"""Task-ledger controller: lifecycle rules, retry cutoff, verifier gate, validation."""

from __future__ import annotations

import copy
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))
import controller as c  # noqa: E402

RETRY = {
    "test_failure": 5,
    "build_failure": 3,
    "integration_failure": 3,
    "same_failure_signature": 2,
}


def make_task(tid: str, **over: Any) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": tid,
        "name": f"Task {tid}",
        "description": "A task used in controller tests.",
        "state": "QUEUED",
        "priority": 5,
        "owner": None,
        "machine": None,
        "branch": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "dependencies": [],
        "blocked_by": [],
        "owned_paths": [f"src/{tid.lower()}/**"],
        "contracts": [],
        "acceptance": {
            "commands": [{"command": "true", "expected_exit_code": 0}],
            "assertions": [{"description": "It works as described."}],
        },
        "retry_policy": dict(RETRY),
        "last_good_commit": None,
        "artifacts": [],
        "handoff_file": None,
        "notes": "",
    }
    task.update(over)
    return task


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    (tmp_path / "agents").mkdir()
    monkeypatch.setattr(c, "ROOT", tmp_path)
    monkeypatch.setattr(c, "LEDGER", tmp_path / "agents" / "TASKS.yaml")
    monkeypatch.setattr(c, "OWNERSHIP", tmp_path / "agents" / "OWNERSHIP.yaml")
    (tmp_path / "agents" / "OWNERSHIP.yaml").write_text(
        yaml.safe_dump({"roles": {"integrator": "A"}}), encoding="utf-8"
    )
    c.save_ledger(
        {
            "version": 1,
            "events": [],
            "tasks": [make_task("T01"), make_task("T02", dependencies=["T01"])],
        }
    )
    yield tmp_path


def run(*args: str) -> int:
    return c.main(list(args))


def state(tid: str) -> str:
    return str(c.get_task(c.load_ledger(), tid)["state"])


def handoff(repo: Path, tid: str) -> None:
    p = repo / "agents" / "handoffs" / tid
    p.mkdir(parents=True, exist_ok=True)
    (p / "LATEST.md").write_text("# handoff\n", encoding="utf-8")


def to_review(repo: Path, tid: str = "T01") -> None:
    assert run("claim", tid, "--owner", "B/w1", "--machine", "B") == 0
    handoff(repo, tid)
    assert run("start", tid) == 0
    assert run("review", tid, "--commit", "abc1234") == 0


def verdict(repo: Path, tid: str, status: str, **over: Any) -> None:
    v: dict[str, Any] = {
        "task": tid,
        "status": status,
        "verified_commit": "abc1234",
        "verifier": "B/v",
        "checked_at": "2026-01-01T00:00:00Z",
        "commands": [{"command": "true", "expected_exit_code": 0, "actual_exit_code": 0}],
        "failures": [],
        "required_actions": [],
    }
    if status == "FAIL":
        v["failures"] = [
            {
                "type": "stub_or_todo",
                "file": "src/t01/a.py",
                "kind": "test_failure",
                "description": "Function is a stub.",
            }
        ]
        v["required_actions"] = ["Implement it."]
    v.update(over)
    (repo / "agents" / "handoffs" / tid / "VERIFICATION.yaml").write_text(
        yaml.safe_dump(v), encoding="utf-8"
    )


def test_next_respects_dependencies_blockers_and_overlap(repo: Path) -> None:
    ledger = c.load_ledger()
    assert [t["id"] for t in c.runnable(ledger)] == ["T01"]
    ledger["tasks"].append(make_task("T03", blocked_by=["human:credentials"]))
    ledger["tasks"].append(make_task("T04", owned_paths=["src/t01/sub/**"]))
    assert [t["id"] for t in c.runnable(ledger)] == ["T01", "T04"]
    c.save_ledger(ledger)
    assert run("claim", "T01", "--owner", "A/w", "--machine", "A") == 0
    assert [t["id"] for t in c.runnable(c.load_ledger())] == []  # T04 overlaps in-flight T01


def test_claim_of_unrunnable_task_is_rejected(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("claim", "T02", "--owner", "A/w", "--machine", "A") == 1
    assert "waiting on T01" in capsys.readouterr().err
    assert state("T02") == "QUEUED"


def test_worker_cannot_skip_verification_or_complete(repo: Path) -> None:
    to_review(repo)
    assert run("complete", "T01", "--commit", "def5678", "--machine", "A") == 1
    assert state("T01") == "REVIEW"


def test_start_requires_handoff_and_review_requires_commit(repo: Path) -> None:
    assert run("claim", "T01", "--owner", "B/w1", "--machine", "B") == 0
    assert run("start", "T01") == 1  # no handoff yet
    handoff(repo, "T01")
    assert run("start", "T01") == 0
    assert run("review", "T01") == 1  # no last_good_commit
    assert state("T01") == "ACTIVE"


def test_verifier_pass_then_integrator_completes_and_unblocks_dependents(repo: Path) -> None:
    to_review(repo)
    verdict(repo, "T01", "PASS")
    assert run("verify", "T01") == 0 and state("T01") == "INTEGRATION"
    assert (
        run("complete", "T01", "--commit", "def5678", "--machine", "B") == 1
    )  # B is not the integrator
    assert run("complete", "T01", "--commit", "def5678", "--machine", "A") == 0
    assert state("T01") == "COMPLETE"
    assert [t["id"] for t in c.runnable(c.load_ledger())] == ["T02"]


def test_pass_verdict_must_run_every_declared_command_at_the_right_commit(repo: Path) -> None:
    to_review(repo)
    verdict(repo, "T01", "PASS", commands=[])
    assert run("verify", "T01") == 1
    verdict(repo, "T01", "PASS", verified_commit="fffffff")
    assert run("verify", "T01") == 1
    verdict(
        repo,
        "T01",
        "PASS",
        commands=[{"command": "true", "expected_exit_code": 0, "actual_exit_code": 1}],
    )
    assert run("verify", "T01") == 1
    assert state("T01") == "REVIEW"


def test_missing_or_invalid_verdict_is_infrastructure_failure_not_task_failure(repo: Path) -> None:
    to_review(repo)
    assert run("verify", "T01") == 1
    verdict(repo, "T01", "FAIL", failures=[])
    assert run("verify", "T01") == 1
    task = c.get_task(c.load_ledger(), "T01")
    assert task["state"] == "REVIEW"
    assert task.get("attempts", {}).get("test_failure", 0) == 0


def test_fail_verdict_returns_to_worker_then_same_signature_blocks(repo: Path) -> None:
    to_review(repo)
    verdict(repo, "T01", "FAIL")
    assert run("verify", "T01") == 0 and state("T01") == "ACTIVE"
    assert run("review", "T01", "--commit", "abc1234") == 0
    assert run("verify", "T01") == 0  # same signature the second time
    task = c.get_task(c.load_ledger(), "T01")
    assert task["state"] == "BLOCKED"
    assert any(b.startswith("retry:same failure signature") for b in task["blocked_by"])
    assert run("review", "T01") == 1


def test_retry_budget_blocks_and_blocker_report_is_enforced(repo: Path) -> None:
    assert run("claim", "T01", "--owner", "B/w1", "--machine", "B") == 0
    handoff(repo, "T01")
    assert run("start", "T01") == 0
    for i in range(4):  # distinct signatures, budget is 5
        assert run("record-failure", "T01", "--kind", "test_failure", "--signature", f"s{i}") == 0
        assert state("T01") == "ACTIVE"
    assert run("record-failure", "T01", "--kind", "test_failure", "--signature", "s4") == 0
    assert state("T01") == "BLOCKED"
    errors = c.validate_ledger(c.load_ledger())
    assert any("BLOCKED without" in e for e in errors)  # report required
    blocker = repo / "agents" / "handoffs" / "T01" / "BLOCKER.md"
    blocker.write_text("\n".join(f"## {h}\ntext\n" for h in c.BLOCKER_HEADINGS), encoding="utf-8")
    assert c.validate_ledger(c.load_ledger()) == []
    assert run("unblock", "T01") == 0 and state("T01") == "QUEUED"
    assert c.get_task(c.load_ledger(), "T01")["attempts"] == {}


def test_block_requires_complete_report(repo: Path) -> None:
    assert run("claim", "T01", "--owner", "B/w1", "--machine", "B") == 0
    handoff(repo, "T01")
    assert run("start", "T01") == 0
    assert run("block", "T01", "--reason", "env:docker") == 1
    (repo / "agents" / "handoffs" / "T01" / "BLOCKER.md").write_text(
        "## Error\nx\n", encoding="utf-8"
    )
    assert run("block", "T01", "--reason", "env:docker") == 1
    assert state("T01") == "ACTIVE"


def test_validate_catches_schema_cycle_overlap_and_unknown_dependency(repo: Path) -> None:
    ledger = c.load_ledger()
    bad = copy.deepcopy(ledger)
    bad["tasks"][0]["state"] = "DONE"
    assert any("state" in e for e in c.validate_ledger(bad, check_files=False))
    cyc = copy.deepcopy(ledger)
    cyc["tasks"][0]["dependencies"] = ["T02"]
    assert any("cycle" in e for e in c.validate_ledger(cyc, check_files=False))
    unk = copy.deepcopy(ledger)
    unk["tasks"][1]["dependencies"] = ["T99"]
    assert any("T99" in e for e in c.validate_ledger(unk, check_files=False))
    ov = copy.deepcopy(ledger)
    for t in ov["tasks"]:
        t.update(
            state="ACTIVE",
            owner="x",
            machine="A",
            branch="agent/x",
            handoff_file="h",
            owned_paths=["src/shared/**"],
            dependencies=[],
        )
    assert any("overlapping" in e for e in c.validate_ledger(ov, check_files=False))


def test_complete_requires_integration_state(repo: Path) -> None:
    assert run("complete", "T01", "--commit", "def5678", "--machine", "A") == 1


def test_events_feed_process_review_and_run_summary(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("log-event", "--kind", "human_intervention", "--note", "restarted worker") == 0
    assert run("log-event", "--kind", "unsupported_automation", "--note", "watcher died") == 0
    summary = c.build_run_summary(c.load_ledger(), "r1")
    assert summary["autonomy"]["human_interventions"] == 1
    assert summary["autonomy"]["unsupported_automation_events"] == 1
    capsys.readouterr()
    assert run("review-process") == 0
    out = capsys.readouterr().out
    assert "human interventions logged" in out and "unsupported-automation" in out


def test_real_ledger_is_valid() -> None:
    assert c.validate_ledger(c.load_ledger()) == []

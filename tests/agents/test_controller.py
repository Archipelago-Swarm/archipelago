"""Task-ledger controller: lifecycle rules, retry cutoff, verifier gate, validation."""

from __future__ import annotations

import copy
import os
import subprocess
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
    "same_failure_signature": 3,
}
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, env={**os.environ, **GIT_ENV}
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def commit(repo: Path, name: str) -> str:
    (repo / f"{name}.txt").write_text(name, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


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
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / ".gitignore").write_text("agents/\n", encoding="utf-8")  # ledger stays untracked
    commit(tmp_path, "base")
    yield tmp_path


def run(*args: str) -> int:
    return c.main(list(args))


def state(tid: str) -> str:
    return str(c.get_task(c.load_ledger(), tid)["state"])


def handoff(repo: Path, tid: str) -> None:
    p = repo / "agents" / "handoffs" / tid
    p.mkdir(parents=True, exist_ok=True)
    (p / "LATEST.md").write_text("# handoff\n", encoding="utf-8")


OWNER = "A/w1"


def to_active(repo: Path, tid: str = "T01") -> None:
    assert run("claim", tid, "--owner", OWNER, "--machine", "A") == 0
    handoff(repo, tid)
    assert run("start", tid, "--by", OWNER) == 0


def to_review(repo: Path, tid: str = "T01") -> str:
    """Claim, start and send to REVIEW at a real commit; returns its full sha."""
    to_active(repo, tid)
    work = commit(repo, f"work-{tid}")
    assert run("review", tid, "--by", OWNER, "--commit", work) == 0
    return work


def ledger_task(tid: str = "T01") -> dict[str, Any]:
    return c.get_task(c.load_ledger(), tid)


def verdict(repo: Path, tid: str, status: str, **over: Any) -> None:
    v: dict[str, Any] = {
        "task": tid,
        "status": status,
        "verified_commit": ledger_task(tid)["last_good_commit"],
        "verifier": "B/v",
        "checked_at": "2026-01-01T00:00:00Z",
        "commands": [{"command": "true", "expected_exit_code": 0, "actual_exit_code": 0}],
        "assertions": [{"description": "It works as described.", "result": "met"}],
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
    work = to_review(repo)
    assert run("complete", "T01", "--commit", work, "--machine", "A") == 1
    assert state("T01") == "REVIEW"


def test_start_requires_handoff_and_review_requires_commit(repo: Path) -> None:
    assert run("claim", "T01", "--owner", OWNER, "--machine", "A") == 0
    assert run("start", "T01", "--by", OWNER) == 1  # no handoff yet
    handoff(repo, "T01")
    assert run("start", "T01", "--by", OWNER) == 0
    assert run("review", "T01", "--by", OWNER) == 1  # no last_good_commit
    assert state("T01") == "ACTIVE"


def test_verifier_pass_then_integrator_completes_and_unblocks_dependents(repo: Path) -> None:
    work = to_review(repo)
    verdict(repo, "T01", "PASS")
    assert run("verify", "T01", "--machine", "B") == 0 and state("T01") == "INTEGRATION"
    merge = integrate(repo, work)
    assert run("complete", "T01", "--commit", merge, "--machine", "B") == 1  # B is not integrator
    assert run("complete", "T01", "--commit", merge, "--machine", "A") == 0
    assert state("T01") == "COMPLETE" and ledger_task()["last_good_commit"] == merge
    assert [t["id"] for t in c.runnable(c.load_ledger())] == ["T02"]


def integrate(repo: Path, work: str) -> str:
    """Merge the task commit into main with a merge commit, as the integrator does."""
    git(repo, "checkout", "-q", "-b", "side", "main")
    commit(repo, "side")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge", "side", work)
    return git(repo, "rev-parse", "HEAD")


def test_pass_verdict_must_run_every_declared_command_at_the_right_commit(repo: Path) -> None:
    work = to_review(repo)
    verdict(repo, "T01", "PASS", commands=[])
    assert run("verify", "T01", "--machine", "B") == 1
    verdict(repo, "T01", "PASS", verified_commit=git(repo, "rev-parse", "HEAD~1"))
    assert run("verify", "T01", "--machine", "B") == 1
    verdict(repo, "T01", "PASS", verified_commit="fffffff")  # unresolvable
    assert run("verify", "T01", "--machine", "B") == 1
    verdict(
        repo,
        "T01",
        "PASS",
        commands=[{"command": "true", "expected_exit_code": 0, "actual_exit_code": 1}],
    )
    assert run("verify", "T01", "--machine", "B") == 1
    assert state("T01") == "REVIEW"
    verdict(repo, "T01", "PASS", verified_commit=work[:9])  # a short sha is normalized
    assert run("verify", "T01", "--machine", "B") == 0


def test_verify_judges_exit_codes_by_the_ledger_not_the_verdict(repo: Path) -> None:
    to_review(repo)
    lying = [{"command": "true", "expected_exit_code": 1, "actual_exit_code": 1}]
    verdict(repo, "T01", "PASS", commands=lying)  # verdict agrees with itself, not the ledger
    assert run("verify", "T01", "--machine", "B") == 1
    extra = [
        {"command": "true", "expected_exit_code": 0, "actual_exit_code": 0},
        {"command": "echo hi", "expected_exit_code": 0, "actual_exit_code": 0},
    ]
    verdict(repo, "T01", "PASS", commands=extra)  # unknown command
    assert run("verify", "T01", "--machine", "B") == 1
    assert state("T01") == "REVIEW"


def test_pass_requires_every_assertion_met(repo: Path) -> None:
    to_review(repo)
    verdict(repo, "T01", "PASS", assertions=[])
    assert run("verify", "T01", "--machine", "B") == 1
    verdict(repo, "T01", "PASS", assertions=[{"description": "other", "result": "met"}])
    assert run("verify", "T01", "--machine", "B") == 1
    verdict(
        repo,
        "T01",
        "PASS",
        assertions=[{"description": "It works as described.", "result": "unmet"}],
    )
    assert run("verify", "T01", "--machine", "B") == 1
    verdict(repo, "T01", "PASS", assertions=[{"description": "It works", "result": "maybe"}])
    assert run("verify", "T01", "--machine", "B") == 1
    assert state("T01") == "REVIEW"
    verdict(repo, "T01", "PASS")
    assert run("verify", "T01", "--machine", "B") == 0


def test_verify_needs_a_commit_and_an_independent_verifier(repo: Path) -> None:
    to_review(repo)
    verdict(repo, "T01", "PASS", verifier=OWNER)  # the owner cannot verify own work
    assert run("verify", "T01", "--machine", "B") == 1
    verdict(repo, "T01", "PASS")
    task = ledger_task()
    task["last_good_commit"] = None
    ledger = c.load_ledger()
    ledger["tasks"][0] = task
    c.save_ledger(ledger)
    assert run("verify", "T01", "--machine", "B") == 1  # null last_good_commit never verifies
    assert state("T01") == "REVIEW"


def test_missing_or_invalid_verdict_is_infrastructure_failure_not_task_failure(repo: Path) -> None:
    to_review(repo)
    assert run("verify", "T01", "--machine", "B") == 1
    verdict(repo, "T01", "FAIL", failures=[])
    assert run("verify", "T01", "--machine", "B") == 1
    task = c.get_task(c.load_ledger(), "T01")
    assert task["state"] == "REVIEW"
    assert task.get("attempts", {}).get("test_failure", 0) == 0


def test_fail_verdict_returns_to_worker_then_same_signature_blocks(repo: Path) -> None:
    to_review(repo)
    for i in range(3):  # three attempts at one root cause, line numbers differ
        verdict(
            repo,
            "T01",
            "FAIL",
            failures=[
                {
                    "type": "stub_or_todo",
                    "file": f"src/t01/a.py:{10 + i}-{20 + i}",
                    "kind": "test_failure",
                    "description": "Function is a stub.",
                }
            ],
        )
        assert run("verify", "T01", "--machine", "B") == 0
        if i < 2:
            assert state("T01") == "ACTIVE"  # one and two attempts do not block
            work = commit(repo, f"retry{i}")
            assert run("review", "T01", "--by", OWNER, "--commit", work) == 0
    task = ledger_task()
    assert task["state"] == "BLOCKED"
    assert task["attempts"]["signatures"] == {"stub_or_todo:src/t01/a.py": 3}
    assert any(b.startswith("retry:same failure signature") for b in task["blocked_by"])
    assert run("review", "T01", "--by", OWNER) == 1


def write_blocker(repo: Path, tid: str = "T01") -> None:
    blocker = repo / "agents" / "handoffs" / tid / "BLOCKER.md"
    blocker.write_text("\n".join(f"## {h}\ntext\n" for h in c.BLOCKER_HEADINGS), encoding="utf-8")


def test_retry_budget_blocks_and_blocker_report_is_enforced(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(c, "current_branch", lambda: "agent/T01-task-t01")  # as on the task branch
    to_active(repo)
    for i in range(4):  # distinct signatures, budget is 5
        assert run("record-failure", "T01", "--by", OWNER, "--kind", "test_failure",
                   "--signature", f"s{i}") == 0  # fmt: skip
        assert state("T01") == "ACTIVE"
    assert run("record-failure", "T01", "--by", OWNER, "--kind", "test_failure",
               "--signature", "s4") == 0  # fmt: skip
    assert state("T01") == "BLOCKED"
    errors = c.validate_ledger(c.load_ledger())
    assert any("BLOCKED without" in e for e in errors)  # report required
    write_blocker(repo)
    assert c.validate_ledger(c.load_ledger()) == []
    assert run("unblock", "T01", "--by", "A") == 0 and state("T01") == "QUEUED"
    assert ledger_task()["attempts"] == {}


def test_three_line_number_variants_of_one_cause_block_and_two_do_not(repo: Path) -> None:
    to_active(repo)
    sigs = ["AssertionError at x.py:10", "AssertionError at x.py:99-120", "AssertionError at x.py"]
    for i, sig in enumerate(sigs):
        assert run("record-failure", "T01", "--by", OWNER, "--kind", "test_failure",
                   "--signature", sig) == 0  # fmt: skip
        assert state("T01") == ("BLOCKED" if i == 2 else "ACTIVE")
    assert ledger_task()["attempts"]["signatures"] == {"AssertionError at x.py": 3}
    assert c.normalize_signature("a.py:1:2 line 7 #L4") == "a.py"


def test_loader_defaults_same_failure_signature_to_three(repo: Path) -> None:
    ledger = c.load_ledger()
    del ledger["tasks"][0]["retry_policy"]["same_failure_signature"]
    c.save_ledger(ledger)
    assert c.load_ledger()["tasks"][0]["retry_policy"]["same_failure_signature"] == 3
    two = c.load_ledger()
    two["tasks"][0]["retry_policy"]["same_failure_signature"] = 2  # cannot undercut CONTRACT.md
    task = two["tasks"][0]
    assert c.bump_failure(task, "test_failure", "x") is None
    assert c.bump_failure(task, "test_failure", "x") is None
    assert c.bump_failure(task, "test_failure", "x") is not None


def test_block_requires_complete_report(repo: Path) -> None:
    to_active(repo)
    assert run("block", "T01", "--by", OWNER, "--reason", "env:docker") == 1
    (repo / "agents" / "handoffs" / "T01" / "BLOCKER.md").write_text(
        "## Error\nx\n", encoding="utf-8"
    )
    assert run("block", "T01", "--by", OWNER, "--reason", "env:docker") == 1
    assert state("T01") == "ACTIVE"


def test_only_the_owner_moves_a_task(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("claim", "T01", "--owner", OWNER, "--machine", "A") == 0
    handoff(repo, "T01")
    assert run("start", "T01", "--by", "A/other") == 1
    assert "refused" in capsys.readouterr().err
    assert state("T01") == "CLAIMED"
    assert run("start", "T01", "--by", OWNER) == 0
    work = commit(repo, "w")
    assert run("review", "T01", "--by", "A/other", "--commit", work) == 1
    assert run("record-failure", "T01", "--by", "A", "--kind", "test_failure",
               "--signature", "s") == 1  # fmt: skip
    write_blocker(repo)
    assert run("block", "T01", "--by", "A/other", "--reason", "env:docker") == 1
    assert state("T01") == "ACTIVE" and "failures" not in ledger_task().get("attempts", {})


def test_requeue_is_owner_or_integrator_and_frees_the_task(repo: Path) -> None:
    to_active(repo)
    assert run("requeue", "T01", "--by", "B/other") == 1  # B is not the integrator machine
    assert run("requeue", "T01", "--by", "A/orchestrator") == 0  # A holds the integrator role
    task = ledger_task()
    assert task["state"] == "QUEUED"
    assert (task["owner"], task["machine"], task["branch"]) == (None, None, None)
    assert run("claim", "T01", "--owner", "A/w", "--machine", "A") == 0  # re-claimable elsewhere


def block_with(repo: Path, reason: str) -> None:
    to_active(repo)
    write_blocker(repo)
    assert run("block", "T01", "--by", OWNER, "--reason", reason) == 0


def test_unblock_needs_resolution_of_human_blockers_and_is_role_gated(repo: Path) -> None:
    block_with(repo, "human:credentials")
    assert run("unblock", "T01", "--by", "B/stranger") == 1
    assert run("unblock", "T01", "--by", "A") == 1  # human blocker unresolved
    assert state("T01") == "BLOCKED"
    assert run("unblock", "T01", "--by", OWNER, "--resolved", "operator added the key") == 0
    assert state("T01") == "QUEUED"
    assert "resolved: operator added the key" in ledger_task()["history"][-1]["note"]


def test_unblock_cycles_are_capped_then_the_task_fails(repo: Path) -> None:
    block_with(repo, "env:docker")
    for _ in range(c.UNBLOCK_CAP):
        assert run("unblock", "T01", "--by", "A") == 0
        assert state("T01") == "QUEUED"
        assert run("claim", "T01", "--owner", OWNER, "--machine", "A") == 0
        assert run("start", "T01", "--by", OWNER) == 0
        assert run("block", "T01", "--by", OWNER, "--reason", "env:docker") == 0
    assert run("unblock", "T01", "--by", "A") == 0
    assert state("T01") == "FAILED"
    assert ledger_task()["history"][-1]["event"] == "unblock_cap"


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
    assert run("complete", "T01", "--commit", git(repo, "rev-parse", "HEAD"), "--machine", "A") == 1


def to_integration(repo: Path) -> str:
    work = to_review(repo)
    verdict(repo, "T01", "PASS")
    assert run("verify", "T01", "--machine", "B") == 0
    return work


def test_complete_rejects_commits_that_are_not_the_integrated_verified_work(repo: Path) -> None:
    work = to_integration(repo)
    assert run("complete", "T01", "--commit", "deadbeef", "--machine", "A") == 1  # unresolvable
    assert run("complete", "T01", "--commit", work, "--machine", "A") == 1  # not a merge commit
    git(repo, "checkout", "-q", "-b", "stray", "main~1")
    stray = commit(repo, "stray")
    git(repo, "checkout", "-q", "main")
    # stray is real but not an ancestor of main's tip and lacks the verified work
    assert run("complete", "T01", "--commit", stray, "--machine", "A") == 1
    git(repo, "checkout", "-q", "-b", "elsewhere", "main~1")
    git(repo, "merge", "-q", "--no-ff", "-m", "m", "stray")  # merge commit, wrong content
    unrelated = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    assert run("complete", "T01", "--commit", unrelated, "--machine", "A") == 1
    assert state("T01") == "INTEGRATION"
    assert run("complete", "T01", "--commit", integrate(repo, work), "--machine", "A") == 0


def test_complete_accepts_a_descendant_of_the_verified_commit_on_the_tip(repo: Path) -> None:
    work = to_integration(repo)
    follow_up = commit(repo, "follow-up")  # fast-forwarded integration plus a later commit
    assert git(repo, "merge-base", work, follow_up) == work
    assert run("complete", "T01", "--commit", follow_up, "--machine", "A") == 0
    assert ledger_task()["last_good_commit"] == follow_up


def test_complete_checks_against_origin_ledger_branch_when_present(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    work = to_integration(repo)
    merge = integrate(repo, work)
    bare = tmp_path_factory.mktemp("origin") / "o.git"
    git(repo, "init", "-q", "--bare", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main~1:refs/heads/main")  # origin/main lacks the merge
    git(repo, "fetch", "-q", "origin")
    assert run("complete", "T01", "--commit", merge, "--machine", "A") == 1
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    assert run("complete", "T01", "--commit", merge, "--machine", "A") == 0


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


def test_verify_requires_a_verifier_different_from_the_task_owner(repo: Path) -> None:
    """Single computer: independence is by agent identity, not by machine."""
    to_review(repo)
    verdict(repo, "T01", "PASS", verifier=OWNER)  # the worker verifying its own work
    assert run("verify", "T01") == 1
    assert state("T01") == "REVIEW"
    verdict(
        repo, "T01", "PASS", verifier=f"  {OWNER.upper()} "
    )  # same identity, different spelling
    assert run("verify", "T01") == 1
    assert state("T01") == "REVIEW"
    verdict(repo, "T01", "PASS", verifier="A/independent-reviewer")
    assert run("verify", "T01") == 0
    assert state("T01") == "INTEGRATION"


def test_review_releases_paths_but_writing_holds_them(repo: Path) -> None:
    ledger = c.load_ledger()
    ledger["tasks"].append(make_task("T05", owned_paths=["src/t01/**"]))
    c.save_ledger(ledger)
    assert run("claim", "T01", "--owner", "A/w1", "--machine", "A") == 0
    assert "T05" not in [t["id"] for t in c.runnable(c.load_ledger())]  # T01 is being written
    handoff(repo, "T01")
    assert run("start", "T01", "--by", "A/w1") == 0
    work = commit(repo, "work-T01")
    assert run("review", "T01", "--by", "A/w1", "--commit", work) == 0
    assert "T05" in [t["id"] for t in c.runnable(c.load_ledger())]  # frozen in REVIEW: lock freed


def test_ledger_file_is_never_a_path_conflict() -> None:
    assert not c.paths_overlap(["agents/TASKS.yaml", "a/**"], ["agents/TASKS.yaml", "b/**"])
    assert c.paths_overlap(["a/**"], ["a/x/**"])


def test_runnable_prefers_the_task_that_unlocks_most(repo: Path) -> None:
    ledger = c.load_ledger()
    ledger["tasks"] = [
        make_task("T01", priority=3),
        make_task("T09", priority=3),
        make_task("T10", priority=3, dependencies=["T09"]),
        make_task("T11", priority=3, dependencies=["T10"]),
    ]
    assert [t["id"] for t in c.runnable(ledger)] == ["T09", "T01"]


def test_reap_returns_abandoned_claims_to_queue(repo: Path) -> None:
    assert run("claim", "T01", "--owner", "A/w1", "--machine", "A") == 0
    assert run("reap") == 0 and state("T01") == "CLAIMED"  # fresh claim survives
    ledger = c.load_ledger()
    c.get_task(ledger, "T01")["updated_at"] = "2026-01-01T00:00:00Z"
    c.save_ledger(ledger)
    assert run("reap", "--dry-run") == 0 and state("T01") == "CLAIMED"
    assert run("reap") == 0
    task = c.get_task(c.load_ledger(), "T01")
    assert task["state"] == "QUEUED" and task["owner"] is None
    assert any(h["event"] == "claim_expired" for h in task["history"])


def test_stalls_names_who_must_act(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = c.load_ledger()
    ledger["tasks"].append(make_task("T05", blocked_by=["human:approve spend"]))
    c.save_ledger(ledger)
    to_review(repo)
    assert run("stalls") == 0
    out = capsys.readouterr().out
    assert "NEEDS_VERIFIER" in out and "HUMAN" in out and "T02" in out and "waits on T01" in out


def test_plan_starts_only_conflict_free_tasks_within_slots(repo: Path) -> None:
    ledger = c.load_ledger()
    ledger["tasks"] = [
        make_task("T01", owned_paths=["x/**"]),
        make_task("T02", owned_paths=["x/sub/**"]),
        make_task("T03", owned_paths=["y/**"]),
        make_task("T04", owned_paths=["z/**"]),
    ]
    assert [t["id"] for t in c.plan_batch(ledger, "A", 2)] == ["T01", "T03"]


def test_fresh_claim_does_not_require_the_handoff_on_the_ledger_branch(repo: Path) -> None:
    assert run("claim", "T01", "--owner", "cloud/w1", "--machine", "cloud") == 0
    assert c.validate_ledger(c.load_ledger(), check_files=True) == []
    assert (
        run("start", "T01", "--by", "cloud/w1") == 1
    )  # still refused until the worker writes the handoff


def test_handoff_files_are_only_required_on_the_task_branch(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    to_review(repo)
    (repo / "agents" / "handoffs" / "T01" / "LATEST.md").unlink()
    monkeypatch.setattr(c, "current_branch", lambda: "main")
    assert c.validate_ledger(c.load_ledger(), check_files=True) == []  # ledger branch: not checked
    branch = c.get_task(c.load_ledger(), "T01")["branch"]
    monkeypatch.setattr(c, "current_branch", lambda: branch)
    assert any("does not exist" in e for e in c.validate_ledger(c.load_ledger(), check_files=True))

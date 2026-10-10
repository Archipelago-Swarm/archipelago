"""New B assignments and existing B prep work must both be dispatchable."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "agents"))
import driver  # noqa: E402


def test_waits_for_new_b_assignment_before_any_task_branch_exists() -> None:
    assert driver.report_machines({"T13": "B"}) == {"B"}


def test_b_retries_the_same_run_when_worker_exits_without_report() -> None:
    plan = {"run_id": "20261010T151923Z", "stop_at_utc": "2099-01-01T00:00:00Z"}

    class StopPolling(Exception):
        pass

    with (
        patch.object(driver, "active", return_value=plan),
        patch.object(driver, "report", side_effect=[None, None, None, {"T13": "review"}]),
        patch.object(driver, "git"),
        patch.object(
            driver.subprocess,
            "run",
            side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)],
        ) as run,
        patch.object(driver.time, "sleep", side_effect=[None, StopPolling]),
    ):
        with pytest.raises(StopPolling):
            driver.driver_b(SimpleNamespace(until_utc=None, max_rounds=10))
    assert run.call_count == 2


def test_new_b_task_starts_from_current_main() -> None:
    state = {"done": ["T06"], "attempts": {}}
    with (
        patch.object(driver, "board", return_value={"T13": ("B", ["T06"])}),
        patch.object(driver, "card_paths", return_value=["services/api/"]),
        patch.object(driver, "git", return_value=""),
    ):
        tasks = driver.next_plan("20261010T010000Z", {}, state)
    assert tasks == [{"id": "T13", "machine": "B", "paths": ["services/api/"]}]


def test_existing_b_prep_branch_is_carried_forward() -> None:
    state = {"done": ["T13"], "attempts": {}}
    with (
        patch.object(driver, "board", return_value={"T10": ("B", ["T13"])}),
        patch.object(driver, "card_paths", return_value=["infra/"]),
        patch.object(driver, "git", return_value="origin/agent/B/T10/prep") as git,
        patch.object(driver, "sh", return_value=SimpleNamespace(returncode=0)) as sh,
    ):
        tasks = driver.next_plan("20261010T020000Z", {}, state)
    assert tasks[0]["source_branch"] == "agent/B/T10/carry-20261010T020000Z"
    assert "refs/remotes/origin/agent/B/T10/*" in git.call_args.args
    assert sh.call_args.args[4].startswith("origin/agent/B/T10/prep:refs/heads/")

"""Machine-checkable safety and two-clone coordination checks for the night runner."""

import json
import subprocess
import sys
import unittest
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "agents"))
import night  # noqa: E402


def git_at(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=directory, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


class NightUnitTests(unittest.TestCase):
    def test_rate_limit_and_non_retryable_errors_are_distinct(self) -> None:
        self.assertEqual(
            night.classify_failure("usage limit resets in 1 hour", 1, False), "rate_limit"
        )
        self.assertEqual(night.classify_failure("HTTP 429", 1, False), "rate_limit")
        self.assertEqual(
            night.classify_failure("invalid API key", 1, False), "authentication_or_billing"
        )
        self.assertEqual(night.classify_failure("permission denied", 1, False), "permission")
        self.assertEqual(night.classify_failure("", 124, True), "timeout")
        self.assertEqual(
            night.classify_failure("mentions usage limit in a successful answer", 0, False),
            "ok",
        )

    def test_result_with_stderr_prefix_and_budget(self) -> None:
        data = night.parse_result('startup warning\n{"total_cost_usd":0.25,"result":"ok"}\n')
        self.assertEqual(night.price_from_result(data), 0.25)
        self.assertIsNone(night.price_from_result({"result": "ok"}))

    def test_reported_reset_overrides_probe_backoff(self) -> None:
        future = night.iso(night.utc_now() + timedelta(hours=4))
        eligible = night.limit_eligible("", {"resets_at": future}, 1)
        self.assertGreater(eligible, night.utc_now() + timedelta(hours=3))

    def test_safe_plan_rejects_duplicate_and_overlapping_ownership(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "agents/tasks").mkdir(parents=True)
            (root / "agents/operations").mkdir(parents=True)
            for task in ("T03", "T04"):
                (root / "agents/tasks" / f"{task}.md").write_text("# Task\n", encoding="utf-8")
            plan_file = root / "agents/operations/night-plan.json"
            with patch.object(night, "ROOT", root), patch.object(night, "PLAN_TEMPLATE", plan_file):
                plan_file.write_text(
                    json.dumps(
                        {
                            "tasks": [
                                {"id": "T03", "machine": "A", "paths": ["packages/sim/"]},
                                {"id": "T04", "machine": "B", "paths": ["packages/sim/deep/"]},
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(night.NightError, "Overlapping paths"):
                    night.read_plan_template()
                plan_file.write_text(
                    json.dumps(
                        {
                            "tasks": [
                                {"id": "T03", "machine": "A", "paths": ["packages/sim/"]},
                                {"id": "T03", "machine": "B", "paths": ["services/api/"]},
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(night.NightError, "unique"):
                    night.read_plan_template()

    def test_local_lock_blocks_second_supervisor(self) -> None:
        with TemporaryDirectory() as temporary, patch.object(night, "RUNTIME", Path(temporary)):
            with night.machine_lock("A"):
                with self.assertRaisesRegex(night.NightError, "already locked"):
                    with night.machine_lock("A"):
                        pass
            # The marker file may remain; the OS lock is released after exit.
            with night.machine_lock("A"):
                pass

    def test_path_audit_rejects_unreserved_edits(self) -> None:
        task = {"id": "T04", "paths": ["services/api/", "tests/api/"]}
        with patch.object(night, "changed_paths", return_value={"services/api/app.py", "uv.lock"}):
            with self.assertRaisesRegex(night.NightError, "uv.lock"):
                night.check_paths(Path("."), task)

    def test_fresh_reviewer_has_read_only_tools_and_bounded_calls(self) -> None:
        args = night.claude_args("review", 10, True, "api", 1.0)
        self.assertIn("dontAsk", args)
        self.assertIn("--json-schema", args)
        self.assertIn("--max-budget-usd", args)
        self.assertNotIn("Edit", args)

    def test_generated_checkout_normalizes_only_line_endings(self) -> None:
        with TemporaryDirectory() as temporary:
            repo = Path(temporary)
            git_at(repo, "init")
            git_at(repo, "config", "user.name", "Test A")
            git_at(repo, "config", "user.email", "a@example.invalid")
            file = repo / "packages/contracts/generated/types.ts"
            file.parent.mkdir(parents=True)
            file.write_bytes(b"export type A = string;\n")
            git_at(repo, "add", ".")
            git_at(repo, "commit", "-m", "generated")
            file.write_bytes(b"export type A = string;\r\n")
            night.normalize_generated_checkout(repo)
            self.assertEqual(file.read_bytes(), b"export type A = string;\n")
            self.assertEqual(git_at(repo, "status", "--porcelain"), "")
            file.write_bytes(b"export type B = string;\r\n")
            with self.assertRaisesRegex(night.NightError, "real content drift"):
                night.normalize_generated_checkout(repo)


class TwoComputerProtocolTests(unittest.TestCase):
    def test_new_night_branch_preserves_existing_b_work(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            remote = parent / "remote.git"
            remote.mkdir()
            git_at(remote, "init", "--bare", "--initial-branch=main")
            repo = parent / "repo"
            git_at(parent, "clone", str(remote), str(repo))
            git_at(repo, "config", "user.name", "Test B")
            git_at(repo, "config", "user.email", "b@example.invalid")
            (repo / "main.txt").write_text("main\n", encoding="utf-8")
            git_at(repo, "add", ".")
            git_at(repo, "commit", "-m", "base")
            git_at(repo, "push", "origin", "main")
            git_at(repo, "switch", "-c", "agent/B/T04/run-api")
            (repo / "services/api").mkdir(parents=True)
            (repo / "services/api/old.py").write_text("old_work = True\n", encoding="utf-8")
            git_at(repo, "add", ".")
            git_at(repo, "commit", "-m", "B work")
            git_at(repo, "push", "origin", "agent/B/T04/run-api")
            git_at(repo, "switch", "main")
            (repo / "new-main.txt").write_text("new shared work\n", encoding="utf-8")
            git_at(repo, "add", ".")
            git_at(repo, "commit", "-m", "new main")
            git_at(repo, "push", "origin", "main")
            plan = {"run_id": "test-night", "main_sha": git_at(repo, "rev-parse", "HEAD")}
            task = {
                "id": "T04",
                "machine": "B",
                "source_branch": "agent/B/T04/run-api",
                "paths": ["services/api/"],
            }
            with (
                patch.object(night, "ROOT", repo),
                patch.object(night, "RUNTIME", repo / ".agent-runtime"),
            ):
                worktree, branch = night.worktree_for(plan, task)
                self.assertEqual(branch, "agent/B/test-night/T04")
                self.assertTrue((worktree / "services/api/old.py").exists())
                self.assertTrue((worktree / "new-main.txt").exists())

    def test_a_publishes_and_b_joins_exact_same_immutable_plan(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            remote = parent / "remote.git"
            remote.mkdir()
            git_at(remote, "init", "--bare", "--initial-branch=main")
            a = parent / "A"
            b = parent / "B"
            git_at(parent, "clone", str(remote), str(a))
            git_at(a, "config", "user.name", "Test A")
            git_at(a, "config", "user.email", "a@example.invalid")
            (a / "packages/contracts").mkdir(parents=True)
            (a / "packages/contracts/pyproject.toml").write_text("[project]\n", encoding="utf-8")
            (a / "agents/tasks").mkdir(parents=True)
            (a / "agents/operations").mkdir(parents=True)
            for task in ("T03", "T04"):
                (a / "agents/tasks" / f"{task}.md").write_text("# Task\n", encoding="utf-8")
            template = {
                "tasks": [
                    {"id": "T03", "machine": "A", "paths": ["packages/sim/"]},
                    {"id": "T04", "machine": "B", "paths": ["services/api/"]},
                ]
            }
            (a / "agents/operations/night-plan.json").write_text(
                json.dumps(template), encoding="utf-8"
            )
            (a / ".gitignore").write_text(".agent-runtime/\n", encoding="utf-8")
            git_at(a, "add", ".")
            git_at(a, "commit", "-m", "fixture")
            git_at(a, "push", "origin", "main")
            git_at(parent, "clone", str(remote), str(b))
            with ExitStack() as stack:
                stack.enter_context(patch.object(night, "ROOT", a))
                stack.enter_context(patch.object(night, "RUNTIME", a / ".agent-runtime"))
                stack.enter_context(
                    patch.object(night, "PLAN_TEMPLATE", a / "agents/operations/night-plan.json")
                )
                plan = night.publish_plan(1)
                with self.assertRaisesRegex(night.NightError, "active run"):
                    night.publish_plan(1)
            with ExitStack() as stack:
                stack.enter_context(patch.object(night, "ROOT", b))
                stack.enter_context(patch.object(night, "RUNTIME", b / ".agent-runtime"))
                stack.enter_context(
                    patch.object(night, "PLAN_TEMPLATE", b / "agents/operations/night-plan.json")
                )
                joined = night.join_plan()
                self.assertEqual(plan, joined)
                self.assertEqual(
                    {task["id"] for task in joined["tasks"] if task["machine"] == "B"}, {"T04"}
                )
            self.assertGreater(night.parse_utc(plan["stop_at_utc"]), datetime.now(UTC))
            self.assertLess(
                night.parse_utc(plan["stop_at_utc"]), datetime.now(UTC) + timedelta(hours=2)
            )

    def test_fake_worker_check_reviewer_and_remote_checkpoint(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            remote = parent / "remote.git"
            remote.mkdir()
            git_at(remote, "init", "--bare", "--initial-branch=main")
            a = parent / "A"
            git_at(parent, "clone", str(remote), str(a))
            git_at(a, "config", "user.name", "Test A")
            git_at(a, "config", "user.email", "a@example.invalid")
            (a / "agents/tasks").mkdir(parents=True)
            (a / "agents/tasks/T03.md").write_text("# Simulator task\n", encoding="utf-8")
            (a / ".gitignore").write_text(".agent-runtime/\n", encoding="utf-8")
            git_at(a, "add", ".")
            git_at(a, "commit", "-m", "fixture")
            git_at(a, "push", "origin", "main")
            plan = {
                "run_id": "fake-run",
                "main_sha": git_at(a, "rev-parse", "HEAD"),
                "start_at_utc": night.iso(night.utc_now()),
                "stop_at_utc": night.iso(night.utc_now() + timedelta(minutes=10)),
                "tasks": [{"id": "T03", "machine": "A", "paths": ["packages/sim/"]}],
            }
            calls: list[str] = []

            def fake_process(
                args: list[str], cwd: Path, timeout: float, log: Path
            ) -> tuple[int, str, bool]:
                del timeout, log
                if args[0] == "claude" and "--json-schema" not in args:
                    calls.append("worker")
                    target = cwd / "packages/sim/world.py"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("def step():\n    return 1\n", encoding="utf-8")
                    return 0, '{"total_cost_usd":0.10,"result":"implemented"}', False
                if args[0] == "claude":
                    calls.append("reviewer")
                    return (
                        0,
                        ('{"total_cost_usd":0.05,"structured_output":{"pass":true,"issues":[]}}'),
                        False,
                    )
                calls.append("checks")
                return 0, "PASS project check", False

            with ExitStack() as stack:
                stack.enter_context(patch.object(night, "ROOT", a))
                stack.enter_context(patch.object(night, "RUNTIME", a / ".agent-runtime"))
                stack.enter_context(patch.object(night, "bootstrap_worktree"))
                stack.enter_context(patch.object(night, "run_process", side_effect=fake_process))
                stack.enter_context(patch.object(night, "bash_executable", return_value="bash"))
                night.run_machine(
                    plan,
                    "A",
                    billing="subscription",
                    budget_usd=None,
                    slice_minutes=1,
                    max_rounds=2,
                )
                state = json.loads(
                    (a / ".agent-runtime/fake-run-A.json").read_text(encoding="utf-8")
                )
                self.assertEqual(state["tasks"]["T03"]["status"], "review")
                self.assertEqual(calls, ["worker", "checks", "reviewer"])
                branch = "agent/A/fake-run/T03"
                git_at(a, "fetch", "origin", branch)
                self.assertEqual(
                    git_at(a, "show", "FETCH_HEAD:packages/sim/world.py"),
                    "def step():\n    return 1",
                )
                self.assertEqual(git_at(a, "rev-parse", "origin/main"), plan["main_sha"])


if __name__ == "__main__":
    unittest.main()

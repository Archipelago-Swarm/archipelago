"""Branch pruning must keep unmerged work and the current assignment recoverable."""

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "agents"))
import cleanup_branches  # noqa: E402


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def branch_with_file(root: Path, branch: str, path: str, content: str) -> None:
    git(root, "switch", "-c", branch)
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    git(root, "add", path)
    git(root, "commit", "-m", branch)
    git(root, "push", "origin", branch)
    git(root, "switch", "main")


def test_apply_archives_reports_and_only_prunes_redundant_refs() -> None:
    with TemporaryDirectory() as temporary:
        parent = Path(temporary)
        remote = parent / "remote.git"
        remote.mkdir()
        git(remote, "init", "--bare", "--initial-branch=main")
        repo = parent / "repo"
        git(parent, "clone", str(remote), str(repo))
        git(repo, "config", "user.name", "Cleanup Test")
        git(repo, "config", "user.email", "cleanup@example.invalid")
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        git(repo, "add", "README.md")
        git(repo, "commit", "-m", "base")
        git(repo, "push", "origin", "main")

        old_run = "20261010T010000Z"
        live_run = "20261010T020000Z"
        old_task = f"agent/B/{old_run}/T06"
        old_report = f"agent/B/{old_run}/report"
        live_report = f"agent/B/{live_run}/report"
        branch_with_file(repo, old_task, "apps/web/feature.txt", "merged work\n")
        git(repo, "merge", "--no-ff", "--no-edit", old_task)
        git(repo, "push", "origin", "main")
        branch_with_file(repo, old_report, f"agents/runs/{old_run}-B.md", "old report\n")
        branch_with_file(repo, live_report, f"agents/runs/{live_run}-B.md", "live report\n")
        branch_with_file(repo, "agent/B/T10/prep", "infra/prep.txt", "unmerged\n")
        branch_with_file(repo, f"agent/B/{live_run}/T06", "apps/web/current.txt", "active\n")

        git(repo, "switch", "-c", "agent-coordination")
        path = repo / "agents/coordination/active.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "run_id": live_run,
                    "tasks": [{"id": "T06", "machine": "B", "source_branch": "agent/B/T10/prep"}],
                }
            ),
            encoding="utf-8",
        )
        git(repo, "add", "agents/coordination/active.json")
        git(repo, "commit", "-m", "active plan")
        git(repo, "push", "origin", "agent-coordination")
        git(repo, "switch", "main")

        assert cleanup_branches.cleanup(repo) == (0, 1)  # merged task only
        archived, deleted = cleanup_branches.cleanup(repo, apply=True)
        assert (archived, deleted) == (2, 2)
        names = cleanup_branches.refs(repo)
        assert old_task not in names
        assert old_report not in names
        assert live_report in names
        assert f"agent/B/{live_run}/T06" in names
        assert "agent/B/T10/prep" in names
        assert (repo / f"agents/runs/{old_run}-B.md").read_text() == "old report\n"
        assert (repo / f"agents/runs/{live_run}-B.md").read_text() == "live report\n"

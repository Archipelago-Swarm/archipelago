"""Archive run reports, then remove only provably redundant generated branches.

Dry-run is the default. ``--apply`` requires a clean, up-to-date main checkout.
Named work branches, divergent checkpoints, and the active run are retained.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = re.compile(r"^agent/([AB])/(\d{8}T\d{6}Z)/report$")
TASK = re.compile(r"^agent/[AB]/\d{8}T\d{6}Z/T\d{2}$")
CARRY = re.compile(r"^agent/[AB]/T\d{2}/carry.*$")
BATCH_SIZE = 20


def git(*args: str, root: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    if check and result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {detail}")
    return result


def out(*args: str, root: Path = ROOT) -> str:
    return git(*args, root=root).stdout.decode().strip()


def refs(root: Path) -> dict[str, str]:
    result = out("ls-remote", "--heads", "origin", "agent/*", root=root)
    return {
        name.removeprefix("refs/heads/"): sha
        for sha, name in (line.split("\t", 1) for line in result.splitlines())
    }


def active_plan(root: Path) -> dict:
    raw = out("show", "origin/agent-coordination:agents/coordination/active.json", root=root)
    return json.loads(raw)


def protected_refs(plan: dict) -> set[str]:
    run = plan["run_id"]
    protected: set[str] = set()
    for machine in ("A", "B"):
        protected.add(f"agent/{machine}/{run}/report")
    for task in plan["tasks"]:
        protected.add(f"agent/{task['machine']}/{run}/{task['id']}")
        if task.get("source_branch"):
            protected.add(task["source_branch"])
    return protected


def report_path(name: str) -> str | None:
    match = REPORT.fullmatch(name)
    if match:
        return f"agents/runs/{match[2]}-{match[1]}.md"
    return None


def report_has_only_its_file(root: Path, sha: str, path: str) -> bool:
    base = out("merge-base", "origin/main", sha, root=root)
    return out("diff", "--name-only", base, sha, root=root).splitlines() == [path]


def blob_at(root: Path, revision: str, path: str) -> str | None:
    result = git("rev-parse", f"{revision}:{path}", root=root, check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def archive_reports(root: Path, branches: dict[str, str]) -> int:
    staged: list[str] = []
    for name, sha in sorted(branches.items()):
        path = report_path(name)
        if path is None or not report_has_only_its_file(root, sha, path):
            continue
        source_blob = blob_at(root, sha, path)
        existing_blob = blob_at(root, "origin/main", path)
        if source_blob is None or (existing_blob is not None and existing_blob != source_blob):
            continue  # never overwrite a different archived report
        if existing_blob == source_blob:
            continue
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(git("show", f"{sha}:{path}", root=root).stdout)
        staged.append(path)
    if not staged:
        return 0
    git("add", "--", *staged, root=root)
    git("commit", "-m", f"Archive {len(staged)} overnight run reports", root=root)
    git("push", "origin", "main", root=root)  # a failed push aborts deletion
    git("fetch", "-q", "origin", "main", root=root)
    return len(staged)


def candidates(root: Path, branches: dict[str, str], protected: set[str]) -> list[tuple[str, str]]:
    selected: list[tuple[str, str]] = []
    for name, sha in sorted(branches.items()):
        if name in protected:
            continue
        path = report_path(name)
        if path:
            source_blob = blob_at(root, sha, path)
            if (
                source_blob is not None
                and report_has_only_its_file(root, sha, path)
                and source_blob == blob_at(root, "origin/main", path)
            ):
                selected.append((name, sha))
        elif (TASK.fullmatch(name) or CARRY.fullmatch(name)) and git(
            "merge-base", "--is-ancestor", sha, "origin/main", root=root, check=False
        ).returncode == 0:
            selected.append((name, sha))
    return selected


def require_clean_main(root: Path) -> None:
    if out("branch", "--show-current", root=root) != "main":
        raise RuntimeError("--apply requires the main checkout")
    if out("status", "--porcelain", root=root):
        raise RuntimeError("--apply requires a clean checkout")
    if out("rev-parse", "HEAD", root=root) != out("rev-parse", "origin/main", root=root):
        raise RuntimeError("--apply requires main to match origin/main")


def cleanup(root: Path = ROOT, *, apply: bool = False) -> tuple[int, int]:
    git("fetch", "-q", "origin", root=root)
    if apply:
        require_clean_main(root)
    plan = active_plan(root)  # no trustworthy active plan -> no deletion
    branches = refs(root)
    archived = archive_reports(root, branches) if apply else 0
    branches = refs(root) if archived else branches
    deletable = candidates(root, branches, protected_refs(plan))
    if not apply:
        pending = 0
        for name, sha in branches.items():
            path = report_path(name)
            if path and blob_at(root, sha, path) != blob_at(root, "origin/main", path):
                pending += 1
        print(
            f"dry run: {len(branches)} agent branches; "
            f"{len(deletable)} safe to delete; {pending} reports need archiving"
        )
        return 0, len(deletable)
    # Re-read coordination just before mutation; an assignment change invalidates the plan.
    git("fetch", "-q", "origin", "agent-coordination", root=root)
    if active_plan(root) != plan:
        raise RuntimeError("active assignment changed; rerun cleanup")
    for start in range(0, len(deletable), BATCH_SIZE):
        batch = deletable[start : start + BATCH_SIZE]
        leases = [f"--force-with-lease=refs/heads/{name}:{sha}" for name, sha in batch]
        deletions = [f":refs/heads/{name}" for name, _ in batch]
        git("push", "--atomic", *leases, "origin", *deletions, root=root)
    if deletable:
        git("fetch", "-q", "--prune", "origin", root=root)
    print(
        f"archived {archived} reports; deleted {len(deletable)} redundant branches; "
        f"retained {len(branches) - len(deletable)} agent branches"
    )
    return archived, len(deletable)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="archive reports and delete proven-redundant generated refs",
    )
    args = parser.parse_args()
    cleanup(apply=args.apply)

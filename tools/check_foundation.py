"""Validate the planning pack without installing application dependencies."""

from pathlib import Path
import json
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
required = [
    "README.md",
    "CLAUDE.md",
    "AGENTS.md",
    "agents/START_HERE.md",
    "agents/CONTRACT.md",
    "agents/vision/roadmap.md",
    "agents/architecture/core.md",
    "agents/architecture/interfaces.md",
    "agents/architecture/evaluation.md",
    "agents/architecture/sources.md",
    "agents/operations/overnight.md",
    "agents/tasks/BOARD.md",
    "agents/templates/handoff.md",
    "agents/templates/run-report.md",
    "agents/PROTOCOL.md",
    "agents/LESSONS.md",
    "agents/TASKS.yaml",
    "agents/OWNERSHIP.yaml",
    "agents/controller.py",
    "agents/launch.py",
    "agents/schemas/task.schema.json",
    "agents/schemas/verification.schema.json",
    "agents/schemas/run.schema.json",
    "agents/reports/LAST_RUN_RETROSPECTIVE.md",
    "Makefile",
]
for name in required:
    if not (ROOT / name).is_file():
        errors.append(f"Missing required file: {name}")

markdown = list(ROOT.glob("*.md")) + list((ROOT / "agents").rglob("*.md"))
for path in markdown:
    body = path.read_text(encoding="utf-8")
    if not body.strip():
        errors.append(f"Empty document: {path.relative_to(ROOT)}")
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", body):
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        destination = target.split("#", 1)[0].split("?", 1)[0]
        if destination and not (path.parent / destination).exists():
            errors.append(f"Broken local link in {path.relative_to(ROOT)}: {target}")

graph: dict[str, list[str]] = {}
for path in sorted((ROOT / "agents/tasks").glob("T[0-9][0-9].md")):
    body = path.read_text(encoding="utf-8")
    match = re.search(r"^- Dependencies: (.+)$", body, re.MULTILINE)
    if not match:
        errors.append(f"No dependencies declared: {path.name}")
        continue
    graph[path.stem] = re.findall(r"T\d{2}", match.group(1))
    for marker in (
        "- Status:",
        "- Planned machine:",
        "## Outcome",
        "## Acceptance checks",
        "## Handoff and recovery",
    ):
        if marker not in body:
            errors.append(f"Missing {marker}: {path.name}")

if len(graph) < 12:
    errors.append("Expected the twelve initial task cards")

visited: set[str] = set()
active: set[str] = set()


def visit(task: str) -> None:
    if task in active:
        errors.append(f"Dependency cycle at {task}")
        return
    if task in visited:
        return
    if task not in graph:
        errors.append(f"Unknown dependency: {task}")
        return
    active.add(task)
    for dependency in graph[task]:
        visit(dependency)
    active.remove(task)
    visited.add(task)


for task in graph:
    visit(task)

config = json.loads(
    (ROOT / "agents/operations/run-config.example.json").read_text(encoding="utf-8")
)
for setting in (
    "allow_paid_fallback",
    "allow_auto_merge",
    "allow_cloud_provisioning",
    "allow_deploy_to_existing_host",
):
    if config.get(setting) is not False:
        errors.append(f"Example must default {setting} to false")

if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
print(
    f"Foundation valid: {len(markdown)} Markdown files, {len(graph)} tasks, local links and dependency graph checked."
)

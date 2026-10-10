"""Bounded, recoverable two-machine Claude Code runner for Archipelago.

The plan is immutable once A publishes it to agent-coordination. Each worker owns
one task branch/worktree at a time. A local test command and a fresh read-only
reviewer decide completion; the coding session does not. No branch is auto-merged.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / ".agent-runtime"
COORD_BRANCH = "agent-coordination"
ACTIVE_PATH = "agents/coordination/active.json"
PLAN_TEMPLATE = ROOT / "agents/operations/night-plan.json"
REVIEW_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "pass": {"type": "boolean"},
            "issues": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["pass", "issues"],
        "additionalProperties": False,
    }
)


class NightError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise NightError(f"Expected UTC timestamp: {value}")
    return result


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def command(
    args: list[str], cwd: Path | None = None, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd or ROOT, text=True, capture_output=True, check=False)
    if check and result.returncode:
        raise NightError(
            f"{' '.join(args[:3])} failed ({result.returncode}): {result.stderr[-800:]}"
        )
    return result


def git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    return command(["git", *args], cwd, check=check).stdout.strip()


def require_git_identity() -> tuple[str, str]:
    name = git("config", "user.name", check=False)
    email = git("config", "user.email", check=False)
    if not name or not email:
        raise NightError("Set Git user.name and user.email in this repository before running")
    return name, email


def read_plan_template() -> list[dict[str, Any]]:
    data = json.loads(PLAN_TEMPLATE.read_text(encoding="utf-8"))
    tasks = data["tasks"]
    ids = [task["id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise NightError("Task IDs must be unique across machines")
    claimed: dict[str, str] = {}
    for task in tasks:
        if task["machine"] not in {"A", "B"} or not re.fullmatch(r"T\d{2}", task["id"]):
            raise NightError(f"Invalid task assignment: {task}")
        source = task.get("source_branch")
        if source and (
            not isinstance(source, str)
            or not source.startswith(f"agent/{task['machine']}/{task['id']}/")
        ):
            raise NightError(f"Source branch must belong to assigned machine/task: {source}")
        if not (ROOT / "agents/tasks" / f"{task['id']}.md").is_file():
            raise NightError(f"Missing task card: {task['id']}")
        for path in task["paths"]:
            if path.startswith("/") or ".." in Path(path).parts or not path.endswith("/"):
                raise NightError(f"Unsafe path reservation: {path}")
            for prior, owner in claimed.items():
                if path.startswith(prior) or prior.startswith(path):
                    raise NightError(
                        f"Overlapping paths {prior} ({owner}) and {path} ({task['id']})"
                    )
            claimed[path] = task["id"]
    return tasks


def require_clean_main() -> str:
    git("fetch", "origin", "main")
    if git("status", "--porcelain"):
        raise NightError("Main checkout has changes; use a clean checkout to start the night run")
    current = git("rev-parse", "HEAD")
    remote = git("rev-parse", "origin/main")
    if current != remote or git("branch", "--show-current") != "main":
        raise NightError("Start from up-to-date main after T01 and T02 have merged")
    if not (ROOT / "packages/contracts/pyproject.toml").exists():
        raise NightError("T01 contracts are absent from main")
    return current


def existing_active() -> dict[str, Any] | None:
    fetched = command(["git", "fetch", "origin", COORD_BRANCH], check=False)
    if fetched.returncode:
        return None
    shown = command(["git", "show", f"FETCH_HEAD:{ACTIVE_PATH}"], check=False)
    if shown.returncode:
        return None
    return json.loads(shown.stdout)


def publish_plan(hours: float) -> dict[str, Any]:
    main_sha = require_clean_main()
    previous = existing_active()
    if previous and parse_utc(previous["stop_at_utc"]) > utc_now():
        raise NightError(f"An active run already exists: {previous['run_id']}")
    start = utc_now()
    plan = {
        "schema_version": 1,
        "run_id": start.strftime("%Y%m%dT%H%M%SZ"),
        "start_at_utc": iso(start),
        "stop_at_utc": iso(start + timedelta(hours=hours)),
        "main_sha": main_sha,
        "dispatcher_machine": "A",
        "tasks": read_plan_template(),
    }
    coord = RUNTIME / "coordination-checkout"
    RUNTIME.mkdir(exist_ok=True)
    if not coord.exists():
        git("clone", "-q", git("remote", "get-url", "origin"), str(coord), cwd=ROOT)
    elif git("status", "--porcelain", cwd=coord):
        raise NightError(f"Coordination checkout has unpublished changes: {coord}")
    name, email = require_git_identity()
    git("config", "user.name", name, cwd=coord)
    git("config", "user.email", email, cwd=coord)
    git("fetch", "origin", cwd=coord)
    if previous:
        if git("branch", "--show-current", cwd=coord) != COORD_BRANCH:
            git("switch", COORD_BRANCH, cwd=coord)
        git("pull", "--ff-only", "origin", COORD_BRANCH, cwd=coord)
    else:
        if git("branch", "--show-current", cwd=coord) != COORD_BRANCH:
            git("switch", "-c", COORD_BRANCH, cwd=coord)
    file = coord / ACTIVE_PATH
    atomic_json(file, plan)
    git("add", ACTIVE_PATH, cwd=coord)
    git("commit", "-m", f"Assign overnight run {plan['run_id']}", cwd=coord)
    git("push", "origin", COORD_BRANCH, cwd=coord)
    atomic_json(RUNTIME / "active-plan.json", plan)
    return plan


def join_plan() -> dict[str, Any]:
    require_clean_main()
    plan = existing_active()
    if not plan:
        raise NightError("A has not published an active run")
    if parse_utc(plan["stop_at_utc"]) <= utc_now():
        raise NightError("Published run has ended")
    if command(["git", "cat-file", "-e", f"{plan['main_sha']}^{{commit}}"], check=False).returncode:
        raise NightError("Published base commit is not available locally")
    if read_plan_template() != plan["tasks"]:
        raise NightError("Local task plan differs from A's published plan; update main first")
    atomic_json(RUNTIME / "active-plan.json", plan)
    return plan


@contextlib.contextmanager
def machine_lock(machine: str):
    RUNTIME.mkdir(exist_ok=True)
    lock = RUNTIME / f"{machine}.lock"
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise NightError(f"{machine} runner is already locked; inspect PID in {lock}") from error
    with os.fdopen(handle, "w", encoding="utf-8") as output:
        output.write(str(os.getpid()))
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def worktree_for(plan: dict[str, Any], task: dict[str, Any]) -> tuple[Path, str]:
    run_id = plan["run_id"]
    branch = f"agent/{task['machine']}/{run_id}/{task['id']}"
    path = RUNTIME / "worktrees" / run_id / task["id"]
    if path.exists():
        if git("branch", "--show-current", cwd=path) != branch:
            raise NightError(f"Existing worktree has wrong branch: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        source = task.get("source_branch")
        if source:
            git("fetch", "origin", source)
            source_sha = git("rev-parse", f"origin/{source}")
            git("worktree", "add", "-b", branch, str(path), source_sha)
            git("merge", "--no-edit", plan["main_sha"], cwd=path)
        else:
            git("worktree", "add", "-b", branch, str(path), plan["main_sha"])
    normalize_generated_checkout(path)
    return path, branch


def normalize_generated_checkout(path: Path) -> None:
    """Refresh a tracked generated file when a Windows worktree inherits old CRLF."""
    relative = "packages/contracts/generated/types.ts"
    file = path / relative
    if not file.exists():
        return
    tracked = subprocess.run(
        ["git", "show", f"HEAD:{relative}"],
        cwd=path,
        capture_output=True,
        check=False,
    )
    if tracked.returncode:
        raise NightError(f"Cannot verify tracked generated file in {path}")
    current = file.read_bytes()
    if current == tracked.stdout:
        return
    if current.replace(b"\r\n", b"\n") != tracked.stdout:
        raise NightError(f"Generated file has real content drift in {path}: {relative}")
    file.write_bytes(tracked.stdout)
    git("add", "--", relative, cwd=path)  # refresh index; identical blob remains unstaged
    if git("diff", "--cached", "--name-only", cwd=path):
        raise NightError(f"Generated file normalization unexpectedly staged changes in {path}")


def changed_paths(path: Path) -> set[str]:
    names: set[str] = set()
    for args in [
        ("diff", "--name-only"),
        ("diff", "--cached", "--name-only"),
        ("ls-files", "--others", "--exclude-standard"),
    ]:
        names.update(line for line in git(*args, cwd=path).splitlines() if line)
    return names


def check_paths(path: Path, task: dict[str, Any]) -> None:
    allowed = task["paths"] + [f"agents/handoffs/{task['id']}/"]
    illegal = [
        name
        for name in changed_paths(path)
        if not any(name.startswith(prefix) for prefix in allowed)
    ]
    if illegal:
        raise NightError(f"Unreserved paths changed in {task['id']}: {', '.join(illegal)}")


def run_process(args: list[str], cwd: Path, timeout: float, log: Path) -> tuple[int, str, bool]:
    log.parent.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    executable = shutil.which(args[0])
    if executable is None:
        raise NightError(f"Child executable unavailable: {args[0]}")
    with log.open("w", encoding="utf-8") as output:
        child = subprocess.Popen(
            [executable, *args[1:]],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=flags,
        )
        try:
            exit_code = child.wait(timeout=max(1, timeout))
            timed_out = False
        except subprocess.TimeoutExpired:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            exit_code = child.returncode or 124
            timed_out = True
    return exit_code, log.read_text(encoding="utf-8", errors="replace"), timed_out


def classify_failure(
    output: str, exit_code: int, timed_out: bool, reported_error: bool = False
) -> str:
    if exit_code == 0 and not timed_out and not reported_error:
        return "ok"
    lower = output.lower()
    if re.search(r"usage limit|rate.limit|429|session limit", lower):
        return "rate_limit"
    if re.search(r"authentication_failed|not logged in|invalid api key|billing_error", lower):
        return "authentication_or_billing"
    if re.search(r"permission denied|permission prompt|not allowed", lower):
        return "permission"
    if timed_out:
        return "timeout"
    return "model_error"


def parse_result(output: str) -> dict[str, Any]:
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        for line in reversed(output.splitlines()):
            if line.lstrip().startswith("{"):
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        return value
                except json.JSONDecodeError:
                    continue
    return {}


def bash_executable() -> str:
    if os.name == "nt":
        git_exe = shutil.which("git")
        candidates = [Path(git_exe).resolve().parents[1] / "bin" / "bash.exe"] if git_exe else []
        candidates += [Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe",
                       Path("C:/msys64/usr/bin/bash.exe")]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        raise NightError("Git Bash is required for scripts/check.sh")
    found = shutil.which("bash")
    if found:
        return found
    raise NightError("bash is required for scripts/check.sh")


def bootstrap_worktree(path: Path, task: dict[str, Any], plan: dict[str, Any]) -> None:
    marker = RUNTIME / "bootstrapped" / plan["run_id"] / f"{task['id']}.done"
    if marker.exists():
        return
    for name, args in [("uv", ["uv", "sync", "--frozen"]), ("npm", ["npm", "ci"])]:
        log = (
            RUNTIME / "logs" / plan["run_id"] / task["machine"] / f"{task['id']}-install-{name}.log"
        )
        exit_code, _, timed_out = run_process(args, path, 900, log)
        if exit_code or timed_out:
            raise NightError(f"{name} install failed; inspect {log}")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(iso(utc_now()) + "\n", encoding="utf-8")


def price_from_result(result: dict[str, Any]) -> float | None:
    value = result.get("total_cost_usd")
    return float(value) if isinstance(value, (float, int)) and value >= 0 else None


def update_handoff(
    path: Path,
    task: dict[str, Any],
    branch: str,
    plan: dict[str, Any],
    round_no: int,
    status: str,
    check_code: int | None,
    review: dict[str, Any] | None,
    issue: str,
) -> None:
    file = path / "agents/handoffs" / task["id"] / "LATEST.md"
    file.parent.mkdir(parents=True, exist_ok=True)
    prior = file.read_text(encoding="utf-8") if file.exists() else ""
    report = (
        f"\n## Supervisor checkpoint {iso(utc_now())}\n\n"
        f"- Run: {plan['run_id']}\n- Machine: {task['machine']}\n"
        f"- Task/branch: {task['id']} / {branch}\n- Base: {plan['main_sha']}\n"
        f"- Round: {round_no}\n- State: {status}\n"
        f"- External check exit: {check_code if check_code is not None else 'not run'}\n"
        f"- Independent review: {json.dumps(review, ensure_ascii=False) if review else 'not run'}\n"
        f"- Next issue: {issue or 'none'}\n"
        "- Resume: fetch this branch, inspect latest commit and continue the task card.\n"
    )
    file.write_text(prior + report, encoding="utf-8")


def checkpoint(path: Path, branch: str, task: dict[str, Any], round_no: int) -> str:
    check_paths(path, task)
    if not changed_paths(path):
        return git("rev-parse", "HEAD", cwd=path)
    git("add", "-A", cwd=path)
    git("commit", "-m", f"{task['id']}: overnight checkpoint {round_no}", cwd=path)
    git("push", "-u", "origin", branch, cwd=path)
    return git("rev-parse", "HEAD", cwd=path)


def worker_prompt(task: dict[str, Any], plan: dict[str, Any], last_issue: str) -> str:
    return (
        f"You are a bounded coding worker on machine {task['machine']} for {task['id']}. "
        "Read CLAUDE.md, the task card, and your latest handoff. Work only in the "
        f"reserved paths {task['paths']} and agents/handoffs/{task['id']}/. "
        "Implement the smallest useful slice toward all acceptance checks. "
        "Do not change shared contracts, lockfiles, CI, or other task paths. "
        "Do not start subagents, commit, push, merge, deploy, or spend on cloud services; "
        "the supervisor owns checkpoints and verification. State what you changed. "
        f"Run {plan['run_id']}; latest independent feedback: {last_issue or 'none'}."
    )


def reviewer_prompt(task: dict[str, Any], check_output: str) -> str:
    return (
        f"You are a fresh independent reviewer of task {task['id']}. Read its task card "
        "and inspect this worktree. You cannot edit files. Decide whether every acceptance "
        "check has implementation evidence, with no stubbed success or weakened tests. "
        "The external project check exited 0. Return pass=true only if the assigned task "
        "is actually ready for a human PR review. List concrete missing evidence in issues. "
        f"External check tail:\n{check_output[-8000:]}"
    )


def claude_args(
    prompt: str, max_turns: int, reviewer: bool, billing: str, per_call_usd: float | None
) -> list[str]:
    args = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--max-turns",
        str(max_turns),
        "--permission-mode",
        "dontAsk" if reviewer else "auto",
        "--permission-prompts",
        "none",
    ]
    if reviewer:
        args.extend(["--allowedTools", "Read", "--json-schema", REVIEW_SCHEMA])
    else:
        args.extend(
            [
                "--disallowedTools",
                "Bash(git add *)",
                "Bash(git commit *)",
                "Bash(git push *)",
                "Bash(git merge *)",
                "Bash(git reset *)",
                "Bash(git checkout *)",
                "Bash(git switch *)",
                "Bash(git worktree *)",
            ]
        )
    if billing == "api" and per_call_usd is not None:
        args.extend(["--max-budget-usd", str(per_call_usd)])
    return args


def limit_eligible(output: str, result: dict[str, Any], attempt: int) -> datetime:
    for key in ("resets_at", "reset_at", "resetAt"):
        value = result.get(key)
        if isinstance(value, str):
            with contextlib.suppress(ValueError, NightError):
                reset = parse_utc(value)
                if reset > utc_now():
                    return reset + timedelta(minutes=1)
    match = re.search(r'"(?:resets_at|reset_at)"\s*:\s*"([^"]+)"', output)
    if match:
        with contextlib.suppress(ValueError, NightError):
            reset = parse_utc(match.group(1))
            if reset > utc_now():
                return reset + timedelta(minutes=1)
    delay = [900, 1800, 3600][min(attempt - 1, 2)]
    return utc_now() + timedelta(seconds=delay)


def wait_until(until: datetime, stop: datetime, stop_file: Path) -> bool:
    until = min(until, stop)
    while utc_now() < until:
        if stop_file.exists():
            return False
        time.sleep(min(30, (until - utc_now()).total_seconds()))
    return utc_now() < stop and not stop_file.exists()


def run_machine(
    plan: dict[str, Any],
    machine: str,
    *,
    billing: str,
    budget_usd: float | None,
    slice_minutes: int,
    max_rounds: int,
) -> None:
    stop = parse_utc(plan["stop_at_utc"])
    stop_file = RUNTIME / "STOP"
    state_path = RUNTIME / f"{plan['run_id']}-{machine}.json"
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {
            "run_id": plan["run_id"],
            "machine": machine,
            "spent_usd": 0.0,
            "tasks": {},
        }
    )
    if state["run_id"] != plan["run_id"] or state["machine"] != machine:
        raise NightError("Local supervisor state does not match published plan")
    tasks = [task for task in plan["tasks"] if task["machine"] == machine]
    for task in tasks:
        if utc_now() >= stop or stop_file.exists():
            break
        task_state = state["tasks"].setdefault(
            task["id"], {"rounds": 0, "status": "ready", "issue": ""}
        )
        if task_state["status"] in {"review", "blocked", "UNSYNCED", "blocked_cost_unknown"}:
            continue
        if task_state["status"] == "paused_limit":
            if int(task_state.get("limit_retries", 0)) >= 10:
                task_state["status"] = "blocked"
                task_state["issue"] = "Ten usage-limit probes reached"
                atomic_json(state_path, state)
                continue
            eligible = parse_utc(task_state["next_eligible_at_utc"])
            if not wait_until(eligible, stop, stop_file):
                break
            task_state["status"] = "in_progress"
            atomic_json(state_path, state)
        if task["id"] == "T08" and not shutil.which("docker"):
            task_state["status"] = "blocked"
            task_state["issue"] = "Docker is required for T08's TimescaleDB/Grafana checks"
            atomic_json(state_path, state)
            continue
        path, branch = worktree_for(plan, task)
        try:
            bootstrap_worktree(path, task, plan)
        except NightError as error:
            task_state["status"] = "blocked"
            task_state["issue"] = str(error)
            atomic_json(state_path, state)
            continue
        limit_retries = int(task_state.get("limit_retries", 0))
        previous_issue = task_state.get("issue", "")
        stalled = task_state.get("stalled", 0)
        while task_state["rounds"] < max_rounds and utc_now() < stop and not stop_file.exists():
            if billing == "api" and (budget_usd is None or state["spent_usd"] >= budget_usd):
                task_state["status"] = "paused_budget"
                break
            round_no = task_state["rounds"] + 1
            timeout = min(slice_minutes * 60, max(1, (stop - utc_now()).total_seconds()))
            per_call = (
                min(3.0, budget_usd - state["spent_usd"])
                if billing == "api" and budget_usd
                else None
            )
            log = (
                RUNTIME / "logs" / plan["run_id"] / machine / f"{task['id']}-worker-{round_no}.log"
            )
            task_state.update(
                {"status": "running", "rounds": round_no, "started_at_utc": iso(utc_now())}
            )
            atomic_json(state_path, state)
            head_before = git("rev-parse", "HEAD", cwd=path)
            exit_code, output, timed_out = run_process(
                claude_args(
                    worker_prompt(task, plan, task_state["issue"]), 30, False, billing, per_call
                ),
                path,
                timeout,
                log,
            )
            result = parse_result(output)
            if git("rev-parse", "HEAD", cwd=path) != head_before:
                task_state["status"] = "blocked"
                task_state["issue"] = (
                    "Worker changed Git history; inspect its worktree before recovery"
                )
                atomic_json(state_path, state)
                break
            cost = price_from_result(result)
            if billing == "api" and cost is None:
                task_state["status"] = "blocked_cost_unknown"
                task_state["issue"] = "API cost unavailable; do not launch another model call"
            elif cost is not None:
                state["spent_usd"] += cost
            failure = classify_failure(output, exit_code, timed_out, bool(result.get("is_error")))
            if result.get("permission_denials"):
                failure = "permission"
            try:
                check_paths(path, task)
            except NightError as error:
                task_state["status"] = "blocked"
                task_state["issue"] = str(error) + "; local worktree preserved"
                atomic_json(state_path, state)
                break
            implementation_changes = {
                name
                for name in changed_paths(path)
                if not name.startswith(f"agents/handoffs/{task['id']}/")
            }
            check_code: int | None = None
            check_output = ""
            review: dict[str, Any] | None = None
            if failure == "ok" and task_state["status"] != "blocked_cost_unknown":
                test_log = (
                    RUNTIME
                    / "logs"
                    / plan["run_id"]
                    / machine
                    / f"{task['id']}-check-{round_no}.log"
                )
                check_code, check_output, _ = run_process(
                    [bash_executable(), "scripts/check.sh"],
                    path,
                    min(900, max(1, (stop - utc_now()).total_seconds())),
                    test_log,
                )
                budget_for_review = billing != "api" or (
                    budget_usd is not None and state["spent_usd"] < budget_usd
                )
                if (
                    check_code == 0
                    and utc_now() < stop
                    and not stop_file.exists()
                    and implementation_changes
                    and budget_for_review
                ):
                    review_log = (
                        RUNTIME
                        / "logs"
                        / plan["run_id"]
                        / machine
                        / f"{task['id']}-review-{round_no}.log"
                    )
                    reviewer_budget = (
                        min(1.0, budget_usd - state["spent_usd"])
                        if billing == "api" and budget_usd
                        else None
                    )
                    review_code, review_output, review_timeout = run_process(
                        claude_args(
                            reviewer_prompt(task, check_output), 10, True, billing, reviewer_budget
                        ),
                        path,
                        min(600, max(1, (stop - utc_now()).total_seconds())),
                        review_log,
                    )
                    parsed = parse_result(review_output)
                    reviewer_cost = price_from_result(parsed)
                    if billing == "api" and reviewer_cost is None:
                        task_state["status"] = "blocked_cost_unknown"
                    elif reviewer_cost is not None:
                        state["spent_usd"] += reviewer_cost
                    structured = parsed.get("structured_output")
                    if review_code == 0 and not review_timeout and isinstance(structured, dict):
                        review = structured
            if task_state["status"] == "blocked_cost_unknown":
                issue = task_state["issue"] or "API reviewer cost unavailable"
            elif failure == "rate_limit":
                issue = "Claude usage/rate limit; wait outside the model"
                task_state["status"] = "paused_limit"
            elif failure != "ok":
                issue = f"Worker {failure}, exit {exit_code}; inspect local log"
                task_state["status"] = (
                    "blocked"
                    if failure in {"authentication_or_billing", "permission"}
                    else "in_progress"
                )
            elif check_code != 0:
                issue = f"External checks failed (exit {check_code}); inspect local check log"
                task_state["status"] = "in_progress"
            elif review and review.get("pass") is True:
                issue = ""
                task_state["status"] = "review"
            else:
                issue = (
                    "; ".join(review.get("issues", []))
                    if review
                    else "Independent review unavailable or inconclusive"
                )
                task_state["status"] = "in_progress"
            task_state["issue"] = issue
            if failure == "ok" and task_state["status"] == "in_progress":
                stalled = (
                    stalled + 1 if issue == previous_issue or not implementation_changes else 0
                )
                task_state["stalled"] = stalled
                if stalled >= 2:
                    task_state["status"] = "blocked"
                    task_state["issue"] = "Two rounds without measurable progress: " + issue
            previous_issue = task_state["issue"]
            update_handoff(
                path, task, branch, plan, round_no, task_state["status"], check_code, review, issue
            )
            try:
                task_state["checkpoint_sha"] = checkpoint(path, branch, task, round_no)
            except NightError as error:
                task_state["status"] = "UNSYNCED"
                task_state["issue"] = str(error)
            atomic_json(state_path, state)
            checkpoint_label = task_state.get("checkpoint_sha", "")[:8] or "local"
            print(
                f"{machine} {task['id']} round {round_no}: {task_state['status']} "
                f"({checkpoint_label})",
                flush=True,
            )
            if task_state["status"] == "paused_limit":
                limit_retries += 1
                task_state["limit_retries"] = limit_retries
                task_state["rounds"] -= 1  # rate-limit probes do not consume coding rounds
                task_state["next_eligible_at_utc"] = iso(
                    limit_eligible(output, result, limit_retries)
                )
                atomic_json(state_path, state)
                if limit_retries >= 10:
                    task_state["status"] = "blocked"
                    task_state["issue"] = "Ten usage-limit probes reached"
                    atomic_json(state_path, state)
                    break
                if not wait_until(parse_utc(task_state["next_eligible_at_utc"]), stop, stop_file):
                    break
                task_state["status"] = "in_progress"
                atomic_json(state_path, state)
                continue
            if task_state["status"] in {"review", "blocked", "blocked_cost_unknown", "UNSYNCED"}:
                break
        if task_state["rounds"] >= max_rounds and task_state["status"] == "in_progress":
            task_state["status"] = "blocked"
            task_state["issue"] = "Maximum coding rounds reached"
            atomic_json(state_path, state)
    write_report(plan, machine, state)


def write_report(plan: dict[str, Any], machine: str, state: dict[str, Any]) -> None:
    lines = [
        f"# Overnight run {plan['run_id']} — machine {machine}",
        "",
        f"- Base: {plan['main_sha']}",
        f"- Window: {plan['start_at_utc']} to {plan['stop_at_utc']}",
        f"- API-equivalent cost reported: ${state['spent_usd']:.2f} (not a subscription charge)",
        "",
        "## Task results",
        "",
    ]
    for task in (item for item in plan["tasks"] if item["machine"] == machine):
        item = state["tasks"].get(task["id"], {})
        lines.append(
            f"- {task['id']}: {item.get('status', 'not started')}; "
            f"rounds {item.get('rounds', 0)}; SHA {item.get('checkpoint_sha', 'none')}; "
            f"issue {item.get('issue', 'none')}"
        )
    lines += [
        "",
        "## Next action",
        "",
        "Review pushed task branches and their LATEST.md handoffs. "
        "Only the integrator may merge after CI and dependency checks.",
        "",
    ]
    report = "\n".join(lines)
    local = RUNTIME / "reports" / f"{plan['run_id']}-{machine}.md"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(report, encoding="utf-8")
    path = RUNTIME / "reports-worktrees" / plan["run_id"] / machine
    branch = f"agent/{machine}/{plan['run_id']}/report"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "-b", branch, str(path), plan["main_sha"])
    destination = path / "agents/runs" / f"{plan['run_id']}-{machine}.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report, encoding="utf-8")
    git("add", str(destination.relative_to(path)).replace("\\", "/"), cwd=path)
    if git("status", "--porcelain", cwd=path):
        git("commit", "-m", f"Report overnight run {plan['run_id']} ({machine})", cwd=path)
    git("push", "-u", "origin", branch, cwd=path)


def preflight(machine: str, billing: str, budget_usd: float | None) -> None:
    if billing == "api" and (budget_usd is None or budget_usd <= 0):
        raise NightError("API mode requires a positive --budget-usd")
    if billing == "subscription" and budget_usd is not None:
        raise NightError("--budget-usd is an API spend cap; omit it for subscription mode")
    if (RUNTIME / "STOP").exists():
        raise NightError("Stop file exists: .agent-runtime/STOP")
    for executable in ("git", "claude", "uv", "npm"):
        if not shutil.which(executable):
            raise NightError(f"Missing required executable: {executable}")
    bash_executable()
    require_clean_main()
    require_git_identity()
    if machine not in {"A", "B"}:
        raise NightError("Machine must be A or B")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--machine", required=True, choices=["A", "B"])
    parser.add_argument("--billing", required=True, choices=["subscription", "api"])
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--slice-minutes", type=int, default=25)
    parser.add_argument("--max-rounds", type=int, default=4)
    args = parser.parse_args()
    if (
        not 0 < args.hours <= 12
        or not 1 <= args.slice_minutes <= 45
        or not 1 <= args.max_rounds <= 10
    ):
        parser.error("Hours, slice minutes and max rounds must stay within bounded limits")
    try:
        with machine_lock(args.machine):
            preflight(args.machine, args.billing, args.budget_usd)
            if args.machine == "A":
                active = existing_active()
                saved = RUNTIME / "active-plan.json"
                if active and parse_utc(active["stop_at_utc"]) > utc_now():
                    if (
                        not saved.exists()
                        or json.loads(saved.read_text(encoding="utf-8"))["run_id"]
                        != active["run_id"]
                    ):
                        raise NightError("Another A dispatcher owns the active run")
                    plan = join_plan()
                else:
                    plan = publish_plan(args.hours)
            else:
                plan = join_plan()
            print(
                f"Run {plan['run_id']} until {plan['stop_at_utc']} UTC on machine {args.machine}",
                flush=True,
            )
            run_machine(
                plan,
                args.machine,
                billing=args.billing,
                budget_usd=args.budget_usd,
                slice_minutes=args.slice_minutes,
                max_rounds=args.max_rounds,
            )
    except NightError as error:
        print(f"Night runner stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

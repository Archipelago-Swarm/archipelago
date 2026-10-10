"""Deterministic task-ledger controller for Archipelago agents.

Reads and edits agents/TASKS.yaml. It is a CLI that runs once and exits: it launches no
agents, starts no background process and keeps no state outside Git. Every transition is
validated against the lifecycle below and recorded in the task's history.

    python agents/controller.py --remote status   # shared ledger on origin/main, writes publish
    python agents/controller.py validate [--files]
    python agents/controller.py status
    python agents/controller.py next [--machine A|B] [--limit N]
    python agents/controller.py deps T10
    python agents/controller.py claim T10 --owner B/w1 --machine B
    python agents/controller.py start|review T10 --by B/w1 [--commit SHA]   # --by must be the owner
    python agents/controller.py requeue T10 --by B/w1     # owner or the integrator machine
    python agents/controller.py record-failure T10 --by B/w1 --kind test_failure --signature "..."
    python agents/controller.py block T10 --by B/w1 --report agents/handoffs/T10/BLOCKER.md --reason "..."
    python agents/controller.py unblock T10 --by A [--resolved "what the human did"]
    python agents/controller.py verify T10        # reads handoffs/T10/VERIFICATION.yaml
    python agents/controller.py integrate-fail T10 --signature "..."
    python agents/controller.py complete T10 --commit <sha> --machine A
    python agents/controller.py log-event --kind human_intervention --note "..."
    python agents/controller.py review-process    # metrics for the reliability reviewer
    python agents/controller.py report --run-id ID
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import yaml

AGENTS = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("ARCHIPELAGO_ROOT") or AGENTS.parent)  # repo checkout to operate on
LEDGER = ROOT / "agents" / "TASKS.yaml"
OWNERSHIP = ROOT / "agents" / "OWNERSHIP.yaml"
SCHEMAS = AGENTS / "schemas"
REMOTE: str | None = None  # --remote: read and publish the ledger on origin/<branch>
LEDGER_BRANCH = "main"  # integration branch: complete checks --commit against origin/<this>
CURRENT_CMD = "update"
PUBLISH_ATTEMPTS = 4
SAME_SIGNATURE_LIMIT = 3  # CONTRACT.md: three attempts at the same root cause -> blocked
UNBLOCK_CAP = 3  # unblock cycles allowed before the task is forced to FAILED
ASSERTION_RESULTS = {"met", "unmet", "not_checked"}

LEDGER_HEADER = (
    "# Canonical task ledger. Edit through agents/controller.py; see agents/PROTOCOL.md.\n"
    "# A task is COMPLETE only after verifier PASS and an integrator merge commit.\n"
)

STATES = ["QUEUED", "CLAIMED", "ACTIVE", "BLOCKED", "REVIEW", "INTEGRATION", "COMPLETE", "FAILED"]
TRANSITIONS: dict[str, set[str]] = {
    "QUEUED": {"CLAIMED", "BLOCKED"},
    "CLAIMED": {"ACTIVE", "QUEUED", "BLOCKED"},
    "ACTIVE": {"REVIEW", "BLOCKED", "FAILED", "QUEUED"},
    "REVIEW": {"INTEGRATION", "ACTIVE", "BLOCKED"},
    "INTEGRATION": {"COMPLETE", "ACTIVE", "BLOCKED"},
    "BLOCKED": {"QUEUED", "FAILED"},
    "COMPLETE": set(),
    "FAILED": set(),
}
IN_FLIGHT = {"CLAIMED", "ACTIVE", "REVIEW", "INTEGRATION"}
FAILURE_KINDS = ["test_failure", "build_failure", "integration_failure"]
BLOCKER_HEADINGS = [
    "Failing command",
    "Error",
    "Hypotheses attempted",
    "Files changed",
    "Last known-good commit",
    "Reproduction",
    "Recommended next action",
]
EVENT_KINDS = [
    "human_intervention",
    "agent_restart",
    "unsupported_automation",
    "regression_found",
    "regression_repaired",
]


class ControllerError(Exception):
    """A rule violation or invalid input. The CLI prints it and exits 1."""


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_schema(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    return data


def git_out(
    *args: str, cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, text=True)
    if check and result.returncode:
        raise ControllerError(
            f"git {' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def full_sha(ref: str, what: str) -> str:
    """Resolve a commit-ish to its full sha, or refuse (unresolvable refs are never accepted)."""
    if not ref or ref.startswith("-"):
        raise ControllerError(f"{what} {ref!r} is not a commit")
    out = git_out("rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False)
    sha = out.stdout.strip()
    if out.returncode or not sha:
        raise ControllerError(f"{what} {ref!r} cannot be resolved to a commit (fetch it first?)")
    return sha


def is_ancestor(older: str, newer: str) -> bool:
    return git_out("merge-base", "--is-ancestor", older, newer, check=False).returncode == 0


def integration_tip() -> str:
    """origin/<ledger-branch> when it exists, else HEAD of the checkout the controller runs in."""
    remote = git_out("rev-parse", "--verify", "-q", f"origin/{LEDGER_BRANCH}", check=False)
    return remote.stdout.strip() if remote.returncode == 0 and remote.stdout.strip() else "HEAD"


_LINE_REFS = re.compile(r"(?<=\S):\d+(?:[-:,]\d+)*|#L\d+(?:-L?\d+)?|\blines? \d+(?:-\d+)?", re.I)


def normalize_signature(signature: str) -> str:
    """Drop line numbers (file.py:12-30, #L4, 'line 9') so one root cause counts once."""
    return re.sub(r"\s+", " ", _LINE_REFS.sub("", signature)).strip()


def require_actor(task: dict[str, Any], by: str | None, action: str, *, integrator: bool) -> str:
    """--by must be the task owner (or, where allowed, a machine holding the integrator role)."""
    if not by:
        raise ControllerError(f"{action} requires --by (the task owner)")
    if task.get("owner") and by == task["owner"]:
        return by
    if integrator and load_ownership().get("roles", {}).get("integrator") == by.split("/")[0]:
        return by
    allowed = "the owner or the integrator machine" if integrator else "the owner"
    raise ControllerError(
        f"{task['id']}: {action} by {by!r} refused; only {allowed} ({task.get('owner')}) may"
    )


def load_ledger(path: Path | None = None) -> dict[str, Any]:
    if path is None and REMOTE:
        text = git_out("show", f"origin/{REMOTE}:agents/TASKS.yaml").stdout
    else:
        text = (path or LEDGER).read_text(encoding="utf-8")
    path = path or LEDGER
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise ControllerError(f"{path}: expected a mapping with a 'tasks' list")
    for task in data["tasks"]:
        if isinstance(task, dict) and isinstance(task.get("retry_policy"), dict):
            task["retry_policy"].setdefault("same_failure_signature", SAME_SIGNATURE_LIMIT)
    return data


def save_ledger(data: dict[str, Any], path: Path | None = None) -> None:
    path = path or LEDGER
    body = yaml.safe_dump(data, sort_keys=False, width=100, allow_unicode=True)
    path.write_text(LEDGER_HEADER + body, encoding="utf-8")


def task_map(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {t["id"]: t for t in data["tasks"]}


def get_task(data: dict[str, Any], task_id: str) -> dict[str, Any]:
    tasks = task_map(data)
    if task_id not in tasks:
        raise ControllerError(f"unknown task {task_id}")
    return tasks[task_id]


def stem(pattern: str) -> str:
    """The literal directory/file prefix of a glob, for overlap checks."""
    return re.split(r"[*?\[]", pattern, maxsplit=1)[0].rstrip("/")


def paths_overlap(a: list[str], b: list[str]) -> bool:
    for pa in a:
        for pb in b:
            sa, sb = stem(pa), stem(pb)
            if sa == sb or sa.startswith(sb + "/") or sb.startswith(sa + "/") or not sa or not sb:
                return True
    return False


def load_ownership() -> dict[str, Any]:
    data = yaml.safe_load(OWNERSHIP.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ControllerError("OWNERSHIP.yaml must be a mapping")
    return data


# ---------------------------------------------------------------- validation


def validate_ledger(data: dict[str, Any], *, check_files: bool = True) -> list[str]:
    errors: list[str] = []
    validator = jsonschema.Draft202012Validator(load_schema("task.schema.json"))
    tasks = data["tasks"]
    ids = [t.get("id") for t in tasks]
    for dup in {i for i in ids if ids.count(i) > 1}:
        errors.append(f"duplicate task id {dup}")
    known = set(ids)
    for task in tasks:
        tid = task.get("id", "?")
        for err in validator.iter_errors(task):
            where = "/".join(str(p) for p in err.absolute_path) or "<task>"
            errors.append(f"{tid}: {where}: {err.message}")
        for dep in task.get("dependencies", []):
            if dep not in known:
                errors.append(f"{tid}: dependency {dep} is not in the ledger")
        state = task.get("state")
        if state in IN_FLIGHT | {"BLOCKED"} and not task.get("handoff_file"):
            errors.append(f"{tid}: state {state} requires handoff_file")
        if state in IN_FLIGHT and not (
            task.get("owner") and task.get("machine") and task.get("branch")
        ):
            errors.append(f"{tid}: state {state} requires owner, machine and branch")
        if state == "BLOCKED" and not task.get("blocked_by"):
            errors.append(f"{tid}: BLOCKED requires at least one blocked_by entry")
        if state == "COMPLETE" and not task.get("last_good_commit"):
            errors.append(f"{tid}: COMPLETE requires last_good_commit (the integration commit)")
        if state in {"QUEUED", "CLAIMED", "ACTIVE", "REVIEW", "INTEGRATION"}:
            blockers = [d for d in task.get("dependencies", []) if d in known]
            if state != "QUEUED" and any(
                task_map(data)[d]["state"] != "COMPLETE" for d in blockers
            ):
                errors.append(f"{tid}: in flight while a dependency is not COMPLETE")
        if check_files and state == "BLOCKED" and task.get("handoff_file"):
            errors.extend(blocker_report_errors(task))
        if check_files and state in IN_FLIGHT | {"BLOCKED"} and task.get("handoff_file"):
            if not (ROOT / task["handoff_file"]).is_file():
                errors.append(f"{tid}: handoff_file {task['handoff_file']} does not exist")
    errors.extend(cycle_errors(data))
    errors.extend(ownership_errors(data))
    return errors


def cycle_errors(data: dict[str, Any]) -> list[str]:
    graph = {t["id"]: list(t.get("dependencies", [])) for t in data["tasks"]}
    errors: list[str] = []
    state: dict[str, int] = {}

    def visit(node: str, trail: list[str]) -> None:
        if state.get(node) == 2:
            return
        if state.get(node) == 1:
            errors.append("dependency cycle: " + " -> ".join([*trail, node]))
            return
        state[node] = 1
        for dep in graph.get(node, []):
            if dep in graph:
                visit(dep, [*trail, node])
        state[node] = 2

    for node in graph:
        visit(node, [])
    return errors


def ownership_errors(data: dict[str, Any]) -> list[str]:
    """In-flight tasks must not own overlapping paths."""
    flight = [t for t in data["tasks"] if t["state"] in IN_FLIGHT]
    errors = []
    for i, a in enumerate(flight):
        for b in flight[i + 1 :]:
            if paths_overlap(a["owned_paths"], b["owned_paths"]):
                errors.append(f"{a['id']} and {b['id']} are in flight with overlapping owned_paths")
    return errors


def blocker_report_errors(task: dict[str, Any]) -> list[str]:
    report = ROOT / task["handoff_file"]
    blocker = report.parent / "BLOCKER.md"
    if not blocker.is_file():
        return [f"{task['id']}: BLOCKED without {blocker.relative_to(ROOT)}"]
    text = blocker.read_text(encoding="utf-8")
    missing = [
        h for h in BLOCKER_HEADINGS if not re.search(rf"^##\s+{re.escape(h)}\s*$", text, re.M)
    ]
    return [f"{task['id']}: BLOCKER.md missing section '{h}'" for h in missing]


# ---------------------------------------------------------------- queries


def unmet_dependencies(data: dict[str, Any], task: dict[str, Any]) -> list[str]:
    tasks = task_map(data)
    return [d for d in task["dependencies"] if tasks[d]["state"] != "COMPLETE"]


def runnable(data: dict[str, Any], machine: str | None = None) -> list[dict[str, Any]]:
    flight_paths = [p for t in data["tasks"] if t["state"] in IN_FLIGHT for p in t["owned_paths"]]
    out = []
    for task in data["tasks"]:
        if task["state"] != "QUEUED" or task["blocked_by"] or unmet_dependencies(data, task):
            continue
        if machine and task["machine"] not in (None, machine):
            continue
        if paths_overlap(task["owned_paths"], flight_paths):
            continue
        out.append(task)
    return sorted(out, key=lambda t: (t["priority"], t["id"]))


def why_not_runnable(data: dict[str, Any], task: dict[str, Any]) -> str:
    if task["state"] != "QUEUED":
        return str(task["state"])
    reasons = []
    if task["blocked_by"]:
        reasons.append("blocked_by: " + "; ".join(task["blocked_by"]))
    unmet = unmet_dependencies(data, task)
    if unmet:
        reasons.append("waiting on " + ", ".join(unmet))
    flight_paths = [p for t in data["tasks"] if t["state"] in IN_FLIGHT for p in t["owned_paths"]]
    if paths_overlap(task["owned_paths"], flight_paths):
        reasons.append("owned_paths overlap an in-flight task")
    return "; ".join(reasons) or "runnable"


# ---------------------------------------------------------------- transitions


def transition(
    task: dict[str, Any], to: str, *, by: str, note: str = "", event: str = "transition"
) -> None:
    current = task["state"]
    if to not in TRANSITIONS[current]:
        raise ControllerError(f"{task['id']}: illegal transition {current} -> {to}")
    task["state"] = to
    task["updated_at"] = now()
    task.setdefault("history", []).append(
        {
            "at": task["updated_at"],
            "event": event,
            "from": current,
            "to": to,
            "by": by,
            "note": note,
        }
    )


def add_event(task: dict[str, Any], event: str, by: str, note: str) -> None:
    task["updated_at"] = now()
    task.setdefault("history", []).append(
        {"at": task["updated_at"], "event": event, "by": by, "note": note}
    )


def add_process_event(
    data: dict[str, Any], event: str, by: str, note: str, task: str | None = None
) -> None:
    """Run-level events (human intervention, restarts, ...) live in the ledger's top-level list."""
    entry = {"at": now(), "event": event, "by": by, "note": note}
    if task:
        entry["task"] = task
    data.setdefault("events", []).append(entry)


def bump_failure(task: dict[str, Any], kind: str, signature: str) -> str | None:
    """Count a failure. Returns a reason string when a retry budget is exhausted."""
    signature = normalize_signature(signature)
    attempts = task.setdefault("attempts", {})
    attempts[kind] = attempts.get(kind, 0) + 1
    sigs = attempts.setdefault("signatures", {})
    sigs[signature] = sigs.get(signature, 0) + 1
    policy = task["retry_policy"]
    # CONTRACT.md fixes the floor at three attempts per root cause; a ledger may only raise it.
    if sigs[signature] >= max(policy["same_failure_signature"], SAME_SIGNATURE_LIMIT):
        return f"same failure signature seen {sigs[signature]}x: {signature}"
    if attempts[kind] >= policy[kind]:
        return f"{kind} budget exhausted ({attempts[kind]}/{policy[kind]})"
    return None


def auto_block(task: dict[str, Any], reason: str, by: str) -> None:
    task["blocked_by"] = [*task["blocked_by"], f"retry:{reason}"]
    transition(task, "BLOCKED", by=by, note=reason, event="auto_block")


def machine_may(role: str, machine: str) -> None:
    holder = load_ownership().get("roles", {}).get(role)
    if holder and holder != machine:
        raise ControllerError(f"role '{role}' belongs to machine {holder}, not {machine}")


# ---------------------------------------------------------------- reports


def process_metrics(data: dict[str, Any]) -> dict[str, Any]:
    tasks = data["tasks"]
    counts = {s: sum(1 for t in tasks if t["state"] == s) for s in STATES}
    events: dict[str, int] = {}
    for entry in data.get("events", []):
        events[entry["event"]] = events.get(entry["event"], 0) + 1
    verification = {"passes": 0, "failures": 0}
    retries = 0
    for task in tasks:
        attempts = task.get("attempts", {})
        retries += sum(attempts.get(k, 0) for k in FAILURE_KINDS)
        for h in task.get("history", []):
            events[h["event"]] = events.get(h["event"], 0) + 1
            if h["event"] == "verify_pass":
                verification["passes"] += 1
            if h["event"] == "verify_fail":
                verification["failures"] += 1
    repeated = [
        (t["id"], sig, n)
        for t in tasks
        for sig, n in t.get("attempts", {}).get("signatures", {}).items()
        if n >= 2
    ]
    return {
        "counts": counts,
        "events": events,
        "verification": verification,
        "retries": retries,
        "repeated_signatures": repeated,
    }


def build_run_summary(data: dict[str, Any], run_id: str) -> dict[str, Any]:
    m = process_metrics(data)
    ev = m["events"]
    stamps = [h["at"] for t in data["tasks"] for h in t.get("history", [])]
    stamps += [e["at"] for e in data.get("events", [])]
    human, restarts, unsupported = (
        ev.get("human_intervention", 0),
        ev.get("agent_restart", 0),
        ev.get("unsupported_automation", 0),
    )
    score = (
        m["counts"]["COMPLETE"]
        + ev.get("regression_repaired", 0)
        - human
        - len(m["repeated_signatures"])
        - m["counts"]["FAILED"]
    )
    return {
        "run": {
            "id": run_id,
            "started_at": min(stamps) if stamps else None,
            "completed_at": max(stamps) if stamps else None,
        },
        "tasks": {
            "completed": m["counts"]["COMPLETE"],
            "blocked": m["counts"]["BLOCKED"],
            "failed": m["counts"]["FAILED"],
            "retried": m["retries"],
        },
        "verification": m["verification"],
        "integration": {
            "conflicts": ev.get("integration_conflict", 0),
            "failed_merges": ev.get("integrate_fail", 0),
        },
        "ci": {
            "runs": "UNKNOWN",
            "cancelled": "UNKNOWN",
            "failures": "UNKNOWN",
            "approximate_total_minutes": "UNKNOWN",
        },
        "autonomy": {
            "human_interventions": human,
            "agent_restarts": restarts,
            "unsupported_automation_events": unsupported,
            "score": score,
        },
        "regressions": {
            "discovered": ev.get("regression_found", 0),
            "repaired": ev.get("regression_repaired", 0),
        },
    }


# ---------------------------------------------------------------- CLI


def cmd_validate(a: argparse.Namespace) -> int:
    # Handoffs and blocker reports live on task branches, so file checks are opt-in (--files, run
    # from the task branch checkout). The ledger branch is validated without them.
    data = load_ledger()
    errors = validate_ledger(data, check_files=a.files)
    if errors:
        print("\n".join(f"ERROR {e}" for e in errors))
        return 1
    print(f"OK: {len(data['tasks'])} tasks valid")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    data = load_ledger()
    m = process_metrics(data)
    print("states: " + ", ".join(f"{s}={n}" for s, n in m["counts"].items() if n))
    for task in sorted(data["tasks"], key=lambda t: t["id"]):
        if task["state"] == "COMPLETE":
            continue
        extra = ""
        if task["state"] == "QUEUED":
            extra = "  [" + why_not_runnable(data, task) + "]"
        elif task["state"] == "BLOCKED":
            extra = "  [" + "; ".join(task["blocked_by"]) + "]"
        elif task["owner"]:
            extra = f"  [{task['owner']} on {task['branch']}]"
        print(f"{task['id']} {task['state']:<11} p{task['priority']} {task['name']}{extra}")
    nxt = runnable(data)
    print("runnable: " + (", ".join(t["id"] for t in nxt) if nxt else "none"))
    return 0


def cmd_next(a: argparse.Namespace) -> int:
    found = runnable(load_ledger(), a.machine)[: a.limit]
    if not found:
        print("NONE: no runnable task (run 'status' to see why)")
        return 2
    for task in found:
        print(f"{task['id']}\tp{task['priority']}\t{task['machine'] or 'any'}\t{task['name']}")
    return 0


def cmd_deps(a: argparse.Namespace) -> int:
    data = load_ledger()
    tasks = task_map(data)
    task = get_task(data, a.task)

    def show(tid: str, depth: int) -> None:
        t = tasks[tid]
        print("  " * depth + f"{tid} [{t['state']}] {t['name']}")
        for dep in t["dependencies"]:
            show(dep, depth + 1)

    show(task["id"], 0)
    rev = [t["id"] for t in data["tasks"] if task["id"] in t["dependencies"]]
    print("unblocks: " + (", ".join(rev) if rev else "nothing"))
    return 0


def publish(action: Any) -> int:
    """Apply `action` to the ledger on origin/<REMOTE> as one commit and push it.

    A rejected push (another writer got there first) refetches and re-applies the action, so a
    lost claim race surfaces as the action's own error ("not runnable"). This is the only lock.
    """
    global LEDGER, REMOTE
    branch = REMOTE or "main"
    name = git_out("config", "user.name", check=False).stdout.strip() or "archipelago-agent"
    email = (
        git_out("config", "user.email", check=False).stdout.strip() or "agent@archipelago.invalid"
    )
    for _ in range(PUBLISH_ATTEMPTS):
        git_out("fetch", "-q", "origin", branch)
        tmp = Path(tempfile.mkdtemp(prefix="ledger-"))
        git_out("worktree", "add", "-q", "--detach", str(tmp), f"origin/{branch}")
        old_ledger, old_remote = LEDGER, REMOTE
        LEDGER, REMOTE = tmp / "agents" / "TASKS.yaml", None
        try:
            data = load_ledger()
            action(data)
            errors = validate_ledger(data, check_files=False)
            if errors:
                print("\n".join(f"ERROR {e}" for e in errors))
                print("ledger NOT written")
                return 1
            save_ledger(data)
            git_out("add", "agents/TASKS.yaml", cwd=tmp)
            if not git_out("diff", "--cached", "--quiet", cwd=tmp, check=False).returncode:
                return 0
            git_out(
                "-c",
                f"user.name={name}",
                "-c",
                f"user.email={email}",
                "commit",
                "-q",
                "-m",
                f"ledger: {CURRENT_CMD}",
                cwd=tmp,
            )
            if (
                git_out(
                    "push", "-q", "origin", f"HEAD:refs/heads/{branch}", cwd=tmp, check=False
                ).returncode
                == 0
            ):
                return 0
        finally:
            LEDGER, REMOTE = old_ledger, old_remote
            git_out("worktree", "remove", "--force", str(tmp), check=False)
            shutil.rmtree(tmp, ignore_errors=True)
    raise ControllerError(
        f"could not publish the ledger to origin/{branch} after {PUBLISH_ATTEMPTS} attempts"
    )


def mutate(action: Any) -> int:
    if REMOTE:
        return publish(action)
    data = load_ledger()
    action(data)
    errors = validate_ledger(data, check_files=False)
    if errors:
        print("\n".join(f"ERROR {e}" for e in errors))
        print("ledger NOT written")
        return 1
    save_ledger(data)
    return 0


def cmd_claim(a: argparse.Namespace) -> int:
    def run(data: dict[str, Any]) -> None:
        task = get_task(data, a.task)
        if task not in runnable(data, a.machine):
            raise ControllerError(f"{a.task} is not runnable: {why_not_runnable(data, task)}")
        task.update(
            owner=a.owner,
            machine=a.machine,
            branch=a.branch
            or f"agent/{a.task}-{re.sub(r'[^a-z0-9]+', '-', task['name'].lower()).strip('-')[:32]}",
            handoff_file=task["handoff_file"] or f"agents/handoffs/{a.task}/LATEST.md",
        )
        transition(task, "CLAIMED", by=a.owner)
        print(
            f"claimed {a.task} on {task['branch']}; "
            f"create the handoff {task['handoff_file']} before starting"
        )

    return mutate(run)


def simple_transition(to: str, event: str) -> Any:
    def cmd(a: argparse.Namespace) -> int:
        def run(data: dict[str, Any]) -> None:
            task = get_task(data, a.task)
            by = require_actor(task, a.by, event, integrator=to == "QUEUED")
            if to == "ACTIVE" and not (ROOT / task["handoff_file"]).is_file():
                raise ControllerError(f"create {task['handoff_file']} before starting")
            if to == "REVIEW" and not task["last_good_commit"] and not a.commit:
                raise ControllerError("sending to REVIEW requires --commit (the last good commit)")
            if a.commit:
                task["last_good_commit"] = a.commit
            transition(task, to, by=by, note=a.note or "", event=event)
            if to == "QUEUED":  # free the task so any machine can claim it again
                task.update(owner=None, machine=None, branch=None)

        return mutate(run)

    return cmd


def cmd_record_failure(a: argparse.Namespace) -> int:
    def run(data: dict[str, Any]) -> None:
        task = get_task(data, a.task)
        by = require_actor(task, a.by, "record-failure", integrator=False)
        reason = bump_failure(task, a.kind, a.signature)
        add_event(task, "failure", by, f"{a.kind}: {normalize_signature(a.signature)}")
        if reason and task["state"] == "ACTIVE":
            auto_block(task, reason, "controller")
            print(
                f"BLOCKED: {reason}\nWrite {Path(task['handoff_file']).parent}/BLOCKER.md "
                f"with sections: {', '.join(BLOCKER_HEADINGS)}"
            )
        else:
            print(f"recorded; attempts={task['attempts']}")

    return mutate(run)


def cmd_block(a: argparse.Namespace) -> int:
    def run(data: dict[str, Any]) -> None:
        task = get_task(data, a.task)
        by = require_actor(task, a.by, "block", integrator=False)
        report = ROOT / (a.report or str(Path(task["handoff_file"] or "").parent / "BLOCKER.md"))
        if not report.is_file():
            raise ControllerError(
                f"blocker report {report} must exist first "
                f"(sections: {', '.join(BLOCKER_HEADINGS)})"
            )
        text = report.read_text(encoding="utf-8")
        missing = [
            h for h in BLOCKER_HEADINGS if not re.search(rf"^##\s+{re.escape(h)}\s*$", text, re.M)
        ]
        if missing:
            raise ControllerError(f"blocker report missing sections: {', '.join(missing)}")
        task["blocked_by"] = [*task["blocked_by"], a.reason]
        transition(task, "BLOCKED", by=by, note=a.reason, event="block")

    return mutate(run)


def cmd_unblock(a: argparse.Namespace) -> int:
    def run(data: dict[str, Any]) -> None:
        task = get_task(data, a.task)
        by = require_actor(task, a.by, "unblock", integrator=True)
        human = [b for b in task["blocked_by"] if b.startswith("human:")]
        if human and not a.resolved:
            raise ControllerError(
                f"{task['id']}: unresolved human blockers ({'; '.join(human)}); "
                "pass --resolved '<what the human decided or did>'"
            )
        cycles = sum(1 for h in task.get("history", []) if h.get("event") == "unblock")
        if cycles >= UNBLOCK_CAP:
            transition(
                task,
                "FAILED",
                by="controller",
                note=f"unblocked {cycles}x already; the cause is not being fixed",
                event="unblock_cap",
            )
            print(f"FAILED: {task['id']} was unblocked {cycles} times (cap {UNBLOCK_CAP})")
            return
        task["blocked_by"] = []
        task["attempts"] = {}
        task["owner"] = None
        note = a.note or "blocker cleared"
        transition(
            task,
            "QUEUED",
            by=by,
            note=f"{note}; resolved: {a.resolved}" if human else note,
            event="unblock",
        )

    return mutate(run)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def assertion_results(claimed: Any, errors: list[str]) -> dict[str, str]:
    """Validate the verdict's optional assertions list; shape problems join `errors`."""
    if claimed is None:
        return {}
    if not isinstance(claimed, list):
        errors.append("assertions must be a list")
        return {}
    results: dict[str, str] = {}
    for item in claimed:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("description"), str)
            or item.get("result") not in ASSERTION_RESULTS
        ):
            errors.append(
                f"each assertion needs a description and a result in {sorted(ASSERTION_RESULTS)}"
            )
            return {}
        results[norm(item["description"])] = item["result"]
    return results


def check_pass_verdict(
    task: dict[str, Any], verdict: dict[str, Any], results: dict[str, str]
) -> None:
    """A PASS must cover the ledger's commands and assertions exactly, judged by the ledger."""
    declared = {c["command"]: c["expected_exit_code"] for c in task["acceptance"]["commands"]}
    ran = [c["command"] for c in verdict["commands"]]
    if unknown := sorted(set(ran) - set(declared)):
        raise ControllerError("PASS verdict has commands not in the ledger: " + "; ".join(unknown))
    if missing := sorted(set(declared) - set(ran)):
        raise ControllerError("PASS verdict did not run: " + "; ".join(missing))
    for entry in verdict["commands"]:
        if entry["actual_exit_code"] != declared[entry["command"]]:
            raise ControllerError(
                f"PASS verdict: {entry['command']!r} exited {entry['actual_exit_code']}, "
                f"ledger expects {declared[entry['command']]}"
            )
    wanted = [x["description"] for x in task["acceptance"].get("assertions", [])]
    if absent := [d for d in wanted if norm(d) not in results]:
        raise ControllerError("PASS verdict has no result for assertions: " + "; ".join(absent))
    if unmet := [d for d in wanted if results[norm(d)] != "met"]:
        raise ControllerError("PASS verdict has unmet assertions: " + "; ".join(unmet))


def cmd_verify(a: argparse.Namespace) -> int:
    def run(data: dict[str, Any]) -> None:
        task = get_task(data, a.task)
        path = ROOT / (
            a.verdict or str(Path(task["handoff_file"] or "").parent / "VERIFICATION.yaml")
        )
        if not path.is_file():
            raise ControllerError(
                f"no verdict at {path}: verifier infrastructure failure, NOT a task failure; "
                f"task stays {task['state']}"
            )
        verdict = yaml.safe_load(path.read_text(encoding="utf-8"))
        # Assertion results are not in verification.schema.json (additionalProperties: false);
        # the controller checks them itself so the schema file can follow separately.
        claimed = verdict.pop("assertions", None) if isinstance(verdict, dict) else None
        errors = [
            e.message
            for e in jsonschema.Draft202012Validator(
                load_schema("verification.schema.json")
            ).iter_errors(verdict)
        ]
        results = assertion_results(claimed, errors)
        if errors:
            raise ControllerError(
                "invalid verdict (verifier infrastructure failure): " + "; ".join(errors)
            )
        if verdict["task"] != task["id"]:
            raise ControllerError(f"verdict is for {verdict['task']}, not {task['id']}")
        if norm(verdict["verifier"]) == norm(task["owner"] or ""):
            raise ControllerError(
                f"verifier {verdict['verifier']!r} is the task owner; verification must be independent"
            )
        if not task["last_good_commit"]:
            raise ControllerError(f"{task['id']} has no last_good_commit to verify against")
        if full_sha(verdict["verified_commit"], "verified_commit") != full_sha(
            task["last_good_commit"], "last_good_commit"
        ):
            raise ControllerError(
                "verdict covers a different commit than last_good_commit; re-verify"
            )
        if verdict["status"] == "PASS":
            check_pass_verdict(task, verdict, results)
            transition(task, "INTEGRATION", by=verdict["verifier"], event="verify_pass")
            return
        if task["state"] != "REVIEW":
            raise ControllerError("FAIL verdicts apply to tasks in REVIEW")
        first = verdict["failures"][0]
        kind = first.get("kind", "test_failure")
        signature = normalize_signature(f"{first['type']}:{first.get('file', '-')}")
        reason = bump_failure(task, kind, signature)
        add_event(task, "verify_fail", verdict["verifier"], "; ".join(verdict["required_actions"]))
        if reason:
            auto_block(task, reason, "controller")
            print(f"BLOCKED: {reason}; write BLOCKER.md")
        else:
            transition(
                task, "ACTIVE", by="controller", note="returned to worker", event="return_to_worker"
            )
            print(f"{task['id']} returned to worker: {verdict['required_actions']}")

    return mutate(run)


def cmd_integrate_fail(a: argparse.Namespace) -> int:
    def run(data: dict[str, Any]) -> None:
        machine_may("integrator", a.machine)
        task = get_task(data, a.task)
        if task["state"] != "INTEGRATION":
            raise ControllerError("integrate-fail applies to tasks in INTEGRATION")
        reason = bump_failure(task, "integration_failure", a.signature)
        add_event(task, "integrate_fail", "integrator", a.signature)
        if reason:
            auto_block(task, reason, "controller")
        else:
            transition(task, "ACTIVE", by="integrator", note=a.signature, event="return_to_worker")

    return mutate(run)


def check_integration_commit(task: dict[str, Any], commit: str) -> str:
    """The integration commit must exist, sit on the integration branch and contain verified work."""
    full = full_sha(commit, "--commit")
    verified = full_sha(task["last_good_commit"] or "", "verified commit (last_good_commit)")
    tip = integration_tip()
    if not is_ancestor(full, tip):
        raise ControllerError(
            f"--commit {full[:12]} is not an ancestor of the integration tip {tip}"
        )
    if not is_ancestor(verified, full):
        raise ControllerError(f"--commit {full[:12]} does not contain verified {verified[:12]}")
    parents = git_out("rev-list", "--parents", "-n", "1", full).stdout.split()[1:]
    if len(parents) < 2 and full == verified:
        raise ControllerError("--commit is the verified commit itself; expected the merge commit")
    return full


def cmd_complete(a: argparse.Namespace) -> int:
    def run(data: dict[str, Any]) -> None:
        machine_may("integrator", a.machine)
        task = get_task(data, a.task)
        if task["state"] != "INTEGRATION":
            raise ControllerError(
                f"{a.task} is {task['state']}; only verified tasks in INTEGRATION can complete"
            )
        commit = check_integration_commit(task, a.commit)
        task["last_good_commit"] = commit
        transition(
            task,
            "COMPLETE",
            by=f"integrator/{a.machine}",
            note=f"merged at {commit}",
            event="complete",
        )

    return mutate(run)


def cmd_log_event(a: argparse.Namespace) -> int:
    def run(data: dict[str, Any]) -> None:
        if a.task:
            get_task(data, a.task)
        add_process_event(data, a.kind, a.by or "unknown", a.note, a.task)

    return mutate(run)


def cmd_review_process(_: argparse.Namespace) -> int:
    data = load_ledger()
    m = process_metrics(data)
    print(json.dumps(m, indent=2, default=list))
    findings = []
    if m["counts"]["BLOCKED"] > 3:
        findings.append(
            f"more than 3 blocked tasks ({m['counts']['BLOCKED']}): trigger a reliability review"
        )
    for tid, sig, n in m["repeated_signatures"]:
        findings.append(
            f"{tid} repeated failure signature x{n}: {sig}; "
            "ask whether the rule, not the task, is wrong"
        )
    if m["events"].get("human_intervention", 0):
        findings.append("human interventions logged: find the rule that would have removed each")
    if m["events"].get("unsupported_automation", 0):
        findings.append("unsupported-automation events logged: redesign around them")
    print("\n".join(f"REVIEW: {f}" for f in findings) or "REVIEW: no triggers fired")
    return 0


def cmd_report(a: argparse.Namespace) -> int:
    summary = build_run_summary(load_ledger(), a.run_id)
    errors = [
        e.message
        for e in jsonschema.Draft202012Validator(load_schema("run.schema.json")).iter_errors(
            summary
        )
    ]
    if errors:
        print("\n".join(errors))
        return 1
    text = yaml.safe_dump(summary, sort_keys=False)
    if a.write:
        (AGENTS / "runs" / f"{a.run_id}.yaml").write_text(text, encoding="utf-8")
    print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--remote",
        action="store_true",
        help="read the ledger from origin/<ledger-branch> and publish every change there as one "
        "fast-forward commit. Use this for all multi-machine work.",
    )
    p.add_argument("--ledger-branch", default="main", help="branch with the shared ledger")
    sub = p.add_subparsers(dest="cmd", required=True)
    v0 = sub.add_parser("validate")
    v0.add_argument(
        "--files", action="store_true", help="also require handoff/BLOCKER files on disk"
    )
    v0.set_defaults(fn=cmd_validate)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    n = sub.add_parser("next")
    n.add_argument("--machine", choices=["A", "B"])
    n.add_argument("--limit", type=int, default=3)
    n.set_defaults(fn=cmd_next)
    d = sub.add_parser("deps")
    d.add_argument("task")
    d.set_defaults(fn=cmd_deps)

    c = sub.add_parser("claim")
    c.add_argument("task")
    c.add_argument("--owner", required=True)
    c.add_argument("--machine", required=True, choices=["A", "B"])
    c.add_argument("--branch")
    c.set_defaults(fn=cmd_claim)

    for name, to, event in (
        ("start", "ACTIVE", "start"),
        ("review", "REVIEW", "to_review"),
        ("requeue", "QUEUED", "requeue"),
    ):
        s = sub.add_parser(name)
        s.add_argument("task")
        s.add_argument(
            "--by", required=True, help="the task owner (requeue: or integrator machine)"
        )
        s.add_argument("--note")
        s.add_argument("--commit")
        s.set_defaults(fn=simple_transition(to, event))

    r = sub.add_parser("record-failure")
    r.add_argument("task")
    r.add_argument("--kind", required=True, choices=FAILURE_KINDS)
    r.add_argument("--signature", required=True)
    r.add_argument("--by", required=True, help="the task owner")
    r.set_defaults(fn=cmd_record_failure)

    b = sub.add_parser("block")
    b.add_argument("task")
    b.add_argument("--reason", required=True)
    b.add_argument("--report")
    b.add_argument("--by", required=True, help="the task owner")
    b.set_defaults(fn=cmd_block)

    u = sub.add_parser("unblock")
    u.add_argument("task")
    u.add_argument("--by", required=True, help="the task owner or the integrator machine")
    u.add_argument("--note")
    u.add_argument("--resolved", help="what resolved the human:* blockers (required if any)")
    u.set_defaults(fn=cmd_unblock)

    v = sub.add_parser("verify")
    v.add_argument("task")
    v.add_argument("--verdict")
    v.set_defaults(fn=cmd_verify)

    i = sub.add_parser("integrate-fail")
    i.add_argument("task")
    i.add_argument("--signature", required=True)
    i.add_argument("--machine", required=True, choices=["A", "B"])
    i.set_defaults(fn=cmd_integrate_fail)

    k = sub.add_parser("complete")
    k.add_argument("task")
    k.add_argument(
        "--commit", required=True, help="integration (merge) commit on the integration branch"
    )
    k.add_argument("--machine", required=True, choices=["A", "B"])
    k.set_defaults(fn=cmd_complete)

    e = sub.add_parser("log-event")
    e.add_argument("--kind", required=True, choices=EVENT_KINDS)
    e.add_argument("--note", required=True)
    e.add_argument("--task")
    e.add_argument("--by")
    e.set_defaults(fn=cmd_log_event)

    sub.add_parser("review-process").set_defaults(fn=cmd_review_process)
    rp = sub.add_parser("report")
    rp.add_argument("--run-id", required=True)
    rp.add_argument("--write", action="store_true")
    rp.set_defaults(fn=cmd_report)
    return p


def main(argv: list[str] | None = None) -> int:
    global REMOTE, CURRENT_CMD, LEDGER_BRANCH
    saved = REMOTE, CURRENT_CMD, LEDGER_BRANCH
    try:
        return _main(argv)
    finally:
        REMOTE, CURRENT_CMD, LEDGER_BRANCH = saved


def _main(argv: list[str] | None) -> int:
    global REMOTE, CURRENT_CMD, LEDGER_BRANCH
    args = build_parser().parse_args(argv)
    LEDGER_BRANCH = args.ledger_branch
    REMOTE = args.ledger_branch if args.remote else None
    CURRENT_CMD = " ".join(
        a for a in (argv if argv is not None else sys.argv[1:]) if a != "--remote"
    )[:100]
    try:
        if REMOTE:
            git_out("fetch", "-q", "origin", REMOTE)
        return int(args.fn(args))
    except ControllerError as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

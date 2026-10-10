"""Deterministic task-ledger controller for Archipelago agents.

Reads and edits agents/TASKS.yaml. It is a CLI that runs once and exits: it launches no
agents, starts no background process and keeps no state outside Git. Every transition is
validated against the lifecycle below and recorded in the task's history.

    python agents/controller.py validate
    python agents/controller.py status
    python agents/controller.py next [--machine A|B] [--limit N]
    python agents/controller.py deps T10
    python agents/controller.py claim|start|review T10 --owner B/w1 --machine B
    python agents/controller.py record-failure T10 --kind test_failure --signature "..."
    python agents/controller.py block T10 --report agents/handoffs/T10/BLOCKER.md --reason "..."
    python agents/controller.py unblock T10
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
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import yaml

AGENTS = Path(__file__).resolve().parent
ROOT = AGENTS.parent
LEDGER = AGENTS / "TASKS.yaml"
OWNERSHIP = AGENTS / "OWNERSHIP.yaml"
SCHEMAS = AGENTS / "schemas"

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


def load_ledger(path: Path | None = None) -> dict[str, Any]:
    path = path or LEDGER
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise ControllerError(f"{path}: expected a mapping with a 'tasks' list")
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
    attempts = task.setdefault("attempts", {})
    attempts[kind] = attempts.get(kind, 0) + 1
    sigs = attempts.setdefault("signatures", {})
    sigs[signature] = sigs.get(signature, 0) + 1
    policy = task["retry_policy"]
    if sigs[signature] >= policy["same_failure_signature"]:
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


def cmd_validate(_: argparse.Namespace) -> int:
    data = load_ledger()
    errors = validate_ledger(data)
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


def mutate(action: Any) -> int:
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
            if to == "ACTIVE" and not (ROOT / task["handoff_file"]).is_file():
                raise ControllerError(f"create {task['handoff_file']} before starting")
            if to == "REVIEW" and not task["last_good_commit"] and not a.commit:
                raise ControllerError("sending to REVIEW requires --commit (the last good commit)")
            if a.commit:
                task["last_good_commit"] = a.commit
            transition(
                task, to, by=a.by or task["owner"] or "unknown", note=a.note or "", event=event
            )

        return mutate(run)

    return cmd


def cmd_record_failure(a: argparse.Namespace) -> int:
    def run(data: dict[str, Any]) -> None:
        task = get_task(data, a.task)
        reason = bump_failure(task, a.kind, a.signature)
        add_event(task, "failure", a.by or task["owner"] or "unknown", f"{a.kind}: {a.signature}")
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
        transition(
            task, "BLOCKED", by=a.by or task["owner"] or "unknown", note=a.reason, event="block"
        )

    return mutate(run)


def cmd_unblock(a: argparse.Namespace) -> int:
    def run(data: dict[str, Any]) -> None:
        task = get_task(data, a.task)
        task["blocked_by"] = []
        task["attempts"] = {}
        task["owner"] = None
        transition(
            task,
            "QUEUED",
            by=a.by or "orchestrator",
            note=a.note or "blocker cleared",
            event="unblock",
        )

    return mutate(run)


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
        errors = [
            e.message
            for e in jsonschema.Draft202012Validator(
                load_schema("verification.schema.json")
            ).iter_errors(verdict)
        ]
        if errors:
            raise ControllerError(
                "invalid verdict (verifier infrastructure failure): " + "; ".join(errors)
            )
        if verdict["task"] != task["id"]:
            raise ControllerError(f"verdict is for {verdict['task']}, not {task['id']}")
        if task["last_good_commit"] and not (
            task["last_good_commit"].startswith(verdict["verified_commit"])
            or verdict["verified_commit"].startswith(task["last_good_commit"])
        ):
            raise ControllerError(
                "verdict covers a different commit than last_good_commit; re-verify"
            )
        if verdict["status"] == "PASS":
            if any(c["actual_exit_code"] != c["expected_exit_code"] for c in verdict["commands"]):
                raise ControllerError(
                    "PASS verdict contains a command whose exit code differs from expected"
                )
            declared = {c["command"] for c in task["acceptance"]["commands"]}
            ran = {c["command"] for c in verdict["commands"]}
            if declared - ran:
                raise ControllerError(
                    "PASS verdict did not run: " + "; ".join(sorted(declared - ran))
                )
            transition(task, "INTEGRATION", by=verdict["verifier"], event="verify_pass")
            return
        if task["state"] != "REVIEW":
            raise ControllerError("FAIL verdicts apply to tasks in REVIEW")
        first = verdict["failures"][0]
        kind = first.get("kind", "test_failure")
        signature = f"{first['type']}:{first.get('file', '-')}"
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


def cmd_complete(a: argparse.Namespace) -> int:
    def run(data: dict[str, Any]) -> None:
        machine_may("integrator", a.machine)
        task = get_task(data, a.task)
        if task["state"] != "INTEGRATION":
            raise ControllerError(
                f"{a.task} is {task['state']}; only verified tasks in INTEGRATION can complete"
            )
        task["last_good_commit"] = a.commit
        transition(
            task,
            "COMPLETE",
            by=f"integrator/{a.machine}",
            note=f"merged at {a.commit}",
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
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate").set_defaults(fn=cmd_validate)
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
        s.add_argument("--by")
        s.add_argument("--note")
        s.add_argument("--commit")
        s.set_defaults(fn=simple_transition(to, event))

    r = sub.add_parser("record-failure")
    r.add_argument("task")
    r.add_argument("--kind", required=True, choices=FAILURE_KINDS)
    r.add_argument("--signature", required=True)
    r.add_argument("--by")
    r.set_defaults(fn=cmd_record_failure)

    b = sub.add_parser("block")
    b.add_argument("task")
    b.add_argument("--reason", required=True)
    b.add_argument("--report")
    b.add_argument("--by")
    b.set_defaults(fn=cmd_block)

    u = sub.add_parser("unblock")
    u.add_argument("task")
    u.add_argument("--by")
    u.add_argument("--note")
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
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except ControllerError as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

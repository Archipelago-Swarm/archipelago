"""Start, inspect and stop ledger-driven agent sessions. Usable by humans and by agents.

    python agents/launch.py pick  --machine A            # what would run next (no side effects)
    python agents/launch.py tick  --machine A            # ONE idempotent step; a scheduler calls this
    python agents/launch.py start --machine A [--hours 8] [--dry-run]       # detached loop of ticks
    python agents/launch.py start --machine A --runner night -- --billing subscription --hours 8
    python agents/launch.py status --machine A
    python agents/launch.py stop  --machine A
    python agents/launch.py schedule --machine A --every 30   # print cron/routine recipes

Reliability (PROTOCOL section 13): `tick` is RELIABLE (runs once, exits). `start` creates a detached
OS process: CONDITIONALLY_RELIABLE, valid only on a machine that stays up (laptop/desktop/server). It
dies with an ephemeral cloud container; there, schedule `tick` with a routine/cron instead. `status`
never trusts a pid file alone: it checks that the process is alive and its heartbeat is fresh.
The loop launches fresh bounded `claude -p` sessions; it never keeps a conversation alive. It does not
use permission-bypass flags and never force-pushes. Sessions run only inside a dedicated git
worktree (.agent-runtime/worktrees/<machine>-<task>), never in the shared checkout. All ledger writes go through
`controller.py --remote`, so two machines cannot claim the same task.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import controller as ctl  # noqa: E402

ROOT = ctl.ROOT
RUNTIME = ROOT / ".agent-runtime"
HEARTBEAT_STALE_SECONDS = 600
LIMIT_MARKERS = ("usage limit", "rate limit", "rate_limit", "quota", "resets at")
# Claude CLI flags. Present in `claude --help` of 2.1.296 (checked 2026-10-10): --output-format,
# --permission-mode auto, --permission-prompts none, --disallowedTools. NOT verified against a live
# unattended session (T23): that `auto` mode plus `none` never stalls on a prompt, and that the
# DENIED patterns are matched against every spelling of a command (`git -C x push`, shell chains,
# aliases, `sh -c`). DENIED is a best-effort prefix list, not a security boundary; the real guards
# are the dedicated worktree, branch protection on main, and the clean-tree checks in this file.
SESSION_FLAGS = [
    "--output-format",
    "json",
    "--permission-mode",
    "auto",
    "--permission-prompts",
    "none",
]
PROTECTED_BRANCHES = ("main", "master")
DENIED = [
    "Bash(git push --force*)",
    "Bash(git push -f*)",
    "Bash(git push --force-with-lease*)",
    "Bash(git push origin main*)",
    "Bash(git push origin master*)",
    "Bash(git push origin HEAD:main*)",
    "Bash(git push origin HEAD:master*)",
    "Bash(git push origin HEAD:refs/heads/main*)",
    "Bash(git push origin HEAD*)",
    "Bash(git push * *:main*)",
    "Bash(git push * *:master*)",
    "Bash(git push * *:refs/heads/main*)",
    "Bash(git push --delete*)",
    "Bash(git push * --delete*)",
    "Bash(git push -d*)",
    "Bash(git push * :*)",
    "Bash(git -C * push*)",
    "Bash(git reset --hard*)",
    "Bash(git checkout main*)",
    "Bash(git checkout master*)",
    "Bash(git merge*)",
    "Bash(git branch -D*)",
    "Bash(git clean*)",
]
COMMON = (
    "Read CLAUDE.md, agents/LESSONS.md and agents/PROTOCOL.md first. Every ledger change goes through "
    "`python agents/controller.py --remote <command>`. Your working directory is a dedicated git worktree "
    "on the task branch; "
    "never force-push, never push to main, never merge, never switch your worktree off the task branch; stay inside the task's owned_paths. Do the work, update the handoff, push, "
    "and stop at the state PROTOCOL names for your role. "
)


def now() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ work selection


def pick_work(data: dict[str, Any], machine: str) -> tuple[str, dict[str, Any]] | None:
    """Deterministic: finish own work first, then verify, integrate, and only then start new work."""
    roles = ctl.load_ownership().get("roles", {})
    tasks = sorted(data["tasks"], key=lambda t: (t["priority"], t["id"]))
    for t in tasks:
        if t["state"] in {"CLAIMED", "ACTIVE"} and t["machine"] == machine:
            return "worker", t
    if roles.get("integrator") == machine:
        for t in tasks:
            if t["state"] == "INTEGRATION":
                return "integrator", t
    if roles.get("verifier") == machine:
        for t in tasks:
            if t["state"] == "REVIEW":
                return "verifier", t
    if roles.get("orchestrator") == machine:
        found = ctl.runnable(data)
        if found:
            return "claim", found[0]
    return None


def prompt_for(role: str, task: dict[str, Any], machine: str) -> str:
    tid, branch = task["id"], task["branch"] or f"agent/{task['id']}-<slug>"
    if role == "worker":
        return (
            f"{COMMON}You are the WORKER for {tid} ({task['name']}) on machine {machine}; branch {branch}. "
            f"Resume from the remote branch and its handoff if they exist. Follow PROTOCOL section 4. "
            f"Ledger commands need `--by {task['owner']}` (you are the owner). End with "
            f"`controller.py --remote review {tid} --by {task['owner']} --commit <sha>` or, if blocked, a "
            f"complete BLOCKER.md and `controller.py --remote block {tid} --by {task['owner']} --reason ...`."
        )
    if role == "verifier":
        return (
            f"{COMMON}You are the VERIFIER for {tid}. Do not modify implementation code. Follow PROTOCOL "
            f"section 7 at commit {task['last_good_commit']}: run every acceptance command, write "
            f"agents/handoffs/{tid}/VERIFICATION.yaml on the task branch, push it, then run "
            f"`controller.py --remote verify {tid} --machine {machine}`."
        )
    return (
        f"{COMMON}You are the INTEGRATOR for {tid} (branch {task['branch']}). Follow PROTOCOL section 8: merge "
        f"into the integration branch (unattended sessions cannot `git merge`; if the merge is denied, "
        f"write the handoff and stop for a human), run `make check-integration`, then "
        f"`controller.py --remote complete {tid} --commit <merge sha> --machine {machine}`, or "
        f"`integrate-fail` with a stable signature."
    )


# ------------------------------------------------------------------ OS helpers


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True
        ).stdout
        return f" {pid} " in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # a zombie is not alive
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def pid_identity(pid: int) -> str | None:
    """Process start time, so a recycled pid is not mistaken for our process (Linux only)."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


@contextlib.contextmanager
def tick_lock(machine: str) -> Iterator[bool]:
    """OS lock held for one tick; overlapping scheduler firings get False and exit."""
    RUNTIME.mkdir(exist_ok=True)
    with (RUNTIME / f"launch-{machine}.lock").open("a+b") as handle:
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.write(b"\0")
                handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True


def state_path(machine: str) -> Path:
    return RUNTIME / f"launch-{machine}.json"


def read_state(machine: str) -> dict[str, Any] | None:
    try:
        value: dict[str, Any] = json.loads(state_path(machine).read_text(encoding="utf-8"))
        return value
    except (OSError, ValueError):
        return None


def write_state(machine: str, **fields: Any) -> None:
    RUNTIME.mkdir(exist_ok=True)
    value = {**(read_state(machine) or {}), **fields, "updated_at": iso(now())}
    tmp = state_path(machine).with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    tmp.replace(state_path(machine))


def stop_requested(machine: str) -> str | None:
    for name in ("STOP", f"STOP-{machine}"):
        if (RUNTIME / name).exists():
            return name
    return None


def liveness(machine: str) -> tuple[str, str]:
    st = read_state(machine)
    if not st or "pid" not in st:
        return "NOT_STARTED", "no launch record"
    if not pid_alive(st["pid"]):
        return (
            "DEAD",
            f"pid {st['pid']} is gone; last stop_reason: {st.get('stop_reason', 'none recorded')}",
        )
    ident = pid_identity(st["pid"])
    if st.get("pid_identity") and ident and ident != st["pid_identity"]:
        return "DEAD", f"pid {st['pid']} was recycled by another process"
    if st.get("runner") == "loop":
        beat = st.get("heartbeat_at")
        age = (
            (
                now() - datetime.strptime(beat, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            ).total_seconds()
            if beat
            else None
        )
        if age is None or age > HEARTBEAT_STALE_SECONDS + st.get("slice_minutes", 30) * 60:
            return (
                "STALLED",
                f"pid alive but heartbeat is {'missing' if age is None else f'{int(age)}s old'}",
            )
    return "ALIVE", f"pid {st['pid']} ({st.get('runner')})"


# ------------------------------------------------------------------ one tick


def fingerprint(task_id: str, remote: str) -> tuple[str, str]:
    """(ledger state of the task, remote head of its branch): changes when a session made progress."""
    ctl.git_out("fetch", "-q", "origin", check=False)
    try:
        task = ctl.get_task(ctl.load_ledger(), task_id)
    except ctl.ControllerError:
        return ("?", "?")
    head = ""
    if task["branch"]:
        head = ctl.git_out(
            "rev-parse", "--verify", "-q", f"origin/{task['branch']}", check=False
        ).stdout.strip()
    return (f"{task['state']}:{task['last_good_commit']}:{len(task.get('history', []))}", head)


def dirty_files(path: Path) -> str:
    """`git status --porcelain` with untracked files; the launcher's own runtime dir is ignored."""
    exclude = ["--", ".", ":(exclude).agent-runtime"]
    return ctl.git_out(
        "status", "--porcelain", "--untracked-files=all", *exclude, cwd=path
    ).stdout.strip()


def current_branch(path: Path) -> str:
    return ctl.git_out("rev-parse", "--abbrev-ref", "HEAD", cwd=path).stdout.strip()


def session_worktree(machine: str, role: str, task: dict[str, Any], remote: str) -> Path:
    """Create or reuse .agent-runtime/worktrees/<machine>-<task> on the task's branch.

    The shared checkout is never used for sessions. Integrators get `integrate/<task>`, never main.
    Existing local branches are reused as they are (never reset), so unpushed work survives.
    """
    branch = f"integrate/{task['id']}" if role == "integrator" else task["branch"]
    if not branch or branch in PROTECTED_BRANCHES:
        raise ctl.ControllerError(f"{task['id']}: refusing to run a session on branch {branch!r}")
    path = RUNTIME / "worktrees" / f"{machine}-{task['id']}"
    has_remote = (
        ctl.git_out("rev-parse", "--verify", "-q", f"origin/{branch}", check=False).returncode == 0
    )
    if (path / ".git").exists():
        if not dirty_files(path) and has_remote and current_branch(path) == branch:
            ctl.git_out("merge", "--ff-only", "-q", f"origin/{branch}", cwd=path, check=False)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    ctl.git_out("worktree", "prune", check=False)
    exists = ctl.git_out("rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)
    if exists.returncode == 0:
        ctl.git_out("worktree", "add", "-q", str(path), branch)
    else:
        base = f"origin/{branch}" if has_remote else f"origin/{remote}"
        ctl.git_out("worktree", "add", "-q", "-b", branch, str(path), base)
    return path


def unsafe_reason(worktree: Path) -> str | None:
    """Why a session must not start now, or None. Checks the shared checkout and the worktree."""
    for label, path in (("shared checkout", ROOT), ("session worktree", worktree)):
        if files := dirty_files(path):
            return f"{label} {path} has modified or untracked files:\n{files[:400]}"
    if (branch := current_branch(worktree)) in PROTECTED_BRANCHES:
        return f"session worktree {worktree} is on {branch}"
    return None


def run_session(
    prompt: str, minutes: int, log: Path, extra: list[str], cwd: Path
) -> tuple[int | None, str]:
    argv = ["claude", "-p", prompt, *SESSION_FLAGS, "--disallowedTools", *DENIED, *extra]
    with log.open("ab") as out:
        out.write(f"\n=== {iso(now())} session start\n".encode())
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=os.name != "nt",
        )
        try:
            text, _ = proc.communicate(timeout=minutes * 60)
            code: int | None = proc.returncode
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(proc.pid, 15)
            else:
                proc.terminate()
            text, _ = proc.communicate()
            code = None
        out.write((text or "").encode())
    return code, text or ""


def tick(
    machine: str, remote: str, minutes: int, extra: list[str], dry_run: bool = False
) -> tuple[str, str]:
    previous, ctl.REMOTE = ctl.REMOTE, remote
    try:
        return _tick(machine, remote, minutes, extra, dry_run)
    finally:
        ctl.REMOTE = previous


def _tick(
    machine: str, remote: str, minutes: int, extra: list[str], dry_run: bool
) -> tuple[str, str]:
    """One step. Returns (status, detail); status in idle|claimed|progress|no_progress|limit|error|stop|busy."""
    if reason := stop_requested(machine):
        return "stop", f"{reason} file present"
    try:
        ctl.git_out("fetch", "-q", "origin", remote)
        picked = pick_work(ctl.load_ledger(), machine)
    except ctl.ControllerError as error:
        return "error", str(error)
    if not picked:
        return "idle", "no runnable or assigned work for this machine"
    role, task = picked
    if dry_run:
        return "idle", f"would run: {role} {task['id']} ({task['name']})"
    if role == "claim":
        target = task["machine"] or machine
        rc = ctl.main(
            [
                "--remote",
                "--ledger-branch",
                remote,
                "claim",
                task["id"],
                "--owner",
                f"{machine}/launcher",
                "--machine",
                target,
            ]
        )
        return (
            ("claimed", f"{task['id']} -> machine {target}")
            if rc == 0
            else ("error", f"claim of {task['id']} lost or refused")
        )
    try:
        ctl.git_out("fetch", "-q", "origin")
        worktree = session_worktree(machine, role, task, remote)
        if problem := unsafe_reason(worktree):
            return "error", f"{role} {task['id']}: {problem}"
    except ctl.ControllerError as error:
        return "error", f"{role} {task['id']}: {error}"
    before = fingerprint(task["id"], remote)
    RUNTIME.mkdir(exist_ok=True)
    code, text = run_session(
        prompt_for(role, task, machine), minutes, RUNTIME / f"launch-{machine}.log", extra, worktree
    )
    if any(m in text.lower() for m in LIMIT_MARKERS):
        return (
            "limit",
            f"provider limit text in output while running {role} {task['id']}; wait for reset",
        )
    after = fingerprint(task["id"], remote)
    if code is None:
        return (
            "progress" if after != before else "no_progress",
            f"{role} {task['id']} hit the {minutes} min slice limit",
        )
    return ("progress" if after != before else "no_progress", f"{role} {task['id']} exit {code}")


# ------------------------------------------------------------------ loop (detached)


def loop(
    machine: str, remote: str, hours: float, minutes: int, max_ticks: int, extra: list[str]
) -> int:
    deadline = now() + timedelta(hours=hours)
    stalls: dict[str, int] = {}
    reason = "max ticks reached"
    for _ in range(max_ticks):
        write_state(machine, heartbeat_at=iso(now()))
        if now() >= deadline:
            reason = "deadline"
            break
        with tick_lock(machine) as got:
            status, detail = (
                ("busy", "another tick holds the lock")
                if not got
                else tick(machine, remote, minutes, extra)
            )
        write_state(
            machine,
            last_tick={"at": iso(now()), "status": status, "detail": detail},
            heartbeat_at=iso(now()),
        )
        print(f"{iso(now())} {status}: {detail}", flush=True)
        if status in {"stop", "idle", "limit", "error"}:
            reason = f"{status}: {detail}"
            break
        key = detail.split(" hit ")[0].split(" exit ")[0]
        stalls[key] = stalls.get(key, 0) + 1 if status == "no_progress" else 0
        if stalls[key] >= 2:
            reason = f"no progress twice on {key}; needs a human or a blocker report"
            break
        if status == "busy":
            time.sleep(30)
    write_state(machine, stop_reason=reason, stopped_at=iso(now()))
    return 0


# ------------------------------------------------------------------ CLI


def cmd_start(a: argparse.Namespace) -> int:
    live, detail = liveness(a.machine)
    if live in {"ALIVE", "STALLED"}:
        print(f"REFUSED: a launcher is already {live} ({detail}); run 'stop' or inspect the log")
        return 1
    if stop_requested(a.machine):
        print(
            f"REFUSED: {stop_requested(a.machine)} exists in {RUNTIME}; remove it deliberately to start"
        )
        return 1
    errors = ctl.validate_ledger(ctl.load_ledger(), check_files=False)
    if errors:
        print("REFUSED: ledger invalid:\n" + "\n".join(errors))
        return 1
    if a.runner == "loop":
        if not shutil.which("claude"):
            print("REFUSED: 'claude' is not on PATH")
            return 1
        if dirty_files(ROOT):
            print("REFUSED: checkout has modified or untracked files")
            return 1
        status, detail = tick(a.machine, a.remote, 1, [], dry_run=True)
        print(f"preflight: {detail}")
        if detail.startswith("no runnable") and not a.force:
            print("REFUSED: nothing to do (use --force to start anyway)")
            return 1
        argv = [
            sys.executable,
            str(Path(__file__)),
            "_loop",
            "--machine",
            a.machine,
            "--remote",
            a.remote,
            "--hours",
            str(a.hours),
            "--slice-minutes",
            str(a.slice_minutes),
            "--max-ticks",
            str(a.max_ticks),
            *[x for e in a.claude_arg for x in ("--claude-arg", e)],
        ]
    else:
        argv = [
            sys.executable,
            str(ROOT / "tools" / "agents" / "night.py"),
            "--machine",
            a.machine,
            *a.rest,
        ]
    if a.dry_run:
        print("dry run; would spawn: " + " ".join(argv))
        return 0
    RUNTIME.mkdir(exist_ok=True)
    log = RUNTIME / f"launch-{a.machine}.log"
    kwargs: dict[str, Any] = {"cwd": ROOT, "stdin": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = (
            0x00000008 | 0x00000200
        )  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    with log.open("ab") as out:
        proc = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, **kwargs)
    state_path(a.machine).unlink(missing_ok=True)
    write_state(
        a.machine,
        pid=proc.pid,
        pid_identity=pid_identity(proc.pid),
        runner=a.runner,
        started_at=iso(now()),
        argv=argv,
        log=str(log),
        slice_minutes=a.slice_minutes,
        heartbeat_at=iso(now()) if a.runner == "loop" else None,
    )
    time.sleep(1.0)
    live, detail = liveness(a.machine)
    finished = (read_state(a.machine) or {}).get("stop_reason")
    if live == "DEAD" and finished:
        print(f"FINISHED within a second: {finished}; log {log}")
        return 0
    print(f"{live}: {detail}; log {log}")
    return 0 if live == "ALIVE" else 1


def cmd_status(a: argparse.Namespace) -> int:
    live, detail = liveness(a.machine)
    st = read_state(a.machine) or {}
    print(f"{live}: {detail}")
    if st.get("last_tick"):
        print(f"last tick: {st['last_tick']}")
    if st.get("runner") == "night":
        print("note: legacy night.py runner (CONDITIONALLY_RELIABLE); no heartbeat, pid check only")
    if stop_requested(a.machine):
        print(f"stop requested via {stop_requested(a.machine)}")
    return 0 if live == "ALIVE" else 1


def cmd_stop(a: argparse.Namespace) -> int:
    RUNTIME.mkdir(exist_ok=True)
    (RUNTIME / f"STOP-{a.machine}").write_text(iso(now()) + "\n", encoding="utf-8")
    print(
        f"STOP-{a.machine} written; the loop stops before its next session. A running session finishes "
        f"or times out; delete the file to allow 'start' again."
    )
    return 0


def cmd_pick(a: argparse.Namespace) -> int:
    ctl.REMOTE = a.remote
    ctl.git_out("fetch", "-q", "origin", a.remote)
    picked = pick_work(ctl.load_ledger(), a.machine)
    print("nothing to do" if not picked else f"{picked[0]} {picked[1]['id']} {picked[1]['name']}")
    return 0 if picked else 2


def cmd_tick(a: argparse.Namespace) -> int:
    with tick_lock(a.machine) as got:
        if not got:
            print("busy: another tick is running")
            return 3
        status, detail = tick(a.machine, a.remote, a.slice_minutes, a.claude_arg, a.dry_run)
    print(f"{status}: {detail}")
    return 0 if status in {"idle", "claimed", "progress"} else 1


def cmd_schedule(a: argparse.Namespace) -> int:
    cmd = f"cd {ROOT} && python3 agents/launch.py tick --machine {a.machine}"
    print(
        f"cron (POSIX, persistent machine):\n  */{a.every} * * * * {cmd} >> .agent-runtime/tick-{a.machine}.log 2>&1"
    )
    print(
        f"\nWindows Task Scheduler:\n  schtasks /Create /SC MINUTE /MO {a.every} /TN archipelago-{a.machine} "
        f'/TR "python agents\\launch.py tick --machine {a.machine}"'
    )
    print(
        "\nClaude routine (ephemeral/cloud sessions; an agent can create this with its trigger tool):\n"
        f"  prompt: 'In the repo, run `python agents/launch.py tick --machine {a.machine}` and report its output. "
        "If it prints a progress/claimed line, run it again until it prints idle, stop, limit or error.'\n"
        f"  schedule: every {a.every} minutes (the platform minimum may be hourly)"
    )
    print(
        "\nThese are printed, not installed: installing a recurring job is a persistent change to the host."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--machine", required=True, choices=["A", "B"])
        sp.add_argument("--remote", default="main", help="ledger branch on origin (default main)")

    for name in ("pick", "status", "stop"):
        common(sub.add_parser(name))
    t = sub.add_parser("tick")
    common(t)
    t.add_argument("--slice-minutes", type=int, default=30)
    t.add_argument("--claude-arg", action="append", default=[])
    t.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("start")
    common(s)
    s.add_argument("--runner", choices=["loop", "night"], default="loop")
    s.add_argument("--hours", type=float, default=8.0)
    s.add_argument("--slice-minutes", type=int, default=30)
    s.add_argument("--max-ticks", type=int, default=40)
    s.add_argument("--claude-arg", action="append", default=[])
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--force", action="store_true")
    s.add_argument("rest", nargs=argparse.REMAINDER, help="after --, arguments for night.py")
    lp = sub.add_parser("_loop")
    common(lp)
    lp.add_argument("--hours", type=float, default=8.0)
    lp.add_argument("--slice-minutes", type=int, default=30)
    lp.add_argument("--max-ticks", type=int, default=40)
    lp.add_argument("--claude-arg", action="append", default=[])
    sc = sub.add_parser("schedule")
    common(sc)
    sc.add_argument("--every", type=int, default=30)
    a = p.parse_args(argv)
    if getattr(a, "rest", None) and a.rest[:1] == ["--"]:
        a.rest = a.rest[1:]
    try:
        if a.cmd == "_loop":
            return loop(a.machine, a.remote, a.hours, a.slice_minutes, a.max_ticks, a.claude_arg)
        handler = {
            "start": cmd_start,
            "status": cmd_status,
            "stop": cmd_stop,
            "pick": cmd_pick,
            "tick": cmd_tick,
            "schedule": cmd_schedule,
        }[a.cmd]
        return int(handler(a))
    except ctl.ControllerError as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

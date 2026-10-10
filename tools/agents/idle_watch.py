"""Keeps a machine's night runner alive indefinitely and publishes its branches.

Usage: python tools/agents/idle_watch.py A|B
Idles while no work is assigned, fast-forwards a clean main so the runner's guard passes,
and after every pass pushes (never force) local agent/<machine>/* branches so the other
machine's watcher can see progress. Never changes billing (subscription). Stops only on
.agent-runtime/STOP; failures back off and retry.
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MACHINE = sys.argv[1].upper() if len(sys.argv) > 1 else "B"
if MACHINE not in {"A", "B"}:
    sys.exit("usage: idle_watch.py A|B")
ROOT = Path(__file__).resolve().parents[2]
RT = ROOT / ".agent-runtime"
RT.mkdir(exist_ok=True)
LOG = RT / f"idle-watch-{MACHINE}.log"
IDLE_SECONDS = 180
BACKOFF = (180, 300, 600, 1200, 1800)  # failures back off but never end the loop
PIDFILE = RT / f"idle-watch-{MACHINE}.pid"


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def sync_main() -> None:
    """Fast-forward the clean main checkout so the runner's up-to-date-main guard passes."""
    git("fetch", "origin", "main")
    if git("status", "--porcelain").stdout.strip():
        return
    if git("branch", "--show-current").stdout.strip() != "main":
        return
    result = git("merge", "--ff-only", "origin/main")
    if result.returncode:
        log(f"ff-only merge failed: {result.stderr.strip()[:200]}")


def push_branches() -> None:
    """Publish local agent/<machine>/* branches; plain pushes only, failures are logged."""
    refs = git("for-each-ref", "--format=%(refname:short)", f"refs/heads/agent/{MACHINE}/").stdout
    for branch in refs.split():
        result = git("push", "-u", "origin", branch)
        if result.returncode:
            log(f"push {branch} failed: {result.stderr.strip()[-200:]}")
        elif "up-to-date" not in result.stderr and "up to date" not in result.stderr:
            log(f"pushed {branch}")


def pid_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
    return f" {pid} " in out


def single_instance() -> bool:
    if PIDFILE.exists():
        try:
            other = int(PIDFILE.read_text())
            if other != os.getpid() and pid_alive(other):
                return False
        except ValueError:
            pass
    PIDFILE.write_text(str(os.getpid()))
    return True


def sleep_interruptible(seconds: int) -> bool:
    for _ in range(seconds):
        if (RT / "STOP").exists():
            return False
        time.sleep(1)
    return True


if not single_instance():
    print("another idle watcher is already running")
    sys.exit(0)
failures = 0
log(f"idle watcher started (machine {MACHINE}, subscription)")
while not (RT / "STOP").exists():
    try:
        sync_main()
        proc = subprocess.run(
            [sys.executable, "tools/agents/night.py", "--machine", MACHINE,
             "--billing", "subscription", "--max-rounds", "10"],
            cwd=ROOT, capture_output=True, text=True,
        )
        out = (proc.stdout + proc.stderr).strip()
        if out:
            log("runner: " + out.replace(chr(10), " | ")[-600:])
        if proc.returncode == 0:
            failures = 0
            wait = IDLE_SECONDS
            log(f"runner exited 0; idling {wait}s for new assignments")
        elif "up-to-date main" in out:
            wait = 10  # main moved between sync and launch; resync immediately
            log("main moved; resyncing")
        else:
            failures += 1
            wait = BACKOFF[min(failures - 1, len(BACKOFF) - 1)]
            log(f"runner exited {proc.returncode} (failure {failures}); retrying in {wait}s")
    except Exception as error:  # the loop must survive anything
        failures += 1
        wait = BACKOFF[min(failures - 1, len(BACKOFF) - 1)]
        log(f"watcher error {error!r}; retrying in {wait}s")
    try:
        push_branches()
    except Exception as error:
        log(f"push sweep error {error!r}")
    if not sleep_interruptible(wait):
        break
log("idle watcher done (STOP file)")
PIDFILE.unlink(missing_ok=True)

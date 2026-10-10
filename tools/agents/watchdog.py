"""Restart an Archipelago driver that exits before its approved UTC deadline.

Run one watchdog per machine in a terminal or a host startup task. The watchdog
does not change assignments, billing, permissions, or the published run window.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / ".agent-runtime"
_LOCK_GUARD = threading.Lock()
_HELD_LOCKS: set[Path] = set()


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_deadline(value: str) -> datetime:
    deadline = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if deadline.tzinfo is None or deadline.utcoffset().total_seconds() != 0:
        raise ValueError("--until-utc must be a UTC timestamp, such as 2026-10-10T21:00:00Z")
    return deadline


def log(message: str) -> None:
    print(f"[watchdog {utc_now():%H:%M:%SZ}] {message}", flush=True)


@contextlib.contextmanager
def process_lock(name: str, runtime: Path | None = None):
    """An OS file lock is released even if its owning process crashes."""
    root = runtime if runtime is not None else RUNTIME
    root.mkdir(exist_ok=True)
    path = root / f"{name}.lock"
    with _LOCK_GUARD:
        if path in _HELD_LOCKS:
            raise RuntimeError(f"{name} is already running")
        _HELD_LOCKS.add(path)
    try:
        with path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as error:
                    raise RuntimeError(f"{name} is already running") from error
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                try:
                    fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    raise RuntimeError(f"{name} is already running") from error
                try:
                    yield
                finally:
                    fcntl.lockf(handle, fcntl.LOCK_UN)
    finally:
        with _LOCK_GUARD:
            _HELD_LOCKS.remove(path)


def write_status(machine: str, **fields: object) -> None:
    path = RUNTIME / f"watchdog-{machine}.json"
    value = {"machine": machine, "updated_at_utc": utc_now().isoformat(), **fields}
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def pause(seconds: float, deadline: datetime) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end and utc_now() < deadline and not (RUNTIME / "STOP").exists():
        time.sleep(max(0, min(5, end - time.monotonic())))


def supervise(machine: str, deadline: datetime, max_rounds: int) -> None:
    failures = 0
    while utc_now() < deadline and not (RUNTIME / "STOP").exists():
        command = [
            sys.executable,
            "tools/agents/driver.py",
            "--machine",
            machine,
            "--until-utc",
            deadline.isoformat().replace("+00:00", "Z"),
            "--max-rounds",
            str(max_rounds),
        ]
        started = time.monotonic()
        try:
            child = subprocess.Popen(command, cwd=ROOT)
            write_status(machine, state="running", driver_pid=child.pid, restarts=failures)
            log(f"started {machine} driver PID {child.pid}")
            code = child.wait()
        except OSError as error:
            code = -1
            log(f"could not start driver: {error}")
        if utc_now() >= deadline or (RUNTIME / "STOP").exists():
            break
        failures = 0 if time.monotonic() - started >= 600 else failures + 1
        delay = min(300, 15 * 2 ** min(failures - 1, 5))
        write_status(
            machine,
            state="retrying",
            last_exit_code=code,
            retry_in_seconds=delay,
            restarts=failures,
        )
        log(f"{machine} driver exited {code}; retrying in {delay}s")
        pause(delay, deadline)
    reason = "STOP file" if (RUNTIME / "STOP").exists() else "deadline"
    write_status(machine, state="stopped", reason=reason)
    log(f"{machine} watchdog stopped")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--machine", choices=["A", "B"], required=True)
    parser.add_argument("--until-utc", required=True)
    parser.add_argument("--max-rounds", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.max_rounds <= 10:
        parser.error("--max-rounds must be between 1 and 10")
    try:
        deadline = parse_deadline(args.until_utc)
        with process_lock(f"watchdog-{args.machine}"):
            supervise(args.machine, deadline, args.max_rounds)
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

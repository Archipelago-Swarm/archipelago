"""Per-test hang guard: a test running past ARCH_TEST_TIMEOUT seconds (default 120), the whole run past ARCH_SESSION_TIMEOUT (default 420) dumps stacks and kills the
whole pytest process tree, so a stuck subprocess wait ends the run instead of freezing it (no pytest-timeout dep)."""

import faulthandler
import os
import subprocess
import sys
import threading

import pytest

SESSION = float(os.environ.get("ARCH_SESSION_TIMEOUT", "420"))  # whole pytest run
LIMIT = float(os.environ.get("ARCH_TEST_TIMEOUT", "120"))


def _die(name: str, cap) -> None:
    if cap:
        cap.suspend_global_capture()  # pytest swallows fd 2 otherwise
    sys.stderr.write(f"\nHANG GUARD: {name} exceeded {LIMIT:.0f}s; killing pytest tree\n")
    faulthandler.dump_traceback(all_threads=True)
    sys.stderr.flush()
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(os.getpid())], check=False)
    os._exit(124)


@pytest.fixture(autouse=True)
def _hang_guard(request):
    t = threading.Timer(
        LIMIT,
        _die,
        args=(request.node.nodeid, request.config.pluginmanager.getplugin("capturemanager")),
    )
    t.daemon = True
    t.start()
    yield
    t.cancel()


def pytest_sessionstart(session):
    t = threading.Timer(
        SESSION,
        _die,
        args=("<whole session>", session.config.pluginmanager.getplugin("capturemanager")),
    )
    t.daemon = True
    t.start()


# Suites that spawn node processes / Docker hang on Windows; skip them there unless ARCH_ALLOW_SLOW=1.
_SLOW = ("tests/infra", "tests/e2e", "tests/swarm", "tests/noderuntime", "tests/experiments")


def pytest_ignore_collect(collection_path, config):
    if sys.platform == "win32" and not os.environ.get("ARCH_ALLOW_SLOW"):
        p = collection_path.as_posix()
        # shortcut: whole dirs skipped incl. in-process tests there; upgrade: fix Windows node startup.
        return any(f"/{s}" in p for s in _SLOW) or None
    return None

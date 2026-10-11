"""Per-test hang guard: a test running past ARCH_TEST_TIMEOUT seconds (default 120), the whole run past ARCH_SESSION_TIMEOUT (default 900) dumps stacks and kills the
whole pytest process tree, so a stuck subprocess wait ends the run instead of freezing it (no pytest-timeout dep)."""
import faulthandler
import os
import subprocess
import sys
import threading

import pytest

SESSION = float(os.environ.get("ARCH_SESSION_TIMEOUT", "900"))  # whole pytest run
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
    t = threading.Timer(LIMIT, _die, args=(request.node.nodeid, request.config.pluginmanager.getplugin("capturemanager")))
    t.daemon = True
    t.start()
    yield
    t.cancel()


def pytest_sessionstart(session):
    t = threading.Timer(SESSION, _die, args=("<whole session>", session.config.pluginmanager.getplugin("capturemanager")))
    t.daemon = True
    t.start()

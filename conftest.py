"""Per-test hang guard: a test running past ARCH_TEST_TIMEOUT seconds (default 120) dumps stacks and kills the
whole pytest process tree, so a stuck subprocess wait ends the run instead of freezing it (no pytest-timeout dep)."""
import faulthandler
import os
import subprocess
import sys
import threading

import pytest

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

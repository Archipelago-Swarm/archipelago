"""Skip tests that need a running Docker daemon when only the CLI (or nothing) is present."""

import shutil
import subprocess

import pytest

NEEDS_DAEMON = {"test_api_image.py", "test_four_nodes.py", "test_runtime_ports.py"}


def _daemon_up() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def pytest_collection_modifyitems(config, items):
    if _daemon_up():
        return
    skip = pytest.mark.skip(reason="Docker daemon not reachable")
    for item in items:
        if item.path.name in NEEDS_DAEMON:
            item.add_marker(skip)

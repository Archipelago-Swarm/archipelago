"""Starts the four node containers and checks each keeps its own checkpoint across a restart."""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not shutil.which("docker"), reason="docker not installed")
ENV = {**os.environ, "ARCHIPELAGO_API_TOKEN": "x" * 32, "GRAFANA_ADMIN_PASSWORD": "x" * 16}
NODES = ["node-01", "node-02", "node-03", "node-04"]
BASE = ["docker", "compose", "-p", "archi-t10-nodes", "-f", str(ROOT / "infra/compose/compose.yml")]
BASE += ["--env-file", str(ROOT / "infra/compose/.env.example"), "--profile", "local"]


def compose(*args, check=True):
    return subprocess.run(BASE + list(args), env=ENV, check=check, capture_output=True, text=True)


def wait_boots(want, timeout=60):
    """Polls every node's checkpoint until all report `want` boots (restart rewrites it)."""
    end = time.time() + timeout
    got = []
    while time.time() < end:
        got = []
        for n in NODES:
            r = compose("exec", "-T", n, "cat", "/node-data/checkpoint.json", check=False)
            got.append(json.loads(r.stdout)["boots"] if r.returncode == 0 and r.stdout else None)
        if got == [want] * len(NODES):
            return got
        time.sleep(2)
    return got


@pytest.fixture(scope="module")
def nodes():
    compose("up", "-d", "--build", *NODES)
    yield
    compose("down", "-v")


def test_four_nodes_keep_checkpoints_across_restart(nodes):
    assert wait_boots(1) == [1] * 4
    compose("restart", *NODES)
    assert wait_boots(2) == [2] * 4

# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""Docker tier: the four node-runtime containers come up healthy, each keeps its own checkpoint, and a
restarted node comes back ready with its checkpoint generation preserved."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.docker
ENV = {**os.environ, "SITE_ADDRESS": "localhost"}
NODES = ["node-01", "node-02", "node-03", "node-04"]
BASE = ["docker", "compose", "-p", "archi-t42-nodes", "-f", str(ROOT / "infra/compose/compose.yml")]
BASE += ["--env-file", str(ROOT / "infra/compose/.env.example")]
BASE += ["--env-file", str(ROOT / "infra/compose/local.env"), "--profile", "local"]
# Runs inside the container: the token and port come from its own environment.
PROBE = (
    "import json,os,urllib.request as u;"
    "r=u.Request('http://127.0.0.1:8080%s',data=%s,headers={'Authorization':'Bearer '+os.environ['NODE_CONTROL_TOKEN'],"
    "'Content-Type':'application/json'});print(u.urlopen(r,timeout=3).read().decode())"
)


def compose(*args, check=True):
    return subprocess.run(BASE + list(args), env=ENV, check=check, capture_output=True, text=True)


def node_call(node, path, body=None):
    code = PROBE % (path, "None" if body is None else repr(json.dumps(body).encode()))
    return json.loads(compose("exec", "-T", node, "python", "-c", code).stdout)


def wait_ready(timeout=90):
    end, last = time.time() + timeout, {}
    while time.time() < end:
        try:
            last = {n: node_call(n, "/v1/status") for n in NODES}
            if all(s.get("ready") for s in last.values()):
                return last
        except subprocess.CalledProcessError:
            pass
        time.sleep(2)
    raise AssertionError(f"nodes not ready: {last}")


@pytest.fixture(scope="module")
def nodes():
    compose("up", "-d", "--build", "--no-deps", *NODES)
    try:
        yield
    finally:
        compose("down", "-v", check=False)


def test_four_nodes_are_ready_and_keep_checkpoints_across_restart(nodes):
    status = wait_ready()
    assert {s["backend"] for s in status.values()} == {"torch-cpu"}
    for n in NODES:
        node_call(n, "/v1/control", {"command": "checkpoint", "run_id": "docker-four-nodes"})
    before = {n: node_call(n, "/v1/status")["checkpoint_generation"] for n in NODES}
    assert all(g is not None and g >= 0 for g in before.values())
    compose("restart", *NODES)
    after = wait_ready()
    for n in NODES:
        assert after[n]["checkpoint_generation"] >= before[n], n

# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""Docker tier: `make demo` end to end with the smoke plan (CI, or any host with a Docker daemon).

Builds the images, brings up the local profile, runs the smoke plan to completion through the API and
asserts on the produced artifacts: every node performed optimizer updates, the cut happened, files parse.
Cannot run without a daemon; the offline parts (artifact generation, driver, plans, compose) are covered by
test_demo_artifacts, test_run_demo, test_plans and test_compose.
"""

import csv
import json
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra/demo"))

import run_demo  # noqa: E402

pytestmark = pytest.mark.docker
NODES = [f"node-0{i}" for i in range(1, 5)]


def free_port() -> str:
    """A free host port for the proxy: never skip because 80 is taken, just use another."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return str(s.getsockname()[1])


@pytest.fixture(scope="module")
def stack(request, tmp_path_factory):
    run_demo.PROJECT = "archipelago-e2e"
    out = tmp_path_factory.mktemp("demo-artifacts")
    port = free_port()
    commit = run_demo.git_commit()
    env = run_demo.compose_env("smoke", commit)
    env["PROXY_HTTP_PORT"] = port
    failed_before = request.session.testsfailed
    ctx = {"env": env, "port": port, "out": out, "commit": commit}
    try:
        run_demo.compose(env, "up", "-d", "--build", "--wait", "--wait-timeout", "600")
        api = run_demo.api_from_env(port)
        api.wait_ready(300)
        ctx["api"] = api
        yield ctx
    finally:
        # Teardown must not mask the test's own failure: save logs when anything failed, then always try
        # to bring the stack down and only warn if that fails.
        if request.session.testsfailed > failed_before or "api" not in ctx:
            run_demo.save_logs(env, out / "logs")
            tail = (out / "logs/compose.log").read_text().splitlines()[-200:]
            print("\n".join(tail), file=sys.stderr)
        down = run_demo.compose(env, "down", "-v", "--remove-orphans", check=False)
        if down.returncode != 0:
            print(f"compose down exited {down.returncode}", file=sys.stderr)


@pytest.fixture(scope="module")
def result(stack):
    return run_demo.run_and_collect(
        stack["api"], "smoke", stack["out"], commit=stack["commit"],
        image_digests=run_demo.image_digests(), poll_interval=2.0,
    )  # fmt: skip


def test_run_completed_and_every_artifact_exists_and_parses(result):
    for name in ("summary.json", "topology_snapshots.json", "node_timeline.json", "run.json"):
        json.loads((result / name).read_text())
    for name in ("curves.csv", "peer_decisions.csv"):
        rows = list(csv.reader((result / name).open()))
        assert len(rows) >= 2, f"{name} has no data rows"
    for name in ("learning_curve.svg", "coverage_return.svg", "partition_timeline.svg"):
        assert ET.parse(result / name).getroot().tag.endswith("svg")
    assert json.loads((result / "run.json").read_text())["view"]["status"] == "completed"


def test_every_node_performed_optimizer_updates(result):
    s = json.loads((result / "summary.json").read_text())
    assert sorted(s["nodes"]) == NODES
    for n in NODES:
        assert s["nodes"][n]["update_count"] > 0, f"{n} never updated its optimizer"
    assert s["commit"] and s["image_digests"].get("archipelago/node")
    assert s["seeds"]["env"] == 101


def test_the_cut_window_happened_and_cut_links_carried_no_offers(result):
    snaps = json.loads((result / "topology_snapshots.json").read_text())
    partition = [x for x in snaps if x["phase"] == "partition"]
    assert partition, "no snapshot taken during the fault window"
    full = max(len(x["links"]) for x in snaps)
    assert all(len(x["links"]) < full for x in partition)
    s = json.loads((result / "summary.json").read_text())
    assert s["peer"]["offers_over_cut_links"] == 0


def test_only_the_proxy_publishes_a_host_port(stack):
    out = subprocess.run(
        run_demo.compose_cmd("ps", "--format", "json"), env=stack["env"], cwd=ROOT,
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    for line in filter(None, out.splitlines()):
        svc = json.loads(line)
        published = [p for p in svc.get("Publishers") or [] if p.get("PublishedPort")]
        assert (svc["Service"] == "proxy") == bool(published), svc["Service"]

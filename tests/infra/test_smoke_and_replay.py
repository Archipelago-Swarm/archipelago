"""T10 acceptance check 4: smoke.sh passes on the real stack and run state survives an api restart.

Specified behaviour (agents/architecture/interfaces.md, services/api runs.py): run METADATA
(status, revision, completion reason, tick) is persisted in /data/runs.json and each run's events
in an append-only JSON Lines file under /data/events. After a restart a finished run keeps its
terminal status AND its replay (`GET /v1/runs/{id}/events` returns exactly the events captured
before the restart), and a run that was active is reported honestly as `interrupted`.
"""

import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra/demo"))

import run_demo  # noqa: E402

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not shutil.which("docker"), reason="docker not installed"),
]
TOKEN = "t" * 32
ENV = {
    **os.environ,
    "ARCHIPELAGO_API_TOKEN": TOKEN,
    "GRAFANA_ADMIN_PASSWORD": "x" * 16,
    "SITE_ADDRESS": "localhost",  # local.env uses plain http for make demo; these tests probe TLS
    "ARCHIPELAGO_COOKIE_SECURE": "true",
}
BASE = "https://localhost"
CTX = ssl._create_unverified_context()  # Caddy internal CA for localhost


def compose(*args: str) -> str:
    cmd = [
        "docker",
        "compose",
        "-p",
        "archi-t10-smoke",
        "-f",
        str(ROOT / "infra/compose/compose.yml"),
        "--env-file",
        str(ROOT / "infra/compose/.env.example"),
        "--env-file",
        str(ROOT / "infra/compose/local.env"),
        "--profile",
        "local",
        *args,
    ]
    return subprocess.run(cmd, env=ENV, check=True, capture_output=True, text=True).stdout


def is_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def call(method: str, path: str, body: Any = None, headers: dict[str, str] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(req, timeout=10, context=CTX) as r:
        return json.loads(r.read())


def wait_ready(timeout: float = 90) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            call("GET", "/readyz")
            return
        except OSError:  # URLError/HTTPError (502 while api restarts), refused, TLS not ready
            time.sleep(2)
    raise AssertionError("stack did not become ready")


def wait_grafana(timeout: float = 120) -> None:
    """Grafana starts slower than the api; the smoke check needs it reachable through the proxy.

    If it never answers, fail with Grafana's own logs so the real cause is visible.
    """
    end = time.time() + timeout
    while time.time() < end:
        try:
            req = urllib.request.Request(BASE + "/grafana/api/health")
            with urllib.request.urlopen(req, timeout=5, context=CTX) as r:
                if r.status == 200:
                    return
        except OSError:
            pass
        time.sleep(3)
    logs = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            "archi-t10-smoke",
            "logs",
            "--no-color",
            "--tail=60",
            "grafana",
        ],
        env=ENV,
        capture_output=True,
        text=True,
    )
    raise AssertionError("grafana never became reachable via the proxy:\n" + logs.stdout[-5000:])


def new_run(run_id: str) -> dict[str, Any]:
    # The live coordinator needs one pose per plan node: use the demo driver config.
    cfg = run_demo.build_run_config("smoke", run_demo.load_plan("smoke"), run_id)
    # Live mode: the Plan is the mounted server-side file (one raw plan is "default", A9).
    return call("POST", "/v1/runs", cfg, {"Idempotency-Key": f"key-{run_id}"})


def wait_status(run_id: str, want: str, timeout: float = 60) -> dict[str, Any]:
    """Live mode: lifecycle commands are relayed to the coordinator and settle asynchronously."""
    end, view = time.time() + timeout, {}
    while time.time() < end:
        view = call("GET", f"/v1/runs/{run_id}")
        if view["status"] == want:
            return view
        time.sleep(1)
    raise AssertionError(f"run {run_id} never reached {want}: {view}")


    """Wait until a finished run's event log stops growing (node shippers flush on their own)."""
    """Wait until a finished run's event log stops growing (node shippers flush on their own clock)."""
    end, last, since = time.time() + timeout, None, time.time()
    while time.time() < end:
        n = call("GET", f"/v1/runs/{run_id}/events?limit=500")["latest_sequence"]
        if n != last:
            last, since = n, time.time()
        elif time.time() - since >= quiet:
            return
        time.sleep(1)
    raise AssertionError(f"event log of {run_id} never settled (latest_sequence {last})")


def stop(run: dict[str, Any]) -> dict[str, Any]:
    body = {
        "command_id": f"stop-{run['run_id']}",
        "command": "stop",
        "expected_revision": run["revision"],
    }
    return call("POST", f"/v1/runs/{run['run_id']}/commands", body)


@pytest.fixture(scope="module")
def stack():
    # No port-in-use skip: if 80/443 are taken, `up` must fail loudly.
    try:
        compose("up", "-d", "--build", "proxy", "web", "api", "grafana")
        wait_ready()
        wait_grafana()
        yield
    except BaseException:
        # Surface the real cause (logs) before teardown, and never let teardown mask it.
        logs = subprocess.run(
            ["docker", "compose", "-p", "archi-t10-smoke", "logs", "--no-color", "--tail=80"],
            env=ENV,
            capture_output=True,
            text=True,
        )
        print(logs.stdout[-6000:], logs.stderr[-2000:])
        raise
    finally:
        subprocess.run(
            ["docker", "compose", "-p", "archi-t10-smoke", "down", "-v"],
            env=ENV,
            capture_output=True,
            text=True,
        )


def test_smoke_script_passes_and_run_state_survives_api_restart(stack):
    smoke = subprocess.run(
        ["bash", str(ROOT / "infra/scripts/smoke.sh")],
        env={**ENV, "BASE_URL": BASE, "API_TOKEN": TOKEN, "SMOKE_CURL_OPTS": "-k"},
        capture_output=True,
        text=True,
    )
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr

    # A run that finishes: stopped explicitly so the test does not depend on tick timing.
    new_run("run-t10-done")
    stop(
        wait_status("run-t10-done", "running")
    )  # stop with the latest revision, not the create view
    done = wait_status("run-t10-done", "completed")
    assert done["status"] == "completed" and done["completion_reason"] == "stopped"
    settle_events("run-t10-done")  # node telemetry keeps shipping after the run ends
    before = call("GET", "/v1/runs/run-t10-done/events?limit=500")
    seqs = [e["sequence"] for e in before["events"]]
    assert seqs and seqs == sorted(seqs), "a finished run must have ordered events"

    # A run still active when the api container restarts (capacity is 1, so after the first ended).
    new_run("run-t10-live")
    live = wait_status("run-t10-live", "running")
    call(
        "POST",
        "/v1/runs/run-t10-live/commands",
        {"command_id": "pause-live", "command": "pause", "expected_revision": live["revision"]},
    )
    paused = wait_status(
        "run-t10-live", "paused"
    )  # pause keeps the run active without depending on timing
    assert paused["status"] == "paused"

    compose("restart", "api")
    wait_ready()

    # Finished run: terminal state is retained exactly.
    after_done = call("GET", "/v1/runs/run-t10-done")
    assert after_done["status"] == "completed"
    assert after_done["completion_reason"] == "stopped"
    assert after_done["tick"] == done["tick"]

    # Active run: reported as interrupted, never as running or completed.
    after_live = call("GET", "/v1/runs/run-t10-live")
    assert after_live["status"] == "interrupted"
    # `docker compose restart` sends SIGTERM, so the graceful shutdown path (not crash recovery)
    # is what marks it.
    assert after_live["completion_reason"] == "process_shutdown"

    # Replay of a finished run is durable: identical events, in order, same latest sequence.
    replay = call("GET", "/v1/runs/run-t10-done/events?limit=500")
    assert [e["sequence"] for e in replay["events"]] == seqs
    assert replay["events"] == before["events"]
    assert replay["latest_sequence"] == before["latest_sequence"]
    assert replay["oldest_sequence"] == before["oldest_sequence"]

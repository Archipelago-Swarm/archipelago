"""T10 acceptance check 4: smoke.sh passes on the real stack and run state survives an api restart.

Specified behaviour (agents/architecture/interfaces.md, services/api runs.py): only run METADATA
(status, revision, completion reason, tick) is persisted in /data/runs.json. Events are held in
memory and are NOT recovered. After a restart a finished run keeps its terminal status, a run that
was active is reported honestly as `interrupted`, and the events endpoint must not invent events.
Known gap: the event log (replay) itself is lost on restart until T08 persists it; the test asserts
the honest behaviour and does not pretend otherwise.
"""

import json
import os
import shutil
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not shutil.which("docker"), reason="docker not installed")
TOKEN = "t" * 32
ENV = {**os.environ, "ARCHIPELAGO_API_TOKEN": TOKEN, "GRAFANA_ADMIN_PASSWORD": "x" * 16}
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


def new_run(run_id: str) -> dict[str, Any]:
    cfg = json.loads((ROOT / "packages/contracts/fixtures/good/run_config.json").read_text())
    cfg["run_id"] = run_id
    return call("POST", "/v1/runs", cfg, {"Idempotency-Key": f"key-{run_id}"})


def stop(run: dict[str, Any]) -> dict[str, Any]:
    body = {
        "command_id": f"stop-{run['run_id']}",
        "command": "stop",
        "expected_revision": run["revision"],
    }
    return call("POST", f"/v1/runs/{run['run_id']}/commands", body)


@pytest.fixture(scope="module")
def stack():
    if is_open(80) or is_open(443):
        pytest.skip("host ports 80/443 already in use")
    try:
        compose("up", "-d", "--build", "proxy", "web", "api", "grafana")
        wait_ready()
        yield
    finally:
        compose("down", "-v")


def test_smoke_script_passes_and_run_state_survives_api_restart(stack):
    smoke = subprocess.run(
        ["bash", str(ROOT / "infra/scripts/smoke.sh")],
        env={**ENV, "BASE_URL": BASE, "API_TOKEN": TOKEN, "SMOKE_CURL_OPTS": "-k"},
        capture_output=True,
        text=True,
    )
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr

    # A run that finishes: stopped explicitly so the test does not depend on tick timing.
    done = stop(new_run("run-t10-done"))
    assert done["status"] == "completed" and done["completion_reason"] == "stopped"
    before = call("GET", "/v1/runs/run-t10-done/events?limit=500")
    seqs = [e["sequence"] for e in before["events"]]
    assert seqs and seqs == sorted(seqs), "a finished run must have ordered events"

    # A run still active when the api container restarts (capacity is 1, so after the first ended).
    live = new_run("run-t10-live")
    assert live["status"] == "running"

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
    assert after_live["completion_reason"] in {"process_restart", "process_shutdown"}

    # Events are not persisted today (gap, see module docstring). The API must stay honest: it may
    # return a prefix of what was recorded, but never events that were not emitted before restart.
    replay = call("GET", "/v1/runs/run-t10-done/events?limit=500")
    assert {e["sequence"] for e in replay["events"]} <= set(seqs)
    assert replay["latest_sequence"] <= before["latest_sequence"]

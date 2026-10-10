"""Starts the real stack (proxy, web, api, timescaledb) and probes it from the host."""

import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not shutil.which("docker"), reason="docker not installed")
ENV = {**os.environ, "ARCHIPELAGO_API_TOKEN": "x" * 32, "GRAFANA_ADMIN_PASSWORD": "x" * 16}


def compose(*args):
    cmd = [
        "docker",
        "compose",
        "-p",
        "archi-t10-rt",
        "-f",
        str(ROOT / "infra/compose/compose.yml"),
        "--env-file",
        str(ROOT / "infra/compose/.env.example"),
        "--profile",
        "local",
        *args,
    ]
    return subprocess.run(cmd, env=ENV, check=True, capture_output=True, text=True).stdout


def is_open(port):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def healthy(timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            # http redirects to https (self-signed locally); redirect or 200 proves api+proxy up.
            req = urllib.request.build_opener(NoRedirect).open(
                "http://127.0.0.1/healthz", timeout=3
            )
            return req.status
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 307, 308):
                return e.code
        except OSError:
            pass
        time.sleep(2)
    return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


@pytest.fixture(scope="module")
def stack():
    if is_open(80) or is_open(443):
        pytest.skip("host ports 80/443 already in use")
    compose("up", "-d", "--build", "proxy", "web", "api", "timescaledb")
    yield
    compose("down", "-v")


def test_only_proxy_ports_open_and_restart_recovers(stack):
    assert healthy() is not None
    assert is_open(80) and is_open(443)
    assert not any(is_open(p) for p in (5432, 8000, 9000, 3000))
    compose("restart", "api")
    assert healthy() is not None

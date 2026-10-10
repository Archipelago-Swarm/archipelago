"""Builds the real API image, runs it, and checks anonymous requests are rejected."""

import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not shutil.which("docker"), reason="docker not installed")
NAME = "archipelago-api-image-test"
PORT = 18765


def status(method, path):
    data = b"{}" if method == "POST" else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method=method, data=data)
    req.add_header("content-type", "application/json")
    try:
        return urllib.request.urlopen(req, timeout=3).status
    except urllib.error.HTTPError as e:
        return e.code


def test_api_image_builds_and_rejects_anonymous():
    docker = ["docker"]
    build = ["build", "-q", "-f", "infra/docker/api.Dockerfile", "-t", NAME, "."]
    subprocess.run(docker + build, cwd=ROOT, check=True)
    subprocess.run(docker + ["rm", "-f", NAME], capture_output=True)
    subprocess.run(
        docker
        + ["run", "-d", "--name", NAME, "-e", "ARCHIPELAGO_API_TOKEN=0123456789abcdef0123"]
        + ["-p", f"127.0.0.1:{PORT}:8000", NAME],
        check=True,
        capture_output=True,
    )
    try:
        for _ in range(30):
            try:
                if status("GET", "/healthz") == 200:
                    break
            except OSError:
                pass
            time.sleep(1)
        else:
            pytest.fail("api never became healthy")
        assert status("GET", "/healthz") == 200
        for method, path in [
            ("POST", "/v1/runs"),
            ("POST", "/v1/runs/x/commands"),
            ("GET", "/v1/runs/x"),
            ("GET", "/v1/runs/x/events"),
        ]:
            assert status(method, path) == 401, (method, path)
    finally:
        subprocess.run(docker + ["rm", "-f", NAME], capture_output=True)

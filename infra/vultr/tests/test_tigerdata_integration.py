"""Real TimescaleDB role checks. CI-only: skipped unless a Docker daemon is reachable."""

import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator

import pytest
from archipelago_ops import tigerdata


def _docker_up() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


psycopg = pytest.importorskip("psycopg")
pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not _docker_up(), reason="Docker daemon not reachable"),
]


@pytest.fixture(scope="module")
def urls() -> Iterator[dict[str, str]]:
    name = f"arch-ops-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-e",
            "POSTGRES_PASSWORD=pw",
            "-p",
            "127.0.0.1::5432",
            "timescale/timescaledb:2.17.2-pg16",
        ],
        check=True,
        capture_output=True,
    )
    try:
        out = subprocess.run(["docker", "port", name, "5432"], capture_output=True, text=True)
        port = out.stdout.split(":")[-1].strip()
        admin = f"postgresql://postgres:pw@127.0.0.1:{port}/postgres"
        for _ in range(60):
            try:
                psycopg.connect(admin, connect_timeout=2).close()
                break
            except Exception:
                time.sleep(1)
        yield {"TIGERDATA_ADMIN_URL": admin, "port": port}
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def test_real_roles(urls: dict[str, str]) -> None:
    port = urls["port"]
    admin_url = urls["TIGERDATA_ADMIN_URL"]
    tigerdata.run_checks({"TIGERDATA_URL": admin_url}, tigerdata.default_connect)  # migrate first
    with psycopg.connect(admin_url, autocommit=True) as c:
        c.execute("CREATE ROLE ops_w LOGIN PASSWORD 'w' IN ROLE archipelago_writer")
        c.execute("CREATE ROLE ops_r LOGIN PASSWORD 'r' IN ROLE archipelago_reader")
    env = {
        "TIGERDATA_URL": f"postgresql://ops_w:w@127.0.0.1:{port}/postgres",
        "TIGERDATA_READER_URL": f"postgresql://ops_r:r@127.0.0.1:{port}/postgres",
        "TIGERDATA_ADMIN_URL": admin_url,
    }
    rep = tigerdata.run_checks(env, tigerdata.default_connect)
    assert rep["ok"], rep

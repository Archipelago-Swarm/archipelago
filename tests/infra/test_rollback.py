"""Rollback script: refusal paths and command shape run anywhere (fake docker);
the real image switch needs a Docker daemon (T10 acceptance check 5)."""

import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/scripts/rollback.sh"
COMPOSE_FILE = str(ROOT / "infra/compose/compose.yml")
ENV_FILE = str(ROOT / "infra/compose/.env.example")
PROJECT = "archi-t10-rollback"
ENV = {**os.environ, "ARCHIPELAGO_API_TOKEN": "x" * 32, "GRAFANA_ADMIN_PASSWORD": "x" * 16}


def run(*args, env=None):
    return subprocess.run(
        ["bash", str(SCRIPT), *args], env=env or ENV, capture_output=True, text=True
    )


@pytest.fixture
def fake_docker(tmp_path):
    """A docker stand-in on PATH that logs calls; images listed in $FAKE_IMAGES exist."""
    log = tmp_path / "calls.log"
    exe = tmp_path / "bin" / "docker"
    exe.parent.mkdir()
    exe.write_text(
        "#!/usr/bin/env bash\n"
        'echo "IMAGE_TAG=${IMAGE_TAG:-} $*" >> "$FAKE_LOG"\n'
        'if [[ "$1 $2" == "image inspect" ]]; then\n'
        '  [[ " $FAKE_IMAGES " == *" $3 "* ]]; exit $?\n'
        "fi\n"
        "exit 0\n"
    )
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    env = {**ENV, "PATH": f"{exe.parent}:{ENV['PATH']}", "FAKE_LOG": str(log)}
    return env, log


@pytest.mark.parametrize(
    "args", [(), ("v2",), ("", "v1"), ("v2", ""), ("v1", "v1"), ("a", "b", "c")]
)
def test_refuses_without_both_distinct_tags(args, fake_docker):
    env, log = fake_docker
    r = run(*args, env=env)
    assert r.returncode == 2  # usage / invalid-argument refusal
    assert "->" not in r.stdout
    assert not log.exists(), "docker must not be invoked when arguments are refused"


def test_refuses_invalid_tag(fake_docker):
    env, log = fake_docker
    assert run("v2", "bad tag;rm", env=env).returncode == 2
    assert not log.exists()


def images(tag):
    return " ".join(f"archipelago/{n}:{tag}" for n in ("web", "api", "node"))


def test_refuses_when_previous_image_missing_and_changes_nothing(fake_docker):
    env, log = fake_docker
    env["FAKE_IMAGES"] = "archipelago/api:v1 archipelago/web:v1"  # node:v1 missing
    r = run("v2", "v1", env=env)
    assert r.returncode == 1  # missing-image refusal, distinct from usage errors (2)
    assert "node:v1" in r.stderr
    assert not any(" up " in f" {ln} " for ln in log.read_text().splitlines())


def test_switches_tag_without_destructive_commands(fake_docker, tmp_path):
    env, log = fake_docker
    env["FAKE_IMAGES"] = images("v1")
    envfile = tmp_path / "compose.env"
    envfile.write_text("IMAGE_TAG=v2\nOTHER=keep\n")
    env["COMPOSE_ENV_FILE"] = str(envfile)
    for _ in range(2):  # idempotent: a second run behaves the same
        r = run("v2", "v1", env=env)
        assert r.returncode == 0, r.stderr
        assert "v2 -> v1" in r.stdout
    assert envfile.read_text() == "IMAGE_TAG=v1\nOTHER=keep\n"  # tag persisted, rest untouched
    lines = log.read_text().splitlines()
    ups = [ln for ln in lines if " up " in ln]
    assert len(ups) == 2
    for ln in ups:
        assert ln.startswith("IMAGE_TAG=v1 ")
        assert "--no-build" in ln and "--no-deps" in ln
    joined = "\n".join(lines)
    for bad in (" down", " -v", "volume rm", "volume prune", "system prune", "image rm", "rmi"):
        assert bad not in joined


# ---- real Docker half: UNVERIFIED locally (no daemon in the authoring sandbox) ----
needs_docker = pytest.mark.skipif(not shutil.which("docker"), reason="docker not installed")


def compose(*args, env=None):
    cmd = ["docker", "compose", "-p", PROJECT, "-f", COMPOSE_FILE, "--env-file", ENV_FILE, *args]
    return subprocess.run(cmd, env=env or ENV, check=True, capture_output=True, text=True).stdout


def api_container_state():
    cid = compose("ps", "-q", "api").strip()
    assert cid
    fmt = "{{.Config.Image}}|{{range .Mounts}}{{.Name}}:{{.Destination}};{{end}}"
    out = subprocess.run(
        ["docker", "inspect", "-f", fmt, cid], check=True, capture_output=True, text=True
    ).stdout.strip()
    image, mounts = out.split("|", 1)
    return image, sorted(m for m in mounts.split(";") if m)


def build_tag(tag):
    # A distinct label per tag makes the two api images genuinely different images.
    for img in ("api", "web", "node"):
        subprocess.run(
            [
                "docker", "build", "-q", "--label", f"archi.test.tag={tag}",
                "-t", f"archipelago/{img}:{tag}",
                "-f", str(ROOT / f"infra/docker/{img}.Dockerfile"), str(ROOT),
            ],
            check=True,
            capture_output=True,
            text=True,
        )  # fmt: skip


@needs_docker
def test_rollback_to_previous_image_keeps_volumes(tmp_path):
    envfile = tmp_path / "compose.env"
    shutil.copy(ENV_FILE, envfile)  # the script rewrites IMAGE_TAG; never touch the tracked file
    try:
        build_tag("v1")
        build_tag("v2")
        compose("up", "-d", "--no-build", "--no-deps", "api", env={**ENV, "IMAGE_TAG": "v2"})
        time.sleep(3)
        image_before, mounts_before = api_container_state()
        assert image_before == "archipelago/api:v2"

        env = {
            **ENV,
            "COMPOSE_PROJECT": PROJECT,
            "COMPOSE_ENV_FILE": str(envfile),
            "ROLLBACK_SERVICES": "api",
        }
        r = run("v2", "v1", env=env)
        assert r.returncode == 0, r.stderr
        time.sleep(3)
        image_after, mounts_after = api_container_state()
        assert image_after == "archipelago/api:v1"
        assert mounts_after == mounts_before and mounts_after
    finally:
        subprocess.run(  # test-owned project only; check=False so cleanup never masks the failure
            ["docker", "compose", "-p", PROJECT, "-f", COMPOSE_FILE, "--env-file", ENV_FILE]
            + ["down", "-v"],
            env=ENV,
            capture_output=True,
        )
        for tag in ("v1", "v2"):
            subprocess.run(
                [
                    "docker",
                    "rmi",
                    "-f",
                    *[f"archipelago/{n}:{tag}" for n in ("web", "api", "node")],
                ],
                capture_output=True,
            )

"""Static checks of the node and coordinator Dockerfiles (no build, no daemon needed)."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NODE = (ROOT / "infra/docker/node.Dockerfile").read_text()
COORD = (ROOT / "infra/docker/coordinator.Dockerfile").read_text()


def copies(text):
    return {m.group(1) for m in re.finditer(r"^COPY (?!--from)(\S+) ", text, re.M)}


def locked(name):
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    return next(p["version"] for p in lock["package"] if p["name"] == name)


def pins(text):
    return dict(re.findall(r'"([A-Za-z0-9_.-]+)==([0-9][^"]*)"', text))


def test_node_torch_pin_matches_the_dependency_group_and_cpu_backend():
    group = tomllib.loads((ROOT / "pyproject.toml").read_text())["dependency-groups"]["torch"]
    assert group == [f"torch=={pins(NODE)['torch']}"]
    assert "--torch-backend cpu" in NODE
    assert "torch" not in pins(COORD) and "torch" not in COORD.replace("No torch", "")


def test_pure_dependency_pins_match_uv_lock():
    for text in (NODE, COORD):
        for name, version in pins(text).items():
            assert locked(name) == version, f"{name} pin differs from uv.lock"


def test_node_image_copies_only_what_the_node_needs():
    assert copies(NODE) == {
        "packages/contracts", "packages/learning", "packages/sim", "packages/node/peer",
        "packages/node/learner", "packages/node/runtime", "packages/transport",
    }  # fmt: skip
    assert not re.search(r"COPY (services|apps|infra|experiments|packages/storage)", NODE)


def test_coordinator_image_copies_only_what_it_needs():
    assert copies(COORD) == {
        "packages/contracts", "packages/sim", "packages/adapters/sim2d", "services/coordinator",
    }  # fmt: skip


def test_node_image_is_nonroot_single_threaded_and_runs_the_runtime():
    assert "FROM python:3.12-slim" in NODE
    assert re.search(r"^USER node$", NODE, re.M)
    assert "OMP_NUM_THREADS=1" in NODE and "MKL_NUM_THREADS=1" in NODE
    assert 'ENTRYPOINT ["python", "-m", "archipelago_noderuntime"]' in NODE
    assert "CONTROL_PORT=8080" in NODE and "PEER_PORT=9000" in NODE
    assert "HEALTHCHECK" in NODE and "127.0.0.1:8080/healthz" in NODE
    for pkg in ("runtime", "peer", "learner"):
        assert f"/repo/packages/node/{pkg}" in NODE.split("PYTHONPATH=")[1]


def test_coordinator_image_is_nonroot_and_runs_the_coordinator():
    assert re.search(r"^USER coordinator$", COORD, re.M)
    assert 'ENTRYPOINT ["python", "-m", "archipelago_coordinator"]' in COORD
    assert "HEALTHCHECK" in COORD and "ARCHIPELAGO_ENV=production" in COORD
    assert "services/coordinator" in COORD.split("PYTHONPATH=")[1]


def test_no_secret_is_baked_into_an_image():
    for text in (NODE, COORD):
        assert not re.search(r"(TOKEN|PASSWORD|SECRET)\s*=\s*\S", text)

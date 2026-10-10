"""Static invariants of infra/compose/compose.yml, via `docker compose config` (no containers started)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not shutil.which("docker"), reason="docker not installed")


def config(*profiles):
    env = {**os.environ, "ARCHIPELAGO_API_TOKEN": "x", "GRAFANA_ADMIN_PASSWORD": "x"}
    args = ["docker", "compose", "-f", str(ROOT / "infra/compose/compose.yml"),
            "--env-file", str(ROOT / "infra/compose/.env.example")]
    for p in profiles:
        args += ["--profile", p]
    out = subprocess.run(args + ["config", "--format", "json"], env=env, check=True,
                         capture_output=True, text=True).stdout
    return json.loads(out)


@pytest.mark.parametrize("profiles", [(), ("local",)])
def test_only_proxy_publishes_ports(profiles):
    published = {n for n, s in config(*profiles)["services"].items() if s.get("ports")}
    assert published == {"proxy"}


def test_four_nodes_isolated_volumes_internal_network():
    cfg = config("local")
    nodes = {n: s for n, s in cfg["services"].items() if n.startswith("node-")}
    assert len(nodes) == 4
    vols = [tuple(v["source"] for v in s["volumes"]) for s in nodes.values()]
    assert len(set(vols)) == 4
    for s in nodes.values():
        assert set(s["networks"]) == {"peers"}
        assert cfg["networks"]["peers"]["internal"] is True

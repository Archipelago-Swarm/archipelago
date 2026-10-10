# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""Static invariants of infra/compose/compose.yml. No containers and no Docker daemon are needed:
`docker compose config` only renders the file, and the YAML tests parse it directly."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "infra/compose/compose.yml"
EXAMPLE = ROOT / "infra/compose/.env.example"
LOCAL = ROOT / "infra/compose/local.env"
NODES = [f"node-0{i}" for i in range(1, 5)]
SECRETS = [
    "NODE_CONTROL_TOKEN",
    "PEER_TOKEN",
    "TELEMETRY_TOKEN",
    "COORDINATOR_TOKEN",
    "COORDINATOR_ADMIN_TOKEN",
    "ARCHIPELAGO_API_TOKEN",
    "GRAFANA_ADMIN_PASSWORD",
]


def _compose_cli() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0


needs_cli = pytest.mark.skipif(not _compose_cli(), reason="docker compose CLI not installed")


def env_file(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k] = v
    return out


def render(*profiles, env_files=(EXAMPLE, LOCAL), extra_env=None, check=True):
    # PATH only: the host environment must not leak secrets into the render.
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), **(extra_env or {})}
    args = ["docker", "compose", "-f", str(COMPOSE)]
    for f in env_files:
        args += ["--env-file", str(f)]
    for p in profiles:
        args += ["--profile", p]
    return subprocess.run(
        args + ["config", "--format", "json"], env=env, check=check, capture_output=True, text=True
    )


def config(*profiles):
    return json.loads(render(*profiles).stdout)


@pytest.fixture(scope="module")
def raw():
    return yaml.safe_load(COMPOSE.read_text())


# ---- pure YAML (always run) -------------------------------------------------------------------
def test_networks_follow_amendment_a12(raw):
    nets = {n: [x for x in (s.get("networks") or [])] for n, s in raw["services"].items()}
    members = lambda net: {n for n, v in nets.items() if net in v}  # noqa: E731
    assert members("peers") == set(NODES)
    assert members("control") == {"coordinator", "api", *NODES}
    assert members("ingest") == {"api", *NODES}
    assert members("core") == {"api", "web", "proxy", "grafana", "timescaledb"}
    for n in NODES:
        assert "core" not in nets[n] and "egress" not in nets[n] and "edge" not in nets[n]
    assert set(nets["coordinator"]) == {"control"}
    for net in ("peers", "control", "ingest", "core"):
        assert raw["networks"][net]["internal"] is True


def test_only_the_proxy_declares_ports(raw):
    assert {n for n, s in raw["services"].items() if s.get("ports") or s.get("expose")} == {"proxy"}


def test_secrets_are_required_with_no_default_in_compose(raw):
    text = COMPOSE.read_text()
    for name in SECRETS:
        assert "${" + name + ":?" in text, f"{name} must be required"
        assert "${" + name + ":-" not in text and "${" + name + "-" not in text, (
            f"{name} has a default"
        )
    example = env_file(EXAMPLE)
    for name in SECRETS:
        assert example.get(name, "") == "", f".env.example must not carry a value for {name}"


def test_dev_values_live_only_in_local_env_and_are_distinct_and_long():
    local = env_file(LOCAL)
    vals = [local[k] for k in SECRETS]
    assert all(len(v) >= 16 for v in vals) and len(set(vals)) == len(vals)
    assert all("dev-only" in v for v in vals)
    # committed on purpose (dev-only values); a real .env must stay ignored
    assert subprocess.run(["git", "check-ignore", "-q", str(LOCAL)], cwd=ROOT).returncode == 1
    assert (
        subprocess.run(
            ["git", "check-ignore", "-q", str(ROOT / "infra/compose/.env")], cwd=ROOT
        ).returncode
        == 0
    )


def test_node_and_coordinator_wiring(raw):
    s = raw["services"]
    for n in NODES:
        env = s[n]["environment"]
        assert env["NODE_ID"] == n
        assert env["CONTROL_PORT"] == "8080" and env["PEER_PORT"] == "9000"
        assert env["TELEMETRY_URL"] == "http://api:8000/v1/telemetry"
        assert s[n]["volumes"] == [f"{n}:/node-data"]
        assert s[n]["restart"] == "unless-stopped" and s[n]["mem_limit"] == "1g"
    assert len({tuple(s[n]["volumes"]) for n in NODES}) == 4
    api = s["api"]["environment"]
    assert (
        api["ARCHIPELAGO_ADAPTER"] == "live" and api["COORDINATOR_URL"] == "http://coordinator:8800"
    )
    assert any(v.endswith(":/plans:ro") for v in s["api"]["volumes"])
    assert s["coordinator"]["environment"]["COORDINATOR_PLAN_FILE"].startswith("/plans/")
    assert all(s[n]["read_only"] for n in (*NODES, "coordinator"))


def test_world_battery_scale_supports_the_900_tick_demo(raw):
    """A13: the 900-tick demo needs battery_scale >= 4 in the coordinator world and in the node validation worlds."""
    s = raw["services"]
    kw = s["coordinator"]["environment"]["COORDINATOR_WORLD_KWARGS"]
    assert "${DEMO_BATTERY_SCALE:-4}" in kw
    world = json.loads(
        kw.replace("${DEMO_BATTERY_SCALE:-4}", "4").replace("${DEMO_N_TARGETS:-0}", "0")
    )
    assert world["battery_scale"] >= 4 and world["n_targets"] == 0
    assert (
        raw["x-node-env"]["WORLD_N_TARGETS"] == "${DEMO_N_TARGETS:-0}"
    )  # node worlds match the coordinator
    node_default = raw["x-node-env"]["WORLD_BATTERY_SCALE"].split(":-")[1].rstrip("}")
    assert float(node_default) >= 4


# ---- rendered by `docker compose config` (no daemon) ------------------------------------------
@needs_cli
@pytest.mark.parametrize("profiles", [(), ("local",)])
def test_rendered_only_proxy_publishes_ports(profiles):
    published = {n for n, s in config(*profiles)["services"].items() if s.get("ports")}
    assert published == {"proxy"}


@needs_cli
def test_rendered_nodes_isolated_volumes_and_networks():
    cfg = config("local")
    nodes = {n: s for n, s in cfg["services"].items() if n.startswith("node-")}
    assert sorted(nodes) == NODES
    assert len({tuple(v["source"] for v in s["volumes"]) for s in nodes.values()}) == 4
    for s in nodes.values():
        assert set(s["networks"]) == {"peers", "control", "ingest"}
    for net in ("peers", "control", "ingest", "core"):
        assert cfg["networks"][net]["internal"] is True


@needs_cli
@pytest.mark.parametrize("missing", ["NODE_CONTROL_TOKEN", "PEER_TOKEN", "TELEMETRY_TOKEN",
                                     "COORDINATOR_TOKEN", "COORDINATOR_ADMIN_TOKEN"])  # fmt: skip
def test_rendering_fails_when_a_token_is_missing(missing, tmp_path):
    kept = "\n".join(f"{k}={v}" for k, v in env_file(LOCAL).items() if k != missing)
    f = tmp_path / "partial.env"
    f.write_text(kept + "\n")
    r = render("local", env_files=(EXAMPLE, f), check=False)
    assert r.returncode != 0 and missing in r.stderr


@needs_cli
def test_production_profile_has_no_local_db_and_hardened_proxy():
    cfg = config()
    assert "timescaledb" not in cfg["services"]
    assert "TIGERDATA_URL" in cfg["services"]["api"]["environment"]
    proxy = cfg["services"]["proxy"]
    assert proxy["cap_drop"] == ["ALL"] and proxy["cap_add"] == ["NET_BIND_SERVICE"]


@needs_cli
def test_rendered_tokens_reach_the_right_services():
    cfg = config("local")["services"]
    local = env_file(LOCAL)
    assert cfg["node-03"]["environment"]["NODE_CONTROL_TOKEN"] == local["NODE_CONTROL_TOKEN"]
    assert cfg["coordinator"]["environment"]["NODE_CONTROL_TOKEN"] == local["NODE_CONTROL_TOKEN"]
    assert (
        cfg["coordinator"]["environment"]["COORDINATOR_ADMIN_TOKEN"]
        == local["COORDINATOR_ADMIN_TOKEN"]
    )
    assert (
        "COORDINATOR_ADMIN_TOKEN" not in cfg["api"]["environment"]
    )  # API never holds the admin token
    assert "COORDINATOR_ADMIN_TOKEN" not in cfg["node-01"]["environment"]
    assert cfg["api"]["environment"]["TELEMETRY_TOKEN"] == local["TELEMETRY_TOKEN"]

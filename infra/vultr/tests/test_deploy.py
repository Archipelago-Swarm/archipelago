import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from archipelago_ops import deploy, guard

NOW = datetime.now(UTC)
D1 = "a" * 64
D2 = "b" * 64
SECRETS = {
    "ARCHIPELAGO_API_TOKEN": "tok-SECRET-1234567890abcdef",
    "GRAFANA_ADMIN_PASSWORD": "graf-SECRET-pw",
    "TIGERDATA_URL": "postgresql://w:db-SECRET-pw@h.example/db?sslmode=require",
    "TIGERDATA_GRAFANA_PASSWORD": "gr-SECRET-ro",
}
ENV = {**SECRETS, "SITE_ADDRESS": "demo.example.com", "OPERATOR_IP": "203.0.113.7"}


def manifest(rel: str, digest: str) -> dict[str, Any]:
    return {
        "release": rel,
        "commit": "c" * 40,
        "repo_url": "https://github.com/example/archipelago.git",
        "images": {s: f"registry.example/archipelago/{s}@sha256:{digest}" for s in deploy.SERVICES},
    }


@pytest.fixture
def ws(tmp_path: Path) -> dict[str, Path]:
    plan: dict[str, Any] = {
        "instances": [],
        "region": "ewr",
        "experiment_end": NOW.isoformat(),
        "approved": True,
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
    }
    plan["plan_hash"] = guard.plan_hash(plan)
    files = {
        "inventory": (
            {"account": {"balance": "0", "pending_charges": "0"}, "instances": [], "plans": {}},
            "inv.json",
        ),
        "plan": (plan, "plan.json"),
        "start": ({"balance": "0", "pending_charges": "0"}, "start.json"),
        "m": (manifest("rel1", D1), "m1.json"),
        "prev": (manifest("rel0", D2), "m0.json"),
    }
    out = {}
    for k, (data, name) in files.items():
        out[k] = tmp_path / name
        out[k].write_text(json.dumps(data))
    out["ev"] = tmp_path / "ev"
    out["key"] = tmp_path / "id_ed25519"
    out["key"].write_text("not a real key")
    return out


def args(ws: dict[str, Path], step: str, *extra: str) -> list[str]:
    return [
        step,
        "--host",
        "203.0.113.9",
        "--identity-file",
        str(ws["key"]),
        "--evidence-dir",
        str(ws["ev"]),
        *extra,
    ]


def guard_args(ws: dict[str, Path]) -> list[str]:
    return [
        "--inventory",
        str(ws["inventory"]),
        "--plan",
        str(ws["plan"]),
        "--start",
        str(ws["start"]),
    ]


class Recorder:
    def __init__(self, rc: int = 0) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self.rc = rc

    def __call__(self, argv: Any, **kw: Any) -> Any:
        self.calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, self.rc, "out", "")


def test_dry_run_prints_commands_executes_nothing_and_masks_secrets(ws: dict[str, Path]) -> None:
    printed: list[str] = []
    rec = Recorder()
    rc = deploy.main(args(ws, "deploy", "--manifest", str(ws["m"])), ENV, rec, NOW, printed.append)
    text = "\n".join(printed)
    assert rc == 0 and rec.calls == []
    assert f"docker pull registry.example/archipelago/api@sha256:{D1}" in text
    assert "docker compose -f infra/compose/compose.yml" in text and "up -d --no-build" in text
    assert "ARCHIPELAGO_API_TOKEN=<redacted>" in text
    log = (ws["ev"] / "deploy-log.txt").read_text()
    for blob in (text, log):
        assert not any(s in blob for s in SECRETS.values())
    assert not (ws["ev"] / "guard-report.json").exists()


def test_execute_deploy_passes_real_env_over_ssh_but_never_logs_it(ws: dict[str, Path]) -> None:
    printed: list[str] = []
    rec = Recorder()
    rc = deploy.main(
        args(ws, "deploy", "--manifest", str(ws["m"]), "--execute", *guard_args(ws)),
        ENV,
        rec,
        NOW,
        printed.append,
    )
    assert rc == 0 and len(rec.calls) == 1
    argv, kw = rec.calls[0]
    assert argv[:3] == ["ssh", "-i", str(ws["key"])] and "StrictHostKeyChecking=yes" in argv
    assert "ARCHIPELAGO_API_TOKEN=tok-SECRET-1234567890abcdef" in kw["input"]
    assert "chmod 600 infra/compose/.env.new" in kw["input"] and "umask 077" in kw["input"]
    assert (ws["ev"] / "guard-report.json").exists()
    log = (ws["ev"] / "deploy-log.txt").read_text() + "\n".join(printed)
    assert not any(s in log for s in SECRETS.values())
    assert "guard passed" in log


def test_execute_without_guard_inputs_or_failing_guard_runs_nothing(ws: dict[str, Path]) -> None:
    rec = Recorder()
    base = args(ws, "deploy", "--manifest", str(ws["m"]), "--execute")
    assert deploy.main(base, ENV, rec, NOW, lambda s: None) == 3
    bad = json.loads(ws["plan"].read_text())
    bad["approved"] = False
    ws["plan"].write_text(json.dumps(bad))
    assert deploy.main(base + guard_args(ws), ENV, rec, NOW, lambda s: None) == 3
    ws["plan"].write_text(json.dumps({**bad, "approved": True, "plan_hash": "x"}))
    assert deploy.main(base + guard_args(ws), ENV, rec, NOW, lambda s: None) == 3
    assert rec.calls == []


def test_guard_violation_blocks_execute(ws: dict[str, Path]) -> None:
    inv = json.loads(ws["inventory"].read_text())
    inv["plans"] = {"p": {"monthly_cost": "250"}}
    inv["instances"] = [{"id": "1", "plan": "p"}]
    ws["inventory"].write_text(json.dumps(inv))
    rec = Recorder()
    rc = deploy.main(
        args(ws, "bootstrap", "--execute", *guard_args(ws)), ENV, rec, NOW, lambda s: None
    )
    assert rc == guard.EXIT_VIOLATION and rec.calls == []
    assert "MAX_MONTHLY_COST" in (ws["ev"] / "deploy-log.txt").read_text()


def test_missing_secret_refused_in_execute(ws: dict[str, Path]) -> None:
    env = {k: v for k, v in ENV.items() if k != "GRAFANA_ADMIN_PASSWORD"}
    rec = Recorder()
    rc = deploy.main(
        args(ws, "deploy", "--manifest", str(ws["m"]), "--execute", *guard_args(ws)),
        env,
        rec,
        NOW,
        lambda s: None,
    )
    assert rc == 3 and rec.calls == []


def test_bootstrap_contents() -> None:
    s = deploy.render_bootstrap("203.0.113.7", "archipelago").script
    assert "ufw allow from 203.0.113.7 to any port 22 proto tcp" in s
    assert "ufw allow 80/tcp" in s and "ufw allow 443/tcp" in s
    assert "docker-compose-plugin" in s and "adduser --disabled-password" in s
    assert "ufw default deny incoming" in s
    rules = deploy.firewall_group_parameters("203.0.113.7")["rules"]
    assert [(r["port"], r["source"]) for r in rules] == [
        ("22", "203.0.113.7/32"),
        ("80", "0.0.0.0/0"),
        ("443", "0.0.0.0/0"),
    ]


@pytest.mark.parametrize("ip", ["", "1.2.3.4; rm -rf /", "999.1.1.1", "$(id)"])
def test_bootstrap_rejects_bad_operator_ip(ip: str) -> None:
    with pytest.raises(deploy.DeployError):
        deploy.render_bootstrap(ip, "archipelago")


def test_manifest_requires_digests(ws: dict[str, Path]) -> None:
    bad = manifest("rel1", D1)
    bad["images"]["api"] = "registry.example/archipelago/api:latest"
    ws["m"].write_text(json.dumps(bad))
    assert (
        deploy.main(
            args(ws, "deploy", "--manifest", str(ws["m"])), ENV, Recorder(), NOW, lambda s: None
        )
        == 3
    )
    bad = manifest("rel 1; x", D1)
    ws["m"].write_text(json.dumps(bad))
    assert (
        deploy.main(
            args(ws, "deploy", "--manifest", str(ws["m"])), ENV, Recorder(), NOW, lambda s: None
        )
        == 3
    )


def test_env_file_is_mode_600_and_secrets_from_environment() -> None:
    step = deploy.render_deploy(manifest("rel1", D1), ENV, reveal=True)
    assert "IMAGE_TAG=rel1" in step.script and SECRETS["TIGERDATA_URL"] in step.script
    assert SECRETS["TIGERDATA_URL"] not in step.shown
    with pytest.raises(deploy.DeployError):
        deploy.render_env_file({**ENV, "SITE_ADDRESS": "a\nIMAGE_TAG=evil"}, "r", True)
    assert "install -m 600 /dev/null infra/compose/.env.new" in step.script


def test_rollback_uses_previous_manifest_and_smoke_script(ws: dict[str, Path]) -> None:
    printed: list[str] = []
    rc = deploy.main(
        args(ws, "rollback", "--previous-manifest", str(ws["prev"])),
        ENV,
        Recorder(),
        NOW,
        printed.append,
    )
    text = "\n".join(printed)
    assert rc == 0 and "IMAGE_TAG=rel0" in text and "--no-build" in text
    assert "git checkout " + "c" * 40 in text
    printed.clear()
    deploy.main(args(ws, "smoke", "--manifest", str(ws["m"])), ENV, Recorder(), NOW, printed.append)
    assert "infra/scripts/smoke.sh" in "\n".join(printed)
    assert SECRETS["ARCHIPELAGO_API_TOKEN"] not in "\n".join(printed)

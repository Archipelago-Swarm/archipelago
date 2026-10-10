"""Host bootstrap / deploy / smoke / rollback rendering and (guarded) execution.

Dry-run is the default: every command is printed with secrets masked and nothing is executed.
`--execute` first runs the cost guard in the same invocation and refuses on any non-zero result.
Remote steps go through `ssh -i <identity file>`; nothing here creates cloud resources.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shlex
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import guard

REPO_ROOT = Path(__file__).resolve().parents[3]
SMOKE = "infra/scripts/smoke.sh"
SERVICES = ("api", "web", "node")
DIGEST_RE = re.compile(r"^[a-z0-9][a-z0-9./_-]*@sha256:[0-9a-f]{64}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$|^[0-9a-fA-F:]+$")
COMPOSE = "docker compose -f infra/compose/compose.yml --env-file infra/compose/.env --profile prod"
SECRET_KEYS = (
    "ARCHIPELAGO_API_TOKEN",
    "GRAFANA_ADMIN_PASSWORD",
    "TIGERDATA_URL",
    "TIGERDATA_GRAFANA_PASSWORD",
)
PLAIN_KEYS = (
    "SITE_ADDRESS",
    "ACME_EMAIL",
    "ARCHIPELAGO_ALLOWED_ORIGINS",
    "ARCHIPELAGO_COOKIE_SECURE",
    "TIGERDATA_GRAFANA_HOST",
    "TIGERDATA_GRAFANA_USER",
    "TIGERDATA_GRAFANA_SSLMODE",
)
REQUIRED_SECRETS = ("ARCHIPELAGO_API_TOKEN", "GRAFANA_ADMIN_PASSWORD", "TIGERDATA_URL")


class DeployError(Exception):
    pass


# ---------------------------------------------------------------- manifest / env


def load_manifest(path: Path) -> dict[str, Any]:
    m = json.loads(path.read_text())
    if not SAFE_ID.match(str(m.get("release", ""))):
        raise DeployError("manifest.release must match [A-Za-z0-9._-]{1,64}")
    if not re.fullmatch(r"[0-9a-f]{40}", str(m.get("commit", ""))):
        raise DeployError("manifest.commit must be a full 40-hex sha")
    if not str(m.get("repo_url", "")).startswith("https://") or re.search(r"\s|'", m["repo_url"]):
        raise DeployError("manifest.repo_url must be an https URL")
    images = m.get("images", {})
    for svc in SERVICES:
        if not DIGEST_RE.match(str(images.get(svc, ""))):
            raise DeployError(f"manifest.images.{svc} must be a name@sha256:<64 hex> digest")
    return m


def render_env_file(env: Mapping[str, str], release: str, reveal: bool) -> str:
    """KEY=value lines. Secret values are replaced with <redacted> unless reveal is set."""
    lines = [f"IMAGE_TAG={release}"]
    for key in PLAIN_KEYS + SECRET_KEYS:
        val = env.get(key, "")
        if "\n" in val or "\r" in val:
            raise DeployError(f"{key} must not contain a newline")
        if key in SECRET_KEYS and not reveal:
            val = "<redacted>" if val else "<unset>"
        lines.append(f"{key}={val}")
    return "\n".join(lines) + "\n"


def secret_values(env: Mapping[str, str]) -> list[str]:
    vals = [env[k] for k in SECRET_KEYS + ("VULTR_API_KEY",) if env.get(k)]
    return sorted(vals, key=len, reverse=True)


def mask(text: str, secrets: list[str]) -> str:
    for s in secrets:
        text = text.replace(s, "<redacted>")
    return text


# ---------------------------------------------------------------- step rendering


@dataclass(frozen=True)
class Step:
    name: str
    where: str  # "remote" (script over ssh stdin) or "local" (argv)
    script: str  # remote: bash script (real values); local: shell-quoted command line
    shown: str  # script with secrets masked


def _apply_images_script(m: dict[str, Any], pull: bool) -> str:
    out = []
    for svc in SERVICES:
        ref = shlex.quote(m["images"][svc])
        tag = shlex.quote(f"archipelago/{svc}:{m['release']}")
        if pull:
            out.append(f"docker pull {ref}")
        else:
            out.append(f"docker image inspect {tag} >/dev/null 2>&1 || docker pull {ref}")
        out.append(f"docker tag {ref} {tag}")
    return "\n".join(out)


def validate_bootstrap_args(operator_ip: str, user: str) -> None:
    try:
        ipaddress.ip_address(operator_ip)
    except ValueError:
        raise DeployError("OPERATOR_IP is not a valid IP address") from None
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
        raise DeployError("deploy user name is invalid")


def firewall_group_parameters(operator_ip: str) -> dict[str, Any]:
    """Parameters for the Vultr firewall group the operator creates in the console."""
    net = f"{operator_ip}/{'128' if ':' in operator_ip else '32'}"
    anywhere = "0.0.0.0/0"
    return {
        "note": "operator creates this group by hand; this tool does not call the API to write",
        "rules": [
            {"protocol": "tcp", "port": "22", "source": net},
            {"protocol": "tcp", "port": "80", "source": anywhere},
            {"protocol": "tcp", "port": "443", "source": anywhere},
        ],
    }


def render_bootstrap(operator_ip: str, user: str) -> Step:
    validate_bootstrap_args(operator_ip, user)
    script = f"""set -euo pipefail
SUDO=""; [ "$(id -u)" = 0 ] || SUDO=sudo
$SUDO apt-get update
$SUDO apt-get install -y ca-certificates curl git ufw
id -u {user} >/dev/null 2>&1 || $SUDO adduser --disabled-password --gecos "" {user}
$SUDO usermod -aG sudo {user}
echo '{user} ALL=(ALL) NOPASSWD:ALL' | $SUDO tee /etc/sudoers.d/90-{user} >/dev/null
$SUDO chmod 440 /etc/sudoers.d/90-{user}
$SUDO install -d -m 700 -o {user} -g {user} /home/{user}/.ssh
if [ -f "$HOME/.ssh/authorized_keys" ]; then
  $SUDO install -m 600 -o {user} -g {user} \\
    "$HOME/.ssh/authorized_keys" /home/{user}/.ssh/authorized_keys
fi
if ! command -v docker >/dev/null 2>&1; then
  $SUDO install -m 0755 -d /etc/apt/keyrings
  $SUDO curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  . /etc/os-release
  DOCKER_REPO=https://download.docker.com/linux/ubuntu
  KEYRING=/etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=$KEYRING] $DOCKER_REPO" \\
    "$VERSION_CODENAME stable" \\
    | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null
  $SUDO apt-get update
  $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
$SUDO usermod -aG docker {user}
$SUDO ufw default deny incoming
$SUDO ufw default allow outgoing
$SUDO ufw allow from {operator_ip} to any port 22 proto tcp
$SUDO ufw allow 80/tcp
$SUDO ufw allow 443/tcp
$SUDO ufw --force enable
$SUDO ufw status verbose
"""
    return Step("bootstrap", "remote", script, script)


def render_deploy(m: dict[str, Any], env: Mapping[str, str], reveal: bool) -> Step:
    def body(show: bool) -> str:
        envtxt = render_env_file(env, m["release"], reveal=show)
        manifest = json.dumps(m, indent=2, sort_keys=True)
        repo = shlex.quote(m["repo_url"])
        return f"""set -euo pipefail
D="$HOME/archipelago-deploy"; mkdir -p "$D"
[ -d "$HOME/archipelago/.git" ] || git clone {repo} "$HOME/archipelago"
cd "$HOME/archipelago"
git fetch origin
git checkout --detach {m["commit"]}
cat > "$D/new.json" <<'MANIFEST_EOF'
{manifest}
MANIFEST_EOF
if [ -f "$D/current.json" ] && ! cmp -s "$D/current.json" "$D/new.json"; then
  cp "$D/current.json" "$D/previous.json"
fi
{_apply_images_script(m, pull=True)}
umask 077
install -m 600 /dev/null infra/compose/.env.new
cat > infra/compose/.env.new <<'ENV_EOF'
{envtxt}ENV_EOF
chmod 600 infra/compose/.env.new
mv infra/compose/.env.new infra/compose/.env
{COMPOSE} config -q
{COMPOSE} up -d --no-build
mv "$D/new.json" "$D/current.json"
{COMPOSE} ps
"""

    return Step("deploy", "remote", body(reveal), body(False))


def render_rollback(prev: dict[str, Any]) -> Step:
    script = f"""set -euo pipefail
D="$HOME/archipelago-deploy"
cd "$HOME/archipelago"
git checkout {prev["commit"]} -- infra/compose infra/proxy
{_apply_images_script(prev, pull=False)}
sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG={prev["release"]}/" infra/compose/.env
chmod 600 infra/compose/.env
{COMPOSE} up -d --no-build
cat > "$D/current.json" <<'MANIFEST_EOF'
{json.dumps(prev, indent=2, sort_keys=True)}
MANIFEST_EOF
{COMPOSE} ps
"""
    return Step("rollback", "remote", script, script)


def render_smoke(host_ip: str, site: str) -> Step:
    line = (
        f'BASE_URL={shlex.quote("https://" + site)} API_TOKEN="$ARCHIPELAGO_API_TOKEN" '
        f"HOST_IP={shlex.quote(host_ip)} {shlex.quote(str(REPO_ROOT / SMOKE))}"
    )
    return Step("smoke", "local", line, line)


def ssh_argv(user: str, host: str, identity: str) -> list[str]:
    if not HOST_RE.match(host):
        raise DeployError("invalid host")
    return [
        "ssh",
        "-i",
        identity,
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        f"{user}@{host}",
        "bash -s",
    ]


# ---------------------------------------------------------------- CLI

Runner = Callable[..., Any]


def _log(path: Path, text: str) -> None:
    with path.open("a") as f:
        f.write(text if text.endswith("\n") else text + "\n")


def main(
    argv: list[str],
    env: Mapping[str, str] | None = None,
    runner: Runner = subprocess.run,
    now: datetime | None = None,
    out: Callable[[str], None] = print,
) -> int:
    env = os.environ if env is None else env
    p = argparse.ArgumentParser(prog="deploy")
    p.add_argument("step", choices=["bootstrap", "deploy", "smoke", "rollback"])
    p.add_argument("--host", required=True)
    p.add_argument("--ssh-user", default="archipelago")
    p.add_argument("--identity-file", required=True)
    p.add_argument("--manifest", type=Path, help="release manifest (deploy, smoke)")
    p.add_argument("--previous-manifest", type=Path, help="rollback target manifest")
    p.add_argument("--deploy-user", default="archipelago", help="user created by bootstrap")
    p.add_argument("--evidence-dir", type=Path, default=Path("evidence"))
    p.add_argument("--inventory", type=Path)
    p.add_argument("--plan", type=Path)
    p.add_argument("--start", type=Path, help="spend-start.json")
    p.add_argument("--execute", action="store_true", help="actually run (default: dry-run)")
    a = p.parse_args(argv)
    evidence: Path = a.evidence_dir
    evidence.mkdir(parents=True, exist_ok=True)
    log = evidence / "deploy-log.txt"
    secrets = secret_values(env)
    mode = "execute" if a.execute else "dry-run"

    def say(text: str) -> None:
        text = mask(text, secrets)
        out(text)
        _log(log, f"[{mode}] {text}")

    try:
        if a.step == "bootstrap":
            op_ip = env.get("OPERATOR_IP", "")
            step = render_bootstrap(op_ip, a.deploy_user)
            say("# Vultr firewall group parameters (create by hand in the console)")
            say(json.dumps(firewall_group_parameters(op_ip), indent=2))
        elif a.step == "rollback":
            if not a.previous_manifest:
                raise DeployError("--previous-manifest is required")
            step = render_rollback(load_manifest(a.previous_manifest))
        else:
            if not a.manifest:
                raise DeployError("--manifest is required")
            m = load_manifest(a.manifest)
            if a.step == "deploy":
                if a.execute:
                    missing = [k for k in REQUIRED_SECRETS if not env.get(k)]
                    if missing:
                        raise DeployError("missing secrets in environment: " + ", ".join(missing))
                step = render_deploy(m, env, reveal=a.execute)
            else:
                step = render_smoke(a.host, env.get("SITE_ADDRESS", a.host))
    except (DeployError, OSError, ValueError) as e:
        say(f"REFUSED: {e}")
        return 3

    ssh = ssh_argv(a.ssh_user, a.host, a.identity_file) if step.where == "remote" else []
    say(f"## step: {step.name} ({'ssh ' + shlex.join(ssh[1:-1]) if ssh else 'local'})")
    say(step.shown)
    if not a.execute:
        say("dry-run: nothing executed (use --execute after the guard inputs are ready)")
        return 0

    if not (a.inventory and a.plan and a.start):
        say("REFUSED: --execute needs --inventory, --plan and --start for the cost guard")
        return 3
    code, _rep, msg = guard.run_guard(
        a.inventory, a.plan, a.start, evidence / "guard-report.json", now
    )
    say(msg)
    if code != guard.EXIT_OK:
        return code
    if not Path(a.identity_file).is_file() and step.where == "remote":
        say("REFUSED: identity file not found")
        return 3

    if step.where == "remote":
        res = runner(ssh, input=step.script, capture_output=True, text=True, check=False)
    else:
        res = runner(
            ["bash", "-c", step.script], env=dict(env), capture_output=True, text=True, check=False
        )
    for stream in (res.stdout, res.stderr):
        if stream:
            say(stream.rstrip("\n"))
    say(f"step {step.name} exit={res.returncode}")
    return int(res.returncode)

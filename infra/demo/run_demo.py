#!/usr/bin/env python3
# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""One-command demo driver (stdlib only): `make demo` -> up, run, collect artifacts, down.

    run_demo.py build|up|run|down|logs|all [--plan smoke|demo]

``up``   docker compose (profile local) with the dev-only env, waits for the API ``/readyz`` (live mode:
         coordinator reachable and a node ready, amendment A11).
``run``  logs in with the dev token, POSTs a run (the plan name selects the server-side plan file, A9),
         polls until it reaches a terminal state, fetches the canonical events and calls
         ``artifacts.write_artifacts`` -> ``artifacts/demo/<run_id>/``.
``down`` compose down -v (fresh volumes every demo); artifacts are left in place.
``all``  up, run, then down even on failure; on failure the compose logs are saved first.

The artifact generator is the pure module ``artifacts.py`` (tested offline); this file only talks to Docker and
to ``GET /v1/runs/{id}/events``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import artifacts  # noqa: E402

COMPOSE_FILE = ROOT / "infra/compose/compose.yml"
ENV_FILES = (ROOT / "infra/compose/.env.example", ROOT / "infra/compose/local.env")
PROJECT = "archipelago-demo"
TERMINAL = {"completed", "failed", "interrupted"}
IMAGES = ("archipelago/node", "archipelago/coordinator", "archipelago/api", "archipelago/web")
# Per-plan run parameters that are not part of the coordinator Plan (the world is fixed by the compose env).
PROFILES: dict[str, dict[str, Any]] = {
    "smoke": {"max_ticks": 150, "timeout_s": 900, "max_wall_seconds": 900.0},
    "demo": {"max_ticks": 900, "timeout_s": 7200, "max_wall_seconds": 7200.0},
}
START_POSES = ((8, 8), (71, 8), (8, 36), (71, 36))  # distinct, inside the 80x45 hidden grid (continuous_flight demo)


class DemoError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------
# helpers (pure, tested)
# ---------------------------------------------------------------------------------------------
def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def load_plan(name: str) -> dict[str, Any]:
    if name not in PROFILES:
        raise DemoError(f"unknown plan {name!r}; expected one of {sorted(PROFILES)}")
    return json.loads((HERE / "plans" / f"{name}.json").read_text())


def build_run_config(plan_name: str, plan: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Contract ``RunConfig`` for the live coordinator (4 distinct starts, budgets from the plan profile)."""
    nodes = sorted(plan["node_urls"])
    if len(nodes) > len(START_POSES):
        raise DemoError("plan has more nodes than start poses")
    first_train = next(e for e in plan["episodes"] if e["kind"] == "train")
    prof = PROFILES[plan_name]
    scenario = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return {
        "kind": "run_config",
        "schema_version": "0.1.0",
        "run_id": run_id,
        "simulator": "sim2d",
        "simulator_version": "0.1.0",
        "scenario_hash": scenario,
        "seeds": {"env": first_train["seed"], "topology": 0, "learner": 0, "exploration": 0},
        "nodes": [
            {"node_id": n, "start_pose": {"x": x, "y": y, "z": 0.0, "heading_rad": 0.0}}
            for n, (x, y) in zip(nodes, START_POSES, strict=False)
        ],
        "observation_id": "obs-v0",
        "action_id": "act-v0",
        "reward_id": "rew-v0",
        "mode": "distributed",
        "learner": "peer_dqn",
        "budgets": {"max_ticks": prof["max_ticks"], "max_wall_seconds": prof["max_wall_seconds"]},
        "fault_schedule": plan["fault_schedule"],
    }


def new_run_id(plan_name: str, now: datetime | None = None) -> str:
    return f"demo-{plan_name}-{(now or datetime.now(UTC)).strftime('%Y%m%dT%H%M%SZ')}"


# ---------------------------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------------------------
class Api:
    def __init__(self, base_url: str, token: str, timeout: float = 15.0) -> None:
        self.base, self.token, self.timeout = base_url.rstrip("/"), token, timeout

    def request(
        self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        h = {"Authorization": f"Bearer {self.token}", **(headers or {})}
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 - local stack URL
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw) if raw else None
            except ValueError:
                return e.code, raw.decode(errors="replace")

    def wait_ready(self, timeout: float, interval: float = 2.0) -> None:
        end, last = time.monotonic() + timeout, None
        while time.monotonic() < end:
            try:
                code, body = self.request("GET", "/readyz")
                last = (code, body)
                if code == 200:
                    return
            except (OSError, urllib.error.URLError) as e:
                last = repr(e)
            time.sleep(interval)
        raise DemoError(f"/readyz not ready after {timeout:.0f}s; last: {last}")

    def login(self) -> None:
        code, body = self.request("POST", "/v1/login", {"token": self.token})
        if code != 200:
            raise DemoError(f"login failed: {code} {body}")

    def start_run(self, plan_name: str, run_config: dict[str, Any]) -> dict[str, Any]:
        # The plan is selected server-side (COORDINATOR_PLAN_FILE, A9); the mounted file is the only plan, so no name is sent.
        code, body = self.request(
            "POST",
            "/v1/runs",
            run_config,  # no plan name: the mounted plan file (one raw plan = "default") is the plan
            {"Idempotency-Key": uuid.uuid4().hex},
        )
        if code not in (200, 201):
            raise DemoError(f"start run failed: {code} {body}")
        return body

    def wait_done(
        self, run_id: str, timeout: float, interval: float = 2.0, log=print
    ) -> dict[str, Any]:
        end, last_line = time.monotonic() + timeout, ""
        view: dict[str, Any] = {}
        while time.monotonic() < end:
            code, view = self.request("GET", f"/v1/runs/{run_id}")
            if code != 200:
                raise DemoError(f"GET run failed: {code} {view}")
            line = (
                f"status={view.get('status')} episode={view.get('episode')} tick={view.get('tick')}"
            )
            if line != last_line:
                log(line)
                last_line = line
            if view.get("status") in TERMINAL:
                return view
            time.sleep(interval)
        raise DemoError(f"run {run_id} not finished after {timeout:.0f}s; last {view}")

    def events(self, run_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        after = 0
        while True:
            code, page = self.request(
                "GET", f"/v1/runs/{run_id}/events?after_sequence={after}&limit=500"
            )
            if code != 200:
                raise DemoError(f"GET events failed: {code} {page}")
            if not page["events"]:
                return out
            out += page["events"]
            after = page["events"][-1]["sequence"]


# ---------------------------------------------------------------------------------------------
# run + collect (no Docker required: tested against a fake API)
# ---------------------------------------------------------------------------------------------
def run_and_collect(
    api: Api,
    plan_name: str,
    out_root: Path,
    *,
    commit: str = "unknown",
    image_digests: dict[str, str] | None = None,
    poll_interval: float = 2.0,
    log=print,
) -> Path:
    plan = load_plan(plan_name)
    run_id = new_run_id(plan_name)
    cfg = build_run_config(plan_name, plan, run_id)
    api.login()
    t0 = time.monotonic()
    started = api.start_run(plan_name, cfg)
    run_id = started.get("run_id", run_id)
    log(f"run {run_id} started (plan {plan_name})")
    view = api.wait_done(run_id, PROFILES[plan_name]["timeout_s"], poll_interval, log)
    wall = time.monotonic() - t0
    events = api.events(run_id)
    out = out_root / run_id
    meta = {
        "run_id": run_id,
        "plan": plan_name,
        "run_config": cfg,
        "seeds": cfg["seeds"],
        "max_ticks": cfg["budgets"]["max_ticks"],
        "episodes": [
            {"kind": e["kind"]} for e in plan["episodes"] for _ in range(int(e.get("count", 1)))
        ],
        "commit": commit,
        "image_digests": image_digests or {},
        "wall_seconds": round(wall, 2),
        "final_status": view.get("status"),
    }
    paths = artifacts.write_artifacts(events, out, meta)
    (out / "run.json").write_text(json.dumps({"view": view, "plan": plan}, indent=2) + "\n")
    (out_root / "LATEST").write_text(run_id + "\n")
    log(f"wrote {len(paths) + 1} artifacts to {out}")
    if view.get("status") != "completed":
        raise DemoError(f"run ended {view.get('status')}: artifacts in {out}")
    if not events:
        raise DemoError(f"run completed but the API returned no events: artifacts in {out}")
    return out


# ---------------------------------------------------------------------------------------------
# docker compose
# ---------------------------------------------------------------------------------------------
def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def compose_env(plan_name: str, commit: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        DEMO_PLAN=plan_name,
        DEMO_MAX_TICKS=str(PROFILES[plan_name]["max_ticks"]),
        ARCHIPELAGO_COMMIT=commit,
    )
    return env


def compose_cmd(*args: str) -> list[str]:
    cmd = ["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE_FILE)]
    for f in ENV_FILES:
        cmd += ["--env-file", str(f)]
    return [*cmd, "--profile", "local", *args]


def compose(
    env: dict[str, str], *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(compose_cmd(*args), env=env, cwd=ROOT, check=check, text=True)


def image_digests(tag: str = "dev") -> dict[str, str]:
    out: dict[str, str] = {}
    for name in IMAGES:
        r = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", f"{name}:{tag}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode == 0:
            out[name] = r.stdout.strip()
    return out


def save_logs(env: dict[str, str], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "compose.log").open("w") as f:
        subprocess.run(compose_cmd("logs", "--no-color", "--timestamps"), env=env, cwd=ROOT, stdout=f,
                       stderr=subprocess.STDOUT, check=False)  # fmt: skip
        f.write("\n--- ps ---\n")
        f.flush()
        subprocess.run(
            compose_cmd("ps", "-a"),
            env=env,
            cwd=ROOT,
            stdout=f,
            stderr=subprocess.STDOUT,
            check=False,
        )


def api_from_env(port: str) -> Api:
    token = (
        os.environ.get("ARCHIPELAGO_API_TOKEN")
        or read_env_file(ENV_FILES[1])["ARCHIPELAGO_API_TOKEN"]
    )
    return Api(f"http://localhost:{port}", token)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("action", choices=["build", "up", "run", "down", "logs", "all"])
    ap.add_argument(
        "--plan", default=os.environ.get("DEMO_PLAN", "smoke"), choices=sorted(PROFILES)
    )
    ap.add_argument("--out", default=str(ROOT / "artifacts/demo"))
    ap.add_argument("--port", default=os.environ.get("PROXY_HTTP_PORT", "80"))
    ap.add_argument("--ready-timeout", type=float, default=300.0)
    args = ap.parse_args(argv)
    out_root = Path(args.out)
    commit = git_commit()
    env = compose_env(args.plan, commit)
    env["PROXY_HTTP_PORT"] = args.port
    api = api_from_env(args.port)

    def up() -> None:
        compose(
            env, "up", "-d", "--build", "--wait", "--wait-timeout", str(int(args.ready_timeout))
        )
        api.wait_ready(args.ready_timeout)

    def run() -> Path:
        return run_and_collect(
            api,
            args.plan,
            out_root,
            commit=commit,
            image_digests=image_digests(env.get("IMAGE_TAG", "dev")),
        )

    try:
        if args.action == "build":
            compose(env, "build")
        elif args.action == "up":
            up()
        elif args.action == "run":
            run()
        elif args.action == "down":
            compose(env, "down", "-v", "--remove-orphans")
        elif args.action == "logs":
            save_logs(env, out_root / "logs")
        else:  # all
            rc = 0
            try:
                up()
                run()
            except (DemoError, subprocess.CalledProcessError) as e:
                print(f"demo failed: {e}", file=sys.stderr)
                save_logs(env, out_root / "logs-failed")
                rc = 1
            finally:
                # Teardown never masks the original failure: report its own error separately.
                down = compose(env, "down", "-v", "--remove-orphans", check=False)
                if down.returncode != 0:
                    print(f"compose down exited {down.returncode}", file=sys.stderr)
            return rc
    except (DemoError, subprocess.CalledProcessError) as e:
        print(f"demo failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

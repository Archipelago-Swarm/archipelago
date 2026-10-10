# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""No-Docker launcher for the live stack: one coordinator and four node runtime processes on localhost.

Everything is created per test: free ports, tokens, temp directories (one checkpoint dir per node), a
telemetry sink standing in for the API ingest, log files per process (read on failure), readiness waits
and a teardown that always kills what it started. Agreement: agents/architecture/live-runtime.md section 11.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
NODE_PATHS = [
    "packages/node/runtime", "packages/node/peer", "packages/node/learner", "packages/transport",
    "packages/contracts/src", "packages/learning", "packages/sim",
]  # fmt: skip
COORD_PATHS = [
    "services/coordinator",
    "packages/sim",
    "packages/adapters/sim2d",
    "packages/contracts/src",
]
NODE_IDS = ["node-01", "node-02", "node-03", "node-04"]
STARTS = {"node-01": (0, 0), "node-02": (7, 0), "node-03": (0, 7), "node-04": (7, 7)}  # 8x8 world
HALVES_CUT = [
    ["node-01", "node-03"],
    ["node-01", "node-04"],
    ["node-02", "node-03"],
    ["node-02", "node-04"],
]
CONTROL_TOKEN = "e2e-node-control-token-0123456789"
PEER_TOKEN = "e2e-peer-token-0123456789"
TELEMETRY_TOKEN = "e2e-telemetry-token-0123456789"
COORD_TOKEN = "e2e-coordinator-token-0123456789"
ADMIN_TOKEN = "e2e-coordinator-admin-token-012345"


def free_ports(n: int) -> list[int]:
    socks = [socket.socket() for _ in range(n)]
    try:
        for s in socks:
            s.bind(("127.0.0.1", 0))
        return [s.getsockname()[1] for s in socks]
    finally:
        for s in socks:
            s.close()


def http(
    method: str, url: str, token: str | None = None, body: Any = None, timeout: float = 10.0
) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else None
        except ValueError:
            return e.code, raw.decode(errors="replace")


class TelemetrySink:
    """Stands in for the API ingest route: records every authenticated batch the nodes ship."""

    def __init__(self, token: str = TELEMETRY_TOKEN) -> None:
        self.batches: list[dict[str, Any]] = []
        self.unauthorized = 0
        self.lock = threading.Lock()
        sink = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(
                    self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"
                )
                ok = self.headers.get("Authorization") == f"Bearer {token}"
                with sink.lock:
                    if ok:
                        sink.batches.append(body)
                    else:
                        sink.unauthorized += 1
                raw = b"{}"
                self.send_response(200 if ok else 401)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1/telemetry"

    def records(self, node: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            out = [r["record"] for b in self.batches for r in b.get("records", [])]
        return [r for r in out if node is None or r["source_node_id"] == node]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class ControlShim:
    """TEMPORARY compatibility proxy between the coordinator and one node (coordinator -> shim -> node).

    The coordinator and the node runtime currently disagree on three control messages (both owned by the
    simulation/learning owner, pending the T27/T39 amendments): the coordinator sends ``reset`` with extra
    ``seed``/``episode_kind`` fields and ``set_schedule`` as ``{run_id, episode, schedule, schedule_sha256}``,
    while the node accepts ``reset{run_id, episode, mode, fault_schedule?}``, ``set_schedule{fault_schedule}`` and
    ``episode_end{tick?, wait?}`` (``extra=forbid``; the coordinator adds ``run_id``/``episode`` to ``episode_end``).
    The shim rewrites exactly those three messages and forwards everything else untouched, so
    the rest of the stack can be exercised. It records the raw coordinator bodies and counts rewrites;
    test_live_contract.py asserts that no rewrite was needed, which is the signal to delete this class.
    """

    def __init__(self, node_url: str) -> None:
        self.target = node_url
        self.raw_control: list[dict[str, Any]] = []
        self.rewrites = 0
        shim = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _forward(self, method: str) -> None:
                n = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(n) if n else b""
                if method == "POST" and self.path == "/v1/control":
                    raw = shim._rewrite(raw)
                req = urllib.request.Request(shim.target + self.path, raw or None, method=method)
                for h in ("Authorization", "Content-Type"):
                    if self.headers.get(h):
                        req.add_header(h, self.headers[h])
                try:
                    with urllib.request.urlopen(req, timeout=30) as r:
                        code, out = r.status, r.read()
                except urllib.error.HTTPError as e:
                    code, out = e.code, e.read()
                except OSError:
                    code, out = 502, b'{"error":"node unreachable"}'
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def do_GET(self):
                self._forward("GET")

            def do_POST(self):
                self._forward("POST")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def _rewrite(self, raw: bytes) -> bytes:
        try:
            body = json.loads(raw)
        except ValueError:
            return raw
        self.raw_control.append(body)
        cmd, new = body.get("command"), None
        if cmd == "reset":
            new = {k: body[k] for k in ("command", "run_id", "episode", "mode") if k in body}
        elif cmd == "episode_end":
            new = {k: body[k] for k in ("command", "tick", "wait") if k in body}
        elif cmd == "set_schedule" and "schedule" in body:
            new = {"command": "set_schedule", "fault_schedule": body["schedule"]}
        if new is None or new == body:
            return raw
        self.rewrites += 1
        return json.dumps(new).encode()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class Proc:
    """A subprocess with its output captured in a log file (never a pipe that can fill up)."""

    def __init__(
        self, name: str, argv: list[str], env: dict[str, str], logdir: Path, cwd: Path
    ) -> None:
        self.name, self.argv, self.env, self.cwd = name, argv, env, cwd
        self.logdir = logdir
        self.starts = 0
        self.killed = (
            False  # deliberately stopped by the test: readiness waits must not treat it as a crash
        )
        self.popen: subprocess.Popen | None = None

    @property
    def log(self) -> Path:
        return self.logdir / f"{self.name}.log"

    def start(self) -> None:
        self.starts += 1
        self.killed = False
        f = self.log.open("ab")
        self.popen = subprocess.Popen(
            self.argv, env=self.env, stdout=f, stderr=subprocess.STDOUT, cwd=self.cwd
        )
        f.close()

    def alive(self) -> bool:
        return self.popen is not None and self.popen.poll() is None

    def kill(self) -> None:
        """SIGKILL: no shutdown hooks and no final checkpoint."""
        self.killed = True
        if self.popen is not None and self.popen.poll() is None:
            self.popen.kill()
        if self.popen is not None:
            self.popen.wait(timeout=30)

    def terminate(self) -> int:
        assert self.popen is not None
        self.popen.terminate()
        return self.popen.wait(timeout=30)

    def tail(self, n: int = 40) -> str:
        try:
            return "\n".join(self.log.read_text(errors="replace").splitlines()[-n:])
        except OSError:
            return ""


def child_env(paths: list[str], **extra: str) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.pathsep.join(str(ROOT / p) for p in paths),
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    env.update(extra)
    return env


class Cluster:
    """Coordinator + four node processes. ``ticks`` is the episode length of both worlds."""

    def __init__(self, tmp: Path, ticks: int = 80, shim: bool = True, **node_env: str) -> None:
        self.tmp, self.ticks = Path(tmp), ticks
        self.use_shim = shim
        self.shims: dict[str, ControlShim] = {}
        self.logs = self.tmp / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        ports = free_ports(2 * len(NODE_IDS) + 1)
        self.control_port = dict(zip(NODE_IDS, ports[:4], strict=True))
        self.peer_port = dict(zip(NODE_IDS, ports[4:8], strict=True))
        self.coord_port = ports[8]
        self.sink = TelemetrySink()
        self.node_env = node_env
        self.nodes: dict[str, Proc] = {}
        self.coord: Proc | None = None

    # -- addresses
    def node_url(self, n: str) -> str:
        return f"http://127.0.0.1:{self.control_port[n]}"

    def coord_node_url(self, n: str) -> str:
        """The URL the coordinator uses for node ``n`` (through the temporary control shim by default)."""
        if not self.use_shim:
            return self.node_url(n)
        if n not in self.shims:
            self.shims[n] = ControlShim(self.node_url(n))
        return self.shims[n].url

    @property
    def coord_url(self) -> str:
        return f"http://127.0.0.1:{self.coord_port}"

    def ckpt_dir(self, n: str) -> Path:
        return self.tmp / "ckpt" / n

    # -- processes
    def _node(self, n: str) -> Proc:
        peers = ",".join(f"{i}=http://127.0.0.1:{self.peer_port[i]}" for i in NODE_IDS)
        env = child_env(
            NODE_PATHS,
            NODE_ID=n, NODE_IDS=",".join(NODE_IDS), PEER_URLS=peers,
            NODE_CONTROL_TOKEN=CONTROL_TOKEN, PEER_TOKEN=PEER_TOKEN, TELEMETRY_TOKEN=TELEMETRY_TOKEN,
            TELEMETRY_URL=self.sink.url, NODE_CHECKPOINT_DIR=str(self.ckpt_dir(n)),
            BIND_HOST="127.0.0.1", CONTROL_PORT=str(self.control_port[n]), PEER_PORT=str(self.peer_port[n]),
            WORLD_SIZE="8", WORLD_N_TARGETS="0", WORLD_BATTERY_SCALE="4", WORLD_MAX_TICKS=str(self.ticks),
            VALIDATION_SEEDS="7001,7002", VALIDATION_MAX_TICKS=str(min(self.ticks, 40)),
            REPLAY_CAPACITY="2000", BATCH_SIZE="16", TARGET_EVERY="25", EPS_DECAY_ACTS="400",
            PEER_TIMEOUT="1.0", PEER_RETRIES="0", TELEMETRY_INTERVAL="0.2",
            OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", TORCH_THREADS="1", SEED="0",
            GIT_COMMIT="e2e",
            **self.node_env,
        )  # fmt: skip
        return Proc(n, [sys.executable, "-m", "archipelago_noderuntime"], env, self.logs, self.tmp)

    def start_nodes(self) -> None:
        for n in NODE_IDS:
            self.ckpt_dir(n).mkdir(parents=True, exist_ok=True)
            self.nodes[n] = self._node(n)
            self.nodes[n].start()

    def start_coordinator(self, tick_interval_s: float = 0.0) -> None:
        urls = ",".join(f"{n}={self.coord_node_url(n)}" for n in NODE_IDS)
        env = child_env(
            COORD_PATHS,
            COORDINATOR_TOKEN=COORD_TOKEN, COORDINATOR_ADMIN_TOKEN=ADMIN_TOKEN,
            NODE_CONTROL_TOKEN=CONTROL_TOKEN, COORDINATOR_DATA_DIR=str(self.tmp / "coordinator"),
            COORDINATOR_NODE_URLS=urls, ARCHIPELAGO_ENV="production", ARCHIPELAGO_COMMIT="e2e",
            COORDINATOR_WORLD_KWARGS=json.dumps({"size": 8, "n_targets": 0, "battery_scale": 4.0}),
            COORDINATOR_TICK_INTERVAL_S=str(tick_interval_s),
        )  # fmt: skip
        self.coord = Proc(
            "coordinator",
            [sys.executable, "-m", "archipelago_coordinator", "--host", "127.0.0.1", "--port", str(self.coord_port)],
            env, self.logs, self.tmp,
        )  # fmt: skip
        self.coord.start()

    def start(self, tick_interval_s: float = 0.0, timeout: float = 90.0) -> Cluster:
        self.start_nodes()
        self.wait_nodes_ready(timeout)
        self.start_coordinator(tick_interval_s)
        self.wait_coordinator_ready(timeout)
        return self

    # -- readiness
    def _wait(self, what: str, pred, procs: list[Proc], timeout: float):
        end, last = time.monotonic() + timeout, None
        while time.monotonic() < end:
            for p in procs:
                if not p.alive() and not p.killed:
                    raise RuntimeError(f"{p.name} exited while waiting for {what}:\n{p.tail()}")
            try:
                last = pred()
                if last:
                    return last
            except (OSError, urllib.error.URLError, ValueError) as e:
                last = repr(e)
            time.sleep(0.2)
        raise TimeoutError(
            f"timeout waiting for {what}; last={last}\n" + "\n".join(p.tail(15) for p in procs)
        )

    def wait_nodes_ready(self, timeout: float = 90.0, only: list[str] | None = None) -> None:
        names = only or NODE_IDS
        self._wait(
            "nodes ready",
            lambda: all(self.node_status(n).get("ready") for n in names),
            [self.nodes[n] for n in names], timeout,
        )  # fmt: skip

    def wait_coordinator_ready(self, timeout: float = 60.0) -> None:
        assert self.coord is not None
        self._wait("coordinator /readyz", lambda: http("GET", self.coord_url + "/readyz", COORD_TOKEN)[0] == 200,
                   [self.coord], timeout)  # fmt: skip

    # -- calls
    def node_status(self, n: str) -> dict[str, Any]:
        code, body = http("GET", self.node_url(n) + "/v1/status", CONTROL_TOKEN)
        assert code == 200, (n, code, body)
        return body

    def node_control(self, n: str, **body: Any) -> tuple[int, Any]:
        return http("POST", self.node_url(n) + "/v1/control", CONTROL_TOKEN, body)

    def coord_call(
        self, method: str, path: str, body: Any = None, token: str = COORD_TOKEN
    ) -> tuple[int, Any]:
        return http(method, self.coord_url + path, token, body)

    def start_run(self, run_id: str, *, episodes: list[dict], fault_schedule: list[dict] | None = None,
                  ticks: int | None = None, seed: int = 1, **plan: Any) -> dict[str, Any]:  # fmt: skip
        code, body = self.coord_call(
            "POST", "/v1/runs", self.run_body(run_id, episodes, fault_schedule, ticks, seed, **plan)
        )
        assert code == 201, (code, body)
        return body

    def run_body(
        self, run_id, episodes, fault_schedule=None, ticks=None, seed=1, **plan
    ) -> dict[str, Any]:
        faults = fault_schedule or []
        cfg = {
            "kind": "run_config", "schema_version": "0.1.0", "run_id": run_id, "simulator": "sim2d",
            "simulator_version": "0.1.0", "scenario_hash": "0" * 64,
            "seeds": {"env": seed, "topology": 0, "learner": 0, "exploration": 0},
            "nodes": [{"node_id": n, "start_pose": {"x": x, "y": y, "z": 0.0, "heading_rad": 0.0}} for n, (x, y) in STARTS.items()],
            "observation_id": "obs-v0", "action_id": "act-v0", "reward_id": "rew-v0",
            "mode": "distributed", "learner": "peer_dqn",
            "budgets": {"max_ticks": ticks or self.ticks, "max_wall_seconds": 600.0},
            "fault_schedule": faults,
        }  # fmt: skip
        return {
            "run_config": cfg,
            "plan": {
                "node_urls": {n: self.coord_node_url(n) for n in NODE_IDS}, "deadline_ms": 2000,
                "episodes": episodes, "fault_schedule": faults, **plan,
            },
        }  # fmt: skip

    def run_status(self, run_id: str) -> dict[str, Any]:
        code, body = self.coord_call("GET", f"/v1/runs/{run_id}")
        assert code == 200, (code, body)
        return body

    def wait_run(
        self, run_id: str, timeout: float = 180.0, until=("completed", "failed", "interrupted")
    ) -> dict[str, Any]:
        def done():
            s = self.run_status(run_id)
            return s if s["status"] in until else None

        assert self.coord is not None
        return self._wait(f"run {run_id}", done, [self.coord, *self.nodes.values()], timeout)

    def events(self, run_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        after = 0
        while True:
            code, page = self.coord_call(
                "GET", f"/v1/runs/{run_id}/events?after_sequence={after}&limit=500"
            )
            assert code == 200, (code, page)
            if not page["events"]:
                return out
            out += page["events"]
            after = page["events"][-1]["sequence"]

    # -- restart / teardown
    def restart_node(self, n: str, *, kill: bool = True, timeout: float = 90.0) -> None:
        p = self.nodes[n]
        if kill:
            p.kill()
        else:
            p.terminate()
        p.start()
        self.wait_nodes_ready(timeout, only=[n])

    def logs_text(self) -> str:
        parts = []
        for p in [*self.nodes.values(), *([self.coord] if self.coord else [])]:
            parts.append(f"--- {p.name} (starts={p.starts}, alive={p.alive()}) ---\n{p.tail(30)}")
        return "\n".join(parts)

    def close(self) -> None:
        for p in [*([self.coord] if self.coord else []), *self.nodes.values()]:
            try:
                p.kill()
            except Exception as e:  # noqa: BLE001 - teardown must reach every process
                print(f"teardown: could not stop {p.name}: {e!r}", file=sys.stderr)
        for sh in self.shims.values():
            sh.close()
        self.sink.close()

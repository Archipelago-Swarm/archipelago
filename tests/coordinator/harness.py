"""Test harness: in-process fake node servers (stdlib) and a coordinator launcher."""

from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from archipelago_coordinator import Coordinator, Settings
from archipelago_coordinator.httpd import make_server
from archipelago_sim2d.smoke import make_config

COORD_TOKEN = "coordinator-token-0123456789"
ADMIN_TOKEN = "admin-token-0123456789-abcdef"
NODE_TOKEN = "node-control-token-0123456789"
ACTIONS = ("stay", "north", "east", "south", "west")
OBS_FIELDS = {
    "kind", "schema_version", "event_id", "run_id", "source_node_id", "sim_tick",
    "emitted_at_utc", "sequence", "crop", "known_mask", "pose", "battery",
    "visible_markers", "neighbor_summaries",
}  # fmt: skip
WORLD_KW = {"n_targets": 0, "battery_scale": 10.0}  # nothing ends the episode before max_ticks


def default_policy(node: str, episode: int, tick: int, obs: dict[str, Any]) -> str:
    return random.Random(f"{node}:{episode}:{tick}").choice(ACTIONS)


class FakeNode:
    """Implements /v1/act, /v1/feedback, /v1/control, /v1/status like a node runtime."""

    def __init__(
        self,
        node_id: str,
        others: list[str],
        policy: Callable[[str, int, int, dict[str, Any]], str] = default_policy,
        stall: Callable[[int, int], float] | None = None,
        corrupt: Callable[[int, int], str | None] | None = None,
    ) -> None:
        self.node_id, self.others, self.policy = node_id, others, policy
        self.stall, self.corrupt = stall, corrupt
        self.token = NODE_TOKEN
        self.acts: list[dict[str, Any]] = []
        self.feedback: list[dict[str, Any]] = []
        self.controls: list[dict[str, Any]] = []
        self.timeline: list[str] = []  # ordered "control:<cmd>" / "act" / "feedback"
        self.violations: list[str] = []
        self.mode = "train"
        self.cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        self.last_tick = -1
        self.lock = threading.Lock()
        self.auth_failures = 0
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            disable_nagle_algorithm = True

            def log_message(self, *a: Any) -> None:
                return

            def _reply(self, code: int, body: dict[str, Any]) -> None:
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _body(self) -> dict[str, Any]:
                n = int(self.headers.get("Content-Length", "0"))
                return json.loads(self.rfile.read(n) or b"{}")

            def do_GET(self) -> None:
                if self.headers.get("Authorization") != f"Bearer {fake.token}":
                    fake.auth_failures += 1
                    return self._reply(401, {"error": "unauthorized"})
                self._reply(200, {"ready": True, "node_id": fake.node_id, "mode": fake.mode})

            def do_POST(self) -> None:
                body = self._body()
                if self.headers.get("Authorization") != f"Bearer {fake.token}":
                    fake.auth_failures += 1
                    return self._reply(401, {"error": "unauthorized"})
                code, out = fake.handle(self.path, body)
                self._reply(code, out)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        ).start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _check_privacy(self, body: dict[str, Any]) -> None:
        if set(body) != {"run_id", "episode", "tick", "deadline_ms", "observation"}:
            self.violations.append(f"unexpected act keys {sorted(body)}")
        obs = body.get("observation", {})
        if not set(obs) <= OBS_FIELDS:
            self.violations.append(f"unexpected observation keys {sorted(set(obs) - OBS_FIELDS)}")
        if obs.get("source_node_id") != self.node_id:
            self.violations.append("observation belongs to another node")
        text = json.dumps(body)
        for other in self.others:
            if other in text:
                self.violations.append(f"payload mentions {other}")
        for secret in ("obstacles", "targets", "poses", "coverage", "topology", "world"):
            if secret in text:
                self.violations.append(f"payload mentions {secret}")

    def handle(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if path == "/v1/control":
            with self.lock:
                self.controls.append(body)
                self.timeline.append(f"control:{body.get('command')}")
                if body.get("command") == "reset":
                    self.mode = body["mode"]
                    self.last_tick = -1
                    self.cache.clear()
            return 200, {"ok": True, "status": {}}
        if path == "/v1/act":
            self._check_privacy(body)
            ep, tick = body["episode"], body["tick"]
            with self.lock:
                self.acts.append(body)
                self.timeline.append("act")
            if self.stall:
                time.sleep(self.stall(ep, tick))
            with self.lock:
                key = (body["run_id"], ep, tick)
                if key in self.cache:
                    return 200, self.cache[key]
                if tick < self.last_tick:
                    return 409, {"error": "stale"}
                self.last_tick = tick
                cmd = self.policy(self.node_id, ep, tick, body["observation"])
                resp_tick = tick
                bad = self.corrupt(ep, tick) if self.corrupt else None
                if bad == "garbage":
                    cmd = "fly"
                if bad == "wrong_tick":
                    resp_tick = tick - 1
                action = {
                    "kind": "action", "schema_version": "0.1.0",
                    "event_id": f"{self.node_id}-fake-{tick}", "run_id": body["run_id"],
                    "source_node_id": self.node_id, "sim_tick": tick,
                    "emitted_at_utc": "2026-01-01T00:00:00Z", "sequence": tick,
                    "action_space_version": "act-v0", "command": cmd, "policy_version": 1,
                }  # fmt: skip
                out = {
                    "node_id": self.node_id, "tick": resp_tick, "action": action,
                    "policy_version": 1, "epsilon": 0.1,
                }  # fmt: skip
                self.cache[key] = out
                return 200, out
        if path == "/v1/feedback":
            with self.lock:
                self.feedback.append(body)
                self.timeline.append("feedback")
                if self.mode == "eval":
                    return 409, {"error": "eval mode"}
            return 200, {"accepted": True, "replay_size": len(self.feedback), "train_steps": 0}
        return 404, {"error": "not found"}


def http(method: str, url: str, token: str | None, body: Any = None) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class Live:
    """A running coordinator (service + HTTP server) with convenience calls."""

    def __init__(self, data_dir: Path, **settings: Any) -> None:
        kw = {"world_kwargs": WORLD_KW, **settings}
        self.settings = Settings(
            coordinator_token=COORD_TOKEN,
            admin_token=ADMIN_TOKEN,
            node_token=NODE_TOKEN,
            data_dir=data_dir,
            **kw,
        )
        self.svc = Coordinator(self.settings)
        self.server = make_server(self.svc)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        ).start()

    def call(self, method: str, path: str, body: Any = None, token: str | None = COORD_TOKEN):
        return http(method, self.url + path, token, body)

    def start_run(self, body: dict[str, Any]) -> dict[str, Any]:
        code, out = self.call("POST", "/v1/runs", body)
        assert code == 201, (code, out)
        return out

    def status(self, run_id: str) -> dict[str, Any]:
        code, out = self.call("GET", f"/v1/runs/{run_id}")
        assert code == 200, (code, out)
        return out

    def wait(self, run_id: str, pred: Callable[[dict[str, Any]], bool], timeout: float = 60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            s = self.status(run_id)
            if pred(s):
                return s
            time.sleep(0.02)
        raise AssertionError(f"timeout waiting; last status {self.status(run_id)}")

    def wait_done(self, run_id: str, timeout: float = 60) -> dict[str, Any]:
        s = self.wait(
            run_id, lambda s: s["status"] in ("completed", "failed", "interrupted"), timeout
        )
        assert s["status"] == "completed", s
        return s

    def command(self, run_id: str, cid: str, cmd: str, rev: int | None = None):
        body: dict[str, Any] = {"command_id": cid, "command": cmd}
        if rev is not None:
            body["expected_revision"] = rev
        return self.call("POST", f"/v1/runs/{run_id}/commands", body)

    def events(self, run_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        after = 0
        while True:
            code, page = self.call(
                "GET", f"/v1/runs/{run_id}/events?after_sequence={after}&limit=500"
            )
            assert code == 200, (code, page)
            if not page["events"]:
                return out
            out += page["events"]
            after = page["events"][-1]["sequence"]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.svc.close()


def make_nodes(n: int = 4, **per_node: Any) -> dict[str, FakeNode]:
    """Fake nodes named node-0..node-{n-1} (the ids smoke.make_config uses)."""
    ids = [f"node-{i}" for i in range(n)]
    return {i: FakeNode(i, [o for o in ids if o != i], **per_node.get(i, {})) for i in ids}


def run_body(
    run_id: str,
    nodes: dict[str, FakeNode],
    *,
    ticks: int = 25,
    seed: int = 1,
    episodes: list[dict[str, Any]] | None = None,
    **plan: Any,
) -> dict[str, Any]:
    cfg = make_config(seed, ticks, len(nodes)).model_dump(mode="json")
    cfg["run_id"] = run_id
    return {
        "run_config": cfg,
        "plan": {
            "node_urls": {k: v.url for k, v in nodes.items()},
            "deadline_ms": 500,
            "episodes": episodes or [{"kind": "train", "seed": seed}],
            **plan,
        },
    }

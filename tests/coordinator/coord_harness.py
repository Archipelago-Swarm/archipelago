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
WORLD_KW = {"n_targets": 0}  # no target ends an episode early; battery comes from the plan
BATTERY_SCALE = 10.0  # nothing ends the episode before max_ticks unless a test lowers it
HOLD_LIMIT_S = 30.0  # safety net only: tests always release or stop their holds
FEEDBACK_KEYS = {
    "run_id", "episode", "tick", "reward", "next_observation", "terminated", "truncated",
    "executed_command", "action_index", "deadline_missed",
}  # fmt: skip
CONFIGURE_KEYS = {
    "command", "run_id", "hyperparameters", "epsilon_schedule", "margin", "world_config",
    "gate_seeds", "n_validation_agents", "encoder_id", "exchange_every_ticks", "seed",
}  # fmt: skip
WORLD_CONFIG_KEYS = {
    "size", "n_targets", "obstacle_density", "sense_radius", "max_ticks", "battery_scale",
    "reward_id",
}  # fmt: skip
RESET_KEYS = {"command", "run_id", "episode", "mode", "fault_schedule"}
EPISODE_END_KEYS = {"command", "run_id", "episode", "tick"}
CONTROL_KEYS = {
    "configure": CONFIGURE_KEYS,
    "reset": RESET_KEYS,
    "episode_end": EPISODE_END_KEYS,
}


def default_policy(node: str, episode: int, tick: int, obs: dict[str, Any]) -> str:
    return random.Random(f"{node}:{episode}:{tick}").choice(ACTIONS)


class Journal:
    """One ordered log shared by all fake nodes: (node, kind, episode, tick, "start" | "end")."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, int, int, str]] = []
        self._lock = threading.Lock()

    def add(self, node: str, kind: str, episode: int, tick: int, phase: str) -> None:
        with self._lock:
            self.entries.append((node, kind, episode, tick, phase))

    def snapshot(self) -> list[tuple[str, str, int, int, str]]:
        with self._lock:
            return list(self.entries)


class FakeNode:
    """Implements /v1/act, /v1/feedback, /v1/control, /v1/status like a node runtime.

    `stall` / `feedback_stall` return a `threading.Event` to hold that request until the test sets
    it (or None): holds are released by the test once it has observed the coordinator's reaction,
    so no outcome depends on how fast the machine is. Wire shapes follow section 14; a deviation
    is recorded in `violations`.
    """

    def __init__(
        self,
        node_id: str,
        others: list[str],
        policy: Callable[[str, int, int, dict[str, Any]], str] = default_policy,
        stall: Callable[[int, int], threading.Event | None] | None = None,
        corrupt: Callable[[int, int], str | None] | None = None,
        feedback_stall: Callable[[int, int], threading.Event | None] | None = None,
        journal: Journal | None = None,
        episode_end_status: int = 202,
        configure_status: int = 200,
        reset_stall: Callable[[int], threading.Event | None] | None = None,
        episode_end_stall: Callable[[int], threading.Event | None] | None = None,
    ) -> None:
        self.configure_status = configure_status
        self.reset_stall, self.episode_end_stall = reset_stall, episode_end_stall
        self.node_id, self.others, self.policy = node_id, others, policy
        self.journal = journal or Journal()
        self.episode_end_status = episode_end_status
        self.held: list[tuple[str, int, int]] = []  # requests that were blocked by a hold
        self.windows = 0
        self.stall, self.corrupt = stall, corrupt
        self.feedback_stall = feedback_stall
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
                out: dict[str, Any] = json.loads(self.rfile.read(n) or b"{}")
                return out

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

    def _hold(self, ev: threading.Event | None, kind: str, ep: int, tick: int) -> None:
        if ev is None:
            return
        with self.lock:
            self.held.append((kind, ep, tick))
        ev.wait(HOLD_LIMIT_S)

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
            cmd = body.get("command")
            ep_no = int(body.get("episode", 0))
            with self.lock:
                self.controls.append(body)
                self.timeline.append(f"control:{cmd}")
            if cmd == "reset" and self.reset_stall:
                self._hold(self.reset_stall(ep_no), "reset", ep_no, 0)
            if cmd == "episode_end" and self.episode_end_stall:
                self._hold(self.episode_end_stall(ep_no), "episode_end", ep_no, 0)
            with self.lock:
                if cmd in CONTROL_KEYS and set(body) != CONTROL_KEYS[cmd]:
                    self.violations.append(f"{cmd} keys {sorted(set(body) ^ CONTROL_KEYS[cmd])}")
                if cmd == "configure":
                    if set(body.get("world_config", {})) != WORLD_CONFIG_KEYS:
                        self.violations.append("configure world_config keys")
                    if any(c["command"] == "reset" for c in self.controls[:-1]):
                        self.violations.append("configure after reset")
                    if self.configure_status != 200:
                        return self.configure_status, {"error": "config conflict"}
                    return 200, {"ok": True, "config_hash": "c" * 16}
                if cmd == "reset":
                    self.mode = body["mode"]
                    self.last_tick = -1
                    self.cache.clear()
                    return 200, {"ok": True, "policy_version": 1}
                if cmd == "episode_end":
                    self.windows += 1
                    return self.episode_end_status, {"window_id": f"w{self.windows}"}
            return 200, {"ok": True, "status": {}}
        if path == "/v1/act":
            self._check_privacy(body)
            ep, tick = body["episode"], body["tick"]
            with self.lock:
                self.acts.append(body)
                self.timeline.append("act")
            self.journal.add(self.node_id, "act", ep, tick, "start")
            self._hold(self.stall(ep, tick) if self.stall else None, "act", ep, tick)
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
            self.journal.add(self.node_id, "act", ep, tick, "end")
            return 200, out
        if path == "/v1/feedback":
            ep, tick = body["episode"], body["tick"]
            with self.lock:
                self.feedback.append(body)
                self.timeline.append("feedback")
                if set(body) != FEEDBACK_KEYS:
                    self.violations.append(f"feedback keys {sorted(set(body) ^ FEEDBACK_KEYS)}")
            self.journal.add(self.node_id, "feedback", ep, tick, "start")
            self._hold(
                self.feedback_stall(ep, tick) if self.feedback_stall else None, "feedback", ep, tick
            )
            with self.lock:
                if self.mode == "eval":
                    return 409, {"error": "eval mode"}
            self.journal.add(self.node_id, "feedback", ep, tick, "end")
            return 200, {
                "accepted": True, "replay_size": len(self.feedback), "train_steps": 0,
                "policy_version": 1,
            }  # fmt: skip
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
        self.plan_file: Path = settings.pop("plan_file", data_dir.parent / "plan.json")
        kw = {"world_kwargs": WORLD_KW, **settings}
        self.settings = Settings(
            coordinator_token=COORD_TOKEN,
            admin_token=ADMIN_TOKEN,
            node_token=NODE_TOKEN,
            data_dir=data_dir,
            plan_file=self.plan_file,
            **kw,
        )
        self.svc = Coordinator(self.settings)
        self.server = make_server(self.svc)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        ).start()

    def call(
        self, method: str, path: str, body: Any = None, token: str | None = COORD_TOKEN
    ) -> tuple[int, dict[str, Any]]:
        """A `RunRequest` is split the way an operator would: its plan goes into the server-side
        plan file and only the run config (and plan name) is sent."""
        if isinstance(body, RunRequest):
            self.plan_file.write_text(json.dumps(body.plan))
            body = body.wire()
        return http(method, self.url + path, token, body)

    def start_run(self, body: dict[str, Any]) -> dict[str, Any]:
        code, out = self.call("POST", "/v1/runs", body)
        assert code == 201, (code, out)
        return out

    def status(self, run_id: str) -> dict[str, Any]:
        code, out = self.call("GET", f"/v1/runs/{run_id}")
        assert code == 200, (code, out)
        return out

    def wait(
        self, run_id: str, pred: Callable[[dict[str, Any]], bool], timeout: float = 60
    ) -> dict[str, Any]:
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

    def command(
        self, run_id: str, cid: str, cmd: str, rev: int | None = None
    ) -> tuple[int, dict[str, Any]]:
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
    """Fake nodes named node-0..node-{n-1} (the ids smoke.make_config uses), one shared journal."""
    ids = [f"node-{i}" for i in range(n)]
    journal = Journal()
    return {
        i: FakeNode(i, [o for o in ids if o != i], journal=journal, **per_node.get(i, {}))
        for i in ids
    }


class RunRequest(dict[str, Any]):
    """`{run_config, plan}` as tests write it; `Live.call` sends only run_config (A9)."""

    @property
    def plan(self) -> dict[str, Any]:
        out: dict[str, Any] = self["plan"]
        return out

    def wire(self) -> dict[str, Any]:
        return {k: v for k, v in self.items() if k != "plan"}


def run_body(
    run_id: str,
    nodes: dict[str, FakeNode],
    *,
    ticks: int = 25,
    seed: int = 1,
    episodes: list[dict[str, Any]] | None = None,
    **plan: Any,
) -> RunRequest:
    cfg = make_config(seed, ticks, len(nodes)).model_dump(mode="json")
    cfg["run_id"] = run_id
    return RunRequest(
        run_config=cfg,
        plan={
            "node_urls": {k: v.url for k, v in nodes.items()},
            "deadline_ms": 500,
            "battery_scale": BATTERY_SCALE,
            "episodes": episodes or [{"kind": "train", "seed": seed}],
            **plan,
        },
    )

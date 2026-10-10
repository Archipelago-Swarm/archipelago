"""Test helpers: fake coordinator client, fake telemetry sink, stalled-peer socket, cluster."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from archipelago_noderuntime.config import Config
from archipelago_noderuntime.runtime import Runtime
from archipelago_sim.env import GridWorld

TOKEN = "unit-test-token-0123456789"
PEER_TOKEN = "unit-peer-token-0123456789"
NOW = "2026-10-10T12:00:00Z"


def make_cfg(tmp, node_id="node-01", node_ids=("node-01", "node-02"), **over) -> Config:
    kw = dict(
        node_id=node_id,
        node_ids=tuple(node_ids),
        control_token=TOKEN,
        peer_token=PEER_TOKEN,
        exchange_every_ticks=0,  # tests opt in to cadence windows explicitly
        window_cancel_wait=1.0,
        checkpoint_dir=tmp / node_id,
        peer_port=0,
        control_port=0,
        capacity=500,
        batch=8,
        lr=1e-3,
        world_size=8,
        world_n_targets=2,
        world_max_ticks=40,
        validation_seeds=(7001, 7002),
        eps_decay_acts=200,
        ship_interval=0.05,
        ship_timeout=1.0,
        peer_timeout=0.5,
        peer_retries=0,
    )
    kw.update(over)
    return Config(**kw)


def obs_json(run_id: str, tag: str, tick: int, o: dict) -> dict:
    """Contract Observation (as JSON) from a GridWorld.observe dict."""
    return {
        "kind": "observation",
        "schema_version": "0.1.0",
        "event_id": f"obs-{tag}-{tick}",
        "run_id": run_id,
        "source_node_id": None,
        "sim_tick": tick,
        "emitted_at_utc": NOW,
        "sequence": tick,
        "crop": o["crop"],
        "known_mask": o["known_mask"],
        "pose": {"x": float(o["pose"][0]), "y": float(o["pose"][1]), "z": 0.0, "heading_rad": 0.0},
        "battery": o["battery"],
        "visible_markers": [[float(x), float(y)] for x, y in o["visible_markers"]],
        "neighbor_summaries": [],
    }


ACTION_IDX = {"stay": 0, "north": 1, "east": 2, "south": 3, "west": 4}


class Client:
    def __init__(self, url, token=TOKEN):
        self.url, self.token = url, token
        self.run = "run-t"  # run id attached to control commands that do not name one

    def call(self, method, path, body=None, token="default", raw=None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        req = urllib.request.Request(self.url + path, data, method=method)
        tok = self.token if token == "default" else token
        if tok:
            req.add_header("Authorization", f"Bearer {tok}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            raw_body = e.read()
            try:
                return e.code, json.loads(raw_body)
            except ValueError:
                return e.code, {"raw": raw_body.decode(errors="replace")}

    def act(self, run, ep, tick, obs, **kw):
        self.run = run
        return self.call(
            "POST",
            "/v1/act",
            {"run_id": run, "episode": ep, "tick": tick, "observation": obs},
            **kw,
        )

    def feedback(
        self, run, ep, tick, reward, nxt, term=False, trunc=False, cmd="stay", missed=False
    ):
        return self.call(
            "POST",
            "/v1/feedback",
            {
                "run_id": run,
                "episode": ep,
                "tick": tick,
                "reward": reward,
                "next_observation": nxt,
                "terminated": term,
                "truncated": trunc,
                "executed_command": cmd,
                "action_index": ACTION_IDX[cmd],
                "deadline_missed": missed,
            },
        )

    def control(self, command, **kw):
        if "run_id" in kw:
            self.run = kw["run_id"]
        return self.call("POST", "/v1/control", {"command": command, "run_id": self.run, **kw})

    def status(self):
        return self.call("GET", "/v1/status")[1]

    def wait_idle(self, timeout=30.0):
        """Poll until the node's background worker has no window running or queued."""
        end = time.time() + timeout
        while time.time() < end:
            if self.status()["window"] == "idle":
                return True
            time.sleep(0.01)
        return False

    def episode_end(self, episode, tick, wait=True):
        """A4: 202 {window_id}; optionally wait for the background window to finish."""
        st, out = self.control("episode_end", episode=episode, tick=tick)
        assert st == 202 and out["window_id"], (st, out)
        if wait:
            assert self.wait_idle()
        return st, out


class MiniCoordinator:
    """A tiny real-world driver: GridWorld stepped by actions that the nodes return over HTTP."""

    def __init__(self, clients: dict[str, Client], size=8, run_id="run-t", max_ticks=500):
        self.clients, self.run_id = clients, run_id
        self.ids = sorted(clients)
        self.world = GridWorld(
            size=size, n_agents=len(self.ids), n_targets=0, max_ticks=max_ticks, sense_radius=2
        )
        self.agent = dict(zip(self.ids, self.world.possible_agents, strict=True))

    def reset(self, episode, mode="train", schedule=None):
        for c in self.clients.values():
            body = {"run_id": self.run_id, "episode": episode, "mode": mode}
            if schedule is not None:
                body["fault_schedule"] = schedule
            st, out = c.control("reset", **body)
            assert st == 200, out

    def run_episode(self, episode, seed, ticks, mode="train", schedule=None, end=False, cadence=0):
        """Run up to `ticks` ticks; returns the number of ticks acted.

        cadence: the nodes' exchange_every_ticks. After each node's act at a cadence tick the
        coordinator waits for that node's window, so cross-node ordering is deterministic.
        """
        self.reset(episode, mode, schedule)
        obs = self.world.reset(seed)
        t = 0
        for t in range(ticks):
            if not self.world.agents:
                break
            acts, sent = {}, {}
            for nid in self.ids:
                a = self.agent[nid]
                if a in self.world.agents:
                    st, out = self.clients[nid].act(
                        self.run_id, episode, t, obs_json(self.run_id, nid, t, obs[a])
                    )
                    assert st == 200, out
                    acts[a] = out["action"]["command"]
                    sent[nid] = a
                    if cadence and t > 0 and t % cadence == 0 and mode == "train":
                        assert self.clients[nid].wait_idle()
            nxt, rew, term, trunc, _ = self.world.step(acts)
            if mode == "train":
                for nid, a in sent.items():
                    st, out = self.clients[nid].feedback(
                        self.run_id,
                        episode,
                        t,
                        rew[a],
                        obs_json(self.run_id, nid, t + 1, nxt[a]),
                        term[a],
                        trunc[a],
                        acts[a],
                    )
                    assert st == 200, out
            obs = nxt
        if end:
            for c in self.clients.values():
                c.episode_end(episode, t + 1)
        return t + 1


class FakeSink:
    """Fake telemetry API ingest: dedupes by event_id; modes ok / down / stall."""

    def __init__(self):
        self.mode = "ok"
        self.events: dict[str, dict] = {}
        self.metas: list[dict] = []
        self.batches = 0
        self.sizes: list[tuple[int, int]] = []  # (events, body bytes) per accepted request
        self.received = 0
        self.connections = 0
        self.lock = threading.Lock()
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(n)
                with outer.lock:
                    outer.connections += 1
                    mode = outer.mode
                if mode == "stall":
                    time.sleep(30)
                if mode == "down":
                    self.send_response(503)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                d = json.loads(body)
                with outer.lock:
                    outer.batches += 1
                    outer.sizes.append((len(d["events"]), n))
                    outer.metas.append({k: v for k, v in d.items() if k != "events"})
                    for r in d["events"]:
                        outer.received += 1
                        outer.events.setdefault(
                            r["event_id"], {"event_id": r["event_id"], "record": r}
                        )
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        class Srv(ThreadingHTTPServer):
            daemon_threads = True

        self.httpd = Srv(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/ingest"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Blackhole:
    """A peer that accepts TCP connections and never answers (a stalled neighbour)."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self.accepted = 0
        self.conns: list[socket.socket] = []
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            self.accepted += 1
            self.conns.append(c)

    def close(self):
        self.sock.close()
        for c in self.conns:
            c.close()


class Cluster:
    """N real runtimes in one process, wired together over real HTTP on localhost."""

    def __init__(self, tmp, ids=("node-01", "node-02"), per_node=None, **over):
        per_node = per_node or {}
        self.runtimes: dict[str, Runtime] = {}
        for nid in ids:
            cfg = make_cfg(tmp, nid, ids, **{**over, **per_node.get(nid, {})})
            self.runtimes[nid] = Runtime(cfg)
        urls = {nid: rt.peer_url for nid, rt in self.runtimes.items()}
        for rt in self.runtimes.values():
            rt.set_peer_urls(urls)
            rt.start()
        self.clients = {nid: Client(rt.control_url) for nid, rt in self.runtimes.items()}

    def node(self, nid):
        return self.runtimes[nid].node

    def close(self):
        for rt in self.runtimes.values():
            rt.stop(checkpoint=False)


def percentile(xs, q):
    return float(np.percentile(np.asarray(xs), q))

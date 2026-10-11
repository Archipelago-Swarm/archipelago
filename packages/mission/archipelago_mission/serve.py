"""Live mission server (stdlib only). The simulation runs on the spot for the requested seed.

python -m archipelago_mission.serve [--port 8765]
GET /api/mission/health
GET /api/mission/run?seed=1002[&uavs=6][&skills=0]  -> full result JSON, computed now
GET /api/mission/summary?seed=1002[&uavs=6]          -> final state + stats, skills on and off
GET /api/mission/stream?seed=1002[&tps=4][&skills=0] -> Server-Sent Events, one tick per 1/tps s
"""

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .sim import MissionConfig, MissionSim, round_floats, run_mission


def _cfg(q: dict) -> MissionConfig:
    uavs = int(q.get("uavs", ["6"])[0])
    if not 1 <= uavs <= 24:
        raise ValueError("uavs must be 1..24")
    return MissionConfig(
        seed=int(q.get("seed", ["1002"])[0]),
        n_uavs=uavs,
        skills_enabled=q.get("skills", ["1"])[0] != "0",
    )


def _arm(cfg: MissionConfig) -> dict:
    r = run_mission(cfg)
    return {"mission": r["frames"][-1]["mission"], "stats": r["stats"]}


def summary(q: dict) -> dict:
    """Final mission state + stats for one map, skills on and off (no frames: small payload)."""
    cfg = _cfg(q)
    off = MissionConfig(**{**cfg.__dict__, "skills_enabled": False})
    on = MissionConfig(**{**cfg.__dict__, "skills_enabled": True})
    return {"seed": cfg.seed, "uavs": cfg.n_uavs, "on": _arm(on), "off": _arm(off)}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, b"")

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/mission/health":
                self._send(200, b'{"ok":true}')
            elif u.path == "/api/mission/run":
                self._send(
                    200,
                    json.dumps(round_floats(run_mission(_cfg(q))), separators=(",", ":")).encode(),
                )
            elif u.path == "/api/mission/summary":
                self._send(
                    200, json.dumps(round_floats(summary(q)), separators=(",", ":")).encode()
                )
            elif u.path == "/api/mission/stream":
                self._stream(_cfg(q), float(q.get("tps", ["4"])[0]))
            else:
                self._send(404, b'{"error":"not found"}')
        except (ValueError, BrokenPipeError, ConnectionResetError) as e:
            if not isinstance(e, (BrokenPipeError, ConnectionResetError)):
                self._send(400, json.dumps({"error": str(e)}).encode())

    def _stream(self, cfg: MissionConfig, tps: float) -> None:
        sim = MissionSim(cfg)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def send(name: str, data: dict) -> None:
            self.wfile.write(
                f"event: {name}\ndata: {json.dumps(round_floats(data), separators=(',', ':'))}\n\n".encode()
            )
            self.wfile.flush()

        send("meta", sim.result()["meta"])
        ev = dec = 0
        while True:
            send(
                "tick",
                {
                    "frame": sim.frames[-1],
                    "events": sim.events[ev:],
                    "decisions": sim.decisions[dec:],
                },
            )
            ev, dec = len(sim.events), len(sim.decisions)
            if sim.status != "RUNNING":
                break
            time.sleep(1.0 / max(0.1, tps))
            sim.step()
        send("end", {"stats": sim.result()["stats"]})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    print(f"mission server on http://127.0.0.1:{a.port}/api/mission/stream?seed=1002")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

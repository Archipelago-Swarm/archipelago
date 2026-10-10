"""Direct private HTTP peer endpoint over the transport contract (T05). Stdlib only."""

from __future__ import annotations

import base64
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3] / "transport"))
from archipelago_transport import MAX_PAYLOAD, Envelope, Network  # noqa: E402


class PeerServer:
    """Accepts POST /envelope from peers; gates and validation are the shared Network rules."""

    def __init__(self, node: str, links, host: str = "127.0.0.1", port: int = 0):
        # shortcut: binds loopback by default; private-network binding is the caller's choice
        self.node, self.net, self.lock = node, Network(links), threading.Lock()
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                if self.path != "/envelope":
                    return self._reply(404)
                if n > 2 * MAX_PAYLOAD:
                    return self._reply(413)
                try:
                    d = json.loads(self.rfile.read(n))
                    payload = base64.b64decode(d["payload"])
                    env = Envelope(
                        d["src"], outer.node, d["seq"], payload, d["version"], d["digest"]
                    )
                except (ValueError, KeyError, TypeError):
                    return self._reply(400)
                self._reply(outer.accept(env))

            def _reply(self, code):
                self.send_response(code)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer((host, port), H)
        self.url = f"http://{host}:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def accept(self, env: Envelope) -> int:
        with self.lock:
            before = sum(self.net.stats.rejected.values())
            self.net.send(env)
            self.net.tick()
            return 200 if sum(self.net.stats.rejected.values()) == before else 422

    def receive(self):
        with self.lock:
            return self.net.receive(self.node)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def post(url: str, env: Envelope, timeout: float = 1.0, retries: int = 2) -> int:
    """POST with timeout+retry on connection failure; returns HTTP status, 0 if unreachable."""
    body = json.dumps(
        {
            "src": env.src,
            "seq": env.seq,
            "version": env.version,
            "digest": env.digest,
            "payload": base64.b64encode(env.payload).decode(),
        }
    ).encode()
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(
                url + "/envelope", body, {"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code  # a verdict, not a transport failure: do not retry
        except OSError:
            continue
    return 0

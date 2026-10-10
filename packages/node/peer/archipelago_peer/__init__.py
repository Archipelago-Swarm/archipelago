"""Direct private HTTP peer endpoint over the transport contract (T05). Stdlib only."""

from __future__ import annotations

import base64
import hmac
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from archipelago_transport import MAX_PAYLOAD, Envelope, Network, load_manifest


class PeerServer:
    """Accepts POST /envelope from peers; gates and validation are the shared Network rules."""

    def __init__(
        self,
        node,
        links,
        host: str = "127.0.0.1",
        port: int = 0,
        urls=None,
        on_catchup=None,
        token: str | None = None,
        allowed_src=None,
        **faults,
    ):
        """token: shared PEER_TOKEN bearer (A8); None disables auth (in-process tests only).

        allowed_src: the declared id list of the token holders; an envelope whose ``src`` is not
        in it is refused (403) even when the bearer is right.
        """
        # shortcut: binds loopback by default; private-network binding is the caller's choice
        self.node, self.net, self.lock = node, Network(links, **faults), threading.Lock()
        self.urls, self.on_catchup = urls or {}, on_catchup
        self.token = token.encode() if token else None
        self.allowed_src = frozenset(allowed_src) if allowed_src is not None else None
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                try:
                    n = int(self.headers.get("Content-Length", 0))
                except ValueError:
                    n = -1
                if n < 0:
                    return self._reply(400)
                # Always consume the request body before replying: closing with unread bytes
                # makes Windows reset the socket, so the client sees WinError 10053 instead
                # of the status. Oversized bodies are drained in bounded chunks and dropped.
                body = self.rfile.read(n) if n <= 2 * MAX_PAYLOAD else self._drain(n)
                if not self._authorized():
                    return self._reply(401)
                if self.path == "/catchup":  # a reconnected peer asks for the newest update
                    try:
                        who = json.loads(body)["node"]
                    except (ValueError, KeyError, TypeError):
                        return self._reply(400)
                    if outer.allowed_src is not None and who not in outer.allowed_src:
                        return self._reply(403)
                    if outer.on_catchup is None:
                        return self._reply(404)
                    outer.on_catchup(who)
                    return self._reply(200)
                if self.path != "/envelope":
                    return self._reply(404)
                if n > 2 * MAX_PAYLOAD:
                    return self._reply(413)
                try:
                    d = json.loads(body)
                    payload = base64.b64decode(d["payload"])
                    env = Envelope(
                        d["src"], outer.node, d["seq"], payload, d["version"], d["digest"]
                    )
                    if not (
                        isinstance(env.src, str)
                        and isinstance(env.digest, str)
                        and type(env.seq) is int
                        and type(env.version) is int
                    ):
                        raise TypeError("bad field type")
                except (ValueError, KeyError, TypeError):
                    return self._reply(400)
                if outer.allowed_src is not None and env.src not in outer.allowed_src:
                    return self._reply(403)
                self._reply(outer.accept(env))

            def _authorized(self):
                if outer.token is None:
                    return True
                scheme, _, given = self.headers.get("Authorization", "").partition(" ")
                return scheme == "Bearer" and hmac.compare_digest(given.encode(), outer.token)

            def _drain(self, n):
                left = min(n, 8 * MAX_PAYLOAD)
                while left > 0:
                    chunk = self.rfile.read(min(65536, left))
                    if not chunk:
                        break
                    left -= len(chunk)
                return b""

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
            if (
                sum(self.net.stats.rejected.values()) != before
            ):  # shortcut: counts, not per-envelope verdicts
                return 422
            # accepted but deferred by the fault schedule (delay/bandwidth): not delivered yet
            return 200 if self.net.last_seq(env.dst, env.src) >= env.seq else 202

    def set_links(self, links):
        """Cut/restore links; a newly opened inbound link makes this node request the latest."""
        with self.lock:
            opened = {s for s, d in set(links) - self.net.links if d == self.node}
            self.net.links = set(links)
        for src in sorted(opened & set(self.urls)):
            _request_catchup(self.urls[src], self.node, self.token.decode() if self.token else None)

    def receive(self):
        with self.lock:
            return self.net.receive(self.node)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _headers(token: str | None) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def post(
    url: str, env: Envelope, timeout: float = 1.0, retries: int = 2, token: str | None = None
) -> int:
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
            req = urllib.request.Request(url + "/envelope", body, _headers(token))
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code  # a verdict, not a transport failure: do not retry
        except OSError:
            continue
    return 0


def _request_catchup(url: str, me: str, token: str | None = None) -> int:
    req = urllib.request.Request(
        url + "/catchup", json.dumps({"node": me}).encode(), _headers(token)
    )
    try:
        with urllib.request.urlopen(req, timeout=0.5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return 0  # sender unreachable; the next reconnect asks again


def serve_manifest(text: str, **faults) -> dict[str, PeerServer]:
    """Start one PeerServer per manifest node, bound to its manifest URL."""
    urls, links = load_manifest(text)
    out = {}
    for node, url in urls.items():
        u = urlparse(url)
        out[node] = PeerServer(
            node, links, u.hostname or "127.0.0.1", u.port or 0, urls=urls, **faults
        )
    return out


class PeerClient:
    """Sends to manifest peers; remembers the latest envelope per peer for bounded catch-up."""

    def __init__(
        self,
        node: str,
        urls: dict[str, str],
        timeout: float = 1.0,
        retries: int = 2,
        token: str | None = None,
        seq_source=None,
    ):
        """seq_source: object with ``next() -> int`` (e.g. a persisted SequenceAllocator), so the
        client's ``seq`` keeps rising across restarts; receivers drop seq <= last seen as stale."""
        self.node, self.urls, self.timeout, self.retries = node, urls, timeout, retries
        self.token, self.seq_source = token, seq_source
        self.seq = 0
        self.latest: dict[str, Envelope] = {}

    def next_seq(self) -> int:
        if self.seq_source is not None:
            self.seq = self.seq_source.next()
        else:
            self.seq += 1
        return self.seq

    def send(self, dst: str, payload: bytes) -> int:
        env = self.latest[dst] = Envelope.make(self.node, dst, self.next_seq(), payload)
        return post(self.urls[dst], env, self.timeout, self.retries, self.token)

    def catch_up(self, dst: str) -> int:
        """On reconnect, resend only the newest update (never a backlog)."""
        if dst not in self.latest:
            return 0  # nothing sent yet, nothing to catch up
        return post(self.urls[dst], self.latest[dst], self.timeout, self.retries, self.token)

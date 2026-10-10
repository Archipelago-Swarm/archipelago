"""Stdlib HTTP front end for the coordinator service (section 12 of live-runtime.md)."""

from __future__ import annotations

import hmac
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .service import Coordinator

MAX_BODY = 1 << 20
_RUN = r"/v1/runs/([A-Za-z0-9_.:-]{1,128})"
ROUTES: list[tuple[str, re.Pattern[str], str]] = [
    ("POST", re.compile(r"/v1/runs"), "create"),
    ("GET", re.compile(_RUN), "get"),
    ("POST", re.compile(_RUN + r"/commands"), "command"),
    ("GET", re.compile(_RUN + r"/events"), "events"),
    ("GET", re.compile(_RUN + r"/snapshot"), "snapshot"),
    ("GET", re.compile(r"/readyz"), "readyz"),
    ("GET", re.compile(r"/healthz"), "healthz"),
]


def _bearer(header: str | None) -> str:
    if header and header.startswith("Bearer "):
        return header[7:].strip()
    return ""


def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def make_server(svc: Coordinator, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        disable_nagle_algorithm = True

        def log_message(self, fmt: str, *args: Any) -> None:  # no request logging (tokens, noise)
            return

        def _send(
            self, code: int, body: dict[str, Any], extra: dict[str, str] | None = None
        ) -> None:
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def _read_json(self) -> tuple[Any, tuple[int, dict[str, Any]] | None]:
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                self.close_connection = True
                return None, (413, {"error": "body_too_large"})
            raw = self.rfile.read(n) if n else b""
            try:
                return json.loads(raw or b"null"), None
            except ValueError:
                return None, (400, {"error": "invalid_json"})

        def _handle(self, method: str) -> None:
            u = urlsplit(self.path)
            path = u.path.rstrip("/") or "/"
            matched: tuple[str, re.Match[str]] | None = None
            path_known = False
            for m, rx, name in ROUTES:
                mo = rx.fullmatch(path)
                if mo:
                    path_known = True
                    if m == method:
                        matched = (name, mo)
                        break
            if matched is None:
                code = 405 if path_known else 404
                self._drain()
                self._send(code, {"error": "method_not_allowed" if path_known else "not_found"})
                return
            name, mo = matched
            if name == "healthz":
                self._send(200, {"ok": True})
                return
            token = _bearer(self.headers.get("Authorization"))
            is_admin = _eq(token, svc.settings.admin_token)
            is_api = _eq(token, svc.settings.coordinator_token)
            if not (is_admin or is_api):
                self._drain()
                self._send(401, {"error": "unauthorized"}, {"WWW-Authenticate": "Bearer"})
                return
            if name == "snapshot" and not is_admin:
                self._drain()
                self._send(403, {"error": "admin_token_required"})
                return
            if name != "snapshot" and not is_api:
                self._drain()
                self._send(403, {"error": "coordinator_token_required"})
                return
            code, body = self._dispatch(name, mo)
            self._send(code, body)

        def _drain(self) -> None:
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = 0
            if 0 < n <= MAX_BODY:
                self.rfile.read(n)
            elif n > MAX_BODY:
                self.close_connection = True

        def _dispatch(self, name: str, mo: re.Match[str]) -> tuple[int, dict[str, Any]]:
            if name == "readyz":
                return svc.readiness()
            if name in ("create", "command"):
                payload, err = self._read_json()
                if err:
                    return err
                if name == "create":
                    return svc.create_run(payload)
                return svc.command(mo.group(1), payload)
            run_id = mo.group(1)
            if name == "get":
                return svc.get_run(run_id)
            if name == "snapshot":
                return svc.snapshot(run_id)
            q = parse_qs(urlsplit(self.path).query)
            try:
                after = int(q.get("after_sequence", ["0"])[0])
                limit = int(q.get("limit", ["500"])[0])
            except ValueError:
                return 400, {"error": "bad_query"}
            if after < 0 or limit < 1:
                return 400, {"error": "bad_query"}
            return svc.events(run_id, after, min(limit, 5000))

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

        def do_PUT(self) -> None:
            self._handle("PUT")

        def do_DELETE(self) -> None:
            self._handle("DELETE")

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    return Server((host, port), Handler)

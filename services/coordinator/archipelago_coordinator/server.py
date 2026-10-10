"""Stdlib HTTP server for the API -> coordinator interface (live-runtime.md section 12)."""

from __future__ import annotations

import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from archipelago_contracts.models import RunConfig

from .core import CommandError, Coordinator

MAX_BODY = 256 * 1024
MIN_TOKEN = 16


def tokens_from_env() -> tuple[str, str]:
    token, admin = (
        os.environ.get("COORDINATOR_TOKEN", ""),
        os.environ.get("COORDINATOR_ADMIN_TOKEN", ""),
    )
    if len(token) < MIN_TOKEN or len(admin) < MIN_TOKEN:
        raise SystemExit("COORDINATOR_TOKEN and COORDINATOR_ADMIN_TOKEN must be set (>=16 chars)")
    return token, admin


def make_server(
    coord: Coordinator, token: str, admin_token: str, host: str, port: int
) -> ThreadingHTTPServer:
    runner: dict[str, threading.Thread] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:  # keep stderr quiet
            return

        def _send(self, code: int, body: Any) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self, secret: str) -> bool:
            sent = self.headers.get("Authorization", "")
            return hmac.compare_digest(sent, f"Bearer {secret}")

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BODY:
                raise CommandError("body too large")
            return dict(json.loads(self.rfile.read(length) or b"{}"))

        def do_GET(self) -> None:
            url = urlparse(self.path)
            parts = url.path.strip("/").split("/")
            if url.path == "/healthz":
                return self._send(200, {"ok": True})
            if url.path == "/readyz":
                ready = coord.adapter is not None and bool(coord.nodes)
                return self._send(200 if ready else 503, {"ready": ready})
            if parts[:2] == ["v1", "runs"] and len(parts) == 4 and parts[3] == "snapshot":
                if not self._authorized(admin_token):
                    return self._send(401, {"error": "admin token required"})
                return self._send(200, coord.privileged_snapshot())
            if not self._authorized(token):
                return self._send(401, {"error": "unauthorized"})
            if parts[:2] == ["v1", "runs"] and len(parts) == 3:
                return self._send(200, coord.run_view())
            if parts[:2] == ["v1", "runs"] and len(parts) == 4 and parts[3] == "events":
                q = parse_qs(url.query)
                after = int(q.get("after_sequence", ["0"])[0])
                limit = min(int(q.get("limit", ["500"])[0]), 1000)
                return self._send(200, coord.spool.read(after, limit))
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._authorized(token):
                return self._send(401, {"error": "unauthorized"})
            parts = urlparse(self.path).path.strip("/").split("/")
            try:
                body = self._body()
                if parts == ["v1", "runs"]:
                    run_id = coord.start_run(RunConfig.model_validate(body["run_config"]))
                    thread = threading.Thread(target=coord.run_to_end, daemon=True)
                    runner["t"] = thread
                    thread.start()
                    return self._send(201, {"run_id": run_id, "status": coord.status})
                if parts[:2] == ["v1", "runs"] and len(parts) == 4 and parts[3] == "commands":
                    reply = coord.command(
                        body["command_id"], body["command"], body.get("expected_revision")
                    )
                    return self._send(200, reply)
            except CommandError as error:
                code = (
                    409
                    if "active" in str(error) or "stale" in str(error) or "cannot" in str(error)
                    else 400
                )
                return self._send(code, {"error": str(error)})
            except (KeyError, ValueError) as error:
                return self._send(400, {"error": f"bad request: {error}"})
            self._send(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), Handler)

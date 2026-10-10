"""Stdlib HTTP front for the node (live-runtime.md section 3). Bearer auth, 256 KiB body cap."""

from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pydantic import ValidationError

from .node import ApiError, Node
from .protocol import CONTROL, MAX_BODY, ActRequest, FeedbackRequest

DRAIN_LIMIT = 4 * MAX_BODY  # oversized bodies are drained (bounded) so the client sees the 413


def _problem(e: ValidationError) -> tuple[int, dict]:
    errs = e.errors(include_url=False, include_context=False, include_input=False)
    status = 400 if any(x["type"] == "json_invalid" for x in errs) else 422
    detail = [{"loc": [str(p) for p in x["loc"]], "msg": x["msg"]} for x in errs[:10]]
    return status, {"error": "invalid_request", "detail": detail}


class ControlServer:
    def __init__(self, node: Node, host: str, port: int):
        outer = self
        self.node = node
        token = node.cfg.control_token.encode()

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "archipelago-node"

            def _send(self, code: int, obj: dict) -> None:
                body = json.dumps(obj, allow_nan=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                if code >= 400 and code != 409:
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self) -> bool:
                h = self.headers.get("Authorization", "")
                scheme, _, given = h.partition(" ")
                return scheme == "Bearer" and hmac.compare_digest(given.encode(), token)

            def _read_body(self) -> bytes | None:
                """Body bytes, or None after having replied (411/413)."""
                raw = self.headers.get("Content-Length")
                if raw is None or self.headers.get("Transfer-Encoding"):
                    self._send(411, {"error": "length_required"})
                    return None
                try:
                    n = int(raw)
                except ValueError:
                    n = -1
                if n < 0:
                    self._send(400, {"error": "bad_content_length"})
                    return None
                if n > MAX_BODY:
                    left = min(n, DRAIN_LIMIT)
                    while left > 0:
                        chunk = self.rfile.read(min(65536, left))
                        if not chunk:
                            break
                        left -= len(chunk)
                    self._send(413, {"error": "too_large", "max_bytes": MAX_BODY})
                    return None
                return self.rfile.read(n)

            def _drain_small(self) -> None:
                try:
                    n = int(self.headers.get("Content-Length", 0))
                except ValueError:
                    return
                if 0 < n <= MAX_BODY:
                    self.rfile.read(n)

            def do_GET(self) -> None:
                try:
                    if self.path == "/healthz":
                        return self._send(200, {"ok": True})
                    if self.path != "/v1/status":
                        return self._send(
                            405 if self.path.startswith("/v1/") else 404, {"error": "not_found"}
                        )
                    if not self._authorized():
                        return self._send(401, {"error": "unauthorized"})
                    self._send(200, outer.node.status())
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_POST(self) -> None:
                try:
                    routes = {"/v1/act": outer.act, "/v1/feedback": outer.feedback,
                              "/v1/control": outer.control}  # fmt: skip
                    fn = routes.get(self.path)
                    if fn is None:
                        self._drain_small()
                        return self._send(
                            405 if self.path == "/v1/status" else 404, {"error": "not_found"}
                        )
                    if not self._authorized():
                        self._drain_small()
                        return self._send(401, {"error": "unauthorized"})
                    body = self._read_body()
                    if body is None:
                        return
                    try:
                        code, obj = 200, fn(body)
                    except ValidationError as e:
                        code, obj = _problem(e)
                    except ApiError as e:
                        code, obj = e.status, {"error": e.code, "detail": e.detail}
                    except Exception:  # never leak internals over the wire
                        code, obj = 500, {"error": "internal"}
                        outer.node.counters["internal_errors"] = (
                            outer.node.counters.get("internal_errors", 0) + 1
                        )
                    self._send(code, obj)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *a) -> None:
                pass

        class Srv(ThreadingHTTPServer):
            daemon_threads = True
            request_queue_size = 128

        self.httpd = Srv((host, port), H)
        self.port = self.httpd.server_port
        self.url = f"http://{host}:{self.port}"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    # --- route bodies ------------------------------------------------------------------------
    def act(self, body: bytes) -> dict:
        return self.node.act(ActRequest.model_validate_json(body))

    def feedback(self, body: bytes) -> dict:
        return self.node.feedback(FeedbackRequest.model_validate_json(body))

    def control(self, body: bytes) -> dict:
        c = CONTROL.validate_json(body)
        n = self.node
        match c.command:
            case "reset":
                return n.control_reset(c)
            case "pause":
                return n.control_pause(True)
            case "resume":
                return n.control_pause(False)
            case "set_schedule":
                return n.control_set_schedule(c)
            case "checkpoint":
                return {**n.checkpoint(), "status": n.status()}
            case "episode_end":
                return n.request_episode_end(c.tick, c.wait)
            case "stop":
                n.stop_event.set()
                return {"ok": True, "stopping": True}
        raise ApiError(400, "unknown_command")

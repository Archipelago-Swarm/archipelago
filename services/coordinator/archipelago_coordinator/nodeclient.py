"""Node HTTP client: bearer auth, per-thread keep-alive, concurrent fan-out with a deadline."""

from __future__ import annotations

import http.client
import json
import socket
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from time import monotonic
from typing import Any
from urllib.parse import urlsplit


@dataclass
class Reply:
    status: int = 0
    body: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 300


class NodeClient:
    def __init__(self, token: str, workers: int = 48) -> None:
        self._token = token
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="node-call")
        self._local = threading.local()

    def call(
        self,
        base_url: str,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        timeout: float,
        keepalive: bool = True,
    ) -> Reply:
        """One request; never raises. Retries once only if a reused keep-alive socket was dead."""
        u = urlsplit(base_url)
        key = (u.scheme, u.netloc)
        conns: dict[Any, http.client.HTTPConnection] = self._local.__dict__.setdefault("c", {})
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        if not keepalive:  # probes must prove a fresh connection works
            headers["Connection"] = "close"
        for attempt in (0, 1):
            conn = conns.get(key) if keepalive else None
            reused = conn is not None
            if conn is None:
                cls = (
                    http.client.HTTPSConnection
                    if u.scheme == "https"
                    else http.client.HTTPConnection
                )
                conn = cls(u.netloc, timeout=timeout)
                if keepalive:
                    conns[key] = conn
            conn.timeout = timeout
            try:
                fresh = conn.sock is None
                if fresh:
                    conn.connect()
                sock = conn.sock
                if sock is None:  # connect() either set it or raised
                    raise OSError("no socket after connect")
                if fresh:
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.settimeout(timeout)
                conn.request(method, u.path.rstrip("/") + path, body=data, headers=headers)
                resp = conn.getresponse()
                raw = resp.read(1 << 20)
                if resp.will_close or not keepalive:
                    conn.close()
                    if keepalive:
                        conns.pop(key, None)
                try:
                    parsed = json.loads(raw) if raw else {}
                except ValueError:
                    return Reply(resp.status, {}, "invalid JSON response")
                return Reply(resp.status, parsed if isinstance(parsed, dict) else {}, None)
            except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError) as e:
                conn.close()
                if keepalive:
                    conns.pop(key, None)
                if reused and attempt == 0:
                    continue
                return Reply(0, {}, f"{type(e).__name__}: {e}")
            except (OSError, http.client.HTTPException) as e:
                conn.close()
                if keepalive:
                    conns.pop(key, None)
                return Reply(0, {}, f"{type(e).__name__}: {e}")
        return Reply(0, {}, "unreachable")  # pragma: no cover

    def fanout(
        self, tasks: dict[str, Callable[[], Reply]], timeout: float
    ) -> dict[str, Reply | None]:
        """Run tasks concurrently; a task not finished within `timeout` seconds yields None.

        Its eventual result is discarded (late responses never reach the caller).
        """
        futs: dict[str, Future[Reply]] = {k: self._pool.submit(fn) for k, fn in tasks.items()}
        deadline = monotonic() + timeout
        wait(list(futs.values()), timeout=max(0.0, deadline - monotonic()))
        out: dict[str, Reply | None] = {}
        for k, f in futs.items():
            out[k] = f.result() if f.done() and not f.cancelled() else None
        return out

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

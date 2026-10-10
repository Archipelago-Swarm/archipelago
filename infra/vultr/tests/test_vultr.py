import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from archipelago_ops.vultr import VultrClient, VultrError, build_inventory

KEY = "SUPERSECRETVULTRKEY1234567890"
SEEN: dict[str, Any] = {"auth": [], "methods": []}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a: Any) -> None:  # silence
        pass

    def _send(self, code: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        SEEN["auth"].append(self.headers.get("Authorization"))
        SEEN["methods"].append("GET")
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            return self._send(401, {"error": f"bad key {self.headers.get('Authorization')}"})
        path = self.path.split("?")[0]
        if path == "/v2/account":
            return self._send(200, {"account": {"balance": -5.5, "pending_charges": 1.25}})
        if path == "/v2/instances":
            if "cursor=p2" in self.path:
                return self._send(
                    200, {"instances": [{"id": "b", "plan": "vc2-2c-4gb"}], "meta": {}}
                )
            return self._send(
                200,
                {
                    "instances": [{"id": "a", "plan": "vc2-1c-1gb", "main_ip": "1.2.3.4"}],
                    "meta": {"links": {"next": "p2"}},
                },
            )
        if path == "/v2/plans":
            return self._send(
                200,
                {"plans": [{"id": "vc2-2c-4gb", "monthly_cost": 20, "vcpu_count": 2, "ram": 4096}]},
            )
        if path == "/v2/regions":
            return self._send(200, {"regions": [{"id": "ewr", "city": "NJ"}]})
        return self._send(404, {})

    def do_POST(self) -> None:
        SEEN["methods"].append("POST")
        self._send(405, {})


@pytest.fixture(scope="module")
def base() -> Any:
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v2"
    srv.shutdown()


def test_inventory_and_pagination(base: str) -> None:
    inv = build_inventory(VultrClient(KEY, base), "2026-01-01T00:00:00+00:00")
    assert [i["id"] for i in inv["instances"]] == ["a", "b"]
    assert "main_ip" not in inv["instances"][0]
    assert inv["plans"]["vc2-2c-4gb"] == {"monthly_cost": "20", "vcpu": 2, "ram_mb": 4096}
    assert inv["account"] == {"balance": "-5.5", "pending_charges": "1.25"}
    assert inv["regions"] == ["ewr"]
    assert set(SEEN["methods"]) == {"GET"}
    assert KEY not in json.dumps(inv)


def test_key_never_in_repr_or_errors(base: str) -> None:
    c = VultrClient("wrong-" + KEY[:8], base)
    assert "wrong-" not in repr(c) and "wrong-" not in str(c)
    with pytest.raises(VultrError) as ei:
        c.account()
    text = str(ei.value) + repr(ei.value) + repr(ei.value.__cause__)
    assert "wrong-" not in text and KEY not in text
    assert "401" in text


def test_key_only_from_env(monkeypatch: pytest.MonkeyPatch, base: str) -> None:
    monkeypatch.delenv("VULTR_API_KEY", raising=False)
    with pytest.raises(VultrError, match="VULTR_API_KEY"):
        VultrClient.from_env(base)
    monkeypatch.setenv("VULTR_API_KEY", KEY)
    assert VultrClient.from_env(base).account()["balance"] == "-5.5"


def test_refuses_cleartext_remote_base() -> None:
    with pytest.raises(VultrError):
        VultrClient(KEY, "http://api.example.com/v2")


def test_unreachable_error_has_no_key() -> None:
    with pytest.raises(VultrError) as ei:
        VultrClient(KEY, "http://127.0.0.1:1/v2", timeout=1).account()
    assert KEY not in str(ei.value)

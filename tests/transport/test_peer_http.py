import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "packages" / "node" / "peer"))
from archipelago_peer import PeerServer, post  # noqa: E402
from archipelago_transport import Envelope  # noqa: E402


def test_http_gate_dedupe_and_unreachable():
    srv = PeerServer("b", {("a", "b")})
    try:
        assert post(srv.url, Envelope.make("a", "b", 1, b"hi")) == 200
        assert post(srv.url, Envelope.make("a", "b", 1, b"hi")) == 422  # duplicate
        assert post(srv.url, Envelope.make("c", "b", 1, b"hi")) == 422  # cut link
        assert srv.receive().payload == b"hi" and srv.receive() is None
    finally:
        srv.close()
    assert post(srv.url, Envelope.make("a", "b", 2, b"x"), timeout=0.2, retries=1) == 0

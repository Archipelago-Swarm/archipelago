import json
import socket
import urllib.error
import urllib.request

from archipelago_peer import PeerClient, PeerServer, post, serve_manifest
from archipelago_transport import Envelope, load_manifest


def _raw(url, path, body, length=None):
    req = urllib.request.Request(url + path, body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=1) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def _doc(env, **over):
    import base64

    d = {
        "src": env.src,
        "seq": env.seq,
        "version": env.version,
        "digest": env.digest,
        "payload": base64.b64encode(env.payload).decode(),
    }
    return json.dumps({**d, **over}).encode()


def test_http_gate_dedupe_and_unreachable():
    srv = PeerServer("b", {("a", "b")})
    try:
        assert post(srv.url, Envelope.make("a", "b", 1, b"hi")) == 200
        assert post(srv.url, Envelope.make("a", "b", 1, b"hi")) == 422  # duplicate
        assert post(srv.url, Envelope.make("a", "b", 0, b"hi")) == 422  # stale
        assert post(srv.url, Envelope.make("c", "b", 1, b"hi")) == 422  # cut link
        assert srv.receive().payload == b"hi" and srv.receive() is None
    finally:
        srv.close()
    assert post(srv.url, Envelope.make("a", "b", 2, b"x"), timeout=0.2, retries=1) == 0


def test_http_bad_requests():
    srv = PeerServer("b", {("a", "b")})
    try:
        e = Envelope.make("a", "b", 1, b"hi")
        assert _raw(srv.url, "/nope", _doc(e)) == 404
        assert _raw(srv.url, "/envelope", b"not json") == 400
        assert _raw(srv.url, "/envelope", b'{"src": "a"}') == 400
        assert _raw(srv.url, "/envelope", _doc(e, digest="0" * 64)) == 422  # bad hash
        assert _raw(srv.url, "/envelope", _doc(e, version=99)) == 422
        assert post(srv.url, Envelope.make("a", "b", 2, b"x" * 200000)) == 413
        assert srv.receive() is None
    finally:
        srv.close()


def test_http_fault_schedule_is_not_reported_as_accepted():
    lossy = PeerServer("b", {("a", "b")}, loss=1.0)
    slow = PeerServer("b", {("a", "b")}, delay=5)
    try:
        assert post(lossy.url, Envelope.make("a", "b", 1, b"x")) == 422
        assert lossy.receive() is None
        assert post(slow.url, Envelope.make("a", "b", 1, b"x")) == 202
        assert slow.receive() is None
    finally:
        lossy.close()
        slow.close()


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_manifest_wiring_and_reconnect_catch_up():
    pa, pb = _free_port(), _free_port()
    text = json.dumps(
        {
            "nodes": {"a": f"http://127.0.0.1:{pa}", "b": f"http://127.0.0.1:{pb}"},
            "links": [["a", "b"]],
        }
    )
    servers = serve_manifest(text)
    try:
        urls, _ = load_manifest(text)
        a = PeerClient("a", urls, timeout=0.2, retries=0)
        assert a.send("b", b"v1") == 200
        # b's server restarts (partition): sends fail, only the newest is kept
        servers["b"].close()
        assert a.send("b", b"v2") == 0 and a.send("b", b"v3") == 0
        servers["b"] = PeerServer("b", {("a", "b")}, port=pb)
        assert a.catch_up("b") == 200
        got = servers["b"].receive()
        assert got.payload == b"v3" and servers["b"].receive() is None
    finally:
        for s in servers.values():
            s.close()


def test_cut_and_restore_link_receiver_requests_latest_only():
    pa, pb = _free_port(), _free_port()
    text = json.dumps(
        {
            "nodes": {"a": f"http://127.0.0.1:{pa}", "b": f"http://127.0.0.1:{pb}"},
            "links": [["a", "b"]],
        }
    )
    servers = serve_manifest(text)
    try:
        urls, _ = load_manifest(text)
        a = PeerClient("a", urls, timeout=0.2, retries=0)
        servers["a"].on_catchup = a.catch_up
        assert a.send("b", b"v1") == 200
        servers["b"].set_links(set())  # cut
        assert a.send("b", b"v2") == 422 and a.send("b", b"v3") == 422
        servers["b"].set_links({("a", "b")})  # restore -> b asks a for the newest only
        got = [servers["b"].receive(), servers["b"].receive(), servers["b"].receive()]
        assert [g.payload for g in got if g] == [b"v1", b"v3"]
    finally:
        for s in servers.values():
            s.close()


def test_payload_over_bandwidth_is_not_stranded():
    srv = PeerServer("b", {("a", "b")}, bandwidth=10)
    try:
        assert post(srv.url, Envelope.make("a", "b", 1, b"x" * 20)) == 200
        assert srv.receive().seq == 1
        assert post(srv.url, Envelope.make("a", "b", 2, b"y")) == 200
    finally:
        srv.close()


def _raw_hdr(srv, headers, body=b""):
    import http.client

    c = http.client.HTTPConnection(srv.url.split("//")[1], timeout=2)
    c.putrequest("POST", "/envelope", skip_accept_encoding=True)
    for k, v in headers.items():
        c.putheader(k, v)
    c.endheaders(body)
    return c.getresponse().status


def test_malformed_requests_get_400():
    srv = PeerServer("b", {("a", "b")})
    try:
        assert _raw_hdr(srv, {"Content-Length": "-1"}) == 400
        assert _raw_hdr(srv, {"Content-Length": "abc"}) == 400
        for d in (
            {"src": ["x"], "seq": 1, "version": 1, "digest": "", "payload": ""},
            {"src": "a", "seq": "1", "version": 1, "digest": "", "payload": ""},
        ):
            b = json.dumps(d).encode()
            assert _raw_hdr(srv, {"Content-Length": str(len(b))}, b) == 400
    finally:
        srv.close()


def test_catch_up_before_any_send_is_noop():
    assert PeerClient("a", {"b": "http://127.0.0.1:1"}).catch_up("b") == 0

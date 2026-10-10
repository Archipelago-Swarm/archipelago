import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "packages" / "transport"))
from archipelago_transport import MAX_PAYLOAD, Envelope, Network, Telemetry, load_manifest  # noqa: E402


def mk(src, dst, seq, p=b"x"):
    return Envelope.make(src, dst, seq, p)


def test_cut_link_blocked_allowed_works():
    net = Network({("a", "b")})
    assert not net.send(mk("b", "a", 1))
    assert net.send(mk("a", "b", 1))
    net.tick()
    assert net.receive("a") is None and net.receive("b").seq == 1


def test_reject_duplicate_stale_oversized_badhash():
    net = Network({("a", "b")})
    for s in (2, 2, 1):
        net.send(mk("a", "b", s))
    assert not net.send(mk("a", "b", 3, b"x" * (MAX_PAYLOAD + 1)))
    bad = Envelope("a", "b", 9, b"x", 1, "bogus")
    net.send(bad)
    net.tick()
    assert net.stats.rejected == {"oversized": 1, "duplicate_or_stale": 2, "hash": 1}
    assert net.receive("b").seq == 2 and net.receive("b") is None


def test_reconnect_sends_only_latest():
    net = Network(set())
    for s in range(1, 6):
        net.send(mk("a", "b", s))
    net.set_links({("a", "b")})
    net.tick()
    assert [net.receive("b").seq, net.receive("b")][0] == 5 and net.receive("b") is None


def test_seeded_loss_reproducible_and_send_nonblocking():
    def run():
        n = Network({("a", "b")}, seed=7, loss=0.5)
        return [n.send(mk("a", "b", i)) for i in range(20)]

    assert run() == run()


def test_delay_bandwidth_and_byte_stats():
    net = Network({("a", "b")}, delay=2, bandwidth=3)
    net.send(mk("a", "b", 1, b"xx"))
    net.send(mk("a", "b", 2, b"yy"))
    net.tick()
    assert net.receive("b") is None  # still in flight
    net.tick()
    assert net.receive("b").seq == 1 and net.receive("b") is None  # 3-byte budget fits one
    net.tick()
    assert net.receive("b").seq == 2
    net.send(mk("b", "a", 1, b"zzz"))  # cut
    s = net.stats
    assert (s.sent_bytes, s.received_bytes, s.dropped_bytes) == (4, 4, 3)


def test_timeout_retry_recovers_after_reconnect_and_gives_up():
    net = Network(set())
    net.send_reliable(mk("a", "b", 1), timeout=1, retries=2)
    net.tick()
    net.links.add(("a", "b"))
    net.tick()
    net.tick()
    assert net.receive("b").seq == 1 and not net._pending
    dead = Network(set())
    dead.send_reliable(mk("a", "b", 1), timeout=1, retries=1)
    for _ in range(4):
        dead.tick()
    assert dead.stats.rejected["timeout"] == 1 and not dead._pending


def test_telemetry_separate_and_partition_never_blocks():
    net, tele = Network(set()), Telemetry(maxlen=2)
    for i in range(3):
        assert not net.send(mk("a", "b", i))  # returns immediately, nothing delivered
        tele.emit("a", {"i": i})
    net.tick()
    assert net.receive("b") is None and [r["i"] for _, r in tele.records] == [1, 2]


def test_manifest():
    urls, links = load_manifest(
        '{"nodes": {"a": "http://x", "b": "http://y"}, "links": [["a", "b"]]}'
    )
    assert links == {("a", "b")} and urls["a"] == "http://x"
    with pytest.raises(ValueError):
        load_manifest('{"nodes": {"a": "u"}, "links": [["a", "z"]]}')

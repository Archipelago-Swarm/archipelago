import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "packages" / "transport"))
from archipelago_transport import MAX_PAYLOAD, Envelope, Network  # noqa: E402


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
    net.send(mk("a", "b", 2)); net.send(mk("a", "b", 2)); net.send(mk("a", "b", 1))
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

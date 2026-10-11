import math

from archipelago_mission.rf import PROFILES, RFEngine, RFNode

G = PROFILES["GENERAL"]


def flat(x, y):
    return 0.0


def link(eng, d, alt=100.0, p=G, zones=()):
    a, b = RFNode("a", 0, 0, alt, p), RFNode("b", d, 0, alt, p)
    return eng.compute_links([b, a], list(zones), 1.0)[0]


def test_distance_decay_and_default_pair():
    e = RFEngine(flat)
    q = [link(e, k * 1000, 1000)["rfQuality"] for k in (10, 40, 70)]
    assert q[0] > q[1] > q[2]
    l = link(e, 40_000, 1000)
    assert l["connected"] and l["state"] in ("GOOD", "DEGRADED") and l["id"] == "a~b"
    assert not link(e, 100_000, 1000)["connected"]


def test_horizon():
    e = RFEngine(flat)
    l = link(e, 90_000, 100)
    assert l["debug"]["rejectReason"] == "BEYOND_HORIZON" and l["state"] == "DISCONNECTED"
    assert l["lineOfSight"] == "NOT_EVALUATED"
    assert link(e, 90_000, 1000)["debug"]["rejectReason"] is None


def test_relay_long_link():
    assert link(RFEngine(flat), 70_000, 1000, PROFILES["RELAY"])["connected"]


def ridge(x, y):
    return 600.0 * math.exp(-(((x - 20_000) / 3_000) ** 2))


def test_ridge_altitude_and_blocked():
    e = RFEngine(ridge)
    low, hi = link(e, 40_000, 100), link(e, 40_000, 2000)
    assert low["lineOfSight"] == "BLOCKED" and hi["lineOfSight"] == "CLEAR"
    assert low["rfQuality"] < hi["rfQuality"]
    assert low["rfQuality"] < link(RFEngine(flat), 40_000, 100)["rfQuality"]


def test_disruption():
    e = RFEngine(flat)

    def z(s):
        return [{"x": 20_000, "y": 0, "radius": 5_000, "severity": s}]

    base = link(e, 40_000, 1000)["rfQuality"]
    lo, hi = (link(e, 40_000, 1000, zones=z(s))["rfQuality"] for s in (0.3, 0.8))
    assert base > lo > hi


def test_determinism_cache():
    nodes = [RFNode(str(i), i * 13_337.0, i * 4_001.0, 500 + 100 * i, G) for i in range(5)]
    z = [{"x": 20_000, "y": 8_000, "radius": 9_000, "severity": 0.5}]
    e1, e2 = RFEngine(ridge), RFEngine(ridge)
    e2.use_cache = False
    r = e1.compute_links(nodes, z, 3.0)
    assert r == e1.compute_links(nodes, z, 3.0) == e2.compute_links(nodes, z, 3.0)

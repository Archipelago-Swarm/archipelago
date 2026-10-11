import json

from archipelago_mission.rf import RFEngine
from archipelago_mission.sim import SKILL, MissionConfig, MissionSim, Skill, run_mission


def _sim(n=3, **kw):
    sim = MissionSim(MissionConfig(n_uavs=n, **kw))
    sim.ground_elev = lambda x, y: 0.0  # flat world: isolate range from terrain
    sim.rf = RFEngine(sim.ground_elev)
    return sim


def _place(sim, *xs):  # xs in km along a line, y fixed
    for u, x in zip(sim.uavs, xs):
        u.x, u.y = 100_000.0 + x * 1000.0, 200_000.0


def _obs(u):
    u.obs[f"{u.id}|POI-01"] = {"node": u.id, "poi": "POI-01", "conf": 0.5, "cls": "VEHICLE", "n": 1, "t": 0.0}
    return f"{u.id}|POI-01"


def _skill(u):
    u.skills[SKILL] = Skill(SKILL, 1, u.id, 0.0, 0.8, 0.9, "SEARCH_REGION_SELECTION", {"spacing_m": 2500.0})


def _run(sim, n=15):
    for _ in range(n):
        sim._exchange_and_links()
        sim._skill_lifecycle()


def _ticks_to_skill(sim, b, cap=60):
    for i in range(1, cap + 1):
        sim._exchange_and_links()
        if SKILL in b.skills:
            return i
    return cap + 1


def test_determinism():
    run = lambda s: json.dumps(run_mission(MissionConfig(seed=s, time_limit=300)), sort_keys=True)  # noqa: E731
    assert run(7) == run(7)
    assert [p["x"] for p in MissionSim(MissionConfig(seed=7)).pois] != [p["x"] for p in MissionSim(MissionConfig(seed=8)).pois]


def test_rf_range_blocks_then_allows():
    sim = _sim(2)
    a, b = sim.uavs
    _place(sim, 0.0, 300.0)
    k = _obs(a)
    _skill(a)
    _run(sim)
    assert k not in b.obs and SKILL not in b.skills
    assert all(not l["connected"] for l in sim.links)
    _place(sim, 0.0, 20.0)
    _run(sim, 15)
    assert k in b.obs
    assert b.skills[SKILL].status == "ADOPTED"


def test_local_knowledge_until_exchanged():
    sim = _sim(3)
    _place(sim, 0.0, 20.0, 300.0)
    k = _obs(sim.uavs[0])
    sim._exchange_and_links()
    assert k in sim.uavs[1].obs and k not in sim.uavs[2].obs
    sim = _sim(3)
    _place(sim, 0.0, 300.0, 600.0)
    k = _obs(sim.uavs[0])
    _run(sim, 5)
    assert all(k not in u.obs for u in sim.uavs[1:])


def test_no_multihop_in_one_tick():
    sim = _sim(3)
    a, b, c = sim.uavs
    _place(sim, 0.0, 20.0, 40.0)  # A-B and B-C connected, A-C (40 km) is also near; push C further
    c.x = b.x + 20_000.0
    a.x = b.x - 20_000.0
    k = _obs(a)
    sim._exchange_and_links()
    assert k in b.obs
    far = [l for l in sim.links if {l["sourceNodeId"], l["targetNodeId"]} == {a.id, c.id}]
    if not far or not far[0]["connected"]:
        assert k not in c.obs  # relayed only on the next tick
    sim._exchange_and_links()
    assert k in c.obs


def test_network_isolation():
    sim = _sim(2)
    a, b = sim.uavs
    _place(sim, 0.0, 300.0)
    k = _obs(a)
    _skill(a)
    _run(sim, 30)
    assert k not in b.obs and SKILL not in b.skills
    assert all(not l["connected"] for l in sim.links)
    sim = _sim(2)
    a, b = sim.uavs
    _place(sim, 0.0, 20.0)
    k = _obs(a)
    _skill(a)
    _run(sim, 15)
    assert all(l["connected"] for l in sim.links)
    assert k in b.obs and SKILL in b.skills


def test_skill_transfer_needs_bandwidth():
    def go(km):
        sim = _sim(2)
        a, b = sim.uavs
        _place(sim, 0.0, km)
        _skill(a)
        return _ticks_to_skill(sim, b), sim.links[0]["state"]

    good, gs = go(20.0)
    marg, ms = go(65.0)
    assert gs in ("EXCELLENT", "GOOD") and ms == "MARGINAL"
    assert good > 1 and marg > good


def test_comm_degradation_zone_lowers_quality():
    sim = _sim(2)
    _place(sim, 0.0, 20.0)
    sim._compute_links()
    q0 = sim.links[0]["rfQuality"]
    z = sim.disruptions[0]
    z.update(active=True, x=sim.uavs[0].x + 10_000.0, y=sim.uavs[0].y, radius=50_000.0, severity=0.9, vx=0.0, vy=0.0)
    sim._compute_links()
    assert sim.links[0]["rfQuality"] < q0


def test_isolated_uav_climbs():
    sim = _sim(2)
    _place(sim, 0.0, 300.0)
    for u in sim.uavs:
        u.speed = 0.0
    for _ in range(6):
        sim.step()
    assert all(u.alt > u.alt_base for u in sim.uavs if u.alive)


def test_success_and_failed():
    sim = _sim(3)
    for u in sim.uavs:
        for p in sim.pois:
            u.obs[f"{u.id}|{p['id']}"] = {"node": u.id, "poi": p["id"], "conf": 0.95, "cls": p["trueType"], "n": 1, "t": 0.0}
    assert sim.frame()["mission"]["status"] == "SUCCESS"
    sim = _sim(3, time_limit=10.0)
    for _ in range(5):
        sim.step()
    assert sim.status == "FAILED"

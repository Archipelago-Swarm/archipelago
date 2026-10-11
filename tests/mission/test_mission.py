import json

from archipelago_mission.sim import SKILL, MissionConfig, MissionSim, Skill, run_mission


def _sim(n=3, **kw):
    sim = MissionSim(MissionConfig(n_uavs=n, **kw))
    sim.terrain.los_clear = lambda a, b: True  # isolate range from terrain
    return sim


def _place(sim, *xs):
    for u, x in zip(sim.uavs, xs):
        u.x, u.y = x, 3000.0


def _obs(u):
    u.obs[f"{u.id}|POI-01"] = {"node": u.id, "poi": "POI-01", "conf": 0.5, "cls": "VEHICLE", "n": 1, "t": 0.0}
    return f"{u.id}|POI-01"


def _skill(u):
    u.skills[SKILL] = Skill(SKILL, 1, u.id, 0.0, 0.8, 0.9, "SEARCH_REGION_SELECTION", {"spacing_m": 2500.0})


def test_determinism():
    run = lambda s: json.dumps(run_mission(MissionConfig(seed=s, time_limit=300)), sort_keys=True)  # noqa: E731
    assert run(7) == run(7)
    assert [p["x"] for p in MissionSim(MissionConfig(seed=7)).pois] != [p["x"] for p in MissionSim(MissionConfig(seed=8)).pois]


def test_rf_range_blocks_then_allows():
    sim = _sim(2)
    a, b = sim.uavs
    _place(sim, 500.0, 9500.0)
    k = _obs(a)
    _skill(a)
    sim._exchange_and_links()
    assert k not in b.obs and SKILL not in b.skills
    assert all(not l["connected"] for l in sim.links)
    _place(sim, 4000.0, 5000.0)
    for _ in range(40):
        sim._exchange_and_links()
        sim._skill_lifecycle()
    assert k in b.obs
    assert b.skills[SKILL].status == "ADOPTED"


def test_local_knowledge_until_exchanged():
    sim = _sim(3)
    _place(sim, 500.0, 5000.0, 9500.0)
    k = _obs(sim.uavs[0])
    sim._exchange_and_links()
    assert all(k not in u.obs for u in sim.uavs[1:])
    _place(sim, 4000.0, 5000.0, 9500.0)
    for _ in range(40):
        sim._exchange_and_links()
    assert k in sim.uavs[1].obs and k not in sim.uavs[2].obs


def test_no_multihop_in_one_tick():
    sim = _sim(3)
    a, b, c = sim.uavs
    _place(sim, 3000.0, 5000.0, 7000.0)  # A-B and B-C in range, A-C (4000) not
    k = _obs(a)
    sim._exchange_and_links()
    for _ in range(40):
        if k in b.obs:
            break
        sim._exchange_and_links()
        assert k not in c.obs
    assert k in b.obs and k not in c.obs


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

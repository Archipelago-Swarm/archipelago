from dataclasses import replace

from archipelago_sim.terrain import Terrain
from archipelago_swarm import rf
from archipelago_swarm.network import Network
from archipelago_swarm.store import Store

CFG = rf.RFConfig()


def _flat():
    return Terrain.flat(24, 100.0)


def _lk(t, d, y=0):
    return rf.link(t, "a", (0, y), "b", (d, y), CFG)


def test_rf_ridge_blocks_clear_los():
    t = _flat()
    clear = _lk(t, 5)
    assert clear.terrain_los and clear.state == rf.UP
    for y in range(24):
        t.elev[3][y] = 500.0  # wall across the path
    blocked = _lk(t, 5)
    assert not blocked.terrain_los and blocked.obstruction_db > 0
    assert blocked.margin_db < clear.margin_db and blocked.state == rf.DOWN
    assert blocked.distance_m == clear.distance_m


def test_rf_distance_degrades_up_degraded_down():
    t = _flat()
    states = [_lk(t, d).state for d in (2, 7, 12)]
    assert states == [rf.UP, rf.DEGRADED, rf.DOWN]
    m = [_lk(t, d).margin_db for d in range(1, 15)]
    assert m == sorted(m, reverse=True)
    assert _lk(t, 12).bandwidth_kbps == 0.0


def test_hysteresis_debounces():
    lk = replace(_lk(_flat(), 7), margin_db=2.0, state=rf.DEGRADED)  # raw: just under UP threshold
    assert rf.with_hysteresis(lk, rf.UP, CFG).state == rf.UP  # stays up within h
    assert rf.with_hysteresis(lk, rf.DEGRADED, CFG).state == rf.DEGRADED
    hi = replace(lk, margin_db=4.0, state=rf.UP)  # raw UP but not by +h
    assert rf.with_hysteresis(hi, rf.DEGRADED, CFG).state == rf.DEGRADED
    lo = replace(lk, margin_db=-1.0, state=rf.DOWN)
    assert rf.with_hysteresis(lo, rf.DEGRADED, CFG).state == rf.DEGRADED
    assert rf.with_hysteresis(lo, rf.DOWN, CFG).state == rf.DOWN


def test_netport_visibility_and_gating():
    t, store = _flat(), Store()
    net = Network(store)
    net.update(1, t, {"a": (0, 0), "b": (2, 0), "c": (7, 0), "d": (20, 0)})
    # a-b UP, a-c DEGRADED, a-d DOWN
    pa = net.port("a")
    nb = pa.neighbors()
    assert set(nb) == {"b", "c"} and nb["b"]["state"] == rf.UP and nb["c"]["state"] == rf.DEGRADED
    assert pa.send("d", {"kind": "SKILL_ADVERT"}) is False
    assert pa.send("c", {"kind": "SKILL_ADVERT"}) is True
    assert pa.send("c", {"kind": "SKILL_CHUNK"}) is False
    assert pa.send("b", {"kind": "SKILL_CHUNK"}) is True
    assert pa.budget_bytes("c") == 0 and pa.budget_bytes("b") > 0
    net.update(2, t, {"a": (0, 0), "b": (2, 0), "c": (7, 0), "d": (20, 0)})
    assert net.port("d").recv() == []
    assert [m["kind"] for m in net.port("c").recv()] == ["SKILL_ADVERT"]
    assert [m["kind"] for m in net.port("b").recv()] == ["SKILL_CHUNK"]
    for tick in range(3, 9):  # link events are debounced: a state must persist 5 ticks
        net.update(tick, t, {"a": (0, 0), "b": (2, 0), "c": (7, 0), "d": (20, 0)})
    assert {e["type"] for e in store.events} >= {"RF_LINK_UP", "RF_LINK_DEGRADED"}

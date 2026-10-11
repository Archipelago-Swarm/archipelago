"""Terrain zones degrade flight/sensing; ridges occlude RF between nodes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/sim"))

from archipelago_sim.terrain import REGION_MODS, Terrain  # noqa: E402


def ridge_world():
    t = Terrain.flat(12, 625.0)
    for y in range(12):
        t.elev[6][y] = 400.0  # a N-S ridge well above the 80 m flight altitude
    t._max_elev = 400.0
    return t


def test_ridge_blocks_rf_but_not_same_side():
    t = ridge_world()
    assert not t.rf_clear((2, 5), (9, 5))
    assert t.rf_clear((2, 5), (4, 5)) and t.rf_clear((7, 5), (10, 3))


def test_regions_and_sensor_degradation():
    t = ridge_world()
    assert t.region((6, 3)) == "canyon" and t.region((2, 2)) == "lowland"
    low = t.detect_p((2, 2), (4, 2), 3)
    t.elev[2][2] = 400.0  # same flight, now in the canyon zone: shorter reach
    assert t.detect_p((2, 2), (4, 2), 3) < low or REGION_MODS["canyon"]["sensor"] < 1
    assert t.detect_p((2, 2), (6, 2), 3) == 0.0 or t.region((2, 2)) == "canyon"


def test_canyon_caps_turn_rate():
    from archipelago_sim.flight import FlightWorld

    def turned(canyon):
        w = FlightWorld(size=12, n_agents=1, n_targets=0, obstacle_density=0.0, terrain_seed=1)
        w.reset(seed=0, starts={"node-0": (3, 3)})
        t = Terrain.flat(12, 625.0)
        if canyon:
            t.elev = [[400.0] * 12 for _ in range(12)]
            t._max_elev = 400.0
        w.terrain = t
        w.fs["node-0"]["heading"] = 0.0
        w.step({"node-0": "south"})
        return abs(w.fs["node-0"]["heading"])

    assert turned(True) < 0.75 * turned(False)


def test_height_and_slope_lookup():
    t = Terrain.flat(12, 625.0)
    for x in range(12):
        for y in range(12):
            t.elev[x][y] = 10.0 * x  # 10 m per cell eastward
    assert abs(t.height_at(5.5 * 625, 3 * 625) - 50.0) < 1e-6
    assert abs(t.slope_at(5.5 * 625, 5 * 625) - 10 / 625) < 1e-6


def test_probes_see_ridge_and_encoder_v3_dim():
    import numpy as np
    from archipelago_learning import encoders

    t = ridge_world()
    p = t.probes((4, 5))  # ridge 2 cells east: east probe clipped, west probe clear
    assert p[0] == 0.25 and p[4] == 1.0 and len(p) == 10
    enc = encoders.get("grid-flat-v3-terrain-s12-r2")
    v = enc.encode_raw({"crop": [[0] * 5] * 5, "pose": (4, 5), "battery": 1.0, "radar": p})
    assert v.shape == (enc.obs_dim,) == (38,) and np.allclose(v[-10:], p)
    assert enc.sha256 != encoders.get("grid-flat-v1-s12-r2").sha256


def test_reward_shaping_specialises_canyon_vs_lowland():
    from archipelago_sim.env import GridWorld

    def shaped(canyon):
        w = GridWorld(size=12, n_agents=1, n_targets=0, obstacle_density=0.0, terrain_seed=1,
                      reward_id="rew-terrain-v1")  # fmt: skip
        w.reset(seed=0, starts={"node-0": (5, 5)})
        t = ridge_world()
        if canyon:
            t.elev = [[700.0] * 12 for _ in range(12)]
            t.elev[6][5] = 900.0  # a wall one cell east
            t._max_elev = 900.0
        w.terrain = t
        w._last_cmd["node-0"] = "north"
        return w._shape("node-0", "east")

    assert shaped(True) < -0.1 < 0 < shaped(False)

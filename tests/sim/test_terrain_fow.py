"""Terrain-aware FOW: real visibility effect, honest observations, shareable estimates."""

import sys
from pathlib import Path

import pytest

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "packages/learning"))

from archipelago_learning.visibility import VisibilityModel  # noqa: E402
from archipelago_sim.env import UNKNOWN, GridWorld  # noqa: E402
from archipelago_sim.terrain import GRASS, JUNGLE, Terrain  # noqa: E402


def world(terr, targets, pos=(5, 5), radius=2):
    w = GridWorld(
        size=12, n_agents=1, n_targets=0, obstacle_density=0.0, sense_radius=radius, terrain_seed=3
    )
    w.reset(seed=0, starts={"node-0": pos})
    w.terrain, w.targets = terr, list(targets)
    return w


def test_terrain_deterministic_and_coherent():
    a, b, c = (Terrain.generate(32, 625.0, s) for s in (1, 1, 2))
    assert a.elev == b.elev and a.biome == b.biome and a.elev != c.elev
    flat = [v for r in a.biome for v in r]
    assert {0, 1, 2} <= set(flat)
    same = sum(a.biome[x][y] == a.biome[x + 1][y] for x in range(31) for y in range(32))
    assert (
        same / (31 * 32) > 0.75
    )  # regions (random 3-class tiles score ~0.34), not salt-and-pepper tiles


def test_same_target_open_vs_forest_changes_detection():
    def rate(veg):
        t = Terrain.flat(12, 625.0)
        t.veg[7][5] = veg
        w = world(t, [(7, 5)])
        hits = 0
        for k in range(400):
            w.tick = k
            w.drones["node-0"].found.clear()
            w._detect("node-0", (7, 5))
            hits += (7, 5) in w.drones["node-0"].found
        return hits / 400

    open_, jungle = rate(0.0), rate(0.9)
    assert open_ > 0.6 and jungle < 0.25 and open_ > 3 * jungle


def test_ridge_blocks_cells_and_targets_without_leaking():
    t = Terrain.flat(12, 625.0)
    t.elev[6][5] = 400.0  # ridge between the drone at (5,5) and the target at (7,5)
    w = world(t, [(7, 5)])
    d = w.drones["node-0"]
    d.known.clear()
    d.found.clear()
    for k in range(50):
        w.tick = k
        w._sense("node-0")
    assert (7, 5) not in d.known and d.known.get(
        (7, 5), UNKNOWN
    ) == UNKNOWN  # occluded cell stays unknown
    assert (6, 5) in d.known and (7, 5) not in d.found
    obs = w.observe("node-0")
    assert (7, 5) not in obs["visible_markers"] and obs[
        "sense_log"
    ] == []  # hidden target: no evidence at all
    assert not {"terrain", "eval_p", "targets", "elev"} & set(obs)


def test_unknown_marker_gives_no_feedback_known_marker_does():
    t = Terrain.flat(12, 625.0)
    t.veg[6][5] = 0.9
    w = world(t, [(6, 5)])
    d = w.drones["node-0"]
    d.found.clear()
    d.known.clear()
    seen_first = False
    for k in range(200):
        w.tick = k
        w._sense("node-0")
        if (6, 5) in d.found:
            seen_first = True
            assert d.sense_log == []  # the detecting tick is not logged
            break
    assert seen_first
    w.tick = 999
    w._sense("node-0")
    assert (
        len(d.sense_log) == 1 and d.sense_log[0][0] == GRASS
    )  # biome the node saw; flat() is grass


def test_visibility_model_learns_and_shares():
    a, b = VisibilityModel("node-a"), VisibilityModel("node-b")
    assert a.estimate(JUNGLE, 80.0, 1) == 0.5  # unobserved is uncertain, not empty
    a.update([(JUNGLE, 80.0, 1, False)] * 8 + [(GRASS, 80.0, 1, True)] * 8)
    assert a.estimate(JUNGLE, 80.0, 1) < 0.2 < 0.8 < a.estimate(GRASS, 80.0, 1)
    assert b.estimate(JUNGLE, 80.0, 1) == 0.5
    b.receive(a.to_wire(), "node-a")
    b.receive(a.to_wire(), "node-a")  # repeat must not double count
    assert b.estimate(JUNGLE, 80.0, 1) == a.estimate(JUNGLE, 80.0, 1)
    assert b.attempts() == 0  # peer counts are never mistaken for own experience
    with pytest.raises(ValueError):
        b.receive(a.to_wire(), "node-z")  # claimed sender must match
    with pytest.raises(ValueError):
        b.receive(b'{"kind":"vis-estimate-v1","node":"node-a","counts":{"x":[5,1]}}', "node-a")


def test_rectangular_world():
    from archipelago_sim.flight import FlightWorld

    w = FlightWorld(size=40, height=20, n_agents=2, n_targets=0, terrain_seed=1)
    w.reset(seed=0, starts={"node-0": (3, 3), "node-1": (36, 16)})
    assert (w.width_m, w.height_m) == (40 * 625.0, 20 * 625.0)
    assert len(w.terrain.elev) == 40 and len(w.terrain.elev[0]) == 20
    assert all(0 <= c[0] < 40 and 0 <= c[1] < 20 for c in w.obstacles)
    for _ in range(150):  # battery lasts ~250 ticks
        w.step({a: "east" for a in w.agents})
    assert all(0 <= d.pos[0] < 40 and 0 <= d.pos[1] < 20 for d in w.drones.values())
    assert w.world_state()["height"] == 20
    with pytest.raises(ValueError):
        FlightWorld(size=20, height=40)


def test_alpine_terrain_is_taller_deterministic_and_occludes():
    a, b = (Terrain.generate(80, 625.0, 1, height=45, style="alpine") for _ in range(2))
    c = Terrain.generate(80, 625.0, 1, height=45)
    assert a.elev == b.elev and a.elev != c.elev
    assert max(map(max, a.elev)) > 2 * max(map(max, c.elev))  # real mountains, not hills
    flat = [v for r in a.biome for v in r]
    assert {0, 1, 2} <= set(flat)
    cells = [(x, y) for x in range(0, 80, 3) for y in range(0, 45, 3)]
    assert any(not a.los_clear((10, 20), (x, y)) for x, y in cells if abs(x - 10) <= 6)
    with pytest.raises(ValueError):
        Terrain.generate(8, 625.0, 1, style="nope")

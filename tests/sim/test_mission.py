from archipelago_sim.env import GridWorld
from archipelago_sim.mission import new_finds


def _world(frac):
    w = GridWorld(size=32, n_agents=2, n_targets=6, terrain_seed=7, canyon_target_frac=frac)
    w.reset(seed=3)
    return w


def test_canyon_bias_places_requested_share_in_canyon():
    w = _world(0.5)
    assert sum(w.terrain.region(c) == "canyon" for c in w.targets) >= 3
    assert len(set(w.targets)) == 6


def test_new_finds_attributes_once_to_lowest_node():
    w = _world(0.0)
    t = w.targets[0]
    w.found_targets.add(t)
    w.drones["node-1"].found.add(t)
    w.drones["node-0"].found.add(t)
    seen: set = set()
    assert new_finds(w, seen) == [(t, "node-0")]
    assert new_finds(w, seen) == []

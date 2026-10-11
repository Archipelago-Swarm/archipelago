from archipelago_sim.env import GridWorld
from archipelago_sim.mission import new_finds


def _world():
    w = GridWorld(size=32, n_agents=2, n_targets=6, terrain_seed=7)
    w.reset(seed=3)
    return w


def test_new_finds_attributes_once_to_lowest_node():
    w = _world()
    t = w.targets[0]
    w.found_targets.add(t)
    w.drones["node-1"].found.add(t)
    w.drones["node-0"].found.add(t)
    seen: set = set()
    assert new_finds(w, seen) == [(t, "node-0")]
    assert new_finds(w, seen) == []

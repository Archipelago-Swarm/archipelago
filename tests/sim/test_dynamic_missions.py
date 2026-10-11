"""Per-episode maps and missions with seeded dynamics. Every assertion would fail if the feature
were stubbed (a constant map seed, a no-op schedule, a mission that never completes)."""

import random

import pytest
from archipelago_sim.env import GridWorld
from archipelago_sim.mission import Dynamics, MissionSpec, derive_map_seed
from archipelago_sim2d.adapter import Sim2DAdapter, replay_final_hash
from archipelago_sim2d.smoke import make_action, make_config

DYN = {
    "id": "sr-1",
    "type": "search_rescue",
    "n_targets": 4,
    "dynamics": {"targets_move_every": 5, "targets_appear": 2, "obstacles_shift_every": 7},
}
WORLD = {"size": 24, "height": 16, "terrain_seed": 3, "mission": DYN}


def adapter(mode: str, episode: int, seed: int = 11, ticks: int = 60, **kw) -> Sim2DAdapter:
    ad = Sim2DAdapter(environment_mode=mode, **{**WORLD, **kw})
    ad.reset(make_config(seed, ticks, 3), episode=episode)
    return ad


def fly(ad: Sim2DAdapter, ticks: int, command=None) -> None:
    rng = random.Random(0)
    for t in range(ticks):
        if not ad.world.agents:
            return
        ad.step({n: make_action(n, t, command or rng.choice(("north", "east", "south", "west")))
                 for n in ad.world.agents})  # fmt: skip


def test_map_seed_is_deterministic_and_distinct_per_episode():
    seeds = {derive_map_seed(11, e) for e in range(50)}
    assert len(seeds) == 50
    assert derive_map_seed(11, 3) == derive_map_seed(11, 3)
    assert derive_map_seed(11, 3) != derive_map_seed(12, 3)


@pytest.mark.parametrize("mode", ["legacy_grid", "continuous_flight"])
def test_each_episode_gets_a_different_map_and_the_same_pair_reproduces(mode):
    a, b, a2 = adapter(mode, 0), adapter(mode, 1), adapter(mode, 0)
    assert a.map_seed != b.map_seed
    assert a.world.obstacles != b.world.obstacles
    assert a.world.targets != b.world.targets
    assert a.world.terrain.elev != b.world.terrain.elev  # terrain follows the map seed too
    assert a.world.terrain_seed == a.map_seed
    assert (a.world.obstacles, a.world.targets) == (a2.world.obstacles, a2.world.targets)
    assert a.world.terrain.elev == a2.world.terrain.elev
    assert a.world.trace_hash() == a2.world.trace_hash()
    assert a.public_snapshot().mission.map_seed == a.map_seed


def test_targets_move_appear_and_obstacles_shift_on_the_seeded_schedule():
    ad = adapter("legacy_grid", 2, ticks=60)
    w = ad.world
    appear = sorted(t for t, _ in w._spawns)
    n0, obstacles0, targets0 = len(w.targets), set(w.obstacles), list(w.targets)
    assert (n0, len(appear)) == (4, 2)
    fly(ad, 40, "stay")
    events = [
        e for rec in ad.replay for e in rec["events"] if e["event"].startswith(("target", "obst"))
    ]
    ticks = lambda name: [e["tick"] for e in events if e["event"] == name]  # noqa: E731
    assert ticks("target_appeared") == appear  # exactly the scheduled ticks
    assert set(ticks("target_moved")) <= set(range(5, 41, 5))
    assert ticks("target_moved")
    assert set(ticks("obstacle_shifted")) <= {7, 14, 21, 28, 35}
    assert ticks("obstacle_shifted")
    assert len(w.targets) == 6 and w.obstacles != obstacles0 and w.targets[:4] != targets0
    assert len(w.obstacles) == len(obstacles0)  # a shift moves cells, it does not create or delete


def test_flight_world_shifts_whole_terrain_features_consistently():
    ad = adapter("continuous_flight", 1, ticks=80)
    w = ad.world
    before = {k: list(v["points"]) for k, v in w.shapes.items()}
    fly(ad, 80, "stay")
    shifted = [e for rec in ad.replay for e in rec["events"] if e["event"] == "obstacle_shifted"]
    assert shifted and any(w.shapes[k]["points"] != before[k] for k in before)
    raster = set().union(*(v["cells"] for v in w.shapes.values())) - w._keep_clear
    assert raster == w.obstacles  # polygon raster and hidden grid stay in step
    assert all(d.pos not in w.obstacles for d in w.drones.values())


def test_dynamic_episode_replays_to_the_same_hash():
    ad = adapter("legacy_grid", 3, ticks=50)
    fly(ad, 50)
    records = ad.replay
    h = ad.world.trace_hash()
    cfg = make_config(11, 50, 3)
    assert replay_final_hash(cfg, records, 3, environment_mode="legacy_grid", **WORLD) == h
    assert replay_final_hash(cfg, records, 4, environment_mode="legacy_grid", **WORLD) != h


def test_search_rescue_completion_and_time_to_complete():
    w = GridWorld(size=12, n_agents=2, mission={"type": "search_rescue", "n_targets": 3})
    w.reset(seed=4)
    assert w.mission_status()["status"] == "active"
    for t in w.targets[:2]:
        w.found_targets.add(t)
    w._update_mission()
    s = w.mission_status()
    assert s["status"] == "active" and s["objectives"][0]["progress"] == pytest.approx(
        2 / 3, abs=1e-3
    )
    w.tick = 17
    w.found_targets.add(w.targets[2])
    w._update_mission()
    s = w.mission_status()
    assert (s["status"], s["completed_tick"], s["objectives"][0]["done"]) == ("succeeded", 17, True)
    w.tick = 30
    w._update_mission()
    assert w.mission_status()["completed_tick"] == 17  # latched


def test_episode_terminates_on_success_and_fails_on_budgets():
    w = GridWorld(
        size=8, n_agents=1, max_ticks=50, mission={"n_targets": 1, "time_budget_ticks": 6}
    )
    w.reset(seed=1)
    for _ in range(5):
        _, _, term, _, _ = w.step({"node-0": "stay"})
    assert w.mission_status()["status"] == "active" and not term["node-0"]
    _, _, term, _, _ = w.step({"node-0": "stay"})
    assert w.mission_status()["status"] == "failed" and term["node-0"]
    e = GridWorld(size=8, n_agents=1, mission={"n_targets": 1, "energy_budget": 0.02})
    e.reset(seed=1)
    for _ in range(40):
        if e.mission_status()["status"] != "active":
            break
        e.step({"node-0": "stay"})
    assert e.mission_status()["status"] == "failed" and e.tick < 40  # ran out of energy budget


def test_coverage_mission_succeeds_at_its_fraction_and_not_before():
    cover = {"id": "cov", "kind": "cover_fraction", "target": 0.5}
    mission = {"type": "coverage", "n_targets": 0, "objectives": [cover]}
    w = GridWorld(size=8, n_agents=2, obstacle_density=0.0, max_ticks=300, mission=mission)
    w.reset(seed=2)
    assert w.mission_status()["status"] == "active" and w.coverage < 0.5
    rng, ended = random.Random(5), None
    for _ in range(300):
        _, _, term, _, _ = w.step(
            {a: rng.choice(("north", "east", "south", "west")) for a in w.agents}
        )
        if not w.agents:
            ended = w.mission_status()
            break
    assert ended["status"] == "succeeded" and w.coverage >= 0.5
    assert ended["completed_tick"] == w.tick


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "teleport"},
        {"n_targets": -1},
        {"n_targets": 0},  # search_rescue with nothing to find
        {"energy_budget": 0},
        {"time_budget_ticks": 0},
        {"dynamics": {"targets_move_every": -1}},
        {"dynamics": {"appear_window": [0.9, 0.1]}},
        {"dynamics": {"bogus": 1}},
        {"objectives": [{"id": "x", "kind": "find_targets", "target": 99}]},
        {"objectives": [{"id": "x", "kind": "cover_fraction", "target": 1.5}]},
        {"surprise": 1},
        {"id": "has space"},
    ],
)
def test_mission_validation_rejects_bad_specs(bad):
    with pytest.raises(ValueError):
        MissionSpec.from_dict({"n_targets": 3, **bad} if "n_targets" not in bad else bad)


def test_safe_defaults_have_no_dynamics_and_a_default_objective():
    m = MissionSpec()
    assert m.dynamics == Dynamics() and m.type == "search_rescue"
    assert [(o.kind, o.target) for o in m.objectives] == [("find_targets", 5)]
    w = GridWorld(size=12, n_agents=2, mission=m)
    w.reset(seed=1)
    before = (list(w.targets), set(w.obstacles))
    for _ in range(30):
        w.step({a: "stay" for a in w.agents})
    assert (w.targets, w.obstacles) == before and w.mission_status()["dynamics"] == []

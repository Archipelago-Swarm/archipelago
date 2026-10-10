import json
import random

import pytest
from archipelago_sim.env import GridWorld, explorer_policy
from archipelago_sim2d.adapter import replay_final_hash
from archipelago_sim2d.smoke import make_config, run_explorer


def run(seed, ticks=60):
    w = GridWorld(max_ticks=ticks)
    obs = w.reset(seed)
    rng, vis = random.Random(seed), {a: {} for a in w.possible_agents}
    while w.agents:
        obs, *_ = w.step({a: explorer_policy(o, vis[a], rng) for a, o in obs.items()})
    return w


def test_same_seed_same_trace_and_different_seed_differs():
    assert run(3).trace_hash() == run(3).trace_hash() != run(4).trace_hash()


def test_local_observation_hides_world():
    w = GridWorld()
    for o in w.reset(1).values():
        assert set(o) == {"crop", "known_mask", "pose", "battery", "visible_markers"}
        hidden = [
            v
            for r, m in zip(o["crop"], o["known_mask"], strict=True)
            for v, k in zip(r, m, strict=True)
            if not k
        ]
        assert all(v == -1 for v in hidden)


def test_wall_swap_and_same_cell_collisions():
    w = GridWorld(n_agents=3, n_targets=0)
    w.reset(1, starts={"node-0": (5, 5), "node-1": (6, 5), "node-2": (5, 7)})
    w.obstacles.clear()
    w.step({"node-0": "east", "node-1": "west", "node-2": "stay"})  # swap blocked
    assert (w.drones["node-0"].pos, w.drones["node-1"].pos) == ((5, 5), (6, 5))
    w.step({"node-0": "south", "node-2": "north"})  # both want (5,6)
    assert w.drones["node-0"].pos == (5, 5) and w.drones["node-2"].pos == (5, 7)
    w.drones["node-0"].pos = (0, 0)
    w.step({"node-0": "north"})
    assert w.drones["node-0"].pos == (0, 0)
    assert {e["event"] for e in w.events} >= {"agent_collision", "wall_collision"}


def test_invalid_missing_energy_and_termination():
    w = GridWorld(n_agents=2, n_targets=1, battery_scale=0.0005)
    w.reset(2)
    _, _, term, _, _ = w.step({"node-0": "jump"})
    kinds = {e["event"] for e in w.events}
    assert {"invalid_action", "missing_action", "energy_exhausted"} <= kinds
    assert all(term.values()) and not w.agents


def test_truncation_at_max_ticks():
    w = GridWorld(max_ticks=2, n_targets=0)
    w.reset(1)
    w.step({})
    _, _, term, trunc, _ = w.step({})
    assert all(trunc.values()) and not any(term.values())


def test_adapter_900_tick_smoke_with_timeout_node(tmp_path):
    ad = run_explorer(5, 900, silent=frozenset({"node-3"}))
    assert 0 < ad.snapshot().coverage <= 1
    m = json.loads(ad.write_replay(tmp_path).read_text())
    assert m["ticks"] > 0 and len(m["replay_sha256"]) == 64
    assert any(e["event"] == "missing_action" for r in ad.replay for e in r["events"])


def test_parallel_api_shape():
    w = GridWorld()
    w.reset(0)
    assert w.possible_agents == w.agents and set(w.action_spaces) == set(w.agents)
    with pytest.raises(RuntimeError):
        GridWorld().step({})


def test_full_900_ticks_replay_reexecutes_and_start_poses(tmp_path):
    kw = {"n_targets": 0, "battery_scale": 10.0}  # no target to end the run early
    ad = run_explorer(5, 900, **kw)
    m = json.loads(ad.write_replay(tmp_path).read_text())
    assert m["ticks"] == 900
    records = [json.loads(line) for line in (tmp_path / "replay.jsonl").read_text().splitlines()]
    assert replay_final_hash(make_config(5, 900), records, **kw) == m["final_state_hash"]
    fresh = type(ad)(**kw)
    fresh.reset(make_config(5, 900))
    assert [(o.x, o.y) for o in fresh.snapshot().poses.values()] == [
        (i + 0.5, 0.5) for i in range(4)
    ]


def test_unknown_reward_id_rejected():
    with pytest.raises(ValueError):
        GridWorld(reward_id="nope")

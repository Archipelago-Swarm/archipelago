"""NodeMemory / v2 encoder semantics that the parity fixtures do not isolate (T38, A18)."""

import numpy as np
import pytest
from archipelago_learning import encoders, schedules
from archipelago_learning.compat import encoder_sha256
from archipelago_learning.visits import NodeMemory

R = 2


def crop(fill=0):
    return [[fill] * 5 for _ in range(5)]


def test_observe_is_idempotent_per_tick_and_counts_stay_ticks():
    m = NodeMemory(8, R)
    assert m.observe(0, 3, 3, crop()) is True
    assert m.observe(0, 3, 3, crop()) is False  # act(t) and feedback(t-1) carry the same tick
    assert m.observe(1, 3, 3, crop()) is True  # staying counts
    assert m.observe(1, 4, 4, crop()) is False  # a stale/duplicate tick can never move the pose
    assert m.visits == {(3, 3): 2}
    assert m.observe(5, 4, 3, crop()) is True  # a gap leaves no count for the missed ticks
    assert m.visits == {(3, 3): 2, (4, 3): 1}


def test_buffer_is_the_union_of_crops_and_frontier_ignores_cells_outside_the_map():
    m = NodeMemory(8, R)
    c = crop(0)
    c[0][0] = -1  # unknown corner (e.g. outside the map): not added to the buffer
    m.observe(0, 0, 0, c)
    # at the corner of the map the north and west rings are outside the map: not frontier
    visits, frontier, peer = m.features(0, 0)
    assert frontier[0] == 0.0 and frontier[3] == 0.0
    # east and south rings: 3 of their 5 cells are inside the map, none sensed yet
    assert frontier[1] == pytest.approx(0.6) and frontier[2] == pytest.approx(0.6)
    assert visits[12] == 1 and sum(visits) == 1 and not any(peer)
    m.observe(1, 1, 0, crop(0))  # sensing the east ring's first cells
    _, frontier, _ = m.features(1, 0)
    assert 0.0 <= frontier[1] <= 1.0


def test_peer_flags_union_senders_and_a_summary_only_grows_within_an_episode():
    m = NodeMemory(8, R)
    m.observe(0, 3, 3, crop())
    m.merge_peer("node-02", [(3, 3), (4, 4)])
    m.merge_peer("node-03", [(1, 1)])
    m.merge_peer("node-02", [(5, 5)])  # a later, smaller view cannot erase what was reported
    assert m.peer_cells() == {(3, 3), (4, 4), (5, 5), (1, 1)}
    _, _, peer = m.features(3, 3)
    assert sum(peer) == 4 and peer[12] is True
    m.reset()
    assert m.peer_cells() == frozenset() and m.own_cells() == frozenset() and m.tick == -1


def test_state_round_trip_and_validation():
    m = NodeMemory(8, R)
    m.observe(0, 2, 2, crop())
    m.observe(1, 3, 2, crop())
    m.merge_peer("node-02", [(0, 0)])
    n = NodeMemory(8, R)
    n.load_state(m.state())
    assert n.state() == m.state()
    for bad in (
        {"tick": 0, "known": [[9, 9]], "visits": [], "peer": {}},  # outside the grid
        {"tick": 0, "known": [], "visits": [[1, 1, 0]], "peer": {}},  # zero count
        {"tick": 0, "known": [], "visits": [], "peer": {"a": [[-1, 0]]}},
        {"tick": "x", "known": [], "visits": [], "peer": {}},
        {"known": [], "visits": [], "peer": {}},
    ):
        with pytest.raises(ValueError):
            NodeMemory(8, R).load_state(bad)
    assert NodeMemory(8, R).state()["visits"] == []  # a failed load leaves the memory untouched


def test_v2_encoder_definitions_are_distinct_and_geometry_bearing():
    loc, sh = (
        encoders.get("grid-flat-v2-visits-s16-r2"),
        encoders.get("grid-flat-v2-visits-shared-s16-r2"),
    )
    assert (loc.obs_dim, sh.obs_dim) == (57, 82) and loc.stateful and sh.stateful
    assert not encoders.get("grid-flat-v1-s16-r2").stateful
    assert encoders.get("grid-flat-v2-visits-shared-s8-r1").obs_dim == 3 * 9 + 3 + 4
    assert sh.definition.startswith(sh.id) and "peer stood-on flags" in sh.definition
    assert encoder_sha256(sh.id) == sh.sha256 != encoder_sha256(loc.id)
    for bad in ("grid-flat-v2-visits-s0-r2", "grid-flat-v2-visits-shared", "grid-flat-v3-s8-r2"):
        with pytest.raises(ValueError):
            encoders.get(bad)


def test_encoder_rejects_bad_geometry_and_clips_battery():
    enc = encoders.get("grid-flat-v2-visits-shared-s8-r2")
    m = enc.new_memory()
    with pytest.raises(ValueError):
        enc.encode_raw({"crop": [[0] * 3] * 3, "pose": (1, 1), "battery": 1.0}, m, 0)
    v = enc.encode_raw({"crop": crop(), "pose": (1, 1), "battery": 1.7}, m, 0)
    assert v.dtype == np.float32 and v[27] == 1.0 and v.shape == (82,)
    assert v[25] == pytest.approx(1 / 8) and v[28 + 12] == pytest.approx(0.25)


def test_schedule_registry_and_epsilon():
    assert schedules.known("sched-v0") and schedules.known("sched-t37-v1")
    assert not schedules.known("sched-nope")
    s = schedules.SCHEDULES["sched-t37-v1"]
    assert s.decay_episodes(400) == 200 and s.decay_episodes(1) == 1 and s.decay_episodes(5) == 3
    assert schedules.epsilon_at(0, 1.0, 0.05, 200) == 1.0
    assert schedules.epsilon_at(100, 1.0, 0.05, 200) == pytest.approx(0.525)
    assert schedules.epsilon_at(200, 1.0, 0.05, 200) == pytest.approx(0.05)
    assert schedules.epsilon_at(10_000, 1.0, 0.05, 200) == pytest.approx(0.05)
    keys = ("lr", "gamma", "hidden", "capacity", "batch", "target_every")
    hyper = {k: getattr(s, k) for k in (*keys, "train_steps_per_feedback")}
    schedules.check(s.id, hyper, {"start": 1.0, "end": 0.05}, True)
    with pytest.raises(ValueError, match="requires lr"):
        schedules.check(s.id, {**hyper, "lr": 0.01}, {"start": 1.0, "end": 0.05}, True)
    with pytest.raises(ValueError, match="double_dqn"):
        schedules.check(s.id, hyper, {"start": 1.0, "end": 0.05}, False)
    with pytest.raises(ValueError, match="registered"):
        schedules.check("sched-v0", hyper, {"start": 0.5, "end": 0.05}, True)

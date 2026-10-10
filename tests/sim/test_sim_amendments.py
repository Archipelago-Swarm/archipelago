"""Sim2DAdapter behavior required by live-runtime.md A10 and A14."""

from datetime import UTC, datetime

from archipelago_sim2d.adapter import Sim2DAdapter
from archipelago_sim2d.smoke import make_action, make_config


def test_public_snapshot_shows_only_discovered_obstacles_and_snapshot_shows_all():
    ad = Sim2DAdapter(n_targets=2)
    obs = ad.reset(make_config(5, 20))
    full = {tuple(o) for o in ad.snapshot().obstacles}
    public = {tuple(o) for o in ad.public_snapshot().obstacles}
    assert public < full  # the rest is undiscovered
    for ox, oy in public:  # every public obstacle is inside some drone's sensing square
        assert any(
            max(abs(ox - int(o.pose.x)), abs(oy - int(o.pose.y))) <= ad.world.radius
            for o in obs.values()
        )
    extras = ad.privileged_extras()
    assert len(extras["targets"]) == 2 and set(extras["battery"]) == set(obs)
    links = [("node-0", "node-1")]
    assert ad.public_snapshot(links).topology.links == links
    assert ad.snapshot().topology.links == []


def test_kill_vanishes_the_drone_but_what_it_discovered_stays_public():
    ad = Sim2DAdapter(n_targets=0, battery_scale=10.0)
    ad.reset(make_config(5, 20))
    for t in range(3):
        ad.step({n: make_action(n, t, "south") for n in ad.world.agents})
    before = {tuple(o) for o in ad.public_snapshot().obstacles}
    known_by_victim = {
        c for c, v in ad.world.drones["node-2"].known.items() if v == 1 and c in ad.world.obstacles
    }
    ad.kill("node-2")
    assert "node-2" not in ad.world.drones and "node-2" not in ad.snapshot().poses
    assert "node-2" not in ad.public_snapshot().poses
    after = {tuple(o) for o in ad.public_snapshot().obstacles}
    assert after == before and known_by_victim <= after


def test_episodes_get_distinct_ids_wall_clock_stamps_and_global_sim_ticks():
    ad = Sim2DAdapter(n_targets=0, battery_scale=10.0)
    t0 = datetime.now(UTC)
    stamped = []
    for episode in range(2):
        cfg = make_config(7 + episode, 5).model_copy(update={"run_id": f"r-e{episode}"})
        obs = ad.reset(cfg, episode=episode)
        stamped += [*obs.values(), ad.snapshot()]
    t1 = datetime.now(UTC)
    assert len({(o.run_id, o.event_id) for o in stamped}) == len(stamped)  # no repeats
    assert all(t0 <= o.emitted_at_utc <= t1 for o in stamped)  # wall time, not a fixture epoch
    assert {o.sim_tick for o in stamped if o.run_id == "r-e0"} == {0}
    assert {o.sim_tick for o in stamped if o.run_id == "r-e1"} == {5}  # episode * max_ticks + 0

"""T37: versioned sim variants (rew-v1, grid-flat-v2-visits[-shared]) and the study guards."""

import hashlib
import inspect
import json
import random

import numpy as np
import protocol_harness as H
import pytest
import t37
from archipelago_sim.env import ACTIONS, GridWorld

# Hashes of full random-action episodes (obs, rewards, flags, world state, events) produced by the
# pre-T37 simulator (origin/main 28c6b3f). Old ids must stay bit-identical.
GOLDEN_V0 = {
    0: "aa4ee96834cc44384e869039b474eeb94401311d277f3c69533ff1ea1d38d0f2",
    1: "a710c16af5d40871a1ecc08150ddc36ed6200b7a9fc19052ce81b156b6b25faf",
    7: "4248e295fc326e84067c7151e509ba8565bb6c76748af190d3ec0b539e140dec",
}


def episode_hash(seed, n_agents=3, **kw):
    w = GridWorld(size=12, n_agents=n_agents, n_targets=5, max_ticks=80, **kw)
    obs = w.reset(seed)
    rng = random.Random(seed)
    log = [json.dumps(obs, sort_keys=True, default=list)]
    while w.agents:
        acts = {a: rng.choice(ACTIONS) for a in w.agents}
        o, r, t, tr, _ = w.step(acts)
        log.append(json.dumps([o, r, t, tr], sort_keys=True, default=list))
    log += [w.trace_hash(), json.dumps(w.events)]
    return hashlib.sha256("".join(log).encode()).hexdigest()


# ------------------------------------------------------------------------- old-id regression
@pytest.mark.parametrize("seed", sorted(GOLDEN_V0))
def test_rew_v0_default_is_bit_identical_to_pre_t37(seed):
    assert episode_hash(seed) == GOLDEN_V0[seed]
    assert episode_hash(seed, reward_id="rew-v0") == GOLDEN_V0[seed]


def test_old_observation_ids_unchanged_shape_and_values():
    assert H.obs_dim("grid-flat-v0") == 28 and H.obs_dim("grid-flat-v1-map") == 28 + 16
    env = H.make_env("grid-flat-v0")
    env.reset(seed=3)
    a = env.agents[0]
    assert np.array_equal(H.flat(env, a)[:25], np.asarray(env.world.observe(a)["crop"]).ravel())
    assert H.flat(env, a).shape == (28,)
    with pytest.raises(ValueError):
        GridWorld(reward_id="rew-v9")


# ---------------------------------------------------------------------------- determinism
@pytest.mark.parametrize("obs", H.OBS_IDS)
def test_play_is_deterministic_per_obs_id(obs):
    def once():
        env = H.make_env(obs, "rew-v1")
        rng = random.Random(5)
        rec = H.play(
            env, H.SCENARIOS["connected"], 123, lambda a, o, t: rng.randrange(5), info=True
        )
        return rec["actions_sha"], rec["ret"], rec["counters"], rec["coverage_gain"]

    assert once() == once()


def test_v1_episode_hash_deterministic_and_differs_from_v0():
    assert episode_hash(4, reward_id="rew-v1") == episode_hash(4, reward_id="rew-v1")
    assert episode_hash(4, reward_id="rew-v1") != episode_hash(4, reward_id="rew-v0")


# ------------------------------------------------------------------- observation shape and ids
@pytest.mark.parametrize("obs", H.OBS_IDS)
def test_flat_length_matches_obs_dim(obs):
    env = H.make_env(obs, "rew-v1")
    env.reset(seed=11)
    for a in env.agents:
        v = H.flat(env, a)
        assert v.shape == (H.obs_dim(obs),) and v.dtype == np.float32 and np.isfinite(v).all()
    assert (H.obs_dim(H.V2_LOCAL), H.obs_dim(H.V2_SHARED)) == (57, 82)


def test_v2_layout_prefix_is_v0_and_visits_are_node_local():
    env = H.make_env(H.V2_LOCAL, "rew-v1")
    env.reset(seed=11)
    w, a = env.world, env.agents[0]
    v = H.flat(env, a)
    v0 = env._flat(w.observe(a))
    v0[-3:-1] /= H.ENV_KW["size"]
    assert np.array_equal(v[:28], v0)
    assert v[28 + 12] == 0.25  # crop centre: spawn cell stood on once, 1/VISIT_CAP
    assert not v[28:53][np.arange(25) != 12].any()
    # a peer's visits never leak into the local-only id even after an info exchange
    bus = H.InfoBus()
    bus.exchange(w, True)
    assert not w.drones[a].peer_visits


def test_shared_summary_arrives_only_through_info_message():
    env = H.make_env(H.V2_SHARED, "rew-v1")
    env.reset(seed=11)
    w = env.world
    a, b = env.agents
    assert not H.flat(env, a)[57:].any()  # nothing received yet
    bus = H.InfoBus(share_visits=True)
    bus.exchange(w, link_up=False)
    assert not w.drones[a].peer_visits  # link down: nothing arrives
    bus.exchange(w, link_up=True)
    assert w.drones[a].peer_visits == set(w.drones[b].visits) | w.drones[a].peer_visits
    px, py = w.drones[b].pos
    ax, ay = w.drones[a].pos
    if max(abs(px - ax), abs(py - ay)) <= 2:
        assert H.flat(env, a)[57:].sum() >= 1
    assert bus.bytes > 0


def test_frontier_counts_unknown_in_bounds_cells_beyond_crop():
    w = GridWorld(size=16, n_agents=1, n_targets=1, obstacle_density=0.0)
    w.reset(0, starts={"node-0": (8, 8)})
    assert w.observe_memory("node-0")["frontier"] == [1.0, 1.0, 1.0, 1.0]
    w.drones["node-0"].known.update({(x, 5): 0 for x in range(6, 11)})
    assert w.observe_memory("node-0")["frontier"][0] == 0.0
    w.reset(0, starts={"node-0": (0, 0)})
    f = w.observe_memory("node-0")["frontier"]
    assert f == [0.0, 0.6, 0.6, 0.0]  # off-map cells never count as frontier


# ------------------------------------------------------------------------ reward components
def drive(w, acts):
    return w.step({a: acts for a in w.agents})


def test_rew_v1_wall_collision_is_four_times_stronger():
    # a bump leaves the node on its (visited) cell, so rew-v1 also charges the revisit penalty
    for rid, coll in (("rew-v0", -0.5), ("rew-v1", -2.0 - 0.25)):
        w = GridWorld(size=8, n_agents=1, n_targets=1, obstacle_density=0.0, reward_id=rid)
        w.reset(0, starts={"node-0": (0, 0)})
        _, r, *_ = drive(w, "north")
        assert r["node-0"] == pytest.approx(-0.01 + coll)
        assert w.counters["wall_collisions"] == 1


def test_rew_v1_revisit_penalty_and_new_cell_rebalance():
    w = GridWorld(size=16, n_agents=1, n_targets=1, obstacle_density=0.0, reward_id="rew-v1")
    w.reset(0, starts={"node-0": (8, 8)})
    w.targets = []
    _, r1, *_ = drive(w, "east")  # fresh strip of 5 cells x 0.5
    assert r1["node-0"] == pytest.approx(-0.01 + 0.5 * 5)
    _, r2, *_ = drive(w, "west")  # back to the spawn cell: revisit, nothing new
    assert r2["node-0"] == pytest.approx(-0.01 - 0.25)
    _, r3, *_ = drive(w, "stay")  # standing on a visited cell is a revisit too
    assert r3["node-0"] == pytest.approx(-0.01 - 0.25)
    assert w.counters["revisits"] == 2 and w.counters["new_cells"] == 5


def test_rew_v0_has_no_revisit_penalty():
    w = GridWorld(size=16, n_agents=1, n_targets=1, obstacle_density=0.0)
    w.reset(0, starts={"node-0": (8, 8)})
    w.targets = []
    drive(w, "east")
    _, r, *_ = drive(w, "west")
    assert r["node-0"] == pytest.approx(-0.01)


def test_spawn_targets_paid_in_v0_not_in_v1():
    got = {}
    for rid in ("rew-v0", "rew-v1"):
        w = GridWorld(size=16, n_agents=1, n_targets=1, obstacle_density=0.0, reward_id=rid)
        w.reset(0, starts={"node-0": (8, 8)})
        w.targets = [(9, 9)]  # inside the 5x5 sensing window at reset
        w.drones["node-0"].found = {(9, 9)}
        w.spawn_found = {(9, 9)}
        w.found_targets = set() if rid == "rew-v0" else {(9, 9)}
        _, r, *_ = drive(w, "stay")
        got[rid] = r["node-0"]
    assert got["rew-v0"] == pytest.approx(-0.01 + 5.0)
    assert got["rew-v1"] == pytest.approx(-0.01 - 0.25)  # only the stay-revisit, no target credit


def test_v1_reset_credits_no_target_and_metrics_exclude_spawn_targets():
    for seed in range(100, 106):
        w = GridWorld(size=16, n_agents=2, n_targets=8, max_ticks=150, reward_id="rew-v1")
        w.reset(seed)
        assert w.found_targets == w.spawn_found and w.targets_after_spawn == 0
        assert w.coverage_gain == 0.0


@pytest.mark.parametrize("act", [t37.idle_act, t37.rule_act, t37.random_act])
def test_reference_return_equals_env_return_under_rew_v1(act):
    env = H.make_env(H.OBS_ID, "rew-v1")
    rec = H.play(env, H.SCENARIOS["connected"], 101, act(env, 101))
    assert t37.ref_return(rec, 2) == pytest.approx(rec["ret"], abs=1e-6)


# --------------------------------------------------------------------------- learner variants
def test_double_dqn_changes_targets_plain_matches_base_learner():
    from archipelago_learning.dqn import Learner

    def fill(lr):
        r = np.random.default_rng(0)
        for _ in range(64):
            lr.observe(r.random(57), int(r.integers(5)), float(r.random()), r.random(57), False)

    base = Learner("a", 57, 5, seed=1, lr=1e-3, capacity=100)
    plain = t37.VLearner("a", 57, 5, seed=1, lr=1e-3, capacity=100, double=False)
    dbl = t37.VLearner("a", 57, 5, seed=1, lr=1e-3, capacity=100, double=True)
    for lr in (base, plain, dbl):
        fill(lr)
        lr.target = Learner("t", 57, 5, seed=9).params_numpy()  # target differs from online
        for _ in range(5):
            lr.train_step()
    assert all(np.array_equal(base.params[k], plain.params[k]) for k in base.params)
    assert any(not np.array_equal(base.params[k], dbl.params[k]) for k in base.params)


def test_epsilon_schedule_and_config_ids():
    c = t37.Config(eps_start=1.0, eps_end=0.05, eps_frac=0.5, episodes=100)
    assert (
        c.epsilon(0) == 1.0
        and c.epsilon(50) == pytest.approx(0.05)
        and c.epsilon(99) == pytest.approx(0.05)
    )
    assert t37.Config().epsilon(77) == 0.2
    assert t37.Config().id == "grid-flat-v0|rew-v0|eps0.2|lr0.01|rb5000|dqn"


# ------------------------------------------------------------------------ test-seed leakage
def test_selection_and_training_worlds_disjoint_from_frozen_test():
    assert not set(t37.SEL_WORLDS) & set(H.TEST)
    assert not set(t37.SEL_EXTRA) & set(H.VAL) and min(t37.SEL_EXTRA) >= t37.TRAIN_CAP
    pre = t37.load_prereg()
    for key in ("stage_a", "stage_b"):
        e, s = pre[key]["episodes"], pre[key]["seeds"]
        train = H.check_seeds(range(s), e)
        assert max(train) < t37.TRAIN_CAP and not train & set(t37.SEL_WORLDS)


def test_check_world_seeds_rejects_test_seeds():
    with pytest.raises(AssertionError):
        t37.check_world_seeds([100, 205])
    t37.check_world_seeds(t37.SEL_WORLDS)


def test_only_the_test_stage_references_test_seeds():
    for fn in (t37.train_cell, t37.stage_a, t37.stage_b, t37.select, t37.baselines_on):
        src = inspect.getsource(fn)
        assert "H.TEST" not in src.replace("set(H.TEST)", "").replace("+ H.TEST", ""), fn.__name__
    assert "H.TEST" in inspect.getsource(t37.test_once)


def test_train_cell_never_evaluates_on_test_worlds(monkeypatch):
    seen = []
    orig = H.play
    monkeypatch.setattr(
        H, "play", lambda env, sc, s, *a, **k: (seen.append(s), orig(env, sc, s, *a, **k))[1]
    )
    t37.train_cell(t37.Config(episodes=2, obs=H.V2_LOCAL, reward="rew-v1"), 0, checkpoints=1)
    assert seen and not set(seen) & set(H.TEST)
    assert set(seen) >= set(t37.SEL_WORLDS)


def test_test_stage_refuses_second_run(tmp_path):
    (tmp_path / "TEST_DONE").write_text("{}")
    with pytest.raises(AssertionError, match="already used"):
        t37.test_once(t37.load_prereg(), tmp_path)


def test_bootstrap_ci_sane():
    d = np.full((6, 5), 2.0) + np.random.default_rng(0).normal(0, 0.1, (6, 5))
    m, lo, hi, slo, shi = t37.hboot(d, n=500)
    assert lo < m < hi and lo > 1.5 and slo > 1.5
    z = np.zeros((6, 5))
    assert t37.hboot(z, n=200)[1:3] == (0.0, 0.0)

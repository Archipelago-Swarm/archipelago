import dataclasses
import hashlib
import json
import sys
from pathlib import Path

import protocol_harness as H
import numpy as np
import pytest
import run

ROOT = Path(__file__).resolve().parents[2]
SMALL = run.CellConfig(episodes=4, exchange_every=2, test_seeds=H.TEST[:3])


def cell(mode, scen="connected", seed=0, cfg=SMALL):
    return run.Cell(mode, scen, seed, cfg)


# ------------------------------------------------------------------ seeds and frozen scenarios
def test_seed_splits_disjoint_and_overlap_detected():
    H.check_seeds(range(10), 150)
    assert not set(H.VAL) & set(H.TEST)
    with pytest.raises(AssertionError, match="train/test"):
        H.check_seeds(range(3), 100, base=150)  # shifted train range reaches the test seeds
    with pytest.raises(AssertionError, match="train/validation"):
        H.check_seeds(range(3), 100, base=0)
    with pytest.raises(AssertionError, match="validation/test"):
        H.check_seeds([0], 1, val=(200,), test=(200,))


def test_validation_is_node_private_and_test_is_frozen():
    c = cell("p2p")
    c.L[c.agents[0]].n = 0
    seen = []
    orig = H.play
    try:
        H.play = lambda env, sc, seed, *a, **k: (seen.append(seed), orig(env, sc, seed, *a, **k))[1]
        c.validate(c.L[c.agents[0]].params)
    finally:
        H.play = orig
    assert set(seen) == set(H.VAL) and not set(seen) & set(H.TEST)
    with pytest.raises(dataclasses.FrozenInstanceError):
        H.SCENARIOS["connected"].name = "x"
    with pytest.raises(AssertionError):
        run.Cell(
            "idle", "connected", 0, run.CellConfig(test_seeds=(1, 2))
        )  # not a frozen TEST seed


def test_train_seeds_paired_across_modes():
    runs = {
        m: cell(m, seed=1) for m in ("independent", "info_only", "p2p", "central_online", "ctde")
    }
    for c in runs.values():
        c.train()
    assert len({tuple(c.train_seeds) for c in runs.values()}) == 1
    assert runs["p2p"].train_seeds == [H.TRAIN_BASE + 4 + i for i in range(4)]


# ------------------------------------------------------------------ scenarios reach their faults
@pytest.mark.parametrize("scen", [s for s in H.SCENARIOS.values() if s.fault_ticks()])
def test_scenarios_reach_fault_ticks_given_horizon_and_battery(scen):
    last = max(scen.fault_ticks().values())
    assert last <= H.ENV_KW["max_ticks"] and H.battery_reaches(H.ENV_KW["max_ticks"])
    for mode in ("idle", "rule"):  # idle never finishes early; rule is the fastest finisher
        r = cell(mode, scen.name, cfg=run.CellConfig(episodes=1)).run()
        assert r["fault_reached"] and all(v == 1.0 for v in r["fault_reached"].values()), (
            mode,
            r["fault_reached"],
        )
        assert r["min_battery"] > 0


def test_t09_config_never_reached_faults_documented():
    # The old 8x8/2-target/60-tick world ended long before tick 20: guard against regressing to it.
    assert H.ENV_KW["size"] >= 16 and H.ENV_KW["max_ticks"] >= 150


def test_connected_and_outage_and_cut_and_kill_semantics():
    env = H.make_env()
    idle = lambda a, o, t: 0  # noqa: E731
    base = H.play(env, H.SCENARIOS["connected"], 200, idle)
    out = H.play(env, H.SCENARIOS["telemetry_outage"], 200, idle)
    assert (
        out["actions_sha"] == base["actions_sha"] and out["ret"] == base["ret"]
    )  # sink never blocks
    assert out["telemetry"]["peak"] == 15 and out["telemetry"]["undelivered"] == 0
    assert base["telemetry"]["peak"] == 0
    kill = H.play(env, H.SCENARIOS["node_failure"], 200, idle)
    assert kill["agent_steps"] == 2 * 20 + (kill["ticks"] - 20)  # survivors only after the kill
    assert kill["reached"] == {"kill": True}


def test_remove_node_leaves_world_and_agents():
    env = H.make_env()
    env.reset(seed=0)
    H.remove_node(env, "node-1")
    assert env.agents == env.world.agents == ["node-0"] and "node-1" not in env.world.drones


# ------------------------------------------------------------------ budgets are per cell
def test_train_env_steps_is_per_cell_not_cumulative():
    a = cell("independent", "connected", seed=0)
    b = cell("independent", "connected", seed=0)
    ra = a.run()
    r1 = cell("independent", "connected", seed=1).run()
    rb = b.run()
    assert ra["budget"]["train_env_steps"] == sum(ra["budget"]["train_episode_ticks"]) > 0
    assert rb["budget"]["train_env_steps"] == ra["budget"]["train_env_steps"]  # unaffected by order
    assert r1["budget"]["train_env_steps"] == sum(r1["budget"]["train_episode_ticks"])
    assert r1["budget"]["train_env_steps"] <= SMALL.episodes * H.ENV_KW["max_ticks"]


def test_node_failure_counts_surviving_agent_transitions():
    cfg = run.CellConfig(episodes=4, test_seeds=H.TEST[:2])
    nf = cell("independent", "node_failure", cfg=cfg).run()["budget"]
    # episodes 0-1 have both nodes, episodes 2-3 lose node-1 at tick 20
    steps, ticks = nf["train_episode_agent_steps"], nf["train_episode_ticks"]
    assert nf["transitions"] == sum(steps) == nf["agent_steps"]
    for i in (0, 1):
        assert steps[i] == 2 * ticks[i]
    for i in (2, 3):
        assert steps[i] == 2 * min(ticks[i], 20) + max(0, ticks[i] - 20)
    # the old accounting (ticks * n_agents) would overcount
    assert nf["transitions"] < 2 * nf["train_env_steps"]


def test_central_online_budget_reflects_control_link_cuts():
    cfg = run.CellConfig(episodes=3, test_seeds=H.TEST[:2])
    co = cell("central_online", "partition_reconnect", cfg=cfg).run()["budget"]
    ind = cell("independent", "partition_reconnect", cfg=cfg).run()["budget"]
    assert co["blocked_agent_steps"] > 0
    assert co["transitions"] == co["agent_steps"] - co["blocked_agent_steps"]
    assert ind["blocked_agent_steps"] == 0 and ind["transitions"] == ind["agent_steps"]
    # one shared learner: one set of optimizer updates over all recorded transitions
    assert co["optimizer_updates"] <= co["transitions"]


def test_budget_columns_for_all_modes_and_untrained_controls():
    for m in run.MODES:
        b = cell(m).run()["budget"]
        assert {"transitions", "optimizer_updates", "update_samples", "train_env_steps"} <= set(b)
        assert b["trains"] == (m not in run.NOTRAIN)
        if m in run.NOTRAIN:
            assert b["transitions"] == b["optimizer_updates"] == b["train_env_steps"] == 0
        else:
            assert b["transitions"] > 0


# ------------------------------------------------------------------ information sharing
def test_info_bus_adds_peer_map_to_local_knowledge_without_params():
    env = H.make_env()
    env.reset(seed=3)
    w = env.world
    a, b = "node-0", "node-1"
    before_b = dict(w.drones[b].known)
    only_a = {c for c in w.drones[a].known if c not in before_b}
    assert only_a  # drones start in different places
    bus = H.InfoBus()
    bus.exchange(w, link_up=False)
    assert w.drones[b].known == before_b and bus.bytes == 0  # cut link delivers nothing
    bus.exchange(w, link_up=True)
    assert only_a <= set(w.drones[b].known) and bus.msgs == 2
    sent = bus.bytes
    bus.exchange(w, link_up=True)
    assert bus.bytes == sent + 2 * 4  # idempotent: only headers when nothing is new
    assert not hasattr(bus, "params")


def test_info_modes_share_same_information_and_p2p_adds_only_models():
    cfg = run.CellConfig(episodes=2, exchange_every=2, margin=float("inf"), test_seeds=H.TEST[:2])
    io, pp = cell("info_only", cfg=cfg), cell("p2p", cfg=cfg)
    rio, rpp = io.run(), pp.run()
    # a p2p node that rejects every candidate behaves exactly like info_only: identical info channel
    assert rio["replay_hashes"] == rpp["replay_hashes"]
    assert rio["budget"]["info_bytes"] == rpp["budget"]["info_bytes"] > 0
    assert rio["test_info_bytes"] == rpp["test_info_bytes"] > 0
    assert rio["decisions"] == [] and rio["budget"]["model_bytes"] == 0
    assert rio["budget"]["replay_rows_received"] == 0
    assert len(rpp["decisions"]) == 2 and all(not d["accepted"] for d in rpp["decisions"])
    assert io.L["node-0"].mode == "information_only"  # offer() refuses parameters in this mode
    ind = cell("independent", cfg=cfg).run()
    assert ind["budget"]["info_bytes"] == 0 and ind["test_info_bytes"] == 0


def _first_step(obs_id, info):
    env, seen = H.make_env(obs_id), {}

    def hook(obs, acts, rew, nxt, term, t):
        if t == 0:
            seen["o"], seen["r"] = nxt["node-0"].copy(), rew["node-0"]

    H.play(env, H.SCENARIOS["connected"], 5, lambda a, o, t: 0, hook, info=info)
    return seen


def test_shared_map_is_inert_under_v0_and_visible_under_v1_map():
    # v0 crop radius == sense radius, so a node's crop is always fully filled by its own sensing:
    # shared cells can never appear in it. Measured fact, see experiments/diagnosis.
    a, b = _first_step(H.OBS_ID, False), _first_step(H.OBS_ID, True)
    assert np.array_equal(a["o"], b["o"]) and a["r"] == b["r"]
    cfg = run.CellConfig(episodes=2, test_seeds=H.TEST[:2])
    ind, io = cell("independent", cfg=cfg).run(), cell("info_only", cfg=cfg).run()
    assert ind["replay_hashes"] == io["replay_hashes"] and io["budget"]["info_bytes"] > 0
    # the opt-in v1-map observation exposes the shared summary; rewards stay identical
    a, b = _first_step("grid-flat-v1-map", False), _first_step("grid-flat-v1-map", True)
    assert a["o"].shape == (H.obs_dim("grid-flat-v1-map"),) and a["r"] == b["r"]
    assert not np.array_equal(a["o"], b["o"])


def test_replay_sharing_is_separately_labeled_and_copies_rows_only():
    assert "replay" in run.LABELS["replay_sharing"] and "replay_sharing" in run.SECONDARY
    r = cell(
        "replay_sharing", cfg=run.CellConfig(episodes=2, exchange_every=2, test_seeds=H.TEST[:1])
    ).run()
    assert r["budget"]["replay_rows_received"] > 0 and r["budget"]["info_bytes"] == 0
    assert r["budget"]["replay_bytes"] % (4 * (2 * 28 + 3)) == 0
    a, b = run.Learner("a", 28, 5, seed=1), run.Learner("b", 28, 5, seed=2)
    for i in range(10):
        a.observe(np.full(28, i), i % 5, 1.0, np.zeros(28), False)
    p0 = {k: v.copy() for k, v in b.params.items()}
    run.share_obs(a, b, 7)
    assert b.n == 7 and all(np.array_equal(p0[k], b.params[k]) for k in p0)


def test_required_modes_run_and_secondary_are_labeled():
    assert run.REQUIRED == ("rule", "idle", "independent", "info_only", "p2p")
    for m in run.REQUIRED:
        r = cell(m).run()
        assert r["label"].startswith("required") and len(r["returns"]) == 3
    for m in run.SECONDARY:
        assert run.LABELS[m].startswith("secondary")
    assert (
        "not a validated" in run.LABELS["central_online"] and "approximation" in run.LABELS["ctde"]
    )


def test_ctde_has_per_node_actors_and_trains_a_joint_critic():
    c = cell("ctde")
    c.train()
    assert c.L["node-0"] is not c.L["node-1"] and c.critic.n > 0 and c.critic.obs_dim == 56
    assert all(x.n > 0 for x in c.L.values())
    co = cell("central_online")
    assert co.L["node-0"] is co.L["node-1"]


# ------------------------------------------------------------------ validation overhead
def test_validation_cost_recorded_per_candidate_decision():
    cfg = run.CellConfig(episodes=4, exchange_every=2, test_seeds=H.TEST[:1])
    c = cell("p2p", cfg=cfg)
    r = c.run()
    assert len(r["decisions"]) == 4  # two swap windows x two directions
    nval = len(cfg.val_seeds)
    for d in r["decisions"]:
        assert d["evaluations"] == 2 * nval  # current + candidate on every validation seed
        assert d["bytes"] > 0 and d["eval_env_ticks"] > 0
        assert d["current_score"] is not None and d["candidate_score"] is not None
    assert r["budget"]["validation_evals"] == sum(d["evaluations"] for d in r["decisions"])
    assert r["budget"]["model_bytes"] == sum(d["bytes"] for d in r["decisions"])
    assert len(c.decision_wall) == len(r["decisions"]) and all(w > 0 for w in c.decision_wall)


def test_partition_blocks_model_swaps_during_cut_episodes():
    cfg = run.CellConfig(episodes=6, exchange_every=1, test_seeds=H.TEST[:1])
    r = cell("p2p", "partition_reconnect", cfg=cfg).run()
    assert {d["episode"] for d in r["decisions"]} == {0, 1, 4, 5}  # episodes 2,3 are cut
    k = cell("p2p", "node_failure", cfg=cfg).run()
    assert {d["episode"] for d in k["decisions"]} == {0, 1, 2}  # none once node-1 is dead


# ------------------------------------------------------------------ bundle, manifest, report
def test_rerun_identical_and_main_writes_bundle(tmp_path):
    args = [
        "--seeds",
        "2",
        "--episodes",
        "2",
        "--test-seeds",
        "2",
        "--scenarios",
        "node_failure",
        "connected",
        "--mode",
        "required",
        "ctde",
        "--exchange-every",
        "2",
        "--report",
    ]
    got = []
    for _ in range(2):
        run.main([*args, "--out", str(tmp_path)])
        got.append(
            [(tmp_path / f).read_bytes() for f in ("raw.jsonl", "per_seed.csv", "summary.json")]
        )
    assert got[0] == got[1]
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert len(man["commit"]) == 40 or man["commit"] == "unknown"
    assert man["seeds"]["experiment_seeds"] == [0, 1] and man["seeds"]["test"] == list(H.TEST[:2])
    assert man["config_hash"] and man["reward_hash"] == H.reward_hash() and man["commands"]["argv"]
    assert set(man["scenario_hashes"]) == set(H.SCENARIOS) and man["backend"] == "numpy"
    for f, h in man["sha256"].items():
        assert hashlib.sha256((tmp_path / f).read_bytes()).hexdigest() == h
    rows = [json.loads(x) for x in (tmp_path / "raw.jsonl").read_text().splitlines()]
    assert len(rows) == 2 * 2 * 6 and {r["seed"] for r in rows} == {0, 1}
    assert "wall_s" in (tmp_path / "timing.jsonl").read_text()
    csv = (tmp_path / "per_seed.csv").read_text().splitlines()
    assert csv[0].startswith("scenario,mode,seed") and len(csv) == 1 + len(rows)
    rep = (tmp_path / "REPORT.md").read_text()
    r0 = next(
        r
        for r in rows
        if r["mode"] == "independent" and r["scenario"] == "connected" and r["seed"] == 0
    )
    assert (
        man["commit"] in rep and f"{r0['budget']['transitions']}" in rep
    )  # numbers come from artifacts


def test_unknown_backend_and_mode_rejected():
    with pytest.raises(SystemExit):
        run.main(
            ["--backend", "torch", "--out", "/nonexistent"]
        )  # torch is added by the live-runtime task
    with pytest.raises(SystemExit):
        run.main(["--mode", "bogus"])
    assert set(run.BACKENDS) == {"numpy"}


def test_report_numbers_are_generated(tmp_path):
    import report

    run.main(
        [
            "--seeds",
            "2",
            "--episodes",
            "2",
            "--test-seeds",
            "2",
            "--scenarios",
            "connected",
            "--mode",
            "idle",
            "independent",
            "--out",
            str(tmp_path),
        ]
    )
    rows, man, summ, timing = report.load(tmp_path)
    text = report.render(rows, man, summ, timing)
    idle = [r["mean"] for r in rows if r["mode"] == "idle"]
    assert report.ms(idle) in text and "PRELIMINARY" in text


# ------------------------------------------------------------------ preserved history
def test_history_is_labeled_and_hashes_match():
    h = ROOT / "experiments/history"
    banner = (h / "README.md").read_text()
    assert "predate" in banner and "differs from the current harness" in banner
    assert (h / "REPORT_T09.md").read_text().lstrip().startswith("> **HISTORICAL")
    assert "do NOT verify" in banner  # history/out was already stale before the repair
    ev = ROOT / "agents/handoffs/T09/evidence"  # the committed, verifiable T09 bundle (read-only)
    man = json.loads((ev / "manifest.json").read_text())
    for name, want in man["sha256"].items():
        data = (ev / name).read_bytes().replace(bytes([13, 10]), bytes([10]))
        assert hashlib.sha256(data).hexdigest() == want, name
    assert (
        not (ROOT / "experiments/REPORT.md").exists()
        or "generated" in (ROOT / "experiments/REPORT.md").read_text()
    )
    assert sys.modules["run"].__file__ != str(h / "run_t09.py")

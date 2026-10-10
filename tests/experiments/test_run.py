import run


def test_seeds_disjoint_and_overlap_detected():
    run.check_seeds(range(3), 20)
    try:
        run.check_seeds(range(6000), 20)  # train seeds reach 100000
    except AssertionError:
        return
    raise AssertionError("overlap not detected")


def test_rerun_identical_and_ctde_not_gated_by_link(tmp_path):
    a = run.run_cell("ctde", "split", 0, 4, [0])
    b = run.run_cell("ctde", "split", 0, 4, [0])
    assert a["replay_hashes"] == b["replay_hashes"]
    # same seeds => ctde trains identically whatever the link does; central_online does not
    c = run.run_cell("ctde", "connected", 0, 4, [0])
    assert a["replay_hashes"] == c["replay_hashes"]
    o = run.run_cell("central_online", "split", 0, 4, [0])
    assert o["replay_hashes"] != a["replay_hashes"]


def test_main_writes_bundle(tmp_path):
    run.main(["--seeds", "2", "--episodes", "4", "--scenarios", "split", "--out", str(tmp_path)])
    for f in ("raw.jsonl", "summary.json", "manifest.json"):
        assert (tmp_path / f).exists()


def test_matched_budget_and_paired_summary():
    rows = [
        run.run_cell(m, "connected", s, 5, [0])
        for m in ("independent", "p2p", "information_only")
        for s in range(2)
    ]
    assert {(r["episodes"], len(r["returns"])) for r in rows} == {(5, len(run.TEST))}
    summ = {r["mode"]: r for r in run.summarise(rows)}
    assert summ["p2p"]["n"] == 2 and summ["p2p"]["ci95"][0] <= summ["p2p"]["ci95"][1]
    assert not set(run.TEST) & set(run.VAL)


def test_node_failure_changes_test_outcome():
    a = run.run_cell("independent", "node_failure", 0, 4, [0])
    b = run.run_cell("independent", "connected", 0, 4, [0])
    assert a["replay_hashes"] != b["replay_hashes"]


def test_information_only_shares_data_not_parameters():
    rows = {
        m: run.run_cell(m, "connected", 0, 10, [0]) for m in ("independent", "information_only")
    }
    io = rows["information_only"]
    assert io["exchange_bytes"] > 0 and rows["independent"]["exchange_bytes"] == 0
    assert io["rejected_exchanges"] == 0
    assert io["replay_hashes"] != rows["independent"]["replay_hashes"]  # no longer a stub


def test_down_node_is_inert():
    d = run.Down()
    assert d.act(None, 0.2) == 0 and d.observe(1) is None and d.train_step() is None


def test_committed_evidence_hashes_match():
    import hashlib
    import json
    import pathlib

    d = pathlib.Path(__file__).resolve().parents[2] / "agents/handoffs/T09/evidence"
    assert (d / "manifest.json").exists(), "evidence bundle missing"
    for name, h in json.loads((d / "manifest.json").read_text())["sha256"].items():
        assert hashlib.sha256((d / name).read_bytes()).hexdigest() == h, name


def test_rerun_bundle_byte_identical(tmp_path):
    args = ["--seeds", "2", "--episodes", "4", "--scenarios", "node_failure", "split"]
    got = []
    for _ in range(2):
        run.main([*args, "--out", str(tmp_path)])
        got.append([(tmp_path / f).read_bytes() for f in ("raw.jsonl", "summary.json")])
    assert got[0] == got[1]
    assert "wall_s" in (tmp_path / "manifest.json").read_text()


def test_share_obs_copies_only_replay_rows_and_bytes_match():
    a, b = run.make_learner("a", 1), run.make_learner("b", 2)
    env = run.make_env()
    run.episode(env, {x: a for x in env.possible_agents}, 0, 0.2)
    before_params, n0 = copy_params(b), b.n
    k = min(7, a.n)
    run.share_obs(a, b, k)
    assert b.n == n0 + k  # exactly k rows copied
    assert copy_params(b) == before_params  # no parameters leak
    cell = run.run_cell("information_only", "connected", 0, 10, [0])
    row = 4 * (2 * a.obs_dim + 3)
    assert cell["exchange_bytes"] > 0 and cell["exchange_bytes"] % row == 0


def copy_params(learner):
    import hashlib
    import pickle

    return hashlib.sha256(pickle.dumps(learner.snapshot())).hexdigest()


def test_central_online_inference_needs_link_but_ctde_does_not():
    kw = dict(seed=0, episodes=4, steps=[0])
    off = run.run_cell("central_online", "split", **kw)
    on = run.run_cell("central_online", "connected", **kw)
    assert off["replay_hashes"] != on["replay_hashes"]
    assert off["mean"] == run.run_cell("central_online", "split", **{**kw, "steps": [0]})["mean"]
    assert (
        run.run_cell("ctde", "split", **kw)["replay_hashes"]
        == (run.run_cell("ctde", "connected", **kw)["replay_hashes"])
    )


def test_idle_control_matches_central_online_without_controller():
    c = run.run_cell("central_online", "split", 0, 4, [0])
    i = run.run_cell("idle", "split", 0, 4, [0])
    assert c["replay_hashes"] == i["replay_hashes"]

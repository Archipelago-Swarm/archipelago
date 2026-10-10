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
    assert all(r["rejected_exchanges"] > 0 for r in rows if r["mode"] == "information_only")
    assert not set(run.TEST) & set(run.VAL)


def test_node_failure_changes_test_outcome():
    a = run.run_cell("independent", "node_failure", 0, 4, [0])
    b = run.run_cell("independent", "connected", 0, 4, [0])
    assert a["replay_hashes"] != b["replay_hashes"]


def test_information_only_flagged_stub_and_bytes_counted():
    rows = [
        run.run_cell(m, "connected", 0, 5, [0]) for m in ("independent", "information_only", "p2p")
    ]
    assert rows[1]["exchange_bytes"] > 0 and rows[0]["exchange_bytes"] == 0
    assert {r["mode"]: r["stub"] for r in run.summarise(rows)} == {
        "information_only": True,
        "p2p": False,
    }


def test_committed_evidence_hashes_match():
    import hashlib
    import json
    import pathlib

    d = pathlib.Path(__file__).resolve().parents[2] / "agents/handoffs/T09/evidence"
    if not (d / "manifest.json").exists():
        return
    for name, h in json.loads((d / "manifest.json").read_text())["sha256"].items():
        assert hashlib.sha256((d / name).read_bytes()).hexdigest() == h, name

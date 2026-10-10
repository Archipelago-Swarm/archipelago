import run


def test_seeds_disjoint_and_overlap_detected():
    run.check_seeds(range(3), 20)
    try:
        run.check_seeds(range(60), 20)  # train seeds reach 900
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

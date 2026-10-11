# ruff: noqa: E501
"""T30 analysis library and harness configuration (no live cluster is started here)."""

from __future__ import annotations

import json

import pytest
import t30_analysis as A
import t30_report as R
import yaml
from archipelago_sim2d.adapter import Sim2DAdapter
from archipelago_sim2d.smoke import make_action, make_config

HALVES = {"node-01": 0, "node-02": 0, "node-03": 1, "node-04": 1}
CUT = [{"start_tick": 40, "end_tick": 90}]


def dec(node, src, tick, transfer="rejected", ep=0, n=[0]):  # noqa: B006 - counter for unique ids
    n[0] += 1
    reason = (
        f"source={src} v=1 sha256=ab margin=1.0" if transfer == "accepted"
        else f"candidate not better than current policy (source={src} v=1 sha256=ab)"
    )  # fmt: skip
    return {
        "kind": "learning_event", "transfer": transfer, "reason": reason, "source_node_id": node,
        "sim_tick": ep * 150 + tick, "event_id": f"{node}-b-{n[0]}", "sequence": n[0],
    }  # fmt: skip


# ----------------------------------------------------------------------------------- statistics
def test_paired_bootstrap_separates_a_clear_gain_and_keeps_noise_inconclusive():
    gain = A.paired_bootstrap([1.0, 1.2, 0.9, 1.1, 1.0, 0.8, 1.3, 1.0])
    assert gain["ci95"][0] > 0 and A.verdict(gain) == "better" and gain["worlds_positive"] == 8
    noise = A.paired_bootstrap([-1.0, 1.0, 2.0, -2.0, 0.5, -0.5])
    assert A.verdict(noise) == "inconclusive" and noise["ci95"][0] < 0 < noise["ci95"][1]
    loss = A.paired_bootstrap([-3.0, -2.5, -3.5, -2.0])
    assert A.verdict(loss) == "worse"
    assert A.paired_bootstrap([1.0, 2.0, 3.0]) == A.paired_bootstrap([1.0, 2.0, 3.0])  # seeded


# ------------------------------------------------------------------------------------ outcomes
def one_episode(policy_maker, ticks=20, seed=1, n=4):  # maps derive from (seed, episode)
    cfg = make_config(seed, ticks, n)
    kw = {"size": 8, "n_targets": 3, "battery_scale": 4.0}
    return cfg, kw, A.play_policy(cfg, kw, policy_maker)


def test_idle_return_is_the_revisit_plus_step_penalty_only():
    _, _, m = one_episode(A.idle_policy, ticks=20)
    # rew-v1: step -0.01 and revisit -0.25 per agent tick, spawn targets earn nothing
    assert m["ref_return"] == pytest.approx(-0.26 * 20)
    assert m["coverage_gain"] == 0 and m["targets_after_spawn"] == 0 and m["revisit_rate"] == 1.0


def test_rule_explorer_beats_idle_and_is_deterministic():
    cfg, kw, rule = one_episode(
        A.rule_policy, ticks=40, seed=1
    )  # seed 1: maps are now derived from (seed, episode)
    assert rule["coverage_gain"] > 0.2 and rule["ref_return"] > -0.26 * 40
    assert A.play_policy(cfg, kw, A.rule_policy) == rule


def test_replay_metrics_re_executes_written_replay_and_matches_the_live_world(tmp_path):
    cfg = make_config(11, 25, 4)
    kw = {"size": 8, "n_targets": 3, "battery_scale": 4.0}
    ad = Sim2DAdapter(**kw)
    ad.reset(cfg)
    cycle = ["east", "south", "west", "north", "stay"]
    for t in range(25):
        if not ad.world.agents:  # the episode may end early (all targets found)
            break
        ad.step({f"node-{i}": make_action(f"node-{i}", t, cycle[(t + i) % 5]) for i in range(4)})
    expected = A.world_metrics(ad.world, 4)
    ad.write_replay(tmp_path / "ep-0000")
    assert A.replay_metrics(tmp_path / "ep-0000") == expected
    manifest = tmp_path / "ep-0000" / "manifest.json"
    bad = json.loads(manifest.read_text())
    bad["final_state_hash"] = "0" * 64
    manifest.write_text(json.dumps(bad))
    with pytest.raises(AssertionError, match="replay diverged"):
        A.replay_metrics(tmp_path / "ep-0000")


# ---------------------------------------------------------------------------- partition evidence
def test_decision_source_parses_accepts_and_rejects():
    assert A.decision_source("source=node-03 v=2 sha256=ab margin=1") == "node-03"
    assert A.decision_source("window_limit (source=node-01 v=1 sha256=ab)") == "node-01"
    assert A.decision_source("local_update window=50 mean_loss") is None


def test_split_decisions_flags_a_cross_cut_decision_inside_the_window_only():
    recs = [
        dec("node-01", "node-03", 25, "accepted"),  # cross, before the cut
        dec("node-01", "node-03", 100),  # cross, after the cut
        dec("node-01", "node-03", 150 * 0 + 0, ep=3),  # cross, final window (tick 150 -> 0)
        dec("node-01", "node-02", 50, "accepted"),  # same side, inside the cut
        dec("node-04", "node-03", 75),  # same side, inside the cut
        dec("node-02", "node-04", 50),  # VIOLATION: cross inside the cut
        {"kind": "metric_sample", "metric": "x", "sim_tick": 1, "event_id": "m", "sequence": 0},
    ]
    out = A.split_decisions(recs, HALVES, CUT, 150)
    assert out["decisions"] == 6 and out["accepted"] == 2 and out["rejected"] == 4
    assert out["cross_outside_cut"] == 3 and out["same_side_inside_cut"] == 2
    assert [v["src"] for v in out["cross_inside_cut"]] == ["node-04"]
    assert out["by_reason"]["accepted"] == 2 and out["by_reason"]["candidate"] == 4
    clean = A.split_decisions(recs[:5], HALVES, CUT, 150)
    assert clean["cross_inside_cut"] == []


def test_isolated_windows_make_every_cross_node_decision_a_violation():
    sep = {n: i for i, n in enumerate(HALVES)}
    out = A.split_decisions(
        [dec("node-01", "node-02", 10)], sep, [{"start_tick": 0, "end_tick": 150}], 150
    )
    assert len(out["cross_inside_cut"]) == 1


def test_summary_rx_evidence_counts_by_side_and_window():
    rx = {
        "node-01": {"0": {"node-02": [10, 45, 60], "node-03": [10, 39, 95], "node-04": [41]}},
        "node-03": {"0": {"node-04": [50], "node-01": [91]}},
    }
    out = A.summary_rx_evidence(rx, HALVES, CUT)
    assert out["same_side_applied_inside_cut"] == 3 and out["same_side_applied_outside_cut"] == 1
    assert out["cross_applied_inside_cut"] == 1 and out["cross_applied_outside_cut"] == 4


def test_sequence_continuity_detects_reuse_and_overlap():
    def rec(seq, boot):
        return {"source_node_id": "node-03", "event_id": f"node-03-{boot}-{seq}", "sequence": seq}

    ok = [rec(s, "aaaa1111") for s in (0, 1, 2, 900)] + [rec(s, "bbbb2222") for s in (1000, 1001)]
    out = A.sequence_continuity(ok, "node-03")
    assert [b["boot_id"] for b in out["boots"]] == ["aaaa1111", "bbbb2222"]
    assert not out["ranges_overlap"] and out["duplicate_event_ids"] == 0
    bad = [rec(s, "aaaa1111") for s in (0, 1, 2)] + [rec(s, "bbbb2222") for s in (2, 3)]
    out = A.sequence_continuity(bad, "node-03")
    assert out["ranges_overlap"]
    dup = ok + [rec(1, "aaaa1111")]
    assert A.sequence_continuity(dup, "node-03")["duplicate_event_ids"] == 1


def test_claim_b_fails_when_a_cross_cut_decision_lands_inside_the_window():
    def nodes(**kw):
        base = {"offers_cut": 4, "summaries_cut": 40, "offers_sent": 5, "offers_received": 5,
                "summaries_sent": 90, "summaries_received": 90}  # fmt: skip
        return {n: base | kw for n in HALVES}

    grew = {n: {"episodes_with_growth_in_window": 3, "episodes_flat_in_window": 0} for n in HALVES}
    good = {
        "B_local_learning_in_cut": grew, "B_counters": nodes(),
        "B_decisions": A.split_decisions(
            [dec("node-01", "node-03", 100), dec("node-01", "node-02", 50)], HALVES, CUT, 150
        ),
        "B_summaries": {"cross_applied_inside_cut": 0, "cross_applied_outside_cut": 9,
                        "same_side_applied_inside_cut": 4, "same_side_applied_outside_cut": 4},
    }  # fmt: skip
    assert R.claim_b("fleet", good)["supported"]
    bad = dict(
        good, B_decisions=A.split_decisions([dec("node-01", "node-03", 60)], HALVES, CUT, 150)
    )
    r = R.claim_b("fleet", bad)
    assert (
        not r["supported"] and not r["checks"][next(k for k in r["checks"] if k.startswith("(ii)"))]
    )
    leak = dict(good, B_summaries=good["B_summaries"] | {"cross_applied_inside_cut": 1})
    assert not R.claim_b("fleet", leak)["supported"]
    stalled = dict(good, B_local_learning_in_cut={n: {"episodes_with_growth_in_window": 0,
                                                      "episodes_flat_in_window": 2} for n in HALVES})  # fmt: skip
    assert not R.claim_b("fleet", stalled)["supported"]


# ------------------------------------------------------------------------------ configuration
def test_registered_plan_uses_frozen_test_seeds_once_and_disjoint_training_seeds():
    import t30_live as L

    pre = L.load_prereg()
    cfg = L.arm_config(pre, "fleet", smoke=False)
    kinds = [(e["kind"], range(e["seed"], e["seed"] + e["count"])) for e in cfg["episodes"]]
    test = [r for k, r in kinds if k == "test"]
    assert len(test) == 1 and list(test[0]) == list(range(200, 220))
    train = {s for k, r in kinds if k == "train" for s in r}
    val = {s for k, r in kinds if k == "validation" for s in r}
    assert train.isdisjoint(test[0]) and val.isdisjoint(test[0]) and train.isdisjoint(val)
    assert max(train) < 5000 and not set(range(5000, 5020)) & train
    assert not set(range(200, 220)) & set(pre["plan"]["node_config"]["gate_seeds"])
    # the kill lands inside a training block, after the first checkpoint opportunities
    idx = cfg["kill"]["at_episode_index"]
    order = [k for k, r in kinds for _ in r]
    assert order[idx] == "train" and order[:idx].count("train") >= 20


def test_smoke_plan_never_touches_the_frozen_test_seeds():
    import t30_live as L

    cfg = L.arm_config(L.load_prereg(), "fleet", smoke=True)
    seeds = {s for e in cfg["episodes"] for s in range(e["seed"], e["seed"] + e["count"])}
    assert not seeds & set(range(200, 220))


def test_fault_schedules_are_expressible_and_isolated_control_cuts_every_pair():
    import t30_live as L

    pre = L.load_prereg()
    fleet = L.arm_config(pre, "fleet", False)["faults"]
    iso = L.arm_config(pre, "isolated", False)["faults"]
    assert fleet == [{"start_tick": 40, "end_tick": 90, "cut_links": fleet[0]["cut_links"]}]
    cross = {frozenset(p) for p in fleet[0]["cut_links"]}
    assert all(HALVES[a] != HALVES[b] for a, b in map(tuple, cross)) and len(cross) == 4
    assert len(iso[0]["cut_links"]) == 6 and iso[0]["start_tick"] == 0
    for w in fleet + iso:  # coordinator A13: windows must end within max_ticks
        assert w["end_tick"] <= pre["world"]["max_ticks"]


def test_cluster_geometry_matches_the_prereg_world():
    import t30_cluster as C

    pre = yaml.safe_load(R.PREREG.read_text())
    w = pre["world"]
    assert (C.SIZE, C.N_TARGETS, C.MAX_TICKS) == (w["size"], w["n_targets"], w["max_ticks"])
    assert {k: tuple(v) for k, v in w["starts"].items()} == C.STARTS_16
    assert len(set(C.STARTS_16.values())) == 4
    assert all(0 <= x < C.SIZE and 0 <= y < C.SIZE for x, y in C.STARTS_16.values())

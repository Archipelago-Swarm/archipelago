# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""Offline tests of infra/demo/artifacts.py from recorded canonical events (no Docker, no network)."""

import csv
import io
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from archipelago_contracts.models import RECORDS

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra/demo"))

import artifacts as art  # noqa: E402

FIXTURE = ROOT / "apps/web/src/fixtures/partition_run.json"
H64 = "a" * 64


def _meta(**o):
    return {
        "commit": "abc1234",
        "image_digests": {"node": "sha256:" + H64},
        "wall_seconds": 12.5,
        **o,
    }


def _base(seq, node, tick, **kw):
    return {
        "schema_version": "0.1.0",
        "run_id": "run-synth",
        "sim_tick": tick,
        "emitted_at_utc": "2026-10-10T12:00:00Z",
        "sequence": seq,
        "event_id": f"ev-{seq}",
        "source_node_id": node,
        **kw,
    }


def synthetic_run(max_ticks=100, episodes=2, cut=(30, 60)):
    """Two 4-node episodes with a cut window: no offers over cut links, decisions after rejoin."""
    nodes = [f"node-0{i}" for i in range(1, 5)]
    full = [[a, b] for i, a in enumerate(nodes) for b in nodes[i + 1 :]]
    halves = [["node-01", "node-02"], ["node-03", "node-04"]]
    ev: list[dict] = []
    seq = 0

    def nxt():
        nonlocal seq
        seq += 1
        return seq

    for ep in range(episodes):
        for tick in range(0, max_ticks, 10):
            t = ep * max_ticks + tick
            cut_now = cut[0] <= tick < cut[1]
            phase = 1 if cut_now else (2 if cut[1] <= tick < cut[1] + 10 else 0)
            ev.append(
                _base(
                    nxt(), None, t, kind="world_snapshot", run_status="running",
                    poses={n: {"x": i, "y": tick % 7, "z": 0, "heading_rad": 0} for i, n in enumerate(nodes)},
                    obstacles=[], coverage=min(1.0, (ep * max_ticks + tick) / (episodes * max_ticks)),
                    topology={"links": halves if cut_now else full},
                )
            )  # fmt: skip
            ev.append(_base(nxt(), None, t, kind="metric_sample", metric="fault_phase", value=phase,
                            unit="state", phase="partition" if phase == 1 else "recovery" if phase == 2 else "other"))  # fmt: skip
            for n in nodes:
                ev.append(_base(nxt(), n, t, kind="learning_event", update_count=(t + 1) * 5, loss=1.0 / (1 + t),
                                previous_version=t // 10, new_version=t // 10 + 1, transfer="none",
                                reason=None, candidate_score=None, bytes=0, wall_seconds=0.001))  # fmt: skip
        # one exchange at rejoin: node-01 offers node-03, accepted; node-02 offers node-04, rejected
        t = ep * max_ticks + cut[1]
        for s, r, tr, why in (("node-01", "node-03", "accepted", "score_improved"),
                              ("node-02", "node-04", "rejected", "window_limit")):  # fmt: skip
            ev.append(_base(nxt(), s, t, kind="peer_envelope", type="model_offer", sender=s, recipient=r,
                            message_id=f"m-{seq}", model_version=3, architecture_hash=H64, encoder_hash=H64,
                            reward_hash=H64, payload_length=4400, payload_sha256=H64, ttl_ticks=10))  # fmt: skip
            ev.append(_base(nxt(), r, t, kind="learning_event", update_count=t, loss=0.1, previous_version=2,
                            new_version=3 if tr == "accepted" else 2, transfer=tr, reason=why,
                            candidate_score=0.5, bytes=4400, wall_seconds=0.2))  # fmt: skip
        for n in nodes:
            for phase, v in (("train" if ep == 0 else "eval", float(ep) + 0.5),):
                ev.append(_base(nxt(), n, ep * max_ticks + max_ticks - 1, kind="metric_sample",
                                metric="episode_return", value=v, unit="return", phase=phase))  # fmt: skip
    return ev


def test_fixture_and_synthetic_records_are_valid_contract_records():
    for ev in (json.loads(FIXTURE.read_text()), synthetic_run()):
        for e in ev:
            RECORDS[e["kind"]].model_validate(e)


def test_recorded_partition_fixture_produces_every_artifact():
    ev = json.loads(FIXTURE.read_text())
    out = art.build_artifacts(ev, _meta(run_config={"learner": "peer_dqn", "mode": "lockstep"}))
    assert set(out) == {
        "summary.json", "curves.csv", "peer_decisions.csv", "topology_snapshots.json",
        "node_timeline.json", "learning_curve.svg", "coverage_return.svg", "partition_timeline.svg",
    }  # fmt: skip
    s = json.loads(out["summary.json"])
    assert s["peer"]["accepted"] == 2 and s["peer"]["rejected"] == 1 and s["peer"]["offers"] == 3
    assert s["peer"]["bytes_accepted"] == 2048 + 4096
    assert s["peer"]["rejection_reasons"] == {"score_below_tolerance": 1}
    assert s["commit"] == "abc1234" and s["wall_seconds"] == 12.5
    assert s["modes"] == {"learner": "peer_dqn", "run_mode": "lockstep"}
    assert (
        s["nodes"]["node-01"]["update_count"] == 10 and s["nodes"]["node-02"]["policy_version"] == 3
    )
    phases = [(p["phase"], p["start"]) for p in s["fault_phases"]]
    assert phases == [("normal", 0), ("partition", 4), ("recovery", 6), ("normal", 7)]
    rows = list(csv.DictReader(io.StringIO(out["peer_decisions.csv"])))
    assert [r["transfer"] for r in rows if r["event"] == "decision"] == [
        "accepted",
        "rejected",
        "accepted",
    ]
    curves = list(csv.DictReader(io.StringIO(out["curves.csv"])))
    assert curves[0].keys() >= {
        "node_id",
        "loss",
        "update_count",
        "policy_version",
        "coverage",
        "return_eval",
    }
    for name, text in out.items():
        if name.endswith(".svg"):
            assert ET.fromstring(text).tag.endswith("svg")
        elif name.endswith(".json"):
            json.loads(text)


def test_multi_episode_run_splits_ticks_and_labels_episode_kinds():
    meta = _meta(max_ticks=100, episodes=[{"kind": "train"}, {"kind": "test"}])
    ev = synthetic_run(max_ticks=100, episodes=2)
    out = art.build_artifacts(ev, meta)
    curves = list(csv.DictReader(io.StringIO(out["curves.csv"])))
    late = [r for r in curves if r["node_id"] == "node-03" and r["sim_tick"] == "150"]
    assert (
        late
        and late[0]["episode"] == "1"
        and late[0]["tick"] == "50"
        and late[0]["episode_kind"] == "test"
    )
    s = json.loads(out["summary.json"])
    assert [(e["episode"], e["kind"]) for e in s["episode_returns"]] == [(0, "train"), (1, "test")]
    assert (
        s["episode_returns"][0]["mean_train"] == 0.5 and s["episode_returns"][1]["mean_eval"] == 1.5
    )


def test_cut_links_carry_no_offers_and_evidence_is_computed_from_the_topology():
    ev = synthetic_run()
    assert (
        art.summarize(art.normalize(ev), {"max_ticks": 100})["peer"]["offers_over_cut_links"] == 0
    )
    # Move an offer into the window across the cut: the summary must flag exactly that one.
    bad = [dict(e) for e in ev]
    first_offer = next(e for e in bad if e["kind"] == "peer_envelope")
    first_offer["sim_tick"] = 40  # inside the cut window, node-01 -> node-03 crosses the halves
    s = art.summarize(art.normalize(bad), {"max_ticks": 100})
    assert s["peer"]["offers_over_cut_links"] == 1


def test_topology_snapshots_cover_each_phase_and_stay_bounded():
    snaps = art.topology_snapshots(art.normalize(synthetic_run(episodes=2)), {"max_ticks": 100})
    assert 3 <= len(snaps) <= art.MAX_TOPOLOGY_SNAPSHOTS
    by_phase = {s["phase"]: s for s in snaps}
    assert {"normal", "partition"} <= set(by_phase)
    assert len(by_phase["partition"]["links"]) == 2  # two halves
    assert len(by_phase["normal"]["links"]) == 6


def test_node_timeline_lists_decisions_per_node():
    tl = art.node_timeline(art.normalize(synthetic_run()), {"max_ticks": 100})
    assert set(tl["nodes"]) == {"node-01", "node-02", "node-03", "node-04"}
    assert tl["nodes"]["node-03"]["counts"]["peer_accepted"] == 2  # one per episode
    assert tl["nodes"]["node-04"]["counts"]["peer_rejected"] == 2
    assert tl["nodes"]["node-01"]["counts"]["offer_sent"] == 2
    assert any(p["phase"] == "partition" for p in tl["fault_phases"])


def test_duplicates_and_wrapped_input_are_normalized():
    ev = json.loads(FIXTURE.read_text())
    wrapped = {"events": ev + ev[:5]}
    assert len(art.normalize(wrapped)) == len(ev)


def test_empty_run_still_writes_valid_artifacts(tmp_path):
    paths = art.write_artifacts([], tmp_path / "out", _meta())
    assert {p.name for p in paths} >= {"summary.json", "curves.csv", "partition_timeline.svg"}
    for p in paths:
        if p.suffix == ".svg":
            ET.parse(p)
    assert json.loads((tmp_path / "out/summary.json").read_text())["events"] == 0


@pytest.mark.parametrize("name", ["learning_curve", "coverage_return", "partition_timeline"])
def test_svgs_draw_data(name):
    out = art.build_artifacts(synthetic_run(), _meta(max_ticks=100))
    svg = out[f"{name}.svg"]
    assert "no data" not in svg and ("<path" in svg or "<circle" in svg)


def test_node_reported_offer_counters_use_the_last_cumulative_value_per_node():
    ev = []
    for seq, (node, metric, v) in enumerate(
        [("node-01", "peer_offers_sent", 1), ("node-01", "peer_offers_sent", 3), ("node-02", "peer_offers_sent", 2),
         ("node-01", "peer_offers_cut", 2), ("node-02", "peer_offers_cut", 1)], start=1,
    ):  # fmt: skip
        ev.append(
            _base(
                seq,
                node,
                seq,
                kind="metric_sample",
                metric=metric,
                value=v,
                unit="count",
                phase="train",
            )
        )
    peer = art.summarize(art.normalize(ev))["peer"]
    assert peer["offers_sent_by_nodes"] == 5 and peer["offers_blocked_by_cut"] == 3

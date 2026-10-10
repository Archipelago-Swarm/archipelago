import json
import time
from datetime import UTC, datetime

import pytest
from archipelago_contracts.models import LearningEvent, MetricSample
from archipelago_noderuntime.runtime import Runtime
from archipelago_noderuntime.telemetry import Shipper, Spool
from support import Client, FakeSink, MiniCoordinator, make_cfg


def wait_until(pred, timeout=10.0, step=0.02):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(step)
    return False


def line(i):
    return {"event_id": f"n-b-{i}", "phase": "train", "record": {"sequence": i, "x": i}}


# --- spool as a unit ----------------------------------------------------------------------
def test_spool_is_bounded_keeps_newest_and_counts_every_drop(tmp_path):
    sp = Spool(tmp_path / "s", max_records=20, seg_records=5)
    for i in range(100):
        sp.append(line(i))
    st = sp.state()
    assert sp.backlog <= 20
    assert st["dropped"] + sp.backlog == 100  # nothing vanished silently
    recs, _ = sp.peek(1000)
    ids = [r["event_id"] for r in recs]
    assert ids == [f"n-b-{i}" for i in range(100 - len(ids), 100)]  # the newest survive, in order
    on_disk = sum(p.stat().st_size for p in (tmp_path / "s").glob("seg-*.jsonl"))
    assert on_disk < 20 * 200  # file space is bounded too


def test_spool_cursor_survives_restart_and_never_resends_committed(tmp_path):
    sp = Spool(tmp_path / "s", max_records=100, seg_records=7)
    for i in range(30):
        sp.append(line(i))
    recs, upto = sp.peek(12)
    assert [r["event_id"] for r in recs] == [f"n-b-{i}" for i in range(12)]
    sp.commit(upto)
    sp.close()
    sp2 = Spool(tmp_path / "s", max_records=100, seg_records=7)
    assert sp2.backlog == 18 and sp2.max_sequence == 29
    assert sp2.peek(1)[0][0]["event_id"] == "n-b-12"
    sp2.append(line(30))
    assert sp2.backlog == 19


def test_spool_recovers_from_a_torn_last_line(tmp_path):
    sp = Spool(tmp_path / "s", max_records=100, seg_records=50)
    for i in range(5):
        sp.append(line(i))
    sp.close()
    seg = next((tmp_path / "s").glob("seg-*.jsonl"))
    with open(seg, "ab") as f:
        f.write(b'{"event_id":"n-b-5","phase":"tr')  # process killed mid-append
    sp2 = Spool(tmp_path / "s", max_records=100, seg_records=50)
    assert sp2.backlog == 5
    sp2.append(line(5))
    assert [r["event_id"] for r in sp2.peek(10)[0]] == [f"n-b-{i}" for i in range(6)]


def test_shipper_catches_up_idempotently_after_a_crash_between_post_and_commit(tmp_path):
    sink = FakeSink()
    try:
        sp = Spool(tmp_path / "s", max_records=1000, seg_records=10)
        for i in range(40):
            sp.append(line(i))
        sh = Shipper(sp, sink.url, {"node_id": "n"}, batch=15, interval=0.01, timeout=1.0)
        recs, _ = sp.peek(15)
        assert sh.post(recs) == 200  # delivered, but the node died before sp.commit()
        sp.close()
        sp2 = Spool(tmp_path / "s", max_records=1000, seg_records=10)
        sh2 = Shipper(sp2, sink.url, {"node_id": "n"}, batch=15, interval=0.01, timeout=1.0)
        while sh2.ship_once():
            pass
        assert sp2.backlog == 0
        assert sink.received == 55 and len(sink.events) == 40  # 15 re-sent, deduped by event_id
    finally:
        sink.close()


def test_shipper_survives_outage_with_backoff_and_loses_nothing(tmp_path):
    sink = FakeSink()
    sink.mode = "down"
    sp = Spool(tmp_path / "s", max_records=1000, seg_records=10)
    sh = Shipper(sp, sink.url, {"node_id": "n"}, batch=10, interval=0.01, timeout=1.0)
    sh.start()
    try:
        for i in range(25):
            sp.append(line(i))
        assert wait_until(lambda: sh.stats["batches_failed"] >= 2)
        assert sink.events == {} and sp.backlog == 25
        sink.mode = "ok"
        assert wait_until(lambda: len(sink.events) == 25, timeout=15)
        assert sp.backlog == 0 and sp.dropped == 0
    finally:
        sh.stop()
        sink.close()


# --- node-level: canonical records, outage, bounded drops ------------------------------------
def _run_episode(rt, ticks=45, episode=0, seed=3):
    c = Client(rt.control_url)
    n = MiniCoordinator({rt.cfg.node_id: c}).run_episode(episode, seed, ticks)
    st, out = c.control("episode_end", wait=True)
    assert st == 200
    return n


def test_node_ships_canonical_records_with_real_time_and_run_metadata(tmp_path):
    sink = FakeSink()
    cfg = make_cfg(tmp_path, node_ids=("node-01",), telemetry_url=sink.url, update_every=10, seed=5)
    t0 = datetime.now(UTC)
    rt = Runtime(cfg).start()
    try:
        _run_episode(rt)
        assert wait_until(lambda: rt.node.spool.backlog == 0 and len(sink.events) > 5)
        t1 = datetime.now(UTC)
        kinds = set()
        ticks = []
        for eid, r in sink.events.items():
            rec = r["record"]
            assert r["event_id"] == eid == rec["event_id"]
            assert eid.startswith(f"node-01-{rt.node.boot_id}-")
            assert rec["source_node_id"] == "node-01" and rec["run_id"] in ("run-t", "run-none")
            when = datetime.fromisoformat(rec["emitted_at_utc"].replace("Z", "+00:00"))
            assert t0 <= when <= t1  # wall clock, not simulation time
            if rec["kind"] == "learning_event":
                LearningEvent.model_validate(rec)
                ticks.append(rec["sim_tick"])
            else:
                MetricSample.model_validate(rec)
                assert rec["phase"] in ("train", "eval", "partition", "recovery", "other")
            kinds.add(rec["kind"])
        assert kinds == {"learning_event", "metric_sample"}
        assert max(ticks) > 20  # simulation time rides in sim_tick
        meta = sink.metas[0]
        assert meta["node_id"] == "node-01" and meta["seed"] == 5
        assert meta["commit"] == "unknown" and meta["config_hash"] == cfg.config_hash
        assert meta["host"]
        seqs = sorted(r["record"]["sequence"] for r in sink.events.values())
        assert seqs == sorted(set(seqs))  # unique, monotonic per node
    finally:
        rt.stop(False)
        sink.close()


def test_outage_backlog_then_idempotent_catch_up(tmp_path):
    sink = FakeSink()
    sink.mode = "down"
    rt = Runtime(
        make_cfg(tmp_path, node_ids=("node-01",), telemetry_url=sink.url, update_every=5)
    ).start()
    try:
        _run_episode(rt)
        assert wait_until(lambda: rt.shipper.stats["batches_failed"] >= 1)
        st = Client(rt.control_url).status()
        assert st["telemetry_backlog"] > 10 and sink.events == {}
        total = rt.node.spool.next_index
        sink.mode = "ok"
        assert wait_until(lambda: len(sink.events) == total, timeout=15)
        st = Client(rt.control_url).status()
        assert st["telemetry_backlog"] == 0 and st["telemetry_dropped"] == 0
    finally:
        rt.stop(False)
        sink.close()


def test_node_spool_drops_oldest_with_counter_during_long_outage(tmp_path):
    sink = FakeSink()
    sink.mode = "down"
    cfg = make_cfg(
        tmp_path,
        node_ids=("node-01",),
        telemetry_url=sink.url,
        update_every=2,
        spool_max_records=30,
        spool_segment_records=10,
    )
    rt = Runtime(cfg).start()
    try:
        for ep in range(3):
            _run_episode(rt, ticks=45, episode=ep, seed=ep + 1)
        st = Client(rt.control_url).status()
        total = rt.node.spool.next_index
        assert total > 60
        assert st["telemetry_backlog"] <= 30 and st["telemetry_dropped"] > 0
        assert st["telemetry_dropped"] + st["telemetry_backlog"] == total
        sink.mode = "ok"
        assert wait_until(lambda: rt.node.spool.backlog == 0, timeout=15)
        assert len(sink.events) == total - st["telemetry_dropped"]  # exactly the survivors
        newest = max(r["record"]["sequence"] for r in sink.events.values())
        assert newest == rt.node.spool.max_sequence  # the newest events are the ones kept
    finally:
        rt.stop(False)
        sink.close()


def test_spool_files_hold_one_json_object_per_line(tmp_path):
    rt = Runtime(make_cfg(tmp_path, node_ids=("node-01",), update_every=5)).start()
    try:
        _run_episode(rt, ticks=20)
        files = list((tmp_path / "node-01" / "telemetry").glob("seg-*.jsonl"))
        assert files
        for f in files:
            for raw in f.read_text().splitlines():
                assert {"event_id", "phase", "record"} <= set(json.loads(raw))
    finally:
        rt.stop(False)


@pytest.mark.parametrize("bad", [400, 422])
def test_poison_batches_are_skipped_and_counted_not_retried_forever(tmp_path, bad):
    sp = Spool(tmp_path / "s", max_records=100, seg_records=10)
    for i in range(5):
        sp.append(line(i))
    sh = Shipper(sp, "http://127.0.0.1:1/x", {}, batch=5)
    sh.post = lambda recs: bad  # type: ignore[method-assign]
    assert sh.ship_once() is True
    assert sp.backlog == 0 and sh.stats["poison"] == 5

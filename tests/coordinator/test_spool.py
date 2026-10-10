"""Event spool: bounded memory window, bounded disk, indexed paging, restart continuity."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from archipelago_contracts.models import MetricSample
from archipelago_coordinator.spool import EventSpool


def put(sp: EventSpool, run: str, tick: int) -> dict[str, Any]:
    ev = sp.emit(
        run,
        tick,
        None,
        lambda b: MetricSample(**b, metric="coverage", value=0.5, unit="fraction", phase="train"),
    )
    assert ev is not None
    return ev


def test_page_returns_the_requested_window_in_order(tmp_path: Path) -> None:
    sp = EventSpool(tmp_path, "b1", keep=20)
    for t in range(50):
        put(sp, "r", t)
    page = sp.page("r", 44, 3)
    assert page is not None
    assert [e["sequence"] for e in page["events"]] == [45, 46, 47]
    assert page["latest_sequence"] == 50
    assert page["oldest_sequence"] >= 50 - 20 - 2  # memory window is bounded (keep + slack)
    tail, empty = sp.page("r", 48, 100), sp.page("r", 50, 10)
    assert tail is not None and empty is not None
    assert [e["sequence"] for e in tail["events"]] == [49, 50]
    assert empty["events"] == []
    assert sp.page("missing", 0, 10) is None


def test_disk_use_is_bounded_and_sequences_survive_rotation_and_restart(tmp_path: Path) -> None:
    sp = EventSpool(tmp_path, "b1", keep=50, max_file_bytes=4000)
    for t in range(300):
        put(sp, "r", t)
    sp.close()
    files = sorted(tmp_path.glob("r.jsonl*"))
    assert [f.name for f in files] == ["r.jsonl", "r.jsonl.1"]
    # each segment stays near the cap (one record of slack), the live file is never empty
    assert all(0 < f.stat().st_size < 4000 + 2000 for f in files)
    sp2 = EventSpool(tmp_path, "b2", keep=50, max_file_bytes=4000)
    ev = put(sp2, "r", 300)
    assert ev["sequence"] == 301 and ev["event_id"].endswith("-b2-301")
    allp = sp2.page("r", 0, 1000)
    assert allp is not None
    got = [e["sequence"] for e in allp["events"]]
    assert got == sorted(got) and got[-1] == 301

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from archipelago_ops import guard

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
START = {"balance": "0", "pending_charges": "0"}


def inv(
    existing: int = 0, price: str = "20", balance: str = "0", pending: str = "0"
) -> dict[str, Any]:
    return {
        "account": {"balance": balance, "pending_charges": pending},
        "instances": [{"id": str(i), "plan": "p"} for i in range(existing)],
        "plans": {
            "p": {"monthly_cost": price},
            "big": {"monthly_cost": "730"},
            "mid": {"monthly_cost": "200"},
        },
    }


def mkplan(instances: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "instances": instances,
        "region": "ewr",
        "experiment_end": NOW.isoformat(),
        "approved": True,
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
    }
    p.update(over)
    p["plan_hash"] = guard.plan_hash(p)
    return p


def new(n: int, plan: str = "p", hours: float = 0) -> list[dict[str, Any]]:
    return [{"label": f"n{i}", "plan": plan, "duration_hours": hours} for i in range(n)]


def test_instance_limit_boundaries() -> None:
    assert guard.evaluate(inv(4), mkplan(new(1)), START, NOW).passed  # exactly 5
    rep = guard.evaluate(inv(4), mkplan(new(2)), START, NOW)  # 6
    assert rep.violations == ["MAX_INSTANCES: 6 > 5"]
    assert guard.evaluate(inv(3), mkplan(new(1)), START, NOW).passed  # 4


@pytest.mark.parametrize(("price", "ok"), [("199.99", True), ("200", True), ("200.01", False)])
def test_monthly_boundary(price: str, ok: bool) -> None:
    rep = guard.evaluate(inv(1, price=price), mkplan([]), START, NOW)
    assert rep.passed is ok
    if not ok:
        assert rep.violations == ["MAX_MONTHLY_COST: 200.01 > 200 USD"]


@pytest.mark.parametrize(("hours", "ok"), [(291.99, True), (292, True), (292.01, False)])
def test_cumulative_boundary(hours: float, ok: bool) -> None:
    # plan "mid" is 200/month (exactly the monthly ceiling); at 200/730 per hour x1.25 safety,
    # 292 hours burn exactly 100 USD. The monthly ceiling therefore holds while cumulative trips.
    rep = guard.evaluate(inv(), mkplan(new(1, "mid", hours)), START, NOW)
    assert rep.passed is ok
    if ok and hours == 292:
        assert rep.costs["projected_cumulative"] == "100.00"
    if not ok:
        assert rep.violations[0].startswith("MAX_CUMULATIVE_SPEND: 100.00 > 100")


def test_cumulative_includes_recorded_spend_and_existing_burn() -> None:
    rep = guard.evaluate(inv(balance="60", pending="40.01"), mkplan([]), START, NOW)
    assert rep.violations[0].startswith("MAX_CUMULATIVE_SPEND")
    later = NOW - timedelta(hours=10)  # existing 20/mo instance burns until experiment_end
    rep2 = guard.evaluate(inv(1), mkplan([], experiment_end=NOW.isoformat()), START, later)
    assert rep2.costs["existing_burn_to_end"] == "0.34"  # 20/730*10*1.25


def test_prorated_capped_at_monthly_price() -> None:
    rep = guard.evaluate(inv(), mkplan(new(1, "p", 2000)), START, NOW)
    assert rep.costs["new_prorated"] == "20.00"


def test_unknown_plan_fails_closed() -> None:
    rep = guard.evaluate(inv(), mkplan(new(1, "nope")), START, NOW)
    assert rep.violations[0].startswith("UNKNOWN_PLAN_PRICE")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("approved"),
        lambda p: p.update(approved="true"),
        lambda p: p.update(approved=False),
        lambda p: p.pop("plan_hash"),
        lambda p: p.update(plan_hash="0" * 64),
        lambda p: p.pop("expires_at"),
        lambda p: p.update(expires_at=(NOW - timedelta(seconds=1)).isoformat()),
        lambda p: p.update(region="lax"),  # edited after hashing
    ],
)
def test_unapproved_plans_refused(mutate: Any, tmp_path: Path) -> None:
    plan = mkplan(new(1))
    mutate(plan)
    paths = {}
    for name, data in (("i", inv()), ("p", plan), ("s", START)):
        paths[name] = tmp_path / name
        paths[name].write_text(json.dumps(data))
    code, rep, msg = guard.run_guard(paths["i"], paths["p"], paths["s"], tmp_path / "r.json", NOW)
    assert code == guard.EXIT_NOT_APPROVED and rep is None
    assert msg.startswith("REFUSED")
    assert not (tmp_path / "r.json").exists()


def test_run_guard_writes_report_and_exit_codes(tmp_path: Path) -> None:
    files = {}
    for name, data in (("i", inv(4)), ("p", mkplan(new(2))), ("s", START)):
        files[name] = tmp_path / name
        files[name].write_text(json.dumps(data))
    code, _, msg = guard.run_guard(files["i"], files["p"], files["s"], tmp_path / "r.json", NOW)
    assert code == guard.EXIT_VIOLATION and "MAX_INSTANCES: 6 > 5" in msg
    report = json.loads((tmp_path / "r.json").read_text())
    assert report["passed"] is False and "projected_monthly" in report["costs"]
    files["p"].write_text(json.dumps(mkplan(new(1))))
    assert guard.run_guard(files["i"], files["p"], files["s"], None, NOW)[0] == guard.EXIT_OK


def test_short_expensive_plan_still_violates_the_monthly_ceiling() -> None:
    """A 730 USD/month plan used for one hour burns little; its recurring price breaks 200/month."""
    rep = guard.evaluate(inv(), mkplan(new(1, "big", 1)), START, NOW)
    assert not rep.passed
    assert rep.violations == ["MAX_MONTHLY_COST: 730.00 > 200 USD"]
    assert rep.costs["new_monthly_full"] == "730.00"
    assert rep.costs["projected_monthly"] == "730.00"
    assert rep.costs["new_prorated"] != rep.costs["new_monthly_full"]

# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""The demo and smoke plans validate against the coordinator's own Plan model and the A13 horizon rules."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "services/coordinator"), str(ROOT / "infra/demo")]

import run_demo  # noqa: E402
from archipelago_contracts.models import RunConfig  # noqa: E402
from archipelago_coordinator.models import CreateRun, Plan, expand_episodes  # noqa: E402

NODES = {f"node-0{i}" for i in range(1, 5)}


def plan(name):
    return Plan.model_validate(json.loads((ROOT / f"infra/demo/plans/{name}.json").read_text()))


@pytest.mark.parametrize("name", ["smoke", "demo"])
def test_plan_loads_through_the_coordinator_model(name):
    p = plan(name)
    assert set(p.node_urls) == NODES
    assert all(u == f"http://{n}:8080" for n, u in p.node_urls.items())
    assert p.deadline_ms == 500
    for w in p.fault_schedule:
        assert w.start_tick < w.end_tick
        assert {x for pair in w.cut_links for x in pair} <= NODES


def test_smoke_plan_is_short_with_one_episode_of_each_kind_and_a_mid_run_cut():
    p = plan("smoke")
    assert [e.kind for e in expand_episodes(p)] == ["train", "validation", "test"]
    (w,) = p.fault_schedule
    assert (w.start_tick, w.end_tick) == (40, 90)
    assert w.end_tick < run_demo.PROFILES["smoke"]["max_ticks"] == 150


def test_demo_plan_is_the_900_tick_cut_300_rejoin_600_scenario():
    p = plan("demo")
    (w,) = p.fault_schedule
    assert (w.start_tick, w.end_tick) == (300, 600)
    assert run_demo.PROFILES["demo"]["max_ticks"] == 900
    kinds = [e.kind for e in expand_episodes(p)]
    assert kinds.count("train") == 6 and kinds.count("validation") == 3 and kinds.count("test") == 3
    # frozen evaluation sits between training blocks so train and eval curves can be compared
    assert kinds.index("validation") < len(kinds) - kinds[::-1].index("train")


@pytest.mark.parametrize("name", ["smoke", "demo"])
def test_episode_seeds_are_unique_and_disjoint_from_node_private_gate_seeds(name):
    seeds = [(e.kind, e.seed) for e in expand_episodes(plan(name))]
    assert len({s for _, s in seeds}) == len(seeds)
    gate = {9001, 9002, 9003}  # node default VALIDATION_SEEDS (packages/node/runtime README)
    assert not gate & {s for _, s in seeds}
    test_seeds = {s for k, s in seeds if k == "test"}
    assert not test_seeds & {s for k, s in seeds if k != "test"}


@pytest.mark.parametrize("name", ["smoke", "demo"])
def test_run_config_from_the_driver_validates_with_the_plan(name):
    p = json.loads((ROOT / f"infra/demo/plans/{name}.json").read_text())
    cfg = run_demo.build_run_config(name, p, run_demo.new_run_id(name))
    body = CreateRun.model_validate({"run_config": cfg, "plan_name": name})
    RunConfig.model_validate(cfg)
    assert len({(n.start_pose.x, n.start_pose.y) for n in body.run_config.nodes}) == 4
    assert body.run_config.budgets.max_ticks == run_demo.PROFILES[name]["max_ticks"]
    assert len(body.run_config.run_id) <= 64
    assert (
        max(w.end_tick for w in body.run_config.fault_schedule) < body.run_config.budgets.max_ticks
    )


def test_battery_scale_for_the_demo_horizon_is_at_least_four():
    """A13: the 900-tick demo needs battery_scale >= 4 carried by the plan itself."""
    for name in ("smoke", "demo"):
        data = json.loads((ROOT / f"infra/demo/plans/{name}.json").read_text())
        assert data.get("battery_scale", 0) >= 4

from pathlib import Path

from archipelago_contracts import parse_json
from archipelago_contracts.adapter import FixtureAdapter, SimulatorAdapter
from archipelago_contracts.models import Observation, RunConfig, WorldSnapshot

G = Path(__file__).resolve().parents[2] / "packages/contracts/fixtures/good"


def _load() -> tuple[RunConfig, FixtureAdapter]:
    cfg = parse_json((G / "run_config.json").read_text())
    obs = parse_json((G / "observation.json").read_text())
    snap = parse_json((G / "world_snapshot.json").read_text())
    assert isinstance(cfg, RunConfig)
    assert isinstance(obs, Observation) and isinstance(snap, WorldSnapshot)
    return cfg, FixtureAdapter(obs, snap)


def test_fixture_adapter_gives_each_node_only_its_own_observation() -> None:
    cfg, adapter = _load()
    proto: SimulatorAdapter = adapter  # structural conformance is type-checked by mypy
    first = proto.reset(cfg)
    assert sorted(first) == ["node-01", "node-02"]
    assert all(o.source_node_id == n for n, o in first.items())
    result = proto.step({})  # missing actions must not remove nodes
    assert sorted(result.observations) == ["node-01", "node-02"]
    assert adapter.steps == 1


def test_reset_restarts_the_step_counter_deterministically() -> None:
    cfg, adapter = _load()
    adapter.reset(cfg)
    adapter.step({})
    adapter.reset(cfg)
    assert adapter.steps == 0

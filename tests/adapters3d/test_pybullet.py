from pathlib import Path

import pytest
from archipelago_contracts import parse_json
from archipelago_contracts.models import Action
from archipelago_learning.dqn import Learner
from archipelago_learning.peer import PeerError, decode, encode

G = Path(__file__).resolve().parents[2] / "packages/contracts/fixtures/good"


def test_3d_model_rejected_by_2d_learner_and_back() -> None:
    l3 = Learner("a", 8, 5, encoder="drone3d-v0")
    l2 = Learner("b", 8, 5)
    with pytest.raises(PeerError, match="incompatible encoder"):
        decode(encode(l3), l2)
    with pytest.raises(PeerError, match="incompatible encoder"):
        decode(encode(l2), l3)


def test_headless_flight_and_collision_metric() -> None:
    pytest.importorskip("pybullet")
    from archipelago_pybullet import PyBullet3DAdapter

    cfg = parse_json((G / "run_config.json").read_text())
    base = parse_json((G / "action.json").read_text()).model_dump()

    def act(n, c):
        return Action(**{**base, "source_node_id": n, "command": c})

    ad = PyBullet3DAdapter()
    assert ad.capabilities().dimensionality == "3d"
    ad.reset(cfg)
    start = {n.node_id: n.start_pose for n in cfg.nodes}
    for _ in range(10):
        res = ad.step({"node-01": act("node-01", "east"), "node-02": act("node-02", "stay")})
    p3 = ad.poses3d()
    assert all(0.5 < z < 1.5 for _, _, z in p3.values())  # holds hover altitude
    assert p3["node-01"][0] > start["node-01"].x + 0.5  # actually moved
    assert ad.snapshot().poses.keys() == p3.keys() and len(res.observations) == 2
    assert ad.collisions == 0

    # a drone parked on top of another must register a physics contact
    ad.reset(
        cfg.model_copy(
            update={
                "nodes": [
                    cfg.nodes[0],
                    cfg.nodes[1].model_copy(update={"start_pose": cfg.nodes[0].start_pose}),
                ]
            }
        )
    )
    ad.step({})
    assert ad.collisions > 0
    ad.close()

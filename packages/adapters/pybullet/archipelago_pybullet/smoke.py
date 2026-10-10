"""Headless flight smoke: python -m archipelago_pybullet.smoke > evidence/smoke.json"""

import json
from pathlib import Path

import pybullet
from archipelago_contracts import parse_json
from archipelago_contracts.models import Action

from archipelago_pybullet import PyBullet3DAdapter

G = Path(__file__).resolve().parents[3] / "contracts/fixtures/good"


def main() -> None:
    cfg = parse_json((G / "run_config.json").read_text())
    base = parse_json((G / "action.json").read_text()).model_dump()
    ad = PyBullet3DAdapter()
    ad.reset(cfg)
    for _ in range(10):
        ad.step({n: Action(**{**base, "source_node_id": n, "command": "east"}) for n in ad.bodies})
    out = {
        "pybullet": pybullet.getAPIVersion(),
        "poses3d": ad.poses3d(),
        "drone_drone_collisions": ad.collisions,
    }
    ad.close()
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()

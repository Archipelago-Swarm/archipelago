import sys
from pathlib import Path

import pytest

root = Path(__file__).resolve().parents[2]
for p in (
    "services/coordinator",
    "packages/sim",
    "packages/adapters/sim2d",
    "packages/contracts/src",
):
    sys.path.insert(0, str(root / p))

from harness import Live, make_nodes  # noqa: E402


@pytest.fixture
def live(tmp_path):
    made: list[Live] = []

    def boot(**settings):
        lv = Live(tmp_path / "coordinator", **settings)
        made.append(lv)
        return lv

    yield boot
    for lv in made:
        lv.close()


@pytest.fixture
def nodes():
    made = []

    def build(n=4, **per_node):
        ns = make_nodes(n, **per_node)
        made.extend(ns.values())
        return ns

    yield build
    for f in made:
        f.stop()

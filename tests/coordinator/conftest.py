import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

root = Path(__file__).resolve().parents[2]
for p in (
    "services/coordinator",
    "packages/sim",
    "packages/adapters/sim2d",
    "packages/contracts/src",
):
    sys.path.insert(0, str(root / p))

from coord_harness import FakeNode, Live, make_nodes  # noqa: E402


@pytest.fixture
def live(tmp_path: Path) -> Iterator[Callable[..., Live]]:
    made: list[Live] = []

    def boot(**settings: Any) -> Live:
        lv = Live(tmp_path / "coordinator", **settings)
        made.append(lv)
        return lv

    yield boot
    for lv in made:
        lv.close()


@pytest.fixture
def nodes() -> Iterator[Callable[..., dict[str, FakeNode]]]:
    made: list[FakeNode] = []

    def build(n: int = 4, **per_node: Any) -> dict[str, FakeNode]:
        ns = make_nodes(n, **per_node)
        made.extend(ns.values())
        return ns

    yield build
    for f in made:
        f.stop()

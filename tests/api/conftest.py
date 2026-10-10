import sys
from pathlib import Path

# sim2d and sim are plain source dirs (no pyproject); expose them so real tests run.
for d in ("adapters/sim2d", "sim"):
    p = Path(__file__).parents[2] / "packages" / d
    if p.is_dir() and str(p) not in sys.path:
        sys.path.append(str(p))

# archipelago_storage is a plain source dir (not a workspace member yet).
_storage = str(Path(__file__).parents[2] / "packages" / "storage")
if _storage not in sys.path:
    sys.path.append(_storage)

# Live-mode tests drive the real coordinator in-process with the coordinator test harness.
_root = Path(__file__).parents[2]
for _d in ("services/coordinator", "tests/coordinator", "tests/storage", "packages/contracts/src"):
    _p = str(_root / _d)
    if _p not in sys.path:
        sys.path.append(_p)

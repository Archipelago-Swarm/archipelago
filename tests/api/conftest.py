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

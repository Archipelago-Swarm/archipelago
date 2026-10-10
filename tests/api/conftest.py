import sys
from pathlib import Path

# sim2d and sim are plain source dirs (no pyproject); expose them so real tests run.
for d in ("adapters/sim2d", "sim"):
    p = Path(__file__).parents[2] / "packages" / d
    if p.is_dir() and str(p) not in sys.path:
        sys.path.append(str(p))

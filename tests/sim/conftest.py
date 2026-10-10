import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
for p in ("packages/sim", "packages/adapters/sim2d", "packages/contracts/src"):
    sys.path.insert(0, str(root / p))

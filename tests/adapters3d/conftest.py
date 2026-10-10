import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
for p in ("packages/adapters/pybullet", "packages/contracts/src", "packages/learning"):
    sys.path.insert(0, str(root / p))

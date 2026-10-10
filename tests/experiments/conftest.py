import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
for p in ("packages/learning", "packages/sim", "experiments"):
    sys.path.insert(0, str(root / p))

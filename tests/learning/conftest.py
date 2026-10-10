import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
for p in ("packages/learning", "packages/sim"):
    sys.path.insert(0, str(root / p))
for p in ("packages/contracts/src", "packages/transport", "packages/node/learner"):
    sys.path.insert(0, str(root / p))

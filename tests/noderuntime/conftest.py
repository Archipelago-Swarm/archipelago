import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
for p in (
    "packages/node/runtime",
    "packages/node/peer",
    "packages/node/learner",
    "packages/transport",
    "packages/contracts/src",
    "packages/learning",
    "packages/sim",
):
    sys.path.insert(0, str(root / p))

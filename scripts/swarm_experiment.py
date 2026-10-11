"""Run the swarm learning experiment/inspector: python scripts/swarm_experiment.py [args]"""

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for p in ("packages/swarm", "packages/learning", "packages/sim"):
    sys.path.insert(0, str(root / p))

from archipelago_swarm.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["experiment"]))

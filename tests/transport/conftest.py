import sys
from pathlib import Path

# shortcut: no installable transport/peer packages yet; add workspace members to drop this
for p in ("transport", "node/peer"):
    sys.path.insert(0, str(Path(__file__).parents[2] / "packages" / p))

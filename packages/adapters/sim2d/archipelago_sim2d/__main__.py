"""CLI: python -m archipelago_sim2d --seed 1 --ticks 900 --out DIR (explorer smoke run)."""

import argparse
from pathlib import Path

from .smoke import run_explorer


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--ticks", type=int, default=900)
    p.add_argument("--nodes", type=int, default=4)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    ad = run_explorer(a.seed, a.ticks, a.nodes)
    print(ad.write_replay(a.out), "coverage", round(ad.snapshot().coverage, 3))


if __name__ == "__main__":
    main()

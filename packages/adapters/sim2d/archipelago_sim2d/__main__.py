"""CLI: python -m archipelago_sim2d --seed 1 --ticks 900 --out DIR (explorer smoke run)."""

import argparse
from pathlib import Path

from .smoke import run_explorer


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--ticks", type=int, default=900)
    p.add_argument("--nodes", type=int, default=4)
    # Smoke defaults: no targets and a large battery so the run lasts the full --ticks.
    p.add_argument("--targets", type=int, default=0)
    p.add_argument("--battery-scale", type=float, default=10.0)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    ad = run_explorer(a.seed, a.ticks, a.nodes, n_targets=a.targets, battery_scale=a.battery_scale)
    print(ad.write_replay(a.out), "coverage", round(ad.snapshot().coverage, 3))


if __name__ == "__main__":
    main()

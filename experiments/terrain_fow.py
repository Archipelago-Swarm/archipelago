# ruff: noqa: E501  (wide report tables)
"""Matched comparison: uniform vs terrain-aware FOW, plus visibility learning and sharing.

    uv run --frozen python experiments/terrain_fow.py [--seeds 5] [--ticks 600]

Scenario: 4 drones fly the rule-based explorer (same actions in both arms) over the same seeded
layout, obstacles and targets. Only the terrain differs. The learned estimate is scored AFTER the
fact against the simulator's true detection probability; the estimator never sees that value.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from pathlib import Path

for p in ("packages/sim", "packages/learning"):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / p))

from archipelago_learning.visibility import VisibilityModel  # noqa: E402
from archipelago_sim.env import explorer_policy  # noqa: E402
from archipelago_sim.flight import FlightWorld  # noqa: E402

KW = {"size": 32, "n_agents": 4, "n_targets": 40, "sense_radius": 2, "obstacle_density": 0.0}


def run(seed: int, ticks: int, terrain: bool, share: bool):
    w = FlightWorld(**KW, max_ticks=ticks, terrain_seed=seed if terrain else None)
    obs = w.reset(seed=seed)
    rngs = {a: random.Random(seed * 31 + i) for i, a in enumerate(w.possible_agents)}
    visits = {a: {} for a in w.possible_agents}
    models = {a: VisibilityModel(a) for a in w.possible_agents}
    first: dict = {}
    brier: list[
        tuple[int, float, float]
    ] = []  # (tick, squared error of the prediction made BEFORE seeing the outcome)
    while w.agents:
        acts = {a: explorer_policy(obs[a], visits[a], rngs[a]) for a in w.agents}
        obs, *_ = w.step(acts)
        for a, o in obs.items():
            for (b, alt, dist, _), true_p in zip(
                o.get("sense_log", []), w.eval_p[a], strict=True
            ):  # truth used for scoring only
                brier.append(
                    (w.tick, abs(models[a].estimate(b, alt, dist) - true_p), abs(0.5 - true_p))
                )
            models[a].update(o.get("sense_log", []))
        for c in w.found_targets:
            first.setdefault(c, w.tick)
        if share and w.tick % 25 == 0:
            for a in models:
                for b in models:
                    if a != b:
                        models[b].receive(models[a].to_wire(), a)
    return w, models, first, brier


def half(brier):
    """Mean prequential Brier error over the first and second half of the attempts."""
    xs = [e for _, e, _ in brier]
    h = len(xs) // 2
    return (statistics.mean(xs[:h]), statistics.mean(xs[h:])) if h else (float("nan"),) * 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--ticks", type=int, default=600)
    a = ap.parse_args()
    print("A. matched worlds (same layout/targets/actions; only terrain differs)")
    print(
        f"{'seed':>4} {'arm':<8} {'cells_known':>11} {'targets':>7} {'first_det_tick':>14} {'ticks_run':>9}"
    )
    rows: dict = {}
    for s in range(a.seeds):
        for arm, terr in (("uniform", False), ("terrain", True)):
            w, _, first, _ = run(s, a.ticks, terr, share=False)
            known = len(set().union(*(d.known.keys() for d in w.drones.values())))
            ft = statistics.mean(first.values()) if first else float("nan")
            rows.setdefault(arm, []).append((known, len(w.found_targets), ft))
            print(f"{s:>4} {arm:<8} {known:>11} {len(w.found_targets):>7} {ft:>14.1f} {w.tick:>9}")
    for arm, r in rows.items():
        print(
            f"  {arm:<8} mean cells_known {statistics.mean(x[0] for x in r):.0f}  targets {statistics.mean(x[1] for x in r):.1f}  mean first-detection tick {statistics.mean(x[2] for x in r):.1f}"
        )
    print(
        "\nB. learning (terrain arm): prequential |estimate - true p| (MAE, scored before each update), 1st half -> 2nd half of attempts"
    )
    print(
        f"{'seed':>4} {'share':<5} {'attempts':>8} {'1st half':>9} {'2nd half':>9} {'always .5':>9}"
    )
    for s in range(a.seeds):
        for share in (False, True):
            _, models, _, brier = run(s, a.ticks, True, share)
            ys = brier
            h1, h2 = half(brier)
            prior = statistics.mean(b for _, _, b in brier)
            print(f"{s:>4} {str(share):<5} {len(ys):>8} {h1:>9.3f} {h2:>9.3f} {prior:>9.3f}")
    print(
        "\nC. learned detection estimate by biome, near, mid altitude (seed 0, node-0, no sharing) vs simulator truth"
    )
    w, models, _, _ = run(0, a.ticks, True, share=False)
    m = next(iter(models.values()))
    for b, name in enumerate(("grass", "forest", "jungle")):
        veg = statistics.mean(
            w.terrain.veg[x][y]
            for x in range(w.size)
            for y in range(w.size)
            if w.terrain.biome[x][y] == b
        )
        true = (1 - 0.9 * veg) * (1 - 0.35 / (w.radius + 1))
        print(
            f"  {name:<7} learned {m.estimate(b, 80.0, 1):.2f}  (n={m._pooled(f'{b}|1|1')[1]})  sim mean {true:.2f}"
        )


if __name__ == "__main__":
    main()

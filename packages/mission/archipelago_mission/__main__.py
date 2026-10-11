"""python -m archipelago_mission --seed 1042 [--out FILE] [--no-skills] [--compare]"""

import argparse
import json
import sys

from .sim import MissionConfig, run_mission


def _round(o):
    if isinstance(o, float):
        return round(o, 3)
    if isinstance(o, dict):
        return {k: _round(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_round(v) for v in o]
    return o


def main() -> None:
    ap = argparse.ArgumentParser(prog="archipelago_mission")
    ap.add_argument("--seed", type=int, default=1042)
    ap.add_argument("--out", help="write the full replay JSON here")
    ap.add_argument("--no-skills", action="store_true", help="disable P2P skill sharing (baseline)")
    ap.add_argument("--compare", action="store_true", help="print skills-on vs skills-off stats")
    a = ap.parse_args()
    run = run_mission(MissionConfig(seed=a.seed, skills_enabled=not a.no_skills))
    if a.out:
        with open(a.out, "w") as f:
            json.dump(_round(run), f, separators=(",", ":"))
    out = {"seed": a.seed, "mission": run["frames"][-1]["mission"], "stats": run["stats"]}
    if a.compare:
        base = run_mission(MissionConfig(seed=a.seed, skills_enabled=False))
        out = {"with_skills": out, "baseline_no_skills": {"mission": base["frames"][-1]["mission"], "stats": base["stats"]}}
    json.dump(out, sys.stdout, indent=2)
    print()


main()

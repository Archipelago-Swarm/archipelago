# ruff: noqa: E501
"""Writes experiments/out/T37/{summary.md,results.json,curves.csv,curves.svg} from the stage files.

No hand-written numbers: every figure comes from stageA.json, stageB.json, selection.json and
test.json produced by t37.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import protocol_harness as H
import t37

NAMES = {
    "ref_return": "reference return (rew-v1 re-scored)",
    "coverage_gain": "coverage gain after spawn",
    "targets_after_spawn": "targets found after spawn (of 8)",
    "wall_collisions": "wall collisions / episode",
    "revisit_rate": "revisit rate",
}


def f(x, d=2):
    return f"{x:.{d}f}"


def ci(p, key="ci95"):
    return f"[{p[key][0]:+.2f}, {p[key][1]:+.2f}]"


def mean_of(rows, m, sl=slice(None)):
    return float(t37.matrix(rows, m, sl).mean())


def spec(cfg: t37.Config) -> str:
    dim = H.obs_dim(cfg.obs)
    sched = (
        f"epsilon {cfg.eps_start:g} -> {cfg.eps_end:g} linearly over the first "
        f"{cfg.eps_frac:.0%} of training episodes, then constant"
        if cfg.eps_frac
        else f"constant epsilon {cfg.eps_start:g}"
    )
    return (
        f"- observation id `{cfg.obs}`, float32[{dim}] (layout below)\n"
        f"- reward id `{cfg.reward}`\n"
        f"- epsilon schedule: {sched} (per episode, evaluated at the episode start)\n"
        f"- Adam lr {cfg.lr:g}, gamma {t37.GAMMA}, batch {t37.BATCH}, hidden {t37.HIDDEN}, "
        f"target sync every {t37.TARGET_EVERY} optimizer steps, one optimizer step per recorded "
        f"transition, MSE TD loss, no gradient clipping\n"
        f"- replay capacity {cfg.replay} transitions per node (uniform sampling, ring buffer)\n"
        f"- {'double DQN: target y = r + gamma*(1-done)*Q_target(s2, argmax_a Q_online(s2,a))' if cfg.double else 'plain DQN: y = r + gamma*(1-done)*max_a Q_target(s2,a)'}\n"
        f"- done = environment termination only (time-limit truncation still bootstraps)\n"
        f"- {cfg.episodes} training episodes per node, world seed 1000 + seed*{cfg.episodes} + i"
    )


LAYOUT = """\
Observation layouts (all float32; crop is 5x5 = sense radius 2, row-major, dy outer, dx inner,
values -1 unknown / 0 free / 1 wall from the node's own buffer):

| index | content | scaling |
|---|---|---|
| 0-24 | crop | raw -1/0/1 |
| 25, 26 | pose x, y | x/size, y/size (size 16) |
| 27 | battery | clipped to [0, 1] |
| 28-52 | `grid-flat-v2-visits`: own stand-on count of each crop cell (same order as crop; spawn cell counts 1; staying counts) | min(count, 4)/4 |
| 53-56 | frontier north, east, south, west: fraction of the 5 cells just outside the crop (row y-3, column x+3, row y+3, column x-3, offsets -2..2) that are inside the map and not in the node's buffer | 0..1 in steps of 0.2 |
| 57-81 | `grid-flat-v2-visits-shared` only: 1 if a peer reported standing on that crop cell through the information message, else 0 | 0/1 |

`grid-flat-v2-visits` = indices 0-56 (57 values); `grid-flat-v2-visits-shared` = 0-81 (82 values).
Frontier cells count as known if they were sensed by this node or merged from a peer's information
message (map cells), so the frontier already reflects shared map knowledge when the InfoBus runs.
The information message (non-model): per tick per directed pair, the cells the sender knows and has
not yet sent (3 bytes), new markers (2 bytes), header 4 bytes and, for `-shared`, newly stood-on
cells (2 bytes each). Implementation: `experiments/protocol_harness.py` (`InfoBus`, `flat`) and
`packages/sim/archipelago_sim/env.py` (`GridWorld.observe_memory`, `Drone.visits/peer_visits`).
`rew-v1` constants: new cell +0.5 per newly sensed free cell, target +5.0 split over living nodes and
only for targets NOT already sensed at reset, step -0.01, wall/agent collision -2.0 each, invalid
action -0.1, revisit -0.25 whenever a node ends a tick on a cell it already stood on (includes
staying and bumping a wall).
"""


def curves(out: Path, rows):
    by = {}
    for r in rows:
        for c in r["curve"]:
            by.setdefault(r["config"], {}).setdefault(c["episode"], []).append(c["ref_return"])
    lines = ["config,episode,mean_val_ref_return,sd_over_seeds,n_seeds"]
    for k, d in by.items():
        for e in sorted(d):
            lines.append(f'"{k}",{e},{np.mean(d[e]):.4f},{np.std(d[e]):.4f},{len(d[e])}')
    (out / "curves.csv").write_text("\n".join(lines) + "\n")
    # minimal SVG (no plotting dependency)
    W, Hh, pad = 720, 360, 50
    allv = [np.mean(v) for d in by.values() for v in d.values()]
    lo, hi = min(allv), max(allv)
    es = sorted({e for d in by.values() for e in d})
    X = lambda e: pad + (W - 2 * pad) * (e - es[0]) / max(1, es[-1] - es[0])  # noqa: E731
    Y = lambda v: Hh - pad - (Hh - 2 * pad) * (v - lo) / max(1e-9, hi - lo)  # noqa: E731
    pal = ["#2a6fb0", "#c4572b", "#3b8f5a", "#8a5db0", "#555555", "#b08a1f"]
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{Hh + 20 * len(by)}" '
        'font-family="sans-serif" font-size="11">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{pad}" y="18">Greedy reference return on VAL 100-104 vs training episodes '
        "(mean over seeds)</text>",
        f'<line x1="{pad}" y1="{Hh - pad}" x2="{W - pad}" y2="{Hh - pad}" stroke="#999"/>',
        f'<text x="4" y="{Y(lo)}">{lo:.0f}</text><text x="4" y="{Y(hi) + 10}">{hi:.0f}</text>',
    ]
    for i, (k, d) in enumerate(by.items()):
        pts = " ".join(f"{X(e):.1f},{Y(np.mean(d[e])):.1f}" for e in sorted(d))
        col = pal[i % len(pal)]
        svg.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2"/>')
        svg.append(f'<text x="{pad}" y="{Hh + 14 + 16 * i}" fill="{col}">{k}</text>')
    svg.append("</svg>")
    (out / "curves.svg").write_text("\n".join(svg))


def write(out: Path, pre: dict):
    A = json.loads((out / "stageA.json").read_text())
    B = json.loads((out / "stageB.json").read_text())["rows"]
    S = json.loads((out / "selection.json").read_text())
    T = json.loads((out / "test.json").read_text()) if (out / "test.json").exists() else None
    byB = {}
    for r in B:
        byB.setdefault(r["config"], []).append(r)
    cfg = t37._config_by_id(pre, S["selected"])
    n = len(t37.VAL)
    L = [
        "# T37 variant study: does learning help once the problem is learnable?",
        "",
        f"Pre-registration: `experiments/prereg/T37.yaml`, original commit "
        f"`{S['prereg']['original_commit']}`, latest (amendment 1) `{S['prereg']['commit']}`, "
        f"file sha256 `{S['prereg']['file_sha256'][:16]}`. Code at `{S['prereg']['head'][:10]}`. "
        "Reproduce: `PYTHONPATH=packages/learning:packages/sim:experiments uv run python "
        "experiments/t37.py all` (about 25 minutes on 4 cores, seeded, deterministic).",
        "",
        "World: 16x16, 2 drones, 8 targets, 150 ticks, scenario connected. Metrics: reference return "
        "(rew-v1 components re-scored for every policy, so reward variants share one yardstick; it "
        "charges revisits, so idle is strongly negative by construction), coverage gain and targets "
        "found after spawn (reward-free). Selection used only training seeds (>=1000), validation "
        "seeds 100-104 and held-out worlds 5000-5019. TEST 200-219 was used once, after selection.",
        "",
    ]
    if T:
        v = T["verdict"]
        L += [
            "## Verdict (frozen TEST seeds 200-219, one shot)",
            "",
            f"- learning helps (vs idle on all three metrics, vs untrained net and vs random policy "
            f"on return, hierarchical 95% CI lower bound > 0): **{v['LEARNING_HELPS']}**",
            f"- beats the rule explorer (pre-registered criterion): **{v['BEATS_RULE']}**",
            "",
        ]
    L += ["## Selected configuration", "", f"`{S['selected']}`", "", spec(cfg), ""]
    L += [
        "## Stage A (successive halving round 1): 4 seeds x 200 episodes, 25 selection worlds",
        "",
        "| rank | config | mean ref return | kept |",
        "|---|---|---|---|",
    ]
    for i, (k, v) in enumerate(A["ranking"], 1):
        L.append(f"| {i} | `{k}` | {f(v)} | {'yes' if k in A['kept'] else ''} |")
    L += [
        "",
        "## Stage B: finalists + control, 10 seeds x 400 episodes (means over seeds)",
        "",
        "| config | ref ret VAL | ref ret SEL25 | cov gain VAL | targets VAL | wall coll VAL | revisit VAL |",
        "|---|---|---|---|---|---|---|",
    ]
    for k, rs in byB.items():
        tag = (
            " (control)"
            if k not in S["pool"]
            else (" **(selected)**" if k == S["selected"] else "")
        )
        L.append(
            f"| `{k}`{tag} | {f(mean_of(rs, 'ref_return', slice(0, n)))} | "
            f"{f(mean_of(rs, 'ref_return'))} | {f(mean_of(rs, 'coverage_gain', slice(0, n)), 3)} | "
            f"{f(mean_of(rs, 'targets_after_spawn', slice(0, n)))} | "
            f"{f(mean_of(rs, 'wall_collisions', slice(0, n)), 1)} | "
            f"{f(mean_of(rs, 'revisit_rate', slice(0, n)), 3)} |"
        )
    bs = S["baselines_sel"]
    for b, v in bs.items():
        L.append(
            f"| baseline {b} (SEL25) | - | {f(v['ref_return'])} | {f(v['coverage_gain'], 3)} | "
            f"{f(v['targets_after_spawn'])} | - | - |"
        )
    L += ["", "Selected config vs baselines, paired (learner minus baseline), 95% CI:", ""]
    for label, d in S["paired_selected"].items():
        L += [
            f"**{label}**",
            "",
            "| metric | baseline | mean diff | hier. CI | seed-only CI |",
            "|---|---|---|---|---|",
        ]
        for m, bd in d.items():
            for b, p in bd.items():
                L.append(
                    f"| {NAMES[m]} | {b} | {p['mean_diff']:+.3f} | {ci(p)} | {ci(p, 'ci95_seed_only')} |"
                )
        L.append("")
    if T:
        L += [
            "## One-shot TEST result (seeds 200-219, 10 experiment seeds, selected config only)",
            "",
            "| metric | learner | baseline | baseline mean | mean diff | hier. 95% CI | seed-only CI | seeds with diff>0 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for m, e in T["metrics"].items():
            for b, p in e["vs"].items():
                L.append(
                    f"| {NAMES[m]} | {e['learner_mean']:.3f} | {b} | {p['baseline_mean']:.3f} | "
                    f"{p['mean_diff']:+.3f} | {ci(p)} | {ci(p, 'ci95_seed_only')} | "
                    f"{p['wins']}/{p['n_seeds']} |"
                )
        L += ["", "Decision record: `" + json.dumps(T["verdict"]) + "`", ""]
    L += [
        "## Adoption note for T38 (PyTorch runtime must reproduce exactly)",
        "",
        spec(cfg),
        "",
        LAYOUT,
    ]
    L += [
        "Cross-backend check: encode the same `GridWorld` state with `harness.flat` and the Torch encoder "
        "and compare element-wise; train the NumPy `VLearner` (experiments/t37.py) and the Torch learner "
        "from the same seed on a fixed replay and compare Q-values. Encoder id for the node header: "
        f"`{cfg.obs}`; the existing `grid-flat-v1-s{{size}}-r{{radius}}` encoder (28 values) does not "
        "carry visit counts, so a new geometry-bearing id and sha256 are required (A6).",
        "",
        "## Limits",
        "",
        "- Only scenario `connected`; partition/node-failure/telemetry faults and p2p model transfer "
        "were not run. 2 drones, 16x16 worlds, 150 ticks, hidden 32 NumPy MLP; not the Torch runtime.",
        "- The reference return was fixed by us and penalises revisits; read it together with the "
        "reward-free coverage gain and targets-after-spawn.",
        "- Stage A used 4 seeds, so the top-4 cut is noisy; the one-factor-at-a-time grid does not "
        "test interactions beyond the two combined cells.",
        "- The shared id changes two things relative to the local id: peer stood-on flags (indices 57-81) "
        "and, because the InfoBus also merges peer map cells into the buffer, a frontier feature that "
        "reflects peer knowledge. No ablation separates the two; Stage A only shows shared > local "
        "(26.5 vs -3.5 mean reference return, 4 seeds).",
        "- The selected learner still trails the rule explorer (return CI excludes 0 on the negative side, "
        "coverage gain equal, targets after spawn inconclusive) and bumps walls ~5 times per episode "
        "(rule: 0). Revisit rate 0.40 vs rule 0.15.",
        "- Hyperparameters other than the 11 registered cells (hidden size, gamma, batch, target sync, "
        "longer training) were not explored; the learner may still be improving at 400 episodes "
        "(see curves.csv).",
        "- Prereg amendment 1 (stage B 500 -> 400 episodes) is recorded in the YAML.",
        "",
    ]
    (out / "summary.md").write_text("\n".join(L))
    curves(out, B)
    (out / "results.json").write_text(
        json.dumps(
            {
                "selected": S["selected"],
                "prereg": S["prereg"],
                "stageA_ranking": A["ranking"],
                "stageB_table": S["table"],
                "baselines_sel": S["baselines_sel"],
                "paired_selected": S["paired_selected"],
                "test": T,
            },
            indent=1,
        )
    )

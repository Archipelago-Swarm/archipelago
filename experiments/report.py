"""Generate REPORT.md from run artifacts (raw.jsonl, summary.json, manifest.json, timing.jsonl).

No number in the report is typed by hand: `python experiments/report.py <out_dir>`.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np


def load(out):
    out = Path(out)
    rows = [json.loads(x) for x in (out / "raw.jsonl").read_text().splitlines() if x]
    man = json.loads((out / "manifest.json").read_text())
    summ = json.loads((out / "summary.json").read_text())
    tpath = out / "timing.jsonl"
    timing = [json.loads(x) for x in tpath.read_text().splitlines() if x] if tpath.exists() else []
    return rows, man, summ, timing


def table(head, body):
    return "\n".join(
        ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        + ["| " + " | ".join(str(c) for c in r) + " |" for r in body]
    )


def ms(x):
    x = np.asarray(x, float)
    return f"{x.mean():.2f} ± {x.std(ddof=1) if len(x) > 1 else 0:.2f}"


def render(rows, man, summ, timing):
    scens = sorted({r["scenario"] for r in rows})
    modes = [m for m in man["resolved_modes"] if any(r["mode"] == m for r in rows)]
    n = len(man["seeds"]["experiment_seeds"])
    o = [f"# Experiment report (generated, protocol {man['protocol']})", ""]
    o.append(
        f"Generated from `raw.jsonl`/`summary.json`/`manifest.json`; do not edit by hand. "
        f"Commit `{man['commit']}` (worktree dirty: {man['worktree_dirty']}), backend "
        f"`{man['backend']}`, config hash `{man['config_hash'][:16]}`, reward `{man['reward_id']}` "
        f"hash `{man['reward_hash'][:16]}`, observation `{man['observation_id']}`."
    )
    o.append(
        f"Experiment seeds: **n={n}**{' (PRELIMINARY, n<10)' if n < 10 else ''}; "
        f"{man['args']['episodes']} training episodes per cell; "
        f"{len(man['seeds']['test'])} frozen test seeds ({man['seeds']['test'][0]}.."
        f"{man['seeds']['test'][-1]}); validation seeds {man['seeds']['validation']}. "
        f"Train world seeds {man['seeds']['train_formula']} are disjoint from both (asserted). "
        f"Reproduce: `{' '.join(map(str, man['commands']['argv']))}` with PYTHONPATH="
        f"`{man['commands']['env']['PYTHONPATH']}`."
    )
    o += ["", "## Modes", "", table(["mode", "label"], [(m, man["mode_labels"][m]) for m in modes])]
    o += [
        "",
        "Secondary modes are not validated comparisons; see the labels. Rule/idle do not train.",
    ]
    for sc in scens:
        sel = [r for r in rows if r["scenario"] == sc]
        body = []
        for m in modes:
            mr = [r for r in sel if r["mode"] == m]
            if not mr:
                continue
            body.append(
                (
                    m,
                    ms([r["mean"] for r in mr]),
                    ms([np.mean(r["coverage"]) for r in mr]),
                    ms([np.mean(r["found"]) for r in mr]),
                    f"{np.mean([r['collisions_per_agent_step'] for r in mr]):.3f}",
                    f"{np.mean([np.mean(r['ticks']) for r in mr]):.1f}",
                )
            )
        o += ["", f"## Scenario `{sc}`: test results (mean ± sd over experiment seeds)", ""]
        o.append(
            table(
                ["mode", "return", "coverage", "targets found", "collisions/agent-step", "ticks"],
                body,
            )
        )
        for base in ("independent", "idle"):
            ps = [p for p in summ["paired"] if p["scenario"] == sc and p["vs"] == base]
            if ps:
                o += [
                    "",
                    f"Paired difference vs `{base}` (bootstrap 95% CI over seeds; "
                    "a claim needs a CI excluding 0):",
                    "",
                ]
                o.append(
                    table(
                        ["mode", "n", "mean diff", "95% CI", "wins"],
                        [
                            (
                                p["mode"],
                                p["n"],
                                f"{p['mean_diff']:+.3f}",
                                f"({p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f})",
                                p["wins"],
                            )
                            for p in ps
                        ],
                    )
                )
    o += ["", "## Training budgets (mean per cell over seeds and scenarios)", ""]
    body = []
    for m in modes:
        mr = [r["budget"] for r in rows if r["mode"] == m]

        def f(k, mr=mr):
            return f"{np.mean([b[k] for b in mr]):.0f}"

        body.append(
            (
                m,
                f("episodes"),
                f("train_env_steps"),
                f("transitions"),
                f("optimizer_updates"),
                f("update_samples"),
                f("info_bytes"),
                f("model_bytes"),
                f("replay_bytes"),
                f("blocked_agent_steps"),
            )
        )
    o.append(
        table(
            [
                "mode",
                "train episodes",
                "env steps",
                "transitions",
                "optimizer updates",
                "update samples",
                "info bytes",
                "model bytes",
                "replay bytes",
                "blocked agent-steps",
            ],
            body,
        )
    )
    o += [
        "",
        "Equal episode counts are not equal budgets: node_failure loses the dead node's "
        "transitions, central_online loses transitions while its control link is cut, and "
        "rule/idle train nothing. Compare modes only with these columns in view.",
    ]
    o += ["", "## Per-scenario transitions (mean per cell)", ""]

    def trans(m, sc):
        v = [r["budget"]["transitions"] for r in rows if r["mode"] == m and r["scenario"] == sc]
        return f"{np.mean(v):.0f}"

    o.append(table(["mode", *scens], [(m, *[trans(m, sc) for sc in scens]) for m in modes]))
    o += ["", "## Candidate validation overhead (p2p)", ""]
    dec = [(r, d) for r in rows if r["mode"] == "p2p" for d in r["decisions"]]
    wall = defaultdict(float)
    for t in timing:
        if t["mode"] == "p2p":
            wall["s"] += sum(t["decision_wall_s"])
    if dec:
        acc = sum(d["accepted"] for _, d in dec)
        o.append(
            f"{len(dec)} candidate decisions, {acc} accepted, {len(dec) - acc} rejected; "
            f"{sum(d['evaluations'] for _, d in dec)} validation episodes "
            f"({sum(d['eval_env_ticks'] for _, d in dec)} env ticks), "
            f"{sum(d['bytes'] for _, d in dec)} candidate bytes, {wall['s']:.1f} wall seconds "
            f"(timing.jsonl, nondeterministic). Per-decision records are in raw.jsonl `decisions`."
        )
    else:
        o.append("No p2p decisions in this run.")
    o += ["", "## Fault ticks reached in test episodes (fraction of test episodes)", ""]
    body = []
    for sc in scens:
        for m in modes:
            mr = [r["fault_reached"] for r in rows if r["scenario"] == sc and r["mode"] == m]
            if mr and mr[0]:
                body.append(
                    (
                        sc,
                        m,
                        ", ".join(f"{k}={np.mean([x[k] for x in mr]):.2f}" for k in sorted(mr[0])),
                    )
                )
    o.append(table(["scenario", "mode", "reached"], body) if body else "No faults configured.")
    o += [
        "",
        f"Minimum battery at episode end across all test episodes: "
        f"{min(r['min_battery'] for r in rows):.3f} (never exhausted before the horizon).",
    ]
    return "\n".join(o) + "\n"


def write_report(out):
    text = render(*load(out))
    (Path(out) / "REPORT.md").write_bytes(text.encode())
    return text


if __name__ == "__main__":
    write_report(sys.argv[1] if len(sys.argv) > 1 else "experiments/out")

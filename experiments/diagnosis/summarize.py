"""Print the measured quantities quoted in idle_vs_learners.md from pilot_results.json."""

import json
from pathlib import Path

import numpy as np

res = json.loads(Path(__file__).with_name("pilot_results.json").read_text())
groups = {}
for c in res["cells"]:
    groups.setdefault((c["mode"], c["obs"]), []).append(c)
print("obs_audit", res["obs_audit"], "wall_s", round(res["wall_s"], 1))
for (mode, obs), cs in groups.items():
    eps = [e for c in cs for e in c["episodes"]]

    def m(f, eps=eps):
        return float(np.mean([f(e) for e in eps]))

    parts = {k: round(m(lambda e, k=k: e["parts"][k]), 2) for k in eps[0]["parts"]}
    hist = {}
    for e in eps:
        for a, n in e["action_hist"].items():
            hist[a] = hist.get(a, 0) + n
    tot = sum(hist.values())
    print(
        f"\n{mode} {obs}: ret={m(lambda e: e['ret']):.2f} (per-seed "
        f"{[round(c['mean_ret'], 2) for c in cs]}) ticks={m(lambda e: e['ticks']):.0f} "
        f"found={m(lambda e: e['found']):.2f} cov={m(lambda e: e['coverage']):.2f} "
        f"wall_coll={m(lambda e: e['wall_collisions']):.1f} "
        f"agent_coll={m(lambda e: e['agent_collisions']):.1f} "
        f"revisit={m(lambda e: e['revisit_rate']):.2f}"
    )
    print("  return parts", parts)
    print("  action share", {a: round(n / tot, 2) for a, n in sorted(hist.items())})
    if "q_audit" in cs[0]:
        for c in cs:
            q = c["q_audit"]["node-0"]
            print(
                f"  seed{c['seed']} train={c['train']} node-0 updates={q['updates']} "
                f"replay={q['replay_rows']}/{q['transitions_seen']} "
                f"q[{q['q_min']:.1f},{q['q_max']:.1f}] "
                f"spread={q['q_action_spread_mean']:.3f} greedy={q['greedy_hist']} "
                f"loss={[round(x, 3) for x in q['loss_windows']]} "
                f"r_mean={q['reward_in_replay_mean']:.3f} "
                f"r>0.5={q['reward_in_replay_pos_frac']:.3f}"
            )
    print("  trace seed0 ep0:", cs[0]["episodes"][0]["trace_head"][:24])

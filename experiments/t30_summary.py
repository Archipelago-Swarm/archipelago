# ruff: noqa: E501  (long prose and table lines)
"""T30 summary.md writer (text only; every number comes from results.json / the raw evidence)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import t30_analysis as A
from t30_report import ARMS, find_line

NAMES = {"ref_return": "reference return (rew-v1 re-scored)", "coverage_gain": "coverage gain after spawn",
         "targets_after_spawn": "targets found after spawn (of 8)", "wall_collisions": "wall collisions / episode",
         "revisit_rate": "revisit rate", "ticks": "episode ticks"}  # fmt: skip
PAIRS = [
    ("fleet", "idle"),
    ("fleet", "rule"),
    ("fleet", "isolated"),
    ("isolated", "idle"),
    ("isolated", "rule"),
]


def ci(p: dict) -> str:
    return f"{p['mean_diff']:+.3f} [{p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f}]"


def yn(b: bool) -> str:
    return "SUPPORTED" if b else "NOT SUPPORTED"


def ptr(
    out: Path, rel: str, needle: str | None = None, nth: int = 1, line: int | None = None
) -> str:
    ln = line if line is not None else (find_line(out / rel, needle, nth) if needle else None)
    return f"`experiments/out/T30/{rel}{':' + str(ln) if ln else ''}`"


def write_summary(out: Path, res: dict[str, Any], ev: dict, tables: dict, pre: dict) -> None:
    smoke = res["smoke"]
    d, oc = res["decisions_D"], res["outcomes"]
    fl, iso = res["claims"]["fleet"], res["claims"]["isolated"]
    rows = [json.loads(x) for x in (out / "decisions.jsonl").read_text().splitlines()]
    L: list[str] = []
    w = L.append
    w(
        "# T30 live pilot: real processes, real optimizer updates, real peer exchange"
        + (" (SMOKE RUN, not the registered run)" if smoke else "")
    )
    w("")
    w(
        f"Pre-registration `experiments/prereg/T30.yaml` at commit `{res['prereg_commit']}` (committed before the run); "
        f"code commit `{res['code_commit']}` (working tree {'DIRTY' if res['git_dirty'] else 'clean'} for experiments/packages/services). "
        "Reproduce: `uv run python experiments/t30_live.py all` (about 40 min wall on 4 cores; no Docker, no cloud)."
    )
    w("")
    w(
        "Setup: per arm one coordinator and four node processes on localhost (`tests/e2e/procs.py` Cluster, configuration only changed in "
        "`experiments/t30_cluster.py`), world 16x16, 8 targets, 150 ticks, 4 drones in the corners, battery_scale 4, T37 ids "
        "(`grid-flat-v2-visits-shared`, `rew-v1`, `sched-t37-v1`), PyTorch "
        f"{fl['A']['detail']['node-01']['torch_version']} on every node. Episodes per arm: "
        f"{res['episode_kinds']['fleet']} (train / validation / test). Fleet: halves {{node-01,node-02}} | {{node-03,node-04}} cut during ticks [40,90) of every episode, exchange window every 25 ticks. "
        "Isolated control: all links cut for ticks [0,150) of every episode and no node holds any peer address (prereg amendment 1). SIGKILL of node-03 at episode index 70, tick >= 60, in both arms."
    )
    w("")
    w(
        "**Budget deviation (decided before any result, see prereg `budget_note`):** 150 training episodes of 150 ticks per node, not T37's 400 episodes "
        "(that would take ~80 min per arm). The learner is therefore under-trained relative to T37, and one training run per arm exists (no training-seed replication)."
    )
    w("")
    w("## Verdict")
    w("")
    w(
        f"- A (four nodes each do optimizer updates on their own policy/optimizer/replay): **{yn(fl['A']['supported'])}** (isolated arm: {yn(iso['A']['supported'])})"
    )
    w(
        f"- B (partition: local learning continues, nothing crosses the cut, exchange resumes with validation-gated decisions): **{yn(fl['B']['supported'])}** (isolated control: {yn(iso['B']['supported'])})"
    )
    c = fl["C"]
    cc = c.get("checks", {})
    w(
        f"- C (SIGKILL, restart from checkpoint, sequence numbers kept, learning resumes): **{yn(bool(cc) and all(cc.values()))}** in fleet; isolated: **{yn(bool(iso['C'].get('checks')) and all(iso['C']['checks'].values()))}**"
    )
    w(
        f"- D1 live-trained fleet beats idle on all three primary metrics (CI lower bound > 0): **{yn(d['fleet_beats_idle_all_three'])}**"
    )
    w(
        f"- D2 fleet beats the rule explorer on reference return: **{yn(d['fleet_beats_rule_on_ref_return'])}** (CI verdict: {d['fleet_vs_rule_ref_return']})"
    )
    w(
        f"- D3 fleet beats the isolated-nodes control on reference return (exchange helps): **{yn(d['fleet_beats_isolated_on_ref_return'])}** (CI verdict: {d['fleet_vs_isolated_ref_return']})"
    )
    w(
        f"- isolated control beats idle on all three primary metrics: **{yn(d['isolated_beats_idle_all_three'])}**"
    )
    w("")
    w(
        "## D. Outcomes on the frozen test worlds 200-219"
        + (" (smoke: seeds 5200-5201)" if smoke else "")
    )
    w("")
    w(
        "Mean per world (20 worlds; greedy frozen policies for fleet/isolated, scripted for idle/rule):"
    )
    w("")
    w("| metric | fleet | isolated | idle | rule |")
    w("|---|---|---|---|---|")
    for m in A.PRIMARY + A.SECONDARY:
        mm = oc["means"]
        w(
            f"| {NAMES[m]} | "
            + " | ".join(f"{mm[a][m]:.3f}" for a in ("fleet", "isolated", "idle", "rule"))
            + " |"
        )
    w("")
    w(
        "Paired differences (first minus second), mean [95% bootstrap CI over worlds, 4000 resamples, seed 0]; "
        "worlds+/worlds- = number of worlds where the difference is positive/negative:"
    )
    w("")
    w("| metric | pair | mean diff [95% CI] | worlds+ / worlds- | CI verdict |")
    w("|---|---|---|---|---|")
    for m in A.PRIMARY + A.SECONDARY:
        for a, b in PAIRS:
            p = oc["paired"][f"{a}-{b}"][m]
            w(
                f"| {NAMES[m]} | {a} - {b} | {ci(p)} | {p['worlds_positive']} / {p['worlds_negative']} | {p['verdict']} |"
            )
    w("")
    w(
        "Uncertainty: the CI resamples the 20 test worlds only. There is one training run per arm, so training-run variance (which T37 showed to be large at this budget) is NOT in these intervals; "
        "a different training seed could move the fleet and the isolated arm by more than the CIs suggest. Metrics re-score the actions the live nodes chose "
        "(coordinator replay `raw/<arm>/replays/ep-NNNN`, final state hash checked) with the T37 reference return. The fault schedule of the arm also applies to its test episodes."
    )
    w("")
    w(
        f"Sources: {ptr(out, 'curves.csv')} (per-episode metrics, test rows are the last 20 per arm), {ptr(out, 'results.json', '"paired"')} (all pairs)."
    )
    w("")
    # learning curves
    w(
        "### Learning curve checkpoints (validation seeds 100-102, greedy frozen, mean of 3 worlds; training-episode means are exploration-confounded)"
    )
    w("")
    w("| arm | after training episodes | ref return | coverage gain | targets after spawn |")
    w("|---|---|---|---|---|")
    for a in ARMS:
        trained = 0
        block: list[dict] = []
        for r in tables[a] + [{"kind": "end"}]:
            if r["kind"] == "validation":
                block.append(r)
            else:
                if block:
                    n = len(block)
                    w(
                        f"| {a} | {trained} | "
                        + " | ".join(f"{sum(x[m] for x in block) / n:.2f}" for m in A.PRIMARY)
                        + " |"
                    )
                    block = []
                trained += r["kind"] == "train"
    w("")
    # claim A
    w("## A. Independent learning on each node")
    w("")
    w(
        "| node | train steps | own replay | policy version | policy sha256 (first 12) | local_update events | boot id |"
    )
    w("|---|---|---|---|---|---|---|")
    for n, v in fl["A"]["detail"].items():
        w(
            f"| {n} | {v['train_steps_final']} | {v['replay_size_final']} | {v['policy_version']} | {v['policy_sha256'][:12]} | {v['local_update_events']} | {v['boot_id']} |"
        )
    w("")
    w(
        f"Distinct final policy hashes: fleet {fl['A']['distinct_hashes']} of 4 (an accepted peer candidate replaces the receiver's parameters, so ties are expected there), isolated {iso['A']['distinct_hashes']} of 4 (required). "
        f"Over all 1 s status samples (all four nodes reachable): fleet {fl['A']['hash_samples']}, isolated {iso['A']['hash_samples']}. Fleet checks: "
        + "; ".join(f"{k}: {v}" for k, v in fl["A"]["checks"].items())
        + ". Isolated checks: "
        + "; ".join(f"{k}: {v}" for k, v in iso["A"]["checks"].items())
        + "."
    )
    w(
        f"Pointers: {ptr(out, 'results.json', '"A": {')} (fleet), {ptr(out, 'raw/fleet/node_status_final.json')} (full node status incl. `train_steps`, `replay_size`, `policy_sha256`, `backend`), "
        f"{ptr(out, 'raw/fleet/telemetry.jsonl.gz')} (all shipped records; `local_update` LearningEvents), per-node checkpoints pointers {ptr(out, 'raw/fleet/node_local/node-01/ckpt_current.json')}. "
        "Each node has its own checkpoint directory and telemetry spool (`raw/<arm>/node_local/<node>`)."
    )
    w("")
    # claim B
    w("## B. Partition window")
    w("")
    for arm, cl in (("fleet", fl), ("isolated", iso)):
        w(f"**{arm}** ({yn(cl['B']['supported'])}):")
        w("")
        for k, v in cl["B"]["checks"].items():
            w(f"- {'PASS' if v else 'FAIL'}: {k}")
        dd, ss = cl["B"]["B_decisions"], cl["B"]["B_summaries"]
        w(
            f"- decisions: {dd['decisions']} total ({dd['accepted']} accepted, {dd['rejected']} rejected); cross-cut inside window: {len(dd['cross_inside_cut'])}; cross-cut outside window: {dd['cross_outside_cut']}; same-side inside window: {dd['same_side_inside_cut']}; same-side outside window: {dd['same_side_outside_cut']}; reasons: {dd['by_reason']}"
        )
        w(
            f"- visit summaries applied (receiver tick vs window; node `summaries.rx_ticks`, only the current boot of node-03 is in memory): {ss}"
        )
        w(
            f"- poll evidence of local learning inside the cut (episodes where train_steps grew / stayed flat between first and last sample in the window): {cl['B']['B_local_learning_in_cut']}"
        )
        w("")
    first_cross = next(
        (
            i
            for i, r in enumerate(rows, 1)
            if r["arm"] == "fleet" and r["cross_cut"] and not r["tick_in_cut_window"]
        ),
        None,
    )
    first_acc = next(
        (i for i, r in enumerate(rows, 1) if r["arm"] == "fleet" and r["transfer"] == "accepted"),
        None,
    )
    first_rej = next(
        (i for i, r in enumerate(rows, 1) if r["arm"] == "fleet" and r["transfer"] == "rejected"),
        None,
    )
    w(
        "Counters per node (fleet), `offers_cut`/`summaries_cut` are sends suppressed by the sender's schedule, `received_cut`/`summaries_received_cut` receives refused on a cut link:"
    )
    w("")
    w(
        "| node | offers_sent | offers_cut | offers_received | received_cut | accepted | rejected | window_limit | summaries_sent | summaries_cut | summaries_received | summaries_received_cut | deadline misses |"
    )
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n, k in fl["B"]["B_counters"].items():
        w(
            f"| {n} | {k['offers_sent']} | {k['offers_cut']} | {k['offers_received']} | {k['received_cut']} | {k['decisions_accepted']} | {k['decisions_rejected']} | {k['decisions_window_limit']} | {k['summaries_sent']} | {k['summaries_cut']} | {k['summaries_received']} | {k['summaries_received_cut']} | {k['feedback_deadline_missed']} |"
        )
    w("")
    w(
        f"Pointers: {ptr(out, 'decisions.jsonl', line=first_cross)} (first cross-cut decision after a cut ended: exchange resumed), "
        f"{ptr(out, 'decisions.jsonl', line=first_acc)} (first accepted), {ptr(out, 'decisions.jsonl', line=first_rej)} (first rejected, with reason), "
        f"{ptr(out, 'results.json', '"B_decisions"', 1)} (fleet) and {ptr(out, 'results.json', '"B_decisions"', 2)} (isolated), "
        f"{ptr(out, 'results.json', '"B_summaries"', 1)}, {ptr(out, 'raw/fleet/samples.jsonl', '"fault_phase": "partition"')} (first 1 s status sample inside a cut), "
        f"{ptr(out, 'spool_excerpt.jsonl', '"why": "first cross-cut decision after a cut"')} (node-local spool record of the same decision)."
    )
    w("")
    # claim C
    w("## C. SIGKILL and restart")
    w("")
    for arm in ARMS:
        cl = res["claims"][arm]["C"]
        if not cl.get("kill_executed"):
            w(f"**{arm}**: kill NOT executed (run ended before the trigger).")
            continue
        w(
            f"**{arm}**: {cl['node']} SIGKILLed at episode {cl['pre']['episode']} tick {cl['pre']['tick']} (pid {cl['pids'][0]} -> {cl['pids'][1]}), restart-to-ready {cl['restart_seconds']} s; checkpoint pointer before {cl['ckpt_pre'].get('current')}."
        )
        w("")
        w(
            "| | boot id | train steps | replay size | policy sha256 | checkpoint gen | sequence ceiling |"
        )
        w("|---|---|---|---|---|---|---|")
        for lab, k in (("just before kill", "pre"), ("just after restart", "post")):
            v = cl[k]
            w(
                f"| {lab} | {v['boot_id']} | {v['train_steps']} | {v['replay_size']} | {v['policy_sha256'][:12]} | {v['checkpoint_generation']} | {v['sequence_ceiling']} |"
            )
        w("")
        w(
            f"Restore info after restart: {cl['restore_info']}. Telemetry sequence ranges per boot: {cl['sequence_continuity']}. Max train_steps seen afterwards: {cl['train_steps_after_restart_max']}."
        )
        w(
            "Checks: "
            + "; ".join(f"{'PASS' if v else 'FAIL'} {k}" for k, v in cl["checks"].items())
            + "."
        )
        w(
            f"Pointers: {ptr(out, f'raw/{arm}/kill.json', '"pre"')}, {ptr(out, f'raw/{arm}/kill.json', '"post"')}, {ptr(out, 'spool_excerpt.jsonl', '"restart boundary"', 1 if arm == 'fleet' else 9)} (spool lines around the boundary), {ptr(out, 'results.json', '"sequence_continuity"', 1 if arm == 'fleet' else 2)}."
        )
        w("")
    w(
        "The state lost to the kill is the work since the last checkpoint generation (checkpoint every 200 feedback steps and at episode end, A17); train steps after restart are therefore at most the pre-kill value. "
        "While the node was down the coordinator applied `stay` for it, and marked it unavailable until the next episode reset."
    )
    w("")
    # unsupported
    w("## Unsupported claims and limits")
    w("")
    items = []
    if not d["fleet_beats_rule_on_ref_return"]:
        items.append(
            f"**Beating the rule explorer is not shown** (fleet-rule reference return {ci(oc['paired']['fleet-rule']['ref_return'])}, verdict {d['fleet_vs_rule_ref_return']})."
        )
    if not d["fleet_beats_isolated_on_ref_return"]:
        items.append(
            f"**Exchange (model offers + visit summaries) helping is not shown** (fleet-isolated reference return {ci(oc['paired']['fleet-isolated']['ref_return'])}, verdict {d['fleet_vs_isolated_ref_return']})."
        )
    if not d["fleet_beats_idle_all_three"]:
        items.append("**Learning helping against idle is not shown on all three primary metrics.**")
    if not d["isolated_beats_idle_all_three"]:
        items.append("The isolated control does not beat idle on all three primary metrics.")
    for arm in ARMS:
        for k, cl in (("A", res["claims"][arm]["A"]), ("B", res["claims"][arm]["B"])):
            if not cl["supported"]:
                items.append(
                    f"Claim {k} ({arm}) failed checks: {[x for x, v in cl['checks'].items() if not v]}."
                )
        cs = res["claims"][arm]["C"].get("checks")
        if not cs or not all(cs.values()):
            items.append(
                f"Claim C ({arm}) failed or not executed: {[x for x, v in (cs or {}).items() if not v]}."
            )
    items += [
        "Not run: untrained same-architecture network and random policy (T37 criteria for 'learning helps' also use them); only idle, rule explorer and the isolated control are compared.",
        "One training run per arm (fixed seed): no between-training-run variance, so D-claims are about these two trained fleets only. Differences between fleet and isolated can be training-run noise.",
        "Training budget 150 episodes per node, below T37's 400; no hyperparameter was changed from the T37-selected recipe and nothing was tuned on test seeds.",
        "The fleet arm's cut is a halves partition (two groups of two keep exchanging), not total isolation; its test episodes are also run under the cut.",
        "World differs from T37: 4 drones (T37: 2), battery_scale 4 (T37: 1), fixed corner starts; the live world has no peer map-cell merge (T38 deviation 1), so results are not comparable one-to-one to T37 numbers.",
        "Telemetry evidence comes from a driver-side sink standing in for the API ingest; the API, the dashboard and TigerData were not part of this run. Docker/Compose were not run.",
        "Summary-trace evidence (`rx_ticks`) is held in node memory: the restarted node-03 only has post-restart episodes.",
        "Wall-clock effects: both arms ran concurrently on the same 4 cores; deadline misses are reported in the counters table, not hidden.",
    ]
    for i in items:
        w(f"- {i}")
    w("")
    w("## Files")
    w("")
    w(
        "`results.json` (all numbers), `curves.csv`, `decisions.jsonl` (every telemetry decision of both arms with source, cut flags and reasons), `spool_excerpt.jsonl`, "
        "`raw/<arm>/` (`samples.jsonl` 1 s status polls, `telemetry.jsonl.gz`, `coordinator_events.jsonl.gz`, `run_status.json`, `kill.json`, `node_status_final.json`, `replays/`, `node_local/`, `logs/`)."
    )
    (out / "summary.md").write_text("\n".join(L) + "\n")

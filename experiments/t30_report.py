# ruff: noqa: E501  (long prose and table lines)
"""T30 analysis: raw evidence of both arms -> results.json, summary.md, curves.csv, decisions.jsonl,
spool_excerpt.jsonl. Decision rules are the ones registered in experiments/prereg/T30.yaml."""

from __future__ import annotations

import csv
import gzip
import json
import subprocess
from pathlib import Path
from typing import Any

import t30_analysis as A
import yaml
from archipelago_contracts.models import RunConfig

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PREREG = ROOT / "experiments" / "prereg" / "T30.yaml"
ARMS = ("fleet", "isolated")
NODES = ["node-01", "node-02", "node-03", "node-04"]
HALVES = {"node-01": 0, "node-02": 0, "node-03": 1, "node-04": 1}
SEPARATE = {n: i for i, n in enumerate(NODES)}  # isolated arm: every node on its own side
MAX_TICKS = 150


def jl(path: Path) -> list[dict]:
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt") as f:
        return [json.loads(line) for line in f if line.strip()]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def find_line(path: Path, needle: str, nth: int = 1) -> int | None:
    k = 0
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if needle in line:
            k += 1
            if k == nth:
                return i
    return None


# ------------------------------------------------------------------------------------ outcomes
def episode_table(raw: Path) -> list[dict]:
    status = json.loads((raw / "run_status.json").read_text())
    rows = []
    for e in status["episodes_done"]:
        m = A.replay_metrics(raw / "replays" / f"ep-{e['episode']:04d}")
        rows.append({
            "episode": e["episode"], "kind": e["kind"], "seed": e["seed"], "ticks": e["ticks"],
            "coverage": e["coverage"], "live_mean_return": sum(e["returns"].values()) / len(e["returns"]),
            **m,
        })  # fmt: skip
    return rows


def baselines(raw: Path, seeds: list[int]) -> dict[str, list[dict]]:
    first = sorted((raw / "replays").iterdir())[-1]
    manifest = json.loads((first / "manifest.json").read_text())
    base_cfg = RunConfig.model_validate(manifest["run_config"])
    out: dict[str, list[dict]] = {"idle": [], "rule": []}
    for s in seeds:
        cfg = base_cfg.model_copy(update={"seeds": {**base_cfg.seeds, "env": s}})
        out["idle"].append(A.play_policy(cfg, manifest["world_kwargs"], A.idle_policy))
        out["rule"].append(A.play_policy(cfg, manifest["world_kwargs"], A.rule_policy))
    return out


def outcome_stats(test: dict[str, list[dict]]) -> dict[str, Any]:
    """test[arm] = per-world metric dicts (arm in fleet, isolated, idle, rule), same world order."""
    res: dict[str, Any] = {"means": {}, "paired": {}}
    for arm, rows in test.items():
        res["means"][arm] = {
            m: sum(r[m] for r in rows) / len(rows) for m in A.PRIMARY + A.SECONDARY
        }
    pairs = [("fleet", "idle"), ("fleet", "rule"), ("fleet", "isolated"), ("isolated", "idle"),
             ("isolated", "rule")]  # fmt: skip
    for a, b in pairs:
        res["paired"][f"{a}-{b}"] = {}
        for m in A.PRIMARY + A.SECONDARY:
            d = [x[m] - y[m] for x, y in zip(test[a], test[b], strict=True)]
            p = A.paired_bootstrap(d)
            res["paired"][f"{a}-{b}"][m] = p | {"verdict": A.verdict(p)}
    return res


# ------------------------------------------------------------------------------------ evidence
def local_learning(samples: list[dict], windows: list[dict], skip_eps: set[int]) -> dict[str, Any]:
    """Per node: train_steps growth between the first and last sample inside the cut window of the
    same training episode (poll samples; needs >= 2 samples in the window)."""
    out: dict[str, Any] = {}
    for n in NODES:
        grew = flat = 0
        by_ep: dict[int, list[int]] = {}
        for s in samples:
            nd = s["nodes"].get(n, {})
            if (s["kind"] != "train" or "error" in nd or s["episode"] in skip_eps
                    or nd["episode"] != s["episode"]):  # fmt: skip
                continue
            if A.cut_active(s["tick"], windows) and A.cut_active(nd["tick"], windows):
                by_ep.setdefault(s["episode"], []).append((nd["tick"], nd["train_steps"]))
        for pts in by_ep.values():
            if len(pts) >= 2 and pts[-1][0] - pts[0][0] >= 5:  # the window must have advanced
                grew += pts[-1][1] > pts[0][1]
                flat += pts[-1][1] <= pts[0][1]
        out[n] = {"episodes_with_growth_in_window": grew, "episodes_flat_in_window": flat}
    return out


def decision_rows(
    arm: str, recs: list[dict], halves: dict[str, int], windows: list[dict]
) -> list[dict]:
    rows = []
    for r in recs:
        if not A.is_decision(r):
            continue
        tick = r["sim_tick"] % MAX_TICKS
        src, dst = A.decision_source(r.get("reason")), r["source_node_id"]
        rows.append({
            "arm": arm, "event_id": r["event_id"], "node": dst, "source": src,
            "episode": r["sim_tick"] // MAX_TICKS, "tick_in_episode": tick, "sim_tick": r["sim_tick"],
            "cross_cut": None if src is None else halves[src] != halves[dst],
            "tick_in_cut_window": A.cut_active(tick, windows), "transfer": r["transfer"],
            "reason": r["reason"], "candidate_score": r.get("candidate_score"),
            "previous_version": r.get("previous_version"), "new_version": r.get("new_version"),
            "phase_of_record": None,
        })  # fmt: skip
    return rows


def arm_evidence(arm: str, raw: Path, pre: dict, cfg_faults: list[dict]) -> dict[str, Any]:
    halves = HALVES if arm == "fleet" else SEPARATE
    recs = jl(raw / "telemetry.jsonl.gz")
    samples = jl(raw / "samples.jsonl")
    final = json.loads((raw / "node_status_final.json").read_text())
    kill = json.loads((raw / "kill.json").read_text())
    kill_ep = kill["planned"]["at_episode_index"]
    ev: dict[str, Any] = {"n_telemetry_records": len(recs), "n_samples": len(samples)}
    # A: independent learners
    updates = {n: [r for r in recs if r["source_node_id"] == n and r["kind"] == "learning_event"
                   and (r.get("reason") or "").startswith("local_update")] for n in NODES}  # fmt: skip
    ev["A"] = {
        n: {
            "train_steps_final": final[n]["train_steps"], "replay_size_final": final[n]["replay_size"],
            "policy_sha256": final[n]["policy_sha256"], "policy_version": final[n]["policy_version"],
            "boot_id": final[n]["boot_id"], "local_update_events": len(updates[n]),
            "checkpoint_generation": final[n]["checkpoint_generation"], "epsilon_final": final[n]["epsilon"],
            "encoder_id": final[n]["encoder_id"], "reward_id": final[n]["reward_id"],
            "learner_schedule_id": final[n]["learner_schedule_id"], "backend": final[n]["backend"],
            "torch_version": final[n]["torch_version"],
        }
        for n in NODES
    }  # fmt: skip
    ev["A_distinct_policy_hashes"] = len({v["policy_sha256"] for v in ev["A"].values()})
    counts = [len({s["nodes"][n]["policy_sha256"] for n in NODES}) for s in samples
              if all("error" not in s["nodes"][n] for n in NODES)]  # fmt: skip
    ev["A_hash_samples"] = {
        "n_samples": len(counts), "share_with_4_distinct": sum(x == 4 for x in counts) / max(1, len(counts)),
        "min_distinct": min(counts, default=None), "max_distinct": max(counts, default=None),
    }  # fmt: skip
    # B: partition behaviour
    ev["B_local_learning_in_cut"] = local_learning(samples, cfg_faults, {kill_ep})
    ev["B_decisions"] = A.split_decisions(recs, halves, cfg_faults, MAX_TICKS)
    rx = {n: final[n]["summaries"].get("rx_ticks", {}) for n in NODES}
    ev["B_summaries"] = A.summary_rx_evidence(rx, halves, cfg_faults)
    ev["B_counters"] = {n: {k: final[n]["counters"][k] for k in (
        "offers_sent", "offers_cut", "offers_received", "received_cut", "exchanges",
        "decisions_accepted", "decisions_rejected", "decisions_window_limit", "summaries_sent",
        "summaries_cut", "summaries_received", "summaries_received_cut", "summaries_applied",
        "feedback_deadline_missed", "feedbacks")} for n in NODES}  # fmt: skip
    # C: SIGKILL + restart
    cn = kill["node"] if kill.get("done") else kill["planned"]["node"]
    c: dict[str, Any] = {"node": cn, "kill_executed": bool(kill.get("done"))}
    if kill.get("done"):
        pre_s, post_s = kill["pre"], kill["post"]
        later = [s["nodes"][cn]["train_steps"] for s in samples
                 if s["t"] > kill["t_kill"] and "error" not in s["nodes"][cn]]  # fmt: skip
        seq = A.sequence_continuity(recs, cn)
        c |= {
            "pre": {k: pre_s[k] for k in ("boot_id", "train_steps", "replay_size", "policy_sha256",
                                          "checkpoint_generation", "sequence_ceiling", "episode", "tick")},
            "post": {k: post_s[k] for k in ("boot_id", "train_steps", "replay_size", "policy_sha256",
                                            "checkpoint_generation", "sequence_ceiling", "episode", "tick")},
            "restore_info": kill["post_restore"], "restart_seconds": kill["restart_seconds"],
            "pids": [kill["pid_before"], kill["pid_after"]], "sequence_continuity": seq,
            "train_steps_after_restart_max": max(later) if later else None,
            "ckpt_pre": kill["ckpt_pre"], "ckpt_post": kill["ckpt_post"],
        }  # fmt: skip
        boots = seq["boots"]
        c["checks"] = {
            "new_boot_id": pre_s["boot_id"] != post_s["boot_id"],
            "restored_from_checkpoint": bool(kill["post_restore"].get("restored")),
            "train_steps_restored_positive_and_not_ahead":
                0 < post_s["train_steps"] <= pre_s["train_steps"],
            "replay_restored": 0 < post_s["replay_size"] <= pre_s["replay_size"],
            "sequences_continue_above_pre_kill": len(boots) >= 2 and not seq["ranges_overlap"],
            "no_event_id_reused": seq["duplicate_event_ids"] == 0,
            "sequence_ceiling_not_lower": post_s["sequence_ceiling"] >= pre_s["sequence_ceiling"],
            "learning_resumed": bool(later) and max(later) > post_s["train_steps"],
        }  # fmt: skip
    ev["C"] = c
    ev["_rows"] = decision_rows(arm, recs, halves, cfg_faults)
    ev["_records"] = recs
    return ev


def claim_b(arm: str, e: dict[str, Any]) -> dict[str, Any]:
    d, s, k = e["B_decisions"], e["B_summaries"], e["B_counters"]
    if arm == "fleet":
        learn = all(v["episodes_with_growth_in_window"] > 0 and v["episodes_flat_in_window"] == 0
                    for v in e["B_local_learning_in_cut"].values())  # fmt: skip
        checks = {
            "(i) train_steps rose inside the cut window in every sampled episode, every node": learn,
            "(ii) no cross-cut offer decided inside the cut window": not d["cross_inside_cut"],
            "(iii) no cross-cut visit summary applied inside the cut window": s["cross_applied_inside_cut"] == 0,
            "(iv) offers_cut>0 and summaries_cut>0 on every node (receiver refusals are reported, amendment 2)":
                all(v["offers_cut"] > 0 and v["summaries_cut"] > 0 for v in k.values()),
            "(v) cross-cut offers decided after the cut ended (exchange resumed), with reasons":
                d["cross_outside_cut"] > 0 and d["unknown_source"] == 0,
            "(v') open same-side peers kept exchanging inside the cut (positive control)":
                d["same_side_inside_cut"] > 0 and s["same_side_applied_inside_cut"] > 0,
            "cross-cut summaries do flow outside the window (positive control)":
                s["cross_applied_outside_cut"] > 0,
        }  # fmt: skip
    else:
        learn = all(v["episodes_with_growth_in_window"] > 0 and v["episodes_flat_in_window"] == 0
                    for v in e["B_local_learning_in_cut"].values())  # fmt: skip
        checks = {
            "train_steps rose in every sampled episode, every node": learn,
            "zero model decisions from any peer": d["decisions"] == 0,
            "zero visit summaries applied from any peer": all(v == 0 for v in s.values()),
            "offers_cut>0; nothing sent, nothing received":
                all(v["offers_cut"] > 0 and v["offers_received"] == 0
                    and v["summaries_received"] == 0 and v["offers_sent"] == 0
                    and v["summaries_sent"] == 0 for v in k.values()),
        }  # fmt: skip
    return {"checks": checks, "supported": all(checks.values())}


def claim_a(arm: str, e: dict[str, Any]) -> dict[str, Any]:
    a = e["A"]
    checks = {
        "every node train_steps > 0": all(v["train_steps_final"] > 0 for v in a.values()),
        "every node own replay non-empty": all(v["replay_size_final"] > 0 for v in a.values()),
        "local_update telemetry events on every node": all(v["local_update_events"] > 0 for v in a.values()),
        "backend is torch-cpu": all(v["backend"] == "torch-cpu" for v in a.values()),
    }  # fmt: skip
    if arm == "isolated":  # amendment 2: required only where nothing can equalise the parameters
        checks["four distinct final policy hashes"] = e["A_distinct_policy_hashes"] == 4
    return {"checks": checks, "supported": all(checks.values())}


def decide(res: dict[str, Any]) -> dict[str, Any]:
    p = res["outcomes"]["paired"]
    lower = lambda pair, m: p[pair][m]["ci95"][0] > 0  # noqa: E731
    return {
        "fleet_beats_idle_all_three": all(lower("fleet-idle", m) for m in A.PRIMARY),
        "isolated_beats_idle_all_three": all(lower("isolated-idle", m) for m in A.PRIMARY),
        "fleet_beats_rule_on_ref_return": lower("fleet-rule", "ref_return"),
        "fleet_vs_rule_ref_return": p["fleet-rule"]["ref_return"]["verdict"],
        "fleet_beats_isolated_on_ref_return": lower("fleet-isolated", "ref_return"),
        "fleet_vs_isolated_ref_return": p["fleet-isolated"]["ref_return"]["verdict"],
    }


# --------------------------------------------------------------------------------------- main
def analyze(out: Path, smoke: bool = False) -> dict[str, Any]:
    pre = yaml.safe_load(PREREG.read_text())
    from t30_live import arm_config

    out.mkdir(parents=True, exist_ok=True)
    raws = {a: out / "raw" / a for a in ARMS}
    cfgs = {a: arm_config(pre, a, smoke) for a in ARMS}
    ev = {a: arm_evidence(a, raws[a], pre, cfgs[a]["faults"]) for a in ARMS}
    tables = {a: episode_table(raws[a]) for a in ARMS}
    test_rows = {a: [r for r in tables[a] if r["kind"] == "test"] for a in ARMS}
    seeds = [r["seed"] for r in test_rows["fleet"]]
    assert seeds == [r["seed"] for r in test_rows["isolated"]]
    assert smoke or seeds == list(range(200, 220)), seeds
    test = {**test_rows, **baselines(raws["fleet"], seeds)}
    outcomes = outcome_stats(test)
    prereg_sha = git("log", "-1", "--format=%H", "--", "experiments/prereg/T30.yaml")
    res: dict[str, Any] = {
        "id": "T30", "smoke": smoke, "prereg_commit": prereg_sha, "code_commit": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain", "--", "experiments", "packages", "services")),
        "test_seeds": seeds, "outcomes": outcomes,
        "episode_kinds": {a: {k: sum(r["kind"] == k for r in tables[a]) for k in ("train", "validation", "test")}
                          for a in ARMS},  # fmt: skip
        "run": {a: json.loads((raws[a] / "DONE").read_text()) for a in ARMS},
        "coordinator": {a: {n: v for n, v in json.loads((raws[a] / "run_status.json").read_text())["nodes"].items()}
                        for a in ARMS},  # fmt: skip
        "claims": {},
    }  # fmt: skip
    for a in ARMS:
        res["claims"][a] = {
            "A": claim_a(a, ev[a]) | {"detail": ev[a]["A"], "distinct_hashes": ev[a]["A_distinct_policy_hashes"],
                                      "hash_samples": ev[a]["A_hash_samples"]},  # fmt: skip
            "B": claim_b(a, ev[a]) | {k: ev[a][k] for k in ("B_local_learning_in_cut", "B_decisions", "B_summaries", "B_counters")},
            "C": ev[a]["C"],
        }  # fmt: skip
    res["decisions_D"] = decide(res)
    # ---- files
    rows = [r for a in ARMS for r in ev[a].pop("_rows")]
    with (out / "decisions.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    for a in ARMS:
        ev[a].pop("_records")
    with (out / "curves.csv").open("w", newline="") as f:
        cols = ["arm", "episode", "kind", "seed", "ticks", "ref_return", "coverage_gain", "targets_after_spawn",
                "wall_collisions", "revisit_rate", "live_mean_return", "coverage"]  # fmt: skip
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        for a in ARMS:
            for r in tables[a]:
                w.writerow({"arm": a, **r})
    excerpt = spool_excerpt(raws, rows)
    with (out / "spool_excerpt.jsonl").open("w") as f:
        for x in excerpt:
            f.write(json.dumps(x) + "\n")
    (out / "results.json").write_text(json.dumps(res, indent=1, default=str))
    from t30_summary import write_summary

    write_summary(out, res, ev, tables, pre)
    print(f"wrote {out}/results.json summary.md curves.csv decisions.jsonl spool_excerpt.jsonl")
    return res


def spool_excerpt(raws: dict[str, Path], rows: list[dict]) -> list[dict]:
    """Raw telemetry spool lines (node-local durable files): around the restart boundary of the
    killed node, and around the first cross-cut decision after a cut ended."""
    out: list[dict] = []
    for arm, raw in raws.items():
        kill = json.loads((raw / "kill.json").read_text())
        node = kill["planned"]["node"]
        lines = jl(raw / "node_local" / node / "spool.jsonl.gz")
        boots = [x["event_id"].split("-")[-2] for x in lines]
        for i in range(1, len(lines)):
            if boots[i] != boots[i - 1]:
                for j in range(max(0, i - 4), min(len(lines), i + 4)):
                    out.append(
                        {
                            "arm": arm,
                            "node": node,
                            "why": "restart boundary",
                            "spool_line": j + 1,
                            **lines[j],
                        }
                    )
                break
        first = next(
            (r for r in rows if r["arm"] == arm and r["cross_cut"] and not r["tick_in_cut_window"]),
            None,
        )
        if first is not None:
            lines = jl(raw / "node_local" / first["node"] / "spool.jsonl.gz")
            for j, x in enumerate(lines):
                if x["event_id"] == first["event_id"]:
                    for k in range(max(0, j - 2), min(len(lines), j + 3)):
                        out.append({"arm": arm, "node": first["node"], "why": "first cross-cut decision after a cut",
                                    "spool_line": k + 1, **lines[k]})  # fmt: skip
                    break
    return out

# ruff: noqa: E501  (long prose and table lines)
"""T30 analysis library: outcome metrics from live replays, baselines, bootstrap, partition evidence.

Pure functions (no processes, no network) so tests/experiments/test_t30.py can check them on synthetic
inputs. ``experiments/t30_live.py`` drives the live cluster and calls these on what it recorded.
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (
    "packages/sim",
    "packages/adapters/sim2d",
    "packages/contracts/src",
    "packages/learning",
):
    if (
        str(_ROOT / _p) not in sys.path
    ):  # so `uv run python experiments/t30_live.py` needs no PYTHONPATH
        sys.path.insert(0, str(_ROOT / _p))

import numpy as np  # noqa: E402
from archipelago_contracts.models import RunConfig  # noqa: E402
from archipelago_sim.env import REWARD_EXTRA, REWARD_SPECS, explorer_policy  # noqa: E402
from archipelago_sim2d.adapter import Sim2DAdapter  # noqa: E402
from archipelago_sim2d.smoke import make_action  # noqa: E402

REF_REWARD = "rew-v1"  # the T37 yardstick: rew-v1 components re-scored from environment counters
PRIMARY = ("ref_return", "coverage_gain", "targets_after_spawn")
SECONDARY = ("wall_collisions", "revisit_rate", "ticks")


# ------------------------------------------------------------------------------------ outcomes
def ref_return(world: Any, n_agents: int) -> float:
    """T37 ``ref_return``: rew-v1 re-scored from counters, per agent (experiments/t37.py)."""
    new, tgt, step, coll, _ = REWARD_SPECS[REF_REWARD]
    rev, c = REWARD_EXTRA[REF_REWARD][0], world.counters
    return (
        new * c["new_cells"]
        + rev * c["revisits"]
        + coll * (c["wall_collisions"] + c["agent_collisions"])
        + step * c["agent_ticks"]
        + tgt * world.targets_after_spawn
    ) / n_agents


def world_metrics(world: Any, n_agents: int) -> dict[str, float]:
    c = world.counters
    return {
        "ref_return": ref_return(world, n_agents),
        "coverage_gain": float(world.coverage_gain),
        "targets_after_spawn": float(world.targets_after_spawn),
        "wall_collisions": float(c["wall_collisions"]),
        "revisit_rate": c["revisits"] / max(1, c["agent_ticks"]),
        "ticks": float(world.tick),
    }


def replay_metrics(replay_dir: Path) -> dict[str, float]:
    """Re-execute the actions the live nodes chose (coordinator replay) on a fresh world and score it
    with the T37 reference return. The final state hash must equal the recorded one."""
    manifest = json.loads((replay_dir / "manifest.json").read_text())
    records = [json.loads(x) for x in (replay_dir / "replay.jsonl").read_text().splitlines()]
    cfg = RunConfig.model_validate(manifest["run_config"])
    ad = Sim2DAdapter(**manifest["world_kwargs"])
    ad.reset(cfg)
    for r in records:
        if "removed" in r:
            ad.kill(r["removed"])
            continue
        ad.step({n: make_action(n, r["tick"], c) for n, c in r["actions"].items() if c})
    w = ad.world
    assert w.trace_hash() == manifest["final_state_hash"], f"replay diverged: {replay_dir}"
    return world_metrics(w, len(cfg.nodes))


Policy = Callable[[Any, str, int], str]  # (world, node, tick) -> command name


def idle_policy(_cfg: RunConfig) -> Policy:
    return lambda world, node, tick: "stay"


def rule_policy(cfg: RunConfig) -> Policy:
    """The rule explorer, seeded per (world seed, node) as in experiments/t37.py::rule_act."""
    seed = cfg.seeds["env"]
    rng = {n.node_id: random.Random(f"{seed}-{n.node_id}") for n in cfg.nodes}
    visits: dict[str, dict] = {n.node_id: {} for n in cfg.nodes}
    return lambda world, node, tick: explorer_policy(world.observe(node), visits[node], rng[node])


def play_policy(
    cfg: RunConfig, world_kwargs: dict[str, Any], make_policy: Callable[[RunConfig], Policy]
) -> dict[str, float]:
    """One episode of a scripted policy in the same adapter/world the live coordinator builds."""
    ad = Sim2DAdapter(**world_kwargs)
    ad.reset(cfg)
    w, policy = ad.world, make_policy(cfg)
    while w.agents:
        t = w.tick
        ad.step({n: make_action(n, t, policy(w, n, t)) for n in list(w.agents)})
    return world_metrics(w, len(cfg.nodes))


# ----------------------------------------------------------------------------------- statistics
def paired_bootstrap(diff: Iterable[float], n: int = 4000, seed: int = 0) -> dict[str, Any]:
    """Mean paired difference over worlds with a 95 percent percentile bootstrap CI (worlds are
    resampled). One training run per arm means this CI does not include training-run variance."""
    d = np.asarray(list(diff), float)
    rng = np.random.default_rng(seed)
    means = np.array([d[rng.integers(len(d), size=len(d))].mean() for _ in range(n)])
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {
        "mean_diff": float(d.mean()), "ci95": [float(lo), float(hi)], "n_worlds": int(len(d)),
        "worlds_positive": int((d > 0).sum()), "worlds_negative": int((d < 0).sum()),
    }  # fmt: skip


def verdict(p: dict[str, Any]) -> str:
    lo, hi = p["ci95"]
    return "better" if lo > 0 else "worse" if hi < 0 else "inconclusive"


# ---------------------------------------------------------------------------- partition evidence
_SOURCE = re.compile(r"source=(node-\d+)")


def decision_source(reason: str | None) -> str | None:
    m = _SOURCE.search(reason or "")
    return m.group(1) if m else None


def is_decision(rec: dict[str, Any]) -> bool:
    return rec.get("kind") == "learning_event" and rec.get("transfer") in ("accepted", "rejected")


def cut_active(tick: int, windows: list[dict[str, Any]]) -> bool:
    return any(w["start_tick"] <= tick < w["end_tick"] for w in windows)


def split_decisions(
    records: list[dict[str, Any]],
    halves: dict[str, int],
    windows: list[dict[str, Any]],
    max_ticks: int,
) -> dict[str, Any]:
    """Classify telemetry decisions by whether the offer's sender is across the cut and whether the
    decision tick (episode-relative) lies inside a cut window. ``halves`` maps node -> side; two
    nodes are cut from each other iff ``windows`` is active and they are on different sides (an
    all-isolated control uses distinct sides for every node)."""
    out: dict[str, Any] = {
        "decisions": 0, "accepted": 0, "rejected": 0,
        "cross_inside_cut": [], "cross_outside_cut": 0, "same_side_inside_cut": 0,
        "same_side_outside_cut": 0, "unknown_source": 0, "by_reason": {},
    }  # fmt: skip
    for r in records:
        if not is_decision(r):
            continue
        out["decisions"] += 1
        out[r["transfer"]] += 1
        head = (r.get("reason") or "").split(" (")[0].split(" ")[0]
        key = "accepted" if r["transfer"] == "accepted" else head
        out["by_reason"][key] = out["by_reason"].get(key, 0) + 1
        src, dst = decision_source(r.get("reason")), r["source_node_id"]
        tick = (
            r["sim_tick"] % max_ticks
        )  # 0 = the final window at the episode end (tick == max_ticks)
        inside = cut_active(tick, windows)
        if src is None:
            out["unknown_source"] += 1
        elif halves[src] != halves[dst]:
            if inside:
                out["cross_inside_cut"].append(
                    {"event_id": r["event_id"], "dst": dst, "src": src, "tick": tick}
                )
            else:
                out["cross_outside_cut"] += 1
        else:
            out["same_side_inside_cut" if inside else "same_side_outside_cut"] += 1
    return out


def summary_rx_evidence(
    rx: dict[str, dict[str, dict[str, list[int]]]],
    halves: dict[str, int],
    windows: list[dict[str, Any]],
) -> dict[str, Any]:
    """``rx[node][episode][sender] = receiver ticks at which a visit summary was applied``
    (node status ``summaries.rx_ticks`` with SUMMARY_TRACE=1)."""
    out = {
        "cross_applied_inside_cut": 0, "cross_applied_outside_cut": 0,
        "same_side_applied_inside_cut": 0, "same_side_applied_outside_cut": 0,
    }  # fmt: skip
    for node, per_ep in rx.items():
        for senders in per_ep.values():
            for src, ticks in senders.items():
                cross = halves[src] != halves[node]
                for t in ticks:
                    inside = cut_active(t, windows)
                    out[f"{'cross' if cross else 'same_side'}_applied_{'inside' if inside else 'outside'}_cut"] += 1  # fmt: skip
    return out


def sequence_continuity(records: list[dict[str, Any]], node: str) -> dict[str, Any]:
    """Per-boot sequence ranges of one node from telemetry (event_id = node-boot-seq). A restart
    must continue above everything issued earlier and never reuse an event id."""
    boots: dict[str, list[int]] = {}
    ids: set[str] = set()
    dup = 0
    for r in records:
        if r.get("source_node_id") != node:
            continue
        boot = r["event_id"].split("-")[-2]
        boots.setdefault(boot, []).append(r["sequence"])
        dup += r["event_id"] in ids
        ids.add(r["event_id"])
    order = sorted(boots, key=lambda b: min(boots[b]))
    rows = [{"boot_id": b, "first": min(boots[b]), "last": max(boots[b]), "n": len(boots[b])} for b in order]  # fmt: skip
    overlap = any(rows[i]["last"] >= rows[i + 1]["first"] for i in range(len(rows) - 1))
    return {"boots": rows, "duplicate_event_ids": dup, "ranges_overlap": overlap}

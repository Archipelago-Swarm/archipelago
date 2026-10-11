"""T38 acceptance (2): the coordinator's world runs the versioned reward id the plan selects,
and its per-step reward equals the NumPy harness (experiments/protocol_harness over GridWorld)
for the same recorded action sequences. Also: ids in the manifest, schedule/encoder validation,
old ids unchanged.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

import pytest
from coord_harness import ACTIONS, run_body

ROOT = Path(__file__).resolve().parents[2]
for p in ("experiments", "packages/learning"):
    sys.path.insert(0, str(ROOT / p))

import protocol_harness as H  # noqa: E402
from archipelago_coordinator.models import LEARNER_SCHEDULES  # noqa: E402
from archipelago_sim.env import REWARD_EXTRA, REWARD_SPECS  # noqa: E402
from archipelago_sim.mission import derive_map_seed  # noqa: E402

TICKS = 120
SEEDS = (5, 8, 21)
WORLD = {"size": 16, "n_targets": 8}


def script(seed: int, nodes: tuple[str, ...]) -> dict[str, list[int]]:
    rng = random.Random(f"script-{seed}")
    return {n: [rng.randrange(5) for _ in range(TICKS)] for n in nodes}


def harness_rewards(seed: int, reward_id: str, seqs: dict[str, list[int]]):
    """Per-step rewards (and world counters) of the NumPy-harness world for a recorded script.
    The coordinator derives each episode map from (env seed, episode index); episode 0 here."""
    env = H.make_env(H.OBS_ID, reward_id)
    nodes = sorted(seqs)
    env.reset(seed=derive_map_seed(seed, 0), options={"starts": {n: (i, 0) for i, n in enumerate(nodes)}})
    out: dict[str, list[float]] = {n: [] for n in nodes}
    t = 0
    while env.agents and t < TICKS:
        _, rew, *_ = env.step({a: seqs[a][t] for a in env.agents})
        for a, r in rew.items():
            out[a].append(r)
        t += 1
    return out, dict(env.world.counters), env.world.targets_after_spawn


def coordinator_rewards(live, nodes, run_id: str, seed: int, reward_id: str | None, seqs):
    plan: dict[str, Any] = {"battery_scale": 1.0}
    if reward_id:
        plan["reward_id"] = reward_id
    body = run_body(run_id, nodes, ticks=TICKS, seed=seed, **plan)
    for f in nodes.values():
        f.policy = lambda node, ep, tick, obs, seqs=seqs: ACTIONS[seqs[node][tick]]
    live.start_run(body)
    status = live.wait_done(run_id)
    got = {n: [fb["reward"] for fb in f_.feedback] for n, f_ in nodes.items()}
    return status, got


@pytest.mark.parametrize("seed", SEEDS)
def test_coordinator_rew_v1_equals_the_numpy_harness_step_by_step(live, nodes, seed):
    lv = live(world_kwargs=WORLD)
    ns = nodes(2)
    seqs = script(seed, tuple(sorted(ns)))
    status, got = coordinator_rewards(lv, ns, f"rw-v1-{seed}", seed, "rew-v1", seqs)
    want, counters, found = harness_rewards(seed, "rew-v1", seqs)
    assert status["ids"]["reward_id"] == "rew-v1" and status["ids"]["reward_source"] == "plan"
    assert got == want, "per-step reward differs between the coordinator world and the harness"
    assert sum(len(v) for v in got.values()) > 2 * 40
    # the reward components themselves: each step's reward is a sum of the rew-v1 constants
    new, tgt, step, coll, inval = REWARD_SPECS["rew-v1"]
    revisit = REWARD_EXTRA["rew-v1"][0]
    total = sum(sum(v) for v in got.values())
    expected = (
        step * counters["agent_ticks"]
        + new * counters["new_cells"]
        + revisit * counters["revisits"]
        + coll * (counters["wall_collisions"] + counters["agent_collisions"])
        + tgt * found
    )
    assert total == pytest.approx(expected, abs=1e-9)
    assert counters["revisits"] > 0 and counters["wall_collisions"] + counters["new_cells"] > 0


def test_rew_v1_is_a_different_reward_from_rew_v0_on_the_same_actions(live, nodes):
    seqs = script(5, ("node-0", "node-1"))
    v1, _, _ = harness_rewards(5, "rew-v1", seqs)
    v0, _, _ = harness_rewards(5, "rew-v0", seqs)
    assert v1 != v0


def test_old_reward_id_still_runs_unchanged_when_the_plan_selects_nothing(live, nodes):
    lv = live(world_kwargs=WORLD)
    ns = nodes(2)
    seqs = script(8, tuple(sorted(ns)))
    status, got = coordinator_rewards(lv, ns, "rw-v0", 8, None, seqs)
    want, *_ = harness_rewards(8, "rew-v0", seqs)
    assert got == want
    assert status["ids"]["reward_id"] == "rew-v0" and status["ids"]["reward_source"] == "run_config"
    assert status["ids"]["learner_schedule_id"] == "sched-v0"


def test_manifest_on_disk_records_the_ids(live, nodes):
    lv = live(world_kwargs=WORLD)
    ns = nodes(2)
    body = run_body(
        "ids-manifest", ns, ticks=10,
        reward_id="rew-v1",
        node_config={"encoder_id": "grid-flat-v2-visits-shared",
                     "learner_schedule_id": "sched-t37-v1"},
    )  # fmt: skip
    lv.start_run(body)
    lv.wait_done("ids-manifest")
    doc = json.loads((lv.settings.data_dir / "runs" / "ids-manifest" / "manifest.json").read_text())
    assert doc["ids"] == {
        "reward_id": "rew-v1", "reward_source": "plan",
        "encoder_id": "grid-flat-v2-visits-shared-s16-r2",
        "learner_schedule_id": "sched-t37-v1",
    }  # fmt: skip
    assert doc["run_config"]["reward_id"] == "rew-v1"
    # every node was configured with the same resolved ids, the registered recipe and the
    # per-training-episode epsilon span
    for f in ns.values():
        cfg = next(c for c in f.controls if c["command"] == "configure")
        assert cfg["encoder_id"] == "grid-flat-v2-visits-shared-s16-r2"
        assert cfg["learner_schedule_id"] == "sched-t37-v1"
        assert cfg["world_config"]["reward_id"] == "rew-v1"
        reg = LEARNER_SCHEDULES["sched-t37-v1"]
        assert cfg["hyperparameters"]["lr"] == reg["lr"] == 1e-3
        assert cfg["hyperparameters"]["capacity"] == 50000 and cfg["hyperparameters"]["double_dqn"]
        assert cfg["epsilon_schedule"] == {"start": 1.0, "end": 0.05, "decay_episodes": 1}
    assert not any(f.violations for f in ns.values()), [f.violations for f in ns.values()]


def test_decay_span_is_half_of_the_training_episodes(live, nodes):
    lv = live(world_kwargs=WORLD)
    ns = nodes(2)
    eps = [{"kind": "train", "seed": 1, "count": 5}, {"kind": "validation", "seed": 900}]
    body = run_body(
        "decay", ns, ticks=5, episodes=eps,
        node_config={"learner_schedule_id": "sched-t37-v1"},
    )  # fmt: skip
    lv.start_run(body)
    lv.wait_done("decay")
    cfg = next(c for c in ns["node-0"].controls if c["command"] == "configure")
    assert cfg["epsilon_schedule"]["decay_episodes"] == 3  # ceil(0.5 * 5 training episodes)


@pytest.mark.parametrize(
    ("plan", "needle"),
    [
        ({"reward_id": "rew-nope"}, "unknown reward_id"),
        ({"node_config": {"learner_schedule_id": "sched-nope"}}, "unknown learner_schedule_id"),
        (
            {"node_config": {"learner_schedule_id": "sched-t37-v1",
                             "hyperparameters": {"lr": 0.01}}},
            "requires lr",
        ),
        ({"node_config": {"hyperparameters": {"double_dqn": True}}}, "double_dqn needs"),
        ({"node_config": {"encoder_id": "grid-flat-v9"}}, "unknown encoder_id"),
        ({"node_config": {"encoder_id": "grid-flat-v1-s9-r2"}}, "does not match the live world"),
    ],
)  # fmt: skip
def test_bad_versioned_ids_are_refused_before_anything_starts(live, nodes, plan, needle):
    lv = live(world_kwargs=WORLD)
    ns = nodes(2)
    body = run_body("bad-ids", ns, ticks=5, **plan)
    code, out = lv.call("POST", "/v1/runs", body)
    assert code == 422 and needle in str(out), (code, out)
    assert all(not f.controls for f in ns.values()), "nothing may reach a node"


def test_run_request_cannot_contradict_the_plan_reward(live, nodes):
    lv = live(world_kwargs=WORLD)
    ns = nodes(2)
    body = run_body("conflict", ns, ticks=5, reward_id="rew-v0")
    body["run_config"]["reward_id"] = "rew-v1"  # a non-default id that disagrees with the plan
    code, out = lv.call("POST", "/v1/runs", body)
    assert code == 422 and "contradicts" in str(out), (code, out)
    assert all(not f.controls for f in ns.values())


def test_the_legacy_default_in_the_run_config_is_upgraded_by_the_plan(live, nodes):
    lv = live(world_kwargs=WORLD)
    ns = nodes(2)
    body = run_body("upgrade", ns, ticks=5, reward_id="rew-v1")
    assert body["run_config"]["reward_id"] == "rew-v0"
    lv.start_run(body)
    st = lv.wait_done("upgrade")
    assert st["ids"]["reward_id"] == "rew-v1"
    cfg = next(c for c in ns["node-0"].controls if c["command"] == "configure")
    assert cfg["world_config"]["reward_id"] == "rew-v1"


def test_registry_mirror_matches_the_learning_package():
    from archipelago_learning import schedules

    assert set(LEARNER_SCHEDULES) == set(schedules.SCHEDULES)
    for sid, mine in LEARNER_SCHEDULES.items():
        theirs = schedules.SCHEDULES[sid]
        assert mine == {k: v for k, v in vars(theirs).items() if k != "id"}, sid


def test_sha_of_reward_spec_is_pinned():
    """rew-v1 constants are part of the id: changing them must change the id, not the meaning."""
    spec = repr((REWARD_SPECS["rew-v1"], REWARD_EXTRA["rew-v1"]))
    assert (
        hashlib.sha256(spec.encode()).hexdigest()[:12]
        == hashlib.sha256(
            repr(((0.5, 5.0, -0.01, -2.0, -0.1), (-0.25, False))).encode()
        ).hexdigest()[:12]
    )

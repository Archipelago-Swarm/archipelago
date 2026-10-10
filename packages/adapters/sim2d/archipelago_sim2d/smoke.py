"""Build contract records and run the explorer loop; shared by the CLI and tests."""

from __future__ import annotations

import random
from datetime import timedelta

from archipelago_contracts.models import SCHEMA_VERSION, Action, RunConfig
from archipelago_sim.env import explorer_policy

from .adapter import EPOCH, Sim2DAdapter


def make_config(seed: int, ticks: int, n: int = 4) -> RunConfig:
    return RunConfig(
        schema_version=SCHEMA_VERSION, run_id=f"sim2d-{seed}", simulator="sim2d",
        simulator_version="0.1.0", scenario_hash="0" * 64,
        seeds={"env": seed, "topology": 0, "learner": 0, "exploration": 0},
        nodes=[{"node_id": f"node-{i}", "start_pose": {"x": 0, "y": 0}} for i in range(n)],
        observation_id="obs-v0", action_id="act-v0", reward_id="rew-v0", mode="lockstep",
        learner="none", budgets={"max_ticks": ticks, "max_wall_seconds": 600})


def make_action(node: str, tick: int, command: str) -> Action:
    return Action(schema_version=SCHEMA_VERSION, event_id=f"a-{node}-{tick}", run_id="sim2d",
                  source_node_id=node, sim_tick=tick, emitted_at_utc=EPOCH + timedelta(seconds=tick),
                  sequence=tick, action_space_version="act-v0", command=command, policy_version=0)


def run_explorer(seed: int, ticks: int, n: int = 4, silent: frozenset[str] = frozenset()):
    """Run to termination; nodes in `silent` never send actions (node timeout)."""
    ad = Sim2DAdapter()
    obs = ad.reset(make_config(seed, ticks, n))
    rng, visits, t = random.Random(seed), {k: {} for k in obs}, 0
    while obs:
        acts = {k: make_action(k, t, explorer_policy(
            {"pose": (int(o.pose.x), int(o.pose.y)), "crop": o.crop}, visits[k], rng))
            for k, o in obs.items() if k not in silent}
        t += 1
        obs = {k: o for k, o in ad.step(acts).observations.items() if k in ad.world.agents}
    return ad

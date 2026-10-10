"""SimulatorAdapter over GridWorld: maps contract Action/Observation/WorldSnapshot records."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from archipelago_contracts.adapter import SimulatorCapabilities, StepResult
from archipelago_contracts.models import (
    SCHEMA_VERSION,
    Action,
    Observation,
    Pose,
    RunConfig,
    Topology,
    WorldSnapshot,
)
from archipelago_sim.env import GridWorld

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)  # deterministic stamps keep replays byte-identical


class Sim2DAdapter:
    def __init__(self, **world_kwargs) -> None:
        self.kw = world_kwargs
        self.world: GridWorld | None = None
        self.replay: list[dict] = []
        self._seq = 0
        self._run_id = ""

    def capabilities(self) -> SimulatorCapabilities:
        return SimulatorCapabilities("sim2d", "2d", "act-v0")

    def _meta(self, node: str | None, kind: str) -> dict:
        self._seq += 1
        t = self.world.tick  # type: ignore[union-attr]
        return {
            "schema_version": SCHEMA_VERSION,
            "event_id": f"{kind}-{self._seq}",
            "run_id": self._run_id,
            "source_node_id": node,
            "sim_tick": t,
            "emitted_at_utc": EPOCH + timedelta(seconds=t),
            "sequence": self._seq,
        }

    def _obs(self, node: str, o: dict) -> Observation:
        x, y = o["pose"]
        return Observation(
            **self._meta(node, "obs"),
            crop=o["crop"],
            known_mask=o["known_mask"],
            pose=Pose(x=x + 0.5, y=y + 0.5),
            battery=o["battery"],
            visible_markers=[(a + 0.5, b + 0.5) for a, b in o["visible_markers"]],
        )

    def reset(self, config: RunConfig) -> dict[str, Observation]:
        nodes = sorted(n.node_id for n in config.nodes)
        self.world = GridWorld(
            n_agents=len(nodes),
            max_ticks=config.budgets.max_ticks,
            **{"reward_id": config.reward_id, **self.kw},
        )
        self.world.possible_agents = nodes  # contract node ids replace default names
        self._run_id, self._seq, self.replay, self._cfg = config.run_id, 0, [], config
        starts = {n.node_id: (int(n.start_pose.x), int(n.start_pose.y)) for n in config.nodes}
        if len(set(starts.values())) != len(starts):
            raise ValueError("node start poses must be distinct")
        if any(
            not (0 <= x < self.world.size and 0 <= y < self.world.size) for x, y in starts.values()
        ):
            raise ValueError("node start poses must be inside the grid")
        raw = self.world.reset(seed=config.seeds["env"], starts=starts)
        return {n: self._obs(n, o) for n, o in raw.items()}

    def step(self, actions: dict[str, Action]) -> StepResult:
        w = self.world
        if w is None:
            raise RuntimeError("reset() first")
        cmds = {n: a.command for n, a in actions.items() if n in w.agents}
        n_events = len(w.events)
        obs, rew, term, trunc, info = w.step(cmds)
        self.replay.append(
            {
                "tick": w.tick,
                "actions": {n: cmds.get(n) for n in w.possible_agents},
                "events": w.events[n_events:],
                "state_hash": w.trace_hash(),
            }
        )
        return StepResult({n: self._obs(n, o) for n, o in obs.items()}, rew, term, trunc, info)

    def snapshot(self) -> WorldSnapshot:
        s = self.world.world_state()  # type: ignore[union-attr]
        poses = {n: Pose(x=p[0] + 0.5, y=p[1] + 0.5) for n, p in s["poses"].items()}
        return WorldSnapshot(
            **self._meta(None, "snap"),
            run_status="running" if self.world.agents else "completed",  # type: ignore[union-attr]
            poses=poses,
            obstacles=[tuple(o) for o in s["obstacles"]],
            coverage=s["coverage"],
            topology=Topology(links=[]),
        )

    def write_replay(self, out: Path) -> Path:
        """Write replay.jsonl + manifest.json (seed, hashes); return the manifest path."""
        out.mkdir(parents=True, exist_ok=True)
        body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in self.replay)
        (out / "replay.jsonl").write_text(body)
        manifest = {
            "run_id": self._run_id,
            "seed": self._cfg.seeds["env"],
            "simulator_version": self._cfg.simulator_version,
            "world_kwargs": self.kw,
            "ticks": len(self.replay),
            "final_state_hash": self.world.trace_hash(),  # type: ignore[union-attr]
            "replay_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "config_hash": hashlib.sha256(self._cfg.model_dump_json().encode()).hexdigest(),
        }
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
        return out / "manifest.json"

    def close(self) -> None:
        self.world = None


def replay_final_hash(config: RunConfig, records: list[dict], **world_kwargs) -> str:
    """Re-execute recorded actions on a fresh world; return its final state hash."""
    from .smoke import make_action  # local: smoke imports this module

    ad = Sim2DAdapter(**world_kwargs)
    ad.reset(config)
    for r in records:
        ad.step({n: make_action(n, r["tick"], c) for n, c in r["actions"].items() if c})
    return ad.world.trace_hash()  # type: ignore[union-attr]

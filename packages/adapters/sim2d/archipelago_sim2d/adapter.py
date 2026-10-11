"""SimulatorAdapter over GridWorld: maps contract Action/Observation/WorldSnapshot records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from archipelago_contracts.adapter import SimulatorCapabilities, StepResult
from archipelago_contracts.models import (
    SCHEMA_VERSION,
    Action,
    Observation,
    Pose,
    RunConfig,
    Topology,
    WorldGeometry,
    WorldSnapshot,
)
from archipelago_sim.env import WALL, GridWorld
from archipelago_sim.flight import FlightWorld

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)  # fixture timestamps for hand-built actions (smoke)


class Sim2DAdapter:
    def __init__(self, **world_kwargs) -> None:
        self.kw = world_kwargs  # includes environment_mode (legacy_grid | continuous_flight)
        self.mode = world_kwargs.get("environment_mode", "legacy_grid")
        if self.mode not in ("legacy_grid", "continuous_flight"):
            raise ValueError(f"unknown environment_mode {self.mode!r}")
        self.world: GridWorld | FlightWorld | None = None
        self.replay: list[dict] = []
        self._seq = 0
        self._run_id = ""
        self._tick_base = 0
        self._vanished_known: dict[tuple[int, int], int] = {}  # cells known to killed drones

    def capabilities(self) -> SimulatorCapabilities:
        return SimulatorCapabilities("sim2d", "2d", "act-v0")

    def _meta(self, node: str | None, kind: str) -> dict:
        self._seq += 1
        # sim_tick is simulation time (global across episodes); emitted_at_utc is wall time and
        # the two are never mixed. Ids are unique because every episode has its own run_id suffix.
        return {
            "schema_version": SCHEMA_VERSION,
            "event_id": f"{kind}-{self._seq}",
            "run_id": self._run_id,
            "source_node_id": node,
            "sim_tick": self._tick_base + self.world.tick,  # type: ignore[union-attr]
            "emitted_at_utc": datetime.now(UTC),
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

    def reset(self, config: RunConfig, episode: int = 0) -> dict[str, Observation]:
        """Start an episode. `episode` offsets sim_tick so it is the global index
        `episode * max_ticks + tick`; give each episode its own run_id suffix and env seed."""
        nodes = sorted(n.node_id for n in config.nodes)
        kw = {k: v for k, v in self.kw.items() if k != "environment_mode"}
        cls = FlightWorld if self.mode == "continuous_flight" else GridWorld
        self.world = cls(
            n_agents=len(nodes),
            max_ticks=config.budgets.max_ticks,
            **{"reward_id": config.reward_id, **kw},
        )
        self.world.possible_agents = nodes  # contract node ids replace default names
        self._run_id, self._seq, self.replay, self._cfg = config.run_id, 0, [], config
        self._tick_base = episode * config.budgets.max_ticks
        self._vanished_known = {}
        starts = {n.node_id: (int(n.start_pose.x), int(n.start_pose.y)) for n in config.nodes}
        if len(set(starts.values())) != len(starts):
            raise ValueError("node start poses must be distinct")
        if any(
            not (0 <= x < self.world.size and 0 <= y < self.world.height)
            for x, y in starts.values()
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

    def kill(self, node: str) -> None:
        """Remove a live drone from the world entirely: it vanishes (no body, no wreck).

        Same semantics as `archipelago_learning.rollout.reset(drop=...)` (the drone leaves
        `drones` and `agents`, so it neither acts, collides nor blocks a cell, and is absent from
        snapshot poses), but usable mid-episode for the coordinator's kill_node scenario. It differs
        from battery death, where the wreck stays in `drones` and blocks its cell. What the drone
        had discovered stays publicly discovered. The removal is recorded in the replay (record
        with a `removed` key and no `actions`) so re-execution reproduces it.
        """
        w = self.world
        if w is None:
            raise RuntimeError("reset() first")
        if node not in w.agents:
            raise ValueError(f"{node!r} is not a live node")
        self._vanished_known.update(w.drones[node].known)
        del w.drones[node]
        w.agents.remove(node)
        self.replay.append({"tick": w.tick, "removed": node, "state_hash": w.trace_hash()})

    def _known_cells(self) -> set[tuple[int, int]]:
        known = set(self._vanished_known)
        for d in self.world.drones.values():  # type: ignore[union-attr]
            known.update(d.known)
        return known

    def discovered_obstacles(self) -> list[tuple[int, int]]:
        """Obstacles in the union of the nodes' discovered cells (what the fleet itself knows)."""
        w = self.world
        known = dict(self._vanished_known)
        for d in w.drones.values():  # type: ignore[union-attr]
            known.update(d.known)
        return sorted(c for c, v in known.items() if v == WALL and c in w.obstacles)  # type: ignore[union-attr]

    def _snapshot(
        self, obstacles: list[tuple[int, int]], links: Iterable[tuple[str, str]]
    ) -> WorldSnapshot:
        s = self.world.world_state()  # type: ignore[union-attr]
        poses = {n: Pose(x=p[0] + 0.5, y=p[1] + 0.5) for n, p in s["poses"].items()}
        geometry = None
        if isinstance(
            self.world, FlightWorld
        ):  # continuous flight: poses in meters, grid stays hidden
            w = self.world
            poses = {
                n: Pose(x=f["x"], y=f["y"], heading_rad=f["heading"], speed_mps=f["speed"])
                for n, f in w.poses_m().items()
            }
            cm = w.cell_m
            geometry = WorldGeometry(
                width_m=w.width_m,
                height_m=w.height_m,
                cell_m=cm,
                sensor_radius_m=w.sensor_radius_m,
                shapes=w.revealed_shapes(set(obstacles)),
                terrain=w.terrain_grid(self._known_cells()),
                targets_found=[
                    {"x": (t[0] + 0.5) * cm, "y": (t[1] + 0.5) * cm, "radius": cm / 2}
                    for t in s["found"]
                ],
            )
            obstacles = []  # polygons in `world.shapes` replace the cell list
        return WorldSnapshot(
            **self._meta(None, "snap"),
            run_status="running" if self.world.agents else "completed",  # type: ignore[union-attr]
            poses=poses,
            obstacles=obstacles,
            coverage=s["coverage"],
            topology=Topology(links=list(links)),
            world=geometry,
        )

    def snapshot(self, links: Iterable[tuple[str, str]] = ()) -> WorldSnapshot:
        """Privileged: every obstacle, hidden ones included. Never publish or send to a node."""
        s = self.world.world_state()  # type: ignore[union-attr]
        return self._snapshot([tuple(o) for o in s["obstacles"]], links)  # type: ignore[misc]

    def public_snapshot(self, links: Iterable[tuple[str, str]] = ()) -> WorldSnapshot:
        """Public view: poses, coverage, links and only the obstacles some node has discovered."""
        return self._snapshot(self.discovered_obstacles(), links)

    def privileged_extras(self) -> dict:
        """Hidden state that has no place in the contract snapshot: targets, found, battery."""
        s = self.world.world_state()  # type: ignore[union-attr]
        return {
            "targets": [list(t) for t in s["targets"]],
            "found": [list(t) for t in s["found"]],
            "battery": s["battery"],
        }

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
            "ticks": sum("actions" in r for r in self.replay),
            "removed_nodes": [r["removed"] for r in self.replay if "removed" in r],
            "run_config": self._cfg.model_dump(mode="json"),
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
        if "removed" in r:
            ad.kill(r["removed"])
            continue
        ad.step({n: make_action(n, r["tick"], c) for n, c in r["actions"].items() if c})
    return ad.world.trace_hash()  # type: ignore[union-attr]


def replay_final_hash_from_dir(out: Path) -> str:
    """Re-execute a written replay (replay.jsonl + manifest.json) and return its final hash."""
    manifest = json.loads((out / "manifest.json").read_text())
    records = [json.loads(x) for x in (out / "replay.jsonl").read_text().splitlines()]
    cfg = RunConfig.model_validate(manifest["run_config"])
    return replay_final_hash(cfg, records, **manifest["world_kwargs"])

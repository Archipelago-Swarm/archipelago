"""Headless SimulatorAdapter on gym-pybullet-drones (CF2X rotor dynamics, DSLPIDControl).

Upstream pinned in requirements.txt. Contract Pose pins z to 0, so true 3D poses are exposed
via poses3d() until the contract allows z.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
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

ACTION_SPACE = "act3d-v0"
ENCODER = "drone3d-v0"  # distinct from the 2D "grid-flat-v0" so peer model updates are rejected
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
HOVER_Z, SPEED, RADIUS, SUBSTEPS = 1.0, 1.0, 0.05, 24  # m, m/s, m, 240Hz physics per 0.1s tick
DIRS = {"stay": (0, 0), "north": (0, 1), "east": (1, 0), "south": (0, -1), "west": (-1, 0)}


class PyBullet3DAdapter:
    def __init__(self) -> None:
        self.env = None
        self.bodies: dict[str, int] = {}
        self.collisions = 0
        self.target_z = HOVER_Z
        self._tick = self._seq = 0
        self._run_id = ""

    def capabilities(self) -> SimulatorCapabilities:
        return SimulatorCapabilities("pybullet", "3d", ACTION_SPACE, supports_substeps=True)

    def _meta(self, node: str | None, kind: str) -> dict:
        self._seq += 1
        return {
            "schema_version": SCHEMA_VERSION,
            "event_id": f"{kind}-{self._seq}",
            "run_id": self._run_id,
            "source_node_id": node,
            "sim_tick": self._tick,
            "emitted_at_utc": EPOCH + timedelta(seconds=self._tick),
            "sequence": self._seq,
        }

    # Action.command is a fixed 2D literal: takeoff/land are adapter-level, not contract commands.
    def takeoff(self) -> None:
        self.target_z = HOVER_Z

    def land(self) -> None:
        self.target_z = RADIUS

    def poses3d(self) -> dict[str, tuple[float, float, float]]:
        return {
            n: tuple(float(v) for v in self.env._getDroneStateVector(i)[:3])
            for i, n in enumerate(self.bodies)
        }

    def _obs(self, node: str) -> Observation:
        x, y, _ = self.poses3d()[node]
        return Observation(
            **self._meta(node, "obs"),
            crop=[[0]],
            known_mask=[[True]],
            pose=Pose(x=x, y=y),
            battery=1.0,
            visible_markers=[],
        )

    def reset(self, config: RunConfig) -> dict[str, Observation]:
        from gym_pybullet_drones.control.DSLPIDControl import DSLPIDControl
        from gym_pybullet_drones.envs.CtrlAviary import CtrlAviary
        from gym_pybullet_drones.utils.enums import DroneModel

        self.close()
        if not 2 <= len(config.nodes) <= 4:
            raise ValueError("3D adapter supports 2-4 drones")
        nodes = sorted(config.nodes, key=lambda n: n.node_id)
        self.env = CtrlAviary(  # gui=False: DIRECT physics, a viewer would not count
            drone_model=DroneModel.CF2X,
            num_drones=len(nodes),
            initial_xyzs=np.array([(n.start_pose.x, n.start_pose.y, HOVER_Z) for n in nodes]),
            pyb_freq=240,
            ctrl_freq=240,
            gui=False,
        )
        self.ctrl = [DSLPIDControl(DroneModel.CF2X) for _ in nodes]
        self.bodies = {n.node_id: int(i) for n, i in zip(nodes, self.env.DRONE_IDS, strict=True)}
        self._run_id, self._tick, self._seq, self.collisions = config.run_id, 0, 0, 0
        self.target_z = HOVER_Z
        return {n: self._obs(n) for n in self.bodies}

    def step(self, actions: dict[str, Action]) -> StepResult:
        import pybullet as p

        if self.env is None:
            raise RuntimeError("reset() first")
        ids, cid = list(self.bodies.values()), self.env.getPyBulletClient()
        rpm = np.zeros((len(ids), 4))
        for _ in range(SUBSTEPS):
            for i, n in enumerate(self.bodies):
                s = self.env._getDroneStateVector(i)
                a = actions.get(n)
                dx, dy = DIRS[a.command] if a else (0, 0)
                vel = np.array([dx * SPEED, dy * SPEED, 0.0])
                target = np.array([s[0], s[1], self.target_z]) + vel * 0.1  # 0.1 s lookahead
                rpm[i], _, _ = self.ctrl[i].computeControl(
                    1 / 240, s[0:3], s[3:7], s[10:13], s[13:16], target, target_vel=vel
                )
            self.env.step(rpm)
            # drone-drone contacts only; the ground plane is not a collision metric
            self.collisions += sum(
                bool(p.getContactPoints(a, b, physicsClientId=cid))
                for i, a in enumerate(ids)
                for b in ids[i + 1 :]
            )
        self._tick += 1
        nodes = list(self.bodies)
        return StepResult(
            {n: self._obs(n) for n in nodes},
            {n: 0.0 for n in nodes},
            {n: False for n in nodes},
            {n: False for n in nodes},
            {n: {"collisions": str(self.collisions)} for n in nodes},
        )

    def snapshot(self) -> WorldSnapshot:
        return WorldSnapshot(
            **self._meta(None, "snap"),
            run_status="running",
            poses={n: Pose(x=x, y=y) for n, (x, y, _) in self.poses3d().items()},
            obstacles=[],
            coverage=0.0,
            topology=Topology(links=[]),
        )

    def close(self) -> None:
        if self.env is not None:
            self.env.close()
        self.env, self.bodies = None, {}

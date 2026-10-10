"""Headless PyBullet SimulatorAdapter: 2-4 point-mass drones with real rigid-body collisions.

Not yet gym-pybullet-drones (rotor dynamics/controllers); see agents/handoffs/T12/LATEST.md.
Contract Pose pins z to 0, so true 3D poses are exposed via poses3d() until the contract allows z.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
HOVER_Z, SPEED, RADIUS, SUBSTEPS = 1.0, 1.0, 0.1, 24  # m, m/s, m, 240Hz physics per 0.1s tick
DIRS = {"stay": (0, 0), "north": (0, 1), "east": (1, 0), "south": (0, -1), "west": (-1, 0)}


class PyBullet3DAdapter:
    def __init__(self) -> None:
        self.cid: int | None = None
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
        import pybullet as p

        return {
            n: tuple(p.getBasePositionAndOrientation(b, physicsClientId=self.cid)[0])
            for n, b in self.bodies.items()
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
        import pybullet as p

        self.close()
        if not 2 <= len(config.nodes) <= 4:
            raise ValueError("3D adapter supports 2-4 drones")
        self.cid = p.connect(p.DIRECT)  # headless
        p.setGravity(0, 0, 0, physicsClientId=self.cid)  # hover controller replaces lift
        p.setTimeStep(1 / 240, physicsClientId=self.cid)
        ground = p.createCollisionShape(p.GEOM_PLANE, physicsClientId=self.cid)
        p.createMultiBody(0, ground, physicsClientId=self.cid)
        shape = p.createCollisionShape(p.GEOM_SPHERE, radius=RADIUS, physicsClientId=self.cid)
        self.bodies = {
            n.node_id: p.createMultiBody(
                1.0,
                shape,
                basePosition=(n.start_pose.x, n.start_pose.y, HOVER_Z),
                physicsClientId=self.cid,
            )
            for n in sorted(config.nodes, key=lambda n: n.node_id)
        }
        self._run_id, self._tick, self._seq, self.collisions = config.run_id, 0, 0, 0
        self.target_z = HOVER_Z
        return {n: self._obs(n) for n in self.bodies}

    def step(self, actions: dict[str, Action]) -> StepResult:
        import pybullet as p

        if self.cid is None:
            raise RuntimeError("reset() first")
        ids = list(self.bodies.values())
        for _ in range(SUBSTEPS):
            z = {n: pos[2] for n, pos in self.poses3d().items()}
            for n, b in self.bodies.items():
                a = actions.get(n)
                dx, dy = DIRS[a.command] if a else (0, 0)
                vz = max(-SPEED, min(SPEED, 5 * (self.target_z - z[n])))
                p.resetBaseVelocity(b, (dx * SPEED, dy * SPEED, vz), physicsClientId=self.cid)
            p.stepSimulation(physicsClientId=self.cid)
            # drone-drone contacts only; the ground plane is not a collision metric
            self.collisions += sum(
                bool(p.getContactPoints(a, b, physicsClientId=self.cid))
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
        if self.cid is not None:
            import pybullet as p

            p.disconnect(physicsClientId=self.cid)
        self.cid, self.bodies = None, {}

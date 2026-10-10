# PyBullet 3D adapter (T12 prototype)

Separately packaged; core 2D code, CI and deployment never import or install it.

## Run
```
pip install -r packages/adapters/pybullet/requirements.txt   # pybullet only, Python 3.11-3.14 wheels vary
PYTHONPATH="packages/adapters/pybullet:packages/contracts/src" python -m archipelago_pybullet.smoke
python -m pytest tests/adapters3d -q
```
Evidence: `evidence/smoke.json` (10 ticks, 2 drones, hover z=1.0, 0 collisions; pybullet API 202010061).

## Upstream
Target: https://github.com/utiasDSL/gym-pybullet-drones at `7ebad1ecabd28a7000add2d05f888aa2e837c2cc`
(HEAD on 2026-10-10), MIT license (checked LICENSE at that SHA). **Not yet integrated**: the adapter is
a PyBullet point-mass sphere with a P-controller on altitude, not upstream rotor dynamics/controllers.
Swapping in upstream (and takeoff/land) is open work.

## Physics only
The adapter connects with `p.DIRECT` (no GUI); a viewer would not count as simulation. Collision
metric = drone-drone rigid-body contacts per substep (`info["collisions"]`).

## Retraining / changes vs 2D
- Encoder `drone3d-v0`, action space `act3d-v0`; 2D models (`grid-flat-v0`) are rejected by peers and vice versa.
- Dynamics: continuous 3D, 240 Hz, 0.1 s tick, 1 m/s, hover at z=1 m. Observations are not grid crops;
  a 3D policy must be retrained from scratch.
- Contract gap: `Pose.z` is pinned to 0, so z is only available via `poses3d()`; needs an ADR.
- Later route: Gazebo/PX4 via the same `SimulatorAdapter` interface, replacing the physics core only.

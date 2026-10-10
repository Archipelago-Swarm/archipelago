# PyBullet 3D adapter (T12)

Separately packaged; core 2D code, CI and deployment never import or install it.

## Run
```
pip install -r packages/adapters/pybullet/requirements.txt   # pinned gym-pybullet-drones + pybullet
PYTHONPATH="packages/adapters/pybullet:packages/contracts/src" python -m archipelago_pybullet.smoke  # rewrites evidence/smoke.json
python -m pytest tests/adapters3d -q
```
Evidence: `evidence/smoke.json` (10 ticks east at 1 m/s, 2 drones, hover z~1.0, 0 collisions). A test reruns it and compares.

## Upstream (used, not just a target)
https://github.com/utiasDSL/gym-pybullet-drones at `7ebad1ecabd28a7000add2d05f888aa2e837c2cc`
(`git ls-remote` HEAD, 2026-10-10), MIT license (LICENSE fetched at that SHA). The adapter runs
upstream `CtrlAviary` (CF2X rotor/thrust physics, headless) and drives it with upstream `DSLPIDControl`
(position/velocity targets from the five contract commands; takeoff/land = altitude target via `takeoff()`/`land()`).
Extra imports of upstream (gymnasium, scipy, pillow, matplotlib, transforms3d) are listed in requirements.txt.

## Physics only
The adapter builds `CtrlAviary(gui=False)` (PyBullet DIRECT); a viewer would not count as simulation. Collision
metric = drone-drone rigid-body contacts per substep (`info["collisions"]`).

## Retraining / changes vs 2D
- Encoder `drone3d-v0`, action space `act3d-v0`; 2D models (`grid-flat-v0`) are rejected by peers and vice versa.
- Dynamics: CF2X quadrotor rotor model, 240 Hz, 0.1 s tick, 1 m/s, hover at z=1 m. Observations are not grid crops;
  a 3D policy must be retrained from scratch.
- Contract gap: `Pose.z` is pinned to 0, so z is only available via `poses3d()`; needs an ADR.
- Later route: Gazebo/PX4 via the same `SimulatorAdapter` interface, replacing the physics core only.
  **Documentation only: no Gazebo/PX4 code exists in this slice.**

## Known gaps (need integrator action, outside T12 paths)
- `Pose.z` is pinned to 0 in the shared contract: Observation/Snapshot carry x,y only; z is adapter-only (`poses3d()`).
- `Action.command` is a fixed literal: takeoff/land are adapter methods (`takeoff()`/`land()`), not contract commands.
- The repo `.venv` lacks pybullet/upstream, so flight tests skip in `scripts/check.sh`; only the saved-evidence shape test runs there.
  Run the full suite in an environment with `requirements.txt` installed.
- Task card still says `pybullet3d/` and `Status: waiting`; the code lives in `packages/adapters/pybullet/`.

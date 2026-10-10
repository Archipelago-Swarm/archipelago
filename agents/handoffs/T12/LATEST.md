# Handoff: T12 / 20261010T063026Z (worker A)

- State: in_progress (UNSYNCED: supervisor owns commit/push)
- Branch: agent/A/20261010T063026Z/T12, base a5076ce
- Reserved paths: packages/adapters/pybullet/, tests/adapters3d/, agents/handoffs/T12/ (task card says `pybullet3d/`+`infra/3d/`; run instructions override)

## Completed
- `packages/adapters/pybullet/archipelago_pybullet/adapter.py`: `PyBullet3DAdapter` (reset/step/snapshot/close, 2-4 drones, DIRECT/headless, real rigid-body spheres, velocity commands from the existing 5 commands, P-controller hover at z=1, drone-drone contact count as collision metric). Action space `act3d-v0`, encoder `drone3d-v0`.
- `requirements.txt`: pybullet isolated to this package.
- `tests/adapters3d/`: encoder-mismatch rejection (2D<->3D, passes); headless flight + collision test (SKIPPED: pybullet not installed).

## Validation
`python -m pytest tests/adapters3d -q` (global Python 3.14, user-site `pip install pybullet pytest pydantic numpy`) from worktree root -> 2 passed (flight hover/move + drone-drone contact verified).
The repo `.venv` is Python 3.13 and has no pybullet, so there the flight test skips (1 passed, 1 skipped).

## Not done / blockers
- Contract `Pose.z` is pinned to 0 (shared contract, not mine): 3D z only via `poses3d()`; Observation/Snapshot carry x,y. Needs integrator decision/ADR to allow z for `dimensionality=3d`.
- Not gym-pybullet-drones: no pinned revision, license review, rotor dynamics, takeoff/land controllers. Landing/takeoff commands absent (Action.command is a fixed literal).
- No saved evidence, build/run docs, retraining/Gazebo-PX4 doc.
- Viewer-only check: adapter uses DIRECT physics only; no GUI path.

## Next steps
1. Get pybullet running (Python 3.11/3.12 venv), run the test, fix whatever fails.
2. Pin gym-pybullet-drones SHA + license, swap point-mass for its controllers.
3. Save a smoke evidence artifact and write docs.

## Supervisor checkpoint 2026-10-10T06:35:13Z

- Run: 20261010T063026Z
- Machine: A
- Task/branch: T12 / agent/A/20261010T063026Z/T12
- Base: a5076ce701a3a7a99a7c3d147779d98c36270f28
- Round: 1
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

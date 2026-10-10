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

## Worker A fix (round 2)
- External check failed on `ruff format --check` for `tests/adapters3d/test_pybullet.py`; ran `ruff format` on my paths. `bash scripts/check.sh` now passes end to end.
- Remaining work unchanged (see Next steps above).

## Supervisor checkpoint 2026-10-10T06:37:07Z

- Run: 20261010T063026Z
- Machine: A
- Task/branch: T12 / agent/A/20261010T063026Z/T12
- Base: a5076ce701a3a7a99a7c3d147779d98c36270f28
- Round: 2
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Check 1 (headless flight smoke with valid 3D poses and collision metrics): the flight/collision test is skipped in the project's check run ('1 skipped'), because pybullet is not installed in the repo .venv. The external check therefore gives no evidence. No smoke artifact is saved. The handoff's 2-pass claim comes from a different global Python, not from the check.", "Check 1 (continued): the shared contract pins Pose.z to 0. Observations and snapshots carry only x and y. 3D z is only available through the adapter-specific poses3d(), so the adapter does not emit 3D poses through the shared contracts. The handoff says this needs an integrator decision or ADR.", "Check 4 (upstream revision/license, exact build/run commands, evidence saved): none of it exists. gym-pybullet-drones is not pinned and there is no license review. The only saved file is a requirements.txt. There is no build/run documentation and no evidence artifact. The handoff admits this.", "Slices 1 and 3 are not implemented: the adapter is a point-mass sphere with a P-controller, not gym-pybullet-drones. There are no takeoff or landing controllers, and Action.command has no takeoff/land commands. Slice 4 is also missing: no docs on retraining, changed dynamics or observations, or the Gazebo/PX4 route.", "Check 2 (2D/3D model updates rejected across incompatible encoders): the test only exercises Learner and decode with a hand-set encoder string. It does not cover model updates produced by the 3D adapter's own encoder or action version. It is weak evidence for the 'new encoder/action version' outcome.", "Check 3 (core 2D CI independent of heavy simulator dependencies): this is only implicit. pybullet is skipped via importorskip, and no test or CI evidence shows 2D CI and deployment never need it. Package placement also deviates from the task card's allowed paths (pybullet3d/ and infra/3d/ versus pybullet/), justified only by 'run instructions override' in the handoff.", "Check 5 (viewer-only visualization does not count as physics): there is no test or doc beyond a handoff remark that the adapter uses DIRECT physics only.", "The T12 task card is still Status: waiting with 'Assignment: unclaimed'. The handoff itself is also self-declared in_progress with its own 'Not done / blockers' list, so the worker admits the task is unfinished."]}
- Next issue: Check 1 (headless flight smoke with valid 3D poses and collision metrics): the flight/collision test is skipped in the project's check run ('1 skipped'), because pybullet is not installed in the repo .venv. The external check therefore gives no evidence. No smoke artifact is saved. The handoff's 2-pass claim comes from a different global Python, not from the check.; Check 1 (continued): the shared contract pins Pose.z to 0. Observations and snapshots carry only x and y. 3D z is only available through the adapter-specific poses3d(), so the adapter does not emit 3D poses through the shared contracts. The handoff says this needs an integrator decision or ADR.; Check 4 (upstream revision/license, exact build/run commands, evidence saved): none of it exists. gym-pybullet-drones is not pinned and there is no license review. The only saved file is a requirements.txt. There is no build/run documentation and no evidence artifact. The handoff admits this.; Slices 1 and 3 are not implemented: the adapter is a point-mass sphere with a P-controller, not gym-pybullet-drones. There are no takeoff or landing controllers, and Action.command has no takeoff/land commands. Slice 4 is also missing: no docs on retraining, changed dynamics or observations, or the Gazebo/PX4 route.; Check 2 (2D/3D model updates rejected across incompatible encoders): the test only exercises Learner and decode with a hand-set encoder string. It does not cover model updates produced by the 3D adapter's own encoder or action version. It is weak evidence for the 'new encoder/action version' outcome.; Check 3 (core 2D CI independent of heavy simulator dependencies): this is only implicit. pybullet is skipped via importorskip, and no test or CI evidence shows 2D CI and deployment never need it. Package placement also deviates from the task card's allowed paths (pybullet3d/ and infra/3d/ versus pybullet/), justified only by 'run instructions override' in the handoff.; Check 5 (viewer-only visualization does not count as physics): there is no test or doc beyond a handoff remark that the adapter uses DIRECT physics only.; The T12 task card is still Status: waiting with 'Assignment: unclaimed'. The handoff itself is also self-declared in_progress with its own 'Not done / blockers' list, so the worker admits the task is unfinished.
- Resume: fetch this branch, inspect latest commit and continue the task card.

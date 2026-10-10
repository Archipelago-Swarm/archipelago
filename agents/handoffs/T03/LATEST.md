# Handoff: T03 / 2026-10-10 (run 20261010T054510Z)

- State: review
- Run / machine / worker: 20261010T054510Z / A / bounded worker
- Branch: agent/A/20261010T054510Z/T03 (base 2d71e98); NOT committed by worker; supervisor owns checkpoint
- Reserved paths: packages/sim/, packages/adapters/sim2d/, tests/sim/

## Completed and verified

- `packages/sim/archipelago_sim/env.py`: seeded `GridWorld` (obstacles, targets, local sensing radius 2, per-node private known buffers, battery, five simultaneous actions, deterministic collision fixpoint for wall/same-cell/swap/move-into-stayer, invalid/missing action -> stay + penalty + event, energy exhaustion, termination on all targets found, truncation at max_ticks, privileged `world_state()`/`trace_hash()`), plus `explorer_policy` fixture.
- `packages/adapters/sim2d/archipelago_sim2d/`: `Sim2DAdapter` (SimulatorAdapter contract), replay + `manifest.json` writer, CLI `python -m archipelago_sim2d`.
- `tests/sim/test_sim.py`: 7 tests (determinism, observation isolation, collisions, invalid/missing/energy/termination, truncation, 4-node 900-tick smoke with a silent node writing a manifest, API shape). `.venv/Scripts/python -m pytest tests -q` -> 49 passed.
- CLI: `PYTHONPATH="packages/sim;packages/adapters/sim2d;packages/contracts/src" .venv/Scripts/python -m archipelago_sim2d --seed 1 --out DIR` -> coverage 0.929, 66 ticks (ended early: all targets found).

## Not done / limits

- PettingZoo compatibility is duck-typed only: pettingzoo/gymnasium are not installed and adding deps needs lockfile/pyproject changes outside reserved paths. The `api_test` acceptance check is NOT met until a dependency is approved.
- `RunConfig.nodes[].start_pose` is ignored (seeded random starts). Reward spec is constants in env.py, not a registered `reward_id`.
- Smoke run ends on target discovery, so it does not reach 900 ticks; the test only caps at 900. Workspace `pyproject.toml` does not include the new packages (tests use `tests/sim/conftest.py` sys.path); no mypy/ruff run.
- Replay is written from adapter step records (actions, events, state hash); no replay re-player yet.

## Next steps

1. Supervisor: decide on adding `pettingzoo` + packaging for sim packages (shared files), then add `parallel_api_test`.
2. Honour start poses; add a longer scenario (more targets) so a run uses the full 900 ticks.
3. Add replay re-execution test comparing `final_state_hash`.

## Supervisor checkpoint 2026-10-10T05:50:35Z

- Run: 20261010T054510Z
- Machine: A
- Task/branch: T03 / agent/A/20261010T054510Z/T03
- Base: 2d71e98ab484ca79eb22bfa3e23270cd1edb2f7c
- Round: 1
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

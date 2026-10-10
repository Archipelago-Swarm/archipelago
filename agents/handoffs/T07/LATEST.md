# Handoff: T07 / 20261010T062257Z (worker A)

- State: review (uncommitted; supervisor owns commit/push)
- Branch: agent/A/20261010T062257Z/T07, base 149f1e4
- Reserved paths: packages/learning/, packages/node/learner/, tests/learning/

## Completed and verified

- `packages/learning/archipelago_learning/dqn.py`: numpy-only DQN `Learner` (torch is not installed). It has per-node params, target, Adam state, replay and RNG. It also has read-only `snapshot()` for inference, a `paused` flag, modes `independent`/`information_only`/`mixing`, and `save`/`load` with model, replay and RNG in separate files.
- `peer.py`: `encode`/`decode` (npz with `allow_pickle=False`; checks metadata compatibility, dtype, shape, finiteness and a 1 MiB size cap), `offer` (accepts only if the caller-supplied `eval_fn` score improves; logs source, version and sha256; drops peer optimizer state and resets the target), `rollback`, and bounded mixing (alpha<=0.5, mixing mode only).
- Events: `local_update`, `peer_offer` and `rollback` are appended to `learner.events`.
- Tests: `tests/learning/test_learning.py` covers every acceptance bullet. The transfer test reports control=0.33 vs treated=1.00 on a toy one-hot task.
- Command (repo root): `uv run --offline pytest tests/learning -q -s` -> 7 passed.

## Not done / limits

- Learning is not yet wired to GridWorld or `GridParallelEnv`. No end-to-end transfer test on the grid sim; the transfer result is from a toy task only.
- `packages/node/learner/` is empty. Emitting events onto the transport/contract schema is not done, because that needs shared contracts.
- Mixing is only checked for bounds, not for benefit. Ruff and mypy were not run.
- The peer-offer path is not rate limited.

## Next steps

1. Run `ruff check packages/learning tests/learning`.
2. Add a grid-sim rollout harness (reward = coverage gain) and a transfer experiment with a no-transfer control across 3+ seeds.
3. Add a node wrapper in `packages/node/learner/` that sends and receives payloads via T05 transport.

## Supervisor checkpoint 2026-10-10T06:24:49Z

- Run: 20261010T062257Z
- Machine: A
- Task/branch: T07 / agent/A/20261010T062257Z/T07
- Base: 149f1e48ba35ff4afef178d5245f51eaf50fc4bd
- Round: 1
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

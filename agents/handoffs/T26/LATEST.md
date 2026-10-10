# Handoff: T26 PyTorch CPU learner with peer-protocol compatibility

- State: implemented, all T26 acceptance commands green locally; awaiting integrator review.
- Base: d30d299 (worktree was created at a73546c and moved forward with `git reset --hard d30d299` before any edit).
- Interface: agents/architecture/live-runtime.md sections 4 and 7.

## Plan / what was done

- `packages/learning/archipelago_learning/torch_dqn.py`: `TorchLearner` (Linear-ReLU-Linear, policy + target nets, torch Adam, bounded NumPy replay, per-instance numpy `Generator` for exploration and replay sampling, per-instance `torch.Generator` for init). `InferenceSnapshot` is an immutable read-only NumPy copy (no autograd); `act` uses the latest published snapshot, republished after each train step / import / restore. Surface matches the NumPy `Learner` (`act/observe/train_step/snapshot/paused/events/steps/version/n`). `threads=None` means env `OMP_NUM_THREADS` else 1; an explicit arg wins. `runtime` dict records backend `torch-cpu`, torch version, threads, deterministic flag and any error. No module-level mutable state (note: `torch.set_num_threads` and `use_deterministic_algorithms` are process-wide torch switches, last constructor wins).
- `compat.py`: param-map-v1 constants, encoder definition hashes, shape/dtype/finite validator shared by both backends.
- `peer.py`: encode/decode/offer/rollback now duck-typed on `params_numpy/load_params_numpy/sync_target/_reset_optimizer` and header attributes, so both backends interoperate. Header adds `format, param_map, backend, reward_id, action_space, encoder_sha256`. Mismatch reasons are named (`incompatible format|param_map|encoder|encoder_sha256|obs_dim|hidden|n_actions|reward_id|action_space`). Kept: tensor-only npz (`allow_pickle=False`), 1 MiB cap, zip inflation bound, dtype/shape/finite, sender check, mixing alpha<=0.5, optimizer state never imported. Added: exact member set check, `_meta` must be 1-D uint8. Accepted-event fields: source, source_version, source_backend, payload_sha256, pre_version/post_version/new_version, current_score, candidate_score, margin, margin_required, validation_seconds. Rollback event has pre/post version. Local updates are `local_update` events; peer imports are `peer_offer` events (distinct types; existing `LearnerNode` still works).
- `dqn.py` (NumPy baseline): docstring labels it REGRESSION BASELINE, `backend = "numpy"`, plus the compat surface only (`params_numpy`, `load_params_numpy`, `sync_target`, header attributes). Training behavior untouched.
- `checkpoint.py` + `TorchLearner.save_generation(root, extra=None)` / `load_latest(root)`: `gen-<n>/` with `model.npz` (policy+target, param-map layout), `optimizer.npz` (Adam step and moments, param-map layout), `replay.npz`, `rng.npz` (numpy bit-generator state as JSON bytes, torch generator state), `previous.npz`, `counters.json`, `events.json`, `extra.<name>.json`; `MANIFEST.json` (sha256 + size per file) written last; `CURRENT` switched by temp + fsync + `os.replace` + dir fsync. Load verifies hashes, tries CURRENT's generation first, then older complete ones; incomplete/corrupt generations ignored and garbage-collected; keeps last 3. Loader parses and validates everything before mutating the learner. Single writer per root assumed.
- `__init__.py` exports `TorchLearner` lazily so `import archipelago_learning` does not import torch (tested).

## Decisions

- Payload versioning: payloads from the pre-T26 encoder have no `format` field and are REJECTED (`incompatible format`); they cannot prove encoder-hash/reward/action-space identity and none are persisted. `backend` is evidence only, never a compatibility criterion.
- `grid-flat-v0` (NumPy default) and `grid-flat-v1` (TorchLearner default) are distinct ids, so default-constructed NumPy and Torch learners reject each other; cross-backend tests construct both with the same encoder id.
- Loss uses `0.5*mean(err^2)` so one-step Adam updates match the NumPy baseline (tested to 1e-4 over 25 steps with identical batches).
- `events` grows unbounded like the NumPy learner (the `LearnerNode` flush index depends on it); runtime may truncate after flushing in a later task.
- Node-runtime state (sequence, exploration schedule, episode, dedupe cache, telemetry cursor) goes through `extra`; T27 owns the content.
- Fault-injection hook: `save_generation(..., _io=DurableIO subclass)`; every filesystem primitive calls `io.hook(op, path)`.

## Evidence (all run in this worktree, torch 2.14.1+cu130 PyPI wheel)

- `uv run pytest tests/learning -q` -> 130 passed (28 s)
- `uv run pytest -q -m "not docker" --ignore=tests/e2e` -> 330 passed, 5 skipped (pre-existing skips), 10 deselected
- `uv run ruff check packages services tests` -> clean; `uv run ruff format --check packages services tests` -> clean; `uv run mypy` -> no issues
- Kill-between-every-write: `test_kill_between_every_pair_of_writes_leaves_loadable_previous_generation` kills the writer before each filesystem primitive of a second generation (plain and torn-temp-file variants, every cut point) and asserts generation 1 (or complete generation 2 after the CURRENT switch) restores bit-identically; first-generation variant asserts a named "no loadable" error before the manifest commit and a whole state after.
- Restore equivalence: `test_restore_and_continue_equals_uninterrupted_run` (80 steps with exploration, observe and target syncs, allclose 1e-6).
- Measurements (`measure.py` in scratchpad: 28-32-5 MLP, capacity 5000, batch 32, 1 thread, 4-core box), two runs:
  - peak RSS of one process after 1000 train steps: ru_maxrss 666.5 / 666.8 MiB (VmHWM 682.7 / 682.9 MB). Of this, a bare `import torch` already peaks at 502 MiB (python alone 38 MiB) because the PyPI wheel is the CUDA build (cu130); the learner itself (replay 5000, nets, 1005 steps) adds about 165 MiB. This exceeds the 512 MB node limit: T27 must measure with the CPU wheel (expected much smaller) before keeping 512 MB. I could not measure the CPU wheel (download.pytorch.org is blocked).
  - train step (warm): median 1.02 / 1.13 ms, p95 1.5 / 1.7 ms (includes snapshot publish, event append)
  - inference `act` (warm, snapshot NumPy): 7.9 / 8.7 us
  - import: `import archipelago_learning` + `TorchLearner` (includes torch) 1.6-1.7 s cold-ish; importing the package alone does not load torch
  - `save_generation` 37-44 ms, `load_latest` 11-18 ms (capacity 5000)

## Files modified

packages/learning/archipelago_learning/{__init__,dqn,peer,compat,checkpoint,torch_dqn}.py; tests/learning/{torch_support,test_torch_learner,test_peer_crossbackend,test_checkpoint_generations}.py; this handoff. Existing tests/learning/test_learning.py unchanged and passing.

## Not run / limits

- CPU-only wheel from download.pytorch.org (blocked); results on cu130 wheel. Do not compare bitwise across wheel variants.
- No Docker, no 4-process node run (T27).

## Next steps

- T27: adopt `TorchLearner`, `save_generation(extra=...)`, measure RSS with the CPU wheel; consider truncating `events` after flush.
- Integrator: confirm the "reject legacy payloads" decision and the v0/v1 encoder id split.

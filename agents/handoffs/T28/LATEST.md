# Handoff: T28 Simulation coordinator service

- State: IMPLEMENTED (repair round 1 applied), awaiting integrator review (worker branch, not pushed)
- Interface: agents/architecture/live-runtime.md sections 1, 2, 3, 6, 12; ADR-0008
- Reserved paths used: services/coordinator/**, tests/coordinator/**, packages/adapters/sim2d/**, tests/sim/**

## Plan (done)
1. Adapter: `Sim2DAdapter.remove_node` (mid-episode drone removal), removal recorded in replay, manifest embeds `run_config`, `replay_final_hash_from_dir`.
2. Coordinator package `archipelago_coordinator`: settings, sim loader (no fixtures), models (Plan), spool (persistent events), nodeclient (bearer, keep-alive, deadline fan-out), runner (tick loop, episodes, faults, kill, replay), service (registry, validation, readiness, recovery), httpd, `__main__`, README.
3. Tests with in-process stdlib fake node servers.

## What was done / design decisions
- GridWorld agent removal: `GridWorld` has no removal API. `archipelago_learning.rollout.reset(drop=...)` deletes the drone from `world.drones` and `world.agents` (no body, no wreck). `Sim2DAdapter.remove_node` does exactly that mid-episode; it differs from battery death where the wreck stays in `drones` and blocks its cell. Recorded in the replay as `{tick, removed, state_hash}` (no `actions`), `replay_final_hash` re-applies it; manifest `ticks` counts only step records, adds `removed_nodes`.
- `kill_node` applies in every episode of the run, before that tick's act round; killed node gets no more act/feedback but still receives `episode_end`.
- Feedback only to nodes whose own action was applied that tick and only in train episodes (a stay-fallback tick would otherwise pair the node's cached action with a different executed action; eval nodes answer 409).
- Unavailable nodes are not called again in the episode; the next episode reset retries and restores `ready`.
- Control order per episode: `reset` (mode train/eval, seed), `set_schedule` (schedule + SHA-256), ticks, `episode_end`. Coordinator pause/resume gate the tick loop only; `stop` is never sent to nodes (would kill node processes).
- `eval_every` is recorded but the explicit episode list is authoritative (spec ambiguity). `count` expands to consecutive seeds.
- telemetry_outage window refers to the tick being executed (events carry sim_tick t+1); dropped events get no sequence, so sequences stay contiguous; `events_dropped` exposed.
- Restart: runs active at process death become `interrupted` on next boot, a `run_interrupted` metric continues the sequence, tick recovered from last event. Run ids cannot be reused (409). Event id `{run_id}-{boot_id}-{seq}`; run_id limited to 64 chars.
- Settings `start_paused` and `tick_interval_s` are ops/test hooks (deterministic pause/step tests).
- Production (`ARCHIPELAGO_ENV=production`): Coordinator init raises `SimulatorUnavailable` if sim2d cannot import (exit 2 from `__main__`); non-production reports readyz false and 503 on run creation. There is no fixture code path.
- Added `Settings` env: COORDINATOR_TOKEN, COORDINATOR_ADMIN_TOKEN, NODE_CONTROL_TOKEN (all >=16 chars, admin != coordinator).

## Evidence (exact commands, 2026-10-10, worktree at d30d299 + changes)
- `uv run ruff check packages services tests` -> All checks passed
- `uv run ruff format --check packages services tests` -> clean
- `uv run mypy` -> Success: no issues found in 21 source files (coordinator not in mypy `files`; needs pyproject change, see notes)
- `uv run pytest tests/coordinator tests/sim -q` -> 53 passed (about 10 s); earlier run repeated 3x with 53 passed each
- `uv run pytest -q -m "not docker" --ignore=tests/e2e` -> 251 passed, 5 skipped (pre-existing skips), 10 deselected
- Not run: Docker/Compose, tests/e2e, real node runtime (T27) integration (T29), load/soak.

## Files modified
- packages/adapters/sim2d/archipelago_sim2d/adapter.py, tests/sim/test_sim.py
- services/coordinator/archipelago_coordinator/{__init__,__main__,settings,sim,models,spool,nodeclient,runner,service,httpd}.py, services/coordinator/README.md
- tests/coordinator/{conftest,harness,test_coordinator_api,test_coordinator_run}.py

## Next steps / for integrator
- Shared-file changes needed (not done by me): add `services/coordinator` and `tests/coordinator` to mypy `files` (the code is lightly typed; expect some fixes) and a Dockerfile/Compose service (T31); workspace/pyproject entry is not required since the package is stdlib plus contracts and tests use sys.path like other packages.
- T27/T29: check node real responses against `_parse_action` (requires `node_id`, `tick`, `action` with `source_node_id==node`, `action_space_version==act-v0`), and that node `reset` accepts extra fields `seed`, `episode_kind`.
- Known limits: no resume of a run after restart; events older than 100k per run are only in the JSONL file; pacing is not wall-time aligned.

## Repair round 1 (findings from review of 321f887)
- checkpoint: implemented. `CommandBody` accepts `checkpoint`; `Run.apply_command` validates it (running or paused only, else 409), is idempotent per command_id, and forwards a node `/v1/control {command: checkpoint}` once to every non-killed node outside the lock; response carries `checkpoint.requested/failed`. Test: `test_checkpoint_is_forwarded_once_per_command_to_live_nodes`. Integrator action: live-runtime.md section 12 command list (line ~101) still reads `pause|resume|step|stop`; please add `checkpoint` (I do not own that file).
- Termination: new tests `test_battery_termination_ends_one_drone_and_the_others_continue` (terminated=True feedback for the dead node only, survivors continue to truncation, replay hash reproduces, energy_exhausted in replay) and `test_episode_ends_when_every_drone_has_terminated_and_next_episode_starts` (the `if not live_world: break` exit, two episodes, hashes reproduce).
- Duplicate/stale: the coordinator's guarantee is now stated and tested: each (episode, tick) act and feedback is sent at most once per node and never retried; a late act reply is dropped (stay applied, 1 miss, no feedback for the stayed tick) and a feedback timeout is recorded as `feedback_failed` without a resend (`test_coordinator_sends_each_step_key_once_and_discards_late_replies`). The old test was renamed `test_wrong_tick_replies_are_misses_not_applied` and no longer claims idempotency. Node-side idempotency (cached replay, 409 stale) is the node runtime's job (T27) and is not tested here beyond the fake node.
- mypy: coordinator source and tests are strict-clean and fixed (lambdas to functools.partial, socket None check, stale ignores, annotations). pyproject.toml is not mine, so `uv run mypy` (21 files) still does not cover them. Integrator: add `services/coordinator/archipelago_coordinator` and `tests/coordinator` to `files`, and put `packages/sim`, `packages/adapters/sim2d`, `services/coordinator`, `tests/coordinator` on `mypy_path` (or add `follow_imports = skip` for archipelago_sim*): without that, import-not-found appears, and the untyped sim/sim2d packages report their own strict errors. Verified with `MYPYPATH=packages/sim:packages/adapters/sim2d:services/coordinator:tests/coordinator uv run mypy services/coordinator/archipelago_coordinator tests/coordinator`: zero errors in coordinator files; remaining 23 are all in packages/sim and packages/adapters/sim2d.
- httpd: `_dispatch` wrapped; unexpected exceptions log and return 500 `{"error":"internal_error"}` (test). service `_validate` probe now catches any Exception and returns 422 with the type name (test).
- spool: on-disk JSONL rotates at 64 MiB per segment (live file plus one `.1`, so about 128 MiB per run; the newest record always lands in the fresh live file so the sequence survives restart); fsync at most once per second and on rotate/close (a crash can lose up to about 1 s of events from the file; the events API is unaffected); memory window is a list trimmed in 10 percent chunks and `page()` uses bisect instead of a scan. Tests in tests/coordinator/test_spool.py.
- Timing tests: stall bound is now 3 s stall vs `max_tick_ms < 1500` (half the stall, comment explains); the sleep-based pause test was replaced by a start_paused plus `step` test that asserts exact tick counts without sleeping.
- Not run: tests/e2e, Docker (T27, T29, no daemon).

### Evidence (repair round)
- `uv run ruff check packages services tests` -> All checks passed; `uv run ruff format --check packages services tests` -> 84 files already formatted
- `uv run mypy` -> Success: no issues found in 21 source files (config unchanged, see above)
- `uv run pytest -q tests/coordinator tests/sim` -> 61 passed (run twice)
- `uv run pytest -q -m "not docker" --ignore=tests/e2e` -> 259 passed, 5 skipped, 10 deselected

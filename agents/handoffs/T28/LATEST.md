# Handoff: T28 Simulation coordinator service

- State: IMPLEMENTED, awaiting integrator review (worker branch, not pushed)
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

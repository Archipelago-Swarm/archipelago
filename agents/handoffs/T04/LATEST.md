# Handoff: T04 / 20261010 checkpoint 2 (UTC)

- State: in_progress (provisional; unmerged until T01 passes CI and merges)
- Run / machine / worker: no RUN_ID / B / B-lead (bootstrap exception, manual assignment from A)
- Assignment generation: bootstrap, 0
- Branch / worktree: agent/B/T04/run-api / C:\archipelago-T04
- T01 base commit (reviewed): 844d2e0 (origin/claude/elegant-pascal-a8a3hp; code at 61ef2ca, T01 state `review`, GitHub CI NOT yet run)
- Main instructions merged: origin/main 0d8691a ("Allow B to start T04...")
- Resume from: origin/agent/B/T04/run-api
- Reserved paths: services/api/, tests/api/. SHARED-FILE REQUEST to A: root pyproject.toml (workspace member services/api, dev deps, mypy files) and uv.lock; applied on this branch only, to be serialized by A at reconciliation.

## Intended outcome and acceptance
See agents/tasks/T04.md. Final review needs a real T03 run; fixture-only is partial.

## Plan
FastAPI app in services/api/src/archipelago_api: idempotent POST /v1/runs, commands (pause/resume/step/stop with command_id + expected_revision), bounded event replay, WS stream (snapshot, sequenced deltas, bounded queues + resnapshot), cookie/bearer auth + WS origin check, /healthz /readyz, restart marks orphaned runs interrupted. Fixture adapter until T03.

## Completed and verified (local, fixture adapter only)
services/api/src/archipelago_api (settings, runs, app) + tests/api/test_api.py (11 tests): idempotent start + capacity/conflict, pause/resume/step/stop and invalid transitions, duplicate/stale commands, budget completion, paged events, bearer/cookie auth + WS origin/auth rejection, snapshot->delta stream, resnapshot on lag, slow subscriber never blocks the sim, disconnect/reconnect, restart and clean shutdown mark runs `interrupted`, /healthz /readyz.

## Validation
`cd C:rchipelago-T04; uv run ruff check packages services tests; uv run mypy; uv run pytest -q` -> clean, 42 passed (31 T01 + 11 T04).
`bash scripts/check.sh`: Python half passes; `npm run gen:check` FAILS here only because git autocrlf=true gives generated/types.ts CRLF endings (T01 portability issue on Windows, not T04; JS steps after it not run). Python 3.12 / GitHub CI not run.

## Shared-file edits needing A's serialization
pyproject.toml (workspace member, deps, mypy files), scripts/check.sh (ruff paths include services), uv.lock (httpx, fastapi, uvicorn added).

## Limits / not done
- Fixture adapter only; real T03 wiring and real-run final check pending. Adapter is chosen by `create_app(settings, factory)`.
- Deltas carry full snapshots (shortcut). Run metadata persists to JSON; events are not recovered after restart.
- Cookie `secure=False` until TLS (T10). Login is a single shared token. No rate limiting.
- Slow-viewer test sets `lagged` directly (TestClient cannot stall a socket); real socket stall relies on send_timeout, untested.

## Next steps
1. Wait for T01 CI + merge; merge main into agent/B/T04/run-api; resolve shared-file conflicts with A's versions.
2. Wire T03 adapter factory; add a real-run test; rerun scripts/check.sh.
3. Open PR with evidence.

## Run 20261010T061419Z (B worker, no commits)
- Re-verified in worktree: `uv run pytest tests/api -q` -> 11 passed. No code changes.
- T03 adapter is not present in this tree (no simulator package), so real-run wiring/final check remain blocked; fixture-only stays partial.
- Next: once T03 merges, add a factory for the real adapter in `create_app_from_env` and a real-run test.

## Supervisor checkpoint 2026-10-10T06:18:50Z

- Run: 20261010T061419Z
- Machine: B
- Task/branch: T04 / agent/B/20261010T061419Z/T04
- Base: ebf81adfd106fe3bbf8faf752dcf254e49ee6e95
- Round: 1
- State: in_progress
- External check exit: 0
- Independent review: not run
- Next issue: Independent review unavailable or inconclusive
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Run 20261010T061419Z round 2 (B worker, no commits)
- Re-checked: `uv run pytest tests/api -q` -> 11 passed. Still no simulator package (`packages/` has only contracts), so T03 real-run wiring is blocked; no code changed.
- Remaining acceptance gap: real T03 run (fixture-only stays partial). Next: when T03 merges, add real adapter factory in `create_app_from_env` plus a real-run test.

## Supervisor checkpoint 2026-10-10T06:19:37Z

- Run: 20261010T061419Z
- Machine: B
- Task/branch: T04 / agent/B/20261010T061419Z/T04
- Base: ebf81adfd106fe3bbf8faf752dcf254e49ee6e95
- Round: 2
- State: blocked
- External check exit: 0
- Independent review: not run
- Next issue: Independent review unavailable or inconclusive
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Run 20261010T063026Z (A worker, no commits)
- T03 adapter now present (packages/adapters/sim2d). Added `sim2d_factory()` in services/api app.py; `create_app_from_env` uses it when `ARCHIPELAGO_ADAPTER=sim2d`. Added `test_real_sim2d_run_streams_and_completes` (importorskip; real GridWorld run through start/pause/step/stream/budget completion).
- Verified: with PYTHONPATH=packages/adapters/sim2d;packages/sim, `.venv/Scripts/python -m pytest tests/api -q` -> 12 passed. Without that path (sim2d not a workspace member) the real test skips.
- Needs supervisor/A (shared file): add packages/adapters/sim2d and packages/sim as workspace members/deps of services/api in pyproject.toml so the real test runs under plain `uv run pytest`. Not run: ruff/mypy, scripts/check.sh. Final real-run review still pending T01/T03 merge.

## Supervisor checkpoint 2026-10-10T06:40:36Z

- Run: 20261010T063026Z
- Machine: A
- Task/branch: T04 / agent/A/20261010T063026Z/T04
- Base: a5076ce701a3a7a99a7c3d147779d98c36270f28
- Round: 1
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Run 20261010T063026Z round 2 (A worker, no commits)
- Cause of exit 1: `uv run mypy` failed with 2 import-not-found errors for optional `archipelago_sim2d` (app.py sim2d_factory, tests/api/test_api.py real-run test). Fixed with `# type: ignore[import-not-found,unused-ignore]` on those two imports.
- Verified: ruff check/format --check clean, mypy clean, `uv run pytest tests/api -q` -> 11 passed, 1 skipped (real sim2d test skips: sim2d not a workspace member).
- Still needs A (pyproject.toml): add packages/adapters/sim2d and packages/sim as deps/members so the real test runs and the ignores can go. Not run: scripts/check.sh (gen:check CRLF issue on Windows).

## Supervisor checkpoint 2026-10-10T06:42:20Z

- Run: 20261010T063026Z
- Machine: A
- Task/branch: T04 / agent/A/20261010T063026Z/T04
- Base: a5076ce701a3a7a99a7c3d147779d98c36270f28
- Round: 2
- State: review
- External check exit: 0
- Independent review: {"pass": true, "issues": ["Real-run test (test_real_sim2d_run_streams_and_completes) uses pytest.importorskip. The handoff says it skips under plain `pytest tests/api` because sim2d is not a workspace member. The full-suite log shows no skips, so it probably runs only because tests/sim/conftest.py adds sim2d to sys.path. I could not run the suite to confirm this. The handoff should record that the real T03 run passed in the full check, and A should add sim2d and sim to pyproject.toml so the test no longer depends on that side effect.", "The `# type: ignore[import-not-found,unused-ignore]` comments on the sim2d imports in app.py and the test are a workaround for the missing workspace membership. Remove them once pyproject.toml is fixed.", "Slow-client coverage sets `lagged` directly because TestClient cannot stall a socket. Real socket-stall and send_timeout behaviour is untested, as the handoff admits. The queue-overflow path is covered, so this is a known limit.", "T01 CI has not run and T01 is not merged. Reconcile with main and re-run the real-simulator check after T01 merges, before the integrator marks T04 done."]}
- Next issue: none
- Resume: fetch this branch, inspect latest commit and continue the task card.

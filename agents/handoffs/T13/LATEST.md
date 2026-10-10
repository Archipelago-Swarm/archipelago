# T13 handoff (run 20261010T151923Z, machine B)

## Done (uncommitted, unverified end to end)
- Cause (from code inspection; API logs NOT captured): `_finish` closes the adapter, then a later stream subscribe calls `snapshot()` on the cleared sim2d world and the stream dies -> DISCONNECTED.
- `runs.py`: `_finish` caches `run.final` snapshot before `close()`; `snapshot_event` serves it for terminal runs. Recovered (restart) runs have none: stream sends status with empty snapshot, never a fake one.
- Web: `liveReducer` tracks `status` from stream messages; `sourceLabel(..., status)` shows `COMPLETED/FAILED/INTERRUPTED (not live)` instead of LIVE.
- Tests: API regression for stopped sim2d stream (skipped here: archipelago_sim2d not installed in this worktree); vitest for labels. Browser smoke now expects COMPLETED for the stopped run and INTERRUPTED after API restart.

## Results
- `uv run pytest tests/api`: 11 passed, 2 skipped. `npx vitest run`: 49 passed (before the final smoke-script edit).
- NOT run: `scripts/check.sh`, sim2d browser smoke, API-log capture.

## Next
Run `scripts/check.sh` and `ARCHIPELAGO_ADAPTER=sim2d npm run smoke -w @archipelago/web` with sim2d installed; capture API stderr to confirm the diagnosis. Command buttons are still enabled for terminal runs (server rejects with a conflict).

## Supervisor checkpoint 2026-10-10T15:24:18Z

- Run: 20261010T151923Z
- Machine: B
- Task/branch: T13 / agent/B/20261010T151923Z/T13
- Base: 843fa070f2e2d0c3dd57d001ad4bac87ff5e7142
- Round: 1
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

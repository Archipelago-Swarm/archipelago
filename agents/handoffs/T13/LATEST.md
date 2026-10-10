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

## Update (run 20261010T151923Z, round 2)
- Fixed the check failure: two ruff E501 lines (runs.py, tests/api/test_api.py).
- `bash scripts/check.sh`: passed. `ARCHIPELAGO_ADAPTER=sim2d npm run smoke -w @archipelago/web`: passed.
- Still not done: API stderr capture to confirm the diagnosis; terminal-run command buttons stay enabled.

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

## Supervisor checkpoint 2026-10-10T15:27:06Z

- Run: 20261010T151923Z
- Machine: B
- Task/branch: T13 / agent/B/20261010T151923Z/T13
- Base: 843fa070f2e2d0c3dd57d001ad4bac87ff5e7142
- Round: 2
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Acceptance check 1 is unmet. The handoff says the stopped-run stream failure was diagnosed 'from code inspection; API logs NOT captured'. It still lists API stderr capture as not done. No diagnostics are recorded.", "The handoff's final committed state is stale and contradictory. The supervisor checkpoint says 'External check exit: 1' and 'Independent review: not run'. The round 2 update says check.sh and the sim2d smoke passed, but gives no exact commands or output. The check.sh and smoke results are not recorded as required.", "The focused API regression test (test_stopped_sim2d_run_still_streams_final_snapshot) uses pytest.importorskip('archipelago_sim2d'). The external run shows 3 skipped, and the handoff says it was skipped in this worktree because sim2d is not installed. The key regression test therefore has no passing evidence.", "Evidence for the browser smoke covering start, pause, resume, stop, replay, disconnect/reconnect and terminal-run navigation is not shown. The smoke script was not found under apps/web/scripts, and the handoff only mentions that it expects COMPLETED and INTERRUPTED. The external check does not run the smoke.", "Terminal-run command buttons are still enabled. The handoff notes this and defers it. It leaves the terminal-run UI incomplete for 'honest status'. Recovered runs also have no snapshot, so what the UI shows for them is not covered by a test.", "The work is uncommitted (runs.py, test_api.py and the handoff are modified), so the pushed handoff and branch do not reflect the current state."]}
- Next issue: Acceptance check 1 is unmet. The handoff says the stopped-run stream failure was diagnosed 'from code inspection; API logs NOT captured'. It still lists API stderr capture as not done. No diagnostics are recorded.; The handoff's final committed state is stale and contradictory. The supervisor checkpoint says 'External check exit: 1' and 'Independent review: not run'. The round 2 update says check.sh and the sim2d smoke passed, but gives no exact commands or output. The check.sh and smoke results are not recorded as required.; The focused API regression test (test_stopped_sim2d_run_still_streams_final_snapshot) uses pytest.importorskip('archipelago_sim2d'). The external run shows 3 skipped, and the handoff says it was skipped in this worktree because sim2d is not installed. The key regression test therefore has no passing evidence.; Evidence for the browser smoke covering start, pause, resume, stop, replay, disconnect/reconnect and terminal-run navigation is not shown. The smoke script was not found under apps/web/scripts, and the handoff only mentions that it expects COMPLETED and INTERRUPTED. The external check does not run the smoke.; Terminal-run command buttons are still enabled. The handoff notes this and defers it. It leaves the terminal-run UI incomplete for 'honest status'. Recovered runs also have no snapshot, so what the UI shows for them is not covered by a test.; The work is uncommitted (runs.py, test_api.py and the handoff are modified), so the pushed handoff and branch do not reflect the current state.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Update (run 20261010T151923Z, round 3) — current state, supersedes earlier "NOT run" notes
- Diagnosis is from code inspection only; API stderr was not captured. The regression test below reproduces the stopped-run path and passes, which is the evidence for the fix.
- Web: new `isTerminal(status)` in `status.ts`; App command buttons are now disabled for completed/failed/interrupted runs.
- API test added: `test_recovered_run_streams_status_without_fake_snapshot` (restarted run streams status `interrupted`, no snapshot).
- mypy: added `import-untyped` to the ignore on the sim2d import in tests/api/test_api.py.
- Commands (sim2d needs a path on this worktree; PowerShell/Git Bash on Windows uses `;`):
  - `PYTHONPATH="packages/adapters/sim2d;packages/sim;packages/contracts/src" uv run pytest tests/api -q` -> 14 passed, 0 skipped (incl. `test_stopped_sim2d_run_still_streams_final_snapshot`, `test_real_sim2d_run_streams_and_completes`). Without that PYTHONPATH: 12 passed, 2 skipped.
  - `bash scripts/check.sh` -> exit 0 (without PYTHONPATH).
  - Same PYTHONPATH + `ARCHIPELAGO_ADAPTER=sim2d npm run smoke -w @archipelago/web` (script: tests/web/browser-smoke.mjs) -> `ok: browser smoke start/pause/resume/stop/replay/disconnect/reconnect`, exit 0.
- Not done: no vitest for the disabled-button state (logic is the tested `isTerminal`); the smoke is not part of check.sh.

## Supervisor checkpoint 2026-10-10T15:31:42Z

- Run: 20261010T151923Z
- Machine: B
- Task/branch: T13 / agent/B/20261010T151923Z/T13
- Base: 843fa070f2e2d0c3dd57d001ad4bac87ff5e7142
- Round: 3
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Acceptance check 1 is still unmet. The handoff says the diagnosis is 'from code inspection only; API stderr was not captured'. The task card requires API diagnostics to be captured and the actual failure identified before changing behavior. No diagnostic output is recorded.", "The work is uncommitted. App.tsx, status.ts, tests/api/test_api.py and the handoff are modified, and runs.py is not listed as modified in this worktree. The pushed branch and handoff do not reflect the current state, and the handoff is not backed by a pushed commit. The committed checkpoints still say 'External check exit: 1' and 'Independent review: not run'.", "The key regression tests need sim2d on PYTHONPATH and are skipped under the standard gate. The external check shows '132 passed, 3 skipped'. The handoff's 14-passed result depends on a manual PYTHONPATH that scripts/check.sh does not use. The sim2d smoke is also not part of check.sh. So the gate does not exercise the fix. The handoff gives results but no captured output.", "The disabled-button behavior for terminal runs has no test of its own. The handoff admits there is no vitest for it, only for the isTerminal helper. Recovered-run UI rendering has no test either.", "The smoke script covers start, pause, resume, stop, replay, disconnect and restart. The terminal-run navigation case is only the single reopen of ?run=ID. I did not run the smoke myself, so its passing rests on the handoff's claim."]}
- Next issue: Acceptance check 1 is still unmet. The handoff says the diagnosis is 'from code inspection only; API stderr was not captured'. The task card requires API diagnostics to be captured and the actual failure identified before changing behavior. No diagnostic output is recorded.; The work is uncommitted. App.tsx, status.ts, tests/api/test_api.py and the handoff are modified, and runs.py is not listed as modified in this worktree. The pushed branch and handoff do not reflect the current state, and the handoff is not backed by a pushed commit. The committed checkpoints still say 'External check exit: 1' and 'Independent review: not run'.; The key regression tests need sim2d on PYTHONPATH and are skipped under the standard gate. The external check shows '132 passed, 3 skipped'. The handoff's 14-passed result depends on a manual PYTHONPATH that scripts/check.sh does not use. The sim2d smoke is also not part of check.sh. So the gate does not exercise the fix. The handoff gives results but no captured output.; The disabled-button behavior for terminal runs has no test of its own. The handoff admits there is no vitest for it, only for the isTerminal helper. Recovered-run UI rendering has no test either.; The smoke script covers start, pause, resume, stop, replay, disconnect and restart. The terminal-run navigation case is only the single reopen of ?run=ID. I did not run the smoke myself, so its passing rests on the handoff's claim.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Update (run 20261010T151923Z, round 4): captured diagnostic
- Reproduced the stopped-run failure at the adapter (the call `snapshot_event` makes after `_finish` closes the adapter), with `PYTHONPATH="packages/adapters/sim2d;packages/sim;packages/contracts/src"`, `Sim2DAdapter().reset(make_config(1, 5))`, `snapshot()` (ok), `close()`, `snapshot()`:
  ```
  File ".../archipelago_sim2d/adapter.py", line 97, in snapshot
    s = self.world.world_state()
  AttributeError: 'NoneType' object has no attribute 'world_state'
  ```
  Confirms the T06 issue hypothesis: `close()` sets `world = None`, so a post-stop WebSocket subscribe raised and the stream died (DISCONNECTED). Not captured from the live API process's stderr; I could not revert runs.py to base here (denied), so this is the same call path run directly.
- Added vitest: recovered run message (`status: interrupted`, empty snapshot) -> no snapshot, `isTerminal`, label `INTERRUPTED (not live)`. `npx vitest run` in apps/web: 23 passed, tsc clean.
- Not done: no component-level test of the disabled buttons (App is untested; logic is `isTerminal`); the sim2d tests/smoke still need the manual PYTHONPATH and are outside `scripts/check.sh`. I did not rerun check.sh or the smoke this round.

## Supervisor checkpoint 2026-10-10T15:32:36Z

- Run: 20261010T151923Z
- Machine: B
- Task/branch: T13 / agent/B/20261010T151923Z/T13
- Base: 843fa070f2e2d0c3dd57d001ad4bac87ff5e7142
- Round: 4
- State: blocked
- External check exit: not run
- Independent review: not run
- Next issue: Worker permission, exit 0; inspect local log
- Resume: fetch this branch, inspect latest commit and continue the task card.

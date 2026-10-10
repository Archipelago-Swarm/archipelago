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

## Update (run 20261010T153519Z): re-verification, no code changes
- Tree already contains the fix (runs.py cached `final`, status.ts `isTerminal`/labels, disabled terminal buttons, tests).
- `PYTHONPATH="packages/adapters/sim2d;packages/sim;packages/contracts/src" uv run pytest tests/api -q` -> 14 passed.
- `bash scripts/check.sh` -> completed through web build (output tail ok; exit status piped through tail, so re-confirm via supervisor check).
- Same PYTHONPATH + `ARCHIPELAGO_ADAPTER=sim2d npm run smoke -w @archipelago/web` -> `ok: browser smoke start/pause/resume/stop/replay/disconnect/reconnect`.
- Still open: live-API-stderr capture (adapter-level traceback recorded in round 4); no component test for disabled buttons; sim2d tests/smoke outside check.sh.

## Supervisor checkpoint 2026-10-10T15:38:31Z

- Run: 20261010T153519Z
- Machine: B
- Task/branch: T13 / agent/B/20261010T153519Z/T13
- Base: e4f95c37d568c8cbc288b5a77eb4dfaf3826296a
- Round: 1
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Acceptance 1 is only partly met. The failure was reproduced at the adapter level (`snapshot()` after `close()` raises AttributeError), and this was done after the fix was written. No diagnostics came from the live API process, and the handoff admits this. The task card asks for API diagnostics before the behavior change.", "The key regression tests (`test_stopped_sim2d_run_still_streams_final_snapshot` and `test_real_sim2d_run_streams_and_completes`) are skipped under the standard gate (133 passed, 3 skipped). They only run with a manual PYTHONPATH. The sim2d browser smoke is also outside scripts/check.sh. The gate therefore never exercises the fix. The handoff lists 14 passed, but there is no captured output or log and I could not rerun it (Bash was denied for me).", "The handoff says check.sh and the smoke were not rerun in round 4. The final handoff has no single run of the exact commands against the final tree.", "The disabled command buttons for terminal runs have no component-level test, only the `isTerminal` helper. The recovered-run UI is covered only by a reducer and label test.", "Browser-smoke coverage of terminal-run navigation is thin, with one reopen of ?run=ID. The handoff does not show that the interrupted-after-restart path is verified end to end by the smoke. I did not re-verify the smoke myself.", "The handoff file is still uncommitted in the working tree (`M agents/handoffs/T13/LATEST.md`). Its older supervisor checkpoints are stale, with 'External check exit: 1' and 'Independent review: not run'. They conflict with the later updates and need a clean final state before a human PR review."]}
- Next issue: Acceptance 1 is only partly met. The failure was reproduced at the adapter level (`snapshot()` after `close()` raises AttributeError), and this was done after the fix was written. No diagnostics came from the live API process, and the handoff admits this. The task card asks for API diagnostics before the behavior change.; The key regression tests (`test_stopped_sim2d_run_still_streams_final_snapshot` and `test_real_sim2d_run_streams_and_completes`) are skipped under the standard gate (133 passed, 3 skipped). They only run with a manual PYTHONPATH. The sim2d browser smoke is also outside scripts/check.sh. The gate therefore never exercises the fix. The handoff lists 14 passed, but there is no captured output or log and I could not rerun it (Bash was denied for me).; The handoff says check.sh and the smoke were not rerun in round 4. The final handoff has no single run of the exact commands against the final tree.; The disabled command buttons for terminal runs have no component-level test, only the `isTerminal` helper. The recovered-run UI is covered only by a reducer and label test.; Browser-smoke coverage of terminal-run navigation is thin, with one reopen of ?run=ID. The handoff does not show that the interrupted-after-restart path is verified end to end by the smoke. I did not re-verify the smoke myself.; The handoff file is still uncommitted in the working tree (`M agents/handoffs/T13/LATEST.md`). Its older supervisor checkpoints are stale, with 'External check exit: 1' and 'Independent review: not run'. They conflict with the later updates and need a clean final state before a human PR review.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## FINAL STATE (run 20261010T153519Z, round 2): supersedes all earlier updates and checkpoints above
Earlier "External check exit: 1" / "not run" checkpoints are stale; this section is the current truth.
- Diagnostic before behavior: `agents/handoffs/T13/prefix_stream_diag.py` runs the real API app (sim2d, TestClient) with the pre-fix `_finish` (no cached snapshot), stops a run, subscribes to the stream. Output in `prefix-stream-diagnostic.log`: server-side traceback `stream -> snapshot_event -> adapter.snapshot -> AttributeError: 'NoneType' object has no attribute 'world_state'`. Cause confirmed: `close()` clears the world; the fix caches the final snapshot first. (In-process ASGI app, not a separate uvicorn process.)
- New `tests/api/conftest.py` puts sim2d/sim on sys.path, so the sim2d regression tests now run in the standard gate (no manual PYTHONPATH).
- New `commandsDisabled()` in status.ts (used by App) + vitest for it (live/connected/non-terminal only).
- Smoke extended: after API restart, command buttons disabled for the INTERRUPTED run; fresh reopen of the completed and the interrupted run shows `COMPLETED/INTERRUPTED (not live)`, no LIVE/DISCONNECTED, buttons disabled.
- Commands against this final tree:
  - `bash scripts/check.sh` -> exit 0 (pytest 133 passed, 3 skipped = pybullet only; vitest 27 + 24 passed; build ok).
  - `uv run pytest tests/api -q` -> 14 passed, 0 skipped.
  - `ARCHIPELAGO_ADAPTER=sim2d npm run smoke -w @archipelago/web` -> exit 0: `ok: browser smoke start/pause/resume/stop/replay/disconnect/reconnect/terminal-reopen`.
- Not done: the smoke is still outside check.sh (scripts/ is outside reserved paths); no DOM-level App render test (logic is in `commandsDisabled`).

## Supervisor checkpoint 2026-10-10T15:43:13Z

- Run: 20261010T153519Z
- Machine: B
- Task/branch: T13 / agent/B/20261010T153519Z/T13
- Base: e4f95c37d568c8cbc288b5a77eb4dfaf3826296a
- Round: 2
- State: review
- External check exit: 0
- Independent review: {"pass": true, "issues": ["Residual, non-blocking: the sim2d browser smoke is not part of scripts/check.sh. Its pass result comes from the handoff's own FINAL STATE section; I could not rerun it because Bash was denied.", "Residual, non-blocking: the diagnostic ran in-process (TestClient) on the pre-fix code path, not against a separate uvicorn process. The traceback is a server-side stream -> snapshot_event -> adapter.snapshot AttributeError, which matches the T06 issue.", "Residual, non-blocking: there is no DOM-level App render test for the disabled buttons. The logic is covered by vitest on commandsDisabled/isTerminal and by the smoke.", "Housekeeping: the working-tree changes, including the handoff, are uncommitted. The supervisor must commit and push them. Earlier stale checkpoints (exit 1, review not run) remain in LATEST.md, but the FINAL STATE section marks them as superseded."]}
- Next issue: none
- Resume: fetch this branch, inspect latest commit and continue the task card.

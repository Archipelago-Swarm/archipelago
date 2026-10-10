# T06 handoff (B, run 20261010T132342Z)

## Done
- `apps/web/src/state.ts` (+test): pure reducer; ignores out-of-order seq, `onClose` marks state disconnected/stale, LIVE/REPLAY/DISCONNECTED label.
- `apps/web/src/App.tsx`: open `/?run=<run_id>`; WS to `/v1/runs/{id}/stream`; Canvas world/obstacles/links/poses (dimmed when not live); pause/resume/step/stop via `/commands` (disabled unless live; revision refetched per event); replay from `/events` stepping frame by frame; run ID, status, sim-tick and coverage units shown. No credentials or hardcoded metrics.

## Verified
`npx tsc --noEmit` clean; `npx vitest run` 2 passed (in apps/web).

## Not done
- No browser smoke (Playwright) against a real run; `tests/web/` empty.
- No start-run/scenario selection (needs RunConfig + login UI; user must POST /v1/login first for cookie).
- No reconnect/backoff (onclose just marks stale), no node health/policy versions/transfer decisions (no contract data yet).
- Replay is manual stepping, not auto-play.

## Supervisor checkpoint 2026-10-10T13:24:16Z

- Run: 20261010T132342Z
- Machine: B
- Task/branch: T06 / agent/B/20261010T132342Z/T06
- Base: 2368137d1885098c5b1012ed08e2a31484b4f8aa
- Round: 1
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker note (run 20261010T132342Z, round 2)
- Check failure is environmental, not code: `.agent-runtime/logs/20261010T132342Z/B/T06-check-1.log` contains only `WSL ... execvpe(/bin/bash) failed: No such file or directory` (no WSL distro on B). Outside T06 paths; supervisor/human must fix.
- Re-verified in apps/web: `tsc --noEmit` clean, `vitest run` 2 passed, `vite build` OK.
- No code changed this round.

## Supervisor checkpoint 2026-10-10T13:24:48Z

- Run: 20261010T132342Z
- Machine: B
- Task/branch: T06 / agent/B/20261010T132342Z/T06
- Base: 2368137d1885098c5b1012ed08e2a31484b4f8aa
- Round: 2
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Supervisor checkpoint 2026-10-10T13:25:10Z

- Run: 20261010T132342Z
- Machine: B
- Task/branch: T06 / agent/B/20261010T132342Z/T06
- Base: 2368137d1885098c5b1012ed08e2a31484b4f8aa
- Round: 3
- State: blocked
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

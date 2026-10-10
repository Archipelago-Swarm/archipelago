# Handoff: T06 / 20261010T061419Z

- State: in_progress
- Run / machine / worker: 20261010T061419Z / B / bounded worker
- Reserved paths: apps/web/, tests/web/

## Completed
- `apps/web/src/model.ts` + `model.test.ts`: live/replay/disconnected-stale label (stale never shown as live).
- `App.tsx`: Canvas render of fixture poses, links, obstacles; run ID, tick, status, coverage (% of free cells) visible; REPLAY label; controls present but disabled.

## Not verified
- Tests/typecheck not run by worker (no install/run attempted). Run: `npm -w @archipelago/web test` and `typecheck`.

## Next steps
1. Run tests/typecheck.
2. Wire API/stream (after T03/T04), enable controls, node health/policy versions, browser smoke in tests/web/.

## Risks
- Acceptance checks (real-run smoke, reconnect) not met; no API exists yet. Coverage unit assumes fraction 0-1.

## Supervisor checkpoint 2026-10-10T06:21:20Z

- Run: 20261010T061419Z
- Machine: B
- Task/branch: T06 / agent/B/20261010T061419Z/T06
- Base: ebf81adfd106fe3bbf8faf752dcf254e49ee6e95
- Round: 1
- State: in_progress
- External check exit: 2
- Independent review: not run
- Next issue: External checks failed (exit 2); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

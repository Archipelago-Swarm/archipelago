# Handoff: T06 / 20261010T064958Z (machine B)

- State: in_progress (first slice, uncommitted; supervisor owns checkpoint)
- Reserved paths: apps/web/, tests/web/

## Completed and verified
- `apps/web/src/status.ts` + `status.test.ts`: live/replay/fixture label; disconnected live stream reads "stale", never "LIVE".
- `apps/web/src/App.tsx`: Canvas world (obstacles, links, drones), run ID, status, tick, coverage (% of free cells), pose units (cells), start/pause/step/stop buttons (disabled unless live+connected), WebSocket `/v1/runs/{id}/stream` with 2s reconnect, `?run=ID[&replay=1]`; default renders the contract fixture labelled as fixture.
- Verified: `npx tsc --noEmit` and `npx vitest run` in apps/web pass (2 tests).

## Not done / assumptions
- Untested against a real API; no browser smoke (tests/web empty). Replay mode only labels; no replay fetch/controls.
- Stream message shape assumed `{snapshot: WorldSnapshot}` from runs.py snapshot_event; incremental events are ignored until next snapshot.
- No run-start UI/seeded scenario selector, node health, policy versions or transfer decisions yet. Auth (login cookie) not handled.
- Revision for commands only fetched on connect; may 409 after status changes.

## Next steps
1. Add scenario select + POST /v1/runs (Idempotency-Key). 2. Replay via GET /events. 3. Playwright smoke in tests/web after T03/T04 merge.

## Supervisor checkpoint 2026-10-10T06:51:14Z

- Run: 20261010T064958Z
- Machine: B
- Task/branch: T06 / agent/B/20261010T064958Z/T06
- Base: 8a7b9b7b2513cebc87e2aa4a701cbf1e0eb564d0
- Round: 1
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Acceptance 1 has no evidence: no browser smoke exists (tests/web is missing) covering start, pause, resume and replay of a real run. The handoff admits this.", "Replay is only a label. There is no replay fetch from the events endpoint and no replay controls.", "No run-start UI or seeded scenario selector. Slice 2 is incomplete.", "No node health, local model/policy versions or transfer decisions, and no error states beyond the disconnect label. Slice 3 and the Outcome are unmet.", "Acceptance 2 has only a unit test of the sourceLabel string. No test covers the reconnect behavior. Stale snapshots are kept and dimmed rather than cleared, and nothing re-syncs state after a reconnect.", "Acceptance 3 is only partly met. Run ID and a coverage unit are shown, but nothing is verified by test. The default view is a fixture, so there is no evidence against a real run.", "Command handling is fragile. The revision is fetched only once, so commands may 409 after a status change. The fetch has no response check or handling, and no authentication is handled.", "Nothing is committed or pushed (the handoff is uncommitted), and the task card still says 'waiting'. The contract requires a pushed handoff."]}
- Next issue: Acceptance 1 has no evidence: no browser smoke exists (tests/web is missing) covering start, pause, resume and replay of a real run. The handoff admits this.; Replay is only a label. There is no replay fetch from the events endpoint and no replay controls.; No run-start UI or seeded scenario selector. Slice 2 is incomplete.; No node health, local model/policy versions or transfer decisions, and no error states beyond the disconnect label. Slice 3 and the Outcome are unmet.; Acceptance 2 has only a unit test of the sourceLabel string. No test covers the reconnect behavior. Stale snapshots are kept and dimmed rather than cleared, and nothing re-syncs state after a reconnect.; Acceptance 3 is only partly met. Run ID and a coverage unit are shown, but nothing is verified by test. The default view is a fixture, so there is no evidence against a real run.; Command handling is fragile. The revision is fetched only once, so commands may 409 after a status change. The fetch has no response check or handling, and no authentication is handled.; Nothing is committed or pushed (the handoff is uncommitted), and the task card still says 'waiting'. The contract requires a pushed handoff.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update, round 2 (uncommitted; supervisor commits)
- `apps/web/src/client.ts`: startRun (seed -> POST /v1/runs with Idempotency-Key), sendCommand (re-reads revision each time, one retry on 409), loadReplay (pages /events), 401 -> sign-in form, nodeHealth (derived from topology only). 4 unit tests in `client.test.ts`.
- `App.tsx`: seed + start run, replay toggle with frame slider, snapshot cleared on disconnect (no stale state shown; server re-sends a snapshot on reconnect), errors shown in an alert, per-drone table (link health, policy version / last transfer from `learning_event` messages, else "not reported").
- `tests/web/smoke.mjs`: API-level smoke (start, pause, resume, step, stop, events replay) against a real fixture-backed API; passed locally: `ARCHIPELAGO_API_TOKEN=... uvicorn archipelago_api.app:create_app_from_env --factory` then `ARCHIPELAGO_URL=... node tests/web/smoke.mjs`.
- Still missing: a real browser smoke (no Playwright/jsdom installed; adding deps is out of scope), reconnect test, UI never seen rendered, API does not emit learning events yet, real sim2d run not exercised, task card status not updated.

## Supervisor checkpoint 2026-10-10T06:53:51Z

- Run: 20261010T064958Z
- Machine: B
- Task/branch: T06 / agent/B/20261010T064958Z/T06
- Base: 8a7b9b7b2513cebc87e2aa4a701cbf1e0eb564d0
- Round: 2
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Acceptance 1: no real browser smoke. tests/web/smoke.mjs is an API-level script, not run by the project check. It needs a manually started API and token. Nothing drives the UI. The handoff says no Playwright/jsdom, and the UI has never been seen rendered.", "Acceptance 2: no test covers disconnect/reconnect. client.test.ts has 4 unit tests of client helpers. status.test.ts has 1 test of the label string. The 'cleared on disconnect, re-synced on reconnect' behavior is unverified.", "Acceptance 3: run ID, units and labels are only in App.tsx, with no rendering test. The default view is a fixture, and no real sim2d run was exercised.", "Slice 3 / Outcome: policy versions and transfer decisions depend on `learning_event` messages the API does not emit yet, so the UI shows 'not reported'. Node health is derived from topology only. The Outcome's 'local model versions' is therefore unmet.", "Process: the task card still says 'waiting' with no owner or branch, and the latest handoff is 'none'. The round-2 worker update is uncommitted and unpushed, so the contract's pushed-handoff requirement is not met.", "Command handling and auth were improved (revision re-read, one 409 retry, 401 sign-in form), but this is covered only by unit tests, not against a live API in the project check."]}
- Next issue: Acceptance 1: no real browser smoke. tests/web/smoke.mjs is an API-level script, not run by the project check. It needs a manually started API and token. Nothing drives the UI. The handoff says no Playwright/jsdom, and the UI has never been seen rendered.; Acceptance 2: no test covers disconnect/reconnect. client.test.ts has 4 unit tests of client helpers. status.test.ts has 1 test of the label string. The 'cleared on disconnect, re-synced on reconnect' behavior is unverified.; Acceptance 3: run ID, units and labels are only in App.tsx, with no rendering test. The default view is a fixture, and no real sim2d run was exercised.; Slice 3 / Outcome: policy versions and transfer decisions depend on `learning_event` messages the API does not emit yet, so the UI shows 'not reported'. Node health is derived from topology only. The Outcome's 'local model versions' is therefore unmet.; Process: the task card still says 'waiting' with no owner or branch, and the latest handoff is 'none'. The round-2 worker update is uncommitted and unpushed, so the contract's pushed-handoff requirement is not met.; Command handling and auth were improved (revision re-read, one 409 retry, 401 sign-in form), but this is covered only by unit tests, not against a live API in the project check.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update, round 3 (uncommitted; supervisor commits)
- The committed App.tsx was still the round-1 version (client.ts was unused). Rewrote it to use client.ts: sendCommand, loadReplay + frame slider, 401 sign-in form, errors in an alert. No run-start/seed UI in App yet (startRun exists in client.ts only).
- `status.ts` `liveReducer`: disconnect drops the snapshot, reconnect re-syncs from the next snapshot. New `View.tsx` renders label, run ID, units, per-drone link health.
- `view.test.tsx` (react-dom/server, no new deps): disconnect/reconnect test and label/run-ID/unit rendering test. `tsc` and vitest pass (8 tests).
- Still missing: real browser smoke (no Playwright/jsdom, deps out of scope), seed/start UI, policy versions (API emits no `learning_event`; UI says "not reported"), real sim2d run, task card status.

## Supervisor checkpoint 2026-10-10T06:55:39Z

- Run: 20261010T064958Z
- Machine: B
- Task/branch: T06 / agent/B/20261010T064958Z/T06
- Base: 8a7b9b7b2513cebc87e2aa4a701cbf1e0eb564d0
- Round: 3
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Acceptance 1: no browser smoke exists. The handoff admits there is no Playwright or jsdom. tests/web/smoke.mjs from round 2 is not in the worktree, so no test covers starting, pausing, resuming or replaying a real run, and nothing drives the UI.", "Slice 2: App.tsx has no run-start or seeded-scenario UI. startRun exists only in client.ts and is unused. The handoff states this.", "Slice 3 and Outcome: policy and model versions are hardcoded as 'policy version: not reported' in View.tsx. There is no transfer-decision display. Node health is derived from topology only. The Outcome is unmet.", "Acceptance 2: view.test.tsx tests the reducer through server rendering only. No test covers a WebSocket reconnect or the live-versus-stale behavior in App.", "Acceptance 3: view.test.tsx covers the labels, run ID and units, but only against the fixture. No real sim2d or API run has been exercised.", "Process: the task card still says 'waiting' with no owner or branch. The round-3 work is uncommitted, so there is no pushed handoff."]}
- Next issue: Acceptance 1: no browser smoke exists. The handoff admits there is no Playwright or jsdom. tests/web/smoke.mjs from round 2 is not in the worktree, so no test covers starting, pausing, resuming or replaying a real run, and nothing drives the UI.; Slice 2: App.tsx has no run-start or seeded-scenario UI. startRun exists only in client.ts and is unused. The handoff states this.; Slice 3 and Outcome: policy and model versions are hardcoded as 'policy version: not reported' in View.tsx. There is no transfer-decision display. Node health is derived from topology only. The Outcome is unmet.; Acceptance 2: view.test.tsx tests the reducer through server rendering only. No test covers a WebSocket reconnect or the live-versus-stale behavior in App.; Acceptance 3: view.test.tsx covers the labels, run ID and units, but only against the fixture. No real sim2d or API run has been exercised.; Process: the task card still says 'waiting' with no owner or branch. The round-3 work is uncommitted, so there is no pushed handoff.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update, round 4 (uncommitted; supervisor commits)
- `App.tsx`: seed + "Start run" form (uses `startRun` with the shared run_config fixture, then opens `?run=<id>`).
- `status.ts`/`View.tsx`: stream `learning_event` messages (bare, or under `event`) are kept per node; the drone list shows policy version (`new_version`) and last transfer decision/reason, else "not reported". Dropped on disconnect.
- `view.test.tsx`: new test for the above. `tsc` and vitest pass (9 tests).
- Not done: real browser smoke (no Playwright/jsdom; deps out of scope), no real sim2d/API run exercised against the UI, the API emits no learning events yet so the wire shape of those messages is assumed, task card status untouched (outside reserved paths). `tests/web/smoke.mjs` (API-level start/pause/resume/step/stop/replay) is committed from checkpoint 2.

## Supervisor checkpoint 2026-10-10T06:58:09Z

- Run: 20261010T064958Z
- Machine: B
- Task/branch: T06 / agent/B/20261010T064958Z/T06
- Base: 8a7b9b7b2513cebc87e2aa4a701cbf1e0eb564d0
- Round: 4
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Acceptance 1: there is no browser smoke. tests/web/smoke.mjs is an API-level script that needs a manually started API and token. The project check does not run it, and nothing drives the UI. The handoff says the UI has never been rendered in a browser. No evidence covers starting, pausing, resuming or replaying a real run through the dashboard.", "Acceptance 2: view.test.tsx only exercises the reducer via server rendering. No test covers a real WebSocket disconnect or reconnect in App. The 2s reconnect and re-sync behavior is unverified.", "Acceptance 3: labels, run ID and units are tested only against the fixture. No real sim2d or API run has been exercised. The weakest part of the 'no hardcoded success metrics' check is the 'not reported' placeholders for policy version and transfer decisions.", "Outcome and slice 3: policy and model versions and transfer decisions depend on `learning_event` messages the API does not emit. The wire shape is assumed, so the 'local model versions' display is unproven. Node health is derived from topology only.", "Process: the round-4 work and handoff update are uncommitted, so the contract's pushed-handoff requirement is not met for this state. The task card still says 'waiting', unassigned, with latest handoff 'none'."]}
- Next issue: Acceptance 1: there is no browser smoke. tests/web/smoke.mjs is an API-level script that needs a manually started API and token. The project check does not run it, and nothing drives the UI. The handoff says the UI has never been rendered in a browser. No evidence covers starting, pausing, resuming or replaying a real run through the dashboard.; Acceptance 2: view.test.tsx only exercises the reducer via server rendering. No test covers a real WebSocket disconnect or reconnect in App. The 2s reconnect and re-sync behavior is unverified.; Acceptance 3: labels, run ID and units are tested only against the fixture. No real sim2d or API run has been exercised. The weakest part of the 'no hardcoded success metrics' check is the 'not reported' placeholders for policy version and transfer decisions.; Outcome and slice 3: policy and model versions and transfer decisions depend on `learning_event` messages the API does not emit. The wire shape is assumed, so the 'local model versions' display is unproven. Node health is derived from topology only.; Process: the round-4 work and handoff update are uncommitted, so the contract's pushed-handoff requirement is not met for this state. The task card still says 'waiting', unassigned, with latest handoff 'none'.
- Resume: fetch this branch, inspect latest commit and continue the task card.

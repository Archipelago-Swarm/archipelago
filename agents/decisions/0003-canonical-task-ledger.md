# ADR-0003: Replace branch mail and BOARD.md parsing with a canonical task ledger

## Evidence

During the 2026-10-10 run (agents/reports/LAST_RUN_RETROSPECTIVE.md):
- 19 mailbox messages and 8 `agent/B/mail-*` branches carried status, decisions and "push your branch" requests.
- `driver.py` planned work by regex over `BOARD.md`, wrote 16 "Driver: next overnight plan" commits and re-dispatched blocked tasks (T09 x5, T12 x9, T06 x8).
- "done" was a hand-edited cell (T09 marked done with stub baselines).

## Problem

Two machines could not see dependency, ownership and blocker state without prose, a watcher or a human.

## Root Cause

No canonical, machine-readable, committed task record with explicit ownership and blockers.

## Existing Mechanism

`agent-coordination` branch (active.json plus mailbox), BOARD.md table, task cards, handoffs.

## Proposed Change

`agents/TASKS.yaml` validated by `agents/schemas/task.schema.json` and edited only by `agents/controller.py`. States QUEUED, CLAIMED, ACTIVE, BLOCKED, REVIEW, INTEGRATION, COMPLETE, FAILED. BOARD.md and cards become background. Claim race is resolved by Git push rejection. The mailbox is retired; its remaining use cases map to `blocked_by`, handoffs and ADRs.

## Expected Benefit

Any agent computes runnable work with one command; blocked tasks stop being re-dispatched; completion requires a recorded verifier PASS.

## Risks

Concurrent edits to the same task entry conflict (rare: one writer per task). The ledger can still be wrong if agents bypass the controller; `validate` runs in CI to catch drift.

## Rollback

Restore BOARD.md as the plan source and re-enable the old driver; both are untouched in history.

## Status

ACCEPTED (legacy runner removal is T20; deletion of remote coordination branches awaits human approval)

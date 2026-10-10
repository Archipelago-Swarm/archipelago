# ADR-0007: Agent-startable launcher over a ledger-driven session loop

## Evidence

Operator request (2026-10-10): the scheduler and `night.py` should be startable by agents themselves. Previously a human launched `night.py`, `driver.py` and `watchdog.py` in terminals; `driver-recovery.md` documents restarts by hand. The bootstrap controller deliberately launched nothing.

## Problem

Autonomy needs a way to begin and continue sessions without a person, but detached processes are only valid on machines that stay up, and the old runners plan from BOARD.md and the coordination branch.

## Root Cause

Session starting was never separated from planning; planning lived in the launcher.

## Existing Mechanism

night.py (fixed JSON plan, coordination branch), driver.py (BOARD.md regex), watchdog.py (restarts the driver).

## Proposed Change

`agents/launch.py`: `tick` (one idempotent, locked step), `start` (detached loop of ticks with preflight, heartbeat, single instance, STOP, no-progress cutoff), `status`, `stop`, `schedule`, plus a pass-through to legacy `night.py`. Planning comes only from the shared ledger (`controller.py --remote`, which also serializes claims through Git push rejection). Agents may use it freely within bounds; OS-level job installation stays with the operator's authorization. Cloud sessions use routines that call `tick`.

## Expected Benefit

An agent can begin, observe and end unattended work from the repository alone, and a dead loop is detectable instead of silent.

## Risks

Unverified against a real two-machine run (tests use a fake `claude`); flags copied from night.py; a loop can burn subscription quota on repeated sessions (bounded by max-ticks, slice minutes, no-progress cutoff, deadline); pushing ledger-only commits to main may conflict with branch protection.

## Rollback

Delete agents/launch.py; the controller and ledger work without it.

## Status

ACCEPTED (live trial pending: T23)

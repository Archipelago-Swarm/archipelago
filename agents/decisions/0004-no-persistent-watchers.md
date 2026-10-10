# ADR-0004: No mechanism may depend on a process outliving a Claude session

## Evidence

`tools/agents/mail_watch.py` relied on a background task whose exit was the notification; `tools/agents/idle_watch.py` was an infinite polling loop using `tasklist` (Windows only) and, per its own handoff, its tracked version had never been run. `driver.py` sleeps 60-300 s and up to 90 minutes in loops. `watchdog.py` exists to restart the driver. Their logs are on machines A/B and were not available (UNKNOWN whether they hard-blocked on the night).

## Problem

Cloud/headless Claude sessions cannot guarantee background processes, hidden terminals or timers; local ones need an awake machine and an open terminal.

## Root Cause

Waiting was implemented as polling because state was not readable from Git (see ADR-0003).

## Existing Mechanism

mail_watch.py, idle_watch.py, driver.py, watchdog.py, night.py.

## Proposed Change

Classify automation as RELIABLE / CONDITIONALLY_RELIABLE / UNRELIABLE / UNSUPPORTED (PROTOCOL.md section 13). Removed now: mail_watch.py, idle_watch.py (no tests, no references). Kept as CONDITIONALLY_RELIABLE and scheduled for replacement: night.py, driver.py, watchdog.py (T20) because they have tests and a live run depends on their plan format.

## Expected Benefit

No silent hard-blocks; every wait is either a finished session or a documented human/scheduler action.

## Risks

Less continuous operation until T20 ports the slice launcher; a person or scheduler must start sessions.

## Rollback

`git revert` the removal commit.

## Status

ACCEPTED

# ADR-0006: Use `agents/` for the control plane, not `.agents/`

## Evidence

`CLAUDE.md`, `AGENTS.md`, `tools/check_foundation.py`, `tools/agents/*`, 30+ handoffs and all task cards reference `agents/`.

## Problem

The bootstrap brief names `.agents/`; creating it duplicates sources of truth.

## Root Cause

Brief written without regard to existing layout; the brief itself says to use an established directory.

## Existing Mechanism

`agents/` tree.

## Proposed Change

Place the control plane in `agents/` (TASKS.yaml, OWNERSHIP.yaml, PROTOCOL.md, LESSONS.md, controller.py, schemas/, runtime/, decisions/, reports/). `agents/contracts/README.md` indexes existing contracts instead of copying them.

## Expected Benefit

One tree, no migration of historical links.

## Risks

Divergence from a future `.agents/` convention; trivial to move later.

## Rollback

`git mv agents .agents` plus reference updates.

## Status

ACCEPTED

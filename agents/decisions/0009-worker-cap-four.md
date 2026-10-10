# ADR-0009: Raise the per-machine model-agent cap from two to four

## Evidence

Operator instruction, 2026-10-10 15:23 America/New_York: raise the worker cap above two and double it to four, changing the contract if needed, to ship and deploy a strong, stable system by 01:00 the next morning, with credits budgeted.

## Problem

The critical path (learner -> node runtime -> live integration -> experiments -> deployment) has several independent branches (coordinator, dashboard, experiment-protocol repair, deployment tooling) that two agents cannot cover in the available hours.

## Root Cause

The two-agent cap was a conservative first-run default, never measured (agents/reports/AUTONOMY_READINESS.md: "the last night's 2-per-machine design was never proven").

## Existing Mechanism

`agents/CONTRACT.md` ("Maximum two active coding workers per machine initially, counting any reviewer"), `agents/PROTOCOL.md` section 14 recommendation.

## Proposed Change

Cap is four concurrent model agents per machine, still counting reviewers; coordinators still do not code in parallel with a full roster. Unchanged: no recursive fan-out, exclusive `owned_paths`, integrator-only shared files and merges, required checks before integration, retry and blocker rules, secrets and spend limits.

## Expected Benefit

Independent slices proceed in parallel; wall-clock to a verified live experiment shrinks.

## Risks

More merge conflicts in shared paths, higher model usage, CI queue pressure. Mitigations: disjoint owned paths enforced by the controller, one integration candidate at a time, batched PRs, token spend tracked per wave and a stop rule below.

## Rollback

Restore the sentence in CONTRACT.md and the line in PROTOCOL.md.

## Status

ACCEPTED (explicit operator authorization). Usage guard: pause new dispatch and report if a wave's measured model usage threatens the operator's credit budget; never switch to paid API billing automatically.

## Amendment 2026-10-10 15:40 America/New_York

The operator removed the numeric cap ("you may deploy as many workers as needed") on condition that model usage is planned across the roughly five-hour usage window. The cap is now the integrator's pacing decision under `agents/operations/token-budget.md` (plan, measured consumption, stop rules). The structural rules (disjoint owned paths, integrator-only shared files, required checks, no recursive fan-out, no automatic paid API fallback) are unchanged.

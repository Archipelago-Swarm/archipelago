# Model-usage plan for the live-experiment push (2026-10-10 afternoon to 01:00)

Operator constraint: the subscription's rolling usage window (about 5 hours) must not be exhausted before the deployment is stable. The operator removed the fixed worker cap (ADR-0009 amended) and delegated the pacing decision to the integrator.

## What is measured so far (this session)

| Wave | Agents | Subagent tokens (reported) | Per agent |
|---|---|---|---|
| T10 gap fan-out 1 | 8 (4 impl + 4 review) | about 549k | about 69k |
| T10 persistence fan-out | 4 (2 impl + 2 review) | about 287k | about 72k |

Large implementation tasks (learner, node runtime, coordinator) are heavier than those gap fixes; the planning figure below assumes about 2-4x per implementation agent.

## Plan (tokens are estimates, replaced by measurements after each wave)

| Item | Agents | Est. subagent tokens |
|---|---|---|
| T26 learner, T27 node runtime, T28 coordinator (impl + review + one repair) | up to 9 | 1.2M |
| T32 experiment repair, T33 dashboard, T34 ops tooling | up to 7 | 0.8M |
| T29 live integration (API, compose, e2e) | up to 4 | 0.6M |
| T30 pilot and sweep protocol | up to 4 | 0.6M |
| Bootstrap/agreement verification, T25, ledger housekeeping | up to 4 | 0.3M |
| T37 variant study, T38 live adoption | up to 6 | 0.7M |
| Repair and CI-fix reserve | - | 0.6M |
| Deployment (T31) and evidence | up to 3 | 0.4M |
| Total planned | | about 5.2M |

The integrator session itself is the other consumer; keep its own turns short and avoid re-reading large logs.

## Pacing rules

1. Dispatch in dependency order; run at most the number of agents that have disjoint owned paths and ready work. More agents only when each has a distinct ready task; never to keep slots busy.
2. After every wave read the reported subagent token total and update the table above. If cumulative subagent usage exceeds 60% of the plan before T29 integrates, shrink scope: drop optional reviewers' second rounds (not first-pass independent review), defer T25, T17 and T19, and reduce experiment sweep size.
3. Workers read only the files they need, run targeted tests during work and the full non-Docker suite once at the end, keep handoffs concise, and never re-run unchanged expensive checks.
4. One bounded repair round per task before the integrator decides; a second repair only for a defect that blocks the critical path.
5. Durable state first: every task has a handoff and a ledger entry, branches are pushed at milestones, so a provider rate limit pauses work and a fresh session resumes from the repository. On a confirmed rate limit stop dispatching, commit state, and wait outside the model for the reported reset; never switch to paid API billing.
6. If the critical path (T26 -> T27 -> T29 -> T30) is at risk, spend on it first: cut T33 polish, T25, T17 and the second Vultr host before cutting T26-T30 verification.

## Measured after wave 2 (T32/T33/T34)

8 agents, about 757k subagent tokens (about 95k per agent); 201 tool uses; 23 minutes wall. Cumulative subagent tokens this session: about 1.6M plus the still-running T26/T27/T28 chains.

## Measured after wave 1 (T26/T27/T28 + T22/T24 verification) - 2026-10-10 16:10 America/New_York

12 agents, about 1.44M subagent tokens (about 120k per agent; 322 tool uses; 45 min wall). Cumulative subagent tokens: about 549k + 287k + 1,437k + 757k = 3.03M, plus wave 3 in flight. That is past the 60% trigger of the 5.2M plan before T29 integrates, so scope is tightened:

1. One reviewer pass per task; a re-review only when the repair touched behavior, not for lint or doc findings.
2. T27 repair, T29, T37, T38, T30 each get a single focused worker with a tight reserved-path prompt; no broad-spec reviews again.
3. T25, T17, T19, T21, T11 and the second Vultr host are deferred unless the critical path finishes early.
4. Subagent prompts forbid repository surveys; workers get exact files to read.
Remaining planned subagent spend: about 2.3M (T27 repair 0.3M, T37 0.4M, T38 0.4M, T29 0.5M, T30 0.4M, T31 0.3M). If usage nears the window limit, durable state is already in the ledger/handoffs; stop dispatching, commit, and wait for the reset.

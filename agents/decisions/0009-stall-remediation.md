# ADR-0009: Stop path locks, dead roles and phantom claims from stalling the ledger

Status: accepted (reversible; revert the commit to roll back)

## Evidence

`controller.py status` on the ledger at ab8b93b (2026-10-10 20:20Z): 16 QUEUED, 2 CLAIMED, 1 BLOCKED, 1 REVIEW, 11 COMPLETE; exactly one task (T19, priority 5) runnable.

- 9 of 16 queued tasks reported "owned_paths overlap an in-flight task". The holder was T22, the control-plane bootstrap, in `REVIEW` with 20 path patterns (`.github/**`, `scripts/**`, `Makefile`, `tests/agents/test_controller.py`, `tests/infra/**`, `agents/launch.py`, ...). Its work was already merged (PR #8) but it could not leave `REVIEW`: `OWNERSHIP.yaml` gave the verifier role only to machine B, and `launch.py pick_work` hands `REVIEW` only to that machine. T20, T23, T25 depend on T22 `COMPLETE`.
- T26 and T28 were `CLAIMED` 70 minutes with no branch on origin and the seed handoff unchanged. Nothing reaps a claim, so they held both worker slots of machine A and the paths of T17/T30 and T29.
- `pick_work` resumes "own CLAIMED/ACTIVE" first and `tick_lock` is one lock per machine, so the second claimed task is never worked while the first exists; CONTRACT allows two workers per machine but the launcher ran one.
- Four tasks wait on a human (T10, T18, T23, T31) with no proposed default, which L-006 requires.
- T29 (10 path patterns, half the repository) and T22 (20) are larger than a few 30-minute slices.
- T24 (interface agreement and registration) is QUEUED although its content was merged in 5ac3f6e and d30d299.

## Root Cause

Locks were held by state (`IN_FLIGHT`) instead of by activity; a role was tied to a machine instead of a capability; claims had no liveness; worker parallelism was promised in CONTRACT but not implemented in the launcher.

## Change

1. `RESERVING = {CLAIMED, ACTIVE}` holds paths; `REVIEW`/`INTEGRATION` do not. `agents/TASKS.yaml` is excluded from overlap checks. A claim warns when an unmerged REVIEW task touches the same paths.
2. `controller.py reap`: CLAIMED idle > 60 min or ACTIVE idle > 180 min (ledger entry and `origin/<branch>` both silent) returns to QUEUED with a `claim_expired` event. The orchestrator tick runs it before choosing work.
3. `roles.verifier: [B, A]` and list-valued roles in `machine_may`/`pick_work`. `verify` rejects a verdict whose verifier equals the task owner.
4. `launch.py tick --slot w1|w2`: per-slot lock/log; slot ticks only resume `<machine>/<slot>` tasks or claim into a free slot (cap 2); the slot-less tick verifies and integrates.
5. `runnable` orders by priority, then by downstream tasks unblocked. New read-only `controller.py stalls` (reason and actor per task, oversized tasks, slot use) and `plan` (conflict-free batch for free slots).
6. PROTOCOL sections 2, 3, 14; CONTRACT slot/claim wording; LESSONS L-013..L-015.

## Expected Benefit

On the current ledger: runnable tasks go from 1 to 4 (T14, T16, T19, T24); T26 and T28 are reaped unless a worker pushes; T22 can be verified by an A verifier tick, which unlocks T20/T25 and, after T23's human gate, the launcher trial.

## Risks

- Two tasks edit the same files while one waits in REVIEW: conflicts surface at integration (`integrate-fail`) instead of at claim time. Mitigated by the claim warning, priority-ordered merges and `check-integration` after each merge.
- A slow but healthy worker is reaped after 180 silent minutes; its branch and handoff are kept, so the cost is a re-claim.
- A and B both verifying: independence rests on the verdict naming a verifier different from the owner, not on a different machine.
- Not exercised against a real two-slot run of `claude -p`; tests use the pure `pick_work`/ledger paths.

## Rollback

Revert the commit; ledger files are unchanged in shape (new `claim_expired` history events are ignored by old code).

## Addendum: cloud-only deployment (operator, 2026-10-10)

Machines A and B no longer exist; all agents are Claude cloud sessions. Roles are held by the `cloud` pool (`"*"`), `machine` accepts `cloud`, `--machine` defaults to `cloud`, QUEUED tasks lost their machine preference, worker cap is 3 for the pool, `launch.py prompt` lets an orchestrator session dispatch via `create_session`, and T23 is retargeted to a cloud trial (its two-machine human gate is replaced by the ledger-branch protection decision).

## Not changed (needs a human)

T10/T31 spend and credentials, T18 public-contract change (Pose.z, takeoff/land), T23 ledger-branch protection. Proposed defaults: T18 accept ADR-0002 option "z is optional, default 0, takeoff/land additive commands"; T23 allow ledger-only commits from the agents' identity on `main`.

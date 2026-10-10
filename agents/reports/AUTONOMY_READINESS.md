# Autonomy readiness

As of the control-plane bootstrap (2026-10-10). Items are labeled **implemented**, **convention** (documented rule, not enforced), **future**, or **unsupported**.

## Implemented

- Canonical ledger `agents/TASKS.yaml` (21 tasks: T01-T13 legacy states with honest notes, T14-T21 real outstanding work) validated against `agents/schemas/task.schema.json`; ownership map `agents/OWNERSHIP.yaml`.
- `agents/launch.py`: pick, tick, start (detached loop or legacy `night.py` pass-through), status (ALIVE/STALLED/DEAD), stop, schedule; `controller.py --remote` publishes ledger changes as fast-forward commits so two machines cannot claim the same task (tested with two clones of a bare origin, including a push race). 9 tests in `tests/agents/test_launch.py`.
- `agents/controller.py`: validate, status, next, deps, claim, start, review, requeue, record-failure, block, unblock, verify, integrate-fail, complete, log-event, review-process, report. Enforces: legal transitions; runnable = deps COMPLETE + no `blocked_by` + no in-flight path overlap; handoff before start; commit before REVIEW; PASS verdict must cover every acceptance command at the verified commit; retry budgets and same-signature cutoff auto-BLOCK; BLOCKED needs a complete `BLOCKER.md`; only the integrator machine can `complete`; COMPLETE only from INTEGRATION. 14 behavior tests in `tests/agents/test_controller.py`.
- Verdict and run-summary schemas (`verification.schema.json`, `run.schema.json`); templates for blocker and verification.
- Tiered validation: `make check-fast`, `check-integration` (no Docker needed), `check-full`; `docker` pytest marker; CI concurrency cancel, fast job first, container build only on main or a `full` label.
- Retrospective, lessons L-001..L-012, ADRs 0003-0006, PROTOCOL.md. Removed `mail_watch.py`, `idle_watch.py`, the watcher handoff, and the standalone `foundation.yml`.

## Existing validation (verified in this session)

`make check-fast` passes (foundation docs, ledger, ruff, 33 agent tests). `SKIP_DOCKER=1 make check-integration` passes in 33 s (ruff, mypy, contract drift, non-Docker pytest, web gen/lint/typecheck/24 Vitest tests/build). `controller.py validate` passes on the real ledger.

## Not verified

- The new `ci.yml` has not run on GitHub; first push is its test. Docker-marked tests, `make check-full`, the container build and the pybullet tests were not run here (no Docker daemon).
- No live agent was driven through a full ledger cycle; the lifecycle is exercised by unit tests only. No real verifier ran.
- Whether `mail_watch`/`idle_watch`/driver actually hard-blocked on the night is UNKNOWN (logs are on machines A/B).

## Remaining gaps

1. `agents/launch.py` (added after the first bootstrap commit, ADR-0007) lets an agent or person start a ledger-driven session loop (`start`), run one step for a scheduler (`tick`), and inspect or stop it. It is covered by tests with a fake `claude` and local git remotes only. It has never driven a real `claude` session, never run on two machines, and its `claude` flags are copied from `night.py` and unconfirmed. Live trial: T23 (currently blocked on a human providing the two machines). It does not wait through provider limits and does not restart a dead loop by itself. In ephemeral cloud sessions a detached loop is not viable; use a routine that calls `tick`.
2. Legacy `driver.py`, `watchdog.py`, `night.py` and the `agent-coordination` branch still exist and still read BOARD.md/the old plan. Do not run them alongside the ledger.
3. The verifier and reviewer are roles with a schema and a controller gate, not automated agents. A verdict is only as good as the verifier session that wrote it.
4. CI minutes, merge-conflict counts and idle time are not collected automatically (run summary fields are `UNKNOWN`).
5. Invariant tests (monotonic sim time, unique ids, negative latency, destroyed-node actions) are partly covered; no dedicated suite. They belong to each domain's tasks.
6. Task cards for T14+ do not exist by design; acceptance is in the ledger.
7. Acceptance commands in legacy COMPLETE entries are coarse (`pytest tests/<area>`), not the original card checks.

## Lessons from the previous run

See `agents/LESSONS.md`. Main ones: state in a file, no persistent watchers, implementation is not completion, a missing verdict is not a task failure, blockers must be machine-readable, one branch per task.

## Removed / simplified band-aids

Removed: `mail_watch.py`, `idle_watch.py`, watcher handoff, `foundation.yml`. Simplified: `check.sh` tiers, CI. Retired by design, deletion pending T20: mailbox/coordination branch, driver, watchdog, BOARD.md planning. Not touched without human approval: remote branches (`agent-coordination`, `agent/B/mail-*`, 6 superseded T06 branches).

## Unsupported automation identified

Background watchers, polling daemons, tasks whose exit is the notification, timers inside cloud sessions, any process expected to outlive a session, and an LLM verdict parsed from free text as the only gate. The controller does not claim any of these.

## Recommended agent count

Two concurrent workers at most (one per machine) plus the verifier and integrator working in the gaps between claims. The ledger can hold more; shared-path contention (`pyproject.toml`, lockfiles, `.github/**`) and the single integrator are the limit, and the last night's 2-per-machine design was never proven.

## Safe overnight tasks (reversible, in-repo, no credentials)

First complete T22 (the bootstrap itself, in REVIEW): it holds `.github/**`, `scripts/**` and the `docker` test markers, so the ledger correctly keeps T14, T16 and T20 unrunnable until T22 is COMPLETE. Then:

T14 persist run events (A); T16 browser smoke in CI (B; workflow file needs the integrator to merge); T20 runner retirement (A; keep the old runner until a live `claude -p` trial passes); T19 card reconciliation (A). Then T15 and T21 once T14 lands. T17 is safe if the compute cap in its description (CPU-only, 45 min per sweep) is accepted.

## Not safe overnight

T10 (needs Vultr and TigerData credentials and spend), T18 (public contract change needs ADR approval), deleting remote branches, anything that deploys, T11 (waits for T10 and T17).

## Suggested machine allocation

A: orchestrator, integrator, runtime/API (T14), agents infrastructure (T20, T19), 3D (T18). B: verifier, reviewer, CI/testing (T16), telemetry (T15, T21), learning (T17). Only A runs `claim`, `complete`, `integrate-fail`.

## CI bottlenecks

Previously: full suite on every push of every branch, no cancellation, Docker tests mixed with lint, docs check running on all branches. Now: concurrency cancel, `fast` gate, one full job per PR, container build restricted. Remaining: `bootstrap` still runs Docker tests on every PR push (kept so Docker regressions are caught before merge); add path filters once T16 lands if it proves slow. Actual minutes are UNKNOWN until job logs are sampled.

## Human intervention risks

Credentials and spend (T10); the contract ADR (T18); the ledger-branch protection decision (agents publish state-only commits to `main`; T23); an unconfirmed `claude` flag set for unattended runs; permission-classifier denials with exit 0 (4 occurrences last night; permission policy for unattended runs is not configured here); Windows/WSL environment differences on the A/B machines.

## Highest-priority next improvement

T23: a supervised trial of `launch.py` on both machines, running one task end to end (claim, work, verify, integrate) with `log-event` counting every human touch. Until that trial, the claim "autonomous multi-hour operation" is not demonstrated.

---

# Comparison with the previous night

| Question | Answer |
|---|---|
| Would the watcher hard-blocks still occur? | The two removed watchers cannot. `driver.py`, `watchdog.py` and `night.py` remain and are CONDITIONALLY_RELIABLE; if run they can still stall. The new `launch.py start` is also CONDITIONALLY_RELIABLE but reports STALLED/DEAD instead of failing silently. **Gap: T20 deletes the legacy runners after the T23 trial.** |
| Is branch mail still necessary? | No. Dependencies, blockers, ownership and decisions are ledger fields, handoffs or ADRs. The old branch and messages remain as history; deletion needs a human. |
| Can a stopped agent be resumed from repo state? | Yes by convention and structure: ledger entry, task branch, `last_good_commit`, handoff, optional CHECKPOINT. Not tested with a real interrupted session. |
| Can a verifier independently reject incomplete work? | Yes at the gate: `verify` FAIL returns the task, PASS requires every acceptance command at the verified commit, COMPLETE needs the integrator. The verifier's thoroughness itself is not automated. |
| Do repeated failures auto-BLOCK? | Yes for failures recorded through `record-failure`/`verify`/`integrate-fail` (same signature twice, per-kind budgets). A worker that never records failures bypasses it; that is a convention. |
| Can the system tell unsupported automation from implementation bugs? | Partly. Reliability classes exist and `log-event unsupported_automation` is counted by `review-process`; a missing verdict is explicitly "verifier infrastructure". Detection is manual; nothing auto-classifies a failure. |
| Can it learn durable lessons? | Yes: LESSONS.md, ADR format, `review-process` triggers, run summaries. Triggering the review is a convention until a scheduler exists. |
| Did coordination complexity decrease? | Yes in mechanisms: two ledgers + mailbox + three long-running scripts -> one ledger + one CLI, 2 files and 1 workflow removed. Added: 1 controller (about 900 lines), 1 launcher (about 500), 3 schemas, PROTOCOL. Net complexity falls fully only after T20 deletes the legacy runner. |

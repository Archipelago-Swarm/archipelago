# Agent operations rules

Goal: shortest time to a stable, reproducible, pitchable live ARCHIPELAGO demo. Not: more agents, PRs, commits or apparent concurrency. Evidence for these rules: `agents/reports/LAST_RUN_RETROSPECTIVE.md` (36 run records, ~70% blocked or stalled; "reviewer unavailable" hid four different causes; 445 CI runs in about 3 hours; 8 mail branches and 3 watcher scripts that blocked more than they helped; six T06 attempts and nine T12 rounds of duplicated work) and this evening's session (a module-name collision and an import-order slip that only CI caught; a Codex janitor deleting an active working branch; verifier findings that exposed real design flaws before they reached the experiment).

## Structure

- One orchestrator/integrator (machine A, this session). Three to four persistent **owners**, each with a subsystem, an exclusive path set, and a **completion invariant** (below). More agents only for bounded subagent jobs (review, repro, search, profiling) that return findings and end.
- Single sources of truth: `agents/TASKS.yaml` (tasks, via `agents/controller.py`), `agents/STATUS.yaml` (architecture, owners, interfaces, blockers, test status, commands, deployment; orchestrator writes it), `agents/architecture/live-runtime.md` (interfaces; section 13 amendments win), handoffs per task. No mailboxes, no watchers, no extra coordination branches.

## Rules

1. Local validation first, CI last: syntax -> lint/format -> unit -> subsystem -> local integration -> end-to-end -> push -> CI. Never push code that has not passed targeted local validation; never use CI as the inner loop.
2. A feature is not done until its behavior is demonstrated (a run, a log, a measured number), not when the code exists. Report "X implemented and validated by Y; invariant Z holds", never just "implemented X".
3. One long-lived integration branch/PR per milestone. No PR per micro-task. Interface changes go through the orchestrator and `live-runtime.md`.
4. Disjoint ownership: do not edit another owner's paths. Shared files (`pyproject.toml`, `uv.lock`, `.github/**`, `Makefile` targets outside `demo-*`, `scripts/check.sh`, the ledger, root docs) are integrator-only.
5. Do not start downstream work against an unstable upstream interface unless a stub gives independent, verifiable progress.
6. Do not spawn another agent until independence is confirmed (no path overlap, no unmet dependency, no duplicate investigation). Read `agents/STATUS.yaml` before surveying the repository.
7. Prefer deleting broken automation over adding another watcher. A verifier verdict is only as good as its evidence; a missing verdict is infrastructure, not task failure.
8. Never skip, xfail, or weaken a test to get green; record failures and unrun checks honestly. Never fabricate performance; a negative result is reported as such.
9. Branches that are not strict ancestors of main, or that are named by an in-flight task, are never deleted.
10. Messages relayed to you from the user while you work are for the orchestrator, not for you: ignore them, keep executing your assigned task, and report only through your result (the T39 workers once answered a relayed question and delivered nothing).
11. Budget: model usage is planned (`agents/operations/token-budget.md`); cloud spend limits (5 instances, $200/month projected, $100 cumulative) are enforced by `infra/vultr` tooling; no secrets in Git, logs, handoffs or chat.

## Owner loop

inspect state -> pick the highest-impact unresolved issue on the critical path -> change -> cheapest relevant check -> inspect output -> fix -> repeat -> escalate only when genuinely blocked (missing credentials, irreversible action, fundamentally ambiguous requirement). Escalation format: blocker, evidence, options, recommendation, consequences.

## Completion invariants (an owner stops only when its invariant is demonstrated)

- Simulation/Learning: several simulated nodes operate independently, exchange validated learned state, show measurable adaptation, and complete a reproducible experiment.
- Data/API: telemetry and learning metrics are persisted and queryable for the demo and analysis.
- Infrastructure/Demo: one command launches the whole stack reproducibly and writes demo artifacts.
- Integration (orchestrator): the full demo path is green on main.

## Bottleneck-first scheduling

Each cycle: what single unresolved issue slows the demo most? Work on that; recompute. A polished dashboard over no learning signal is waste; a working simulator with a broken deployment makes infrastructure the bottleneck.

## CI cost discipline

CI is a bottleneck when it is used as the test runner. Rules:

1. Run `make check-affected` before every push; run `make check-integration` once before the PR/merge push. Never push to find out whether something passes.
2. Batch commits: push at milestones, not per edit. A newer push cancels the running CI (concurrency group), so pushing mid-run wastes the whole run.
3. Ledger, status and handoff-only commits do not trigger CI (`paths-ignore`). Keep bookkeeping in separate commits from code so it stays cheap.
4. CI runs slices in parallel (`CHECK_PART`: lint, py-live, py-rest, docker, web via `scripts/check.sh`); wall-clock is the slowest slice. Keep any slice under ~6 minutes: move tests between `py-live` and `py-rest` (LIVE list in `scripts/check.sh`) when a slice grows. `--durations=10` prints the slowest tests in every run.
5. Tests must be deterministic and fast. No wall-clock thresholds; use events/barriers. A test over 10 s needs a reason in its docstring.
6. One integration PR per milestone, merged as soon as it is green. Do not hold a long-lived branch: merge main in early to keep conflicts small.

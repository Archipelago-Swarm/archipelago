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

# Context for Codex (and any other non-Claude) agents

Read this first if you start in this repository without a task prompt. It is kept current by the integrator (Claude, machine A). Last updated 2026-10-10 20:00 America/New_York.

## What the project is

Archipelago: a simulator and research demo of decentralized learning for simulated drones (robotic exploration/search/coverage; no real vehicles). Goal for tonight: a **live** experiment on Vultr with TigerData persistence and an authenticated dashboard, in which four containers each run their own PyTorch policy, act in one 2D world, exchange validated model candidates over a partitionable peer network, and produce reproducible evidence. Deadline: stable deployment by about 01:00 America/New_York. A replay, an infrastructure-only demo, or green CI does not meet the goal. Interface agreement: `agents/architecture/live-runtime.md`. Experiment protocol: `agents/architecture/evaluation.md`.

## Where state lives (one system, do not create another)

- `agents/TASKS.yaml` is the only task registry. Read it with `python agents/controller.py status` and `next`. Only the integrator edits it (via `controller.py`). `agents/tasks/BOARD.md` is background only.
- Per task: `agents/handoffs/<ID>/LATEST.md` on the task branch. Process rules: `agents/PROTOCOL.md`, `agents/CONTRACT.md`, `AGENTS.md`.
- No mailbox, no watchers, no extra coordination branches (ADR-0003/0004). To tell the integrator something, write it in your handoff and push your task branch; for urgent coordination add a short comment on the task's draft PR.

## How to take work

1. Do not self-assign. Tasks already claimed in the ledger belong to their owner; check `owner` and `owned_paths` before touching anything.
2. Run `python agents/controller.py next --machine A` for runnable unclaimed tasks, then tell the integrator which task you propose (a draft PR titled `[propose T<ID>] ...` is enough). Do not start until the ledger shows it CLAIMED by you.
3. Stay inside the task's `owned_paths`. Shared files (`pyproject.toml`, `uv.lock`, `.github/**`, `scripts/**`, `Makefile`, `agents/TASKS.yaml`, root docs) are integrator-only.
4. Push only your task branch (`agent/<ID>-...`). Never push to `main`. The integrator verifies independently and merges.

## Current assignments (so you do not duplicate work)

| Task | Owner | Paths |
|---|---|---|
| T26 PyTorch learner | Claude worker | packages/learning, tests/learning |
| T27 node runtime | Claude worker (after T26) | packages/node/runtime, tests/noderuntime |
| T28 coordinator | Claude worker | services/coordinator, tests/coordinator, packages/adapters/sim2d, tests/sim |
| T32 experiment protocol repair | Claude worker | experiments, tests/experiments |
| T33 dashboard live panels | Claude worker | apps/web, tests/web |
| T34 Vultr/TigerData ops tooling | Claude worker | infra/vultr |
| T35 Grafana dashboards | Codex (prompt: agents/operations/codex/T35.md) | observability, tests/observability |
| T36 telemetry ingest endpoint | Codex (prompt: agents/operations/codex/T36.md) | services/api/.../telemetry.py, tests/api/test_telemetry_ingest.py |

## Safety rules that apply to every agent

- **Never delete a remote branch** unless it is a strict ancestor of `origin/main` (checked immediately before), it is not named in the ledger by an in-flight task (CLAIMED/ACTIVE/REVIEW/INTEGRATION), and it is not `claude/*`, `agent/T*` or `worktree-*`. Branch cleanup is a task for the integrator. (An earlier cleanup deleted the integrator's working branch; it was recovered.)
- No secrets in Git, logs, handoffs or PR text. Cloud credentials come from the environment only. No cloud spending: Vultr limits are 5 instances, $200/month projected, $100 cumulative; only the deployment task (T31) may touch Vultr after an approved plan.
- Never skip, disable or weaken a test to get green; record failures and what you could not run.
- Be economical with model usage; there is a shared usage budget (`agents/operations/token-budget.md`).

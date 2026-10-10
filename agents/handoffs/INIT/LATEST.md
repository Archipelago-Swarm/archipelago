# INIT: repository foundation handoff

- State: foundation authored and locally validated; publication verified by the initialization completion record
- Date: 2026-10-10
- Authoring role: initial architecture/setup agent
- Target: Archipelago-Swarm/archipelago, initially empty remote repository
- Assignment generation: initial bootstrap; runtime ledger not created yet
- Last good application commit: none; no application is implemented

## Completed

Created vision/roadmap, technical architecture, interfaces, evaluation plan, root Claude/Codex entrypoints, agent contract, two-computer runbook, run configuration template, twelve task cards, handoff/ADR/run templates, PR template, and a documentation/dependency validation check with GitHub Actions workflow. Secret/binary ignores and line endings are initialized.

The prior project discussion was read to recover the local-learning/P2P/partition direction. Its downloadable long-form roadmap was unavailable locally; this pack is a new concrete implementation plan based on that discussion and the user's latest requirements.

## Deliberate defaults

Computer A dispatches/integrates; B leads platform/product. Two worker slots per machine; no nested worker fan-out. Main application stack uses Vultr + Docker, TigerData + Grafana, Python/PyTorch/PettingZoo/FastAPI and React/Canvas. Baseline mission is synthetic disaster-area search/coverage. First 3D spike is an isolated gym-pybullet-drones adapter; Gazebo/PX4 follows.

## Pending

All T01-T12 implementation acceptance checks remain unchecked. Supervisor, cross-computer ledger, simulator, learners, web app, database, cloud resources and deployment are not running. No training results exist. No paid work or cloud provisioning has been launched.

## Validation

From the repository root, `python tools/check_foundation.py` passed: 29 Markdown files, twelve task cards, required sections, internal links, acyclic dependencies and conservative example configuration. `git diff --check` passed on the tracked state; staged whitespace validation is required immediately before the initial commit. These checks validate the foundation only, not application behavior. GitHub Actions execution must be distinguished from the locally executed check.

## Recovery

1. Clone/fetch the published repository and read root CLAUDE.md.
2. Both operators set machine identity, run window, budgets and approved permissions in an ignored runtime config.
3. Computer A runs T01 with agents/START_HERE.md; B prepares access/tools and waits for T01's schema gate.
4. Implement/test T02 before unattended runs. Run a supervised cross-computer recovery trial.

Exact initial publication SHA and local validation evidence are recorded in the completion response; future checkpoints use the dispatcher ledger. Do not assume the existence of GitHub access through one connector proves or disproves local Git authentication: during setup, the connector returned 404 but local authenticated Git cloned the empty repository successfully.

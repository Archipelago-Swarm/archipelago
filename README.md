# Archipelago

Decentralized learning for simulated drone swarms: each node observes, acts, learns locally, and exchanges knowledge with its neighbors. Start in 2D; expand through a simulator adapter into open-source 3D drone physics.

**Current state:** repository and agent planning foundation. The simulator, learners, deployment, and overnight supervisor are tasks to implement; they are not operational yet. No benchmark results are claimed.

## Start here

1. Read [the vision and roadmap](agents/vision/roadmap.md).
2. Give Claude [the initialization prompt](agents/START_HERE.md).
3. Follow [the two-computer runbook](agents/operations/overnight.md).
4. Track work through [the task board](agents/tasks/BOARD.md) and individual task files.

The complete agent contract is in [agents/CONTRACT.md](agents/CONTRACT.md), loaded by the root `CLAUDE.md` and `AGENTS.md` entrypoints.

## Required stack

- **Vultr:** deployed application, simulation containers, Grafana, and eventual artifact storage/GPU workloads.
- **Docker Compose:** local development and the initial Vultr deployment.
- **TigerData / TimescaleDB:** durable relational and time-series data; **Grafana** queries it for observability.
- **Python 3.12, PyTorch, NumPy, PettingZoo, FastAPI:** simulation, local learning, peer transport, and application API.
- **TypeScript, React, Vite, Canvas:** live 2D dashboard; later Three.js for a 3D view.
- **GitHub:** source, pull requests, CI, and durable coding-agent coordination.

See [architecture](agents/architecture/core.md) for boundaries, [contracts](agents/architecture/interfaces.md) for interfaces, and [evidence](agents/architecture/evaluation.md) for the experiment design.

## First operator actions

Both developers clone this repository and authenticate their own Claude/GitHub accounts. Assign your computer `A` and your friend's `B`. Fill out [the run configuration](agents/operations/run-config.example.json) together, agree on cloud and model budgets, then have computer A perform bootstrap task T01. Once A has pushed a validated T01 review commit, B can start T04 provisionally against that commit while A completes CI and merges it.

No credentials belong in Git. No cloud resources or paid agent runs have been created by this initialization. License choice remains an owner decision before a public open-source release.

Validate this planning foundation with `python tools/check_foundation.py`. Application install/run commands will be established and documented by T01.

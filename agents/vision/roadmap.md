# Archipelago vision and roadmap

Status: design baseline, 2026-10-10. Implementation has not started.

## Vision

**A swarm in which every node can learn locally, improve through its peers, and keep operating when the network splits.**

The earlier project discussion established local actor/learner/memory ownership, P2P knowledge propagation, partition recovery, and evidence-based comparisons. This document turns that direction into an implementable plan. The initial mission choice is cooperative search and coverage of a synthetic disaster area, giving the team visible utility and measurable outcomes without needing real drone hardware.

Each drone searches an unknown region for simulated rescue markers, avoids obstacles, and budgets movement energy. Radio links depend on range and a seeded fault schedule. When links disappear, drones keep acting and learning from their own experience. Reconnection allows compatible learning updates to flow again. The central visual is **connected swarm -> separated islands -> independent adaptation -> reconnection -> measured knowledge transfer**.

This is a research hypothesis, not a promised win. More nodes may improve coverage but may also increase interference, compute cost, or communication. Report those tradeoffs.

## Non-negotiable outcomes

| Must have | Acceptance evidence |
|---|---|
| Executable 2D world | Seeded reset/step/replay; obstacles, local sensing, coverage, energy and termination |
| Independent node state | Separate policies, buffers, optimizers and checkpoint volumes; no shared mutable model |
| Actual learning | Training changes parameters and behavior; fixed-policy controls distinguish learning from map sharing |
| Actual peer transfer | Trace sender/version/bytes/recipient, accepted or rejected candidate, and downstream policy version |
| Partitions and reconnection | A seeded cut removes only intended peer links; both islands continue; recovery is bounded and deduplicated |
| Honest baseline comparisons | Same scenario, seeds, observation budgets, training budget, and defined network failure conditions |
| Durable experiment records | TigerData run metadata/time series; immutable replay/checkpoint artifacts with hashes |
| Usable dashboard | Run controls, map, links, local model versions, failures, metrics, live/replay labels |
| Vultr deployment | Dockerized smoke test over authenticated HTTPS, restart recovery, recorded image/commit and rollback |
| Recoverable coding work | Every task has ownership, evidence and pushed Markdown handoffs |
| 3D expansion boundary | Adapter contract separates mission logic, physics, policy encoding and rendering |

## Stack decisions

| Layer | Decision | Purpose |
|---|---|---|
| Deployed compute | Vultr Cloud Compute | Host initial container stack; size after measuring a 4-node run |
| Packaging | Docker + Compose v2 | Reproducible local/Vultr environments and per-node isolation |
| Persistent database | TigerData managed TimescaleDB/PostgreSQL | Runs, events, time-series metrics; local TimescaleDB Docker image for development |
| Dashboards | Grafana on Vultr, PostgreSQL data source | Read-only operational and experiment queries against TigerData |
| Simulation | Python 3.12 + NumPy + PettingZoo Parallel API | Seeded simultaneous-action 2D environment |
| Learning | PyTorch, small DQN first | CPU-friendly independent discrete-action learners and bounded peer mixing |
| API and networking | FastAPI/Pydantic + HTTPX; REST and WebSocket | Typed API, direct peer endpoints, live state |
| Web UI | Node 22 baseline, TypeScript + React + Vite + Canvas | Fast live/replay demo; lock exact compatible package versions in T01 |
| Data access | Psycopg + SQL migrations | Small explicit relational/time-series schema |
| Testing | pytest, Ruff, mypy; Vitest/Playwright | Core behavior, contracts, UI smoke, integration |
| Repository | GitHub + Actions | Branches, CI, reviewed integration and agent ledger |
| 3D first spike | gym-pybullet-drones / PyBullet | Headless drone physics adapter; pinned upstream revision and license record |
| 3D later | Gazebo + PX4 SITL | Higher-fidelity flight stack after the learning experiment works |
| Optional presentation | Remotion + Three.js | Measured replay video and 3D rendering, after core gates |

Vultr hosts application infrastructure; TigerData is the deliberate database exception. Do not substitute another hosted database/cloud. Local replay files and per-node in-memory buffers are not extra database services. Add Vultr Object Storage when artifacts outgrow mounted disk. Defer Kubernetes, Redis, Ray/RLlib, vector databases, LLM-per-drone control, model sharding and elaborate service meshes until a measured requirement justifies them.

## Delivery gates

### G0: Foundation and coordinated development

T01-T02: executable project scaffold, contract fixtures, CI, single integration owner, isolated worktrees, pushable checkpoints, bounded supervisor, restart/rate-limit tests. Two machines must prove they cannot claim the same task before unattended fan-out.

### G1: End-to-end 2D demonstration

T03-T06: four rule-based drones run a seeded mission; dashboard displays authoritative state; peer messages obey topology; pause/step/reset/replay work. Local containers run from one documented command. This milestone proves plumbing and remains useful if training is slow.

### G2: Decentralized learning

T07: local DQN learners with separate state, independent baseline, bounded knowledge transfer, compatibility gates and rollback. Demonstrate a small controlled transfer test and record actual outcomes. Shipping state sharing alone does not pass this gate.

### G3: Persistence, evidence and deployment

T08-T10: TigerData -> Grafana, fair benchmark matrix, Vultr Docker deployment. All three are required for the intended project; the first eight-hour session may leave explicitly documented follow-up work. A cloud demo must never be reported as deployed without its smoke-test evidence.

### G4: Presentation and 3D bridge

T11-T12: measured narrative/demo video; one headless 3D mission adapter with the same run/event contracts. Port observation/action encoders explicitly; retrain as needed. 2D policy weights are not assumed to transfer to 3D. Gazebo/PX4, larger swarms and graph neural policies follow measured stability.

## Eight-hour target

Treat this as an eight-hour wall-clock window with possible waiting time, not eight guaranteed hours of model access or training progress. Plan roughly: hour 0-1 bootstrap; 1-3 simulator/network/UI skeleton; 3-5 learning/persistence; 5-7 integration/benchmarks/deployment; 7-8 freeze, evidence and handoff. Dependency gates override the clock. If limits intervene, keep the last passing integrated slice and resume the highest-value unfinished task.

Priority: functional slice -> genuine decentralized learning -> trustworthy evidence -> cloud demonstration -> presentation -> 3D spike. Do not sacrifice reproducibility for sponsor/tool count; use each required technology for a visible purpose.

## What success can legitimately say

- Engineering success: isolated nodes learn and exchange updates; the system exposes and survives defined peer-network partitions.
- Research result: report measured differences and uncertainty, including neutral or negative results.
- Future claim: larger-scale and 3D behavior remain unproven until their experiments pass.

Full contracts, workload assignments, acceptance criteria and recovery rules live in the linked documents and task cards. Mark gates complete only after their evidence is merged.

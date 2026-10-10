# ADR-0008: Live decentralized-learning runtime (PyTorch CPU nodes + world coordinator)

## Evidence

- `infra/node/entrypoint.py` runs a peer server and a boot counter; no learner runs in any deployed container.
- `services/api/.../runs.py` steps the adapter with `adapter.step({})`; no node supplies actions.
- Learning exists only as a NumPy DQN exercised by offline `experiments/run.py`; PyTorch is a roadmap claim with no dependency in the lockfile.
- Operator assignment (2026-10-10): the deliverable is a live experiment on Vultr with TigerData persistence, four containers each training their own PyTorch policy, real peer transfer, partitions and an authenticated live dashboard. A replay, a boot counter or green CI does not meet it.

## Problem

There is no component that connects real world actions and rewards to per-container optimizers, so no claim about decentralized learning can be made from the deployed system.

## Root Cause

The infrastructure track (T10) was scoped to packaging; the learner, node runtime and world coordinator were never assigned tasks, and the registry (BOARD/cards) had no live-runtime entries.

## Existing Mechanism

`packages/learning` (NumPy Learner, tensor-only peer protocol), `packages/node/learner` (LearnerNode), `packages/node/peer` (PeerServer), `packages/adapters/sim2d` (real world), `services/api`, Persister, Compose files.

## Proposed Change

Implement `agents/architecture/live-runtime.md`: a PyTorch CPU `TorchLearner` (T26), a node runtime process with act/feedback/control/peer/telemetry (T27), a simulation coordinator service owning only the world (T28), live integration with a no-Docker local end-to-end smoke (T29), the experiment protocol repair and evidence (T30), and the Vultr deployment (T31). NumPy results and learner are kept as a labeled regression baseline. Peer exchange keeps validation-gated tensor-only candidates. The 2D simulator is used first. Node-control schemas stay internal to the runtime package; the frozen v0.1 public contracts are not changed.

## Expected Benefit

A deployed run in which optimizer updates, action selection and peer transfer demonstrably happen inside separate containers, with evidence that separates "a learner runs" from "transfer helps".

## Risks

- Centralized world service: coordinator failure stops the world (stated limitation).
- PyPI Linux PyTorch wheels bundle ~3 GB of CUDA libraries; the CPU index is unreachable from the authoring sandbox (policy 403, not retried). Mitigation: dependency group `torch` locked from PyPI for local dev; `scripts/install-torch-cpu.sh` installs the pinned CPU wheel in CI and images. Results are never compared bitwise across wheel variants.
- Measured warm cost is small (0.77 ms per optimizer step, 27 us per inference on one thread), so CPU is not the expected bottleneck; memory per node and HTTP overhead must be measured before limits are kept (T27).
- Obs/cost of a node-private validation world per exchange window; measured and recorded as overhead.
- Preexisting evidence (idle and rule-based beating learners) may persist; the live experiment reports it honestly.

## Rollback

Delete the new packages and compose services; the NumPy learner, offline experiments and infrastructure demo are untouched.

## Status

ACCEPTED (operator assignment; independent review of the agreement runs in T24).

# Architectural contracts (index)

This is an index, not a copy. Each contract has one authoritative source; tasks cite it in `contracts`.

| Area | Authority | Rule agents must keep |
|---|---|---|
| Wire/data formats (observation, action, snapshot, envelope, metrics, run config, manifest) | `packages/contracts/schemas/*.json`, models in `packages/contracts/src`, fixtures `good/` and `bad/` | Executable schemas win over prose. Changing one needs an ADR and the integrator (`shared`/`contracts` ownership). |
| Core runtime vs simulator | `agents/architecture/core.md`, `agents/architecture/interfaces.md` | Core logic depends on the adapter interface, never on a simulator. Target: Core runtime -> Networking, Learning, Telemetry, Simulator adapter -> {2D sim, 3D sim}. |
| 2D to 3D | `agents/decisions/0002-pose-z-3d.md`, `packages/adapters/pybullet/README.md` | `z` is 0 in 2D runs (rejected otherwise); 3D enters through the adapter only. |
| Evaluation | `agents/architecture/evaluation.md` | Same scenario, seeds and budgets across baselines; report intervals; PRELIMINARY until n>=30. |
| Persistence | `packages/storage/migrations/`, `agents/architecture/core.md` | TigerData only for durable data; no persistence added without a task. |
| Deployment | `infra/runbooks/*` | Vultr + Docker; no deploy from agent branches. |

## Invariants to turn into executable tests (backlog guidance, not yet complete)

Node ids unique; simulated time never decreases; severed links carry no traffic; destroyed nodes emit no actions; latency is non-negative; serialization round-trips preserve required fields; a seed reproduces results byte for byte; one invalid node state does not crash the simulator. Existing coverage: seeded determinism and replay hashes (`tests/sim`, `tests/experiments`), fixture round-trips (`tests/contracts`), topology obedience (`tests/transport`). Gaps are listed in `agents/reports/AUTONOMY_READINESS.md`. New invariant tests belong to the owning domain's task, not to a separate "invariants" task.

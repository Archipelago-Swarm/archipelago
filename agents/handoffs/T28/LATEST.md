# Handoff: T28 / initial

- State: in_progress
- Run / machine / worker: cloud/w2
- Branch / base commit: agent/T28-simulation-coordinator-service / origin/main
- Reserved paths: services/coordinator/**, tests/coordinator/**, packages/adapters/sim2d/**, tests/sim/**

## Intended outcome and acceptance
Implement `archipelago_coordinator` per agents/architecture/live-runtime.md sections 3, 6, 12.
Acceptance: `uv run pytest tests/coordinator tests/sim -q` exit 0 plus the ledger assertions.

## Completed and verified
Nothing yet (claim + plan only).

## Plan
1. Adapter: `kill_node`, per-episode reset with seeds (packages/adapters/sim2d).
2. `services/coordinator`: core (tick loop with deadlines, stay fallback, health, replay, idempotent commands, persisted sequence spool), HTTP server.
3. Tests against in-process fake nodes (node runtime is T27; coded to the section 3 contract).

## Next steps
Implement slices above; run `make check-fast`, then `make check-integration`.

# Handoff: T04 / 20261010 checkpoint 1 (UTC)

- State: in_progress (provisional; unmerged until T01 passes CI and merges)
- Run / machine / worker: no RUN_ID / B / B-lead (bootstrap exception, manual assignment from A)
- Assignment generation: bootstrap, 0
- Branch / worktree: agent/B/T04/run-api / C:\archipelago-T04
- T01 base commit (reviewed): 844d2e0 (origin/claude/elegant-pascal-a8a3hp; code at 61ef2ca, T01 state `review`, GitHub CI NOT yet run)
- Main instructions merged: origin/main 0d8691a ("Allow B to start T04...")
- Resume from: origin/agent/B/T04/run-api
- Reserved paths: services/api/, tests/api/. SHARED-FILE REQUEST to A: root pyproject.toml (workspace member services/api, dev deps, mypy files) and uv.lock; applied on this branch only, to be serialized by A at reconciliation.

## Intended outcome and acceptance
See agents/tasks/T04.md. Final review needs a real T03 run; fixture-only is partial.

## Plan
FastAPI app in services/api/src/archipelago_api: idempotent POST /v1/runs, commands (pause/resume/step/stop with command_id + expected_revision), bounded event replay, WS stream (snapshot, sequenced deltas, bounded queues + resnapshot), cookie/bearer auth + WS origin check, /healthz /readyz, restart marks orphaned runs interrupted. Fixture adapter until T03.

## Next steps
1. Implement + tests (`uv run pytest tests/api`). 2. Push checkpoint. 3. After T01 merges: merge main, switch to real adapter, rerun scripts/check.sh.

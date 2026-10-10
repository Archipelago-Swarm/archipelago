# Handoff: T14 / 2026-10-10

- State: in_progress
- Run / machine / worker: cloud/w3
- Branch / base commit: agent/T14-persist-run-events-so-replay-sur / origin/main e1d7c4e
- Last good commit: none yet
- Reserved paths: services/api/**, tests/api/**, tests/infra/test_smoke_and_replay.py

## Intended outcome and acceptance

Replay of a finished run equals the pre-restart replay after an api restart. `uv run pytest tests/api -q` (fast) and `tests/infra/test_smoke_and_replay.py` (docker, integration).

## Current state

Started; inspecting services/api eventlog.py/runs.py (an event log module and tests already exist on main).

## Validation

Not yet run.

## Next steps

1. Run `uv run pytest tests/api -q` to reproduce current state.

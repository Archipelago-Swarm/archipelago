# Handoff: T28 / simulation coordinator

- State: review
- Owner / worker: cloud/janitor (single serial session)
- Branch / base commit: agent/T28-simulation-coordinator-service / origin/main 314866a (+ earlier worker handoff 49cfca6)
- Reserved paths: services/coordinator/**, tests/coordinator/**, packages/adapters/sim2d/**, tests/sim/**

## Outcome
`archipelago_coordinator` implements live-runtime.md sections 3 (client side), 6 (adapter kill) and 12:
- `core.py`: `Coordinator` (tick loop, concurrent act requests bounded by `deadline_ms`, missing/late -> `stay` via the world's `missing_action`, 5 consecutive misses -> `unavailable`, idempotent commands with `expected_revision`, `kill_node`, per-episode replay with hash re-check, `Spool` JSONL whose sequence continues across restarts, re-stamped event ids `<run>-e<episode>-<kind>-<seq>`), `default_adapter_factory` raising `SimulatorUnavailable` (no fixture fallback).
- `server.py`: stdlib HTTP, bearer tokens (>=16 chars via `tokens_from_env`), routes `POST /v1/runs`, `GET /v1/runs/{id}`, `POST .../commands`, `GET .../events`, `GET .../snapshot` (admin token), `/healthz`, `/readyz`.
- `Sim2DAdapter.kill_node` + replay records `kills` (replay_final_hash repeats them).

## Acceptance
- `uv run pytest tests/coordinator tests/sim -q`: 25 passed (pre-existing sim tests plus 9 coordinator tests).
- `make check-fast`: only `test_real_ledger_is_valid` fails on this branch, caused by T14's missing handoff on the ledger branch; fixed by PR #16 (not in this branch's base).
- `SKIP_DOCKER=1 make check-integration`: 232 passed, 5 skipped, same single failure.
- Assertion mapping: node isolation, deadline/unavailable/stall, idempotent commands, kill_node, replay hash (including a kill), no fixture fallback, sequence continuity and unique ids are each a named test in tests/coordinator/test_coordinator.py.

## Not done / not run
- Docker, real nodes (T27 not built; fake in-process nodes only), `set_schedule` push to nodes (fault schedule distribution is recorded in config only; node side is T27), multi-episode `Plan` execution (`episodes`, `eval_every`, `telemetry_outage`) and the `Plan` body of `POST /v1/runs`: the server accepts a bare `run_config` and runs one episode. The next slice (T29 gate/T32) needs these; recorded here rather than claimed.
- Mypy: the coordinator is not in the root mypy file list (root `pyproject.toml` is integrator-owned).
- Root workspace membership for `services/coordinator` is not added (shared file); tests use path injection like tests/sim.

## Decisions
- Coordinator calls node clients through a `NodeClient` protocol so T27's HTTP client slots in; HTTP client itself is not written here.
- Verifier must be a session other than cloud/janitor.

## Next
Verifier runs the two acceptance commands at the last_good_commit. Follow-up task needed for Plan/episode schedules and the HTTP NodeClient (see Not done).

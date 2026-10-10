# T29 Data / API live mode handoff (owner B)

Status: local validation complete; CI-only parts listed below are NOT RUN. Not verified by an independent reviewer.
Branch: worktree-wf_3aeacd71-a28-1; base 94712c5.

## Invariant

Telemetry and learning metrics are persisted and queryable for the demo, and API live mode works end to end against the real coordinator package with fake nodes.

Demonstrated by `tests/api/test_live_mode.py` (real `archipelago_coordinator` in-process, four fake HTTP nodes, API in live mode) and `tests/storage/test_queries.py`:
no fixture fallback, `/readyz` independent of run activity, coordinator events and node telemetry in the event log, WebSocket stream and the Persister sink, sink outage does not block ingest, and the report queries return the expected curves from the persisted rows.

## What changed

- `services/api`: `TELEMETRY_TOKEN` setting mounts the T36 router in `create_app`; A7 request-level `context` accepted, stored with each event and passed to `Persister.record_event`; `peer_envelope` records are admitted (the web panels use them to attribute senders).
- `live.py` (new): `ARCHIPELAGO_ADAPTER=live`. `CoordinatorClient`, plan-name allowlist from `COORDINATOR_PLAN_FILE`, run driver that mirrors status and revision, forwards idempotent commands, pulls `GET /v1/runs/{id}/events` into the run log through the same admission path as node telemetry. Startup raises `LiveConfigError` for a missing/unusable URL, tokens, plan file, or coordinator package. Unknown adapter names raise. `/readyz` in live mode = coordinator ready and at least one node ready.
- `persistence.py`: canonical records are stored under their source node (`swarm` for coordinator-wide records), their own `event_id` and emission time (idempotent across API restarts), with `payload.context`; run rows carry the commit. Before this, every row had `node_id = 'api'`, so all per-node Grafana series collapsed into one.
- `packages/storage`: `migrations/0003_demo_views.sql` (views only, idempotent, SELECT granted to reader/writer), `queries.py`, `report.py` (`python -m archipelago_storage.report <run_id> [--compare <run_id>] [--format json|csv] [--out PATH]`).
- Grafana: "Training loss per node" now excludes null-loss rows (decision events carry no loss); the dashboard test was updated to match.

## Evidence

- `uv run ruff check packages services tests infra/vultr experiments`: pass; `ruff format --check`: pass; `uv run mypy`: pass (34 files).
- `uv run pytest -q -m "not docker" --ignore=tests/e2e`: 516 passed, 5 skipped.
- `npm ci`, `npm run lint`, `typecheck`, `test` (44 passed), `build`: pass (no apps/web change).

## NOT RUN

- Real TimescaleDB: `tests/storage/test_demo_views_integration.py` (migration 0003 twice, views under the reader role, report on PostgreSQL) is CI-only and has never executed. The SQLite stand-in checks logic, not PostgreSQL equivalence.
- Docker/Compose, `tests/e2e/test_live_local.py`, real node processes (T27 is amended elsewhere).

## Requests for the integrator (shared files)

- `infra/compose`: the `api` service needs `ARCHIPELAGO_ADAPTER=live`, `COORDINATOR_URL`, `COORDINATOR_TOKEN`, `COORDINATOR_ADMIN_TOKEN` (optional; unused by any API route), `COORDINATOR_PLAN_FILE` (mounted JSON object `name -> Plan` with node URLs), `TELEMETRY_TOKEN`; the API image must contain the `archipelago_coordinator` package (live mode imports `archipelago_coordinator.models.Plan` to validate the plan file at startup). `pyproject.toml`/image changes are integrator-only.
- The coordinator's `/readyz` only probes nodes from `COORDINATOR_NODE_URLS` plus the active run's plan, so it must be set for the API to be ready before the first run.

## Interface notes

- Coordinator routes used match section 12 (`POST /v1/runs`, `GET /v1/runs/{id}`, `POST .../commands`, `GET .../events`, `GET /readyz`). The coordinator status carries no `boot_id`; the API falls back to `"coordinator"`.
- Episode in coordinator-event context is derived from `sim_tick` as `max(tick-1,0) // max_ticks` (A7 global index); the coordinator currently emits some records at the per-episode tick, so for multi-episode runs the context episode is best effort. Reports order by `sim_tick`, not by episode.
- Dashboard "Peer decisions" shows the deciding node only; the sender is parsed from the reason string by the report CLI.
- An API restart marks live runs `interrupted` (existing recovery behavior) while the coordinator run continues; reattaching is not implemented.

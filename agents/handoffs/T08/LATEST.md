# Handoff: T08 / 2026-10-10 (fan-out, machine A)

- State: review
- Run / machine / worker: A fan-out worker, supervised by integrator
- Branch / base commit: agent/A/T08/fanout from d61113b
- Reserved paths: packages/storage/, observability/, tests/storage/, agents/handoffs/T08/

## Intended outcome and acceptance

Persist run/event/metric records to TigerData; provisioned Grafana dashboards. Docker unavailable, so only Docker-free checks were run.

## Completed and verified (no Docker)

- `packages/storage/migrations/0001_schema.sql`, `0002_roles.sql`: runs, events and metrics hypertables, dropped_metrics, artifacts manifest, NOLOGIN writer/reader roles (reader is SELECT only).
- `packages/storage/archipelago_storage/writer.py`: bounded queue (drop-oldest, drops counted and recorded into `dropped_metrics`), batched `ON CONFLICT DO NOTHING` inserts, `flush()` never raises, reconnects after failure, `connect_from_env` requires sslmode for non-local URLs.
- `observability/`: local compose profile (TimescaleDB + Grafana), provisioned datasource and a dashboard with coverage, transfer, latency and failures panels (units percentunit/bytes/ms).
- Tests (`tests/storage`, fake connection + static SQL/JSON checks): retry idempotence, outage backlog, bound and drop recording, SSL guard, hypertable unique keys include `ts`, dashboard units.

## Validation

From the worktree root: `uv run ruff check packages tests` (pass), `uv run ruff format --check packages tests` (pass), `uv run mypy --strict packages/storage/archipelago_storage` (pass), `uv run pytest -q tests/storage` (5 passed).

NOT RUN: migrations against a real TimescaleDB; ingestion/replay against a real DB; real-DB duplicate check (fake emulates ON CONFLICT only); node-keeps-running outage test with a real driver; Grafana rendering a real run; production TigerData connectivity/role check (blocked, needs credentials); `scripts/check.sh` as a whole and mypy via root config (root `files` excludes storage); npm checks.

## Decisions

- `psycopg` is imported lazily and is NOT in the root `pyproject.toml` or lockfile (shared files, serialized). Integrator must add the dependency (`psycopg[binary]`) and add storage paths to mypy `files`.
- Hypertable uniqueness is `(run_id, event_id, ts)` / `(run_id, node_id, name, ts)` because TimescaleDB requires the partition column in unique keys; idempotence therefore assumes a retry reuses the same ts.
- `migrate()` re-executes all files each call (idempotent DDL, no version table); upgrade when a non-idempotent migration is needed.
- Writer is not thread-safe; callers flush from one task. Writer does not yet spool to disk (memory only).

## Next steps

1. Integrator: add psycopg dependency; run `docker compose -f observability/docker-compose.yml up -d`, apply migrations via `migrate()`, replay a run, confirm Grafana panels.
2. Optional disk spool; wire real producers into `Writer.put`.
3. Grant LOGIN/passwords to roles out of band and record the production role check.

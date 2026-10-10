-- T08 schema. Idempotent (IF NOT EXISTS) so replay is safe. Requires TimescaleDB (TigerData).
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS runs (
    run_id     text PRIMARY KEY,
    started_at timestamptz NOT NULL,
    scenario   text,
    git_sha    text
);

-- Hypertable unique keys must include the partition column (ts).
CREATE TABLE IF NOT EXISTS events (
    ts       timestamptz NOT NULL,
    run_id   text NOT NULL REFERENCES runs(run_id),
    node_id  text NOT NULL,
    event_id text NOT NULL,
    kind     text NOT NULL,
    payload  jsonb NOT NULL DEFAULT '{}',
    UNIQUE (run_id, event_id, ts)
);
SELECT create_hypertable('events', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS metrics (
    ts      timestamptz NOT NULL,
    run_id  text NOT NULL REFERENCES runs(run_id),
    node_id text NOT NULL,
    name    text NOT NULL,   -- coverage_ratio | transfer_bytes | latency_ms | failures
    value   double precision NOT NULL,
    unit    text NOT NULL,   -- ratio | bytes | ms | count
    UNIQUE (run_id, node_id, name, ts)
);
SELECT create_hypertable('metrics', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS metrics_run_name_ts ON metrics (run_id, name, ts DESC);

-- Rows the writer shed under backpressure.
CREATE TABLE IF NOT EXISTS dropped_metrics (
    ts      timestamptz NOT NULL DEFAULT now(),
    run_id  text NOT NULL,
    kind    text NOT NULL,
    dropped bigint NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    run_id  text NOT NULL REFERENCES runs(run_id),
    path    text NOT NULL,
    sha256  text NOT NULL,
    bytes   bigint NOT NULL,
    created timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, path)
);

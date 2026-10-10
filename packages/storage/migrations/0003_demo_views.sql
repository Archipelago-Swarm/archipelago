-- T29 demo views over the canonical records the API Persister writes into `events`.
-- Additive and idempotent: only CREATE OR REPLACE VIEW and GRANT, no table is altered.
-- Row shape (see services/api persistence.py): events.node_id is the record's
-- source_node_id ('swarm' for coordinator-wide records), events.event_id the record's event_id,
-- events.ts its emission time, and payload the canonical record plus payload.context
-- {commit, config_hash, seed, host, boot_id, episode} (live-runtime.md A7).

CREATE OR REPLACE VIEW demo_learning AS
SELECT ts, run_id, node_id, event_id,
       CAST(payload->>'sim_tick' AS bigint) AS sim_tick,
       CAST(payload->'context'->>'episode' AS integer) AS episode,
       CAST(payload->>'update_count' AS bigint) AS update_count,
       CAST(payload->>'loss' AS double precision) AS loss,
       CAST(payload->>'previous_version' AS bigint) AS previous_version,
       CAST(payload->>'new_version' AS bigint) AS policy_version,
       payload->>'transfer' AS transfer,
       payload->>'reason' AS reason,
       CAST(payload->>'candidate_score' AS double precision) AS candidate_score,
       CAST(payload->>'bytes' AS bigint) AS bytes,
       CAST(payload->>'wall_seconds' AS double precision) AS wall_seconds,
       payload->'context'->>'commit' AS commit_sha,
       payload->'context'->>'config_hash' AS config_hash,
       CAST(payload->'context'->>'seed' AS bigint) AS seed,
       payload->'context'->>'host' AS host
FROM events
WHERE kind = 'learning_event';

CREATE OR REPLACE VIEW demo_peer_decisions AS
SELECT * FROM demo_learning WHERE transfer IN ('accepted', 'rejected');

CREATE OR REPLACE VIEW demo_metrics AS
SELECT ts, run_id, node_id, event_id,
       CAST(payload->>'sim_tick' AS bigint) AS sim_tick,
       CAST(payload->'context'->>'episode' AS integer) AS episode,
       payload->>'metric' AS metric,
       CAST(payload->>'value' AS double precision) AS value,
       payload->>'unit' AS unit,
       payload->>'phase' AS phase,
       payload->'context'->>'commit' AS commit_sha,
       payload->'context'->>'config_hash' AS config_hash,
       CAST(payload->'context'->>'seed' AS bigint) AS seed,
       payload->'context'->>'host' AS host
FROM events
WHERE kind = 'metric_sample';

-- Partition/recovery timeline: one row per fault phase transition (value = links cut).
CREATE OR REPLACE VIEW demo_fault_phases AS
SELECT ts, run_id, sim_tick, episode, phase, CAST(value AS integer) AS links_cut
FROM demo_metrics
WHERE metric = 'fault_phase';

-- Coverage and return split into training and frozen evaluation (never mixed).
CREATE OR REPLACE VIEW demo_task_curves AS
SELECT ts, run_id, node_id, sim_tick, episode, metric, phase, value
FROM demo_metrics
WHERE metric IN ('coverage', 'episode_return') AND phase IN ('train', 'eval');

GRANT SELECT ON demo_learning, demo_peer_decisions, demo_metrics, demo_fault_phases,
    demo_task_curves TO archipelago_reader, archipelago_writer;

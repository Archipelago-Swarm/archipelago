# archipelago_coordinator

Simulation coordinator (T28, `agents/architecture/live-runtime.md` sections 1, 2, 3, 6, 12). Owns the
authoritative `Sim2DAdapter` world and the tick loop. It never chooses actions, holds models, trains or
aggregates parameters. Stdlib only for HTTP (`ThreadingHTTPServer`, `http.client`, a thread pool); the
only third-party imports are the Pydantic contract models already used across the repo.
Killing the coordinator stops the world (stated limitation of the architecture).

## Run

```
export COORDINATOR_TOKEN=...        # >= 16 chars, used by the API / tests
export COORDINATOR_ADMIN_TOKEN=...  # >= 16 chars, different; only for GET /v1/runs/{id}/snapshot
export NODE_CONTROL_TOKEN=...       # >= 16 chars, sent as bearer to every node
export COORDINATOR_DATA_DIR=/data/coordinator   # events spool, run manifests, replays
export ARCHIPELAGO_ENV=production   # missing/broken simulator then aborts startup (exit 2)
export COORDINATOR_NODE_URLS=node-01=http://node-01:8000,node-02=http://node-02:8000   # readyz probes
export PYTHONPATH=services/coordinator:packages/sim:packages/adapters/sim2d:packages/contracts/src
python -m archipelago_coordinator --host 0.0.0.0 --port 8800
```

Optional: `COORDINATOR_WORLD_KWARGS` (JSON passed to `Sim2DAdapter`, e.g. `{"battery_scale": 10}`),
`COORDINATOR_TICK_INTERVAL_S` (pacing), `ARCHIPELAGO_COMMIT` (else `git rev-parse HEAD`).

## HTTP API

All routes except `GET /healthz` need `Authorization: Bearer <COORDINATOR_TOKEN>` (the snapshot route
needs the admin token and rejects the normal one with 403). See section 12 of the agreement.

| Route | Notes |
|---|---|
| `POST /v1/runs` `{run_config, plan}` | 201; 409 if a run is active or the `run_id` was used; 422 on unknown reward id, nodes without URL (or extra URLs), non-distinct/out-of-grid starts, bad windows/kill node; 503 if the simulator is unavailable |
| `GET /v1/runs/{id}` | status, revision, episode, tick, phase, `fault_phase`, per-node health (`ready/unavailable/killed`), deadline-miss counts, config hash, fault-schedule hash, commit, timing, finished episodes (kind, seed, final state hash, replay manifest) |
| `POST /v1/runs/{id}/commands` `{command_id, command, expected_revision?}` | `pause/resume/step/stop`; duplicate `command_id` returns the first answer (`duplicate: true`) without re-executing; stale revision or invalid transition is 409 |
| `GET /v1/runs/{id}/events?after_sequence=&limit=` | canonical `WorldSnapshot` and `MetricSample` records only |
| `GET /v1/runs/{id}/snapshot` | privileged snapshot, admin token only |
| `GET /readyz` | 503 unless the real simulator imports and at least one node answers `GET /v1/status` |

## Behavior and decisions

- Per tick each ready node gets only its own contract `Observation` on `POST /v1/act` with
  `{run_id, episode, tick, deadline_ms}`, all requests concurrent. Missing, late, invalid, wrong-tick or
  non-2xx replies become `stay` plus a `deadline_missed` metric. Five consecutive misses mark the node
  `unavailable` (still in the world, still stays, no longer called until the next episode reset, where a
  successful reset makes it `ready` again). Late replies are discarded.
- `POST /v1/feedback` (reward, next observation, terminated, truncated) goes only to nodes whose own
  action was applied this tick, and only in train episodes (eval is frozen; nodes answer 409).
- Episodes follow the explicit `plan.episodes` order (`count` expands to consecutive seeds). `train`
  episodes use control mode `train`; `validation` and `test` use mode `eval`. At each episode the control
  sequence is `reset`, `set_schedule` (same immutable schedule and its SHA-256 for every node), ticks,
  `episode_end`. `eval_every` is recorded only; the explicit list is authoritative. `stop` is never sent to
  nodes and coordinator pause/resume do not pause node training.
- `kill_node {node_id, tick}` applies in every episode: before that tick's act round the drone is removed
  with `Sim2DAdapter.remove_node` (no body, no wreck, like `rollout.reset(drop=...)`, unlike battery death
  where a wreck blocks its cell). Survivors continue; the node still gets `episode_end`. The removal is part of
  the replay.
- `telemetry_outage {start_tick, end_tick}` drops events of the ticks being executed in that window from the
  coordinator's own event sink (counted in `events_dropped`); nothing else is affected. Dropped events get no
  sequence number, so sequences stay contiguous. Snapshot and tick metrics carry `sim_tick = t + 1`.
- Events live in `<data>/events/<run>.jsonl`. Sequences start at 1 and continue across restarts; ids are
  `{run_id}-{boot_id}-{sequence}`. A run that was active when the process died is marked `interrupted` at
  next start and a `run_interrupted` metric continues the sequence.
- Per episode `<data>/replays/<run>/ep-NNNN/{replay.jsonl,manifest.json}` via `Sim2DAdapter.write_replay`
  (manifest also embeds `run_config` so `archipelago_sim2d.adapter.replay_final_hash_from_dir` can re-execute).
  Run manifest: `<data>/runs/<run>/manifest.json`.
- Not implemented here: peer exchange, checkpoints, node-side idempotency (T27). The service has no
  fixture fallback anywhere.

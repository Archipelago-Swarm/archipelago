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
export COORDINATOR_PLAN_FILE=/etc/archipelago/plan.json   # the Plan (node URLs included); required in production
export PYTHONPATH=services/coordinator:packages/sim:packages/adapters/sim2d:packages/contracts/src
python -m archipelago_coordinator --host 0.0.0.0 --port 8800
```

Optional: `COORDINATOR_WORLD_KWARGS` (JSON passed to `Sim2DAdapter`, e.g. `{"n_targets": 0}`; `battery_scale`
is refused here because the Plan owns it),
`COORDINATOR_TICK_INTERVAL_S` (pacing), `ARCHIPELAGO_COMMIT` (else `git rev-parse HEAD`).

## HTTP API

All routes except `GET /healthz` need `Authorization: Bearer <COORDINATOR_TOKEN>` (the snapshot route
needs the admin token and rejects the normal one with 403). See section 12 of the agreement.

| Route | Notes |
|---|---|
| `POST /v1/runs` `{run_config, plan_name?}` | 201; 409 if a run is active or the `run_id` was used; 422 on a request-supplied `plan`/`node_urls` (A9), unknown plan name, unknown reward id, nodes without URL (or extra URLs), non-distinct/out-of-grid starts, bad windows/kill node, a fault window past the reachable horizon (A13), `gate_seeds` overlapping episode seeds; 503 if the simulator is unavailable or the plan file is missing/invalid |
| `GET /v1/runs/{id}` | status, revision, episode, tick, phase, `fault_phase`, per-node health (`ready/unavailable/killed`), deadline-miss counts, config hash, fault-schedule hash, commit, timing, finished episodes (kind, seed, final state hash, replay manifest) |
| `POST /v1/runs/{id}/commands` `{command_id, command, expected_revision?}` | `pause/resume/step/stop/checkpoint` (checkpoint, valid while running or paused, forwards a node `checkpoint` control once to every non-killed node and reports `checkpoint.requested/failed`; no lifecycle change); duplicate `command_id` returns the first answer (`duplicate: true`) without re-executing; stale revision or invalid transition is 409 |
| `GET /v1/runs/{id}/events?after_sequence=&limit=` | canonical `WorldSnapshot` (public: poses, coverage, links, only obstacles some node discovered) and `MetricSample` records only; `sim_tick` is global, `episode * max_ticks + tick` (A7) |
| `GET /v1/runs/{id}/snapshot` | privileged snapshot (A10), admin token only: contract `WorldSnapshot` with every obstacle, plus `privileged: {targets, found, battery}`; fresh `event_id`/`sequence` per call |
| `GET /readyz` | 503 unless the real simulator imports and at least one node answers `GET /v1/status` |

## Behavior and decisions

- Per tick each ready node gets only its own contract `Observation` on `POST /v1/act` with
  `{run_id, episode, tick, deadline_ms}`, all requests concurrent. Missing, late, invalid, wrong-tick or
  non-2xx replies become `stay` plus a `deadline_missed` metric. Five consecutive misses mark the node
  `unavailable` (still in the world, still stays, no longer called until the next episode reset, where a
  successful reset makes it `ready` again). Late replies are discarded.
- Plan (A9): `COORDINATOR_PLAN_FILE`, read at each run request, is one Plan object (name `default`) or
  `{"plans": {name: Plan}}`. Its SHA-256 and the plan name are in the run status and manifest. The plan carries
  `node_urls`, `deadline_ms`, `battery_scale` (A13, default 1.0; moving drones die at `battery_scale / 0.004`
  ticks), `node_config` (hyperparameters, epsilon schedule, margin, gate seeds, ... for `configure`), episodes,
  fault schedule, `kill_node`, `telemetry_outage`. The coordinator attaches `NODE_CONTROL_TOKEN` itself.
- `POST /v1/control configure` (A5, section 14 shape) goes to each node once per run before its first `reset`
  (a node whose configure failed is retried at the next reset, never re-sent after success); a node that refuses
  is `unavailable`. `world_config` is read from the live world, `max_ticks` from the run config.
- `POST /v1/feedback` (A2) goes in train episodes only (eval is frozen; nodes answer 409), to every node that was
  asked to act that tick, with `executed_command`, `action_index` and `deadline_missed`: a node that missed
  the deadline is told `stay` / 0 / true. The coordinator awaits all acks, bounded by `2 * deadline_ms`,
  before tick t+1's act round. A late or failed ack counts as `feedback_failed` and is never retried.
- Episodes follow the explicit `plan.episodes` order (`count` expands to consecutive seeds). `train`
  episodes use control mode `train`; `validation` and `test` use mode `eval`. At each episode the control
  sequence is (`configure` once,) `reset` (carries the same immutable `fault_schedule` for every node; its
  timeout is 8 s because a node's reset may wait 5 s for a running exchange window), ticks, `episode_end`
  `{episode, tick}` (A4) to every node except killed ones, terminated and unavailable nodes included; the
  node answers 202 `{window_id}` and runs its final window in the background, the coordinator only waits for
  the ack (bounded) and records `window_ids`. `eval_every` is recorded only; the explicit list is authoritative. `stop` is never sent to
  nodes and coordinator pause/resume do not pause node training.
- `kill_node {node_id, tick}` (episode-local tick) applies in every episode: before that tick's act round the
  drone vanishes via `Sim2DAdapter.kill` (no body, no wreck, like `rollout.reset(drop=...)`, unlike battery
  death where a wreck blocks its cell; what it discovered stays public). Survivors continue; the killed node gets
  no further act, feedback or `episode_end`. The removal is part of the replay.
- Each episode runs under a derived RunConfig (A14): run id `<run>-e<index>`, env seed from the plan, so adapter
  ids never repeat across episodes or runs; stamps are wall time, `sim_tick` is global.
- `telemetry_outage {start_tick, end_tick}` drops events of the ticks being executed in that window from the
  coordinator's own event sink (counted in `events_dropped`); nothing else is affected. Dropped events get no
  sequence number, so sequences stay contiguous. Snapshot and tick metrics carry the global
  `episode * max_ticks + t + 1`; fault, kill and outage ticks in the plan stay episode-local.
- Events live in `<data>/events/<run>.jsonl`. Sequences start at 1 and continue across restarts; ids are
  `{run_id}-{boot_id}-{sequence}`. A run that was active when the process died is marked `interrupted` at
  next start and a `run_interrupted` metric continues the sequence.
- Per episode `<data>/replays/<run>/ep-NNNN/{replay.jsonl,manifest.json}` via `Sim2DAdapter.write_replay`
  (manifest also embeds `run_config` so `archipelago_sim2d.adapter.replay_final_hash_from_dir` can re-execute).
  Run manifest: `<data>/runs/<run>/manifest.json`.
- Not implemented here: peer exchange, checkpoints, node-side idempotency (T27). The service has no
  fixture fallback anywhere.

# archipelago_noderuntime

The per-container node process of `agents/architecture/live-runtime.md` (sections 3, 5, 7, 8, the
section 13 amendments A1-A8, A16, A17 and the normative message shapes of section 14). One process
owns one `TorchLearner` and trains it **in-process** on `/v1/feedback`; it exchanges validated model
candidates with the other nodes directly and ships telemetry in the background.

```
PYTHONPATH=packages/node/runtime:packages/node/peer:packages/node/learner:packages/transport:\
packages/contracts/src:packages/learning:packages/sim  python -m archipelago_noderuntime
```

The process prints one JSON line (`node_ready`, with the bound `control_url`, `peer_url`, `boot_id`
and what was restored) and runs until SIGTERM/SIGINT or a `stop` control command; it writes a
final checkpoint generation on a graceful stop.

## Configuration (environment, optionally overridden per run by `configure`)

Required: `NODE_ID`, `NODE_CONTROL_TOKEN` and `PEER_TOKEN` (both >= 16 chars, else exit 2),
`NODE_CHECKPOINT_DIR`.

| Variable | Default | Meaning |
|---|---|---|
| `NODE_IDS` | `NODE_ID` | comma separated static manifest (all-to-all peer links) |
| `PEER_URLS` | empty | `node-01=http://node-01:9000,...` (ids must be in `NODE_IDS`, http/https) |
| `BIND_HOST` / `CONTROL_PORT` / `PEER_PORT` | `127.0.0.1` / 8080 / 9000 | `0.0.0.0` in containers; port 0 = ephemeral |
| `EXCHANGE_EVERY_TICKS` | 50 | A1 cadence in the node's own ticks (0 = only the `episode_end` window) |
| `WINDOW_CANCEL_WAIT` | 5.0 | A4: seconds `reset` waits for a running window before cancelling it |
| `TELEMETRY_URL` (`TELEMETRY_TOKEN`) | none | batch POST target; unset keeps only the bounded spool |
| `TORCH_THREADS` | 1 | also exported as `OMP_NUM_THREADS`/`MKL_NUM_THREADS` before torch loads |
| `SEED` | 0 | learner seed is `SEED*1000 + index of NODE_ID in the sorted NODE_IDS` |
| `HIDDEN LR GAMMA REPLAY_CAPACITY BATCH_SIZE TARGET_EVERY TRAIN_STEPS_PER_FEEDBACK` | 32 .01 .95 5000 32 50 1 | learner |
| `EPS_START EPS_END EPS_DECAY_ACTS` | .5 .05 5000 | linear exploration schedule over train-mode acts |
| `LEARNER_SCHEDULE_ID DOUBLE_DQN EPS_DECAY_EPISODES` | `sched-v0` 0 (unset) | A18: `sched-t37-v1` fixes lr 1e-3, replay 50000, double DQN and makes epsilon decay per TRAINING episode (1.0 to 0.05 over the first half); a registered id supplies these defaults and refuses contradicting values |
| `ENCODER_FAMILY SUMMARY_TIMEOUT SUMMARY_TRACE` | `grid-flat-v1` 0.5 0 | A18: `grid-flat-v2-visits[-shared]` adds node-local visit memory (57/82 floats) and, for `-shared`, visited-cell summaries to peers (not model offers; see live-runtime.md section 15); `SUMMARY_TRACE=1` lists in status the ticks at which each peer's summary was applied |
| `LEARNER_MODE` / `MIX_ALPHA` | `independent` | `independent`, `mixing` (needs 0<alpha<=.5), `information_only` |
| `PEER_MARGIN PEER_TIMEOUT PEER_RETRIES` | 0.0 1.0 1 | gate margin and peer HTTP behaviour |
| `WORLD_SIZE WORLD_N_TARGETS WORLD_OBSTACLE_DENSITY WORLD_SENSE_RADIUS WORLD_MAX_TICKS WORLD_BATTERY_SCALE REWARD_ID` | 16 3 .12 2 900 1.0 `rew-v0` | the node-private validation world; size and radius also fix the encoder id `{ENCODER_FAMILY}-s{size}-r{radius}` |
| `VALIDATION_SEEDS` / `N_VALIDATION_AGENTS` / `VALIDATION_MAX_TICKS` / `TEST_SEEDS` | 9001,9002,9003 / 1 / `WORLD_MAX_TICKS` / empty | gate seeds, drones in the private world; `TEST_SEEDS` is only used to refuse overlap |
| `TELEMETRY_SPOOL_MAX_RECORDS` etc. | 20000 | spool cap, segment size, batch, interval, timeout, local-update window |
| `GIT_COMMIT` | `unknown` | sent in the telemetry request `context` with `config_hash`, `seed`, `host`, `boot_id`, `episode` |

## HTTP (private network, bearer `NODE_CONTROL_TOKEN`, body <= 256 KiB)

`POST /v1/act`, `POST /v1/feedback`, `POST /v1/control`, `GET /v1/status` with the field names of
section 14 (unknown fields are rejected, every control command carries `run_id`); models are in
`protocol.py`. `GET /healthz` is the only unauthenticated route. Status codes: 401 auth, 400
malformed JSON, 411 no length, 413 oversize, 422 schema or encoder error, 409 `stale` /
`wrong_run` / `wrong_episode` / `unknown_step` / `eval_mode` / `episode_not_acted` /
`config_conflict`.

* Step key `(run_id, episode, tick)`; staleness is lexicographic on `(episode, tick)`. A duplicate
  `act` returns the cached reply (same action and `event_id`, exploration is never re-sampled); a
  duplicate `feedback` returns the cached reply with `duplicate: true` and stores nothing.
* **Feedback carries what was executed** (A2): the transition stored is `(obs, executed action,
  reward, next_obs, done)`; a fallback `stay` is trained as `stay`. The new inference snapshot is
  published inside the handler, before the response. Barrier: if the feedback of an earlier tick is
  being processed, `act` waits for it (bounded by `deadline_ms`, at most 1 s), so act(t+1) sees the
  post-feedback(t) policy. `deadline_missed` feedback for an act the node never saw is acknowledged
  with `accepted: false` and stores nothing.
* **configure** (A5): once per run before the first reset. Same run and same hash is idempotent;
  same run, different hash is 409; a new `run_id` starts a fresh learner (the previous generations
  are moved to `ckpt-before-<run>-<boot>`, never deleted). The accepted body is persisted in
  `run_config.json` so a restarted node rebuilds the same learner before restoring its checkpoint.
* **Exchange windows** (A1/A4): the node's own tick counter (from `act`) triggers a window at every
  multiple of `exchange_every_ticks` in train mode; `episode_end` triggers the final window and
  answers `202 {window_id}` (idempotent per episode). All windows and periodic checkpoints run on
  one background worker, never in the act path. Fault decisions use the window's tick, so a window
  inside a cut sees the cut; sender and receiver both enforce the schedule. Candidates are judged in
  arrival order with `archipelago_learning.OfferWindow`: at most one acceptance, the rest rejected
  as `window_limit` without validation cost. `reset` waits up to `WINDOW_CANCEL_WAIT` for a
  running window, then cancels it (`window_cancelled`); a cancelled window never applies a
  candidate.
* **Peer trust** (A8): peer endpoints need `Authorization: Bearer <PEER_TOKEN>`; the receiver
  refuses a `src` that is not one of the other declared node ids (403).

## Design notes

* **Acting never blocks** on training, validation, checkpoints, peers or telemetry: `act` takes only
  a microsecond-scale state lock and reads the immutable published snapshot. Training is inline in
  `feedback` (`TRAIN_STEPS_PER_FEEDBACK`, about 1 ms/step) so step counts are exact. While a
  candidate is being validated optimizer steps are deferred (`train_deferred`). The node measures
  its own act handler latency (`status.act_latency_ms`, p50/p99/max) for A16.
* **Identity** (A3): `boot_id` is 8 hex characters per process start;
  `event_id = {node}-{boot_id}-{sequence}`. Sequence numbers come from
  `archipelago_learning.SequenceAllocator` (`sequence.json`, blocks of 1000 persisted before use), the
  peer envelope `seq` from a second allocator (`peer_seq.json`); a restarted node therefore never
  reissues a number and peers do not drop its offers as stale. The pending `(obs, action)` per step
  key and `tick`/`fed_tick` are part of the checkpoint.
* **Checkpoints** (A17) are written by `ckpt.py` with the fixed names `policy.npz target.npz
  optimizer.npz replay.npz rng.json counters.json MANIFEST.json` (fsync, hash manifest, atomic
  `CURRENT`, keep 3), every 200 feedback steps and at each `episode_end`. The learner library's own
  `save_generation` predates A17 and is not used by the node.
* **Telemetry** (A7): spool lines are `{event_id, phase, record}`; the shipper posts
  `{source, boot_id, events:[records], context:{commit, config_hash, seed, host, boot_id, episode?}}`
  (<= 500 events and ~200 KiB per request) with optional bearer `TELEMETRY_TOKEN`. `sim_tick` is
  `episode * max_ticks + tick`. Decision evidence (validation seconds, evaluations, margin) rides as
  `MetricSample`s; source and sha256 stay in `LearningEvent.reason`.
* **Encoder** (A6): `encoder.py` is a thin adapter over `archipelago_learning.encoders`.

## Measuring

`uv run python tests/noderuntime/measure_node.py` starts one real node and prints idle/training RSS
(from `/proc`, plus the node-reported peak), act/feedback latency percentiles, act latency during a
full-size validation and the memory limit proposal (1.5 x peak RSS rounded up to 64 MiB). It needs
the same `PYTHONPATH` as above. Use it with the CPU wheel in the image before fixing the Compose
memory limit.

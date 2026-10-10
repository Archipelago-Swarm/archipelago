# archipelago_noderuntime

The per-container node process of `agents/architecture/live-runtime.md` (sections 3, 5, 7, 8,
decision record `agents/decisions/0008-live-runtime.md`). One process owns one `TorchLearner`
and trains it **in-process** on `/v1/feedback`; it exchanges validated model candidates with the
other nodes directly and ships telemetry in the background.

```
PYTHONPATH=packages/node/runtime:packages/node/peer:packages/node/learner:packages/transport:\
packages/contracts/src:packages/learning:packages/sim  python -m archipelago_noderuntime
```

The process prints one JSON line (`node_ready`, with the bound `control_url`, `peer_url`, `boot_id`
and what was restored) and runs until SIGTERM/SIGINT or a `stop` control command; it writes a
final checkpoint generation on a graceful stop.

## Configuration (environment only)

Required: `NODE_ID`, `NODE_CONTROL_TOKEN` (>= 16 chars, else exit 2), `NODE_CHECKPOINT_DIR`.

| Variable | Default | Meaning |
|---|---|---|
| `NODE_IDS` | `NODE_ID` | comma separated static manifest (all-to-all peer links) |
| `PEER_URLS` | empty | `node-01=http://node-01:9000,...` |
| `BIND_HOST` / `CONTROL_PORT` / `PEER_PORT` | `127.0.0.1` / 8000 / 9000 | `0.0.0.0` in containers; port 0 = ephemeral |
| `TELEMETRY_URL` (`TELEMETRY_TOKEN`) | none | batch POST target; unset keeps only the bounded spool |
| `TORCH_THREADS` | 1 | also exported as `OMP_NUM_THREADS`/`MKL_NUM_THREADS` before torch loads |
| `SEED` | 0 | learner seed is `SEED*1000 + index of NODE_ID in the sorted NODE_IDS` |
| `HIDDEN LR GAMMA REPLAY_CAPACITY BATCH_SIZE TARGET_EVERY TRAIN_STEPS_PER_FEEDBACK` | 32 .01 .95 5000 32 50 1 | learner |
| `EPS_START EPS_END EPS_DECAY_ACTS` | .5 .05 5000 | linear exploration schedule over train-mode acts |
| `LEARNER_MODE` / `MIX_ALPHA` | `independent` | `independent`, `mixing` (needs 0<alpha<=.5), `information_only` |
| `PEER_MARGIN PEER_TIMEOUT PEER_RETRIES` | 0.0 1.0 1 | gate margin and peer HTTP behaviour |
| `WORLD_SIZE WORLD_N_TARGETS WORLD_OBSTACLE_DENSITY WORLD_SENSE_RADIUS WORLD_MAX_TICKS WORLD_BATTERY_SCALE REWARD_ID` | 16 3 .12 2 900 1.0 `rew-v0` | the node-private validation world (must match the live world config; the encoder also needs `WORLD_SIZE`) |
| `VALIDATION_SEEDS` / `VALIDATION_MAX_TICKS` / `TEST_SEEDS` | 9001,9002,9003 / `WORLD_MAX_TICKS` / empty | `TEST_SEEDS` is only used to refuse overlap |
| `TELEMETRY_SPOOL_MAX_RECORDS` etc. | 20000 | spool cap, segment size, batch, interval, timeout, local-update window |
| `GIT_COMMIT` | `unknown` | attached to every telemetry batch with `config_hash`, `seed`, `host`, `node_id` |

## HTTP (private network, bearer `NODE_CONTROL_TOKEN`, body <= 256 KiB)

`POST /v1/act`, `POST /v1/feedback`, `POST /v1/control`, `GET /v1/status` as in the agreement;
`GET /healthz` is the only unauthenticated route and returns `{"ok": true}`. Models are in
`protocol.py`. Status codes: 401 auth, 400 malformed JSON, 411 no length, 413 oversize,
422 schema or encoder error, 409 `stale` / `wrong_run` / `unknown_step` / `eval_mode` /
`episode_not_acted`.

* Step key `(run_id, episode, tick)`. A duplicate `act` returns the cached reply (same action and
  `event_id`, exploration is never re-sampled); a duplicate `feedback` returns the cached reply with
  `duplicate: true` and stores nothing. A lower tick (or lower episode) that is not a cached
  duplicate is 409. A higher episode of the same run advances the node implicitly (counted), so a
  restarted node keeps working without a fresh `reset`; a different `run_id` needs `reset`.
* `reset` is idempotent for the same `(run_id, episode, mode)`. `eval` freezes optimizer,
  exploration (epsilon 0), replay, and peer exchange; `feedback` is 409.
* `episode_end` queues the exchange window on a worker thread and returns at once (`wait: true`
  blocks, bounded by `exchange_wait_max`). Requests arriving while one is running are coalesced
  (latest wins). The window ends with a checkpoint generation.
* The window enforces the fault schedule itself: a window is active for `start_tick <= tick <
  end_tick` on the node's own tick counter (from `act`), and each listed pair is cut in **both**
  directions on send and on receive. The exchange only happens at `episode_end`, so a cut only
  prevents an offer if the window covers the tick at which `episode_end` is issued.

## Design notes

* **Acting never blocks**: `act` takes only a microsecond-scale state lock and reads the immutable
  published snapshot; it has its own exploration RNG. Training is inline in `feedback` (bounded:
  `TRAIN_STEPS_PER_FEEDBACK`, about 1 ms/step) so step counts are exact; exchange, validation,
  checkpoint cadence and shipping run on other threads. While a candidate is being validated
  optimizer steps are deferred (`train_deferred` counter) so the judged policy equals the replaced
  one; transitions are still stored. The validation loop yields the GIL every simulated step.
* **Validation** is `ValidationWorld`: a private single-drone `GridWorld` with the node's own world
  config, configured validation seeds only, greedy policy, no optimizer. Scores of the current and
  each candidate policy are computed once, candidates are tried best-first (ties by node id) and at
  most one is accepted per window; the rest are logged as `window limit`. `validation_seconds` and
  `evaluations` are recorded on every decision.
* **Deviation from the agreement text**: `LearnerNode` is not used. Its `poll` has no per-window
  limit, ordering, or lock discipline and its event ids lack the boot id; the node uses the same
  building blocks directly (`archipelago_peer.PeerServer`/`post`, `archipelago_transport.Envelope`,
  `archipelago_learning.encode/decode/offer`). The envelope `seq` is the policy version, which
  continues across restarts (a node restored from an old generation re-offers only once its version
  passes what peers have seen).
* **Checkpoints** use `TorchLearner.save_generation` with `extra` = node counters and sequence,
  boot id, exploration RNG, schedule, last-sent versions, peer dedupe cache, spool cursor.
  Event sequence on restore is `max(checkpoint, highest sequence found in the spool) + 1`, and
  `event_id = node-boot-sequence` carries a fresh boot id, so ids never collide. A checkpoint
  whose identity (hidden size, encoder...) differs from the config is refused, not reset.
* **Telemetry** records are canonical `LearningEvent` / `MetricSample` (source node, wall-clock
  `emitted_at_utc`, simulation `sim_tick`). A spool line is `{event_id, phase, record}`; a batch is
  `POST` JSON `{node_id, host, commit, config_hash, seed, records:[lines]}` with optional bearer
  `TELEMETRY_TOKEN`. 2xx acknowledges (the sink must dedupe by `event_id`); 400/413/422 skip the
  batch (counted as `poison`); anything else retries with backoff. Local-update events are
  windowed (`TELEMETRY_UPDATE_EVERY` steps, mean loss).

## Measuring

`uv run python tests/noderuntime/measure_node.py` starts one real node and prints idle/training RSS
(from `/proc`, split into anonymous and file-backed), act/feedback latency percentiles, and act
latency during a full-size validation. Use it with the CPU wheel in the image before fixing the
Compose memory limit.

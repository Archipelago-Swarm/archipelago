# Live decentralized-learning runtime: interface agreement (T24)

Status: AGREED 2026-10-10 by the integrator (machine A) under the operator's assignment. Workers implement against this document. A change needs an ADR and the integrator; do not diverge in a worker branch.

Goal this serves: four drone containers, each running its own PyTorch policy and training loop, acting in one authoritative 2D world, exchanging validated model candidates directly over a partitionable peer network, with persistent telemetry and a live dashboard. See `evaluation.md` for the experiment protocol.

## 1. Processes and ownership

| Process | Package / path | Owns | Must never |
|---|---|---|---|
| node runtime (x4) | `packages/node/runtime/` (`archipelago_noderuntime`) | policy+target nets, optimizer, replay, RNG, exploration schedule, counters, checkpoints, telemetry spool, peer client and server | read world state beyond its own observation; load another node's files; train in another process |
| coordinator (x1) | `services/coordinator/` (`archipelago_coordinator`) | `Sim2DAdapter` world, tick loop, episode and fault schedules, authoritative replay, privileged snapshots | choose actions, hold models, train, aggregate parameters |
| API | `services/api/` | run lifecycle, auth, WebSocket, event log, persistence ingest | step the world or touch learners when `ARCHIPELAGO_ADAPTER=live` |
| learner library | `packages/learning/` | `TorchLearner` (new), NumPy `Learner` (kept as regression baseline), peer encode/decode/offer | do I/O beyond checkpoint files given to it |

The coordinator is a centralized world service. That is a limitation to state: killing it stops the world. Only decision, learning and peer exchange are decentralized. Three channels exist and fail independently: (a) coordinator<->node control/observation/action, (b) node<->node peer, (c) telemetry to API/DB. A peer partition cuts only (b).

## 2. Identity and ordering

- `run_id` unique per run. `episode` int from 0. `tick` int per episode from 0. A step key is `(run_id, episode, tick)`.
- `node_id` is `node-01`..`node-04` (contract Id charset). Sorted order must never change outcomes.
- Every node-emitted event uses the canonical v0 records (`LearningEvent`, `MetricSample`, `Action`, `PeerEnvelope` fields) with `source_node_id` set, a per-node monotonic `sequence` that **continues across restarts** (persisted in the checkpoint manifest), `event_id = f"{node_id}-{boot_id}-{sequence}"` (unique across restarts), real `emitted_at_utc`, and `sim_tick` carrying simulation time. Simulation time and wall time are never mixed.
- Phases (`MetricSample.phase`): `train`, `eval`, `partition`, `recovery`, `other`. Evaluation splits are named in `RunConfig`-adjacent metadata: `train` seeds, `validation` seeds (candidate gating, node-private), `test` seeds (final reporting only, never used for gating or tuning).

## 3. Node runtime HTTP interface (coordinator -> node, private network)

Stdlib `http.server`, JSON bodies, `application/json`. Auth: shared bearer token from env `NODE_CONTROL_TOKEN` (required, >=16 chars); nodes reject others with 401. Max body 256 KiB. Node-control schemas live in `packages/node/runtime/archipelago_noderuntime/protocol.py` (Pydantic) and are internal runtime protocol, not part of the frozen v0.1 public contracts; embedded `observation` and `action` are canonical contract records. Promoting any of it to public contracts needs an ADR.

| Endpoint | Request | Response | Semantics |
|---|---|---|---|
| `POST /v1/act` | `{run_id, episode, tick, deadline_ms, observation}` (`observation` = contract `Observation`) | `{node_id, tick, action, policy_version, epsilon}` (`action` = contract `Action`) | Select an action from the current immutable inference snapshot. Idempotent per step key (a duplicate returns the cached action, never re-samples exploration). A tick lower than the last acted tick is 409 `stale`. Must not block on training, peers or telemetry. |
| `POST /v1/feedback` | `{run_id, episode, tick, reward, next_observation, terminated, truncated}` | `{accepted, replay_size, train_steps}` | Store the transition (`done = terminated`, truncation still bootstraps), run the configured number of optimizer steps. Idempotent per step key. Not valid in `eval` mode (409). |
| `POST /v1/control` | `{command, ...}` | `{ok, status}` | `reset` (new episode; `mode` train or eval; `eval` freezes optimizer, exploration and replay), `pause`/`resume` training only (acting continues), `checkpoint` (write a generation now), `set_schedule` (peer fault schedule, section 6), `episode_end` (triggers the peer exchange window, section 5), `stop`. |
| `GET /v1/status` | | readiness, `run_id`, `episode`, `tick`, `mode`, `backend` (`torch-cpu`), `torch_version`, `policy_version`, `train_steps`, `replay_size`, `loss_ema`, `checkpoint_generation`, peer states (`up/cut`), `rss_bytes`, `telemetry_backlog` | `ready=false` until a model exists and the peer server is listening. |

Deadlines: the coordinator waits `deadline_ms` (default 500) per node. A missing or late action becomes `stay` with a `deadline_missed` metric; K=5 consecutive misses mark the node `unavailable` (still in the world, still stays). One slow node never blocks the others (requests are concurrent). A late response arriving after the tick is discarded by the coordinator and acknowledged idempotently by the node.

Observation encoder `grid-flat-v1` (contract `Observation` -> `float32[28]` for radius 2): flatten `crop` row-major (values -1 unknown, 0 free, 1 wall, as emitted), then `floor(pose.x)/size`, `floor(pose.y)/size`, `battery`. This equals the `grid-flat-v0` vector used by the NumPy baseline after the existing `_norm`, so both backends train on identical inputs; the encoder id and a SHA-256 of its definition are part of every model's compatibility header. Action space `act-v0` (stay, north, east, south, west) -> indices 0..4. Reward id `rew-v0`.

## 4. TorchLearner contract (library, used only inside node runtime)

```
TorchLearner(node_id, obs_dim, n_actions, hidden, seed, lr, gamma, capacity, mode, encoder, threads=1)
  act(obs, eps) -> int                      # uses an immutable inference snapshot, no autograd
  observe(o, a, r, o2, done) -> None
  train_step(batch, target_every) -> float | None
  snapshot() -> InferenceSnapshot           # published at step/episode boundaries, never mutated
  params_numpy() -> dict[str, np.ndarray]   # float32 arrays, keys below
  load_params_numpy(d) -> None              # only through peer.offer / rollback / checkpoint load
  save_generation(dir) -> manifest ; load_latest(dir) -> manifest   # section 7
  backend = "torch-cpu"; counters: steps, version, n; events: list[dict]
```
Hard rules: separate mutable state per instance (no module-level tensors or RNG); `torch.set_num_threads(threads)`, `OMP_NUM_THREADS` and MKL equivalents set from env, default 1; seeded `torch.Generator` plus numpy `Generator` for exploration/replay sampling; `torch.use_deterministic_algorithms` where supported and any exception recorded in the run manifest; `weights_only` loading everywhere; **never `pickle`/`torch.load` a peer payload**.

Parameter mapping (versioned, `param-map-v1`): the MLP is `Linear(obs_dim,hidden)-ReLU-Linear(hidden,n_actions)`. Transmitted arrays are exactly `w1[obs_dim,hidden]`, `b1[hidden]`, `w2[hidden,n_actions]`, `b2[n_actions]` float32 in NumPy-compatible layout (PyTorch `weight` is transposed on export/import). The same payload therefore loads in the NumPy baseline and the PyTorch learner, which gives a cross-backend regression test for `peer.encode/decode`. `peer.py` keeps its tensor-only npz format, 1 MiB cap, zip-inflation bound, dtype/shape/finite checks, sender check, `mixing` alpha<=0.5 rule, rollback, and the "optimizer state is never imported" rule. Compatibility header adds `param_map`, `backend`, `reward_id`, `action_space` and `encoder_sha256` to the existing `encoder/obs_dim/hidden/n_actions` fields; any mismatch rejects with a named reason.

On acceptance: policy replaced (or mixed), target network = copy of new policy, optimizer re-created (moments dropped), `version += 1`, previous params kept for one rollback, structured event with source node, source version, payload sha256, pre/post version, current and candidate validation scores, margin, validation wall seconds. Local-update parameter changes and peer-import changes are separate event types so evidence can distinguish them.

## 5. Peer exchange

Transport is the existing `archipelago_peer.PeerServer` (HTTP, private network) / `archipelago_transport` envelope: `Envelope(src, dst, version, payload)`. The node runtime adapts `LearnerNode` to it. In-process tests use the in-memory network; containers use HTTP. Peers are a static manifest `NODE_IDS` plus `PEER_URLS` (`node-01=http://node-01:9000,...`); cross-host deployments pass explicit URLs.

Exchange window: at each episode boundary (`episode_end`) a node (1) broadcasts one candidate offer (its latest published policy) to allowed neighbors, (2) drains received candidates, (3) validates each via `peer.offer` with `eval_fn` = mean return of the policy over its own **validation seeds in a node-private `GridWorld` instance** (no access to the live world; same world config; no optimizer updates), margin from config, (4) logs accept/reject with reason, (5) at most one in-flight candidate per neighbor, <= 1 accepted candidate per window, dedupe by `(sender, version, sha256)`, no backlog replay after a reconnect (only the latest compatible version is offered). Validation cost is recorded (`validation_seconds`, evaluations run). Candidates and validation never read test seeds.

Information sharing (modes 4 and 5 in `evaluation.md`) uses a separate non-model peer message class that carries no parameters. Its schema and effect on the learner are defined by T30 before any claim; T27 only guarantees a generic `kind`-tagged peer payload path so it can be added without touching model-offer code.

## 6. Partition and fault model

The coordinator sends each node, at episode `reset`, the same immutable seeded fault schedule: windows `{start_tick, end_tick, cut_links:[[a,b],...]}` over **peer links only**. Each node enforces it itself using its own tick counter (learned from `act` requests), so a coordinator crash does not erase an active partition. Sender and receiver both enforce (cut links neither send nor accept). The coordinator-node observation/action link and telemetry link are never cut by this schedule; separate scenario flags exist for node restart/failure (`kill_node` removes the drone from the world through the adapter, distinct from a container restart) and telemetry outage (blocks only the telemetry sink). The demonstration schedule is the existing 900-tick horizon, cut at 300, rejoin at 600; a run config must prove episode length and battery reach those ticks (T30 acceptance), otherwise the faults never trigger.

## 7. Checkpoints

A generation is a directory `ckpt/gen-<n>/` containing `model.safetensors`-equivalent arrays (NumPy `.npz`, `allow_pickle=False`), `optimizer`, `replay`, `rng`, `counters.json`; every file is fsynced and hash-listed in `gen-<n>/MANIFEST.json`. The active generation is switched by atomically replacing `ckpt/CURRENT` (write temp, fsync, `os.replace`, fsync dir) with the generation number and the manifest SHA-256. Loading verifies hashes and falls back to the previous complete generation; partial generations are ignored and garbage-collected (keep 3). Restored state: policy, target, optimizer moments, replay (contents, write index), RNG streams, exploration schedule, step/version/sequence/episode counters, peer dedupe cache, telemetry spool cursor. Test: kill between every pair of writes and assert a consistent restore.

## 8. Telemetry

Nodes and coordinator write JSONL events to a bounded durable spool on their own volume and a background shipper POSTs batches to the API ingest. Outage: spool grows to a cap, then drops oldest with an explicit dropped counter; catch-up after recovery is idempotent (`event_id` unique). Nothing in channels (a) or (b) waits on telemetry. The API persists to TigerData through the existing Persister; TigerData is a durable observability store only, never a coordination dependency. Every record carries `run_id`, `commit`, `config_hash`, `seed`, `node_id`, `host`, `phase`.

### 8.1 Telemetry ingest wire format (fixed for T36 and T27/T28 senders)

`POST /v1/telemetry` on the API, header `Authorization: Bearer <TELEMETRY_TOKEN>` (>=16 chars, separate from user login tokens), body `{"source": "<node-id|coordinator>", "boot_id": "<id>", "events": [<canonical v0 record>, ...]}` with at most 500 events and 256 KiB per request. Records are validated against the canonical contract models (`LearningEvent`, `MetricSample`, `WorldSnapshot`, `Action`); anything else is rejected per item. Response `200 {"accepted": n, "duplicates": n, "rejected": [{"event_id": "...", "reason": "..."}]}`; dedupe by `(run_id, event_id)`; a whole-request failure (auth 401, size 413, malformed JSON 400, ingest overloaded 503 with `Retry-After`) never partially applies. Accepted events are appended to the run's event log (live stream/replay) and passed to the Persister; ingest never blocks the run loop and has a bounded in-memory queue.

## 9. API and dashboard

`ARCHIPELAGO_ADAPTER=live` makes the API a client of the coordinator (`COORDINATOR_URL`, token). It fails visibly at startup and in `/readyz` if the coordinator is unreachable; it never falls back to `FixtureAdapter`. Run lifecycle commands map to coordinator control. Existing `/v1/runs`, events paging, WebSocket and auth are reused. Dashboard additions are limited to the live panels listed in the assignment (positions/actions, update counts/loss/versions, peer offers and decisions, topology/fault phase, training vs frozen evaluation curves, resources, telemetry freshness/backlog) and must label stale, replay and disconnected states.

## 10. Packaging and dependencies

- `torch==2.14.1` in dependency group `torch` (lockfile resolved from PyPI by the integrator). Images and CI install the **CPU** wheel (`uv pip install --torch-backend cpu torch==2.14.1`, index `download.pytorch.org/whl/cpu`, unreachable from the authoring sandbox by policy, reachable from GitHub runners and Vultr). Local development in the sandbox uses the PyPI wheel. Never bitwise-compare results across wheel variants.
- One node image: `python:3.12-slim`, non-root, `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`; memory limit set from measured RSS (T27 measures before keeping 512 MB).
- Compose services: `coordinator`, `node-01..04` (own volumes, `peers` network + `control` network to the coordinator), existing `api`, `web`, `proxy`, `grafana`; `timescaledb` only in the local profile.

## 11. Local development smoke (no Docker)

`tests/e2e/test_live_local.py` starts the coordinator and four node runtime processes on localhost ports with temp directories, runs a short episode set, and asserts: optimizer updates occurred in each node process, distinct per-node policy hashes, actions came from nodes (not the API), a cut link carried zero peer traffic while local updates continued, an offer was transmitted and a decision logged, and a killed-and-restarted node resumes from its checkpoint with continued sequence numbers. The Docker path (`make check-full`) re-runs the same scenario on Compose.

## 12. Coordinator HTTP interface (API -> coordinator, private network)

Stdlib server, JSON, bearer token `COORDINATOR_TOKEN` (>=16 chars). Only the API (and tests) call it; browsers never do. The privileged snapshot route uses a second token `COORDINATOR_ADMIN_TOKEN`.

| Endpoint | Body / response | Notes |
|---|---|---|
| `POST /v1/runs` | `{run_config: RunConfig, plan: Plan}` -> `{run_id, status}` | 409 if a run is active (one active run). Rejects unknown reward ids, nodes without a URL, non-distinct starts. |
| `GET /v1/runs/{id}` | status, episode, tick, phase, per-node health (`ready/unavailable/killed`), deadline-miss counts, config hash, commit | `status` follows the API run states (`created/starting/running/paused/stopping/completed/failed/interrupted`). |
| `POST /v1/runs/{id}/commands` | `{command_id, command: pause|resume|step|stop, expected_revision}` | Duplicate `command_id` is idempotent; stale revision 409. |
| `GET /v1/runs/{id}/events?after_sequence=&limit=` | `{events, latest_sequence, oldest_sequence}` | Canonical v0 records only: `WorldSnapshot` (tick snapshots, `topology.links` = peer links currently allowed by the schedule), `MetricSample` (coverage, episode_return, deadline_missed, node_unavailable, fault_phase, node_killed, train/eval phase) with `phase` set. Sequences are unique and continue across a coordinator restart (persisted spool). |
| `GET /v1/runs/{id}/snapshot` | privileged `WorldSnapshot` | admin token only; the world's hidden state never goes to nodes. |
| `GET /healthz`, `GET /readyz` | liveness / real-simulator availability and node reachability | `readyz` is false when the sim cannot import or no node is reachable; no fixture fallback exists in this service. |

`Plan` = `{node_urls: {node_id: url}, deadline_ms: 500, episodes: [{kind: train|validation|test, seed: int, count?: 1}], eval_every: int, fault_schedule: [{start_tick, end_tick, cut_links}], kill_node: {node_id, tick} | null, telemetry_outage: {start_tick, end_tick} | null}`. Episode order is explicit and recorded; `test` seeds only ever run in frozen `eval` mode and are excluded from candidate gating. The coordinator distributes `fault_schedule` to nodes at each episode `reset` (section 6) and records its hash in the run manifest.

## 13. Amendments after independent review (A1-A17) - these supersede earlier text

Source: independent review of this agreement against the code (T24 verdict, 2026-10-10). Where a numbered amendment conflicts with sections 1-12, the amendment wins.

**A1 Exchange cadence and partitions.** Peer exchange windows run on a tick cadence inside the episode: each node triggers a window when its own tick counter (learned from `act` requests) reaches a multiple of `exchange_every_ticks` (default 50), in a background thread that never runs in the act path, plus a final window at episode end. Fault decisions use the node's current tick, so windows during a cut see the cut. Within a window candidates are evaluated in arrival order and at most one is accepted; the rest are rejected with reason `window_limit` without spending validation cost. The existing catch-up resend on link reopen counts as an offer in the next window, not outside one.

**A2 Feedback carries what was executed.** `/v1/feedback` adds `executed_command` (stay/north/east/south/west), `action_index` and `deadline_missed`. The node stores `(obs, executed action, reward, next_obs, done)`; a fallback `stay` is trained as `stay`. The coordinator awaits all feedback acknowledgements (bounded by `2 * deadline_ms`) before issuing tick t+1 `act` calls; the node publishes the new inference snapshot at the end of its feedback handler, so `act(t+1)` uses the post-feedback(t) policy deterministically. Staleness is keyed on `(episode, tick)` lexicographically.

**A3 Restart-safe identity.** `boot_id` = 8 hex characters generated at process start. `event_id = "{node}-{boot_id}-{sequence}"`. Sequences are monotonic across boots: the checkpoint stores a reserved ceiling reserved in blocks of 1000 before use, so numbers issued after the last generation can never be reissued. The node's pending `(obs, action)` per step key is part of the checkpointed state. The peer client `seq` is persisted the same way so receivers do not drop post-restart messages as stale.

**A4 `episode_end` semantics.** Sent to every node in the world except killed ones (including terminated and unavailable nodes); returns `202 {window_id}` immediately and runs the final window in the background. A `reset` waits up to 5 s for a running window, then cancels it and records `window_cancelled`.

**A5 Run configuration.** `POST /v1/control {command:"configure", ...}` is sent once per run before the first reset: hyperparameters, epsilon schedule, validation margin, `world_config` (size, n_targets, obstacle density, radius, max_ticks, battery_scale, reward_id), `gate_seeds` (node-private model-selection seeds, disjoint from the Plan episode seeds), `n_validation_agents`, `encoder_id`, `exchange_every_ticks`, `seed`. The node-private validation world is a labeled simulated-oracle model-selection step; it receives no live-world state.

**A6 Encoder identity and ownership.** The encoder lives in `packages/learning` (`archipelago_learning.encoders`), with entry points for a contract `Observation` (pose = floor(x), floor(y)) and for raw `GridWorld` dicts. Ids include geometry: `grid-flat-v1-s{size}-r{radius}`; the header carries the sha256 of the canonical definition. Learners compare ids exactly. The "equals grid-flat-v0" claim holds only for size 8; the NumPy baseline uses matching ids in cross-backend tests.

**A7 Telemetry context and time.** Canonical v0 records are unchanged and cannot carry commit, config hash, seed, host or episode. The ingest request gains a request-level `context` object `{commit, config_hash, seed, host, boot_id, episode?}` stored beside the events. `sim_tick` in records is the global index `episode * max_ticks + tick`. Extra decision evidence (validation seconds, evaluations, margin, payload sha256) is emitted as additional `MetricSample`s with `unit` and `phase` set; the accepted-candidate source and sha256 stay in `LearningEvent.reason` as today.

**A8 Transport and trust facts.** Envelope is `Envelope(src, dst, seq, payload, version, digest)`; effective payload cap is 64 KiB (current model about 4.4 KB). Control port 8080, peer port 9000. `PEER_URLS` format is `node-01=http://node-01:9000,...`. Peer endpoints require a shared `PEER_TOKEN` bearer (private network defense in depth) and the receiver binds `src` to the authenticated token holder's declared id list.

**A9 Plan source.** The coordinator `Plan` comes from a server-side plan file (`COORDINATOR_PLAN_FILE`), whose hash is recorded in the manifest. `POST /v1/runs` on the API takes only the run config plus an optional plan name from an allowlist; request-supplied `node_urls` are forbidden (the coordinator attaches `NODE_CONTROL_TOKEN` to node requests).

**A10 Snapshots.** Public stream snapshot: poses, discovered coverage, links, and obstacles only for cells in the union of nodes' discovered cells. Privileged snapshot (admin token): full obstacles, targets, battery.

**A11 Readiness.** In live mode API `/readyz` means coordinator reachable and at least one node ready; it does not depend on run activity.

**A12 Compose networks.** `peers` (nodes only, internal), `control` (nodes + coordinator + API-to-coordinator, internal), `ingest` (nodes + API telemetry route only, internal), `core` (api, web, proxy, grafana, db). Nodes do not join `core`.

**A13 Battery and schedules.** The Plan carries `battery_scale`. Moving drones exhaust the battery near tick 250 at scale 1; the demonstration (900 ticks, cut 300, rejoin 600) requires `battery_scale >= 4`. The coordinator rejects, before starting, any fault schedule that extends past the minimum feasible survival horizon of the configured world.

**A14 Node removal.** `Sim2DAdapter.kill(node)` (T28 scope) removes the drone from `drones` and `agents` (vanish, no wreck, absent from snapshot poses). Per-episode `RunConfig` is derived with a distinct env seed and run id suffix; `event_id` and sequence re-stamp per episode so ids never repeat across episodes or runs; `emitted_at_utc` is wall time (simulation time stays in `sim_tick`); `topology.links` is populated from the current allowed links.

**A15 Ownership grants.** T27 additionally owns `packages/node/peer/**`, `packages/transport/**`, `tests/transport/**` and `packages/node/learner/**`. T26 owns the encoders module. The integrator adds the new packages to the workspace, mypy `files` and pytest path configuration.

**A16 Numeric acceptance.** Act latency p99 under 50 ms while the validation worker runs at 100% load on 0.5 CPU; deadline-miss rate under 1% in the local e2e; node memory limit = 1.5x peak training RSS rounded up to 64 MiB; "distinct per-node policy" means distinct parameter hashes after identical-seed initialization plus different data, asserted after training.

**A17 Checkpoint cadence.** A node writes a generation every 200 feedback steps and at each `episode_end`; file names are fixed (`policy.npz`, `target.npz`, `optimizer.npz`, `replay.npz`, `rng.json`, `counters.json`, `MANIFEST.json`); replay file size bound is `capacity * obs_dim * 4 * 2` bytes.

## 14. Normative control message shapes (coordinator <-> node), implementing A1-A5

All bodies are JSON objects; unknown fields are rejected by the receiver; every request carries `run_id`.

- `POST /v1/control {"command":"configure","run_id":..., "hyperparameters":{"lr","gamma","hidden","capacity","batch","target_every","train_steps_per_feedback"}, "epsilon_schedule":{"start","end","decay_episodes"}, "margin":float, "world_config":{"size","n_targets","obstacle_density","sense_radius","max_ticks","battery_scale","reward_id"}, "gate_seeds":[int,...], "n_validation_agents":int, "encoder_id":str, "exchange_every_ticks":int, "seed":int}` -> `200 {"ok":true,"config_hash":str}`. Sent once per run before the first reset; the node rejects a second configure with a different hash while a run is active (409).
- `POST /v1/control {"command":"reset","run_id":...,"episode":int,"mode":"train"|"eval","fault_schedule":[{"start_tick","end_tick","cut_links":[[a,b],...]}]}` -> `200 {"ok":true,"policy_version":int}`. Starts an episode; `eval` freezes optimizer, exploration and replay.
- `POST /v1/act {"run_id","episode","tick","deadline_ms","observation":<contract Observation>}` -> `200 {"node_id","tick","action":<contract Action>,"policy_version":int,"epsilon":float}`; stale `(episode,tick)` -> 409.
- `POST /v1/feedback {"run_id","episode","tick","reward":float,"next_observation":<contract Observation>,"terminated":bool,"truncated":bool,"executed_command":"stay|north|east|south|west","action_index":int,"deadline_missed":bool}` -> `200 {"accepted":bool,"replay_size":int,"train_steps":int,"policy_version":int}`. Idempotent per `(run_id,episode,tick)`. The policy snapshot is published before the response is sent.
- `POST /v1/control {"command":"episode_end","run_id","episode","tick":int}` -> `202 {"window_id":str}` (final exchange window runs in the background; see A4).
- `POST /v1/control {"command":"checkpoint","run_id"}` -> `200 {"generation":int}`; `{"command":"stop","run_id"}` -> `200`.
- `GET /v1/status` additionally returns `config_hash`, `exchange_every_ticks`, `window` state (`idle|running`), `last_window_id`, `dropped_events`, `boot_id`, `sequence_ceiling`.
- Peer endpoints (A8) require `Authorization: Bearer <PEER_TOKEN>`; telemetry shipper posts to `TELEMETRY_URL` (`POST /v1/telemetry`, section 8.1 + A7 `context`).

## 15. Amendment A18: v2 observation, rew-v1, shared visit summaries (T38)

Source: the T37 variant study (`experiments/out/T37/summary.md`, "Adoption note"). A18 adopts its selected configuration in the live runtime and adds one peer message class. It adds ids and fields; it removes nothing. Every old id (`grid-flat-v1-s{size}-r{radius}`, `rew-v0`, `sched-v0`) behaves exactly as before and is covered by regression tests. Where A18 conflicts with sections 1-14, A18 wins.

**Ids (all versioned, all exact-match).**

| kind | id | meaning |
|---|---|---|
| encoder | `grid-flat-v2-visits-s{S}-r{R}` | float32[57] for R=2: v1 prefix (25 crop, floor(x)/S, floor(y)/S, battery) + 25 own stand-on counts `min(count,4)/4` of the crop cells (spawn cell counts 1, staying counts) + 4 frontier fractions N,E,S,W (share of the 5 cells just outside the crop that are inside the map and not in the node's own buffer) |
| encoder | `grid-flat-v2-visits-shared-s{S}-r{R}` | float32[82] for R=2: the 57 above + 25 peer flags (1 if a peer reported standing on that crop cell through the information message) |
| reward | `rew-v1` | new cell +0.5, target +5.0 split over living nodes and only for targets not sensed at reset, step -0.01, wall/agent collision -2.0 each, invalid action -0.1, revisit -0.25 whenever a node ends a tick on a cell it already stood on. Computed by the world (`GridWorld`), never by a node |
| learner schedule | `sched-t37-v1` | epsilon 1.0 -> 0.05 linearly over the first 50% of the TRAINING episodes (evaluated once per training episode start, index 0 = first training episode; eval episodes do not count), Adam lr 1e-3, gamma 0.95, batch 32, hidden 32, target sync every 50 optimizer steps, one optimizer step per transition, replay 50000 per node, double DQN, loss 0.5 * mean squared TD error, no gradient clipping, `done` = termination only |
| learner schedule | `sched-v0` | legacy: the values in `configure` as given, epsilon per act (`decay_episodes * max_ticks` acts), single DQN |

The encoder definition text (and its SHA-256, the compatibility header of A6) lives in `archipelago_learning.visits` (v2) and `archipelago_learning.encoders` (v1). The recipe registry is `archipelago_learning.schedules.SCHEDULES`; `archipelago_coordinator.models.LEARNER_SCHEDULES` mirrors it (the coordinator image does not ship the learning package) and a test keeps them equal. A configure that names `sched-t37-v1` with any value that contradicts the registry is refused (node: 422 `bad_config`, coordinator: 422 before the run starts).

**Selection.** `Plan.reward_id` (optional) is the versioned reward id the world runs. It is authoritative over `RunConfig.reward_id`: the legacy default `rew-v0` in a run request is replaced by it, any other differing id is refused (422 "contradicts"). The coordinator's `GridWorld` is built from the effective id, so the per-step reward the nodes receive in `feedback` is the world's. `Plan.node_config.encoder_id` is a family name (`grid-flat-v1` default, `grid-flat-v2-visits`, `grid-flat-v2-visits-shared`; geometry is taken from the live world) or a full id; `node_config.learner_schedule_id` defaults to `sched-v0`; `hyperparameters.double_dqn` and `epsilon_schedule.decay_fraction` (fraction of the plan's training episodes, `ceil`) are new; a registered schedule fills what the plan leaves out. The `configure` message (section 14) gains `learner_schedule_id` and `hyperparameters.double_dqn`; its `epsilon_schedule.decay_episodes` is then the resolved number of training episodes of the span.

**Where the ids are recorded.** Coordinator run status and `manifest.json`: `ids {reward_id, reward_source (plan|run_config), encoder_id (resolved, with geometry), learner_schedule_id}`. Node `GET /v1/status`: `encoder_id`, `encoder_sha256`, `reward_id`, `learner_schedule_id`, `double_dqn`, `obs_dim`. Node checkpoint `counters.json` identity: `encoder`, `encoder_sha256`, `reward_id`, `learner_schedule`, `double_dqn` (+ sizes). Peer model payload header: `encoder`, `encoder_sha256`, `reward_id` (existing fields). Node telemetry: one `MetricSample` per boot/configure named `ids:<encoder_id>:<reward_id>:<learner_schedule_id>` (value 1, unit `flag`), because canonical records and the ingest context have no field for them.

**Rejection rules.** A model candidate whose header names another encoder id, encoder sha256 or reward id is rejected before any evaluation (`incompatible encoder: ...`, `incompatible reward_id: ...`; first mismatch named, encoder checked first). A checkpoint whose identity differs is refused at load with the field named (`checkpoint encoder mismatch`, `reward_id mismatch`, `learner_schedule mismatch`); a checkpoint written before A18 has none of the new fields and is read as `sched-v0`, single DQN, so it loads only into a legacy-configured node. A visit summary with another encoder id, size, run or episode is never applied (below).

**Node-local memory.** The v2 features come from `NodeMemory` (`archipelago_learning.visits`), built only from the node's own `act`/`feedback` observations and the summaries it received: the buffer is the union of the crops (cells whose value is not -1), own counts come from the received poses, one count per simulation tick (the observation of tick t arrives twice, as `observation` of act(t) and as `next_observation` of feedback(t-1), and counts once; a tick that never reached the node leaves no count). It is reset at each episode reset, written into every checkpoint (`node.memory`) and restored with the node. The node never reads world state. Deviation from the study, stated: the study's information bus also merged peers' MAP cells into each drone's buffer; the live world has no such merge, so the crop and the frontier see only the node's own sensing. The golden parity test therefore runs the harness with the visit half of the bus only.

**Visit summary (`visit-summary-v1`, non-model information message).** Same `Envelope` and `PeerServer` path as model offers (bearer `PEER_TOKEN`, `allowed_src`, digest = sha256 of payload, `src` = authenticated sender), recognised by a JSON payload (first byte `{`; model offers are npz archives starting `PK`). One UTF-8 JSON object with exactly the members `kind` (`visit-summary-v1`), `node` (must equal the envelope `src`), `run_id`, `episode`, `tick` (sender's), `encoder` (full encoder id), `size`, `n` (population count) and `cells`: base64 of a bitmap of `size*size` bits, bit `y*size+x`, little-endian bit order within each byte, no bits beyond the grid. It is the sender's FULL stood-on set of the current episode (not a delta), so a lost, refused or cut message is repaired by the next one. Size bound: `ceil(size^2/8)` bytes of bitmap (32 B at 16x16, at most 8 KiB at the 256x256 maximum), whole payload at most `MAX_SUMMARY_BYTES = 16 KiB` (well under the 64 KiB envelope cap); larger, malformed, inconsistent, wrong-kind or wrong-digest messages get 422, a `node` that differs from the sender 403, a wrong token 401, a sender outside `NODE_IDS` 403.

*Cadence and effect.* After every `act` the node wakes one sender thread per peer (never in the act path; a stuck peer delays only its own thread; POST timeout `SUMMARY_TIMEOUT`, default 0.5 s, no retries). Each wake sends the latest own set, so consecutive ticks coalesce. The receiver applies a summary only if its `run_id` and `episode` equal the node's current ones (otherwise 202, counted `summaries_ignored`) and its envelope `seq` is higher than the last applied one from that sender (otherwise 202, `summaries_stale`; the stream has its own persisted allocator, `summary_seq.json`). Applying replaces nothing and removes nothing: the peer's set is unioned into `NodeMemory.peer_by_src[sender]`; the 25 peer flags of the next encoded observation are the union over senders at the crop cells. No parameters, replay rows, policy outputs or map cells travel on it.

*Partitions.* Sender and receiver honour the node's own fault schedule exactly as for model offers: the sender sends nothing on a link the schedule cuts at its current tick (`summaries_cut`); the receiver refuses with 403 any envelope on a cut link before looking at its class (`summaries_received_cut`, a separate counter from the model `received_cut`) and re-checks inside the handler. Flags learned before a cut stay until the episode ends (information already obtained is not erased); nothing new crosses it. A summary is never a model transfer: it does not touch the model inbox, `offers_*` counters, exchange windows, validation, decisions or the learner, and it is not a `LearningEvent`. Counters in status: `summaries_sent`, `summaries_cut`, `summaries_unreachable`, `summaries_refused_by_peer`, `summaries_received`, `summaries_received_cut`, `summaries_applied`, `summaries_ignored`, `summaries_stale`, `summaries_rejected`; `status.summaries` shows the peer sources and, with `SUMMARY_TRACE=1`, the receiver ticks at which each sender's summary was applied (evidence for tests).

**Node-private validation world.** It uses the same encoder: one `NodeMemory` per validation drone, and for the shared id the drones swap their stood-on sets every tick (all links up, no cuts in the private world), the study's bus without map merging. The world runs the run's reward id.

**Smaller changes.** Exploration under `sched-t37-v1` is per training episode (`Node.train_ep`, persisted); `epsilon` in `act` responses and status is constant within an episode. Checkpoints store the replay's filled prefix only (rows `0..min(n, capacity)-1`; the old full-ring form still loads), so a 50000-row buffer is not serialised as megabytes of zeros while the learner lock is held; the A17 size bound is unchanged. Compose `x-node-env` gains `ENCODER_FAMILY`, `REWARD_ID`, `LEARNER_SCHEDULE_ID` (defaults: the T37 ids) so a node that boots before any run matches the demo plans, which select the T37 ids (`battery_scale` stays 4).

**Limits.** Single-world, 2-drone, scenario-`connected` evidence only (T37); the live 4-node fleet, partitions and p2p model transfer under the T37 recipe are exercised by tests, not by a new study. The T37 verdict stands: learning beats idle, random and untrained, and does not beat the rule explorer on return.

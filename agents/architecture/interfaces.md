# Shared contracts: v0 design baseline

T01 owns making these executable under `packages/contracts/`, with JSON Schema/Pydantic fixtures and generated TypeScript types. T01 may refine details but must record changes before dependent tasks begin. One canonical schema generates consumers; duplicated handwritten shapes are forbidden.

## Common fields

Every event includes `schema_version`, `event_id`, `run_id`, `source_node_id` (nullable for harness), `sim_tick`, `emitted_at_utc`, `sequence`, and `kind`. IDs are stable strings, times are ISO-8601 UTC, positions are ENU meters, velocities m/s, battery is normalized [0,1]. Node sequence is monotonic per run; out-of-order delivery is accepted only according to the message type. Unknown schema majors are rejected explicitly.

## Records and ownership

| Contract | Required data | Producer -> consumer |
|---|---|---|
| RunConfig | seed streams, simulator/version, scenario hash, node manifest, observation/action/reward IDs, learner config, mode, budgets, fault schedule | API -> harness/nodes |
| Observation | tick, node ID, local crop and known-mask, own pose/energy, visible markers, allowed neighbor summaries | adapter -> own node only |
| Action | node ID, tick, action-space version, command, policy version | node -> adapter |
| WorldSnapshot | tick, poses, obstacles, coverage, topology, run status | harness -> UI/replay only |
| PeerEnvelope | sender/recipient, message ID, model version, architecture/encoder/reward hashes, payload length/hash, logical tick, TTL, type | peer -> peer |
| LearningEvent | local update count/loss, previous/new version, transfer accepted/rejected, reason, candidate score, bytes, wall time | node -> metrics |
| MetricSample | metric name, finite numeric value, unit, node/run/tick, UTC time, phase | components -> storage |
| ArtifactManifest | path, SHA-256, format/version, run/node, tick, commit/config hash | writer -> storage/replay |

P0 peer types: `hello`, `model_offer`, `model_request`, `model_payload`, `ack`. Negotiate supported versions at hello. Provisional payload cap: 4 MiB and one in-flight candidate per neighbor; T01/T05 may lower it after model sizing. No arbitrary filesystem paths from received messages; resolve artifacts through validated IDs.

## SimulatorAdapter (Python protocol)

```python
capabilities() -> SimulatorCapabilities
reset(config: RunConfig) -> dict[NodeId, Observation]
step(actions: dict[NodeId, Action]) -> StepResult
snapshot() -> WorldSnapshot
close() -> None
```

StepResult contains per-agent observations, rewards, terminations, truncations and infos, matching PettingZoo's simultaneous-action semantics. Dynamic missing nodes and invalid actions have documented deterministic behavior. `snapshot()` is privileged; learner objects are never given it. The 3D adapter may require substeps and a different action/encoder version without changing event IDs or run lifecycle.

## API surface

- `POST /v1/runs`: validate config and resource cap; require idempotency key; return run ID or conflict.
- `GET /v1/runs/{id}`: status/config/artifact manifest, no secrets.
- `POST /v1/runs/{id}/commands`: typed pause/resume/step/stop; command ID and expected run revision prevent duplicate/stale changes.
- `GET /v1/runs/{id}/events?after_sequence=...`: bounded paginated replay.
- `WS /v1/runs/{id}/stream`: snapshot then sequenced deltas; slow viewers get bounded queues and a resnapshot instruction.
- `GET /healthz`: process liveness. `GET /readyz`: ability to accept new runs, with dependency status.
- Private node endpoints: observation/action exchange, peer envelopes and checkpoint status; no public browser access.

Run states: `created -> starting -> running <-> paused -> stopping -> completed`; failures lead to `failed`. Stopped early runs retain an explicit completion reason. A process restart marks orphaned runs `interrupted` until checkpoint recovery is verified; never silently claim they completed.

Auth: same-origin authenticated dashboard/API; verify WebSocket origin and session; authenticated mutating routes; no wildcard production CORS. A simple owner-operated demo login is sufficient initially. Protect peer transport separately.

## Database outline

- `runs`: run_id primary key, timestamps, status, seed/config JSON, commit/image versions, scenario and model metadata.
- `node_metrics`: time-series samples with time/run/node/tick/metric/value/unit/phase; hypertable configured by migration.
- `events`: stable event_id and typed payload, ordered sequence, run/node/tick/time; unique event IDs support dedupe.
- `artifacts`: path/hash/format/size/run/node and producer metadata.

Retention, metric sampling frequency and disk caps are explicit run config, initially short development retention. Keep raw benchmark outputs long enough for verification; never purge them inside an agent cleanup loop. Migration owner is T08; only the integrator serializes migration ordering.

## Compatibility gate

CI validates known-good fixtures, malformed payloads, unsupported major versions, stale sequence, NaN/Inf, oversize payloads and 2D z=0 conventions. Use fixtures to let UI, transport and simulation proceed independently. Breaking changes require an ADR, producer/consumer migration plan and updated fixtures in the same integration sequence.

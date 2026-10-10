# T11 demo narrative, storyboard and script (PREP DRAFT)

Status: DRAFT written before T09/T10 exist. Nothing here is a measured result.
Convention: every number is written `PENDING-T09:<name>` and must be replaced from an exported run artifact (run ID + file + field). Anything marked UNVERIFIED describes UI or API behavior read from specs/handoffs, not observed running. The dashboard (T06) is not on main as of base 7999daf (`apps/web/src/App.tsx` is a 16-line scaffold), so UI element names below are planned, not confirmed.

## 1. Narrative skeleton

1. Problem. After a disaster, a team of drones searches an unknown area for rescue markers. Radio links break (range, obstacles, jamming). A swarm that depends on a central controller or on constant sharing stalls when the network splits.
2. Idea (hypothesis, not a promise). Each drone owns its own policy, replay buffer and optimizer. It keeps acting and learning alone during a split, and exchanges validated learning updates with peers when links return. (roadmap: "connected swarm -> separated islands -> independent adaptation -> reconnection -> measured knowledge transfer")
3. What the audience sees: a 2D map with 4 drones, links drawn between them, per-node policy versions, a partition at tick 300 and rejoin at tick 600 (900-tick horizon, evaluation.md), and a log of accepted/rejected transfers.
4. Honest comparison: Independent DQN, information-sharing DQN, Archipelago (the required modes for a transfer claim). Central controller and CTDE only if T09 ran them; otherwise say "not evaluated".
5. Limitations stated on screen: synthetic 2D world, no real vehicles, preliminary seed count, 2D weights not assumed to transfer to 3D, scripted fault schedule (acceptable) but no scripted winning metric.

Allowed claims: only what the exported data shows, including neutral or negative results. Forbidden: general intelligence, benchmark superiority, "X% better" without a paired comparison from T09, any 3D or real-hardware claim beyond the T12 adapter spike result.

## 2. Mode labels (required on every shot)

Each shot carries one label: LIVE (running stack), REPLAY (recorded actions of run `PENDING-T09:run_id`, commit `PENDING-T09:commit`), or ILLUSTRATIVE (diagram, not data). The UI must show run ID and a LIVE/REPLAY badge (T06 acceptance). UNVERIFIED that the badge exists yet.

## 3. Storyboard / shot list (3:00)

API surface (VERIFIED by reading services/api/src/archipelago_api/app.py): `POST /v1/runs`, `POST /v1/runs/{id}/commands` (pause/resume/step/stop), `GET /v1/runs/{id}/events`, WebSocket `/v1/runs/{id}/stream` (snapshot, deltas, `resnapshot`), `/healthz`, `/readyz`. Contract record kinds (VERIFIED, packages/contracts/schemas): `world_snapshot` (poses, coverage, topology, obstacles, run_status), `learning_event` (previous_version, new_version, update_count, loss, transfer none|accepted|rejected, candidate_score, bytes, source_node_id), `metric_sample` (metric, value, unit, phase), `peer_envelope` (model offers etc.), `run_config`, `artifact_manifest`.

| # | Time | Label | On screen (planned UI, UNVERIFIED) | Data source | Narration beat |
|---|---|---|---|---|---|
| 1 | 0:00-0:20 | ILLUSTRATIVE | Title, problem statement, disaster-area cartoon | none | Problem |
| 2 | 0:20-0:40 | LIVE (fresh browser at `PENDING-T10:url`) | Dashboard, run config, Start | `POST /v1/runs` | One command starts a seeded mission |
| 3 | 0:40-1:05 | LIVE or REPLAY | Connected map, 4 drones, coverage rising, node policy versions | `world_snapshot` over WS; `learning_event` local updates | Local learning while connected |
| 4 | 1:05-1:30 | REPLAY (seeded schedule) | Tick 300: links cut, two islands, "partitioned" banner | `world_snapshot.topology`; link metric `PENDING-T05:name` | Both islands keep acting and learning |
| 5 | 1:30-1:50 | REPLAY | Per-island policy versions diverge; coverage during split | `learning_event` (transfer=none), `metric_sample` | Independent adaptation |
| 6 | 1:50-2:15 | REPLAY | Tick 600 rejoin; peer offers, accepted/rejected markers with candidate_score and bytes | `peer_envelope`, `learning_event` transfer=accepted/rejected | Reconnection and validated transfer |
| 7 | 2:15-2:40 | REPLAY, charts from exports | Comparison chart across modes, all seeds shown, recovery time | `experiments/reports/*` (T09) | Measured outcome, including negative parts |
| 8 | 2:40-3:00 | ILLUSTRATIVE + REPLAY provenance card | Limitations, run ID, commit, artifact hashes, 3D path | `artifact_manifest` | Limits and what is next |

Controls to demo only if verified in T06 (UNVERIFIED): pause, step, reset, replay scrubbing. If live fails, play the REPLAY of the same run (T11 slice 4) and label it REPLAY.

## 4. Script (placeholders)

Do not fill a placeholder from memory. Each `PENDING-T09:<metric>` is replaced by value + unit + run ID + artifact path + seeds.

1. "After a disaster, drones search for survivors, but radio links fail exactly when they are needed."
2. "A seeded mission: 4 drones, each with its own learner. Run `PENDING-T09:run_id`, commit `PENDING-T09:commit`. This view is [LIVE|REPLAY]."
3. (optional, single-run figure only) "Coverage is `PENDING-T09:coverage_tick300` at tick 300 in this run."
4. "At tick 300 the network splits into two islands. Each keeps searching and training alone. Coverage gain during the split: `PENDING-T09:partition_coverage_gain`, versus `PENDING-T09:connected_coverage_gain` in the matched connected run."
5. "At tick 600 the links return. Drones exchanged `PENDING-T09:offers` offers; `PENDING-T09:accepted` accepted, `PENDING-T09:rejected` rejected; peer traffic `PENDING-T09:peer_bytes`."
6. "Against independent and information-sharing learners over `PENDING-T09:n_seeds` paired seeds, final coverage differed by `PENDING-T09:paired_delta` (CI `PENDING-T09:ci`)." Direction and wording (better / no different / worse) are decided by the data. If the CI spans zero, say so. Label "preliminary" if seeds are fewer than planned.
7. "Recovery after rejoin took `PENDING-T09:recovery_ticks` ticks." If the resilience denominator is undefined, say "undefined"; do not compute a score.
8. "Limits: synthetic 2D world, `PENDING-T09:n_seeds` seeds, no real vehicles; 3D is a separate adapter (T12 status: `PENDING-T12:status`)."

Negative-result branch: if Archipelago does not beat baselines, replace beats 6-7 with: "In our runs, transfer did not improve held-out coverage; what the system did show is the partition and rejoin mechanism working (events above)." Choose only after T09 data exists.

## 5. Entry point and fallback (confirm with T10/T06)

Documented entrypoint: `PENDING-T10:url-or-compose-command` (UNVERIFIED). A fresh browser must reach the demo with no local state. Replay fallback: recorded actions plus exported `events.json`/`topology.json`/`metrics.json` served statically, labeled REPLAY, with the provenance card. Call the cloud demo "deployed" only with T10 smoke-test evidence.

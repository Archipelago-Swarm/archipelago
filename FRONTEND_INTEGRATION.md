# Mission Frontend Integration

Source of truth: `packages/mission/archipelago_mission/sim.py` (`MissionSim.frame()`, `result()`, `emit()`, `decide_log()`, `Skill.to_dict()`) and `__main__.py`. All names below are camelCase exactly as emitted. Engine tuning is finished; the JSON schema is stable and `apps/web/public/mission/seed-1042.json` is committed and final. Sample payloads in section 14 are real output of `--seed 1042`.

```
Mission begins -> UAVs search -> POIs discovered -> verified -> RF links change
   -> disruption -> agent adapts -> skill created/adopted -> skill propagates P2P
   -> behavior changes -> mission success / fail
```

World: 10000 x 6000 m (`meta.world`); x right, y down (map metres). Search grid 16 x 10 (`meta.searchGrid`). Tick `dt` = 5 s (`meta.dt`). Time limit 1800 s, 6 UAVs, 6 POIs (`meta.config`, which also has `rendezvous_after` 0.45).

## 1. Mission State: `frame.mission` (every frame)

| Field | Type / range | Unit | UI use |
|---|---|---|---|
| seed | int | | footer/debug |
| status | `RUNNING` \| `SUCCESS` \| `FAILED` | | banner; terminal states stop the run |
| elapsedTime | float 0..timeLimit | s | clock |
| timeLimit | float (1800) | s | countdown denominator |
| totalPois / requiredPois | int (6 / 6; required defaults to all) | | "verified N / required" |
| discoveredPois / verifiedPois | int 0..totalPois | | counters |
| fleetKnowledgeCoverage | float 0..1 | ratio | progress bar vs `knowledgeThreshold` |
| knowledgeThreshold | float (0.8) | ratio | threshold tick mark |
| operationalNodes / totalNodes | int (<=6 / 6) | | fleet health |

**knowledgeCoverage definition** (`_fleet`): let V = set of POIs verified by at least one operational UAV. Per operational UAV, coverage = |V intersect that UAV's own locally-verified POIs| / |V|. `fleetKnowledgeCoverage` = mean of that over operational UAVs (0 if V empty or no UAV alive). So it measures how much of the verified truth has propagated to every node over P2P links, not just what exists somewhere.

**Success condition** (`_update_status`): `verifiedPois >= requiredPois AND fleetKnowledgeCoverage >= knowledgeThreshold` -> `SUCCESS`, event `MISSION_SUCCESS`. Otherwise `elapsedTime >= timeLimit` or no operational UAVs -> `FAILED`, event `MISSION_FAILED`. The spec form `elapsed < timeLimit` holds because the fail check fires when time reaches the limit. Seed 1042 ends SUCCESS at 510 s (6/6 verified, coverage 0.806 >= 0.8); the same seed without skills FAILS at the time limit.

## 2. UAV state: `frame.uavs[]` (6 entries, order stable, always present even when failed)

| Field | Type / range | Unit | Frequency | UI use |
|---|---|---|---|---|
| id | `UAV-01`..`UAV-06` | | static | key |
| role | `SCOUT` \| `SENSOR` \| `RELAY` \| `GENERAL` | | static | icon/label |
| sensorRadius, commRadius | float (SCOUT 600/2600, SENSOR 520/3000, RELAY 250/5200, GENERAL 420/3400) | m | static nominal (sensor shrinks in nav zone but field stays nominal; use `sensorState`) | range rings |
| status | `OPERATIONAL` \| `FAILED` | | occasional (once, on PLATFORM_FAILURE) | grey out |
| health | 1.0 or 0.0 | | occasional | |
| position {x,y} | float | m | per-frame | marker |
| heading | float | rad, atan2(dy,dx) | per-frame | marker rotation |
| speed | float 0..55 | m/s | per-frame | |
| currentObjective | `DISCOVER_POI` \| `VERIFY_POI` \| `STAY_OPERATIONAL` \| `MAINTAIN_CONNECTIVITY` \| `SHARE_INFORMATION` \| `NONE` (failed) | | per-frame, changes occasionally | label/colour |
| currentAction | `search_cell` \| `approach_poi` \| `leave_degradation_zone` \| `rejoin_peer` \| `move_toward_peer` \| `hold_position` \| `failed` | | per-frame | tooltip |
| sensorState | `NOMINAL` \| `DEGRADED` (inside nav zone) \| `OFFLINE` | | per-frame | badge |
| communicationState | `CONNECTED` \| `DEGRADED` \| `ISOLATED` \| `OFFLINE` | | per-frame | badge |
| neighbors | string[] of UAV ids with `connected:true` links | | per-frame | |
| networkComponent | int (-1 for failed) | | per-frame | partition colouring |
| activeSkill | skill id \| null (non-null only when status is LOCAL or ADOPTED) | | occasional | "skill active" glow |
| skills | Skill[] (section 6) | | occasional | skill panel |
| localKnowledgeCount | int | observations held | per-frame | |
| knownPois / verifiedPois | POI id[] known / verified by THIS node | | occasional | per-node knowledge (drives coverage) |
| searchedCells | int | cells | per-frame | |
| lastSync | {peerId: time} | s | per-frame | sync freshness |

## 3. POI state: `frame.pois[]` (6 entries)

| Field | Type / range | Notes |
|---|---|---|
| id | `POI-01`.. | static |
| position {x,y} | m | static |
| trueType | `INFRASTRUCTURE` \| `VEHICLE` \| `SIGNAL` | **GROUND TRUTH. Must not be shown before `state=="VERIFIED"`** (it is present in every frame including UNKNOWN). Show `classification` instead. |
| state | `UNKNOWN` \| `DISCOVERED` \| `VERIFIED` | fleet-wide (any operational UAV). Only advances, but a POI can briefly drop if its only holder fails |
| discovered / verified | bool | convenience of state |
| classification | type string or `UNKNOWN` | best fleet estimate; can differ from trueType until verified |
| confidence | float 0..1 | best node's confidence; verified at >= `verify_conf` 0.9 |
| observationCount | int | max over nodes |
| lastObserved | s \| null | |
| knownBy / verifiedBy | UAV id[] | nodes that hold it (per-node propagation) |

Update frequency: per-frame values, transitions are rare (6 discover, 6 verify per run). Events: `POI_DISCOVERED`, `POI_VERIFIED`.

## 4. RF links: `frame.links[]`

One entry per pair of operational UAVs whose distance is under `min(commRadius)`; pairs beyond range are absent. Pairs involving a failed UAV are absent.

| Field | Type | Notes |
|---|---|---|
| sourceNodeId, targetNodeId | UAV id | undirected, source < target |
| signalQuality | float 0..1 | `1 - d/range`, forced to 0 if terrain-obstructed, multiplied by `(1 - severity)` inside a comm-degradation zone |
| distance | m (int) | |
| connected | bool | `signalQuality >= 0.15` |
| reason | `null` when connected; else `OBSTRUCTED` (terrain line-of-sight blocked) \| `DEGRADED` (comm-degradation zone) \| `WEAK` (just low quality) | |

**The frontend must not recompute RF** (LOS, quality, connectivity and partitions are decided server-side from the terrain model). Draw only what is here: solid for connected, dashed/red with the reason for `connected:false`. Components: `uav.networkComponent`. Events: `NETWORK_PARTITIONED`, `NETWORK_RECONNECTED`.

## 5. Disruptions: `frame.disruptions[]` (always 3 entries, scheduled per seed)

Fields: `id` (EVT-1..3), `type`, `active` (bool), `startTime` (s), `endTime` (s or null), `position {x,y}` (null for PLATFORM_FAILURE; moves per tick for zones), `radius` (m), `velocity {x,y}` (m/s), `severity` 0..1, `nodeId` (target UAV for PLATFORM_FAILURE, else null).

| type | Effect | Status |
|---|---|---|
| COMMUNICATION_DEGRADATION | moving circle; links touching it get quality x (1 - 0.95), reason `DEGRADED` | IMPLEMENTED |
| NAVIGATION_DEGRADATION | static circle; UAV inside: sensor radius shrinks, speed halves, objective `STAY_OPERATIONAL`, sensorState `DEGRADED` | IMPLEMENTED |
| PLATFORM_FAILURE | one UAV (UAV-02..06) permanently fails at `startTime`; `active` is false immediately after (instant); event `UAV_FAILED` | IMPLEMENTED |
| POI_CHANGED | | NOT IMPLEMENTED |
| ROLE_CHANGED | | NOT IMPLEMENTED |

The disruption list includes future ones (`startTime` in the future, `active:false`); do not announce them before the `DISRUPTION_STARTED`/`UAV_FAILED` event time. `active:false` with `endTime` in the past = ended.

## 6. Skill lifecycle

One skill exists today: `adaptive_search_spacing` (`behaviorType: SEARCH_REGION_SELECTION`, id `adaptive_search_spacing_v1`).

```
LOCAL (learned by a node)            -- learned after N redundant search selections (N = 3..8 per node)
  -> peer over a CONNECTED link without it/with lower (version, utility) copies it
RECEIVED (tick of transfer)
  -> VALIDATING (next tick; 2 ticks)
  -> ADOPTED   if utilityScore >= 0.5 and confidence >= 0.5
  -> REJECTED  otherwise (id added to node's rejected set; never re-offered)   [no rejection occurs in seed 1042]
SKILL_USED event: first time a node uses an active skill (LOCAL or ADOPTED) to pick a search cell
```

Only LOCAL/ADOPTED skills are shared onward, so propagation is multi-hop. Transfers only happen over `connected:true` links, so partitions and comm degradation delay or stop spread; that gap is what the `fleetKnowledgeCoverage` and success story depends on.

**Behavior it modifies** (search cell selection, `_pick_cell`): without the skill a UAV picks the nearest unsearched cell by local coverage only, and counts redundancy when re-searching a cell a peer covered. With the skill it (a) excludes cells peers have searched (`peer_cells`), (b) excludes cells peers claimed as target in the last 150 s, (c) adds a penalty for cells closer than `spacing_m` (2500 m) to peers' last-known positions. The decision log marks this with `skillUsed` and `reason` "...peer coverage exclusion and 2500 m spacing". Observable effect: stats `redundancyRatio` falls; UAVs spread out.

**Who created / who transferred**
- Created: `skill.sourceNodeId` + `skill.createdAt` (in `uav.skills[]`) and the `SKILL_LEARNED` event `nodeId`. Note: two nodes can independently learn the same id `..._v1`; the node keeps the higher-utility copy, so `sourceNodeId` is the creator of the copy that node holds.
- Transferred: `skill.receivedFrom` + `receivedAt` (per holder, null for the creator), and the `SKILL_TRANSFERRED` event (`sourceNodeId` -> `targetNodeId`, `signalQuality`). `receivedFrom` is the immediate peer, not the creator: use it to draw the chain.
- Adopted: `skill.status` and the `SKILL_ADOPTED` event (`nodeId`, `fromNodeId`).

Skill fields (`Skill.to_dict`): `id`, `name`, `version`, `sourceNodeId`, `createdAt` (s), `receivedAt` (s|null), `receivedFrom` (id|null), `confidence` 0..1, `utilityScore` 0..1, `behaviorType`, `status` (`LOCAL|RECEIVED|VALIDATING|ADOPTED|REJECTED`), `metadata` (`spacing_m`, `excludes_peer_covered_cells`, `excludes_peer_claimed_cells`, `trigger` string). Frequency: occasional (changes only on lifecycle steps).

## 7. Skill events (in `events[]`)

| type | demo | Fields |
|---|---|---|
| SKILL_LEARNED | true | nodeId, skillId, version, utilityScore, reason |
| SKILL_TRANSFERRED | true | sourceNodeId, targetNodeId, skillId, version, signalQuality |
| SKILL_RECEIVED | **false** | nodeId, skillId, fromNodeId |
| SKILL_ADOPTED | true | nodeId, skillId, version, fromNodeId |
| SKILL_REJECTED | true | nodeId, skillId, reason (implemented, not triggered in seed 1042) |
| SKILL_USED | true | nodeId, skillId, version, behavior (`search_cell_selection`) |

No `SKILL_VALIDATING` event; read `uav.skills[].status` for that state.

## 8. Decision events: top-level `decisions[]`

Logged only when a node's (objective, action, target, skill) changes, not every tick.

Fields: `timestamp` (s), `nodeId`, `state` (objective enum as `currentObjective`), `action`, `reason` (human sentence, display as-is), `metrics` (object: `neighbors`, `verifiedKnown`, `discoveredKnown`; optional `confidence`, `redundancyHits`, `isolatedTicks`, `cell`), `skillUsed` (skill id or null), `target` ([x, y] m or null). Use for the "why" panel; decisions with `skillUsed != null` are the skill-in-action moments.

## 9. Event feed: top-level `events[]`

Common fields: `id` (`E-0001`), `type`, `timestamp` (s), `demo` (bool), plus type-specific fields. **Show only `demo:true` in the primary feed**; `demo:false` are internal (`SKILL_RECEIVED`, `NETWORK_TOPOLOGY_CHANGED`) and belong in a debug view only. Types: `MISSION_STARTED` (requiredPois, totalPois, timeLimit), `POI_DISCOVERED` (poiId, nodeId, confidence), `POI_VERIFIED` (poiId, nodeId, confidence, classification), `DISRUPTION_STARTED` (eventId, disruptionType, position, radius, severity), `DISRUPTION_ENDED` (eventId, disruptionType), `UAV_FAILED` (nodeId, eventId), `NETWORK_PARTITIONED` / `NETWORK_RECONNECTED` (components: id[][]), `NETWORK_TOPOLOGY_CHANGED` (componentCount; demo false), skill events (section 7), `MISSION_SUCCESS` / `MISSION_FAILED` (elapsedTime, verifiedPois, fleetKnowledgeCoverage). The `eventCount`/`decisionCount` in each frame are the lengths so far.

## 10. Data flow

```
MissionSim.step()  (every dt=5 s of sim time)
  disruptions -> per-UAV decide+move+sense -> RF links (terrain LOS, comm zones)
  -> P2P exchange over connected links (obs, cells, positions, skills)
  -> skill lifecycle -> frame()
        |
   frames[] + events[] + decisions[] + stats   (result())
        |
 CLI: python -m archipelago_mission --out seed-1042.json
        |
 apps/web: fetch replay JSON -> pick frame by playhead time
        -> MissionHUD.tsx (mission/stats), FlightMap.tsx (uavs/pois/links/disruptions)
        -> feed = events/decisions with timestamp <= frame.time
```

## 11. Transport

Currently a **static replay JSON** produced by the CLI:

```
python -m archipelago_mission --seed 1042 --out apps/web/public/mission/seed-1042.json
```
(Windows PowerShell: `$env:PYTHONPATH="packages/mission;packages/sim"` first. Other flags: `--no-skills` baseline, `--compare` prints skills-on vs off stats to stdout.) The file for seed 1042 is already committed at that path; regenerate only if the engine changes.

Top-level keys: `meta` (seed, dt, skillsEnabled, world{width,height}, searchGrid{nx,ny}, config{...}), `frames[]` (103 for seed 1042, one per tick, index = tick-1), `events[]`, `decisions[]`, `stats`. Each frame: `tick, time, mission, uavs, pois, links, disruptions, eventCount, decisionCount`. Feed for a frame = events and decisions with `timestamp <= frame.time` (or slice the first `eventCount` events / `decisionCount` decisions: equivalent and cheaper). `stats`: redundantCellMarks, uniqueCellMarks, skillsLearned, skillTransfers, skillAdoptions, skillRejections, partitions, dataSyncs, redundancyRatio, missionStatus, elapsedTime, firstSkillLearnedAt, finalSkillHolders.

**Live endpoint: NOT IMPLEMENTED.** No HTTP/WebSocket/SSE server exists in `packages/mission`. To step live in Python:
```python
from archipelago_mission.sim import MissionSim, MissionConfig
sim = MissionSim(MissionConfig(seed=1042))
while sim.status == "RUNNING":
    sim.step(); f = sim.frame()      # also appended to sim.frames
    # new events: sim.events[prev:], new decisions: sim.decisions[prev:]
run = sim.result()
```

## 12. Recommended layout

Main: FlightMap (terrain, comm/nav zones as translucent circles, links coloured by connected/reason, UAV markers with objective colour and skill glow, POIs as `?`/`!`/typed icon by `state`). Top HUD: status, clock vs `timeLimit`, verified N/required, coverage bar with `knowledgeThreshold` mark, nodes alive. Right: event feed (demo:true), decisions "why" panel for the selected UAV. Bottom: timeline scrubber with event markers; skill lineage (`createdAt`, `receivedFrom` chain, status per node). Selecting a UAV shows `skills`, `knownPois`, `lastSync`.

## 13. Demo moments (seed 1042, times in sim seconds from the committed replay)

A. Search + first POI: `POI_DISCOVERED`/`POI_VERIFIED` POI-06 (t=5 / 10 s, UAV-01). B. Early disruption/partition: `NETWORK_PARTITIONED` t=80 s (UAV-01 alone), `NETWORK_RECONNECTED` t=85 s; `DISRUPTION_STARTED` NAVIGATION_DEGRADATION t=95 s (ends 425 s), and a second partition at t=95 s. C. Skill created: `SKILL_LEARNED` UAV-02 at t=110 s (13 redundant selections, utility 1.0). D. Propagation: `SKILL_TRANSFERRED` UAV-02 -> UAV-01 and UAV-03 (115 s), -> UAV-06 (120 s); `SKILL_ADOPTED` 125/125/130 s; `SKILL_USED` follows. E. Independent learning in the second partition: UAV-04 `SKILL_LEARNED` t=155 s, transfers to UAV-05 (165 s), adopted 175 s. F. COMM zone: `DISRUPTION_STARTED` COMMUNICATION_DEGRADATION t=195 s (ends 460 s); POI-04 verified 195 s, POI-03 375 s, POI-01 415 s, POI-02 505 s. G. Outcome: `MISSION_SUCCESS` t=510 s (6/6 verified, coverage 0.806 >= 0.8). Contrast: the `--no-skills` baseline for the same seed FAILS at 1800 s. The `PLATFORM_FAILURE` (UAV-04, 533 s) is scheduled but not reached in this replay.

## 14. Sample payloads (seed 1042, copied from the committed `apps/web/public/mission/seed-1042.json`)

MissionState (`frames[-1].mission`):
```json
{"seed":1042,"status":"SUCCESS","elapsedTime":510.0,"timeLimit":1800.0,"totalPois":6,"requiredPois":6,"discoveredPois":6,"verifiedPois":6,"fleetKnowledgeCoverage":0.806,"knowledgeThreshold":0.8,"operationalNodes":6,"totalNodes":6}
```
UAV (UAV-01, adopted Skill received from UAV-02; `lastSync` truncated to 2 of 5 entries):
```json
{"id":"UAV-01","role":"SCOUT","status":"OPERATIONAL","position":{"x":3549.2,"y":4093.9},"heading":0.954,"speed":55.0,"health":1.0,"sensorRadius":600.0,"commRadius":2600.0,"currentObjective":"DISCOVER_POI","currentAction":"search_cell","sensorState":"NOMINAL","communicationState":"ISOLATED","neighbors":[],"networkComponent":0,"activeSkill":"adaptive_search_spacing_v1","skills":[{"id":"adaptive_search_spacing_v1","name":"adaptive_search_spacing","version":1,"sourceNodeId":"UAV-02","createdAt":110.0,"receivedAt":115.0,"receivedFrom":"UAV-02","confidence":0.8,"utilityScore":1.0,"behaviorType":"SEARCH_REGION_SELECTION","status":"ADOPTED","metadata":{"spacing_m":2500.0,"excludes_peer_covered_cells":true,"excludes_peer_claimed_cells":true,"trigger":"13 redundant search selections"}}],"localKnowledgeCount":5,"knownPois":["POI-06"],"verifiedPois":["POI-06"],"searchedCells":52,"lastSync":{"UAV-02":120.0,"UAV-03":145.0}}
```
POI:
```json
{"id":"POI-01","position":{"x":8374.6,"y":2000.3},"trueType":"INFRASTRUCTURE","state":"VERIFIED","discovered":true,"verified":true,"classification":"INFRASTRUCTURE","confidence":0.939,"observationCount":3,"lastObserved":425.0,"knownBy":["UAV-02","UAV-03","UAV-04","UAV-05","UAV-06"],"verifiedBy":["UAV-02","UAV-03","UAV-04","UAV-05","UAV-06"]}
```
Links (connected; and disrupted/blocked):
```json
{"sourceNodeId":"UAV-04","targetNodeId":"UAV-05","signalQuality":0.793,"distance":539,"connected":true,"reason":null}
{"sourceNodeId":"UAV-03","targetNodeId":"UAV-04","signalQuality":0.006,"distance":2970,"connected":false,"reason":"DEGRADED"}
{"sourceNodeId":"UAV-01","targetNodeId":"UAV-03","signalQuality":0.0,"distance":2225,"connected":false,"reason":"OBSTRUCTED"}
```
(The DEGRADED link is from the frame at t=195 s; the others from the last frame.)

Disruptions (`frames[-1]`; floats trimmed). Note PLATFORM_FAILURE is scheduled at 533.29 s, after the mission ends at 510 s, so `UAV_FAILED` never fires in this replay:
```json
{"id":"EVT-1","type":"COMMUNICATION_DEGRADATION","active":false,"startTime":193.55,"endTime":455.04,"position":{"x":4266.6,"y":4382.9},"radius":1815.9,"velocity":{"x":-2.19,"y":1.72},"severity":0.95,"nodeId":null}
{"id":"EVT-3","type":"PLATFORM_FAILURE","active":false,"startTime":533.29,"endTime":null,"position":null,"radius":null,"velocity":null,"severity":1.0,"nodeId":"UAV-04"}
```
Events:
```json
{"id":"E-0011","type":"SKILL_LEARNED","timestamp":110.0,"demo":true,"nodeId":"UAV-02","skillId":"adaptive_search_spacing_v1","version":1,"utilityScore":1.0,"reason":"Re-searched 13 cells already covered by peers; learned spacing/coordination strategy."}
{"id":"E-0014","type":"SKILL_TRANSFERRED","timestamp":115.0,"demo":true,"sourceNodeId":"UAV-02","targetNodeId":"UAV-01","skillId":"adaptive_search_spacing_v1","version":1,"signalQuality":0.664}
{"id":"E-0020","type":"SKILL_ADOPTED","timestamp":125.0,"demo":true,"nodeId":"UAV-01","skillId":"adaptive_search_spacing_v1","version":1,"fromNodeId":"UAV-02"}
{"id":"E-0032","type":"SKILL_LEARNED","timestamp":155.0,"demo":true,"nodeId":"UAV-04","skillId":"adaptive_search_spacing_v1","version":1,"utilityScore":1.0,"reason":"Re-searched 17 cells already covered by peers; learned spacing/coordination strategy."}
{"id":"E-0034","type":"SKILL_TRANSFERRED","timestamp":165.0,"demo":true,"sourceNodeId":"UAV-04","targetNodeId":"UAV-05","skillId":"adaptive_search_spacing_v1","version":1,"signalQuality":0.354}
{"id":"E-0036","type":"SKILL_ADOPTED","timestamp":175.0,"demo":true,"nodeId":"UAV-05","skillId":"adaptive_search_spacing_v1","version":1,"fromNodeId":"UAV-04"}
{"id":"E-0007","type":"NETWORK_PARTITIONED","timestamp":95.0,"demo":true,"components":[["UAV-01","UAV-02","UAV-03","UAV-06"],["UAV-04","UAV-05"]]}
{"id":"E-0074","type":"MISSION_SUCCESS","timestamp":510.0,"demo":true,"elapsedTime":510.0,"verifiedPois":6,"fleetKnowledgeCoverage":0.806}
```
Decision (skill in use):
```json
{"timestamp":115.0,"nodeId":"UAV-02","state":"DISCOVER_POI","action":"search_cell","reason":"Search cell (4, 1) chosen with peer coverage exclusion and 2500 m spacing.","metrics":{"neighbors":1,"verifiedKnown":1,"discoveredKnown":1,"cell":401},"skillUsed":"adaptive_search_spacing_v1","target":[2812,900]}
```
Stats (`stats`): `{"redundantCellMarks":193,"uniqueCellMarks":148,"skillsLearned":2,"skillTransfers":4,"skillAdoptions":4,"skillRejections":0,"partitions":2,"dataSyncs":305,"redundancyRatio":0.566,"missionStatus":"SUCCESS","elapsedTime":510.0,"firstSkillLearnedAt":110.0,"finalSkillHolders":6}`

## 15. Mock / fallback

The committed replay file for seed 1042 is the mock and the fallback: `apps/web/public/mission/seed-1042.json` (committed, final; regenerate with the section 11 command only if the engine changes). **1042 is the recommended demo seed. Other seeds are not tuned (seeds 2 and 3 fail).** The `?seed=` URL param is a frontend concern: map seed -> `/mission/seed-<seed>.json`; only 1042 is pre-generated and tuned, so any other seed must fall back to 1042 (or the user runs the CLI for it). If the fetch fails, show an error panel, not synthetic data.

## 16. Source map

| Concern | Location |
|---|---|
| frame/result/events/decisions | `packages/mission/archipelago_mission/sim.py` (`frame`, `result`, `emit`, `decide_log`, `_fleet`, `_update_status`) |
| Skill schema and lifecycle | `sim.py` (`Skill`, `_exchange_and_links`, `_skill_lifecycle`, `_pick_cell`) |
| RF links | `sim.py` `_compute_links` (uses terrain from packages/sim) |
| Disruptions | `sim.py` `_build_events`, `_update_disruptions` |
| CLI | `packages/mission/archipelago_mission/__main__.py` |
| Frontend integration points | `apps/web/src/MissionHUD.tsx` (mission state, counters, stats), `apps/web/src/FlightMap.tsx` (uavs, pois, links, disruptions); existing `replay.ts`, `client.ts`, `Timeline.tsx`, `Lineage.tsx` are candidates for the replay loader, feed and skill lineage but are not wired to this schema yet |

## 17. Implementation status

- [x] IMPLEMENTED: mission state, success/fail logic, knowledgeCoverage
- [x] IMPLEMENTED: UAV state, POI state (UNKNOWN/DISCOVERED/VERIFIED), RF links with reasons
- [x] IMPLEMENTED: COMMUNICATION_DEGRADATION, NAVIGATION_DEGRADATION, PLATFORM_FAILURE
- [x] IMPLEMENTED: skill learn / transfer / validate / adopt / reject / use; decisions log; event feed with demo flag
- [x] IMPLEMENTED: CLI replay export, `--no-skills` baseline, `--compare`
- PARTIAL: skills (a single skill type, `adaptive_search_spacing`; spacing fixed at 2500 m); only seed 1042 is tuned (seeds 2, 3 fail)
- PARTIAL: frontend wiring (MissionHUD.tsx/FlightMap.tsx exist; mission replay schema consumption not verified here)
- MOCKED: the committed static replay file (seed 1042) is the only data source for the UI
- NOT IMPLEMENTED: live HTTP/WebSocket/SSE endpoint; POI_CHANGED disruption; ROLE_CHANGED disruption; multi-seed pre-generated files (only 1042); `SKILL_VALIDATING` event

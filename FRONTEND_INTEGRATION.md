# Mission Frontend Integration

Source of truth: `packages/mission/archipelago_mission/sim.py` (`MissionSim.frame()`, `result()`, `emit()`, `decide_log()`, `Skill.to_dict()`), `rf.py` (`RFEngine.compute_links`) and `__main__.py`. All names below are camelCase exactly as emitted. Engine tuning is finished; the JSON schema is stable and `apps/web/public/mission/seed-1002.json` is committed and final (floats rounded to 3 decimals by the CLI). Sample payloads in section 15 are real output of `--seed 1002`.

```
Mission begins -> UAVs search -> POIs discovered -> verified -> RF links change
   -> disruption -> agent adapts -> skill created/adopted -> skill propagates P2P
   -> behavior changes -> mission success / fail
```

## 0. World, units, time

- **Canonical unit is METRES everywhere** (positions, radii, distances, altitudes, disruption radii, decision `target`). x right, y down.
- World is **400 km x 500 km = 4 x 5 tiles of 100 km**. The frontend must read it from `meta.world` and **never hardcode a world size** (the old 10 x 6 km values are gone):
  ```json
  "world":{"width":400000.0,"height":500000.0,"tileMeters":100000.0,"tilesX":4,"tilesY":5,"units":"meters"}
  ```
- Conversion: 1 tile = `meta.world.tileMeters` = 100,000 m; `tiles = m / tileMeters`; `km = m / 1000`. Display distances in km (`distanceKm`, `radius / 1000`). Fit the map from `meta.world`, not constants.
- `meta.searchGrid` = `{"nx":16,"ny":20}` coarse search cells of 25 km x 25 km (`width/nx`).
- Tick `meta.dt` = **30 s**; `config.time_limit` = **28800 s** (8 h); 6 UAVs, 6 POIs; `config.rendezvous_after` 0.45, `skill_transfer_s` 60, `verify_conf` 0.9. **Frames are emitted every 30 s of sim time**: frame index = tick (frame 0 is t=0; seed 1002 has 285 frames, t=0..8520 s).
- **Speed-up**: the mission takes 8520 sim-seconds to succeed on seed 1002 (2 h 22 min). UAV speeds are realistic and are not accelerated in the backend; watch the replay with the frontend's playback speed-up (default 60 sim-s per real s = ~2.4 min; 120 = ~71 s).
- **All UAVs are identical (no roles)**: speed 140 m/s, sensor radius 40 km, cruise altitude 400 m AGL, one RF profile (nominal link range 40 km, extended 100 km). There are no `role` or `rfProfile` fields.

## 1. Mission State: `frame.mission` (every frame)

| Field | Type / range | Unit | UI use |
|---|---|---|---|
| seed | int | | footer/debug |
| status | `RUNNING` \| `SUCCESS` \| `FAILED` | | banner; terminal states stop the run |
| elapsedTime | float 0..timeLimit | s | clock |
| timeLimit | float (28800) | s | countdown denominator |
| totalPois / requiredPois | int (6 / 6; required defaults to all) | | "verified N / required" |
| discoveredPois / verifiedPois | int 0..totalPois | | counters |
| fleetKnowledgeCoverage | float 0..1 | ratio | progress bar vs `knowledgeThreshold` |
| knowledgeThreshold | float (0.8) | ratio | threshold tick mark |
| operationalNodes / totalNodes | int (<=6 / 6) | | fleet health |

**knowledgeCoverage definition** (`_fleet`): let V = set of POIs verified by at least one operational UAV. Per operational UAV, coverage = |V intersect that UAV's own locally-verified POIs| / |V|. `fleetKnowledgeCoverage` = mean of that over operational UAVs (0 if V empty or no UAV alive). It measures how much of the verified truth has propagated to every node over P2P links, not just what exists somewhere.

**Success condition** (`_update_status`): `verifiedPois >= requiredPois AND fleetKnowledgeCoverage >= knowledgeThreshold` -> `SUCCESS`, event `MISSION_SUCCESS`. Otherwise `elapsedTime >= timeLimit` or no operational UAVs -> `FAILED`, event `MISSION_FAILED`. Seed 1002 ends SUCCESS at **8520 s** (6/6 verified, coverage 0.972 >= 0.8). The same seed with `--no-skills` FAILS at the 28800 s limit (5/6 verified, 5 of 6 UAVs left because UAV-02 fails at 13417 s). In local scans most seeds (1000-1011, 1, 2, 3, 1002) succeed with skills; seeds 1006 and 7 fail even with skills. Only 1002 has a committed replay.

## 2. UAV state: `frame.uavs[]` (6 entries, order stable, always present even when failed)

| Field | Type / range | Unit | Frequency | UI use |
|---|---|---|---|---|
| id | `UAV-01`..`UAV-06` | | static | key |
| sensorRadius | float (40000) | m | static nominal (shrinks in nav zone but field stays nominal; use `sensorState`) | sensor ring |
| commRadius | float = RF profile **nominal** range (40000) | m | static | nominal range ring only; real reach comes from `links[]` |
| altitudeMeters | float, AGL. Starts at 400 (cruise), max 2000 | m | per-frame | altitude badge |
| status | `OPERATIONAL` \| `FAILED` | | occasional (once, on PLATFORM_FAILURE) | grey out |
| health | 1.0 or 0.0 | | occasional | |
| position {x,y} | float | m | per-frame | marker |
| heading | float | rad, atan2(dy,dx) | per-frame | marker rotation |
| speed | float 0..140 (reduced in nav zone; 0 when holding) | m/s | per-frame | |
| currentObjective | `DISCOVER_POI` \| `VERIFY_POI` \| `STAY_OPERATIONAL` \| `MAINTAIN_CONNECTIVITY` \| `SHARE_INFORMATION` \| `NONE` (failed) | | per-frame, changes occasionally | label/colour |
| currentAction | `search_cell` \| `approach_poi` \| `leave_degradation_zone` \| `rejoin_peer` \| `move_toward_peer` \| `hold_position` \| `failed` | | per-frame | tooltip |
| sensorState | `NOMINAL` \| `DEGRADED` (inside nav zone) \| `OFFLINE` | | per-frame | badge |
| communicationState | `CONNECTED` (>=1 connected link) \| `DEGRADED` (no connected link but a disrupted link in a comm zone) \| `ISOLATED` \| `OFFLINE` (failed). Seed 1002 only shows CONNECTED and ISOLATED | | per-frame | badge |
| neighbors | string[] of UAV ids with `connected:true` links (sorted) | | per-frame | connected peers |
| networkComponent | int connected-component id of the RF graph (-1 for failed) | | per-frame | partition colouring |
| activeSkill | skill id \| null (non-null only when status is LOCAL or ADOPTED) | | occasional | "skill active" glow |
| skills | Skill[] (section 7) | | occasional | skill panel |
| localKnowledgeCount | int | observations held | per-frame | |
| knownPois / verifiedPois | POI id[] known / verified by THIS node | | occasional | per-node knowledge (drives coverage) |
| searchedCells | int | cells | per-frame | |
| lastSync | {peerId: time} | s | per-frame | sync freshness |

**Isolated UAVs climb.** After 3 consecutive ticks (90 s) with no connected link, a UAV gains 150 m per tick (cap 2000 m AGL) to extend its geometric horizon and clear terrain; once it has a neighbour again it descends 150 m per tick back to its cruise altitude. The first climb emits a decision `{state:"MAINTAIN_CONNECTIVITY", action:"climb_for_los", metrics:{altitudeMeters}}` (section 9). After 8 isolated ticks (240 s) the node also heads for the last-known peer position (`rejoin_peer`). Show climbing as an altitude change; `currentAction` stays the movement action.

## 3. POI state: `frame.pois[]` (6 entries)

| Field | Type / range | Notes |
|---|---|---|
| id | `POI-01`.. | static |
| position {x,y} | m | static |
| trueType | `INFRASTRUCTURE` \| `VEHICLE` \| `SIGNAL` | **GROUND TRUTH. Must not be shown before `state=="VERIFIED"`** (present in every frame including UNKNOWN). Show `classification` instead. |
| state | `UNKNOWN` \| `DISCOVERED` \| `VERIFIED` | fleet-wide (any operational UAV). Only advances, but a POI can briefly drop if its only holder fails |
| discovered / verified | bool | convenience of state |
| classification | type string or `UNKNOWN` | best fleet estimate; can differ from trueType until verified |
| confidence | float 0..1 | best node's confidence; verified at >= `verify_conf` 0.9 |
| observationCount | int | max over nodes |
| lastObserved | s \| null | |
| knownBy / verifiedBy | UAV id[] | nodes that hold it (per-node propagation) |

Update frequency: per-frame values, transitions are rare (6 discover, 6 verify per run). Events: `POI_DISCOVERED`, `POI_VERIFIED`.

## 4. RF links: `frame.links[]` (RFLink contract)

**Who computes what.** The backend builds the RF graph G(t) **once per sim tick (every 30 s)** from node positions, altitudes, the RF profile, terrain line of sight and active comm-degradation zones, and the whole P2P layer (data sync, skill transfer, partitions) runs only over G(t). **The frontend must NOT recompute RF**: no distance-to-quality maths, no LOS, no connectivity or partition logic. Render and inspect the fields as emitted. Between ticks interpolate UAV positions if you like, but keep link styling from the floor frame.

**Which pairs appear.** One entry per pair of operational UAVs whose 3-D distance is **<= 150 km** (`report_range_m`), **connected or not**. Pairs farther than 150 km, and pairs involving a failed UAV, are **omitted = no edge** (draw nothing). `id` is `"<source>~<target>"`, source < target by id. Max 15 links (6 UAVs).

### RFLink fields (real link, UAV-02~UAV-04 at t=1680 s)

```json
{"id":"UAV-02~UAV-04","sourceNodeId":"UAV-02","targetNodeId":"UAV-04","distanceMeters":22006.15,"horizontalDistanceMeters":22006.15,"distanceKm":22.006,"sourceAltitudeMeters":400.0,"targetAltitudeMeters":400.0,"geometricHorizonMeters":164800.0,"lineOfSight":"CLEAR","rfQuality":0.844,"bandwidthFactor":0.922,"state":"EXCELLENT","connected":true,"attenuationFactor":1.0,"disruptionFactor":1.0,"lastUpdated":1680.0,"debug":{"distanceQuality":0.844,"terrainFactor":1.0,"platformFactor":1.0,"minClearanceMeters":471.653,"linkClass":"NORMAL","rejectReason":null}}
```

| Field | Type / range | Meaning |
|---|---|---|
| id | string | `"UAV-02~UAV-04"` |
| sourceNodeId, targetNodeId | UAV id | undirected |
| distanceMeters | float, m | 3-D distance (horizontal + altitude difference) |
| horizontalDistanceMeters | float, m | ground distance |
| distanceKm | float, km | `distanceMeters / 1000`, ready for display |
| sourceAltitudeMeters, targetAltitudeMeters | float, m AGL | current `uav.altitudeMeters` of each end |
| geometricHorizonMeters | float, m | radio horizon `4.12 * (sqrt(h1) + sqrt(h2)) km` (h in m) |
| lineOfSight | `CLEAR` \| `PARTIAL` \| `BLOCKED` \| `NOT_EVALUATED` | terrain LOS result; `NOT_EVALUATED` when rejected before LOS (beyond range/horizon) |
| rfQuality | float 0..1 | final link quality (see model); the single number to drive opacity |
| bandwidthFactor | float 0..1 | usable throughput fraction; 0 when not connected. Paces skill transfer (section 7) |
| state | `EXCELLENT` \| `GOOD` \| `DEGRADED` \| `MARGINAL` \| `DISCONNECTED` | `connected` and `rfQuality >=` 0.80 / 0.60 / 0.35 / 0.10 respectively (else MARGINAL when connected); `DISCONNECTED` when not connected |
| connected | bool | `rfQuality >= 0.15` |
| attenuationFactor | float 0.5..1 | extra loss when the distance approaches the horizon |
| disruptionFactor | float 0..1 | 1 = untouched; <1 = link passes through an active COMMUNICATION_DEGRADATION zone |
| lastUpdated | s | sim time the link was computed (= frame time) |
| debug.distanceQuality | float 0..1 | quality from distance alone |
| debug.terrainFactor | float | LOS multiplier: CLEAR 1.0, PARTIAL 0.55, BLOCKED 0.08, 0 if not evaluated |
| debug.platformFactor | float | product of both nodes' profile `quality_multiplier` (1.0 today; 0 if not evaluated) |
| debug.minClearanceMeters | float \| null | smallest height of the ray above terrain along the path (CLEAR >= 30, PARTIAL >= -150, else BLOCKED); null if not evaluated |
| debug.linkClass | `SHORT` (<20 km) \| `NORMAL` (<50) \| `STRONG_LOS` (<80) \| `EXTENDED_LOS` | label by 3-D distance |
| debug.rejectReason | `BEYOND_HORIZON` \| `BEYOND_MAX_RANGE` \| null | why the link was rejected before the quality model ran |

**The old fields `signalQuality`, `reason` and `distance` NO LONGER EXIST.** Use `rfQuality`, `state`, `debug.rejectReason`, `lineOfSight`, `disruptionFactor`, and `distanceMeters`/`distanceKm`. `SKILL_TRANSFERRED` also changed (`rfQuality` + `bandwidthFactor`, section 8).

### Model (deterministic, no randomness)

`rfQuality = clamp(distanceQuality * terrainFactor * attenuationFactor * disruptionFactor * platformFactor, 0, 1)`, rounded to 4 decimals in the engine.

- **Distance bands** (for the single 40 km-nominal profile every UAV uses; the engine scales the distance by `40 km / min(nominal of both ends)`, which is a no-op while all nodes share the profile): 0-20 km EXCELLENT (quality 1.0 -> 0.85), 20-40 GOOD (-> 0.65), 40-60 DEGRADED (-> 0.35), 60-80 MARGINAL (-> 0.10), **> 80 km normally disconnected**. 80-120 km is an "exceptional" tail (quality <= 0.10, only with CLEAR LOS and horizon >= 1.5x distance, bounded by the profile's extended range): never usable in practice.
- **Hard rejects** (`rfQuality` 0, `lineOfSight NOT_EVALUATED`): `BEYOND_MAX_RANGE` if distance > min(120 km, the profile's extended range = 100 km); else `BEYOND_HORIZON` if distance > `geometricHorizonMeters`. Raising altitude raises the horizon (`climb_for_los`).
- **Terrain LOS**: ray sampled every 5 km (max 64 samples) against the terrain. `CLEAR` factor 1.0, `PARTIAL` 0.55, `BLOCKED` 0.08. Simple quantized (500 m) LOS cache; exact for the quantized geometry.
- **Attenuation**: between half the horizon and the horizon, quality is scaled down to at most 0.5x (`attenuationFactor`).
- **Comm-degradation multiplier**: `disruptionFactor = prod over active zones of (1 - severity * min(1, 0.4 + coverage))`, `coverage` = fraction (of 16 samples) of the straight link inside the zone circle. A severity 0.9 zone crossing a whole link leaves 0.1x.
- **RF profile**: all UAVs use the GENERAL profile (nominal 40 km, extended 100 km, quality multiplier 1.0). `rf.py` still contains an `RFProfile` table (SCOUT/SENSOR/RELAY/...), but only GENERAL is used; a link would use the weaker end's values.
- `bandwidthFactor` is a monotone map of `rfQuality`: 0 below 0.10; 0.05 at 0.10, 0.35 at 0.35, 0.65 at 0.60, 0.90 at 0.80, 1.0 at 1.0; forced to 0 when not connected.

The committed replay contains `CLEAR` (most), `PARTIAL` (5 link-ticks, e.g. t=7110 s) and `disruptionFactor < 1` links; `BLOCKED` does not occur but the UI must handle it.

### Recommended visual mapping

| `state` | Line style | Opacity |
|---|---|---|
| EXCELLENT | solid, thick, bright green | from `rfQuality` |
| GOOD | solid, normal, green | from `rfQuality` |
| DEGRADED | solid, thinner, amber | from `rfQuality` |
| MARGINAL | weak: thin, red-orange | from `rfQuality` |
| DISCONNECTED | dashed, red, faint (debug / inspector only, optional) | 0.25 |
| pair not in `links[]` | **no edge** | n/a |

Opacity = `clamp(0.35 + 0.65 * rfQuality, 0.35, 1)` for connected links. Colour/dash from `state`, opacity from `rfQuality`, never from distance. Partition colouring: `uav.networkComponent`. Events: `NETWORK_PARTITIONED`, `NETWORK_RECONNECTED`.

### Node inspector (example, UAV-02 at t=1680 s)

Source: `uav.neighbors` + `links[]` filtered to the node.

```
UAV-02  alt 400 m  nominal range 40 km  comm: CONNECTED  component 0
Connected peers (3): UAV-03, UAV-04, UAV-05
Best link:  UAV-02~UAV-04  EXCELLENT  rfQuality 0.844  22.0 km  bandwidth 0.922
Worst link: UAV-02~UAV-05  DEGRADED   rfQuality 0.457  51.9 km  bandwidth 0.479
Not connected: UAV-01 (89.8 km, quality 0.051), UAV-06 (92.9 km, quality 0.029)
```

Best/worst = max/min `rfQuality` among links with `connected:true` for that node. If `neighbors` is empty show `ISOLATED`, the node's `altitudeMeters` (climbing) and the nearest disconnected link's `debug.rejectReason`.

### Link inspector (example, same frame)

```
UAV-02 <-> UAV-04            state EXCELLENT   connected
distance      22.01 km (horizontal 22.01 km; altitudes 400 m / 400 m)
rfQuality     0.844        bandwidth 92.2%
LOS           CLEAR (min clearance 472 m)
horizon       164.8 km     attenuation 1.00
disruption    1.00         platform 1.00   class NORMAL
```

Fields: `distanceKm`, `horizontalDistanceMeters`, `sourceAltitudeMeters`/`targetAltitudeMeters`, `rfQuality`, `bandwidthFactor`, `lineOfSight`, `debug.minClearanceMeters`, `geometricHorizonMeters`, `attenuationFactor`, `disruptionFactor`, `debug.platformFactor`, `debug.linkClass`.

### Debug explanation example ("why is this link weak/down?")

Built from fields only, first matching rule wins:

1. `debug.rejectReason == "BEYOND_MAX_RANGE"`: "UAV-01 to UAV-06 is 101.5 km apart (t=1230 s), beyond the maximum routine range."
2. `debug.rejectReason == "BEYOND_HORIZON"`: "Radio horizon is {geometricHorizonMeters/1000} km but the link is {distanceKm} km; climbing would extend it."
3. `lineOfSight` is `BLOCKED` or `PARTIAL`: "Terrain blocks the path (min clearance {debug.minClearanceMeters} m)." Real PARTIAL example: UAV-03~UAV-06 at t=7110 s, 80.5 km, `terrainFactor` 0.55, min clearance 7.2 m, rfQuality 0.
4. `disruptionFactor < 1`: "Communication-degradation zone reduces quality to {round(disruptionFactor*100)}%." Real example: UAV-02~UAV-03 at t=2610 s, 92.7 km, `disruptionFactor` 0.359, rfQuality 0.011, DISCONNECTED.
5. not connected: "Quality 0.104 is below the 0.15 threshold: 78.6 km is too far for this pair." (real: UAV-01~UAV-05 at t=300 s, CLEAR, `rejectReason` null, state DISCONNECTED.)
6. else "{debug.linkClass} link, {state}."

### Other communication-related UAV fields

`uav.neighbors`, `uav.communicationState`, `uav.networkComponent`, `uav.lastSync`, `uav.altitudeMeters`, `uav.commRadius`.

## 5. Disruptions: `frame.disruptions[]` (always 3 entries, scheduled per seed)

Fields: `id` (EVT-1..3), `type`, `active` (bool), `startTime` (s), `endTime` (s or null), `position {x,y}` (m; null for PLATFORM_FAILURE; moves per tick for zones), `radius` (m, 30-70 km), `velocity {x,y}` (m/s), `severity` 0..1, `nodeId` (target UAV for PLATFORM_FAILURE, else null).

| type | Effect | Status |
|---|---|---|
| COMMUNICATION_DEGRADATION | moving circle (severity 0.9); links crossing it get `disruptionFactor < 1` (section 4) | IMPLEMENTED |
| NAVIGATION_DEGRADATION | static circle (severity 0.6); UAV inside: sensor radius x (1 - 0.6 sev), speed x (1 - 0.5 sev), objective `STAY_OPERATIONAL`, sensorState `DEGRADED` | IMPLEMENTED |
| PLATFORM_FAILURE | one UAV (UAV-02..06) permanently fails at `startTime`; `active` is false immediately after (instant); event `UAV_FAILED` | IMPLEMENTED |
| POI_CHANGED | | NOT IMPLEMENTED |
| ROLE_CHANGED | roles are not implemented (all UAVs identical; not needed) | NOT IMPLEMENTED |

The list includes future disruptions (`startTime` in the future, `active:false`); do not announce them before the `DISRUPTION_STARTED`/`UAV_FAILED` event time. `active:false` with `endTime` in the past = ended. Events fire on the first tick at or after `startTime`/`endTime`. Seed 1002: EVT-2 NAV (centre ~177 km, 377 km; r 38 km) start 1300.13 (event 1320 s), end 7432.86 (event 7440 s); EVT-1 COMM (r 50 km, drifting; position at start ~206 km, 270 km) start 2603.23 (event 2610 s), end 6244.68 (event 6270 s); EVT-3 PLATFORM_FAILURE UAV-02 at 13417 s (after mission end, never fires).

## 6. Data sync (P2P)

Every tick, for every `connected:true` link, both ends exchange observations (last-writer-wins per observer+POI), searched cells, last-known peer positions/targets and skills. **Deterministic: no random packet loss. Stochastic loss is deliberately not implemented.** Data sync is not bandwidth-paced (only skill transfer is); partitions are the only reason data does not propagate. Counted in `stats.dataSyncs` (one per connected link per tick).

## 7. Skill lifecycle

One skill exists today: `adaptive_search_spacing` (`behaviorType: SEARCH_REGION_SELECTION`, id `adaptive_search_spacing_v1`, `spacing_m` 80000).

```
LOCAL (learned by a node)            -- learned after N redundant search selections (N = 10..24 per node)
  -> peer over a CONNECTED link without it/with lower (version, utility) accumulates transfer progress
     progress += link.bandwidthFactor * dt / skill_transfer_s   (skill_transfer_s = 60 s of FULL bandwidth)
     (resumable across ticks; copied when progress >= 1)
RECEIVED (tick of transfer)
  -> VALIDATING (next tick; 2 ticks)
  -> ADOPTED   if utilityScore >= 0.5 and confidence >= 0.5      (60 s after transfer)
  -> REJECTED  otherwise (id added to node's rejected set; never re-offered)   [no rejection occurs in seed 1002]
SKILL_USED event: first time a node uses an active skill (LOCAL or ADOPTED) to pick a search cell
```

**Transfer is paced by link quality**: a perfect link (bandwidthFactor 1.0) moves the skill in 2 ticks (60 s); a 0.35 link takes ~6 ticks (170 s); a 0.45 link ~5 ticks; a link below `connected` never finishes. Weak links visibly delay propagation. Show `bandwidthFactor` on the transfer animation.

Only LOCAL/ADOPTED skills are shared onward, so propagation is multi-hop. Transfers only happen over connected links, so partitions, distance and comm degradation delay or stop spread; that gap is what the `fleetKnowledgeCoverage` and success story depends on.

**Behavior it modifies** (search cell selection, `_pick_cell`): without the skill a UAV picks the nearest unsearched cell by local coverage only, and counts redundancy when re-searching a cell a peer covered. With the skill it (a) excludes cells peers have searched (`peer_cells`), (b) excludes cells peers claimed as target in the last 150 s, (c) adds a penalty for cells closer than `spacing_m` (80 km) to peers' last-known positions. The decision log marks this with `skillUsed` and `reason` "...peer coverage exclusion and 80000 m spacing". Observable effect: stats `redundancyRatio` falls (0.639 with skills vs 0.781 baseline for seed 1002) and UAVs spread out.

**Who created / who transferred**
- Created: `skill.sourceNodeId` + `skill.createdAt` (in `uav.skills[]`) and the `SKILL_LEARNED` event `nodeId`. Two nodes can independently learn the same id `..._v1` (seed 1002: UAV-02 at 1590 s and UAV-06 at 1620 s, the latter while partitioned); the node keeps the higher-utility copy.
- Transferred: `skill.receivedFrom` + `receivedAt` (per holder, null for the creator), and the `SKILL_TRANSFERRED` event (`sourceNodeId` -> `targetNodeId`, `rfQuality`, `bandwidthFactor`). `receivedFrom` is the immediate peer, not the creator: use it to draw the chain.
- Adopted: `skill.status` and the `SKILL_ADOPTED` event (`nodeId`, `fromNodeId`).

Skill fields (`Skill.to_dict`): `id`, `name`, `version`, `sourceNodeId`, `createdAt` (s), `receivedAt` (s|null), `receivedFrom` (id|null), `confidence` 0..1, `utilityScore` 0..1, `behaviorType`, `status` (`LOCAL|RECEIVED|VALIDATING|ADOPTED|REJECTED`), `metadata` (`spacing_m`, `excludes_peer_covered_cells`, `excludes_peer_claimed_cells`, `trigger` string). Frequency: occasional.

## 8. Skill events (in `events[]`)

| type | demo | Fields |
|---|---|---|
| SKILL_LEARNED | true | nodeId, skillId, version, utilityScore, reason |
| SKILL_TRANSFERRED | true | sourceNodeId, targetNodeId, skillId, version, **rfQuality, bandwidthFactor** (of the link at the completing tick) |
| SKILL_RECEIVED | **false** | nodeId, skillId, fromNodeId |
| SKILL_ADOPTED | true | nodeId, skillId, version, fromNodeId |
| SKILL_REJECTED | true | nodeId, skillId, reason (implemented, not triggered in seed 1002) |
| SKILL_USED | true | nodeId, skillId, version, behavior (`search_cell_selection`) |

No `SKILL_VALIDATING` event; read `uav.skills[].status` for that state.

## 9. Decision events: top-level `decisions[]`

Logged only when a node's (objective, action, target, skill) changes, not every tick (489 for seed 1002).

Fields: `timestamp` (s), `nodeId`, `state` (objective enum), `action`, `reason` (human sentence, display as-is), `metrics` (`neighbors`, `verifiedKnown`, `discoveredKnown`; optional `confidence`, `redundancyHits`, `isolatedTicks`, `cell`; for climb only `altitudeMeters`), `skillUsed` (skill id or null), `target` ([x, y] m or null). Use for the "why" panel; decisions with `skillUsed != null` (257 in seed 1002) are the skill-in-action moments. `action:"climb_for_los"` (state `MAINTAIN_CONNECTIVITY`, `target` null) is the "isolated, gaining altitude" moment; 23 occur in seed 1002 (first: UAV-06 at 1710 s, altitude 550 m; then UAV-01 2190 s, UAV-04/05/06 2370 s, UAV-02 2610 s, ...). `metrics.cell` = `cx*100 + cy` (search grid cell).

## 10. Event feed: top-level `events[]`

Common fields: `id` (`E-0001`), `type`, `timestamp` (s), `demo` (bool), plus type-specific fields. **Show only `demo:true` in the primary feed**; `demo:false` are internal (`SKILL_RECEIVED`, `NETWORK_TOPOLOGY_CHANGED`) and belong in a debug view only. Types: `MISSION_STARTED` (requiredPois, totalPois, timeLimit), `POI_DISCOVERED` (poiId, nodeId, confidence), `POI_VERIFIED` (poiId, nodeId, confidence, classification), `DISRUPTION_STARTED` (eventId, disruptionType, position, radius, severity), `DISRUPTION_ENDED` (eventId, disruptionType), `UAV_FAILED` (nodeId, eventId), `NETWORK_PARTITIONED` / `NETWORK_RECONNECTED` (components: id[][]; fired only on the transition connected -> partitioned and back), `NETWORK_TOPOLOGY_CHANGED` (componentCount; demo false), skill events (section 8), `MISSION_SUCCESS` / `MISSION_FAILED` (elapsedTime, verifiedPois, fleetKnowledgeCoverage). `eventCount`/`decisionCount` in each frame are the lengths so far (seed 1002 totals: 76 events, 489 decisions).

## 11. Data flow

```
MissionSim.step()  (every dt=30 s of sim time)
  disruptions -> per-UAV decide(+climb)+move+sense -> RF graph G(t) (rf.py: distance, horizon, terrain LOS, comm zones)
  -> P2P exchange over connected links (obs, cells, positions, bandwidth-paced skills)
  -> skill lifecycle -> frame()
        |
   frames[] + events[] + decisions[] + stats   (result())
        |
 CLI: python -m archipelago_mission --out seed-1002.json
        |
 apps/web: fetch replay JSON -> pick frame by playhead time
        -> HUD (mission/stats), map (uavs/pois/links/disruptions)
        -> feed = events/decisions with timestamp <= playhead time
```

## 12. Transport

Currently a **static replay JSON** produced by the CLI:

```
python -m archipelago_mission --seed 1002 --out apps/web/public/mission/seed-1002.json
```
(PYTHONPATH setup: PowerShell `$env:PYTHONPATH="packages/mission;packages/sim"`; Git Bash/Linux/macOS `PYTHONPATH="packages/mission:packages/sim"` (Windows Python under Git Bash needs `;`). Other flags: `--no-skills` baseline, `--compare` prints skills-on vs off stats to stdout.) The file for seed 1002 is already committed at that path (parse it as JSON; do not hand-edit); regenerate only if the engine changes.

Top-level keys: `meta` (seed, dt, skillsEnabled, world{width,height,tileMeters,tilesX,tilesY,units}, searchGrid{nx,ny}, uavSpec, rfModel, missionRules, config{...}; see section 20), `frames[]` (285 for seed 1002, index = tick, frame 0 = t 0, one per 30 s), `events[]`, `decisions[]`, `stats`. Each frame: `tick, time, mission, uavs, pois, links, disruptions, eventCount, decisionCount`. Feed for a frame = events and decisions with `timestamp <= frame.time` (or slice the first `eventCount` events / `decisionCount` decisions: equivalent and cheaper). `stats`: redundantCellMarks, uniqueCellMarks, skillsLearned, skillTransfers, skillAdoptions, skillRejections, partitions, dataSyncs, redundancyRatio, missionStatus, elapsedTime, firstSkillLearnedAt, finalSkillHolders.

**Live endpoint: NOT IMPLEMENTED.** No HTTP/WebSocket/SSE server exists in `packages/mission`. To step live in Python:
```python
from archipelago_mission.sim import MissionSim, MissionConfig
sim = MissionSim(MissionConfig(seed=1002))
while sim.status == "RUNNING":
    sim.step(); f = sim.frame()      # also appended to sim.frames
    # new events: sim.events[prev:], new decisions: sim.decisions[prev:]
run = sim.result()
```

## 13. Recommended layout

Main: map (terrain, tile grid, comm/nav zones as translucent circles, RF links styled by `state` with opacity from `rfQuality`, UAV markers with objective colour, skill glow and altitude badge, POIs as `?`/`!`/typed icon by `state`; scale to `meta.world`). Top HUD: status, clock vs `timeLimit`, verified N/required, coverage bar with `knowledgeThreshold` mark, nodes alive. Right: event feed (demo:true), decisions "why" panel for the selected UAV. Bottom: timeline scrubber with event markers; skill lineage (`createdAt`, `receivedFrom` chain, status per node). Selecting a UAV shows the node inspector, `skills`, `knownPois`, `lastSync`; selecting a link shows the link inspector.

## 14. Demo moments (seed 1002, times in sim seconds from the committed replay)

A. Search + first POI: `POI_DISCOVERED` POI-03 t=420 s, `POI_VERIFIED` POI-03 t=720 s (UAV-01). B. Navigation disruption and first skill: `DISRUPTION_STARTED` NAVIGATION_DEGRADATION **t=1320 s** (ends 7440 s); POI-02 discovered 1380 s / verified 1560 s; `SKILL_LEARNED` **UAV-02 t=1590 s** (11 redundant selections, utility 1.0), `SKILL_USED` 1620 s. C. Partition + independent learning: `NETWORK_PARTITIONED` **t=1620 s** (UAV-06 alone), `SKILL_LEARNED` **UAV-06 t=1620 s** (10 redundant selections), UAV-06 isolated and **climbs** (`climb_for_los` at 1710 s, 400 -> 550 m), `rejoin_peer` decision 1860 s, `NETWORK_RECONNECTED` t=1890 s. D. P2P propagation (bandwidth-paced): `SKILL_TRANSFERRED` UAV-02 -> UAV-03 and UAV-04 at **1680 s** (rfQuality 0.803 / 0.844, bandwidth 0.901 / 0.922), UAV-02 -> UAV-05 at **1710 s** (rfQuality 0.435, bandwidth 0.452); `SKILL_ADOPTED` UAV-03 and UAV-04 at 1740 s, UAV-05 at 1770 s; `SKILL_USED` 1770-1800 s; multi-hop `SKILL_TRANSFERRED` UAV-05 -> UAV-01 at **2010 s** over a weak link (rfQuality 0.314, bandwidth 0.307), `SKILL_ADOPTED` UAV-01 2070 s. Final skill holders 6 of 6 (UAV-02 and UAV-06 learned it themselves). E. Another partition at 2100 s (UAV-01 alone); POI-06 discovered 2280 s / verified 2520 s. F. Communication disruption: `DISRUPTION_STARTED` COMMUNICATION_DEGRADATION **t=2610 s**, `DISRUPTION_ENDED` **t=6270 s** (links through the zone get `disruptionFactor < 1`; some UAVs show `communicationState` DEGRADED); POI-01 2670 / 2940 s; POI-05 4320 / 4440 s; more partitions at 6300 / 6810 / 6960 s (reconnects 6270 / 6750 / 6900 / 7890 s); NAV zone ends 7440 s. 5 partitions in total (`stats.partitions` = 5). G. Outcome: POI-04 discovered 8460 s, verified 8520 s, `MISSION_SUCCESS` **t=8520 s** (6/6 verified, coverage 0.972 >= 0.8). Contrast: the `--no-skills` baseline for the same seed FAILS at 28800 s (5/6 verified, 5 of 6 UAVs operational, 0 skills). The `PLATFORM_FAILURE` (UAV-02, 13417 s) is scheduled but not reached in this replay.

## 15. Sample payloads (seed 1002, copied from the committed `apps/web/public/mission/seed-1002.json`)

MissionState (`frames[-1].mission`):
```json
{"seed":1002,"status":"SUCCESS","elapsedTime":8520.0,"timeLimit":28800.0,"totalPois":6,"requiredPois":6,"discoveredPois":6,"verifiedPois":6,"fleetKnowledgeCoverage":0.972,"knowledgeThreshold":0.8,"operationalNodes":6,"totalNodes":6}
```
UAV (`frames[-1]`, UAV-01: connected, adopted the skill from UAV-05 who got it from UAV-02):
```json
{"id":"UAV-01","status":"OPERATIONAL","position":{"x":72964.6,"y":470850.2},"heading":-2.41,"speed":140.0,"health":1.0,"sensorRadius":40000.0,"altitudeMeters":400.0,"commRadius":40000.0,"currentObjective":"VERIFY_POI","currentAction":"approach_poi","sensorState":"NOMINAL","communicationState":"CONNECTED","neighbors":["UAV-02","UAV-03","UAV-05","UAV-06"],"networkComponent":0,"activeSkill":"adaptive_search_spacing_v1","skills":[{"id":"adaptive_search_spacing_v1","name":"adaptive_search_spacing","version":1,"sourceNodeId":"UAV-02","createdAt":1590.0,"receivedAt":2010.0,"receivedFrom":"UAV-05","confidence":0.8,"utilityScore":1.0,"behaviorType":"SEARCH_REGION_SELECTION","status":"ADOPTED","metadata":{"spacing_m":80000.0,"excludes_peer_covered_cells":true,"excludes_peer_claimed_cells":true,"trigger":"11 redundant search selections"}}],"localKnowledgeCount":16,"knownPois":["POI-01","POI-02","POI-03","POI-04","POI-05","POI-06"],"verifiedPois":["POI-01","POI-02","POI-03","POI-04","POI-05","POI-06"],"searchedCells":178,"lastSync":{"UAV-02":8520.0,"UAV-03":8520.0,"UAV-04":5040.0,"UAV-05":8520.0,"UAV-06":8520.0}}
```
POI (`frames[-1].pois[0]`):
```json
{"id":"POI-01","position":{"x":258385.2,"y":274285.0},"trueType":"VEHICLE","state":"VERIFIED","discovered":true,"verified":true,"classification":"VEHICLE","confidence":1.0,"observationCount":27,"lastObserved":6060.0,"knownBy":["UAV-01","UAV-02","UAV-03","UAV-04","UAV-05","UAV-06"],"verifiedBy":["UAV-01","UAV-02","UAV-03","UAV-04","UAV-05","UAV-06"]}
```
RFLinks (full contract in section 4). Connected EXCELLENT link (UAV-02~UAV-04 at t=1680 s, section 4), a link degraded by the comm zone (t=2610 s), a PARTIAL-LOS link (t=7110 s) and a rejected link (t=1230 s):
```json
{"id":"UAV-02~UAV-03","sourceNodeId":"UAV-02","targetNodeId":"UAV-03","distanceMeters":92674.538,"horizontalDistanceMeters":92674.417,"distanceKm":92.675,"sourceAltitudeMeters":550.0,"targetAltitudeMeters":400.0,"geometricHorizonMeters":179022.565,"lineOfSight":"CLEAR","rfQuality":0.011,"bandwidthFactor":0.0,"state":"DISCONNECTED","connected":false,"attenuationFactor":0.998,"disruptionFactor":0.359,"lastUpdated":2610.0,"debug":{"distanceQuality":0.03,"terrainFactor":1.0,"platformFactor":1.0,"minClearanceMeters":495.616,"linkClass":"EXTENDED_LOS","rejectReason":null}}
{"id":"UAV-03~UAV-06","sourceNodeId":"UAV-03","targetNodeId":"UAV-06","distanceMeters":80529.816,"horizontalDistanceMeters":80529.816,"distanceKm":80.53,"sourceAltitudeMeters":400.0,"targetAltitudeMeters":400.0,"geometricHorizonMeters":164800.0,"lineOfSight":"PARTIAL","rfQuality":0.0,"bandwidthFactor":0.0,"state":"DISCONNECTED","connected":false,"attenuationFactor":1.0,"disruptionFactor":1.0,"lastUpdated":7110.0,"debug":{"distanceQuality":0.0,"terrainFactor":0.55,"platformFactor":1.0,"minClearanceMeters":7.222,"linkClass":"EXTENDED_LOS","rejectReason":null}}
{"id":"UAV-01~UAV-06","sourceNodeId":"UAV-01","targetNodeId":"UAV-06","distanceMeters":101534.118,"horizontalDistanceMeters":101534.118,"distanceKm":101.534,"sourceAltitudeMeters":400.0,"targetAltitudeMeters":400.0,"geometricHorizonMeters":164800.0,"lineOfSight":"NOT_EVALUATED","rfQuality":0.0,"bandwidthFactor":0.0,"state":"DISCONNECTED","connected":false,"attenuationFactor":1.0,"disruptionFactor":1.0,"lastUpdated":1230.0,"debug":{"distanceQuality":0.0,"terrainFactor":0.0,"platformFactor":0.0,"minClearanceMeters":null,"linkClass":"EXTENDED_LOS","rejectReason":"BEYOND_MAX_RANGE"}}
```
Disruptions (`frames[-1]`; floats trimmed):
```json
{"id":"EVT-1","type":"COMMUNICATION_DEGRADATION","active":false,"startTime":2603.23,"endTime":6244.68,"position":{"x":218280.1,"y":281378.9},"radius":50297.014,"velocity":{"x":3.311,"y":3.031},"severity":0.9,"nodeId":null}
{"id":"EVT-3","type":"PLATFORM_FAILURE","active":false,"startTime":13416.85,"endTime":null,"position":null,"radius":null,"velocity":null,"severity":1.0,"nodeId":"UAV-02"}
```
Events:
```json
{"id":"E-0004","type":"DISRUPTION_STARTED","timestamp":1320.0,"demo":true,"eventId":"EVT-2","disruptionType":"NAVIGATION_DEGRADATION","position":{"x":177094.865,"y":376660.874},"radius":38367.888,"severity":0.6}
{"id":"E-0007","type":"SKILL_LEARNED","timestamp":1590.0,"demo":true,"nodeId":"UAV-02","skillId":"adaptive_search_spacing_v1","version":1,"utilityScore":1.0,"reason":"Re-searched 11 cells already covered by peers; learned spacing/coordination strategy."}
{"id":"E-0009","type":"NETWORK_PARTITIONED","timestamp":1620.0,"demo":true,"components":[["UAV-01","UAV-02","UAV-03","UAV-04","UAV-05"],["UAV-06"]]}
{"id":"E-0012","type":"SKILL_TRANSFERRED","timestamp":1680.0,"demo":true,"sourceNodeId":"UAV-02","targetNodeId":"UAV-03","skillId":"adaptive_search_spacing_v1","version":1,"rfQuality":0.803,"bandwidthFactor":0.901}
{"id":"E-0018","type":"SKILL_ADOPTED","timestamp":1740.0,"demo":true,"nodeId":"UAV-03","skillId":"adaptive_search_spacing_v1","version":1,"fromNodeId":"UAV-02"}
{"id":"E-0025","type":"SKILL_TRANSFERRED","timestamp":2010.0,"demo":true,"sourceNodeId":"UAV-05","targetNodeId":"UAV-01","skillId":"adaptive_search_spacing_v1","version":1,"rfQuality":0.314,"bandwidthFactor":0.307}
{"id":"E-0054","type":"DISRUPTION_ENDED","timestamp":6270.0,"demo":true,"eventId":"EVT-1","disruptionType":"COMMUNICATION_DEGRADATION"}
{"id":"E-0076","type":"MISSION_SUCCESS","timestamp":8520.0,"demo":true,"elapsedTime":8520.0,"verifiedPois":6,"fleetKnowledgeCoverage":0.972}
```
Decisions (skill in use; climb; rejoin):
```json
{"timestamp":1620.0,"nodeId":"UAV-02","state":"DISCOVER_POI","action":"search_cell","reason":"Search cell (8, 6) chosen with peer coverage exclusion and 80000 m spacing.","metrics":{"neighbors":4,"verifiedKnown":2,"discoveredKnown":2,"cell":806},"skillUsed":"adaptive_search_spacing_v1","target":[212500,162500]}
{"timestamp":1710.0,"nodeId":"UAV-06","state":"MAINTAIN_CONNECTIVITY","action":"climb_for_los","reason":"No RF link for 3 ticks; gaining altitude to extend horizon and clear terrain.","metrics":{"altitudeMeters":550.0},"skillUsed":null,"target":null}
{"timestamp":1860.0,"nodeId":"UAV-06","state":"MAINTAIN_CONNECTIVITY","action":"rejoin_peer","reason":"No RF link for 8 ticks; heading to last-known position of UAV-03.","metrics":{"neighbors":0,"verifiedKnown":2,"discoveredKnown":2,"isolatedTicks":8},"skillUsed":null,"target":[114480,180286]}
```
Stats (`stats`): `{"redundantCellMarks":565,"uniqueCellMarks":319,"skillsLearned":2,"skillTransfers":4,"skillAdoptions":4,"skillRejections":0,"partitions":5,"dataSyncs":1520,"redundancyRatio":0.639,"missionStatus":"SUCCESS","elapsedTime":8520.0,"firstSkillLearnedAt":1590.0,"finalSkillHolders":6}`. Baseline `--no-skills`: `{"missionStatus":"FAILED","elapsedTime":28800.0,"skillsLearned":0,"partitions":4,"dataSyncs":6995,"redundancyRatio":0.781}`, mission 5/6 verified, 5 UAVs operational.

## 16. Mock / fallback

The committed replay file for seed 1002 is the mock and the fallback: `apps/web/public/mission/seed-1002.json` (committed, final; regenerate with the section 12 command only if the engine changes). **1002 is the recommended demo seed and the only committed replay.** Other seeds are untuned: in local scans most seeds (1000-1011, 1, 2, 3, 1002) succeed with skills, seeds 1006 and 7 fail even with skills. The `?seed=` URL param is a frontend concern: map seed -> `/mission/seed-<seed>.json`; any seed without a file shows an error panel with the regenerate command (or falls back to 1002). If the fetch fails, show an error panel, not synthetic data.

## 17. Source map

| Concern | Location |
|---|---|
| frame/result/events/decisions | `packages/mission/archipelago_mission/sim.py` (`frame`, `result`, `emit`, `decide_log`, `_fleet`, `_update_status`) |
| Skill schema and lifecycle | `sim.py` (`Skill`, `_exchange_and_links`, `_skill_lifecycle`, `_pick_cell`) |
| RF model and RFLink | `packages/mission/archipelago_mission/rf.py` (`RFEngine.compute_links`, `PROFILES`, `RFConfig`); called from `sim.py` `_compute_links` (terrain from packages/sim) |
| Altitude / climb | `sim.py` `_decide` (`ALT_MAX_M`, `CLIMB_M_PER_TICK`) |
| World / units | `sim.py` (`TILE_M`, `TILES_X/Y`, `W`, `H`, `tiles_to_m`, `m_to_tiles`) |
| Disruptions | `sim.py` `_build_events`, `_update_disruptions` |
| CLI (rounds floats to 3 dp) | `packages/mission/archipelago_mission/__main__.py` |
| Frontend | see section 19.h |

## 18. Implementation status

- [x] IMPLEMENTED: mission state, success/fail logic, knowledgeCoverage
- [x] IMPLEMENTED: UAV state (altitude; identical UAVs, no roles), POI state (UNKNOWN/DISCOVERED/VERIFIED)
- [x] IMPLEMENTED: RF engine (`rf.py`): distance bands, geometric horizon, terrain LOS, attenuation, comm-zone multiplier, RF profile, full RFLink contract with debug block
- [x] IMPLEMENTED: simple quantized LOS cache (500 m quantization); no spatial index needed at 6 UAVs
- [x] IMPLEMENTED: climb-for-LOS behaviour when isolated
- [x] IMPLEMENTED: COMMUNICATION_DEGRADATION, NAVIGATION_DEGRADATION, PLATFORM_FAILURE
- [x] IMPLEMENTED: skill learn / transfer (bandwidth-paced) / validate / adopt / reject / use; decisions log; event feed with demo flag
- [x] IMPLEMENTED: deterministic data sync over every connected link
- [x] IMPLEMENTED: CLI replay export, `--no-skills` baseline, `--compare`
- NOT IMPLEMENTED (by design): stochastic packet loss / random link failure
- PARTIAL: skills (a single skill type, `adaptive_search_spacing`; spacing fixed at 80 km); only seed 1002 is committed (others untuned)
- PARTIAL: frontend wiring (existing web files predate this schema; they must be updated to 400 x 500 km metres and the RFLink fields, section 19)
- MOCKED: the committed static replay file (seed 1002) is the only data source for the UI
- NOT IMPLEMENTED: live HTTP/WebSocket/SSE endpoint; POI_CHANGED disruption; ROLE_CHANGED disruption; multi-seed pre-generated files (only 1002); UAV roles (all UAVs identical); `SKILL_VALIDATING` event

## 19. Frontend implementation guide

Everything needed to build the core demo from the replay JSON alone. Sections 0-18 define semantics; this section is the build recipe.

### 19.a TypeScript interfaces (copy-paste; keys are the real JSON keys)

```ts
export type Id = string;                       // "UAV-01" | "POI-01" | "EVT-1" | "E-0001"
export interface XY { x: number; y: number }   // metres

export interface MissionReplay { meta: ReplayMeta; frames: Frame[]; events: MissionEvent[]; decisions: DecisionEvent[]; stats: Stats }

export interface ReplayMeta {
  seed: number; dt: number; skillsEnabled: boolean;               // dt = 30 (s)
  world: { width: number; height: number; tileMeters: number; tilesX: number; tilesY: number; units: "meters" };
  searchGrid: { nx: number; ny: number };                         // 16 x 20
  uavSpec: UavSpec; rfModel: RfModel; missionRules: MissionRules;   // static spec data, section 20
  config: { seed: number; dt: number; time_limit: number; n_uavs: number; n_pois: number; required_pois: number | null;
            knowledge_threshold: number; verify_conf: number; skill_transfer_s: number; skills_enabled: boolean;
            validation_ticks: number; min_adopt_utility: number; isolated_ticks_before_rendezvous: number; rendezvous_after: number };
}

export interface UavSpec {
  count: number; platformClass: string; cruiseSpeedMps: number; cruiseSpeedKmh: number;
  cruiseAltitudeAglMeters: number; maxAltitudeAglMeters: number; climbRateMetersPerTick: number; climbRateMps: number;
  nominalSpeedInNavDegradationFactor: number;
  sensor: { type: string; radiusMeters: number; radiusInNavDegradationFactor: number; detection: string; searchCellMeters: [number, number] };
  comms: { nominalRangeMeters: number; extendedRangeMeters: number; horizonAtCruiseMeters: number; horizonAtMaxAltitudeMeters: number };
  autonomy: string; learnedSkills: string[];
}
export interface RfModel {
  connectedThreshold: number; maxRoutineRangeMeters: number; reportRangeMeters: number;
  stateThresholds: { EXCELLENT: number; GOOD: number; DEGRADED: number; MARGINAL: number };
  horizonFormulaKm: string; updateIntervalSeconds: number;
}
export interface MissionRules {
  timeLimitSeconds: number; tickSeconds: number; totalPois: number; requiredPois: number; knowledgeThreshold: number;
  verifyConfidence: number; skillTransferSecondsAtFullBandwidth: number; skillValidationTicks: number; minAdoptUtility: number;
  poiTypes: PoiType[]; disruptionTypes: Disruption["type"][];
}

export interface Frame {
  tick: number; time: number;                                     // time = tick * 30 (s)
  mission: MissionState; uavs: UavState[]; pois: PoiState[]; links: RFLink[]; disruptions: Disruption[];
  eventCount: number; decisionCount: number;                      // events.slice(0, eventCount), decisions.slice(0, decisionCount)
}

export interface MissionState {
  seed: number; status: "RUNNING" | "SUCCESS" | "FAILED"; elapsedTime: number; timeLimit: number;
  totalPois: number; requiredPois: number; discoveredPois: number; verifiedPois: number;
  fleetKnowledgeCoverage: number; knowledgeThreshold: number; operationalNodes: number; totalNodes: number;
}

export type Objective = "DISCOVER_POI" | "VERIFY_POI" | "STAY_OPERATIONAL" | "MAINTAIN_CONNECTIVITY" | "SHARE_INFORMATION" | "NONE";
export type UavAction = "search_cell" | "approach_poi" | "leave_degradation_zone" | "rejoin_peer" | "move_toward_peer" | "hold_position" | "failed";
export interface UavState {
  id: Id; status: "OPERATIONAL" | "FAILED"; position: XY; heading: number; speed: number; health: number;
  sensorRadius: number; altitudeMeters: number; commRadius: number;
  currentObjective: Objective; currentAction: UavAction; sensorState: "NOMINAL" | "DEGRADED" | "OFFLINE";
  communicationState: "CONNECTED" | "DEGRADED" | "ISOLATED" | "OFFLINE"; neighbors: Id[]; networkComponent: number;
  activeSkill: string | null; skills: Skill[]; localKnowledgeCount: number; knownPois: Id[]; verifiedPois: Id[];
  searchedCells: number; lastSync: Record<Id, number>;
}

export interface Skill {
  id: string; name: string; version: number; sourceNodeId: Id; createdAt: number; receivedAt: number | null; receivedFrom: Id | null;
  confidence: number; utilityScore: number; behaviorType: "SEARCH_REGION_SELECTION";
  status: "LOCAL" | "RECEIVED" | "VALIDATING" | "ADOPTED" | "REJECTED";
  metadata: { spacing_m: number; excludes_peer_covered_cells: boolean; excludes_peer_claimed_cells: boolean; trigger: string };
}

export type PoiType = "INFRASTRUCTURE" | "VEHICLE" | "SIGNAL";
export interface PoiState {
  id: Id; position: XY; trueType: PoiType;                        // trueType: show ONLY when state === "VERIFIED"
  state: "UNKNOWN" | "DISCOVERED" | "VERIFIED"; discovered: boolean; verified: boolean;
  classification: PoiType | "UNKNOWN"; confidence: number; observationCount: number; lastObserved: number | null;
  knownBy: Id[]; verifiedBy: Id[];
}

export type RFState = "EXCELLENT" | "GOOD" | "DEGRADED" | "MARGINAL" | "DISCONNECTED";
export interface RFLink {
  id: string; sourceNodeId: Id; targetNodeId: Id;
  distanceMeters: number; horizontalDistanceMeters: number; distanceKm: number;
  sourceAltitudeMeters: number; targetAltitudeMeters: number; geometricHorizonMeters: number;
  lineOfSight: "CLEAR" | "PARTIAL" | "BLOCKED" | "NOT_EVALUATED";
  rfQuality: number; bandwidthFactor: number; state: RFState; connected: boolean;
  attenuationFactor: number; disruptionFactor: number; lastUpdated: number;
  debug: { distanceQuality: number; terrainFactor: number; platformFactor: number; minClearanceMeters: number | null;
           linkClass: "SHORT" | "NORMAL" | "STRONG_LOS" | "EXTENDED_LOS"; rejectReason: "BEYOND_HORIZON" | "BEYOND_MAX_RANGE" | null };
}

export interface Disruption {
  id: Id; type: "COMMUNICATION_DEGRADATION" | "NAVIGATION_DEGRADATION" | "PLATFORM_FAILURE"; active: boolean;
  startTime: number; endTime: number | null; position: XY | null; radius: number | null; velocity: XY | null;
  severity: number; nodeId: Id | null;
}

interface EventBase { id: string; timestamp: number; demo: boolean }
export type MissionEvent = EventBase & (
  | { type: "MISSION_STARTED"; requiredPois: number; totalPois: number; timeLimit: number }
  | { type: "POI_DISCOVERED"; poiId: Id; nodeId: Id; confidence: number }
  | { type: "POI_VERIFIED"; poiId: Id; nodeId: Id; confidence: number; classification: PoiType }
  | { type: "DISRUPTION_STARTED"; eventId: Id; disruptionType: Disruption["type"]; position: XY; radius: number; severity: number }
  | { type: "DISRUPTION_ENDED"; eventId: Id; disruptionType: Disruption["type"] }
  | { type: "UAV_FAILED"; nodeId: Id; eventId: Id }
  | { type: "NETWORK_PARTITIONED"; components: Id[][] }
  | { type: "NETWORK_RECONNECTED"; components: Id[][] }
  | { type: "NETWORK_TOPOLOGY_CHANGED"; componentCount: number }          // demo:false
  | { type: "SKILL_LEARNED"; nodeId: Id; skillId: string; version: number; utilityScore: number; reason: string }
  | { type: "SKILL_TRANSFERRED"; sourceNodeId: Id; targetNodeId: Id; skillId: string; version: number; rfQuality: number; bandwidthFactor: number }
  | { type: "SKILL_RECEIVED"; nodeId: Id; skillId: string; fromNodeId: Id }  // demo:false
  | { type: "SKILL_ADOPTED"; nodeId: Id; skillId: string; version: number; fromNodeId: Id | null }
  | { type: "SKILL_REJECTED"; nodeId: Id; skillId: string; reason: string }
  | { type: "SKILL_USED"; nodeId: Id; skillId: string; version: number; behavior: "search_cell_selection" }
  | { type: "MISSION_SUCCESS" | "MISSION_FAILED"; elapsedTime: number; verifiedPois: number; fleetKnowledgeCoverage: number }
);

export interface DecisionEvent {
  timestamp: number; nodeId: Id; state: Objective;
  action: UavAction | "climb_for_los"; reason: string;
  metrics: { neighbors?: number; verifiedKnown?: number; discoveredKnown?: number; confidence?: number; redundancyHits?: number;
             isolatedTicks?: number; cell?: number; altitudeMeters?: number };
  skillUsed: string | null; target: [number, number] | null;       // metres
}

export interface Stats {
  redundantCellMarks: number; uniqueCellMarks: number; skillsLearned: number; skillTransfers: number; skillAdoptions: number;
  skillRejections: number; partitions: number; dataSyncs: number; redundancyRatio: number;
  missionStatus: "RUNNING" | "SUCCESS" | "FAILED"; elapsedTime: number; firstSkillLearnedAt: number | null; finalSkillHolders: number;
}
```

### 19.b Loading

```ts
const seed = Number(new URLSearchParams(location.search).get("seed") ?? 1002);
const res = await fetch(`/mission/seed-${seed}.json`);
if (!res.ok) throw new Error(`No replay for seed ${seed} (HTTP ${res.status})`);
const replay = (await res.json()) as MissionReplay;
```
- Missing file or non-OK (note: a dev server may return 200 with `index.html` for a missing file, so also catch the JSON parse error): show an error panel ("No replay for seed N. Generate it: ..." with the command below) and a link to `?seed=1002`. Never show synthetic data. Validate `replay.frames.length > 0` and `meta.world.units === "meters"`.
- Regenerate from the repo root. PowerShell: `$env:PYTHONPATH="packages/mission;packages/sim"; python -m archipelago_mission --seed N --out apps/web/public/mission/seed-N.json`. Bash (Linux/macOS): `PYTHONPATH="packages/mission:packages/sim" python -m archipelago_mission --seed N --out apps/web/public/mission/seed-N.json` (Git Bash with Windows Python: use `;` as the separator). The file is a few MB; one `fetch` + `JSON.parse` is fine.

### 19.c Playback clock

- State: `t` (sim seconds, 0..`frames[last].time`), `playing`, `rate` (sim-seconds per real second; offer 15, 60, 120, 300; **default 60**). The mission is 8520 sim-seconds, so reuse the app's playback speed-up control; the backend does not accelerate UAVs. Advance `t += rate * realDeltaSeconds` per animation frame; clamp at the last frame time and stop. Pause, play, seek (scrubber sets `t`) and restart are just setting `t`/`playing`. No `Math.random`, no wall-clock in rendered values: the same `t` always renders identically.
- `i = Math.min(frames.length - 1, Math.floor(t / meta.dt))`; `A = frames[i]`, `B = frames[Math.min(i + 1, last)]`, `a = (t - A.time) / meta.dt` (0 at the last frame).
- **Interpolate only continuous motion** between A and B (match UAVs by id; skip if either is `FAILED`): `position.x/y` and `altitudeMeters` linearly; `heading` along the shortest arc (`d = ((hB - hA + 3*PI) % (2*PI)) - PI; h = hA + a*d`). Everything else is stepped from the **floor frame A**: `links`, `pois`, `skills`, `neighbors`, `communicationState`, `mission`; `disruptions` are stepped except zone `position`, which may be lerped. This keeps edges appearing/disappearing exactly at tick boundaries (the RF graph is a 30 s snapshot).
- Feed at time `t`: `events.filter(e => e.timestamp <= t)` (or `events.slice(0, A.eventCount)`) with `demo:true`; decisions likewise. For the selected UAV's "why" panel use the last decision with `nodeId === id && timestamp <= t`.

### 19.d World to screen

- Read `W = meta.world.width`, `H = meta.world.height` (400,000 x 500,000 m), `T = meta.world.tileMeters`. Never hardcode.
- `scale = min(viewW / W, viewH / H)` (px per metre); `sx = offX + x * scale`, `sy = offY + y * scale`. **y grows downward** in the data and on screen (no flip). Centre with `offX = (viewW - W*scale)/2`, `offY = (viewH - H*scale)/2`. The map is portrait (4 x 5 tiles).
- Tile grid: vertical lines at `x = k*T` for k in 0..tilesX, horizontal at `y = k*T` for k in 0..tilesY (faint); optional tile labels. Optional faint 25 km search grid (`W/nx`, `H/ny`).
- Scale bar: choose a round length (50 or 100 km); width px = `km * 1000 * scale`; label "100 km". Label distances in km (`m / 1000`).
- Zones: circle centred at `position`, radius `radius * scale` px. Comm zone (translucent amber/red), nav zone (translucent blue/violet), drawn only while `active`. Optional range rings: `sensorRadius * scale` (solid) and `commRadius * scale` (nominal comm, dashed).
- UAV markers are fixed pixel size (not metres); at this scale 1 km is ~1-2 px, so physical sizes are not drawable.
- The existing viewport code (`camera.ts`) works in its own units; for the mission map prefer a separate SVG/canvas layer driven by the transform above.

### 19.e Derivation rules

HUD (from the floor-frame `A.mission`; do not interpolate):
- Clock `elapsedTime` as `H:MM:SS`; remaining = `timeLimit - elapsedTime` (same format); time progress = `elapsedTime / timeLimit`.
- Verified `"{verifiedPois} / {requiredPois} verified"`; discovered `"{discoveredPois} / {totalPois} discovered"`.
- Coverage `Math.round(fleetKnowledgeCoverage * 100) + "%"` with a bar and a threshold tick at `knowledgeThreshold * 100` % (80%); green once coverage >= threshold.
- Nodes `"{operationalNodes} / {totalNodes} UAVs"`; status banner from `status` (RUNNING / SUCCESS green / FAILED red).
- The run ends early on SUCCESS (8520 of 28800 s): hold the final state after the last frame; never extrapolate.

POI markers (`pois[]`):
- `UNKNOWN`: draw nothing (or a tiny faint dot behind a debug toggle). Positions of undiscovered POIs are ground truth and must not be revealed by default.
- `DISCOVERED`: amber `?` marker, label `classification` (can be wrong) with confidence percent.
- `VERIFIED`: solid icon by `trueType` (equals classification), green check, label type. **Never read `trueType` while state is not VERIFIED**, including tooltips and debug text.
- Hover: `knownBy`/`verifiedBy` counts.

UAV markers (`uavs[]`):
- Position from the interpolated frame, rotation `heading` (rad, 0 = +x, clockwise on screen since y is down), colour by `currentObjective` (DISCOVER blue, VERIFY amber, STAY_OPERATIONAL orange, MAINTAIN_CONNECTIVITY purple, SHARE_INFORMATION green); one glyph for all UAVs (no roles); label with `id`.
- `status === "FAILED"`: grey, no rings, strike-through label, no links (it has none).
- Active skill: glow/badge when `activeSkill != null`; pulsing chip for `RECEIVED`/`VALIDATING` read from `skills[]`.
- Altitude: badge `"{Math.round(altitudeMeters)} m"`; an up arrow "climbing" when altitude at B > altitude at A (or the last `climb_for_los` decision for the node is within 3 ticks); down arrow when decreasing. Cruise altitude 400 m; cap 2000 m.
- `communicationState` badge (CONNECTED green, DEGRADED amber, ISOLATED red, OFFLINE grey); partition ring colour by `networkComponent` (palette index; skip -1).
- `sensorState === "DEGRADED"` shows a warning badge.

Links (`A.links`), per section 4:
- Draw `connected:true` links as solid lines styled by `state` (EXCELLENT thick bright green, GOOD green, DEGRADED amber, MARGINAL thin red-orange), `opacity = clamp(0.35 + 0.65 * rfQuality, 0.35, 1)`, width `1 + 3 * bandwidthFactor` px.
- `connected:false` pairs: draw nothing by default; an optional "show weak near pairs" toggle draws only those with `debug.rejectReason === null` as faint dashed red (opacity 0.25). Pairs with a `rejectReason` and pairs absent from `links` are never drawn.
- Partition = edges disappear (no solid edge between components). Lines connect marker centres (interpolated positions), styling comes from the floor-frame link.
- Never compute distance/quality client-side.

Disruptions: draw a circle only when `active:true`; fade out after `DISRUPTION_ENDED`. `PLATFORM_FAILURE` has no geometry (use `UAV_FAILED` to flash the UAV). Do not announce disruptions whose `startTime > t`.

### 19.f Event feed templates (`demo:true` only)

| type | Text | Emphasis |
|---|---|---|
| MISSION_STARTED | "Mission started: {requiredPois}/{totalPois} POIs required, limit {timeLimit/3600} h" | none |
| POI_DISCOVERED | "{nodeId} discovered {poiId} (confidence {pct(confidence)})" | pulse the POI `?` |
| POI_VERIFIED | "{nodeId} verified {poiId} as {classification} ({pct(confidence)})" | flip to icon, green flash (E-G) |
| DISRUPTION_STARTED | "{label(disruptionType)} started (radius {round(radius/1000)} km, severity {pct(severity)})" | zone fade-in, camera hint (E, F) |
| DISRUPTION_ENDED | "{label(disruptionType)} ended" | zone fade-out |
| UAV_FAILED | "{nodeId} failed" | red flash, grey (not in 1002) |
| NETWORK_PARTITIONED | "Network partitioned into {components.length} groups: {components.map(c => c.join(', ')).join(' | ')}" | flash vanishing edges, colour components (A, D, E) |
| NETWORK_RECONNECTED | "Network reconnected" | edges restored |
| SKILL_LEARNED | "{nodeId} learned skill {skillId}: {reason}" | badge on UAV, ring pulse (B, D) |
| SKILL_TRANSFERRED | "{sourceNodeId} sent {skillId} to {targetNodeId} (RF {pct(rfQuality)}, bandwidth {pct(bandwidthFactor)})" | animated arrow along link `source~target` (C, D) |
| SKILL_ADOPTED | "{nodeId} adopted {skillId} from {fromNodeId}" | badge turns solid |
| SKILL_REJECTED | "{nodeId} rejected {skillId}: {reason}" | grey badge |
| SKILL_USED | "{nodeId} is using {skillId} to choose search cells" | glow |
| MISSION_SUCCESS | "Mission succeeded at {fmt(elapsedTime)}: {verifiedPois} POIs verified, coverage {pct(fleetKnowledgeCoverage)}" | banner (G) |
| MISSION_FAILED | "Mission failed at {fmt(elapsedTime)}: {verifiedPois} POIs verified, coverage {pct(fleetKnowledgeCoverage)}" | banner |

`label`: COMMUNICATION_DEGRADATION -> "Communication degradation", NAVIGATION_DEGRADATION -> "Navigation degradation". `pct(x) = Math.round(x*100) + "%"`.

Decision template ("why" panel; shown for decisions with `skillUsed != null` or `action` in `climb_for_los`, `rejoin_peer`, `move_toward_peer`, `leave_degradation_zone`; all decisions appear in the selected-UAV list):
```
{nodeId} changed route                       t={fmt(timestamp)}
Reason: {reason}
Action: {action}{target ? " -> (" + (target[0]/1000).toFixed(0) + ", " + (target[1]/1000).toFixed(0) + ") km" : ""}
Skill: {skillUsed ?? "none"}
```
(`climb_for_los` headline: "{nodeId} is climbing to {metrics.altitudeMeters} m to regain line of sight".) A feed entry arriving in the last ~2 real seconds is highlighted; Moments A-G (section 14) get a timeline marker, and the skill chain (UAV-02 -> UAV-03/04/05, UAV-05 -> UAV-01 in 1002) is drawn as arrows.

### 19.g Inspector mappings

Node inspector (selected UAV `u`, floor frame A):
- `peers = u.neighbors`; `myLinks = A.links.filter(l => l.sourceNodeId === u.id || l.targetNodeId === u.id)`; `conn = myLinks.filter(l => l.connected)`; best = `conn` max by `rfQuality`; worst = `conn` min by `rfQuality`; other end = `l.sourceNodeId === u.id ? l.targetNodeId : l.sourceNodeId`.
- Show: id, nominal range `commRadius/1000` km, `altitudeMeters`, `communicationState`, `networkComponent`, connected peers count and ids, best/worst link (peer, `state`, `rfQuality`, `distanceKm`, `bandwidthFactor`), skills (status, source, `receivedFrom`), `knownPois`/`verifiedPois`, sync ages `t - lastSync[peer]`, objective/action plus the last decision reason. If `conn` is empty: "Isolated" plus the nearest disconnected link's `debug.rejectReason` or "weak signal".
- Average RF = `mean(conn.map(l => l.rfQuality))`; fleet edge count = `A.links.filter(l => l.connected).length`.

Link inspector (selected `l`): table from section 4 (distance km, altitudes, rfQuality percent, bandwidth percent, state, LOS + `debug.minClearanceMeters`, horizon km = `geometricHorizonMeters/1000`, attenuation, disruption percent = `disruptionFactor*100`, `debug.linkClass`, `lastUpdated`) plus the debug-explanation rules of section 4. Estimated skill transfer time = `config.skill_transfer_s / bandwidthFactor` s (only if `connected`; e.g. 60 / 0.452 = 133 s for UAV-02~UAV-05 at 1710 s). Clicking an edge or a `SKILL_TRANSFERRED` row opens this inspector for `sourceNodeId~targetNodeId`.

### 19.h Files to touch and constraints

- The existing app has a snapshot/live pipeline (`apps/web/src/App.tsx` with `?run=`, `?replay`, `?demo`; `live.ts`, `replay.ts`, `client.ts`, `Panels`/`WorldSnapshot`); `MissionHUD.tsx` today takes `Panels` from that pipeline. **The mission replay is a separate, new data source** with a different schema; do not feed it through `WorldSnapshot`.
- Add a mode: `?mission=1` (optional `&seed=N`, default 1002) or treat bare `?seed=` as mission mode (the existing pipeline does not read `seed` from the URL). In `App.tsx` branch early: `if (params.has("mission") || params.has("seed")) return <MissionApp />`.
- New files: `apps/web/src/missionReplay.ts` (types from 19.a, `loadMissionReplay(seed)`, `frameAt(replay, t)` returning interpolated UAVs + floor-frame state, `feedAt(replay, t)`), `apps/web/src/MissionApp.tsx` (clock, scrubber, layout), optionally `apps/web/src/MissionMap.tsx`. Touch: `FlightMap.tsx` (add or branch to the mission layer: tile grid, zones, links, UAVs, POIs with the 19.d transform), `MissionHUD.tsx` (add a variant consuming `MissionState` + `Stats`), `App.tsx` (mode switch only). Leave `replay.ts` (run-record replay) unchanged.
- Constraints: no RF recomputation (render link fields only); no `Math.random`, `Date.now()` or non-deterministic ordering in rendered values (iterate `uavs`/`links` in array order); read world size from `meta.world`; never show `trueType` before VERIFIED; do not edit backend files or the replay JSON.
- Tests (match `mission.test.tsx` / `fixture.test.ts` style): `frameAt` interpolation and floor-stepping, heading shortest arc, feed filtering, `trueType` hiding, world transform at the corners, link styling by state.

### 19.i Acceptance checklist

- [ ] `/?seed=1002` loads `/mission/seed-1002.json`; a missing seed shows an error panel with the regenerate command; no synthetic fallback.
- [ ] Map is 400 x 500 km (4 x 5 tiles) taken from `meta.world`, tile grid every 100 km, km scale bar, y down; zone circles scale with radius in metres.
- [ ] Play / pause / seek / rate work (default 60x); UAVs move smoothly between 30 s frames; links/POIs/skills change only at frame boundaries; the same `t` renders the same picture.
- [ ] HUD shows clock and remaining time, verified N/6, coverage % with 80% tick, nodes 6/6, status banner; final state SUCCESS at 8520 s.
- [ ] Moment A: POI-03 `?` at 420 s becomes a verified icon at 720 s (`trueType` hidden before then).
- [ ] Moment B: nav zone appears at 1320 s (clears 7440 s); `SKILL_LEARNED` UAV-02 at 1590 s with badge and feed entry.
- [ ] Moment C: at 1620 s UAV-06 is cut off (edges disappear, component colouring) and learns the skill independently; it climbs from 1710 s (altitude badge 400 -> 550 m, `climb_for_los` in the why panel); reconnect at 1890 s.
- [ ] Moment D: transfer arrows on the actual RF links UAV-02 -> UAV-03 / UAV-04 at 1680 s (bandwidth 0.901 / 0.922) and UAV-02 -> UAV-05 at 1710 s (rfQuality 0.435, bandwidth 0.452); adoptions at 1740 / 1740 / 1770 s; UAV-05 -> UAV-01 at 2010 s over a weak link (bandwidth 0.307), adopted 2070 s.
- [ ] Moment E: comm zone from 2610 s to 6270 s drawn; links through it dim (`disruptionFactor`), `communicationState` DEGRADED badges at 2610 s; the link inspector explains the cause.
- [ ] Moment F: further partitions/reconnects (2100, 6270/6300, 6750/6810, 6900/6960, 7890 s) visible as edges disappearing and returning.
- [ ] Moment G: remaining POIs verify (720, 1560, 2520, 2940, 4440, 8520 s); success banner at 8520 s.
- [ ] Link styling follows `state` and `rfQuality` opacity; only connected links solid; pairs absent from `links[]` never drawn.
- [ ] Node inspector shows connected peers count and best/worst link; link inspector shows all fields and a debug explanation.
- [ ] Event feed shows only `demo:true` events with the templates above; `demo:false` only in debug.
- [ ] Failed-UAV rendering exists (grey) even though 1002 never reaches `UAV_FAILED`.
- [ ] No backend RF logic or `Math.random` in the frontend; `apps/web` tests, lint and typecheck pass.

### 19.j Known gaps and limitations

- No live stream (static replay only); there is no HTTP/WebSocket/SSE endpoint.
- Only seed 1002 has a committed replay. In local scans most seeds (1000-1011, 1, 2, 3, 1002) succeed with skills; seeds 1006 and 7 fail even with skills; the skills-off baseline for 1002 fails (use `--compare` for the contrast numbers).
- `POI_CHANGED` and `ROLE_CHANGED` disruptions are not implemented (UAV roles do not exist: all UAVs are identical); there is one skill type; no stochastic packet loss; no `SKILL_VALIDATING` event.
- `UAV_FAILED` does not occur in the 1002 replay (failure scheduled for UAV-02 at 13417 s, mission ends at 8520 s); `BLOCKED` LOS never appears in it. Implement these paths anyway.
- Frames carry a 30 s snapshot; edges can only change at tick boundaries. Interpolated positions between ticks may briefly show a drawn link longer than its nominal range; that is expected.

## 20. UAV specification panel

The replay carries the platform, RF and rule constants in `meta.uavSpec`, `meta.rfModel` and `meta.missionRules` (static; identical every frame). **The frontend renders a fleet/platform spec card from these objects and must never hardcode any of these numbers.** The same card opens from the node inspector (button "Platform spec" next to the selected UAV) and from a fleet header ("6 identical UAVs"). TS types: `UavSpec`, `RfModel`, `MissionRules` in 19.a.

### 20.a Real `meta` data (seed 1002)

```json
"uavSpec":{"count":6,"platformClass":"Abstract fixed-wing recon UAV (all units identical)","cruiseSpeedMps":140.0,"cruiseSpeedKmh":504.0,"cruiseAltitudeAglMeters":400.0,"maxAltitudeAglMeters":2000.0,"climbRateMetersPerTick":150.0,"climbRateMps":5.0,"nominalSpeedInNavDegradationFactor":0.7,"sensor":{"type":"Wide-area EO/IR (abstract)","radiusMeters":40000.0,"radiusInNavDegradationFactor":0.64,"detection":"Per-tick detection probability from terrain line-of-sight and vegetation concealment; confidence 0.4-0.98 rises as range closes.","searchCellMeters":[25000.0,25000.0]},"comms":{"nominalRangeMeters":40000.0,"extendedRangeMeters":100000.0,"horizonAtCruiseMeters":164800.0,"horizonAtMaxAltitudeMeters":368504.003},"autonomy":"Local decisions only: objective priority STAY_OPERATIONAL > VERIFY_POI > SHARE_INFORMATION > MAINTAIN_CONNECTIVITY > DISCOVER_POI","learnedSkills":["adaptive_search_spacing"]}
"rfModel":{"connectedThreshold":0.15,"maxRoutineRangeMeters":120000.0,"reportRangeMeters":150000.0,"stateThresholds":{"EXCELLENT":0.8,"GOOD":0.6,"DEGRADED":0.35,"MARGINAL":0.1},"horizonFormulaKm":"4.12 * (sqrt(h1_m) + sqrt(h2_m))","updateIntervalSeconds":30.0}
"missionRules":{"timeLimitSeconds":28800.0,"tickSeconds":30.0,"totalPois":6,"requiredPois":6,"knowledgeThreshold":0.8,"verifyConfidence":0.9,"skillTransferSecondsAtFullBandwidth":60.0,"skillValidationTicks":2,"minAdoptUtility":0.5,"poiTypes":["INFRASTRUCTURE","VEHICLE","SIGNAL"],"disruptionTypes":["COMMUNICATION_DEGRADATION","NAVIGATION_DEGRADATION","PLATFORM_FAILURE"]}
```

### 20.b Spec card: field to display mapping (all from `meta`)

| Card row | Source | Display (seed 1002) |
|---|---|---|
| Platform | `uavSpec.platformClass`, `uavSpec.count` | "6 x Abstract fixed-wing recon UAV (all units identical)" |
| Cruise speed | `cruiseSpeedMps`, `cruiseSpeedKmh` | "140 m/s (504 km/h)" |
| Speed in nav-degradation zone | `cruiseSpeedMps * nominalSpeedInNavDegradationFactor` | "98 m/s (x0.7)" |
| Altitude | `cruiseAltitudeAglMeters`, `maxAltitudeAglMeters` | "cruise 400 m AGL, max 2000 m AGL" |
| Climb rate | `climbRateMps`, `climbRateMetersPerTick` | "5 m/s (150 m per 30 s tick)" |
| Sensor | `sensor.type`, `sensor.radiusMeters/1000` | "Wide-area EO/IR (abstract), radius 40 km" |
| Degraded sensor | `sensor.radiusMeters * sensor.radiusInNavDegradationFactor / 1000` | "25.6 km inside a navigation-degradation zone (x0.64)" |
| Detection model | `sensor.detection` (show text as is) | text |
| Search cell | `sensor.searchCellMeters` (km) | "25 x 25 km cells (`meta.searchGrid` 16 x 20)" |
| Comm range | `comms.nominalRangeMeters`, `extendedRangeMeters` (km) | "nominal 40 km, extended 100 km" |
| RF horizon | `comms.horizonAtCruiseMeters`, `horizonAtMaxAltitudeMeters` (km) | "165 km at cruise, 369 km at 2000 m" (pair horizon, both ends at that altitude) |
| RF link states | `rfModel.stateThresholds`, `connectedThreshold` | "EXCELLENT >= 0.80, GOOD >= 0.60, DEGRADED >= 0.35, MARGINAL >= 0.10; connected at rfQuality >= 0.15" |
| RF update | `rfModel.updateIntervalSeconds`, `reportRangeMeters`, `maxRoutineRangeMeters`, `horizonFormulaKm` | "graph recomputed every 30 s; links listed up to 150 km; routine max 120 km; horizon = 4.12 (sqrt h1 + sqrt h2) km" |
| Autonomy | `autonomy` | text, plus the priority list split on " > " and numbered 1..5 (STAY_OPERATIONAL first) |
| Learned skills | `learnedSkills` | chip per skill name |
| Mission rules | `missionRules` | "time limit 8 h (28800 s); 6 POIs, 6 required; verification confidence 90%; fleet knowledge threshold 80%; skill transfer 60 s at full bandwidth; validation 2 ticks; adopt if utility >= 0.5; tick 30 s" |
| POI types | `missionRules.poiTypes` | chips |
| Disruption types | `missionRules.disruptionTypes` | chips with labels from 19.f |

Unit helpers: km = m / 1000, one decimal if < 100 else integer; `hms(s)` for durations; `pct(x)`.

### 20.c Per-UAV live panel (selected UAV, floor frame A; altitude/speed may use the interpolated value)

| Row | Field | Formula / display |
|---|---|---|
| Status / health | `status`, `health` | "OPERATIONAL" / "FAILED", health percent |
| Altitude | `altitudeMeters` | "{round} m AGL" with "climbing" / "descending" arrow vs cruise (`uavSpec.cruiseAltitudeAglMeters`) |
| Speed | `speed` | "{round(speed)} m/s ({round(speed*3.6)} km/h)" |
| Sensor | `sensorState` | NOMINAL: `uavSpec.sensor.radiusMeters`; DEGRADED: `radiusMeters * radiusInNavDegradationFactor` (effective radius, km); OFFLINE: "-" |
| Communication | `communicationState` | CONNECTED / DEGRADED / ISOLATED / OFFLINE badge |
| Neighbors | `neighbors` | count and ids |
| Skill | `activeSkill` | name + status from `skills[]`, or "none" |
| Knowledge | `localKnowledgeCount`, `knownPois`, `verifiedPois` | observations held, POIs known/verified by this node |
| Coverage | `searchedCells` | "{n} of 320 cells" (`searchGrid.nx * ny`) |
| Objective / action | `currentObjective`, `currentAction` | labels |

### 20.d "Judge facts" list (talking points; render as a collapsible card)

1. **All 6 UAVs are identical** (same platform, sensor and radio from `meta.uavSpec`); no roles, no leader.
2. **No global communications**: each UAV knows only its own observations; data and skills travel only over RF links of the current graph (`links[]` with `connected:true`); partitions really isolate nodes (5 partitions in seed 1002).
3. **Radio is physical**: range, horizon from altitude, terrain line of sight and jamming zones decide each link; isolated UAVs climb to extend their horizon.
4. **Deterministic**: the same seed always produces the same run and the same replay (no wall-clock randomness); the demo plays a recorded run.
5. **A skill changes behaviour, measurably**: `adaptive_search_spacing` changes search-cell selection (skips cells peers covered or claimed in the last 150 s, keeps 80 km spacing). Measured, seed 1002: with skills redundancy ratio 0.639 (565 redundant of 884 cell marks) and the mission succeeds at 8520 s; without skills 0.781 (993 of 1272) and the mission FAILS at 28800 s with 5/6 POIs verified. Numbers come from `stats` (skills) and the `--no-skills` run; reproduce with the `--compare` command below.
6. **What "skill" means here**: a small versioned behaviour package (name, version, source node, utility, confidence, trigger) that one UAV learns from its own experience (repeatedly searching cells a peer had already covered), shares over RF links, and peers validate and adopt before using; transfer takes `skillTransferSecondsAtFullBandwidth` (60 s) at full bandwidth, so weak links are slower.
7. **Why not real reinforcement learning**: out of scope for this demo. The learning is a rule-triggered behaviour change with a measurable effect, not a trained policy; the contribution shown is decentralised skill sharing under realistic communication limits.

`--compare` for seed 1002 (stdout JSON, key fields):

```
PYTHONPATH="packages/mission:packages/sim" python -m archipelago_mission --seed 1002 --compare
with_skills:         status SUCCESS, elapsedTime 8520.0, verifiedPois 6/6, fleetKnowledgeCoverage 0.972, redundancyRatio 0.639, skillsLearned 2, skillTransfers 4, skillAdoptions 4, partitions 5, dataSyncs 1520, finalSkillHolders 6
baseline_no_skills:  status FAILED,  elapsedTime 28800.0, verifiedPois 5/6, fleetKnowledgeCoverage 1.0 (5 UAVs left), redundancyRatio 0.781, skillsLearned 0, partitions 4, dataSyncs 6995, finalSkillHolders 0
```
(PowerShell: set `$env:PYTHONPATH="packages/mission;packages/sim"` first.) In the UI take the with-skills numbers from the replay `stats`; the baseline numbers are static facts that may be shown as text next to them (they are not in the replay file).

### 20.e Layout suggestion

- Fleet header chip "6 identical UAVs - 140 m/s - 40 km sensor - 40 km radio" (from `meta.uavSpec`) opening a right-side drawer with the spec card (20.b, grouped as Platform, Sensor, Radio, Autonomy, Mission rules).
- Node inspector (19.g) gets a "Platform spec" link and a live block (20.c); the link inspector (19.g) stays separate.
- "Judge facts" lives as a collapsible card at the bottom of the same drawer, with the measured skill effect (redundancy ratio 0.639 vs 0.781, SUCCESS vs FAILED) shown as two bars.
- The spec drawer is static: opening it must not pause the playback unless the user pauses.

### 20.f Acceptance checklist (spec panel)

- [ ] Spec card is generated from `meta.uavSpec`, `meta.rfModel`, `meta.missionRules`; changing a value in the JSON changes the card (no hardcoded numbers).
- [ ] Shows cruise speed in m/s and km/h, cruise/max altitude, climb rate, sensor type and radius in km, degraded radius (radius x factor), detection text, search cell size.
- [ ] Shows comm nominal/extended range, RF horizon at cruise and at max altitude in km, state thresholds, connect threshold, update interval, objective priority list, learned skills, mission rules, POI and disruption types.
- [ ] Reachable from the fleet header and from the node inspector.
- [ ] Per-UAV live block updates with the playback: altitude, speed, sensorState with effective radius (shows 25.6 km while DEGRADED), communicationState, health/status, activeSkill, localKnowledgeCount, searchedCells, neighbors.
- [ ] Judge facts list present, including the baseline vs skills comparison and the `--compare` command for seed 1002.
- [ ] Failed UAV (not in seed 1002) shows status FAILED and sensor OFFLINE without errors.
